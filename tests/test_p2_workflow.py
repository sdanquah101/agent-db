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
    # the S1 table shows the coupled channels moved: coupled_outside
    bad = {"sensor": {"channel": "gas_flow", "s1_holds": False,
                      "s1": {"coupled_inside": False}}, "sensor_proposed": True}  # fmt: skip
    out = wf.admit(lab, _table(ns=True, failed=["gas_flow"]), bad)
    assert out["rejected"] == [{"label": "sensor", "code": "coupled_outside"}]
    # the table holds but no reading admits it (the offline fallback): signature_absent
    unread = {"sensor": {"channel": "gas_flow", "s1_holds": False,
                         "s1": {"coupled_inside": True}}, "sensor_proposed": True}  # fmt: skip
    out = wf.admit(lab, _table(ns=True, failed=["gas_flow"]), unread)
    assert out["rejected"] == [{"label": "sensor", "code": "signature_absent"}]
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


def _steps(day: float, channels=("ph", "tan")) -> dict[str, dict[str, Any]]:
    """Residual summaries with a 5-se step at ``day`` on ``channels``, flat elsewhere."""
    out = {}
    for ch in ("gas_flow", "ph", "tan", "cod_total"):
        stepped = ch in channels
        out[ch] = {"channel": ch, "step_z": 5.0 if stepped else 0.5,
                   "step_day": day if stepped else 100.0, "rmse_z": 4.0,
                   "serially_structured": stepped, "most_explanatory": "time"}  # fmt: skip
    return out


def test_the_admitting_change_point_is_on_failed_channels_after_the_first_hrt(cfg):
    """The lead's rulings of 2026-10-08, each with its negative control."""
    attr = cfg["p0"]["attribution"]
    hrt_end = 0.0 + float(attr["transient_d"])  # the early/late test's own boundary
    failed = ["ph", "tan"]
    # a step on the failed channels after the first HRT admits
    tied = wf.tied_change_point(_steps(80.0), failed, attr, hrt_end)
    assert tied["common"] and tied["channels"] == ["ph", "tan"] and tied["day"] == 80.0
    # a step on channels that did not fail does not (P0's arithmetic alone would admit it)
    off = wf.tied_change_point(_steps(80.0), ["gas_flow", "cod_total"], attr, hrt_end)
    assert not off["common"] and off["off_failed"] == ["ph", "tan"]
    assert wf.common_change_point(_steps(80.0), attr)["common"]
    # nor a step shared by one failed and one non-failed channel: it must be common to
    # failed channels
    assert not wf.tied_change_point(_steps(80.0), ["ph", "gas_flow"], attr, hrt_end)["common"]
    # a step inside the first HRT does not admit, on the failed channels too; the boundary
    # day itself is inside (the early/late test's t <= boundary)
    for day in (15.0, hrt_end):
        early = wf.tied_change_point(_steps(day), failed, attr, hrt_end)
        assert not early["common"] and {"ph", "tan"} <= set(early["first_hrt_excluded"])
        assert wf.common_change_point(_steps(day), attr)["common"]
    # through admission: NM on the failed channels, the tied step admits, the untied not
    lab = cfg["p0"]["labels"]
    nm = _table(nm=True, failed=failed)
    assert wf.admit(lab, nm, {"parameter": True, "parameter_proposed": True})["admitted"] == [
        "parameter"
    ]
    out = wf.admit(
        lab,
        nm,
        {
            "parameter": False,
            "parameter_proposed": True,
            "parameter_code": "change_point_not_on_failed_channels_after_hrt",
        },
    )
    assert out["rejected"] == [
        {"label": "parameter", "code": "change_point_not_on_failed_channels_after_hrt"}
    ]  # fmt: skip


def test_the_workflow_ties_the_change_point_and_r3_to_the_failed_channels(monkeypatch, cfg):
    """The same rulings through ``step_profile``: the signatures the verifier admits."""
    fake = FakeTools()
    monkeypatch.setattr(wf, "tools", fake)

    def profiled(residuals: dict[str, Any], failed: list[str]) -> wf.Workflow:
        run = wf.Workflow(json.loads(json.dumps(cfg)))
        run.placement = {}
        for ch in ("gas_flow", "ph", "tan", "cod_total"):
            side = 1 if ch in failed else 0
            for where in ("at_defaults", "after_fit"):
                run.placement[f"{ch}.{where}.mean_z"] = side
            run.placement[f"{ch}.after_fit.rms_z"] = side
            run.placement[f"{ch}.at_defaults.rms_z"] = 0
        run.table = wf.null_table(run.placement)
        run.residuals = residuals
        run.step_profile()
        return run

    hrt_end = float(cfg["p0"]["attribution"]["transient_d"])
    # on the failed channels, after the first HRT: the signature holds, R3 too
    run = profiled(_steps(80.0), ["ph", "tan"])
    assert run.table["NM"] and run.signatures["parameter"] and run.signatures["r3"]
    assert run.signatures["change_point_tied"]["channels"] == ["ph", "tan"]
    # the negative controls: off the failed channels, or inside the first HRT
    run = profiled(_steps(80.0), ["gas_flow", "cod_total"])
    assert run.table["NM"] and not run.signatures["parameter"]
    assert run.signatures["parameter_proposed"]  # P0's arithmetic alone would propose it
    assert run.signatures["parameter_code"] == "change_point_not_on_failed_channels_after_hrt"
    assert not run.signatures["r3"] and run.signatures["structural_proposed"]
    assert run.signatures["structural_code"] == "r3_not_on_failed_channels"
    run = profiled(_steps(hrt_end / 2), ["ph", "tan"])
    assert not run.signatures["parameter"]
    assert run.signatures["r3"]  # R3 is tied to channels, not to days


def test_a_signature_over_a_standing_null_concludes_none_not_unexplained(monkeypatch, cfg):
    """A rejected signature over a clean table is the null case working (the smoke run)."""
    fake = FakeTools()
    monkeypatch.setattr(wf, "tools", fake)
    run = wf.Workflow(json.loads(json.dumps(cfg)))
    run.reference = {"balance": {}, "channels": {}}
    run.placement = {"cod_closure": 0}
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
    run2.placement = {"cod_closure": 0}
    run2.table = _table(nm=True, failed=["ph", "tan"])
    run2.signatures = {}
    run2.prediction = run.prediction
    run2.series = {}
    run2.step_verify()
    assert run2.verdict["verdict"] == "fail" and "revise" in run2.trace
    run2.step_conclude()
    assert run2.classification["rule"] == "null_failed_unexplained"


def _power_record(fake: FakeTools, truth: list[str], *, completed: bool = True) -> dict:
    """A run's record as ``scripts/p2_power.py`` reads it from the report."""
    report = json.loads(fake.run.outputs[wf.REPORT_FILE])
    return {"cell": "X", "truth": truth, "completed": completed, "label": report["label"],
            "outcome": report["outcome"], "rule": report["rule"], "verdict": report["verdict"],
            "null_table": report["null_table"], "signatures": report["signatures"],
            "evaluations_used": 0, "evaluations_total": 1, "wall_s": 1.0}  # fmt: skip


def test_a_run_without_a_null_table_abstains_and_never_reads_none(monkeypatch, cfg):
    """The state must carry a label, so it holds the null one; no count may read it."""
    from scripts import p2_power

    run, fake, doc = run_fake(monkeypatch, cfg, FakeTools(evals=60))
    assert run.verdict["verdict"] == "abstain" and run.table is None
    assert doc["classification"]["rule"] == "abstain:no_null_table"
    assert doc["classification"]["confidence"] == 0.0
    assert "no_null_table" in doc["plan"]["fallbacks"]
    assert {"kinetic_attribution", "parameter_values", "structural_adequacy"} <= set(
        doc["abstentions"]
    )
    # what every count keys on is the outcome, and it is not none
    report = json.loads(fake.run.outputs[wf.REPORT_FILE])
    assert report["outcome"] == "abstain" != report["label"]
    out = p2_power.summarise([_power_record(fake, ["none"])])
    row = out["cells"][0]
    assert row["outcome"] == "abstain" and row["excluded"] and not row["hit"]
    # on a faulted cell it is excluded, not a miss read as none
    out = p2_power.summarise([_power_record(fake, ["sensor"])])
    assert out["hits_faulted"] == "0 of 0 scored"
    assert out["excluded_faulted"] == {"abstain": 1, "pending": 0}
    # a run that stopped before CONCLUDE is pending, whatever label it wrote
    assert p2_power.outcome_of({"completed": False, "rule": "pending", "label": "none"}) == (
        "pending"
    )
    assert p2_power.outcome_of({"completed": True, "rule": "pending", "label": "none"}) == (
        "pending"
    )
    # an older record without the field is derived the same way, from the verdict
    old = {"completed": True, "rule": "abstain:no_null_table", "label": "none",
           "verdict": {"verdict": "abstain"}}  # fmt: skip
    assert p2_power.outcome_of(old) == "abstain"
    # the negative control: a completed run whose null stands is counted as none
    _run, fake, _doc = run_fake(monkeypatch, cfg)
    report = json.loads(fake.run.outputs[wf.REPORT_FILE])
    assert report["outcome"] == report["label"] == "none"
    row = p2_power.summarise([_power_record(fake, ["none"])])["cells"][0]
    assert not row["excluded"] and row["hit"]


def test_a_run_that_places_no_statistic_abstains(monkeypatch, cfg):
    """No statistic placed is no null table, never a null that stands (the review's F-H)."""
    monkeypatch.setattr(wf, "band_placement", lambda stats, band: {})
    run, fake, doc = run_fake(monkeypatch, cfg)
    assert run.verdict["verdict"] == "abstain" and run.table is None
    assert run.verdict["reason"] == "no_statistics_placed"
    assert doc["classification"]["rule"] == "abstain:no_statistics_placed"
    assert "no_statistics_placed" in doc["plan"]["fallbacks"]
    assert json.loads(fake.run.outputs[wf.REPORT_FILE])["outcome"] == "abstain"


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


def test_the_side_nb_failed_on_is_the_one_dated():
    """``nb_side`` in every NB case (the review's F-D); a flipped sign fails here."""
    assert wf.nb_side({"cod_closure": -1, "cod_closure_worst": -1}) == -1
    assert wf.nb_side({"cod_closure": 1, "cod_closure_worst": 1}) == 1
    # NB on the inadmissible count only: the worst window's side, else the mean's
    assert wf.nb_side({"n_cod_inadmissible": 1, "cod_closure_worst": 1}) == 1
    assert wf.nb_side({"n_cod_inadmissible": 1, "cod_closure_worst": -1}) == -1
    assert wf.nb_side({"n_cod_inadmissible": 1, "cod_closure": 1}) == 1
    # no side outside: 0, and the onset test cannot pass on it
    assert wf.nb_side({"n_cod_inadmissible": 1, "cod_closure": 0}) == 0
    step = _windows([0.0, 0.01, 0.25, 0.30, 0.27])
    env = (-0.138, 0.023)
    assert wf.onset_test(step, env, 0, 60.0, ONSET)["code"] == "no_side"
    assert wf.candidate_onsets(step, env, 0, ONSET) == []
    # NB not failed: nothing to date
    assert wf.nb_side({"cod_closure": 1, "cod_closure_worst": 0}) == 0
    assert wf.nb_side({}) == 0
    # the negative control: the side the closures are on dates the step, the other does not
    assert wf.onset_test(step, env, 1, 60.0, ONSET)["passes"]
    assert not wf.onset_test(step, env, -1, 60.0, ONSET)["passes"]


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


def _served(plant: str, tier: str, band: dict[str, Any]) -> dict[str, Any]:
    """A band dict through the band tool's served output schema, as the verifier reads it."""
    from tools.config import load_background
    from tools.schemas import BandRecord, DeclaredBackgroundOutput

    config = load_background()
    return DeclaredBackgroundOutput(
        plant=plant, tier=tier, status=config.provenance.status,
        band_seeds=config.provenance.seeds, procedure=config.procedure, units={},
        **BandRecord.model_validate(band).model_dump(),
    ).model_dump(mode="json")  # fmt: skip


def _band_path_counts(placement=None) -> dict[str, dict[str, int]]:
    """The frozen rule's counts over the 120 leave-one-out runs, by the workflow's path.

    Each run's statistics (``record_statistics``) are placed by ``band_placement`` against
    a band the band driver's own ``aggregate`` builds from the other runs of its (plant,
    tier), served through the tool's output schema: the path the workflow's verifier takes.
    """
    placement = placement or wf.band_placement
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in sorted(bg.read_record(), key=lambda r: r["key"]):
        groups[(r["plant"], r["tier"])].append(r)
    rules = {"NB": wf.n_bal, "NM": wf.n_multi, "NS": wf.n_single,
             "null_rejected": wf.null_rejected, "null_partial": wf.null_partial}  # fmt: skip
    counts = {name: defaultdict(int) for name in rules}
    for (plant, tier), rs in groups.items():
        for i, r in enumerate(rs):
            band = bg.aggregate(rs[:i] + rs[i + 1 :])[plant][tier]
            p = placement(wf.record_statistics(r), _served(plant, tier, band))
            for name, rule in rules.items():
                counts[name][f"{plant}/{tier}"] += int(rule(p))
    return {name: dict(c) for name, c in counts.items()}


def test_the_band_path_reproduces_the_frozen_counts_and_predictions():
    """The pin through ``band_envelopes``/``band_placement`` (the review's F-C)."""
    frozen = json.loads((REPO / "reports" / "background" / "null_rule_loo.json").read_text())
    counts = _band_path_counts()
    for name, per in counts.items():
        assert per == frozen["rules"][name]["per_plant_tier"], name

    # the negative control: the band path without the inadmissible count (half of NB)
    # loses NB failures the frozen rule has
    def without_inadmissible(stats, band):
        return wf.band_placement({k: v for k, v in stats.items() if k != "n_cod_inadmissible"},
                                 band)  # fmt: skip

    mutated = _band_path_counts(without_inadmissible)
    assert mutated["NB"] != frozen["rules"]["NB"]["per_plant_tier"]
    # the four §4.5 cells, placed against the band tool's served output
    from tests.p2_support import FakeTools as Fake

    placed = json.loads((REPO / "reports" / "background" / "dev_cells.json").read_text())
    outcome = {}
    for cell in placed["cells"]:
        _sid, pt = cell["cell"].split(" ")
        plant, tier = pt.split("/")
        served = Fake()._declared_background(plant, tier).model_dump(mode="json")
        stats = {r["statistic"]: r["value"] for r in cell["rows"]
                 if r.get("ruled", True) and r["value"] is not None}  # fmt: skip
        p = wf.band_placement(stats, served)
        outcome[cell["cell"]] = (wf.n_bal(p), wf.n_multi(p), wf.n_single(p),
                                 wf.failed_channels(p))  # fmt: skip
    assert outcome["S0-01 B/A"] == (False, False, False, [])
    assert outcome["S0-01 B/B"] == (False, False, False, [])
    assert outcome["S0-01 B/C"] == (False, True, False, ["digestate_ts", "digestate_vs"])
    assert outcome["S1-01 B/B"] == (True, False, False, ["gas_flow"])


# ------------------------------------------------------------------ the hold-out bit (F-I)


def test_the_holdout_bit_is_the_verifiers_validate_output_on_the_reference(monkeypatch, cfg):
    run, fake, doc = run_fake(monkeypatch, cfg, FakeTools(offsets={"gas_flow": 20.0, "ph": 20.0}))
    holdout = run.tables["holdout"]
    # one logged validate call by the verifier, in standardised form (a zero prediction)
    calls = [a for a in doc["actions"] if a["name"] == "validate"]
    mine = [a for a in calls if a["step"] == "verification.holdout"]
    assert len(mine) == 1 and holdout["call"] == mine[0]["call_index"]
    args = next(a for n, a in fake.calls if n == "validate")
    assert all(not np.any(v) for v in args["predicted"].values())
    # the bit is the tool's output against the band's after-fit maximum
    limit = int(cfg["holdout"]["min_channels_failed"])
    above = [n for n, rms in holdout["rms_z"].items()
             if rms > run.band["channels"][n]["after_fit"]["rms_z"]["max"]]  # fmt: skip
    assert {"gas_flow", "ph"} <= set(above)
    assert holdout["holdout_failed"] is (len(above) >= limit) is True
    assert run.verdict["holdout_failed"] is True
    # it reads the reference prediction: a later prediction (a subset fit's) changes nothing
    before = dict(holdout["rms_z"])
    shifted = fake._simulate(wf.MODEL)
    shifted.outputs = {k: v + 1e6 for k, v in shifted.outputs.items()}
    run.prediction = shifted
    assert run.holdout_check()["rms_z"] == before
    # the negative control: a clean record passes the hold-out
    run, _fake, _doc = run_fake(monkeypatch, cfg)
    assert run.tables["holdout"]["holdout_failed"] is False

    # and a failed call leaves the bit unknown, never passed
    def broken(**kw: Any) -> Any:
        raise wf.tools.ToolError("validate failed")

    fake = FakeTools()
    monkeypatch.setattr(fake, "_validate", broken)
    run, _fake, _doc = run_fake(monkeypatch, cfg, fake)
    assert run.tables["holdout"]["holdout_failed"] is None
    out = wf.admit(cfg["p0"]["labels"], _table(nm=True),
                   {"r3": True, "structural": False, "structural_proposed": True,
                    "holdout_failed": None})  # fmt: skip
    assert out["rejected"] == [{"label": "structural", "code": "holdout_unavailable"}]


# ------------------------------------------------------------------ F-J


def test_the_rule_names_no_null_component_the_verifier_did_not_evaluate(monkeypatch, cfg):
    fake = FakeTools()
    monkeypatch.setattr(wf, "tools", fake)
    c = json.loads(json.dumps(cfg))
    c["ablation"]["verifier"] = False
    run = wf.Workflow(c)
    run.reference = {"balance": {}, "channels": {}}
    run.placement = {"cod_closure": 0}
    run.signatures = {"parameter": True}
    run.prediction = fake._simulate(wf.MODEL)
    run.series = {}
    run.step_verify()
    run.step_conclude()
    assert run.classification["rule"] == "unverified+parameter"
    # the negative control: with the verifier on, the evaluated component is named
    run2 = wf.Workflow(json.loads(json.dumps(cfg)))
    run2.reference = {"balance": {}, "channels": {}}
    run2.placement = {"cod_closure": 0}
    run2.table = _table(nm=True, failed=["ph", "tan"])
    run2.signatures = {"parameter": True}
    run2.prediction = run.prediction
    run2.series = {}
    run2.step_verify()
    run2.step_conclude()
    assert run2.classification["rule"] == "NM+parameter"


def test_the_reference_weights_use_the_served_noise_floors(monkeypatch, cfg):
    """The floors are the band's served procedure's, not p0.yaml's (the review's F-J)."""
    fake = FakeTools()
    served = fake._declared_background

    def floors_changed(plant, tier):
        out = served(plant, tier)
        proc = out.procedure.model_copy(update={"min_relative_sd": 0.5})
        return out.model_copy(update={"procedure": proc})

    monkeypatch.setattr(fake, "_declared_background", floors_changed)
    run, fake, _doc = run_fake(monkeypatch, cfg, fake)
    lsq = next(a for n, a in fake.calls if n == "fit_lsq")
    gas = next(d for d in lsq["data"] if d["output"] == "q_gas_stp_dry")
    s = run.series["gas_flow"]
    floors = {"min_relative_sd": 0.5, "sd_floor_abs": served("B", "B").procedure.sd_floor_abs}
    keep = (s.t >= run.cal[0]) & (s.t <= run.cal[1])
    np.testing.assert_allclose(gas["sd"], s.weights(floors)[keep])
    # the negative control: P0's floors give other weights
    assert not np.allclose(gas["sd"], s.sd[keep])


def test_the_summary_counts_each_roles_cost_from_the_call_log(tmp_path):
    """``summary.json``'s ``by_role`` (design §9): the log's numbers, the action's role."""
    import types

    from state.provenance import CallRecord
    from tools.runner import by_role

    lines = [
        CallRecord(seq=0, t_utc="x", name="read_sensors", version="1", args_hash="a",
                   runtime_s=0.1, outcome="ok", n_evaluations=0, assay_units=0),
        CallRecord(seq=1, t_utc="x", name="simulate", version="1", args_hash="b",
                   runtime_s=2.0, outcome="ok", n_evaluations=1, assay_units=0),
        CallRecord(seq=2, t_utc="x", name="fit_lsq", version="1", args_hash="c",
                   runtime_s=30.0, outcome="ok", n_evaluations=40, assay_units=0),
        CallRecord(seq=3, t_utc="x", name="request_assay", version="1", args_hash="d",
                   runtime_s=0.2, outcome="ok", n_evaluations=0, assay_units=1),
        CallRecord(seq=4, t_utc="x", name="validate", version="1", args_hash="e",
                   runtime_s=0.1, outcome="ok", n_evaluations=0, assay_units=0),
    ]  # fmt: skip
    (tmp_path / "calls.jsonl").write_text("".join(c.to_json() + "\n" for c in lines))
    act = types.SimpleNamespace
    state = types.SimpleNamespace(actions=[
        act(seq=1, step="calibration.read"), act(seq=2, step="calibration.reference"),
        act(seq=3, step="design.assay"), act(seq=4, step="verification.holdout"),
    ])  # fmt: skip
    out = by_role(tmp_path, state, first_seq=1)
    assert out["calibration"]["evaluations"] == 41 and out["calibration"]["calls"] == 2
    assert out["design"]["assay_units"] == 1 and out["verification"]["calls"] == 1
    assert "unattributed" not in out  # seq 0 is before this launch
    assert sum(r["evaluations"] for r in out.values()) == 41
    # the negative control: a logged call no action names is counted, not dropped
    out = by_role(tmp_path, state, first_seq=0)
    assert out["unattributed"]["calls"] == 1


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
    summary = json.loads((out / "summary.json").read_text())
    assert sum(int(v["evaluations"]) for v in summary["by_role"].values()) == (
        result.simulator_evals_used
    )
    assert report["outcome"] == report["label"]  # completed, placed: not excluded
    assert report["null_table"] is not None  # the reference completed and was placed
    from state.provenance import read_calls

    logged = {c.seq for c in read_calls(root / run.run_id)}
    assert {a.seq for a in doc.actions} <= logged
    assert not report["refusals"]
    assert all(
        r["fallback_used"] and r["attempts"] == 0
        for r in map(json.loads, (out / "decisions.jsonl").read_text().splitlines())
    )
