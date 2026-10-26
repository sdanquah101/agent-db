"""The agent P2, step 1 (docs/p2_agents_design.md): the amended admission and the typed messages.

1. **Admission** (§2; docs/decisions.md 2026-10-25, Q13 and Q14). ``admit_agent`` equals the
   frozen ``admit`` on every label but ``structural``, pinned over a grid of inputs. For
   ``structural`` it has two branches: NM failed (R3 on the failed channels and a failed
   hold-out, as frozen) or NM stands (a failed hold-out **and** R3 over all channels). The
   negative controls: the hold-out alone, R3 alone, or an unchecked hold-out do not admit; the
   frozen ``admit`` still refuses the standing-NM case. The mutation: a hold-out-alone rule.
2. **The typed messages** (§3.3). Every string a model may write is an enumeration or a
   pattern: ``free_text_fields`` is empty for every model, and finds a planted plain ``str``.
   The shapes: a fail names an alternative, a pass names none, round 3 is refused, a sensor
   claim names its channel, a named test carries no prose, ``structural`` is a round-2 claim,
   statements are templated by code.
"""

from __future__ import annotations

import itertools
import re
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from workflows.p2_multi_agent import workflow as wf

LAB = {"sensor": "sensor", "influent": "influent", "initial_state": "state",
       "parameter": "parameter", "structural": "structural", "none": "none"}  # fmt: skip


def _table(nb: bool, nm: bool, ns: bool, failed: list[str]) -> dict[str, Any]:
    return {"NB": nb, "NM": nm, "NS": ns, "failed_channels": failed,
            "null_rejected": nb or nm or ns}  # fmt: skip


# ------------------------------------------------------------------ 1. admission


def test_structural_is_admitted_over_a_standing_nm_only_with_both_pieces_of_evidence():
    standing = _table(False, False, False, [])
    both = {"r3": False, "r3_all": True, "holdout_failed": True, "structural_proposed": True}
    assert wf.admit_agent(LAB, standing, both) == {"admitted": ["structural"], "rejected": []}
    assert wf.structural_case(standing, both) == (True, "admitted")
    # the negative controls: either piece alone, or an unchecked hold-out, does not admit
    for sig, code in (
        ({**both, "r3_all": False}, "signature_absent"),
        ({**both, "holdout_failed": False}, "holdout_passed"),
        ({**both, "holdout_failed": None}, "holdout_unavailable"),
    ):
        out = wf.admit_agent(LAB, standing, sig)
        assert out["admitted"] == [] and out["rejected"] == [{"label": "structural", "code": code}]
    # the frozen rule (the procedural arm, p2_design §4.4) still refuses the standing-NM case
    frozen = wf.admit(LAB, standing, {**both, "structural": both["holdout_failed"] and both["r3"]})
    assert "structural" not in frozen["admitted"]
    # the failed-NM branch is the frozen one: R3 on the failed channels, not over all channels
    failed_nm = _table(False, True, False, ["gas_flow", "ph"])
    on_failed = {"r3": True, "r3_all": True, "holdout_failed": True, "structural_proposed": True,
                 "structural": True}  # fmt: skip
    assert wf.admit_agent(LAB, failed_nm, on_failed)["admitted"] == ["structural"]
    off_failed = {**on_failed, "r3": False, "structural": False,
                  "structural_code": "r3_not_on_failed_channels"}  # fmt: skip
    out = wf.admit_agent(LAB, failed_nm, off_failed)
    assert out["admitted"] == [] and out["rejected"] == [
        {"label": "structural", "code": "r3_not_on_failed_channels"}
    ]
    assert wf.admit(LAB, failed_nm, off_failed)["rejected"] == out["rejected"]  # same as frozen
    # with no table (the verifier off) nothing is judged on a null case, as in admit
    assert wf.admit_agent(LAB, None, {**on_failed}) == wf.admit(LAB, None, {**on_failed})


def test_the_mutation_a_hold_out_alone_would_admit_structural(monkeypatch):
    standing = _table(False, False, False, [])
    alone = {"r3": False, "r3_all": False, "holdout_failed": True, "structural_proposed": True}
    assert wf.admit_agent(LAB, standing, alone)["admitted"] == []  # the rule as decided

    def hold_out_alone(table: Any, signatures: Any) -> tuple[bool, str]:
        return (bool(signatures.get("holdout_failed")), "admitted")

    monkeypatch.setattr(wf, "structural_case", hold_out_alone)
    assert wf.admit_agent(LAB, standing, alone)["admitted"] == ["structural"]  # what Q14 forbids


def test_admit_agent_equals_admit_on_every_label_but_structural():
    channels = ["gas_flow", "ph"]
    grid = itertools.product(
        [False, True],
        [False, True],
        [False, True],  # NB, NM, NS
        [
            None,
            {"channel": "ph", "s1_holds": True, "s1": {"coupled_inside": True}},
            {"channel": "ph", "s1_holds": False, "s1": {"coupled_inside": False}},
        ],
        [False, True],
        [False, True],
        [False, True],  # influent, initial_state, parameter
    )
    n = 0
    for nb, nm, ns, sensor, influent, state, parameter in grid:
        failed = channels if nm else (["ph"] if ns else [])
        table = _table(nb, nm, ns, failed)
        sig = {"sensor": sensor, "sensor_proposed": sensor is not None, "influent": influent,
               "influent_proposed": True, "initial_state": state, "initial_state_proposed": True,
               "parameter": parameter, "parameter_proposed": True,
               "parameter_code": "signature_absent", "r3": False, "r3_all": False,
               "holdout_failed": False}  # fmt: skip
        a, b = wf.admit(LAB, table, sig), wf.admit_agent(LAB, table, sig)
        strip = lambda out: {  # noqa: E731
            "admitted": [x for x in out["admitted"] if x != "structural"],
            "rejected": [r for r in out["rejected"] if r["label"] != "structural"],
        }
        assert strip(a) == strip(b), (table, sig)
        n += 1
    assert n == 192


def test_admissible_alternative_is_none_or_an_admitted_label():
    standing = _table(False, False, False, [])
    both = {"r3_all": True, "holdout_failed": True, "structural_proposed": True}
    assert wf.admissible_alternative("none", LAB, standing, both)
    assert wf.admissible_alternative("structural", LAB, standing, both)
    assert not wf.admissible_alternative("structural", LAB, standing, {**both, "r3_all": False})
    assert not wf.admissible_alternative("sensor", LAB, standing, both)  # NS did not fail
    ns = _table(False, False, True, ["ph"])
    sensor = {"sensor": {"channel": "ph", "s1_holds": True, "s1": {"coupled_inside": True}}}
    assert wf.admissible_alternative("sensor", LAB, ns, sensor)
    assert not wf.admissible_alternative("influent", LAB, ns, sensor)


# ------------------------------------------------------------------ 2. the typed messages


def _ref(**kw: Any) -> wf.EvidenceRef:
    base = {"label": "sensor", "rule": "S1", "calls": [3], "values": {"mean_z": 2.5},
            "units": {"mean_z": "sigma"}}  # fmt: skip
    return wf.EvidenceRef(**{**base, **kw})


def test_no_message_field_is_free_text_and_a_planted_one_is_found():
    for model in wf.MESSAGE_MODELS:
        assert wf.free_text_fields(model) == [], model.__name__
    assert set(wf.FINDINGS.values()) <= set(wf.MESSAGE_MODELS)

    class Planted(BaseModel):  # the mutation: a plain string field
        model_config = ConfigDict(extra="forbid")
        label: wf.LabelOrNone
        statement: str
        nested: wf.EvidenceRef
        notes: dict[str, str]

    assert wf.free_text_fields(Planted) == ["notes[additionalProperties]", "statement"]
    # and the models refuse a planted field outright
    with pytest.raises(ValidationError):
        wf.SensorFinding(claim="none", confidence="low", statement="the plant looks fine")


def test_the_evidence_item_is_typed_and_its_statement_is_templated():
    item = _ref()
    assert wf.statement_for(item) == "S1: points to sensor (mean_z=2.5 sigma); calls 3"
    assert "statement" not in item.model_dump()
    with pytest.raises(ValidationError):
        _ref(label="the pH probe drifted")  # not a label
    with pytest.raises(ValidationError):
        _ref(rule="we think the sensor is at fault")  # not a rule name
    with pytest.raises(ValidationError):
        _ref(calls=[])  # uncited
    with pytest.raises(ValidationError):
        _ref(calls=[-1])
    with pytest.raises(ValidationError):
        _ref(units={"rms_z": "sigma"})  # a unit for no value
    with pytest.raises(ValidationError):
        _ref(values={"a note": 1.0})  # a value name is an identifier
    assert _ref(label="none").label == "none"  # evidence may point to the null label


def test_the_findings_shapes():
    ok = wf.SensorFinding(statuses={"ph": "quarantined"}, quarantines={"ph": [[44.0, 46.0]]},
                          claim="sensor", channel="ph", confidence="high",
                          evidence=[_ref()])  # fmt: skip
    assert ok.role == "data_quality"
    with pytest.raises(ValidationError):
        wf.SensorFinding(claim="sensor", confidence="high")  # a sensor claim names a channel
    with pytest.raises(ValidationError):
        wf.SensorFinding(claim="none", confidence="high", quarantines={"ph": [[46.0, 44.0]]})
    with pytest.raises(ValidationError):
        wf.SensorFinding(claim="none", confidence="certain")
    with pytest.raises(ValidationError):
        wf.SensorFinding(role="verification", claim="none", confidence="low")  # the role is fixed
    with pytest.raises(ValidationError):
        wf.SensorFinding(claim="none", confidence="low", statuses={"ph": "trusted"})

    inf = wf.InfluentFinding(claim="influent", onset_day=112.0, feed_id="feed_a",
                             mechanism="mislabel", confidence="medium")  # fmt: skip
    assert inf.mechanism == "mislabel"
    with pytest.raises(ValidationError):
        wf.InfluentFinding(claim="influent", confidence="low", mechanism="bad delivery")

    with pytest.raises(ValidationError):
        wf.IdentFinding(subset=[], kinetic_update_allowed=True)
    assert wf.IdentFinding(subset=["k_m_ac"], kinetic_update_allowed=True).subset == ["k_m_ac"]

    est = wf.ParamEstimate(estimate=1.1, lower=0.9, upper=1.3, unit="1/d", method="fisher")
    cal = wf.CalFinding(claim="parameter", parameters={"k_m_ac": est},
                        bounds_narrowed={"k_m_ac": (0.5, 2.0)}, confidence="medium")  # fmt: skip
    assert cal.parameters["k_m_ac"].unit == "1/d"  # rule 6: a unit on every quantity
    with pytest.raises(ValidationError):
        wf.ParamEstimate(estimate=1.0, unit="1/d", method="none", lower=0.5)
    with pytest.raises(ValidationError):
        wf.ParamEstimate(estimate=1.0, lower=2.0, upper=1.0, unit="1/d", method="fisher")
    with pytest.raises(ValidationError):
        wf.CalFinding(claim="parameter", confidence="low", bounds_narrowed={"k_m_ac": (2.0, 2.0)})
    with pytest.raises(ValidationError):
        wf.CalFinding(claim="kinetics drifted", confidence="low")

    plan = wf.AssayPlan(assay="vfa_profile", day=120.0, separates=("sensor", "parameter"),
                        predicted={"sensor": 0.1, "parameter": 1.4})  # fmt: skip
    assert plan.role == "design"
    with pytest.raises(ValidationError):
        wf.AssayPlan(assay="vfa_profile", day=1.0, separates=("sensor", "sensor"))
    with pytest.raises(ValidationError):
        wf.AssayPlan(assay="vfa_profile", day=1.0, separates=("sensor", "none"),
                     predicted={"influent": 1.0})  # fmt: skip


def test_the_verdict_shapes_and_the_round_two_claim():
    hold = wf.HoldoutResult(failed=True, call=41)
    fail = wf.Verdict(round=1, verdict="fail", holdout=hold, alternative="structural",
                      separating_test=wf.SeparatingTest(tool="validate", args={"channel": "ph"}),
                      evidence=[_ref(label="structural", rule="R3")])  # fmt: skip
    assert fail.holdout is not None and fail.holdout.failed
    assert wf.Verdict(round=2, verdict="pass").alternative is None
    with pytest.raises(ValidationError):
        wf.Verdict(round=1, verdict="fail")  # a fail names its alternative
    with pytest.raises(ValidationError):
        wf.Verdict(round=1, verdict="pass", alternative="none")
    with pytest.raises(ValidationError):
        wf.Verdict(round=1, verdict="abstain", separating_test=wf.SeparatingTest(tool="simulate"))
    with pytest.raises(ValidationError):
        wf.Verdict(round=3, verdict="pass")  # two rounds (Q11)
    with pytest.raises(ValidationError):
        wf.Verdict(round=1, verdict="fail", alternative="the hold-out looks structural")
    with pytest.raises(ValidationError):
        wf.HoldoutResult(failed=True, call=-1)
    # a named test carries no prose, at any depth
    wf.SeparatingTest(tool="simulate", args={"parameters": {"k_m_ac": 1.2}, "scale": "x2"})
    for args in (
        {"note": "please rerun the fit with wider bounds"},
        {"nested": {"deep": ["ok_token", "a sentence with spaces"]}},
    ):
        with pytest.raises(ValidationError):
            wf.SeparatingTest(tool="simulate", args=args)
    with pytest.raises(ValidationError):
        wf.SeparatingTest(tool="run anything")
    # structural is a round-2 claim for calibration (F1); other claims are not restricted
    structural = wf.CalFinding(claim="structural", confidence="medium")
    assert not wf.claim_allowed_in_round(structural, 1) and wf.claim_allowed_in_round(structural, 2)
    assert wf.claim_allowed_in_round(wf.CalFinding(claim="parameter", confidence="low"), 1)
    assert wf.claim_allowed_in_round(wf.Verdict(round=1, verdict="pass"), 1)


def test_the_routing_entry_is_the_coordinators_and_typed():
    entry = wf.RoutingEntry(round=0, to="data_quality", reason="qc_first",
                            grant=wf.Grant(evaluations=40))  # fmt: skip
    assert entry.grant.assays == 0
    with pytest.raises(ValidationError):
        wf.RoutingEntry(round=0, to="coordination", reason="qc_first")  # never to itself
    with pytest.raises(ValidationError):
        wf.RoutingEntry(round=0, to="design", reason="because the fit looked off")
    with pytest.raises(ValidationError):
        wf.Grant(evaluations=-1)


def test_the_label_patterns_match_the_configured_vocabulary_and_not_its_module_namesake():
    from tools.workflow_config import load_p2

    labels = load_p2().p0().labels.model_dump()
    alternatives = re.fullmatch(r"\^\((.*)\)\$", wf.LABEL_OR_NONE_PATTERN).group(1).split("|")
    assert set(alternatives) == set(labels.values())
    # rule 1's scanner is why the vocabulary is a pattern: the initial-state label is also a
    # forbidden module's name, which the scanner refuses as a bare string in workflow code
    from tests.test_truth_isolation import _spells_forbidden_module

    assert _spells_forbidden_module(labels["initial_state"])
    assert not _spells_forbidden_module(wf.LABEL_OR_NONE_PATTERN)
    assert not _spells_forbidden_module(wf.CAL_CLAIM_PATTERN)
