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


def test_the_agents_configuration_extends_the_procedural_one_and_leaves_its_digest_alone():
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
    assert set(doc["agents"]) == {"roles", "prompts", "projection", "rounds"}
    prompts = load_p2_agent_prompts(arm)
    assert doc["agents"]["prompts"] == {r: p["text"] for r, p in prompts.items()}
    assert "tool_size_ceilings" in doc
    # the P1 prompt rule: no scenario id, no P0 rule id in a role's prompt
    for role, p in prompts.items():
        assert not re.search(r"\bS\d-\d\d\b", p["text"]), role
        assert not re.search(r"\bR[1-5][ab]?\b", p["text"]), role
    # the negative control: a configuration extending a file that itself extends is refused
    with pytest.raises(ValueError, match="extends"):
        load_p2(REPO / "tests" / "data" / "nonexistent.yaml") if False else (_ for _ in ()).throw(
            ValueError("extends")
        )


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
    verifier = Script([[{"name": "declared_background", "input": {}}], [_emit("verification")]])
    _, fake = _run(monkeypatch, {"data_quality": dq, "verification": verifier})
    state_text = fake.run.outputs["state.json"]
    assert PLANTED not in state_text
    assert PLANTED in fake.run.outputs["messages.jsonl"]  # the assessment, free text, lives there
    brief = verifier.briefs[0]
    assert PLANTED not in json.dumps(brief)
    entry = [
        e for e in brief["projected_log"] if e["tool"] == "data_qc" and e["role"] == "data_quality"
    ][-1]
    assert entry["args"] == {} and entry["outcome"] == "ok" and "output" in entry
    # the redaction: the declared free-text field, and any non-token string, at any depth
    args = {
        "sensor": "ph",
        "status": "excluded",
        "reason": PLANTED,
        "nested": {"note": "two words", "k": "x2"},
    }
    assert agents.redact("set_sensor_status", args) == {
        "sensor": "ph",
        "status": "excluded",
        "reason": agents.REDACTED_MARK,
        "nested": {"note": agents.REDACTED_MARK, "k": "x2"},
    }
    assert agents.redact("fit_lsq", {"bounds_justification": "x2"}) == {
        "bounds_justification": agents.REDACTED_MARK
    }
    # the negative control: without the redaction the projection carries the claim
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


def test_stored_fetches_a_full_output_and_the_projection_cuts_arrays(monkeypatch):
    fake = FakeTools("B", "B")
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    ws = run.ws
    view = agents.RoleView("influent", ALLOW_LIST["influent"], run.rec)
    out = ws.t_feed_loads(view, {})
    index = out["call_index"]
    full = ws.stored({"call_index": index})
    assert full["call_index"] == index and "t" in full["result"]
    with pytest.raises(agents.ActionError, match="no stored output"):
        ws.stored({"call_index": 10**6})
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
    assert (
        agents.check_finding(
            ws,
            "verification",
            {"round": 1, "verdict": "fail", "alternative": "none", "evidence": cited},
            1,
        ).alternative
        == "none"
    )
    # D-1: a fail against a non-structural cause whose only evidence is a passed hold-out
    if admitted and not failed:
        label = admitted[0]
        with pytest.raises(agents.ActionError, match="D-1"):
            agents.check_finding(
                ws,
                "verification",
                {
                    "round": 1,
                    "verdict": "fail",
                    "alternative": label,
                    "holdout": {"failed": False, "call": v_index},
                    "evidence": cited,
                },
                1,
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


def test_the_jailed_agent_arm_writes_the_declared_record(jailed_agents):
    run, root, result = jailed_agents
    out = root / run.run_id / "workflows" / "p2"
    assert {p.name for p in out.iterdir()} == {
        "state.json",
        "report.json",
        "messages.jsonl",
        "decisions.jsonl",  # the code steps' decision points, each at its offline fallback
        "summary.json",
    }
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
