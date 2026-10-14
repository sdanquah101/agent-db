"""The lead's ruling of 2026-10-14: the three decision-layer defects attempt 1 showed.

Attempt 1's actual inputs (``reports/p2_pilot/attempt1/run_c2509d5aec41/llm_calls.jsonl``)
are the fixtures. Each fix has a negative control and a mutation that reverts it, through the
module-level helper the fix lives in, and fails a test.

a. ``verify.differential`` offers its allowed labels: ``none`` is offered where nothing is
   admitted (the model answered ``null``); the set-aside codes are the design's enum.
b. ``dq.trust`` is shown the calibration window only: day 172 of a hold-out starting at
   day 150 is no longer shown; a refused quarantine is logged and counted.
c. ``cal.split`` accepts any valid common step: ``tan`` + ``alkalinity`` around days
   105-112 is accepted; ``tan`` + ``cod_total`` (z 1.43) is still refused.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from state.task_state import TaskState
from tests.p2_support import FakeTools
from tests.test_p2_live import _answer, _gateway, _request
from tools.llm import ModelError
from tools.p2_live import check_p2_frozen, frozen_record_sha256
from tools.workflow_config import load_p2, sandbox_config
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]
ATTEMPT1 = REPO / "reports" / "p2_pilot" / "attempt1" / "run_c2509d5aec41" / "llm_calls.jsonl"


@pytest.fixture(scope="module")
def cfg() -> dict[str, Any]:
    return json.loads(json.dumps(sandbox_config(load_p2())))


@pytest.fixture(scope="module")
def attempt1() -> dict[str, dict[str, Any]]:
    """Attempt 1's inputs by decision point (the first attempt of each), as the jail built them."""
    out: dict[str, dict[str, Any]] = {}
    for line in ATTEMPT1.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        point = rec["provenance"]["point"]
        messages = rec.get("messages") or []
        if point in out or not messages:
            continue
        # the jail serialises its inputs through str(): a Python literal inside a JSON
        # string (reported in docs/decisions.md, 2026-10-14; not changed by this ruling)
        out[point] = ast.literal_eval(json.loads(messages[-1]["content"]))
    return out


def _run(monkeypatch: pytest.MonkeyPatch, cfg: dict, fake: FakeTools, respond: Any) -> Any:
    monkeypatch.setattr(wf, "tools", fake)
    run = wf.Workflow(json.loads(json.dumps(cfg)), respond)
    run.run()
    TaskState.model_validate(json.loads(fake.run.outputs[wf.STATE_FILE]))
    return run


def _records(fake: FakeTools, point: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in fake.run.outputs[wf.DECISIONS_FILE].splitlines()
            if json.loads(x)["point"] == point]  # fmt: skip


# ------------------------------------------------------------------ a. verify.differential


def test_none_is_offered_where_nothing_is_admitted(attempt1):
    inputs = attempt1["verify.differential"]
    assert inputs["admitted"] == []  # attempt 1: the null stood, nothing admitted
    inputs = {**inputs, "allowed_labels": ["none"]}
    tool = wf.decision_tool("verify.differential", inputs)
    assert tool["input_schema"]["properties"]["label"]["enum"] == ["none"]
    # the frozen tool is the one without the per-call enum
    frozen_form = wf.decision_tool("verify.differential")["input_schema"]["properties"]["label"]
    assert "enum" not in frozen_form
    assert wf.base_tool(tool, "verify.differential") == wf.decision_tool("verify.differential")
    # with admitted labels, they are offered beside none
    tool = wf.decision_tool("verify.differential", {**inputs, "allowed_labels": ["sensor", "none"]})
    assert tool["input_schema"]["properties"]["label"]["enum"] == ["sensor", "none"]
    # the template states the allowed values, the literal none included
    text = sandbox_config(load_p2())["templates"]["verify.differential"]["text"]
    assert "`none`" in text and "allowed_labels" in text
    assert all(code in text for code in wf.REJECTION_CODES)
    # the set-aside codes: attempt 1's answer is refused by the schema, the design's accepted
    with pytest.raises(ValidationError):
        wf.VerifyDifferential.model_validate(
            {"label": "none", "rejected": [{"s1": "not_admitted"}]}
        )
    with pytest.raises(ValidationError):
        wf.VerifyDifferential.model_validate(
            {"label": "none", "rejected": [{"label": "parameter", "code": "not_admitted"}]}
        )
    ok = wf.VerifyDifferential.model_validate(
        {"label": "none", "rejected": [{"label": "parameter", "code": "signature_absent"}]}
    )
    assert ok.rejected[0].code == "signature_absent"
    # code's finer codes map onto the design's for the fallback
    assert wf.design_code("change_point_not_on_failed_channels_after_hrt") == "signature_absent"
    assert wf.design_code("holdout_unavailable") == "signature_absent"
    assert all(wf.design_code(c) == c for c in wf.REJECTION_CODES)
    # other points are untouched by the narrowing
    assert wf.narrow_tool(wf.decision_tool("cal.bound"), "cal.bound", {}) == wf.decision_tool(
        "cal.bound"
    )
    # the point cannot be asked without its allowed labels; with them it can
    templates = {p: {"text": "t", "sha256": "s"} for p in wf.DECISIONS}
    d = wf.Decider(templates, wf.offline_responder)
    asked = {k: v for k, v in inputs.items() if k != "allowed_labels"}
    with pytest.raises(wf.DecisionError, match="allowed_labels"):
        d.decide("verify.differential", asked, {"label": "none", "rejected": []})
    assert (
        d.decide("verify.differential", inputs, {"label": "none", "rejected": []}).label == "none"
    )
    assert d.records[-1]["offered"] == {"label": ["none"]}


def test_the_gateway_accepts_the_per_call_enum_and_nothing_else(tmp_path, attempt1):
    sent: list[dict[str, Any]] = []

    def policy(params: dict[str, Any]) -> dict[str, Any]:
        sent.append(params)
        return _answer("verify_differential", {"label": "none", "rejected": []})

    gw = _gateway(tmp_path, policy)
    inputs = {**attempt1["verify.differential"], "allowed_labels": ["none"]}
    req = {**_request("verify.differential", inputs),
           "tools": [wf.decision_tool("verify.differential", inputs)]}  # fmt: skip
    out = gw.complete(req)
    assert out["response"]["content"][0]["input"]["label"] == "none"
    assert sent[0]["tools"][0]["input_schema"]["properties"]["label"]["enum"] == ["none"]

    # the negative controls, refused before sending: an enum without none, an empty one,
    # a duplicate, another field narrowed, another schema change
    def with_label(label: dict[str, Any]) -> dict[str, Any]:
        tool = json.loads(json.dumps(wf.decision_tool("verify.differential")))
        tool["input_schema"]["properties"]["label"] = label
        return {**req, "tools": [tool]}

    base = wf.decision_tool("verify.differential")["input_schema"]["properties"]["label"]
    bad = [
        with_label({**base, "enum": ["sensor"]}),
        with_label({**base, "enum": []}),
        with_label({**base, "enum": ["none", "none"]}),
        with_label({**base, "enum": ["none"], "description": "pick one"}),
        {**req, "tools": [wf.decision_tool("verify.differential")]} | {"system": "x"},
    ]
    tool = json.loads(json.dumps(wf.decision_tool("verify.differential", inputs)))
    tool["input_schema"]["$defs"]["Rejected"]["properties"]["code"]["enum"] = ["x"]
    bad.append({**req, "tools": [tool]})
    for request in bad:
        with pytest.raises(ModelError):
            gw.complete(request)
    assert len(sent) == 1
    # another point's tool is not narrowed by its inputs, and is still checked as before
    gw.complete(_request("cal.bound", {"parameter": "k", "bounds": [0, 1], "estimate": 1,
                                       "sd": 0.1}))  # fmt: skip
    assert len(sent) == 2  # a valid request of another point is sent as before


class ScriptedPoint:
    """A responder that answers one point with a script and leaves the rest offline."""

    def __init__(self, point: str, answers: list[Any], sensor: str | None = None) -> None:
        """Answer ``point`` (for ``sensor`` only, if given) with ``answers``, then nothing."""
        self.point, self.answers, self.seen, self.sensor = point, list(answers), [], sensor

    def __call__(self, point: str, template: str, inputs: dict[str, Any]) -> Any:
        if point != self.point or (self.sensor is not None and inputs.get("sensor") != self.sensor):
            return None
        self.seen.append(json.loads(json.dumps(inputs, default=str)))
        return self.answers.pop(0) if self.answers else None


def test_the_verifier_offers_the_allowed_labels_and_still_accepts_only_them(monkeypatch, cfg):
    # attempt 1's answer, then a valid one: the first is refused by the schema (its
    # rejected entry), the second decided; the allowed labels are the input and the record
    null_then_none = [{"label": "null", "rejected": [{"s1": "not_admitted"}]},
                      {"label": "none", "rejected": []}]  # fmt: skip
    fake = FakeTools()
    script = ScriptedPoint("verify.differential", null_then_none)
    run = _run(monkeypatch, cfg, fake, script)
    rec = _records(fake, "verify.differential")[-1]
    assert rec["status"] == "decided" and rec["attempts"] == 2
    assert rec["failures"] == ["schema: 2 errors"] or rec["failures"][0].startswith("schema")
    assert rec["offered"] == {"label": ["none"]} and script.seen[0]["allowed_labels"] == ["none"]
    assert run.verdict["label"] == "none"
    # the code's acceptance is unchanged: a label outside admitted + none is refused
    fake = FakeTools()
    _run(
        monkeypatch,
        cfg,
        fake,
        ScriptedPoint("verify.differential", [{"label": "sensor", "rejected": []}] * 2),
    )
    rec = _records(fake, "verify.differential")[-1]
    assert rec["fallback_used"] and rec["failures"] == ["refused by the code constraint"] * 2
    # the fallback carries the design's codes, and the verdict keeps code's finer ones
    fake = FakeTools()
    run = _run(monkeypatch, cfg, fake, wf.offline_responder)
    rec = _records(fake, "verify.differential")[-1]
    assert all(r["code"] in wf.REJECTION_CODES for r in rec["output"]["rejected"])
    assert run.verdict["rejected"] == run.verdict["rejected"]  # present, unchanged in form
    # the mutation: the tool not narrowed offers no enum, and the gateway refuses it
    monkeypatch.setattr(wf, "narrow_tool", lambda tool, point, inputs: tool)
    tool = wf.decision_tool("verify.differential", {"allowed_labels": ["none"]})
    assert "enum" not in tool["input_schema"]["properties"]["label"]


# ------------------------------------------------------------------ b. dq.trust


def test_dq_trust_is_shown_the_calibration_window_only():
    # attempt 1 r0: T 200, the hold-out from day 150, pH's one spike at day 172
    t = np.arange(0.0, 200.0)
    value = np.ones(t.size)
    flagged = np.zeros(t.size, bool)
    flagged[172] = True
    windows, count = wf.shown_to_dq_trust(t, value, flagged, 0.0, 150.0)
    assert windows == [] and count == 150  # day 172 is not shown; days 0..149 counted
    # a window crossing the start is trimmed to its last calibration sample
    flagged[:] = False
    flagged[147:153] = True
    windows, _ = wf.shown_to_dq_trust(t, value, flagged, 0.0, 150.0)
    assert windows == [[147.0, 149.0]]
    # the negative control: windows inside the calibration window are shown whole
    flagged[:] = False
    flagged[[44, 46]] = True
    assert wf.shown_to_dq_trust(t, value, flagged, 0.0, 150.0)[0] == [[44.0, 44.0], [46.0, 46.0]]
    # missing samples are not counted; the hold-out's are not either
    value[10] = np.nan
    assert wf.shown_to_dq_trust(t, value, flagged, 0.0, 150.0)[1] == 149


class SpikeAt(FakeTools):
    """QC flags one pH spike at ``day``."""

    day = 172.0

    def _data_qc(self, series: Any, event_windows: Any, **kw: Any) -> Any:
        out = super()._data_qc(series, event_windows, **kw)
        for r in out.results:
            if r.name == "ph":
                r.flags, r.spikes = ["spikes"], [self.day]
        return out


def test_a_hold_out_spike_is_not_shown_and_a_hold_out_quarantine_is_refused_and_counted(
    monkeypatch, cfg
):
    quarantine_172 = {"sensor": "ph", "quarantine": [[172.0, 172.0]], "reason": "spike_run"}
    fake = SpikeAt()
    script = ScriptedPoint("dq.trust", [quarantine_172] * 2, sensor="ph")
    _run(monkeypatch, cfg, fake, script)
    shown = [s for s in script.seen if s["sensor"] == "ph"]
    assert shown and shown[0]["flagged_windows"] == [] and shown[0]["sample_counts"] <= 150
    assert all(b < 150.0 for s in script.seen for _, b in s["flagged_windows"])
    # defence in depth: the quarantine over the hold-out is refused, logged and counted
    rec = [r for r in _records(fake, "dq.trust") if r["output"]["sensor"] == "ph"][-1]
    assert rec["fallback_used"] and rec["failures"] == ["refused by the code constraint"] * 2
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    logged = [f for f in doc["tool_failures"] if f["name"] == "p2.dq.refused"]
    assert len(logged) == 2 and all("holdout" in f["message"] for f in logged)
    assert json.loads(fake.run.outputs[wf.REPORT_FILE])["dq_refused"] == 2
    assert doc["plan"]["fallbacks"].count("dq.refused:ph") == 2
    assert doc["data_quality"]["ph"]["quarantined_windows"] == []
    # the negative control: a calibration-window spike is shown, and its quarantine
    # accepted, logged as nothing
    fake = SpikeAt()
    fake.day = 44.0
    script = ScriptedPoint("dq.trust", [{"sensor": "ph", "quarantine": [[44.0, 44.0]],
                                         "reason": "spike_run"}], sensor="ph")  # fmt: skip
    _run(monkeypatch, cfg, fake, script)
    shown = next(s for s in script.seen if s["sensor"] == "ph")
    assert shown["flagged_windows"] == [[44.0, 44.0]]
    assert not [r for r in _records(fake, "dq.trust") if r["output"]["sensor"] == "ph"][-1][
        "fallback_used"
    ]
    assert json.loads(fake.run.outputs[wf.REPORT_FILE])["dq_refused"] == 0
    # the mutation: the pre-ruling inputs (every flagged window, the whole window's count)
    # show the hold-out spike again
    monkeypatch.setattr(wf, "shown_to_dq_trust",
                        lambda t, v, flagged, cal_start, holdout_start:
                        (wf.mask_windows(t, flagged), int(np.isfinite(v).sum())))  # fmt: skip
    fake = SpikeAt()
    script = ScriptedPoint("dq.trust", [quarantine_172], sensor="ph")
    _run(monkeypatch, cfg, fake, script)
    shown = next(s for s in script.seen if s["sensor"] == "ph")
    assert shown["flagged_windows"] == [[172.0, 172.0]]


# ------------------------------------------------------------------ c. cal.split


def test_any_valid_common_step_is_accepted_and_a_weak_channel_refused(attempt1, cfg):
    steps = attempt1["cal.split"]["steps"]
    attr = cfg["p0"]["attribution"]
    assert steps["cod_total"]["step_z"] == pytest.approx(1.4256, abs=1e-3)
    # attempt 1's answer: tan + cod_total at day 105, still refused (cod_total below threshold)
    assert not wf.split_agrees(105.0, ["cod_total", "tan"], steps, attr)
    # tan (105) + alkalinity (112): accepted at either day, and at any day within 30 d of both
    assert wf.split_agrees(105.0, ["tan", "alkalinity"], steps, attr)
    assert wf.split_agrees(112.0, ["alkalinity", "tan"], steps, attr)
    assert wf.split_agrees(120.0, ["tan", "alkalinity"], steps, attr)
    assert not wf.split_agrees(150.0, ["tan", "alkalinity"], steps, attr)  # 45 d from tan
    # R4's own earliest common step is still valid: gas_flow (15) + ph (23)
    assert wf.split_agrees(15.0, ["gas_flow", "ph"], steps, attr)
    # the controls: one channel, an unknown channel, a duplicate, days too far apart, no day
    # with channels, and no day with none
    assert not wf.split_agrees(105.0, ["tan"], steps, attr)
    assert not wf.split_agrees(105.0, ["tan", "bogus"], steps, attr)
    assert not wf.split_agrees(105.0, ["tan", "tan"], steps, attr)
    assert not wf.split_agrees(60.0, ["ph", "tan"], steps, attr)  # 23 and 105: 82 d apart
    assert not wf.split_agrees(None, ["tan", "alkalinity"], steps, attr)
    assert wf.split_agrees(None, [], steps, attr)


def test_the_split_decision_accepts_tan_and_alkalinity_and_refuses_cod_total(
    monkeypatch, cfg, attempt1
):
    steps = attempt1["cal.split"]["steps"]
    # the workflow's residual table is patched to attempt 1's steps, so the decision sees
    # exactly what the model saw
    original = wf.Workflow.step_residuals

    def with_steps(self: Any) -> None:
        original(self)
        for ch, s in steps.items():
            if ch in self.residuals:
                self.residuals[ch]["step_z"] = s["step_z"]
                self.residuals[ch]["step_day"] = s["step_day"]

    monkeypatch.setattr(wf.Workflow, "step_residuals", with_steps)
    for answer, decided in (
        ({"common_step_day": 105, "channels": ["tan", "alkalinity"]}, True),
        ({"common_step_day": 112, "channels": ["alkalinity", "tan"]}, True),
        ({"common_step_day": 105, "channels": ["cod_total", "tan"]}, False),  # attempt 1's
    ):
        fake = FakeTools()
        script = ScriptedPoint("cal.split", [answer] * 2)
        _run(monkeypatch, cfg, fake, script)
        assert script.seen and script.seen[0]["steps"]["tan"]["step_day"] == 105.0
        rec = _records(fake, "cal.split")[-1]
        assert rec["fallback_used"] is (not decided), answer
        if decided:
            assert rec["output"] == {"common_step_day": float(answer["common_step_day"]),
                                     "channels": answer["channels"]}  # fmt: skip
        else:
            assert rec["output"]["common_step_day"] == 15.0  # R4's earliest: gas_flow + ph
    # the mutation: the pre-ruling rule (R4's earliest common day only) refuses tan +
    # alkalinity
    attr = cfg["p0"]["attribution"]

    def earliest_only(day: Any, channels: Any, steps_: Any, attr_: Any) -> bool:
        change = wf.common_change_point(steps_, attr_)
        return day is None or (change["common"] and abs(day - change["day"])
                                <= float(attr_["step_day_tolerance_d"]))  # fmt: skip

    assert not earliest_only(105.0, ["tan", "alkalinity"], steps, attr)
    monkeypatch.setattr(wf, "split_agrees", earliest_only)
    fake = FakeTools()
    _run(
        monkeypatch,
        cfg,
        fake,
        ScriptedPoint(
            "cal.split", [{"common_step_day": 105, "channels": ["tan", "alkalinity"]}] * 2
        ),
    )
    assert _records(fake, "cal.split")[-1]["fallback_used"]


# ------------------------------------------------------------------ the freeze


def test_the_freeze_is_the_new_one_and_the_old_record_is_refused():
    from tests.test_p2_live import COMMITTED_FROZEN_SHA256

    assert frozen_record_sha256() == COMMITTED_FROZEN_SHA256
    frozen = check_p2_frozen(load_p2())
    assert frozen.date == "2026-10-14" and "2026-10-14" in frozen.word
    # the old digests of the three changed items are gone
    old = {
        (
            "templates",
            "dq.trust",
        ): "312267663f55e074441e48e0bd831d577990c7d68bfed0902fa5e53f7169882b",
        (
            "templates",
            "verify.differential",
        ): "67511e64f10381805ecad262ca5a8cd9099267fe5617c52ed4220a58b935d670",
        (
            "schemas",
            "verify.differential",
        ): "20a29bfdeaee0c250cfd08ec7a0fca286cd2c10f0af348375048ba4bcc626825",
        (
            "tools",
            "verify.differential",
        ): "28c1f9c5496ebf99bf05e3fd34f674b9d56ca04737dd88c738dd2f8bd4d1c09f",
    }
    for (kind, point), digest in old.items():
        assert getattr(frozen, f"{kind}_sha256")[point] != digest
    # cal.split's template and schema are unchanged: the fix is in the code's check
    assert frozen.templates_sha256["cal.split"] == (
        "f28ea106116f724e3812458fd848e5ba11bb7d646a956ce9fde730730cbbdf0a"
    )
    assert frozen.schemas_sha256["cal.split"] == (
        "235d2699272247a756bb6663495dcebae27c94267e9ec3592f79d7e38bf8f982"
    )
