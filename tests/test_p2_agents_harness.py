"""The agent P2's harness (docs/p2_agents_design.md §3 to §5; ``agents.py`` of the package).

In-process on ``tests/p2_support.FakeTools`` with scripted responders standing in for the
model, each guard rail with its negative control:

* the configuration: ``p2_agents.yaml`` extends ``p2.yaml`` (the procedural digest and the
  frozen record unchanged; the agent arm's digest differs), the §3.1 allow-list is the
  configured one, the jail document carries the roles and their prompts' texts;
* the allow-list is enforced in the view (a call outside it is refused and recorded; one
  inside runs); a QC-flagged sensor is never reinstated (an unflagged one may be excluded);
* the projection redacts every free-text argument and every non-token string, and a claim
  planted in a role's reason and in its text reaches ``messages.jsonl`` only: neither
  ``state.json`` nor the verifier's brief carries it (the control: with the redaction
  disabled the projection carries it); ``stored`` fetches a full output;
* a finding is checked: an uncited call, a fabricated value, a wrong unit, a missing unit
  on a quantity, a round-2 claim in round 1 are refused; a well-formed one is accepted;
* a verdict is checked: a non-admitted alternative, a hold-out citing a non-validate call,
  and a fail against a non-structural cause on a passed hold-out alone (D-1) are refused;
* code concludes: pass -> the leading admitted claim; last-round fail with ``none`` ->
  ``none``, with another alternative -> abstain; abstain -> abstain; verifier off -> the
  leading claim, or ``none`` on a standing null;
* the coordinator routes on the typed state and is the only writer of routing entries;
* the gateway accepts a role's turn and refuses a foreign prompt, foreign tools or a
  history that does not start with the brief;
* one jailed run of the arm, offline, through the runner.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from state.task_state import TaskState
from tests.p2_support import FakeTools
from tools.workflow_config import (
    WORKFLOW_CONFIG_DIR,
    load_p2,
    load_p2_agent_prompts,
    sandbox_config,
)
from workflows.p2_multi_agent import agents, evidence, messages
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]
AGENTS_YAML = WORKFLOW_CONFIG_DIR / "p2_agents.yaml"
PILOT_CONFIG_SHA256 = "cf59bcbb555aab376dd53a0a3ce7d8d91e3b453df8165879c39f9163dcc2f404"
PLANTED = "the pH probe was replaced by the night shift on day 40"

ALLOW_LIST = {  # docs/p2_agents_design.md §3.1, the table
    "data_quality": {
        "data_qc",
        "set_sensor_status",
        "inspect_record",
        "residual_diag",
        "simulate",
        "declared_background",
    },
    "influent": {"inspect_record", "mass_balance", "feed_loads", "simulate", "declared_background"},
    "identifiability": {
        "describe_model",
        "gsa_morris",
        "gsa_sobol",
        "fisher_info",
        "profile_likelihood",
        "residual_diag",
    },
    "calibration": {
        "residual_diag",
        "simulate",
        "fit_lsq",
        "fit_de",
        "fit_cmaes",
        "bayes_mcmc",
        "declared_background",
    },
    "design": {"voi_assay", "request_assay"},
    "verification": {
        "inspect_record",
        "residual_diag",
        "simulate",
        "declared_background",
        "validate",
    },
}


def _cfg() -> dict[str, Any]:
    return json.loads(json.dumps(sandbox_config(load_p2(AGENTS_YAML))))


def _install(monkeypatch, fake: FakeTools) -> None:
    monkeypatch.setattr(wf, "tools", fake)
    monkeypatch.setattr(agents, "tools", fake)


class Script:
    """A scripted role: a list of turns, each a list of blocks; ``LAST`` is the last call index."""

    def __init__(self, turns: list[list[dict[str, Any]]]) -> None:
        """Set up."""
        self.turns = turns
        self.i = 0
        self.last: int | None = None
        self.briefs: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        history = request["messages"]
        if len(history) == 1:
            self.briefs.append(json.loads(history[0]["content"]))
        last = history[-1]["content"]
        if isinstance(last, list):
            for block in last:
                if block.get("type") == "tool_result" and not block.get("is_error"):
                    payload = json.loads(block["content"])
                    if "call_index" in payload:
                        self.last = int(payload["call_index"])
        blocks = self.turns[min(self.i, len(self.turns) - 1)]
        self.i += 1
        content = []
        for n, b in enumerate(blocks):
            b = json.loads(
                json.dumps(b).replace('"LAST"', str(self.last if self.last is not None else -1))
            )
            if b.get("type") == "text":
                content.append(b)
            else:
                content.append({"type": "tool_use", "id": f"u{self.i}-{n}", **b})
        return {
            "response": {"content": content, "stop_reason": "tool_use", "usage": {}},
            "status": {},
        }


def _finding(role: str, **kw: Any) -> dict[str, Any]:
    base = {
        "data_quality": {"claim": "no_claim", "confidence": "low", "evidence": []},
        "influent": {"claim": "no_claim", "confidence": "low", "evidence": []},
        "identifiability": {"subset": [], "kinetic_update_allowed": False, "evidence": []},
        "calibration": {"claim": "no_claim", "confidence": "low", "evidence": []},
        "verification": {"round": 1, "verdict": "pass", "evidence": []},
    }[role]
    return {**base, **kw}


def _emit(role: str, **kw: Any) -> dict[str, Any]:
    return {"name": "emit_finding", "input": {"finding": _finding(role, **kw)}}


def _run(
    monkeypatch,
    scripts: dict[str, Script],
    fake: FakeTools | None = None,
    cfg: dict[str, Any] | None = None,
) -> tuple[agents.AgentRun, FakeTools]:
    fake = fake or FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    cfg = cfg or _cfg()
    run = agents.AgentRun(
        cfg, responder=lambda role: scripts.get(role) or agents.OfflineModel(role)
    )
    run.run()
    return run, fake


def _state(fake: FakeTools) -> dict[str, Any]:
    return json.loads(fake.run.outputs["state.json"])


# ------------------------------------------------------------------ the configuration


def test_the_agents_configuration_extends_the_procedural_one_and_leaves_its_digest_alone(
    tmp_path,
):
    from scripts.p2_pilot import pilot_config_digest
    from tools.p2_live import check_p2_frozen, config_digest

    base, arm = load_p2(), load_p2(AGENTS_YAML)
    assert pilot_config_digest() == PILOT_CONFIG_SHA256  # the procedural arm's, unchanged
    assert config_digest(arm) != config_digest(base)  # the agent arm's binds its block
    assert base.model_dump(mode="json") == {
        **arm.model_dump(mode="json"),
        "workflow_version": base.workflow_version,
    }
    assert arm.frozen == base.frozen and arm.agents is not None and base.agents is None
    check_p2_frozen(arm)
    # the §3.1 allow-list, as configured, and `stored` / `emit_finding` as actions
    assert {r: set(s.tools) for r, s in arm.agents.roles.items()} == ALLOW_LIST
    assert arm.agents.rounds == 2
    doc = sandbox_config(arm)
    # the caps stay on the privileged side, as p2.yaml's (J3); the seed base is the jail's
    assert set(doc["agents"]) == {"roles", "prompts", "projection", "rounds", "seeds"}
    assert doc["agents"]["seeds"] == {"base": arm.agents.seeds.base}
    prompts = load_p2_agent_prompts(arm)
    assert doc["agents"]["prompts"] == {r: p["text"] for r, p in prompts.items()}
    assert "tool_size_ceilings" in doc
    # the P1 prompt rule: no scenario id, no P0 rule id in a role's prompt
    for role, p in prompts.items():
        assert not re.search(r"\bS\d-\d\d\b", p["text"]), role
        assert not re.search(r"\bR[1-5][ab]?\b", p["text"]), role
    # the negative control (a real one, J9): a configuration extending a file that itself
    # extends is refused by load_p2; the files are copied beside each other, since
    # `extends` resolves beside the configuration
    import shutil

    here = tmp_path / "configs"
    here.mkdir()
    for name in ("p2.yaml", "p2_agents.yaml"):
        shutil.copy2(WORKFLOW_CONFIG_DIR / name, here / name)
    (here / "chain.yaml").write_text("extends: p2_agents.yaml\nworkflow_version: x\n")
    with pytest.raises(ValueError, match="extends names a file that is not a plain"):
        load_p2(here / "chain.yaml")


def test_each_role_is_offered_its_tools_stored_and_its_typed_finding():
    arm = load_p2(AGENTS_YAML)
    for role, spec in arm.agents.roles.items():
        specs = agents.role_tool_specs(role, list(spec.tools))
        names = [s["name"] for s in specs]
        assert set(names) == set(spec.tools) | {"stored", "emit_finding"}
        schema = specs[-1]["input_schema"]["properties"]["finding"]
        assert schema == messages.FINDINGS[role].model_json_schema()
    with pytest.raises(ValueError, match="no specification"):
        agents.role_tool_specs("design", ["conclude"])


# ------------------------------------------------------------------ the loop and the views


def test_the_offline_arm_runs_end_to_end_and_writes_a_valid_record(monkeypatch):
    _, fake = _run(monkeypatch, {})
    state = _state(fake)
    TaskState.model_validate(state)
    report = json.loads(fake.run.outputs["report.json"])
    assert report["arm"] == "agents" and report["completed"]
    assert report["outcome"] == "abstain"  # the scripted verifier never argues: it abstains
    assert [e["to"] for e in report["routing"]][:1] == ["data_quality"]  # QC first
    assert report["routing"][-1]["to"] == "verification"
    assert all(
        e["reason"] in ("qc_first", "null_failed", "null_stands", "conflict", "verify")
        for e in report["routing"]
    )
    kinds = [json.loads(x)["kind"] for x in fake.run.outputs["messages.jsonl"].splitlines()]
    assert kinds.count("decision") == len(report["routing"])
    assert "verdict" in kinds
    # the code steps' calls and the roles' calls are one record
    assert state["actions"] and state["plan"]["sizes"]["model_turns"] == 2 * len(
        report["role_runs"]
    )
    assert state["annotations"][1].startswith("arm: agents")


def test_a_call_outside_the_allow_list_is_refused_and_one_inside_runs(monkeypatch):
    dq = Script(
        [
            [{"name": "fit_lsq", "input": {"parameters": ["k_m_ac"]}}],  # not data quality's
            [{"name": "data_qc", "input": {}}],
            [_emit("data_quality")],
        ]
    )
    _, fake = _run(monkeypatch, {"data_quality": dq})
    report = json.loads(fake.run.outputs["report.json"])
    assert report["refusals"] == [{"role": "data_quality", "step": "fit_lsq", "name": "fit_lsq"}]
    state = _state(fake)
    assert not any(
        a["name"] == "fit_lsq" and a["step"].startswith("data_quality.") for a in state["actions"]
    )
    state = _state(fake)
    refused = [f for f in state["tool_failures"] if f["name"] == "p2.data_quality.refused"]
    assert refused and "not on the data_quality role's list" in refused[0]["message"]
    assert any(
        a["name"] == "data_qc" and a["step"] == "data_quality.data_qc" for a in state["actions"]
    )


def test_a_qc_flagged_sensor_is_never_reinstated(monkeypatch):
    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    ws = run.ws
    ws.series["ph"].flags = ["drift"]  # as the quality checks would flag it
    view = agents.RoleView("data_quality", ALLOW_LIST["data_quality"], run.rec)
    for status, in_obj in (("ok", True), ("ok", False), ("quarantined", True)):
        with pytest.raises(agents.ActionError, match=r"never set ok|never enters"):
            ws.t_status(
                view, {"sensor": "ph", "status": status, "in_objective": in_obj, "reason": "x"}
            )
    out = ws.t_status(
        view, {"sensor": "ph", "status": "excluded", "in_objective": False, "reason": "x"}
    )
    assert out["status"] == "excluded" and "ph" not in out["objective_now"]
    # the negative control: an unflagged sensor may be set ok and quarantined
    out = ws.t_status(
        view,
        {
            "sensor": "tan",
            "status": "quarantined",
            "in_objective": True,
            "quarantine": [[10.0, 20.0]],
            "reason": "x",
        },
    )
    assert out["quarantined_windows"] == [[10.0, 20.0]] and "tan" in out["objective_now"]
    # the window is [start, end): days 10..19 dropped, day 20 kept (J13)
    tan = ws.series["tan"]
    dropped = np.isnan(tan.value) & (tan.t >= 9.0) & (tan.t <= 21.0)
    assert sorted(tan.t[dropped].tolist()) == [float(d) for d in range(10, 20)]
    with pytest.raises(agents.ActionError, match="hold-out"):
        ws.t_status(
            view,
            {
                "sensor": "tan",
                "status": "ok",
                "in_objective": True,
                "quarantine": [[10.0, 199.0]],
                "reason": "x",
            },
        )
    # the reason never reaches the state: its length is templated into the note
    state = run.build_state(False)
    assert (
        state["data_quality"]["ph"]["notes"]
        == "status excluded set by data_quality (reason of 1 chars, logged)"
    )


# ------------------------------------------------------------------ the projection


def test_a_planted_claim_reaches_messages_only_and_the_projection_redacts_it(monkeypatch):
    dq = Script(
        [
            [
                {"type": "text", "text": f"Assessment: {PLANTED}."},
                {
                    "name": "set_sensor_status",
                    "input": {
                        "sensor": "ph",
                        "status": "excluded",
                        "in_objective": False,
                        "reason": PLANTED,
                    },
                },
            ],
            [{"name": "data_qc", "input": {}}],
            [
                _emit(
                    "data_quality",
                    claim="none",
                    evidence=[
                        {
                            "label": "none",
                            "rule": "sensor",
                            "calls": ["LAST"],
                            "values": {},
                            "units": {},
                        }
                    ],
                )
            ],
        ]
    )
    # the claim planted in a tool-argument string of a REGISTRY call (J8): a fit's
    # bounds_justification enters args_by_index, so the projection must redact it
    fit = {
        "name": "fit_lsq",
        "input": {
            "parameters": ["k_m_ac"],
            "bounds": {"k_m_ac": [0.5, 2.0]},
            "bounds_justification": PLANTED,
            "n_starts": 1,
            "max_nfev_per_start": 10,
        },
    }
    cal = Script([[fit], [_emit("calibration")]])
    verifier = Script([[{"name": "declared_background", "input": {}}], [_emit("verification")]])
    _, fake = _run(monkeypatch, {"data_quality": dq, "calibration": cal, "verification": verifier})
    state_text = fake.run.outputs["state.json"]
    assert PLANTED not in state_text
    # the assessment, the sensor reason and the justification, free text, live in
    # messages.jsonl as the roles' own messages (J6)
    lines = [json.loads(x) for x in fake.run.outputs["messages.jsonl"].splitlines()]
    reasons = [m for m in lines if m["step"] == "set_sensor_status.reason"]
    assert reasons and reasons[0]["from_role"] == "data_quality"
    assert reasons[0]["body"] == {
        "sensor": "ph",
        "status": "excluded",
        "in_objective": False,
        "reason": PLANTED,
    }
    justified = [m for m in lines if m["step"] == "bounds_justification"]
    assert justified and justified[0]["from_role"] == "calibration"
    assert justified[0]["body"]["justification"] == PLANTED
    assert justified[0]["body"]["bounds"] == {"k_m_ac": [0.5, 2.0]}
    assert any(m["step"] == "assessment.1" and PLANTED in m["body"]["text"] for m in lines)
    brief = verifier.briefs[0]
    assert PLANTED not in json.dumps(brief)
    entry = [
        e for e in brief["projected_log"] if e["tool"] == "data_qc" and e["role"] == "data_quality"
    ][-1]
    assert entry["args"] == {} and entry["outcome"] == "ok" and "output" in entry
    fit_entry = [e for e in brief["projected_log"] if e["tool"] == "fit_lsq"][-1]
    assert fit_entry["role"] == "calibration"
    assert fit_entry["args"]["bounds_justification"] == agents.REDACTED_MARK
    assert fit_entry["args"]["bounds"] == {"k_m_ac": [0.5, 2.0]}
    # the redaction: the declared free-text field, and any non-token string, at any depth
    # (three deep too)
    args = {
        "sensor": "ph",
        "status": "excluded",
        "reason": PLANTED,
        "nested": {"note": "two words", "k": "x2", "deeper": {"deepest": [PLANTED, "x3"]}},
    }
    assert agents.redact("set_sensor_status", args) == {
        "sensor": "ph",
        "status": "excluded",
        "reason": agents.REDACTED_MARK,
        "nested": {
            "note": agents.REDACTED_MARK,
            "k": "x2",
            "deeper": {"deepest": [agents.REDACTED_MARK, "x3"]},
        },
    }
    assert agents.redact("fit_lsq", {"bounds_justification": "x2"}) == {
        "bounds_justification": agents.REDACTED_MARK
    }
    # the negative control, on the real channel: with the redaction replaced by the
    # identity, the verifier's projection carries the planted justification
    rec = agents.Recorder()
    rec.actions.append(
        {
            "step": "data_quality.set_sensor_status",
            "name": "set_sensor_status",
            "version": "",
            "args_hash": "",
            "seq": 0,
            "call_index": 0,
            "outcome": "ok",
            "detail": "",
        }
    )
    projected = agents.project(rec, {0: args}, 200, 12)
    assert PLANTED not in json.dumps(projected)
    monkeypatch.setattr(agents, "redact", lambda name, a: a)
    assert PLANTED in json.dumps(agents.project(rec, {0: args}, 200, 12))
    cal2 = Script([[fit], [_emit("calibration")]])
    verifier2 = Script([[{"name": "declared_background", "input": {}}], [_emit("verification")]])
    _run(monkeypatch, {"calibration": cal2, "verification": verifier2})
    unredacted = [e for e in verifier2.briefs[0]["projected_log"] if e["tool"] == "fit_lsq"][-1]
    assert unredacted["args"]["bounds_justification"] == PLANTED


def test_stored_fetches_a_full_output_and_the_projection_cuts_arrays(monkeypatch):
    fake = FakeTools("B", "B")
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    ws = run.ws
    view = agents.RoleView("influent", ALLOW_LIST["influent"], run.rec)
    out = ws.t_feed_loads(view, {})
    index = out["call_index"]
    full = ws.stored({"call_index": index}, "influent")
    assert full["call_index"] == index and "t" in full["result"]
    with pytest.raises(agents.ActionError, match="no stored output"):
        ws.stored({"call_index": 10**6}, "influent")
    assert agents.cut_points(list(range(1000)), 200) == [
        agents.compact(v, 200) for v in range(0, 1000, 5)
    ]
    projected = agents.project(run.rec, ws.args_by_index, 50, 12)
    entry = next(e for e in projected if e["call_index"] == index)
    assert isinstance(entry["output"], dict)


# ------------------------------------------------------------------ the findings


def test_a_finding_is_checked_for_cited_calls_values_units_and_round(monkeypatch):
    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    ws = run.ws
    view = agents.RoleView("data_quality", ALLOW_LIST["data_quality"], run.rec)
    out = ws.t_simulate(view, {})
    index = out["call_index"]
    produced = {k: v for k, v in run.rec.produced[index].items()}
    assert "mean_z" in produced and "mean_predicted" in produced
    mean_z = next(v for v, unit, sensor in produced["mean_z"] if sensor == "ph")
    # a quantity with a real unit (ph's is "-"): tan's mean prediction, in its sensor's unit
    mean_pred, pred_unit = next(
        (v, unit) for v, unit, sensor in produced["mean_predicted"] if sensor == "tan"
    )
    assert pred_unit == "mg/L"
    ok = {
        "claim": "sensor",
        "channel": "ph",
        "confidence": "high",
        "evidence": [
            {
                "label": "sensor",
                "rule": "sensor",
                "calls": [index],
                "values": {"mean_z": mean_z, "mean_predicted": mean_pred},
                "units": {"mean_predicted": "mg/L"},
            }
        ],
    }
    accepted = agents.check_finding(ws, "data_quality", ok, 1)
    assert accepted.claim == "sensor"
    assert agents.evidence_items(accepted)[0]["statement"].startswith("sensor: points to sensor")

    def refused(payload: dict[str, Any], match: str, round_: int = 1) -> None:
        with pytest.raises(agents.ActionError, match=match):
            agents.check_finding(ws, "data_quality", payload, round_)

    item = ok["evidence"][0]
    refused({**ok, "evidence": [{**item, "calls": [10**6]}]}, "no call of this run that returned")
    refused(
        {
            **ok,
            "evidence": [{**item, "values": {"mean_z": mean_z + 1.0, "mean_predicted": mean_pred}}],
        },
        "not what the cited calls produced",
    )
    refused(
        {**ok, "evidence": [{**item, "values": {"rmse": 1.0}, "units": {}}]},
        "no cited call produced",
    )
    refused({**ok, "evidence": [{**item, "units": {"mean_predicted": "kg/m3"}}]}, "has unit")
    refused(
        {**ok, "evidence": [{**item, "units": {}}]}, "give its unit"
    )  # a quantity needs its unit
    refused({**ok, "channel": "nonsense"}, "no sensor")
    refused({**ok, "claim": "the probe drifted"}, "finding:")
    cal = {"claim": "structural", "confidence": "low", "evidence": []}
    with pytest.raises(agents.ActionError, match="round-2"):
        agents.check_finding(ws, "calibration", cal, 1)
    assert agents.check_finding(ws, "calibration", cal, 2).claim == "structural"
    with pytest.raises(agents.ActionError, match="not narrowed"):
        agents.check_finding(
            ws,
            "calibration",
            {"claim": "no_claim", "confidence": "low", "bounds_narrowed": {"k_m_ac": [0.5, 2.0]}},
            1,
        )


def test_a_verdict_is_checked_for_its_alternative_its_hold_out_and_d1(monkeypatch):
    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    ws = run.ws
    view = agents.RoleView("verification", ALLOW_LIST["verification"], run.rec)
    sim = ws.t_simulate(view, {})
    val = ws.t_validate(view, {"prediction": sim["call_index"]})
    v_index = val["call_index"]
    failed = val["result"]["holdout_failed"]
    admitted = evidence.admit_agent(run.lab, run.base.table, run.base.signatures)["admitted"]
    passing = {"round": 1, "verdict": "pass", "holdout": {"failed": failed, "call": v_index}}
    assert agents.check_finding(ws, "verification", passing, 1).holdout.call == v_index
    with pytest.raises(agents.ActionError, match="no validate call"):
        agents.check_finding(
            ws,
            "verification",
            {**passing, "holdout": {"failed": failed, "call": sim["call_index"]}},
            1,
        )
    with pytest.raises(agents.ActionError, match="not what the validate call found"):
        agents.check_finding(
            ws, "verification", {**passing, "holdout": {"failed": not failed, "call": v_index}}, 1
        )
    cited = [
        {"label": "none", "rule": "holdout_failed", "calls": [v_index], "values": {}, "units": {}}
    ]
    not_admitted = next(x for x in ("influent", "structural", "sensor") if x not in admitted)
    with pytest.raises(agents.ActionError, match="not admitted"):
        agents.check_finding(
            ws,
            "verification",
            {"round": 1, "verdict": "fail", "alternative": not_admitted, "evidence": cited},
            1,
        )
    # a fail that cites the validate call states its result (J2): with it, `none` is admitted
    with_holdout = {"holdout": {"failed": failed, "call": v_index}}
    assert (
        agents.check_finding(
            ws,
            "verification",
            {
                "round": 1,
                "verdict": "fail",
                "alternative": "none",
                "evidence": cited,
                **with_holdout,
            },
            1,
        ).alternative
        == "none"
    )
    # D-1: a fail against a non-structural cause whose only evidence is a passed hold-out.
    # The case is built, not hoped for (J2): every label is admitted (the admission is the
    # evidence module's, tested there) and the validate call's recorded result is a pass
    _admit_everything(monkeypatch)
    run.rec.produced[v_index]["holdout_failed"] = [(False, "-", None)]
    passed = {"failed": False, "call": v_index}
    fail_sensor = {"round": 1, "verdict": "fail", "alternative": "sensor", "evidence": cited}
    with pytest.raises(agents.ActionError, match="D-1"):
        agents.check_finding(ws, "verification", {**fail_sensor, "holdout": passed}, 1)
    # a fail citing a validate call may not leave `holdout` out ...
    with pytest.raises(agents.ActionError, match="states its result in `holdout`"):
        agents.check_finding(ws, "verification", fail_sensor, 1)
    # ... nor name a validate call the evidence does not cite
    sim2 = ws.t_simulate(view, {})
    v2 = ws.t_validate(view, {"prediction": sim2["call_index"]})["call_index"]
    run.rec.produced[v2]["holdout_failed"] = [(False, "-", None)]
    with pytest.raises(agents.ActionError, match="not one of the cited validate calls"):
        agents.check_finding(
            ws, "verification", {**fail_sensor, "holdout": {"failed": False, "call": v2}}, 1
        )
    # the controls: the same fail against `structural` or `none` passes D-1; a fail against
    # sensor with a FAILED hold-out passes; one with other evidence beside the hold-out passes
    for alternative in ("structural", "none"):
        ok = {**fail_sensor, "alternative": alternative, "holdout": passed}
        assert agents.check_finding(ws, "verification", ok, 1).alternative == alternative
    run.rec.produced[v_index]["holdout_failed"] = [(True, "-", None)]
    failed_holdout = {**fail_sensor, "holdout": {"failed": True, "call": v_index}}
    assert agents.check_finding(ws, "verification", failed_holdout, 1).holdout.failed
    run.rec.produced[v_index]["holdout_failed"] = [(False, "-", None)]
    more = [
        *cited,
        {
            "label": "sensor",
            "rule": "sensor",
            "calls": [sim["call_index"]],
            "values": {},
            "units": {},
        },
    ]
    assert (
        agents.check_finding(
            ws, "verification", {**fail_sensor, "holdout": passed, "evidence": more}, 1
        ).alternative
        == "sensor"
    )


# ------------------------------------------------------------------ the conclusion


def _admit_everything(monkeypatch) -> None:
    """The admission is the evidence module's (tested there); here every label is admitted."""
    labels = ["sensor", "influent", "state", "parameter", "structural"]
    monkeypatch.setattr(
        agents.evidence,
        "admit_agent",
        lambda lab, table, signatures: {"admitted": labels, "rejected": []},
    )


def _sensor_claim(ws_index: str = "LAST") -> dict[str, Any]:
    return {
        "claim": "sensor",
        "channel": "ph",
        "confidence": "high",
        "evidence": [
            {"label": "sensor", "rule": "sensor", "calls": [ws_index], "values": {}, "units": {}}
        ],
    }


@pytest.mark.parametrize(
    ("verdict", "expected_label", "expected_outcome"),
    [
        ({"verdict": "pass"}, "sensor", "sensor"),
        ({"verdict": "fail", "alternative": "none"}, "none", "none"),
        ({"verdict": "fail", "alternative": "structural"}, "abstain", "abstain"),
        ({"verdict": "abstain"}, "abstain", "abstain"),
    ],
)
def test_code_concludes_from_the_verdict(monkeypatch, verdict, expected_label, expected_outcome):
    dq = Script([[{"name": "simulate", "input": {}}], [_emit("data_quality", **_sensor_claim())]])
    extra = {}
    if verdict.get("verdict") == "fail":
        extra = {
            "evidence": [
                {
                    "label": verdict["alternative"],
                    "rule": "sensor",
                    "calls": ["LAST"],
                    "values": {},
                    "units": {},
                }
            ]
        }
    ver = Script([[{"name": "simulate", "input": {}}], [_emit("verification", **verdict, **extra)]])
    _admit_everything(monkeypatch)
    _, fake = _run(monkeypatch, {"data_quality": dq, "verification": ver})
    report = json.loads(fake.run.outputs["report.json"])
    assert (report["label"], report["outcome"]) == (expected_label, expected_outcome), report[
        "verdict"
    ]
    if expected_label == "sensor":
        assert report["verdict"]["leading_role"] == "data_quality"
        assert _state(fake)["classification"]["flag_sensor"] == "ph"


def test_with_the_verifier_off_code_concludes_the_leading_claim_or_none(monkeypatch):
    cfg = _cfg()
    cfg["ablation"]["verifier"] = False
    dq = Script([[{"name": "simulate", "input": {}}], [_emit("data_quality", **_sensor_claim())]])
    # the negative control first: with the real admission (no S1 signature on this fake cell)
    # the sensor claim is not admitted and nothing concludes it
    _, fake0 = _run(monkeypatch, {"data_quality": dq}, cfg=cfg)
    assert json.loads(fake0.run.outputs["report.json"])["label"] != "sensor"
    _admit_everything(monkeypatch)
    dq = Script([[{"name": "simulate", "input": {}}], [_emit("data_quality", **_sensor_claim())]])
    _, fake = _run(monkeypatch, {"data_quality": dq}, cfg=cfg)
    report = json.loads(fake.run.outputs["report.json"])
    assert report["verdicts"] == [] and all(e["to"] != "verification" for e in report["routing"])
    assert report["label"] == "sensor" and report["rule"] == "verifier_off:leading_claim"
    # a standing null with no claim concludes none; a failed one with no admitted claim abstains
    _, fake2 = _run(monkeypatch, {}, fake=FakeTools("B", "B"), cfg=cfg)
    report2 = json.loads(fake2.run.outputs["report.json"])
    table = report2["null_table"]
    if table and table["null_rejected"]:
        assert report2["label"] == "abstain"
    else:
        assert report2["label"] == "none" and report2["rule"] == "verifier_off:null_stands"


# ------------------------------------------------------------------ the coordinator


def test_the_coordinator_routes_on_the_typed_state_and_writes_the_entries(monkeypatch):
    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    table = run.base.table
    assert table and table["null_rejected"] and table["NS"]
    assert run.coordinator.specialists_for() == ["identifiability", "calibration"]
    run.base.table = {**table, "NB": True}
    assert run.coordinator.specialists_for()[0] == "influent"
    run.base.table = {**table, "null_rejected": False, "NB": False, "NM": False, "NS": False}
    assert run.coordinator.specialists_for() == ["influent", "identifiability", "calibration"]
    # a conflict between two findings routes to design
    sensor = messages.SensorFinding(claim="sensor", channel="ph", confidence="high")
    param = messages.CalFinding(claim="parameter", confidence="high")
    assert run.coordinator.conflict({"data_quality": sensor, "calibration": param}) == (
        "parameter",
        "sensor",
    )
    assert run.coordinator.conflict({"data_quality": sensor}) is None
    entry = run.coordinator.route(1, "design", "conflict", {"evaluations": 10, "assays": 1})
    assert entry["grant"] == {"evaluations": 10, "assays": 1}
    logged = [m for m in run.log.messages if m.kind == "decision" and m.from_role == "coordination"]
    assert logged and logged[-1].body == entry
    with pytest.raises(Exception, match="validation error"):
        run.coordinator.route(1, "coordination", "conflict", {})  # never to itself


# ------------------------------------------------------------------ the gateway


def test_the_gateway_accepts_a_roles_turn_and_refuses_foreign_ones(tmp_path):
    from tools.llm import ModelError, ScriptedClient
    from tools.p2_live import P2AgentGateway, P2Gateway

    arm = load_p2(AGENTS_YAML)
    gw = P2Gateway.for_config(
        arm, ScriptedClient(lambda p: {"content": [{"type": "text", "text": "ok"}]}), tmp_path
    )
    assert isinstance(gw, P2AgentGateway)
    # the agent arm's caps are its own block's, the lead's Q8 (J3): the gateway takes
    # them, the procedural freeze keeps p2.yaml's, and an approval binds them through
    # the configuration digest
    from tools.p2_live import config_digest, run_caps

    base = load_p2()
    assert (gw.max_turns, gw.max_total_tokens, gw.max_usd) == (200, 10_000_000, 0.5)
    assert run_caps(arm) == arm.agents.caps and run_caps(base) == base.caps
    assert (base.caps.max_requests, arm.caps.max_requests) == (60, 60)  # p2.yaml's, untouched
    assert sum(r.turns for r in arm.agents.roles.values()) <= arm.agents.caps.max_requests
    tightened = arm.model_copy(
        update={
            "agents": arm.agents.model_copy(
                update={"caps": arm.agents.caps.model_copy(update={"max_requests": 150})}
            )
        }
    )
    assert config_digest(tightened) != config_digest(arm)
    prompts = load_p2_agent_prompts(arm)
    specs = agents.role_tool_specs("calibration", list(arm.agents.roles["calibration"].tools))
    request = {
        "system": prompts["calibration"]["text"],
        "tools": specs,
        "messages": [
            {"role": "user", "content": "the brief"},
            {"role": "assistant", "content": [{"type": "text", "text": "thinking"}]},
            {"role": "user", "content": [{"type": "text", "text": "go on"}]},
        ],
    }
    assert gw.decision_of(request) == ("agent.calibration", "calibration")
    out = gw.complete(request)
    assert (
        out["response"]["content"][0]["text"] == "ok" and gw.by_role["calibration"]["requests"] == 1
    )
    for bad, match in (
        (
            {**request, "system": prompts["calibration"]["text"] + "\nBe decisive."},
            "not one of the agent",
        ),
        ({**request, "tools": specs[:-1]}, "not the role's"),
        (
            {
                **request,
                "tools": agents.role_tool_specs("design", list(arm.agents.roles["design"].tools)),
            },
            "not the role's",
        ),
        (
            {**request, "messages": [{"role": "assistant", "content": "hi"}]},
            "starts with the role's brief",
        ),
        ({**request, "extra": 1}, "only system, messages and tools"),
    ):
        with pytest.raises(ModelError, match=match):
            gw.decision_of(bad)
    # the procedural configuration still gets the decision gateway
    plain = P2Gateway.for_config(
        load_p2(), ScriptedClient(lambda p: {"content": []}), tmp_path / "plain"
    )
    assert type(plain) is P2Gateway


# ------------------------------------------------------------------ the review of 1486cfb


SEEDED = (
    "gsa_morris",
    "gsa_sobol",
    "profile_likelihood",
    "fit_lsq",
    "fit_de",
    "fit_cmaes",
    "bayes_mcmc",
    "voi_assay",
)
"""Every handler that seeds its registry call (rule 4)."""


def _use(name: str, inp: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": f"u-{name}", "name": name, "input": inp}


def _content(result: dict[str, Any]) -> dict[str, Any]:
    return json.loads(result["content"])


def test_every_handler_runs_through_execute_and_every_seeded_call_is_seeded(monkeypatch):
    """J0 / J11: no handler dies on the registry's shapes; a seeded call carries base + index."""
    fake = FakeTools("B", "B", evals=5000, offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    cfg = _cfg()
    run = agents.AgentRun(cfg)
    run.code_steps()
    ws = run.ws
    base = int(cfg["agents"]["seeds"]["base"])
    every = sorted(agents.registry_tool_specs())
    assert set(SEEDED) <= set(every)
    # one agent holding every tool (the allow-lists are tested elsewhere), a wide grant
    agent = agents.RoleAgent(
        "calibration",
        ws,
        lambda r: None,
        round_=1,
        grant={"evaluations": 10**6, "assays": 2},
        brief={},
        turns=5,
    )
    agent.view = agents.RoleView("calibration", every, run.rec)
    agent.specs = agents.role_tool_specs("calibration", every)
    first_assay = sorted(cfg["assay_catalogue"])[0]
    sim_index = _content(agent.execute(_use("simulate", {})))["call_index"]
    fit_index = _content(
        agent.execute(
            _use("fit_lsq", {"parameters": ["k_m_ac"], "n_starts": 1, "max_nfev_per_start": 10})
        )
    )["call_index"]
    post_index = _content(
        agent.execute(
            _use(
                "bayes_mcmc",
                {"parameters": ["k_m_ac"], "from_fit": fit_index, "n_walkers": 4, "n_steps": 4},
            )
        )
    )["call_index"]
    day = float(ws.cal[0]) + 1.0
    inputs = {
        "inspect_record": {"what": "sensor", "name": "tan"},
        "describe_model": {},
        "feed_loads": {},
        "data_qc": {},
        "mass_balance": {},
        "gsa_morris": {"parameters": ["k_m_ac", "K_S_ac"], "n_trajectories": 2},
        "gsa_sobol": {"parameters": ["k_m_ac", "K_S_ac"], "n_samples": 4},
        "fisher_info": {"parameters": ["k_m_ac"]},
        "profile_likelihood": {
            "parameters": ["k_m_ac", "K_S_ac"],
            "profile": "k_m_ac",
            "n_grid": 3,
            "n_starts": 1,
        },
        "fit_de": {"parameters": ["k_m_ac"], "popsize": 2, "max_generations": 1},
        "fit_cmaes": {"parameters": ["k_m_ac"], "max_evaluations": 10},
        "residual_diag": {"sensor": "tan", "prediction": sim_index},
        "request_assay": {"assay": first_assay, "day": day},
        "voi_assay": {"posterior": post_index, "day": day, "n_outer": 2},
        "set_sensor_status": {
            "sensor": "tan",
            "status": "ok",
            "in_objective": True,
            "reason": "fine",
        },
        "declared_background": {},
        "validate": {"prediction": sim_index},
    }
    assert set(inputs) | {"simulate", "fit_lsq", "bayes_mcmc"} == set(every)
    for name, inp in inputs.items():
        before = agents.Recorder.next_index()
        result = agent.execute(_use(name, inp))
        assert not result.get("is_error"), (name, result["content"])
        if name in SEEDED:
            called = [a for n, a in fake.calls if n == name][-1]
            assert called["seed"] == base + before, name
    for name, index in (("fit_lsq", fit_index), ("bayes_mcmc", post_index)):
        assert [a for n, a in fake.calls if n == name][-1]["seed"] == base + index
    assert agent.state["refused"] == 0
    assert not agent.execute(_use("stored", {"call_index": sim_index})).get("is_error")
    # the negative control: the base is the configuration's, so another base moves the seed
    ws.agents_cfg = {**ws.agents_cfg, "seeds": {"base": base + 7}}
    before = agents.Recorder.next_index()
    assert not agent.execute(_use("fit_cmaes", inputs["fit_cmaes"])).get("is_error")
    assert [a for n, a in fake.calls if n == "fit_cmaes"][-1]["seed"] == base + 7 + before


def test_a_silent_verifier_never_passes_a_proposal(monkeypatch):
    """J1: the verifier ran and delivered no verdict: the run abstains."""
    dq = Script([[{"name": "simulate", "input": {}}], [_emit("data_quality", **_sensor_claim())]])
    silent = Script([[{"type": "text", "text": "I have nothing to add."}]])  # never emits
    _admit_everything(monkeypatch)
    _, fake = _run(monkeypatch, {"data_quality": dq, "verification": silent})
    report = json.loads(fake.run.outputs["report.json"])
    assert (report["label"], report["rule"]) == ("abstain", "abstain:no_verdict")
    assert report["verdict"]["rounds"] == 0 and report["verdicts"] == []
    ver = next(r for r in report["role_runs"] if r["role"] == "verification")
    assert ver["stop"].endswith("turns used without a finding")
    # the negative control: the same proposal with a verdict concludes it
    dq = Script([[{"name": "simulate", "input": {}}], [_emit("data_quality", **_sensor_claim())]])
    loud = Script([[{"name": "simulate", "input": {}}], [_emit("verification")]])
    _, fake2 = _run(monkeypatch, {"data_quality": dq, "verification": loud})
    assert json.loads(fake2.run.outputs["report.json"])["label"] == "sensor"


def test_a_pass_with_no_proposal_over_a_failed_null_abstains(monkeypatch):
    """J4: `none` over a failed null needs a specialist's cited `none` finding."""
    ver = Script([[{"name": "simulate", "input": {}}], [_emit("verification")]])
    _, fake = _run(monkeypatch, {"verification": ver})  # every specialist claims nothing
    report = json.loads(fake.run.outputs["report.json"])
    assert report["null_table"]["null_rejected"]  # the fixture's ph offset fails NS
    assert (report["label"], report["rule"]) == ("abstain", "abstain:no_proposal")
    assert report["verdict"] == {
        **report["verdict"],
        "verdict": "abstain",
        "reason": "no_proposal",
    }
    # the control: a specialist's cited `none` finding, passed, concludes none
    none_finding = _emit(
        "data_quality",
        claim="none",
        evidence=[
            {"label": "none", "rule": "sensor", "calls": ["LAST"], "values": {}, "units": {}}
        ],
    )
    dq = Script([[{"name": "simulate", "input": {}}], [none_finding]])
    ver = Script([[{"name": "simulate", "input": {}}], [_emit("verification")]])
    _, fake2 = _run(monkeypatch, {"data_quality": dq, "verification": ver})
    report2 = json.loads(fake2.run.outputs["report.json"])
    assert (report2["label"], report2["rule"]) == ("none", "agents:pass")
    # and on a standing null a pass with no claim is none
    ver = Script([[{"name": "simulate", "input": {}}], [_emit("verification")]])
    _, fake3 = _run(monkeypatch, {"verification": ver}, fake=FakeTools("B", "B"))
    report3 = json.loads(fake3.run.outputs["report.json"])
    if not report3["null_table"]["null_rejected"]:
        assert (report3["label"], report3["rule"]) == ("none", "agents:pass:none")


def test_a_value_is_the_calls_to_five_digits_and_the_record_keeps_the_calls_own(monkeypatch):
    """J5: equality at the five digits shown; state.json carries the produced value."""
    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    ws = run.ws
    view = agents.RoleView("data_quality", ALLOW_LIST["data_quality"], run.rec)
    index = ws.t_simulate(view, {})["call_index"]
    produced = next(v for v, _, s in run.rec.produced[index]["mean_predicted"] if s == "tan")

    def finding(value: float) -> dict[str, Any]:
        return {
            "claim": "sensor",
            "channel": "ph",
            "confidence": "high",
            "evidence": [
                {
                    "label": "sensor",
                    "rule": "sensor",
                    "calls": [index],
                    "values": {"mean_predicted": value},
                    "units": {"mean_predicted": "mg/L"},
                }
            ],
        }

    shown = float(f"{produced:.5g}")
    accepted = agents.check_finding(ws, "data_quality", finding(shown), 1)
    assert agents.evidence_items(accepted)[0]["values"]["mean_predicted"] == produced
    assert accepted.evidence[0].values["mean_predicted"] == produced
    off = produced * (1 + 5e-4)  # 0.05 % off: inside the old 0.1 % tolerance, refused now
    assert f"{off:.5g}" != f"{produced:.5g}"
    with pytest.raises(agents.ActionError, match="not what the cited calls produced"):
        agents.check_finding(ws, "data_quality", finding(off), 1)
    assert agents._same_value(2.61128, 2.61363) is False
    assert agents._same_value(2.61128, 2.611283) is True


def test_the_hold_out_output_is_hidden_from_every_proposer(monkeypatch):
    """J7: `validate`'s output reaches the verifier's projection and `stored` only (§4 step 8)."""
    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    ws = run.ws
    view = agents.RoleView("verification", ALLOW_LIST["verification"], run.rec)
    sim_index = ws.t_simulate(view, {})["call_index"]
    v_index = ws.t_validate(view, {"prediction": sim_index})["call_index"]
    grant = {"evaluations": 0, "assays": 0}
    for role in agents.SPECIALISTS:
        log = run.brief(role, 1, grant, 5)["projected_log"]
        entry = next(e for e in log if e["call_index"] == v_index)
        assert entry["tool"] == "validate" and entry["hidden"] is True and "output" not in entry
        assert "holdout_failed" not in json.dumps(log)
        with pytest.raises(agents.ActionError, match="verifier's only"):
            ws.stored({"call_index": v_index}, role)
        assert ws.stored({"call_index": sim_index}, role)["call_index"] == sim_index
    # the negative control: the verifier sees the output, in its projection and by index
    log = run.brief("verification", 1, grant, 5)["projected_log"]
    entry = next(e for e in log if e["call_index"] == v_index)
    assert "output" in entry and "hidden" not in entry and "holdout_failed" in json.dumps(entry)
    assert ws.stored({"call_index": v_index}, "verification")["call_index"] == v_index


def test_the_offline_design_finding_is_accepted_on_a_conflict(monkeypatch):
    """J10: the scripted design role's plan passes the harness's check."""
    dq = Script([[{"name": "simulate", "input": {}}], [_emit("data_quality", **_sensor_claim())]])
    param = _emit(
        "calibration",
        claim="parameter",
        confidence="high",
        evidence=[
            {
                "label": "parameter",
                "rule": "change_point",
                "calls": ["LAST"],
                "values": {},
                "units": {},
            }
        ],
    )
    cal = Script([[{"name": "simulate", "input": {}}], [param]])
    _admit_everything(monkeypatch)
    _, fake = _run(monkeypatch, {"data_quality": dq, "calibration": cal})  # design: offline
    report = json.loads(fake.run.outputs["report.json"])
    assert any(e["to"] == "design" and e["reason"] == "conflict" for e in report["routing"])
    assert report["findings"]["design"]["assay"] in _cfg()["assay_catalogue"]
    design = next(r for r in report["role_runs"] if r["role"] == "design")
    assert design["stop"] == "finding emitted" and design["refused"] == 0


def test_grants_are_fixed_when_a_stage_starts(monkeypatch):
    """J12: every role of a stage gets the same share, whatever the earlier roles spent."""
    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    left = int(fake.remaining().simulator_evals)
    grants = run.coordinator.grants_for(["influent", "identifiability", "calibration"])
    assert {g["evaluations"] for g in grants.values()} == {left // 3}
    assert {g["assays"] for g in grants.values()} == {0}
    assert run.coordinator.grants_for(["design"])["design"]["assays"] == fake.totals["assays"]
    # in a run: identifiability spends, calibration's share is the same as its own
    ident = Script(
        [
            [{"name": "gsa_morris", "input": {"parameters": ["k_m_ac"], "n_trajectories": 3}}],
            [_emit("identifiability")],
        ]
    )
    _, fake2 = _run(monkeypatch, {"identifiability": ident})
    routing = json.loads(fake2.run.outputs["report.json"])["routing"]
    stage = [e for e in routing if e["to"] in ("identifiability", "calibration")]
    assert [e["to"] for e in stage] == ["identifiability", "calibration"]
    assert stage[0]["grant"]["evaluations"] == stage[1]["grant"]["evaluations"] > 0
    spent = next(r for r in json.loads(fake2.run.outputs["report.json"])["role_runs"]
                 if r["role"] == "identifiability")["spent"]["evaluations"]  # fmt: skip
    assert spent == 6  # 3 trajectories x (1 + 1)


# ------------------------------------------------------------------ rule 1 and the pins


def test_the_harness_imports_only_what_the_jail_has_and_passes_rule_one():
    from tests.test_truth_isolation import find_truth_references

    path = REPO / "workflows" / "p2_multi_agent" / "agents.py"
    assert find_truth_references(path) == []
    text = path.read_text(encoding="utf-8")
    imports = set(re.findall(r"^(?:from|import) ([a-z_]+)", text, flags=re.M))
    assert imports <= {
        "__future__",
        "json",
        "math",
        "typing",
        "numpy",
        "pydantic",
        "tools",
        "workflows",
    }
    assert "8f78881" in text  # the P1 revision the loop copies, named


# ------------------------------------------------------------------ the jail


@pytest.fixture(scope="module")
def jailed_agents(tmp_path_factory):
    """The agent arm in the sandbox on a short generated cell, offline, with the real tools."""
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from tools.runner import run_workflow

    s = load_scenario(REPO / "scenarios" / "S0-01.yaml")
    budget = s.budget.model_copy(update={"simulator_evals": 300, "wall_clock_min": 45.0})
    s = s.model_copy(update={"duration_days": 30.0, "budget": budget})
    root = tmp_path_factory.mktemp("p2agents") / "runs"
    run = generate_run(s, "B", plant=load_plant_config("C"), runs_root=root)
    result = run_workflow(run.run_id, "p2", runs_root=root, scenario=s, config_path=AGENTS_YAML)
    return run, root, result


def test_the_jailed_agent_arm_writes_the_declared_record(jailed_agents, tmp_path):
    run, root, result = jailed_agents
    out = root / run.run_id / "workflows" / "p2"
    assert {p.name for p in out.iterdir()} == {
        "state.json",
        "report.json",
        "messages.jsonl",
        "decisions.jsonl",  # the code steps' decision points, each at its offline fallback
        "summary.json",
        "launch.json",  # the launcher's record of the staged package (privileged side)
    }
    # the record carries the digest of the code that ran: the staged tree's, as the
    # launcher computes it, and every staged module by name (the review of #40, H2)
    from tools.sandbox import stage_workflow

    launch = json.loads((out / "launch.json").read_text())
    box = tmp_path / "box_digest"
    box.mkdir()
    staged = stage_workflow(REPO / "workflows" / "p2_multi_agent" / "workflow.py", box)
    assert launch["package_sha256"] == staged.package_sha256
    assert launch["entry"] == "workflows/p2_multi_agent/workflow.py"
    assert launch["entry_sha256"] == staged.entry_sha256
    assert set(launch["modules"]) == set(staged.modules)
    assert {"workflows/p2_multi_agent/agents.py", "workflows/p2_multi_agent/messages.py"} <= set(
        launch["modules"]
    )
    decisions = [json.loads(x) for x in (out / "decisions.jsonl").read_text().splitlines()]
    assert decisions and all(r["fallback_used"] and r["attempts"] == 0 for r in decisions)
    doc = TaskState.model_validate_json((out / "state.json").read_text())
    assert doc.workflow == "p2" and doc.workflow_version == "0.4-agents" and doc.final.completed
    assert result.completed
    report = json.loads((out / "report.json").read_text())
    assert report["arm"] == "agents" and report["routing"][0]["to"] == "data_quality"
    assert report["outcome"] == "abstain"  # the offline verifier abstains
    assert not report["refusals"]
    kinds = [json.loads(x)["kind"] for x in (out / "messages.jsonl").read_text().splitlines()]
    assert "decision" in kinds and "verdict" in kinds
    summary = json.loads((out / "summary.json").read_text())
    # offline no gateway is built, so the summary's model fields are null, as the
    # procedural arm's are (never a count)
    assert summary["decider"] == "offline" and summary["llm_turns"] is None
    assert summary["model_id"] is None and summary["llm_cost_usd"] is None
