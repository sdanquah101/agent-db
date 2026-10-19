"""The lead's word of 2026-10-19, "Implement your recommendations": the P2 tidy-up.

A. The decision layer (one freeze move):

- A1 (D-2). ``dq.trust``'s template states the first-HRT spike rule the code enforces; a
  proposal that quarantines a first-HRT spike is still refused (the control).
- A2 (D-3). ``verify.differential``'s ``rejected[].label`` is the label vocabulary, not a
  free string, and ``holdout_passed`` is allowed with ``structural`` only. Attempt 2's own
  answers are the fixtures: it set aside ``s1`` (no label) and ``sensor`` as
  ``holdout_passed``. The control: a valid rejection is still accepted. The mutation: the
  pre-ruling ``Rejected`` accepts both.
- A3 (cost). A request whose answer cannot change the outcome is not made: ``cal.split``
  and ``cal.bound`` (answers unused in deliverable 3) and a ``dq.trust`` shown nothing.
  The outcome is the offline decider's exactly; the controls (a ``dq.trust`` with
  something shown, ``verify.differential``) are still asked; the mutation (the switch
  emptied) asks them again.

B. Small fixes: B1 the first-HRT boundary, B2 the whole-record QC codes never shown to
``dq.trust``, B3 ``_jsonable`` refuses what has no JSON form and writes NaN as ``null``.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pytest
from pydantic import ValidationError

from state.task_state import TaskState
from tests.p2_support import FakeTools
from tests.test_p2_decision_fixes import ScriptedPoint, SpikeAt
from tools.workflow_config import load_p2, sandbox_config
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]
ATTEMPT2 = REPO / "reports" / "p2_pilot" / "attempt2"


@pytest.fixture(scope="module")
def cfg() -> dict[str, Any]:
    return json.loads(json.dumps(sandbox_config(load_p2())))


def _run(monkeypatch: pytest.MonkeyPatch, cfg: dict, fake: FakeTools, respond: Any) -> Any:
    monkeypatch.setattr(wf, "tools", fake)
    run = wf.Workflow(json.loads(json.dumps(cfg)), respond)
    run.run()
    TaskState.model_validate(json.loads(fake.run.outputs[wf.STATE_FILE]))
    return run


def _records(fake: FakeTools) -> list[dict[str, Any]]:
    return [json.loads(x) for x in fake.run.outputs[wf.DECISIONS_FILE].splitlines()]


class Counting:
    """The offline decider that also notes every point it is asked."""

    def __init__(self) -> None:
        """Nothing asked yet."""
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, point: str, template: str, inputs: dict[str, Any]) -> None:
        self.asked.append((point, json.loads(wf.to_json(inputs))))
        return None


class AtBound(FakeTools):
    """A fit with its first parameter at a bound, so ``cal.bound`` has something to read."""

    def _fit_lsq(self, parameters: Any, max_nfev_per_start: int = 40, **kw: Any) -> Any:
        out = super()._fit_lsq(parameters, max_nfev_per_start, **kw)
        out.at_bound = [next(iter(parameters))]
        return out


# ------------------------------------------------------------------ A1


def test_the_dq_trust_template_states_the_first_hrt_spike_rule_the_code_enforces(monkeypatch, cfg):
    text = sandbox_config(load_p2())["templates"]["dq.trust"]["text"]
    assert "first hydraulic retention time" in text and "not quarantinable" in text
    assert "`first_hrt_d`" in text  # the input the rule is stated against
    # the control: the code still refuses a proposal over a first-HRT spike. FakeTools'
    # QC flags a spike at day 5 on every sensor, inside the first HRT
    answer = {"sensor": "ph", "quarantine": [[5.0, 5.0]], "reason": "spike_run"}
    fake = FakeTools()
    script = ScriptedPoint("dq.trust", [answer] * 2, sensor="ph")
    run = _run(monkeypatch, cfg, fake, script)
    assert run.first_hrt > 5.0 and script.seen  # asked: the spike is shown
    rec = [r for r in _records(fake) if r["point"] == "dq.trust"
           and r["output"]["sensor"] == "ph"][-1]  # fmt: skip
    assert rec["fallback_used"] and rec["failures"] == ["refused by the code constraint"] * 2
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    refused = [f for f in doc["tool_failures"] if f["name"] == "p2.dq.refused"]
    assert refused and all("first_hrt_spike" in f["message"] for f in refused)
    assert doc["data_quality"]["ph"]["quarantined_windows"] == []  # the fallback trims it


# ------------------------------------------------------------------ A2


def _attempt2_rejections() -> list[dict[str, Any]]:
    """Every ``rejected`` entry attempt 2's model answered ``verify.differential`` with."""
    out = []
    for path in sorted(ATTEMPT2.glob("run_*/llm_calls.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec["provenance"]["point"] != "verify.differential":
                continue
            for block in (rec.get("response") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    out += block["input"].get("rejected") or []
    return out


class PreRulingRejected(wf._Out):
    """The mutation: ``Rejected`` before the word of 2026-10-19 (a free label, any code)."""

    label: str
    code: Literal[
        "null_not_failed", "signature_absent", "coupled_outside", "holdout_passed", "superseded"
    ]


def test_a_rejected_label_is_the_vocabulary_and_holdout_passed_is_structural_only(cfg):
    seen = _attempt2_rejections()
    assert {"label": "s1", "code": "signature_absent"} in seen  # not a label at all
    assert {"label": "sensor", "code": "holdout_passed"} in seen  # the hold-out beside sensor
    for entry in ({"label": "s1", "code": "signature_absent"},
                  {"label": "sensor", "code": "holdout_passed"},
                  {"label": "none", "code": "signature_absent"},  # never a candidate
                  {"label": "Sensor", "code": "signature_absent"},
                  {"label": "state ", "code": "signature_absent"}):  # fmt: skip
        with pytest.raises(ValidationError):
            wf.Rejected.model_validate(entry)
        with pytest.raises(ValidationError):
            wf.VerifyDifferential.model_validate({"label": "none", "rejected": [entry]})
    # the control: every candidate label with an ordinary code, and structural with the
    # hold-out code, are accepted
    for label in ("sensor", "influent", "state", "parameter", "structural"):
        assert wf.Rejected.model_validate({"label": label, "code": "signature_absent"})
    assert wf.Rejected.model_validate({"label": "structural", "code": "holdout_passed"})
    # the vocabulary is the configuration's five classes, the null label excluded
    labels = cfg["p0"]["labels"]
    alternatives = set(re.fullmatch(r"\^\((.*)\)\$", wf.CANDIDATE_PATTERN).group(1).split("|"))
    assert alternatives == set(labels.values()) - {labels["none"]}
    # the tool offers it: the model is told the constraint it is held to
    schema = wf.decision_tool("verify.differential")["input_schema"]
    assert schema["$defs"]["Rejected"]["properties"]["label"]["pattern"] == wf.CANDIDATE_PATTERN
    # code's own fallback still validates on every path admit() can take
    lab = {k: v for k, v in labels.items()}
    signatures = {f"{k}_proposed": True for k in
                  ("sensor", "influent", "initial_state", "parameter", "structural")}  # fmt: skip
    signatures |= {"r3": True, "holdout_failed": False}
    verdict = wf.admit(lab, {"NB": False, "NM": False, "NS": False}, signatures)
    rejected = [{"label": r["label"], "code": wf.design_code(r["code"])}
                for r in verdict["rejected"]]  # fmt: skip
    assert {"label": "structural", "code": "holdout_passed"} in rejected
    wf.VerifyDifferential.model_validate({"label": "none", "rejected": rejected})
    # the mutation: the pre-ruling schema accepts both of attempt 2's answers
    assert PreRulingRejected.model_validate({"label": "s1", "code": "signature_absent"})
    assert PreRulingRejected.model_validate({"label": "sensor", "code": "holdout_passed"})


# ------------------------------------------------------------------ A3


def _outcome(fake: FakeTools) -> dict[str, Any]:
    """Everything a run writes but its decision records (and the run's own timings)."""
    state = json.loads(fake.run.outputs[wf.STATE_FILE])
    report = json.loads(fake.run.outputs[wf.REPORT_FILE])
    for doc in (state, report):
        doc.pop("by_role", None)
    return {"state": state, "report": report}


def _ask_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mutation: the switch emptied and the nothing-shown reason ignored (pre-A3)."""
    monkeypatch.setattr(wf, "NOT_ASKED_UNUSED", frozenset())
    decide = wf.Decider.decide

    def asks(self: Any, point: str, inputs: Any, fallback: Any, **kw: Any) -> Any:
        kw.pop("not_asked", None)
        return decide(self, point, inputs, fallback, **kw)

    monkeypatch.setattr(wf.Decider, "decide", asks)


@pytest.mark.parametrize("make", [FakeTools, AtBound, SpikeAt], ids=["plain", "at_bound",
                                                                     "holdout_spike"])  # fmt: skip
def test_no_request_whose_answer_cannot_change_the_outcome_and_the_outcome_is_unchanged(
    monkeypatch, cfg, make
):
    fake = make()
    respond = Counting()
    _run(monkeypatch, cfg, fake, respond)
    asked = [p for p, _ in respond.asked]
    after = _outcome(fake)
    records = _records(fake)
    assert "cal.split" not in asked and "cal.bound" not in asked
    skipped = {(r["point"], r["reason"]) for r in records if r["status"] == "not_asked"}
    assert ("cal.split", wf.UNUSED_REASON) in skipped
    if make is AtBound:
        assert ("cal.bound", wf.UNUSED_REASON) in skipped
    if make is SpikeAt:  # pH's only spike is in the hold-out: nothing shown, not asked
        assert ("dq.trust", wf.NOTHING_SHOWN_REASON) in skipped
        assert all(i["sensor"] != "ph" for p, i in respond.asked if p == "dq.trust")
    assert all(r["attempts"] == 0 and r["fallback_used"] for r in records
               if r["status"] == "not_asked")  # fmt: skip
    # the controls: a dq.trust with something shown and the differential are still asked
    assert "verify.differential" in asked
    assert any(p == "dq.trust" and i["flagged_windows"] for p, i in respond.asked)

    # the mutation: everything asked again, offline, so the same fallbacks are taken
    _ask_everything(monkeypatch)
    fake = make()
    respond = Counting()
    _run(monkeypatch, cfg, fake, respond)
    asked_before = [p for p, _ in respond.asked]
    assert "cal.split" in asked_before
    if make is AtBound:
        assert "cal.bound" in asked_before
    if make is SpikeAt:
        assert any(p == "dq.trust" and i["sensor"] == "ph" and not i["flagged_windows"]
                   for p, i in respond.asked)  # fmt: skip
    # and the outcome is identical: not asking is the offline decider's outcome exactly
    assert _outcome(fake) == after
    outputs = {(r["point"], json.dumps(r["output"], sort_keys=True)) for r in _records(fake)}
    assert outputs == {(r["point"], json.dumps(r["output"], sort_keys=True)) for r in records}


def test_the_not_asked_path_still_checks_its_inputs():
    templates = {p: {"text": "t", "sha256": "s"} for p in wf.DECISIONS}
    d = wf.Decider(templates, wf.offline_responder)
    with pytest.raises(wf.DecisionError, match="undeclared"):
        d.decide("cal.split", {"steps": {}, "extra": 1}, {"common_step_day": None})
    out = d.decide("cal.split", {"steps": {}}, {"common_step_day": None, "channels": []})
    assert out.common_step_day is None and d.records[-1]["status"] == "not_asked"
    with pytest.raises(ValidationError):  # the fallback is still validated
        d.decide("cal.bound", {"parameter": "x"}, {"code": "not_a_code"})


# ------------------------------------------------------------------ B1


class FeedOnHoldoutStart(FakeTools):
    """A feed log whose hold-out start day carries a large flow."""

    holdout_start = 0.0

    def _feed_loads(self, model: str) -> Any:
        out = super()._feed_loads(model)
        out.q_m3_d = np.where(out.t == self.holdout_start, 6000.0, out.q_m3_d)
        return out


def _first_hrt(
    module: Any, monkeypatch: pytest.MonkeyPatch, cfg: dict, holdout_start: float
) -> tuple[float, float]:
    fake = FeedOnHoldoutStart()
    fake.holdout_start = holdout_start
    monkeypatch.setattr(module, "tools", fake)
    run = module.Workflow(json.loads(json.dumps(cfg)), module.offline_responder)
    run.run()
    v = float(cfg["plant_geometry"][run.plant]["V_liq_m3"])
    return run.first_hrt, v / 60.0


def test_the_first_hrt_and_the_sample_count_read_the_same_window(monkeypatch, cfg, tmp_path):
    # the hold-out start day's feed (6000 m3/d, a hundred times the rest) is the hold-out's,
    # as sample_counts already counts it: the first HRT is V over the mean before it
    monkeypatch.setattr(wf, "tools", FakeTools())
    probe = wf.Workflow(json.loads(json.dumps(cfg)), wf.offline_responder)
    probe.run()
    assert probe.cal[1] == probe.holdout[0]  # the boundary in question
    got, want = _first_hrt(wf, monkeypatch, cfg, probe.holdout[0])
    assert got == pytest.approx(want)
    # the mutation: the pre-B1 window (t <= cal_end) takes the hold-out start's feed in
    source = (REPO / "workflows" / "p2_multi_agent" / "workflow.py").read_text(encoding="utf-8")
    mutated = source.replace("(t < self.holdout[0]) & np.isfinite(q)",
                             "(t <= self.cal[1]) & np.isfinite(q)")  # fmt: skip
    assert mutated != source
    path = tmp_path / "workflow_mutated_b1.py"
    path.write_text(mutated, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("workflow_mutated_b1", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "workflow_mutated_b1", module)
    spec.loader.exec_module(module)
    got, want = _first_hrt(module, monkeypatch, cfg, probe.holdout[0])
    assert got < 0.9 * want


# ------------------------------------------------------------------ B2


class WholeRecordCodes(FakeTools):
    """QC raises drift and informative missingness on pH, beside one calibration spike."""

    def _data_qc(self, series: Any, event_windows: Any, **kw: Any) -> Any:
        out = super()._data_qc(series, event_windows, **kw)
        for r in out.results:
            if r.name == "ph":
                r.flags = ["drift", "informative_missingness", "spikes"]
                r.spikes = [44.0]
                r.drift_flag, r.informative_missingness = True, True
        return out


def test_whole_record_qc_codes_are_never_shown_to_dq_trust(monkeypatch, cfg):
    # the helper: whatever the masks, the codes are only those whose evidence is shown
    rng = np.random.default_rng(3)
    t = np.arange(0.0, 200.0)
    value = np.ones(t.size)
    for _ in range(50):
        flat, spikes = rng.random(t.size) < 0.05, rng.random(t.size) < 0.05
        windows, _, codes = wf.shown_to_dq_trust(t, value, flat, spikes, 0.0, 150.0)
        assert set(codes) <= {"flatline", "spikes"}
        assert bool(codes) == bool(windows)  # a code only with its window
    # the workflow: pH's drift and informative missingness never reach the model
    script = ScriptedPoint("dq.trust", [], sensor="ph")
    _run(monkeypatch, cfg, WholeRecordCodes(), script)
    (shown,) = script.seen
    assert shown["qc_findings"] == ["spikes"]  # the control: the shown spike's code
    assert shown["flagged_windows"] == [[44.0, 44.0]]
    # the mutation: QC's own flags passed through, as before the review of f5aa41f (B-1)
    original = wf.shown_to_dq_trust

    def with_flags(*a: Any) -> Any:
        windows, count, codes = original(*a)
        return windows, count, [*codes, "drift", "informative_missingness"]

    monkeypatch.setattr(wf, "shown_to_dq_trust", with_flags)
    script = ScriptedPoint("dq.trust", [], sensor="ph")
    _run(monkeypatch, cfg, WholeRecordCodes(), script)
    assert "drift" in script.seen[0]["qc_findings"]


# ------------------------------------------------------------------ B3


def _pre_b3(x: Any) -> Any:
    """The mutation: ``_jsonable`` as it was (1-D arrays, ``str()`` for anything else)."""
    if isinstance(x, np.ndarray):
        return [wf._f(v) for v in x.tolist()]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return wf._f(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return str(x)


def test_jsonable_writes_nan_as_null_and_refuses_what_has_no_json_form():
    value = {
        "grid": np.array([[1.0, np.nan], [np.inf, 2.0]]),
        "nested": [float("nan"), (np.float32(1.5), np.int64(3), np.bool_(True))],
        "label": "sensor",
        "none": None,
    }
    assert wf._jsonable(value) == {
        "grid": [[1.0, None], [None, 2.0]],
        "nested": [None, [1.5, 3, True]],
        "label": "sensor",
        "none": None,
    }
    text = wf.to_json(value, sort_keys=True)
    assert "NaN" not in text and "Infinity" not in text
    for bad in (object(), Path("x"), {"k": {1, 2}}, [b"bytes"]):
        with pytest.raises(TypeError):
            wf._jsonable(bad)
        with pytest.raises(TypeError):
            wf.to_json(bad)
    # the control: plain JSON values pass unchanged
    plain = {"a": [1, 2.5, "x", True, None]}
    assert wf._jsonable(plain) == plain
    # the mutation: the pre-B3 handler, as json.dumps's default, writes an object as its
    # str() and a NaN float as JSON's invalid NaN, and breaks on a 2-D array
    assert json.dumps({"o": object()}, default=_pre_b3).startswith('{"o": "<object object')
    assert "NaN" in json.dumps({"x": float("nan")}, default=_pre_b3)
    with pytest.raises(TypeError):
        json.dumps({"g": np.array([[1.0, 2.0]])}, default=_pre_b3)
