"""P2's workflow (``docs/p2_design.md``), deliverable 2: every test of design §10.

Most tests run the workflow in-process against :class:`tests.p2_support.FakeTools` (no
simulator, the real band); the module fixture at the end runs it once in the sandbox on a
short generated cell, with the real tools, as the integration check.

1. Allow-lists: a call outside a role's list is refused and recorded; the negative
   control is the same call from a role that holds the tool.
2. No free text reaches the verifier: a planted claim in a decision output is refused by
   the schema; the negative control is a schema that lets text through.
3. The budget is summed across roles and equals the registry's meter.
4. The message log: every message validates, ``seq`` is continuous, cited calls exist.
5. The null case in the verifier's output (admission, §4.4) and the abstention without
   a null table (decision c).
6. Every decision point's schema: valid accepted; invalid retried once, then the fallback.
7. Every ablation switch: recorded, its element absent, the state still valid.
8. Like-for-like: the workflow's arithmetic is the band driver's; the reference fit's
   settings are the served procedure block.
9. Rule 1: the workflow passes the truth-isolation checker and its import allow-list.
10. ``dq.trust``'s constraints, with the fallback trimmed (the review's R2).
11. The onset test (N1, R1), with the edge-of-envelope case.
12. The templates: no labelling rule the code owns; their sha256 in every record.
13. The workflow's null rule is the frozen one: the JSON's counts over all 120
    leave-one-out placements and the four §4.5 outcomes (scoped by the review's R4), and
    the two frozen files' sha256.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import BaseModel, ValidationError

from scripts import declared_background as bg
from state.task_state import TaskState
from tests.p2_support import FakeTools
from tools.workflow_config import DECISION_POINTS, load_p2, sandbox_config
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]
FROZEN = {
    "scripts/null_rule_loo.py": "fb8e88917d440b1b50001d1f29b0e8f36a88256219f44ff81c19167549059812",
    "reports/background/null_rule_loo.json": (
        "de537c459d737fa895d3af5cdf170c30ad3eebf6a847ce6be07c57230f094e9c"
    ),
}


@pytest.fixture(scope="module")
def cfg() -> dict[str, Any]:
    """The sandbox document the runner writes for P2."""
    return json.loads(json.dumps(sandbox_config(load_p2())))


def run_fake(
    monkeypatch: pytest.MonkeyPatch,
    cfg: dict[str, Any],
    fake: FakeTools | None = None,
    *,
    ablation: dict[str, Any] | None = None,
    respond: Any = wf.offline_responder,
) -> tuple[wf.Workflow, FakeTools, dict[str, Any]]:
    """Run the workflow in-process on a fake registry; return it, the fake, the state."""
    fake = fake or FakeTools()
    monkeypatch.setattr(wf, "tools", fake)
    c = json.loads(json.dumps(cfg))
    for key, value in (ablation or {}).items():
        if key == "roles":
            c["ablation"]["roles"].update(value)
        else:
            c["ablation"][key] = value
    run = wf.Workflow(c, respond)
    run.run()
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    TaskState.model_validate(doc)
    return run, fake, doc


# ------------------------------------------------------------------ 1. allow-lists


def test_a_role_outside_its_list_is_refused_and_the_holder_is_not(monkeypatch, cfg):
    fake = FakeTools()
    monkeypatch.setattr(wf, "tools", fake)
    rec = wf.Recorder()
    dq = wf.RoleView("data_quality", cfg["roles"]["data_quality"]["tools"], rec)
    cal = wf.RoleView("calibration", cfg["roles"]["calibration"]["tools"], rec)
    with pytest.raises(wf.RoleRefused):
        dq.call("probe", "simulate", model=wf.MODEL)
    assert fake.calls == []  # refused before the registry
    assert rec.refusals == [{"role": "data_quality", "step": "probe", "name": "simulate"}]
    assert rec.failures[-1]["name"] == "p2.data_quality.refused"
    # the negative control: the role that holds the tool calls it
    out = cal.call("probe", "simulate", model=wf.MODEL)
    assert fake.calls[-1][0] == "simulate" and out.outputs
    assert rec.actions[-1]["step"] == "calibration.probe"
    # no role but the verifier holds validate; no role holds the state-space filters
    holders = {r for r, spec in cfg["roles"].items() if "validate" in spec["tools"]}
    assert holders == {"verification"}
    every = {t for spec in cfg["roles"].values() for t in spec["tools"]}
    assert not every & {"filter_enkf", "filter_mhe"}
    assert cfg["roles"]["coordination"]["tools"] == []


# ------------------------------------------------------------------ 2. no free text


def test_a_planted_claim_never_reaches_the_verifier():
    claim = "the gas meter is obviously broken"
    templates = {p: {"text": "t", "sha256": "s"} for p in DECISION_POINTS}

    def planting(point: str, template: str, inputs: dict[str, Any]) -> Any:
        if point == "dq.coupled":
            return {"sensor": "gas_flow", "code": "coupled_inside", "note": claim}
        if point == "verify.differential":
            return {"label": claim, "rejected": []}
        return None

    d = wf.Decider(templates, planting)
    out = d.decide("dq.coupled", {"s1_table": {}, "assays": []},
                   {"sensor": "gas_flow", "code": "insufficient"})  # fmt: skip
    assert out.code == "insufficient"  # an extra text field is refused, the fallback stands
    out = d.decide(
        "verify.differential",
        {"null_table": {}, "admitted": ["sensor"], "tables": {}, "holdout_failed": False},
        {"label": "sensor", "rejected": []},
        check=lambda o: o.label in ["sensor", "none"],
    )
    assert out.label == "sensor"  # text in the label slot fails the code check
    assert claim not in json.dumps(d.records)
    assert all(r["fallback_used"] and r["attempts"] == 2 for r in d.records)

    # the negative control: a schema that lets text through, and the scan finds it
    class Loose(BaseModel):
        sensor: str
        code: str
        note: str = ""

    assert claim in json.dumps(Loose.model_validate(planting("dq.coupled", "", {})).model_dump())
    # and every decision output schema forbids extra fields
    for spec in wf.DECISIONS.values():
        with pytest.raises(ValidationError):
            spec["model"].model_validate({"unexpected": claim})


# ------------------------------------------------------------------ 3 and 4. budget, messages


def test_the_budget_is_summed_across_roles_and_the_message_log_is_sound(monkeypatch, cfg):
    run, fake, doc = run_fake(monkeypatch, cfg)
    by_role = run.rec.by_role
    assert sum(int(v["evaluations"]) for v in by_role.values()) == fake.used["evals"]
    assert sum(int(v["assay_units"]) for v in by_role.values()) == fake.used["assays"]
    assert sum(int(v["calls"]) for v in by_role.values()) == fake.used["calls"]
    assert doc["budget"]["simulator_evals_used"] == fake.used["evals"]
    assert set(by_role) <= set(cfg["roles"]) | {"harness"}
    # every action names its role
    assert all(a["step"].split(".")[0] in set(cfg["roles"]) | {"harness"} for a in doc["actions"])
    # the message log
    lines = [json.loads(x) for x in fake.run.outputs[wf.MESSAGES_FILE].splitlines()]
    assert lines and [m["seq"] for m in lines] == list(range(len(lines)))
    for m in lines:
        wf.Message.model_validate(m)
    indices = {a["call_index"] for a in doc["actions"]}
    for m in lines:
        for c in m["body"].get("calls", []):
            assert c in indices
    # a role that would exceed the budget is refused by the registry, not the role
    small = FakeTools(evals=60)
    run, small, doc = run_fake(monkeypatch, cfg, small)
    assert run.reference is None and "no_null_table" in run.codes
    assert any(a["outcome"] == "budget_exceeded" for a in doc["actions"])
    assert not run.rec.refusals


# ------------------------------------------------------------------ 5. the null case


def _table(nb=False, nm=False, ns=False, failed=(), rejected=None):
    return {"NB": nb, "NM": nm, "NS": ns, "failed_channels": list(failed),
            "null_rejected": bool(nb or nm or ns) if rejected is None else rejected,
            "null_partial": False, "n_outside": 0}  # fmt: skip


def test_admission_needs_a_failed_null_case_and_its_signature(cfg):
    lab = cfg["p0"]["labels"]
    clean = _table()
    sig = {"sensor": {"channel": "gas_flow", "s1_holds": True}, "sensor_proposed": True}
    # a signature without a failed null case is rejected: null_not_failed
    out = wf.admit(lab, clean, sig)
    assert out["admitted"] == []
    assert out["rejected"] == [{"label": "sensor", "code": "null_not_failed"}]
    # NS on that channel with the S1 reading: admitted
    assert wf.admit(lab, _table(ns=True, failed=["gas_flow"]), sig)["admitted"] == ["sensor"]
    # NS on another channel: rejected
    assert wf.admit(lab, _table(ns=True, failed=["ph"]), sig)["admitted"] == []
    # the S1 reading fails: coupled_outside
    bad = {"sensor": {"channel": "gas_flow", "s1_holds": False}, "sensor_proposed": True}
    out = wf.admit(lab, _table(ns=True, failed=["gas_flow"]), bad)
    assert out["rejected"] == [{"label": "sensor", "code": "coupled_outside"}]
    # influent on NB only; parameter on NM without NB; structural on NM with R3 and hold-out
    inf = {"influent": True, "influent_proposed": True}
    assert wf.admit(lab, _table(nb=True), inf)["admitted"] == ["influent"]
    assert wf.admit(lab, _table(nm=True), inf)["admitted"] == []
    par = {"parameter": True, "parameter_proposed": True}
    assert wf.admit(lab, _table(nm=True), par)["admitted"] == ["parameter"]
    assert wf.admit(lab, _table(nm=True, nb=True), par)["admitted"] == []
    st = {"structural": False, "r3": True, "structural_proposed": True}
    out = wf.admit(lab, _table(nm=True), st)
    assert out["rejected"] == [{"label": "structural", "code": "holdout_passed"}]
    assert wf.admit(lab, _table(nm=True), {**st, "structural": True})["admitted"] == ["structural"]
    # a clean table and no signature: nothing admitted, the null stands
    assert wf.admit(lab, clean, {}) == {"admitted": [], "rejected": []}
    assert wf.first_in_p0_order(lab, []) == "none"
    assert wf.first_in_p0_order(lab, ["parameter", "sensor"]) == "sensor"


def test_a_signature_over_a_standing_null_concludes_none_not_unexplained(monkeypatch, cfg):
    """A rejected signature over a clean table is the null case working (the smoke run)."""
    fake = FakeTools()
    monkeypatch.setattr(wf, "tools", fake)
    run = wf.Workflow(json.loads(json.dumps(cfg)))
    run.reference = {"balance": {}, "channels": {}}
    run.table = _table()
    run.signatures = {"parameter": True, "parameter_proposed": True}
    run.prediction = fake._simulate(wf.MODEL)
    run.series = {}
    run.step_verify()
    assert run.verdict["verdict"] == "pass" and run.verdict["label"] == "none"
    assert run.verdict["rejected"] == [{"label": "parameter", "code": "null_not_failed"}]
    run.step_conclude()
    assert run.classification["rule"] == "null_stands"
    assert run.classification["confidence"] == cfg["p0"]["attribution"]["confidence"]["none"]
    assert "revise" not in run.trace
    # and a rejected null with nothing admitted is the fail that concludes unexplained
    run2 = wf.Workflow(json.loads(json.dumps(cfg)))
    run2.reference = {"balance": {}, "channels": {}}
    run2.table = _table(nm=True, failed=["ph", "tan"])
    run2.signatures = {}
    run2.prediction = run.prediction
    run2.series = {}
    run2.step_verify()
    assert run2.verdict["verdict"] == "fail" and "revise" in run2.trace
    run2.step_conclude()
    assert run2.classification["rule"] == "null_failed_unexplained"


def test_a_run_without_a_null_table_abstains_and_never_reads_none(monkeypatch, cfg):
    run, _fake, doc = run_fake(monkeypatch, cfg, FakeTools(evals=60))
    assert run.verdict["verdict"] == "abstain" and run.table is None
    assert doc["classification"]["rule"] == "abstain:no_null_table"
    assert doc["classification"]["confidence"] == 0.0
    assert "no_null_table" in doc["plan"]["fallbacks"]
    assert {"kinetic_attribution", "parameter_values", "structural_adequacy"} <= set(
        doc["abstentions"]
    )


# ------------------------------------------------------------------ 6. decision schemas


def test_every_decision_point_validates_retries_once_then_falls_back(cfg):
    assert set(wf.DECISIONS) == set(DECISION_POINTS) and len(DECISION_POINTS) == 12
    attempts: list[str] = []

    def bad_then_good(point, template, inputs):
        attempts.append(point)
        return {"window_index": "x"} if attempts.count(point) == 1 else {"window_index": 2}

    d = wf.Decider(cfg["templates"], bad_then_good)
    out = d.decide("influent.window", {"window_closures": []}, {"window_index": 0})
    assert out.window_index == 2 and d.records[-1]["attempts"] == 2
    assert not d.records[-1]["fallback_used"]

    def always_bad(point, template, inputs):
        return {"window_index": "x"}

    d = wf.Decider(cfg["templates"], always_bad)
    out = d.decide("influent.window", {"window_closures": []}, {"window_index": 0})
    assert out.window_index == 0 and d.records[-1]["fallback_used"]
    assert d.records[-1]["attempts"] == 2 and len(d.records[-1]["failures"]) == 2
    # undeclared inputs are refused
    with pytest.raises(wf.DecisionError):
        d.decide("influent.window", {"window_closures": [], "truth": 1}, {"window_index": 0})
    # the offline decider: no attempt, the fallback, recorded
    d = wf.Decider(cfg["templates"], wf.offline_responder)
    d.decide("cal.bound", {"parameter": "k", "bounds": [0, 1], "estimate": 1, "sd": 0.1},
             {"code": "identifiability_limit"})  # fmt: skip
    rec = d.records[-1]
    assert rec["attempts"] == 0 and rec["fallback_used"] and rec["llm_call_ids"] == []
    assert rec["schema_sha256"] == wf.schema_sha256(wf.CalBound)
    # the kinetic update is not a value cal.bound can take
    with pytest.raises(ValidationError):
        wf.CalBound.model_validate({"code": "kinetic_update"})


# ------------------------------------------------------------------ 7. ablations


ABLATIONS = [
    ({"verifier": False}, "unverified"),
    ({"coordinator": False}, None),
    ({"persistent_state": False}, None),
    ({"self_correction": False}, None),
    ({"roles": {"data_quality": False}}, "qc"),
    ({"roles": {"influent": False}}, "influent"),
    ({"roles": {"identifiability": False}}, "screen"),
    ({"roles": {"calibration": False}}, "mcmc"),
    ({"roles": {"design": False}}, "assays"),
]


@pytest.mark.parametrize(("switch", "absent"), ABLATIONS)
def test_every_ablation_switch_is_recorded_and_leaves_a_valid_state(
    monkeypatch, cfg, switch, absent
):
    run, _fake, doc = run_fake(monkeypatch, cfg, ablation=switch)
    recorded = json.loads(doc["annotations"][2].split("ablation: ", 1)[1])
    for key, value in switch.items():
        if key == "roles":
            for role, on in value.items():
                assert recorded["roles"][role] is on
        else:
            assert recorded[key] is value
    points = {r["point"] for r in run.decider.records}
    if absent == "unverified":
        assert run.verdict["verdict"] == "unverified" and run.table is None
        assert "verify.differential" not in points
    elif absent == "qc":
        assert "qc" in doc["plan"]["steps_skipped"] and "dq.trust" not in points
        assert not any(a["name"] == "data_qc" for a in doc["actions"])
    elif absent == "influent":
        assert not run.signatures["influent"] and "influent.onset" not in points
    elif absent == "screen":
        assert "screen" in doc["plan"]["steps_skipped"] and "ident.subset" not in points
    elif absent == "mcmc":
        assert "mcmc" in doc["plan"]["steps_skipped"]
        assert not any(a["name"] == "bayes_mcmc" for a in doc["actions"])
        assert "posterior_intervals" in doc["abstentions"]
    elif absent == "assays":
        assert not any(a["name"] == "request_assay" for a in doc["actions"])
    if switch.get("self_correction") is False or switch.get("coordinator") is False:
        assert "revise" not in run.trace
    assert doc["final"]["completed"] is True


# ------------------------------------------------------------------ 8. like-for-like


def test_the_workflows_arithmetic_is_the_band_drivers_and_the_settings_are_served(monkeypatch, cfg):
    rng = np.random.default_rng(3)
    t = np.arange(0.0, 150.0)
    value = 10 + rng.normal(0, 1, t.size)
    value[[4, 17, 60]] = np.nan
    raw = {"channel": "y", "unit": "u", "sample_t_d": t,
           "value": [None if np.isnan(v) else v for v in value]}  # fmt: skip
    cal = {"min_relative_sd": 0.02, "sd_floor_abs": 1e-6}
    driver = bg._Series("y", raw, 0.05, 0.3, cal)
    sd = wf.declared_sd(value, 0.05, 0.3, cal)
    np.testing.assert_allclose(sd, driver.sd)

    class Sim:
        t = np.arange(0.0, 151.0)
        outputs = {"y": 10.2 + 0.01 * np.arange(0.0, 151.0)}  # noqa: RUF012

    for window in ((0.0, 112.5), (30.0, 60.0)):
        assert wf.z_summary(t, value, sd, Sim.t, Sim.outputs["y"], window) == driver.summary(
            Sim(), window
        )
    # the reference fit's settings are the served procedure block, not P0's retyped
    _run, fake, _doc = run_fake(monkeypatch, cfg)
    proc = fake._declared_background("B", "B").procedure
    morris = next(a for n, a in fake.calls if n == "gsa_morris")
    lsq = next(a for n, a in fake.calls if n == "fit_lsq")
    assert morris["n_trajectories"] == proc.morris_trajectories
    assert morris["seed"] == proc.morris_seed and morris["summary"] == proc.gsa_summary
    assert lsq["n_starts"] == proc.lsq_starts and lsq["seed"] == proc.fit_seed
    assert lsq["max_nfev_per_start"] == proc.lsq_max_nfev_per_start
    balance = next(a for n, a in fake.calls if n == "mass_balance")
    widths = {w["end"] - w["start"] for w in balance["windows"]}
    assert widths == {proc.balance_window_d}


# ------------------------------------------------------------------ 9. rule 1


def test_the_workflow_passes_rule_one_and_imports_only_what_the_jail_has():
    from tests.test_truth_isolation import find_truth_references

    path = REPO / "workflows" / "p2_multi_agent" / "workflow.py"
    assert find_truth_references(path) == []
    text = path.read_text(encoding="utf-8")
    imports = set(re.findall(r"^(?:from|import) ([a-z_]+)", text, flags=re.M))
    assert imports <= {"__future__", "hashlib", "json", "math", "collections", "typing",
                       "numpy", "pydantic", "tools"}  # fmt: skip


# ------------------------------------------------------------------ 10. dq.trust


def test_the_quarantine_constraints_refuse_a_model_and_trim_the_fallback():
    t = np.arange(0.0, 100.0)
    flagged = np.zeros(t.size, bool)
    flagged[[3, 40, 41, 42, 90]] = True
    spikes = np.zeros(t.size, bool)
    spikes[[3, 90]] = True
    first_hrt, holdout = 30.0, 75.0
    # a model's quarantine over a first-HRT spike, an unflagged sample or the hold-out:
    # refused whole
    for picked in ([3], [40, 41, 42, 43], [90]):
        sel = np.zeros(t.size, bool)
        sel[picked] = True
        out = wf.constrain_quarantine(t, sel, flagged, spikes, first_hrt, holdout, trim=False)
        assert out["refused"] and not out["accepted"].any()
    # P0's fallback is trimmed instead (the review's R2): the rest stands
    out = wf.constrain_quarantine(t, flagged, flagged, spikes, first_hrt, holdout, trim=True)
    assert not out["refused"] and out["trimmed"] == 2
    assert list(np.flatnonzero(out["accepted"])) == [40, 41, 42]
    assert set(out["reasons"]) == {"first_hrt_spike", "holdout"}
    # the negative controls: a QC-flagged window after the first HRT, and a first-HRT
    # flatline (not a spike), are both accepted
    sel = np.zeros(t.size, bool)
    sel[[40, 41, 42]] = True
    assert not wf.constrain_quarantine(t, sel, flagged, spikes, first_hrt, holdout,
                                       trim=False)["refused"]  # fmt: skip
    flat = np.zeros(t.size, bool)
    flat[[5, 6, 7]] = True
    out = wf.constrain_quarantine(t, flat, flat, np.zeros(t.size, bool), first_hrt, holdout,
                                  trim=False)  # fmt: skip
    assert not out["refused"] and out["accepted"].sum() == 3
    assert wf.mask_windows(t, out["accepted"]) == [[5.0, 7.0]]


# ------------------------------------------------------------------ 11. the onset test


ONSET = {"min_windows_before": 2, "every_window_after": True, "min_windows_after": 2}


def _windows(closures: list[float | None]) -> list[dict[str, Any]]:
    return [{"start": 30.0 * i, "end": 30.0 * (i + 1), "closure": c}
            for i, c in enumerate(closures)]  # fmt: skip


def test_the_onset_test_dates_a_step_and_refuses_an_offset():
    env = (-0.138, 0.023)
    step = _windows([-0.05, -0.04, -0.25, -0.30, -0.27])
    assert wf.onset_test(step, env, -1, 60.0, ONSET)["passes"]
    assert wf.candidate_onsets(step, env, -1, ONSET) == [60.0]
    # a uniform offset fails at every day, day 0 included
    offset = _windows([-0.20, -0.22, -0.19, -0.21, -0.20])
    assert wf.candidate_onsets(offset, env, -1, ONSET) == []
    assert wf.onset_test(offset, env, -1, 0.0, ONSET)["code"] == "too_few_windows_before"
    # a model's day with an outside window before it is refused
    assert wf.onset_test(step, env, -1, 90.0, ONSET)["code"] == "outside_before"
    # fewer than two evaluable windows before the onset
    assert wf.onset_test(step, env, -1, 30.0, ONSET)["code"] == "too_few_windows_before"
    gap = _windows([-0.05, None, -0.25, -0.30, -0.27])
    assert wf.onset_test(gap, env, -1, 60.0, ONSET)["code"] == "too_few_windows_before"
    # R1: every evaluable window after the onset outside; in, in, out, in, out fails
    mixed = _windows([-0.05, -0.04, -0.25, -0.10, -0.27])
    assert wf.onset_test(mixed, env, -1, 60.0, ONSET)["code"] == "inside_after"
    assert wf.onset_test(mixed, env, -1, 60.0, {**ONSET, "every_window_after": False})["passes"]
    assert wf.onset_test(step, env, -1, None, ONSET)["code"] == "no_onset"
    # the edge-of-envelope case: a uniform offset near the edge, some windows just inside
    # (S1-01 B/B-like: mean -0.19 against a minimum -0.138), is not dated
    edge = _windows([-0.13, -0.137, -0.19, -0.136, -0.21, -0.18])
    assert wf.candidate_onsets(edge, env, -1, ONSET) == []
    assert wf.onset_test(edge, env, -1, 60.0, ONSET)["code"] == "inside_after"


# ------------------------------------------------------------------ 12. the templates


LABEL_WORDS = ("sensor", "influent", "state", "parameter", "structural", "none")


def template_problems(name: str, text: str, thresholds: set[str]) -> list[str]:
    """What in a template would be a labelling rule the code owns."""
    found = []
    words = LABEL_WORDS if name != "verify.differential" else ()
    for w in (*words, "NB", "NM", "NS"):
        if re.search(rf"(?<![A-Za-z_]){w}(?![A-Za-z_])", text, flags=re.I if len(w) > 2 else 0):
            found.append(w)
    found += re.findall(r"S\d-\d\d|(?<![A-Za-z])R[1-6](?![0-9])", text)
    found += [n for n in re.findall(r"\d+\.\d+|\d+", text) if n in thresholds]
    return found


def _numbers(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set().union(*(_numbers(v) for v in node.values())) if node else set()
    if isinstance(node, list):
        return set().union(*(_numbers(v) for v in node)) if node else set()
    if isinstance(node, bool) or node is None or isinstance(node, str):
        return set()
    return {str(node), f"{float(node):g}"} - {"0", "1", "2"}


def test_no_template_holds_a_labelling_rule_and_every_record_carries_its_hash(monkeypatch, cfg):
    thresholds = _numbers(cfg["p0"]["attribution"]) | _numbers(cfg["onset"])
    for name, t in cfg["templates"].items():
        assert template_problems(name, t["text"], thresholds) == [], name
        assert t["sha256"] == hashlib.sha256(t["text"].encode("utf-8")).hexdigest()
    # the negative control: a planted line with a label and a threshold is found
    planted = cfg["templates"]["dq.trust"]["text"] + "\nIf in doubt call it a sensor fault at 3.0."
    assert set(template_problems("dq.trust", planted, thresholds)) >= {"sensor", "3.0"}
    _run, fake, _doc = run_fake(monkeypatch, cfg)
    records = [json.loads(x) for x in fake.run.outputs[wf.DECISIONS_FILE].splitlines()]
    assert records
    for r in records:
        assert r["template_sha256"] == cfg["templates"][r["point"]]["sha256"]
        assert r["schema_sha256"] == wf.schema_sha256(wf.DECISIONS[r["point"]]["model"])


# ------------------------------------------------------------------ 13. the frozen rule


def test_the_frozen_files_are_unchanged():
    for rel, sha in FROZEN.items():
        assert hashlib.sha256((REPO / rel).read_bytes()).hexdigest() == sha, rel


def test_the_workflows_null_rule_reproduces_the_frozen_counts_and_predictions():
    """Scoped to NB, NM, NS, null_rejected and null_partial (the review's R4)."""
    frozen = json.loads((REPO / "reports" / "background" / "null_rule_loo.json").read_text())
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in sorted(bg.read_record(), key=lambda r: r["key"]):
        groups[(r["plant"], r["tier"])].append(r)
    rules = {"NB": wf.n_bal, "NM": wf.n_multi, "NS": wf.n_single,
             "null_rejected": wf.null_rejected, "null_partial": wf.null_partial}  # fmt: skip
    counts = {name: defaultdict(int) for name in rules}
    for (plant, tier), rs in groups.items():
        for i, r in enumerate(rs):
            p = wf.envelope_placement(r, rs[:i] + rs[i + 1 :])
            for name, rule in rules.items():
                counts[name][f"{plant}/{tier}"] += int(rule(p))
    for name in rules:
        assert dict(counts[name]) == frozen["rules"][name]["per_plant_tier"], name
    # the four pre-registered §4.5 outcomes, from the published placement
    placed = json.loads((REPO / "reports" / "background" / "dev_cells.json").read_text())
    outcome = {}
    for cell in placed["cells"]:
        p = {r["statistic"]: wf.place(r["value"], r["band_min"], r["band_max"])
             for r in cell["rows"] if r.get("ruled", True) and r["value"] is not None
             and r["band_min"] is not None}  # fmt: skip
        outcome[cell["cell"]] = (wf.n_bal(p), wf.n_multi(p), wf.n_single(p),
                                 wf.failed_channels(p))  # fmt: skip
    assert outcome["S0-01 B/A"] == (False, False, False, [])
    assert outcome["S0-01 B/B"] == (False, False, False, [])
    assert outcome["S0-01 B/C"] == (False, True, False, ["digestate_ts", "digestate_vs"])
    assert outcome["S1-01 B/B"] == (True, False, False, ["gas_flow"])


def test_the_band_placement_and_the_envelope_placement_agree(monkeypatch, cfg):
    """The verifier's placement against the tool's band is the envelope rule exactly."""
    fake = FakeTools()
    band = fake._declared_background("B", "B").model_dump(mode="json")
    rec = next(r for r in bg.read_record() if (r["plant"], r["tier"]) == ("B", "B"))
    stats = wf.record_statistics(rec)
    p = wf.band_placement(stats, band)
    env = wf.band_envelopes(band)
    for key, side in p.items():
        lo, hi = env[key]
        assert side == wf.place(float(stats[key]), lo, hi)
    assert all(v == 0 for v in p.values())  # a clean run inside the band it helped build


# ------------------------------------------------------------------ the integration run


@pytest.fixture(scope="module")
def jailed(tmp_path_factory):
    """P2 in the sandbox on a short generated cell, with the real tools."""
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from tools.runner import run_workflow

    s = load_scenario(REPO / "scenarios" / "S0-01.yaml")
    budget = s.budget.model_copy(update={"simulator_evals": 300, "wall_clock_min": 45.0})
    s = s.model_copy(update={"duration_days": 30.0, "budget": budget})
    root = tmp_path_factory.mktemp("p2store") / "runs"
    run = generate_run(s, "B", plant=load_plant_config("C"), runs_root=root)
    result = run_workflow(run.run_id, "p2", runs_root=root, scenario=s)
    return run, root, result


def test_the_sandboxed_run_writes_the_declared_record(jailed):
    run, root, result = jailed
    out = root / run.run_id / "workflows" / "p2"
    assert {p.name for p in out.iterdir()} == {"state.json", "report.json", "messages.jsonl",
                                               "decisions.jsonl", "summary.json"}  # fmt: skip
    doc = TaskState.model_validate_json((out / "state.json").read_text())
    assert doc.workflow == "p2" and doc.final.completed and result.completed
    report = json.loads((out / "report.json").read_text())
    used = sum(int(v["evaluations"]) for v in report["by_role"].values())
    assert used == result.simulator_evals_used
    assert report["null_table"] is not None  # the reference completed and was placed
    from state.provenance import read_calls

    logged = {c.seq for c in read_calls(root / run.run_id)}
    assert {a.seq for a in doc.actions} <= logged
    assert not report["refusals"]
    assert all(
        r["fallback_used"] and r["attempts"] == 0
        for r in map(json.loads, (out / "decisions.jsonl").read_text().splitlines())
    )
