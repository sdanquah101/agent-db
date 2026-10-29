"""The agent P2's evidence and messages modules (docs/p2_agents_design.md §2, §3.3).

Step 1 put them in a section of ``workflow.py``; step 2 moved them, as units, into the
staged package (the lead's option A, 2026-10-26): ``evidence.py`` (the frozen ``admit``,
moved verbatim, and the agent arm's amended admission) and ``messages.py`` (the typed
messages).

1. **Admission** (§2; docs/decisions.md 2026-10-25, Q13 and Q14). ``admit_agent`` equals the
   frozen ``admit`` on every label but ``structural``, pinned over a grid of inputs. For
   ``structural`` it has two branches: NM failed (R3 on the failed channels and a failed
   hold-out, as frozen) or NM stands (a failed hold-out **and** R3 over all channels, read as
   the pipeline's own ``structural_proposed``). The signatures fixtures carry exactly the
   keys the pipeline's ``step_profile`` and hold-out write, and a test pins every key the
   evidence module reads (``.get`` and subscript) to one the pipeline writes. The negative
   controls: the hold-out alone, one structured channel, or an unchecked hold-out do not
   admit; the frozen ``admit`` still refuses the standing-NM case. The mutation: a
   hold-out-alone rule. The frozen ``admit``'s source is pinned by digest.
2. **The typed messages** (§3.3). Every string a model may write is an enumeration or a
   pattern, no node is untyped and no object has free keys: ``free_text_fields`` is empty
   for every model, and finds a planted plain ``str``, ``Any``, ``list[Any]``,
   ``dict[str, Any]`` and ``dict[str, float]``. The name pattern admits every fitted
   parameter name and channel key; the unit pattern admits the symbol of every registry
   unit after ``unit_head``; the identifier collections are bounded by the channel and
   parameter counts. The shapes: a fail names an alternative and cites evidence, a pass
   names none, round 3 is refused, a sensor claim names its channel, a named test carries
   no prose at any depth, ``structural`` is a round-2 claim, statements are templated by
   code.
3. **The package.** Each module imports only what the jail has, passes rule 1's scanner,
   and ``workflow.py`` takes ``admit`` from the evidence module.
"""

from __future__ import annotations

import hashlib
import inspect
import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from workflows.p2_multi_agent import evidence as ev
from workflows.p2_multi_agent import messages as msg
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "workflows" / "p2_multi_agent"
LAB = {"sensor": "sensor", "influent": "influent", "initial_state": "state",
       "parameter": "parameter", "structural": "structural", "none": "none"}  # fmt: skip
FROZEN_ADMIT_SHA256 = "9c7f821bd7b94959c96f6407ac36754979f321f49484894888cfa59bf7308a56"
"""sha256 of ``admit``'s source as frozen in ``workflow.py`` on 2026-10-07 (moved verbatim)."""


def _need() -> int:
    """The configured minimum, read at the exact path the pipeline reads it.

    ``self.attr`` is ``p0["attribution"]`` in the entry (the review of #40, H4).
    """
    from tools.workflow_config import load_p2

    return int(load_p2().p0().model_dump()["attribution"]["structural_channels_min"])


def _table(nb: bool, nm: bool, ns: bool, failed: list[str]) -> dict[str, Any]:
    return {"NB": nb, "NM": nm, "NS": ns, "failed_channels": failed,
            "null_rejected": nb or nm or ns}  # fmt: skip


def _profile(failed: list[str], structured: list[str], holdout: bool | None) -> dict[str, Any]:
    """The structural signatures exactly as ``step_profile`` and the hold-out write them."""
    need = _need()
    r3 = [c for c in structured if c in set(failed)]
    sig: dict[str, Any] = {
        "r3": len(r3) >= need,
        "r3_channels": r3,
        "r3_channels_all": structured,
        "structural_proposed": len(structured) >= need,
        "holdout_failed": holdout,
        "structural": len(r3) >= need and bool(holdout),
    }
    if len(structured) >= need and len(r3) < need:
        sig["structural_code"] = "r3_not_on_failed_channels"
    return sig


def _written_signature_keys() -> set[str]:
    text = (PACKAGE / "workflow.py").read_text(encoding="utf-8")
    return set(re.findall(r'self\.signatures\["(\w+)"\]\s*=', text))


# ------------------------------------------------------------------ 1. admission


def test_the_evidence_module_reads_only_signature_keys_the_pipeline_writes():
    text = (PACKAGE / "evidence.py").read_text(encoding="utf-8")
    reads = set(re.findall(r'signatures\.get\("(\w+)"', text)) | set(
        re.findall(r'signatures\["(\w+)"\]', text)
    )
    written = _written_signature_keys()
    assert reads and reads <= written, sorted(reads - written)
    assert set(_profile([], [], None)) <= written
    # the rule vocabulary of the evidence items is the pipeline's signature keys
    assert set(msg.Rule.__args__) <= written, sorted(set(msg.Rule.__args__) - written)
    # the negative control: the key the first draft read, which no code writes
    assert "r3_all" not in written
    # the pin sees subscript reads too (the review of 2026-10-26, F2)
    assert re.findall(r'signatures\["(\w+)"\]', 'x = signatures["r3_all"]') == ["r3_all"]


def test_the_frozen_admit_moved_verbatim_and_the_entry_takes_it_from_the_module():
    source = inspect.getsource(ev.admit)
    assert hashlib.sha256(source.encode()).hexdigest() == FROZEN_ADMIT_SHA256
    assert wf.admit is ev.admit
    assert "def admit(" not in (PACKAGE / "workflow.py").read_text(encoding="utf-8")


MOVED_AND_IMPORTED_BACK = (
    "band_placement",
    "candidate_onsets",
    "common_change_point",
    "early_late",
    "failed_channels",
    "feed_covariate",
    "inhibition",
    "nb_side",
    "null_table",
    "onset_test",
    "record_statistics",
    "s1_table",
    "split_agrees",
    "structured_channels",
    "tied_change_point",
)
"""The fifteen moved names the entry's steps still use (the move of 2026-10-28, H3)."""

MOVED_NOT_IMPORTED_BACK = (
    "NEVER_IN_OBJECTIVE",
    "BALANCE_STATS",
    "place",
    "worst_window",
    "envelope_placement",
    "band_envelopes",
    "channels_of",
    "channel_fails",
    "n_bal",
    "n_multi",
    "n_single",
    "null_partial",
    "null_rejected",
)
"""The thirteen moved names used only inside the moved block."""


def test_the_entry_takes_every_moved_name_it_uses_from_the_module(monkeypatch):
    """L6 (the review of PR #42): the entry's names ARE the module's, like `admit`.

    Each of the fifteen re-imported names is the evidence module's own object, so a
    change to the module reaches the entry; the thirteen names used only inside the moved
    block are not in the entry at all, and no moved definition is left in it.
    """
    entry = (PACKAGE / "workflow.py").read_text(encoding="utf-8")
    for name in MOVED_AND_IMPORTED_BACK:
        assert getattr(wf, name) is getattr(ev, name), name
        assert f"def {name}(" not in entry, name
    assert wf.Placement is ev.Placement
    for name in MOVED_NOT_IMPORTED_BACK:
        assert not hasattr(wf, name), name
        assert hasattr(ev, name), name
        assert f"def {name}(" not in entry and f"\n{name} = " not in entry, name
    assert len(MOVED_AND_IMPORTED_BACK) + len(MOVED_NOT_IMPORTED_BACK) + 1 == 29  # + Placement
    # the negative control: a rebinding in the entry would break the identity
    monkeypatch.setattr(wf, "null_table", lambda *a, **k: None)
    assert wf.null_table is not ev.null_table


def test_structural_is_admitted_over_a_standing_nm_only_with_both_pieces_of_evidence():
    need = _need()
    assert need == 2  # the configured minimum (configs/workflows/p0.yaml), not a literal here
    standing = _table(False, False, False, [])
    both = _profile([], ["q_gas_stp_dry", "pH"], holdout=True)
    assert "r3_all" not in both and both["r3"] is False
    assert ev.admit_agent(LAB, standing, both) == {"admitted": ["structural"], "rejected": []}
    assert ev.structural_case(standing, both) == (True, "admitted")
    # the negative controls: one structured channel, a passed or an unchecked hold-out
    for sig, code in (
        (_profile([], ["pH"], holdout=True), "signature_absent"),
        (_profile([], ["q_gas_stp_dry", "pH"], holdout=False), "holdout_passed"),
        (_profile([], ["q_gas_stp_dry", "pH"], holdout=None), "holdout_unavailable"),
    ):
        out = ev.admit_agent(LAB, standing, sig)
        assert out["admitted"] == [], sig
        assert out["rejected"] == [{"label": "structural", "code": code}], sig
    # the frozen rule (the procedural arm, p2_design §4.4) still refuses the standing-NM case
    assert "structural" not in ev.admit(LAB, standing, both)["admitted"]
    # the failed-NM branch is the frozen one: R3 on the failed channels, not over all channels
    failed_nm = _table(False, True, False, ["q_gas_stp_dry", "pH"])
    on_failed = _profile(["q_gas_stp_dry", "pH"], ["q_gas_stp_dry", "pH"], holdout=True)
    assert ev.admit_agent(LAB, failed_nm, on_failed)["admitted"] == ["structural"]
    off_failed = _profile(["q_gas_stp_dry", "pH"], ["tan", "vfa_ac"], holdout=True)
    out = ev.admit_agent(LAB, failed_nm, off_failed)
    assert out["admitted"] == [] and out["rejected"] == [
        {"label": "structural", "code": "r3_not_on_failed_channels"}
    ]
    assert ev.admit(LAB, failed_nm, off_failed)["rejected"] == out["rejected"]  # same as frozen
    # the deliberate difference: a structured channel short of a proposal is on the record
    # for the agent arm's verifier, where the frozen rule records nothing
    short = _profile([], ["pH"], holdout=True)
    assert ev.admit(LAB, standing, short)["rejected"] == []
    assert ev.admit_agent(LAB, standing, short)["rejected"] == [
        {"label": "structural", "code": "signature_absent"}
    ]
    # with no table (the verifier off) nothing is judged on a null case, as in admit
    assert ev.admit_agent(LAB, None, on_failed) == ev.admit(LAB, None, on_failed)


def test_the_mutation_a_hold_out_alone_would_admit_structural(monkeypatch):
    standing = _table(False, False, False, [])
    alone = _profile([], [], holdout=True)
    assert ev.admit_agent(LAB, standing, alone)["admitted"] == []  # the rule as decided

    def hold_out_alone(table: Any, signatures: Any) -> tuple[bool, str]:
        return (bool(signatures.get("holdout_failed")), "admitted")

    monkeypatch.setattr(ev, "structural_case", hold_out_alone)
    assert ev.admit_agent(LAB, standing, alone)["admitted"] == ["structural"]  # Q14 forbids


def test_admit_agent_equals_admit_on_every_label_but_structural():
    channels = ["q_gas_stp_dry", "pH"]
    grid = itertools.product(
        [False, True],
        [False, True],
        [False, True],  # NB, NM, NS
        [
            None,
            {"channel": "pH", "s1_holds": True, "s1": {"coupled_inside": True}},
            {"channel": "pH", "s1_holds": False, "s1": {"coupled_inside": False}},
        ],
        [False, True],
        [False, True],
        [False, True],  # influent, initial_state, parameter
    )
    n = 0
    for nb, nm, ns, sensor, influent, state, parameter in grid:
        failed = channels if nm else (["pH"] if ns else [])
        table = _table(nb, nm, ns, failed)
        sig = {"sensor": sensor, "sensor_proposed": sensor is not None, "influent": influent,
               "influent_proposed": True, "initial_state": state, "initial_state_proposed": True,
               "parameter": parameter, "parameter_proposed": True,
               "parameter_code": "signature_absent",
               **_profile(failed, [], holdout=False)}  # fmt: skip
        a, b = ev.admit(LAB, table, sig), ev.admit_agent(LAB, table, sig)
        strip = lambda out: {  # noqa: E731
            "admitted": [x for x in out["admitted"] if x != "structural"],
            "rejected": [r for r in out["rejected"] if r["label"] != "structural"],
        }
        assert strip(a) == strip(b), (table, sig)
        n += 1
    assert n == 192


def test_admissible_alternative_is_none_or_an_admitted_label():
    standing = _table(False, False, False, [])
    both = _profile([], ["q_gas_stp_dry", "pH"], holdout=True)
    assert ev.admissible_alternative("none", LAB, standing, both)
    assert ev.admissible_alternative("structural", LAB, standing, both)
    one = _profile([], ["pH"], holdout=True)
    assert not ev.admissible_alternative("structural", LAB, standing, one)
    assert not ev.admissible_alternative("sensor", LAB, standing, both)  # NS did not fail
    ns = _table(False, False, True, ["pH"])
    sensor = {"sensor": {"channel": "pH", "s1_holds": True, "s1": {"coupled_inside": True}}}
    assert ev.admissible_alternative("sensor", LAB, ns, sensor)
    assert not ev.admissible_alternative("influent", LAB, ns, sensor)


# ------------------------------------------------------------------ 2. the typed messages


def _ref(**kw: Any) -> msg.EvidenceRef:
    base = {"label": "sensor", "rule": "sensor", "calls": [3], "values": {"mean_z": 2.5},
            "units": {"mean_z": "sigma"}}  # fmt: skip
    return msg.EvidenceRef(**{**base, **kw})


def test_no_message_field_is_free_text_and_a_planted_one_is_found():
    for model in msg.MESSAGE_MODELS:
        assert msg.free_text_fields(model) == [], model.__name__
    assert set(msg.FINDINGS.values()) <= set(msg.MESSAGE_MODELS)

    class Planted(BaseModel):  # the mutations: a plain string, untyped nodes, free keys
        model_config = ConfigDict(extra="forbid")
        label: msg.LabelOrNone
        statement: str
        nested: msg.EvidenceRef
        notes: dict[str, str]
        blob: Any
        many: list[Any]
        bag: dict[str, Any]
        keyed: dict[msg.Name, Any]
        prices: dict[str, float]  # values typed, keys free (the review of 2026-10-26, F1)

    assert msg.free_text_fields(Planted) == [
        "bag[additionalProperties]",
        "bag[keys]",
        "blob[untyped]",
        "keyed[patternProperties][untyped]",
        "many[items][untyped]",
        "notes[additionalProperties]",
        "notes[keys]",
        "prices[keys]",
        "statement",
    ]
    # and the models refuse a planted field outright
    with pytest.raises(ValidationError):
        msg.SensorFinding(claim="none", confidence="low", statement="the plant looks fine")


def test_the_name_pattern_admits_every_parameter_and_channel_name_and_no_prose():
    from sim.adm1 import load_parameters
    from sim.observation import CHANNEL_UNITS
    from tools.fitted import load_fitted_model

    fitted = list(load_fitted_model().parameters)  # describe_model's parameter_names
    assert {"K_S_pro", "K_I_nh3", "Y_ac"} <= set(fitted)
    base = list(load_parameters().namespace())  # every ADM1 parameter
    for name in [*fitted, *base, *CHANNEL_UNITS]:
        assert re.fullmatch(msg.NAME_PATTERN, name), name
    assert msg.CalFinding(claim="parameter", confidence="low",
                          bounds_narrowed={"K_S_pro": (0.5, 2.0)}).bounds_narrowed  # fmt: skip
    # the negative controls: a space, a sentence, a leading digit
    for bad in ("k m ac", "the acetate half-saturation", "2fast", ""):
        assert not re.fullmatch(msg.NAME_PATTERN, bad), bad
    with pytest.raises(ValidationError):
        msg.IdentFinding(subset=["the acetate half-saturation"], kinetic_update_allowed=True)


def test_the_identifier_collections_are_bounded_by_the_channel_and_parameter_counts():
    from sim.observation import CHANNEL_UNITS
    from tools.fitted import load_fitted_model

    assert len(CHANNEL_UNITS) == msg.MAX_CHANNELS
    assert len(load_fitted_model().parameters) == msg.MAX_PARAMETERS
    channels = [f"c{i}" for i in range(msg.MAX_CHANNELS + 1)]
    params = [f"p{i}" for i in range(msg.MAX_PARAMETERS + 1)]
    values = [f"v{i}" for i in range(msg.MAX_VALUES + 1)]
    # at the bound each collection is accepted; one over, refused
    assert msg.SensorFinding(claim="none", confidence="low",
                             statuses={c: "ok" for c in channels[:-1]})  # fmt: skip
    with pytest.raises(ValidationError):
        msg.SensorFinding(claim="none", confidence="low", statuses={c: "ok" for c in channels})
    with pytest.raises(ValidationError):
        msg.SensorFinding(claim="none", confidence="low",
                          quarantines={c: [(1.0, 2.0)] for c in channels})  # fmt: skip
    assert msg.IdentFinding(subset=params[:-1], kinetic_update_allowed=True)
    with pytest.raises(ValidationError):
        msg.IdentFinding(subset=params, kinetic_update_allowed=True)
    est = msg.ParamEstimate(estimate=1.0, unit="-", method="none")
    with pytest.raises(ValidationError):
        msg.CalFinding(claim="parameter", confidence="low", parameters={p: est for p in params})
    with pytest.raises(ValidationError):
        msg.CalFinding(claim="parameter", confidence="low",
                       bounds_narrowed={p: (0.5, 2.0) for p in params})  # fmt: skip
    assert _ref(values={v: 1.0 for v in values[:-1]}, units={})
    with pytest.raises(ValidationError):
        _ref(values={v: 1.0 for v in values}, units={})
    with pytest.raises(ValidationError):
        msg.SeparatingTest(tool="simulate", args={v: 1 for v in values})


def test_the_unit_pattern_admits_the_symbol_of_every_registry_unit():
    from sim.adm1 import load_parameters
    from sim.observation import CHANNEL_UNITS

    namespace = load_parameters().namespace()
    # the parameter unit string as tools/fitted.py writes it (the review of 2026-10-26, F7)
    parameter_units = [f"- (multiplier of the BSM2 default {namespace[n]:.6g})"
                       for n in ("K_S_pro", "k_m_ac", "K_I_nh3")]  # fmt: skip
    for unit in [*CHANNEL_UNITS.values(), *parameter_units]:
        head = msg.unit_head(unit)
        assert re.fullmatch(msg.UNIT_PATTERN, head), (unit, head)
        assert msg.same_unit(head, unit)
    assert {msg.unit_head(u) for u in parameter_units} == {"-"}
    assert msg.unit_head(CHANNEL_UNITS["tan"]) == "kg N/m3"
    assert msg.unit_head(CHANNEL_UNITS["q_gas_stp_dry"]) == "m3/d"
    assert msg.unit_head(CHANNEL_UNITS["vfa_ac"]) == "kg/m3"
    assert msg.unit_head(CHANNEL_UNITS["pH"]) == "-"
    assert not msg.same_unit("kg/m3", CHANNEL_UNITS["tan"])
    # the negative controls: the registry's full strings and prose are not symbols
    assert not re.fullmatch(msg.UNIT_PATTERN, CHANNEL_UNITS["tan"])
    for bad in ("kilograms per cubic metre of digestate", "kg N/m3 (NH3)", "", "m3/d at stp"):
        assert not re.fullmatch(msg.UNIT_PATTERN, bad), bad
    with pytest.raises(ValidationError):
        msg.ParamEstimate(estimate=1.0, unit="multiplier of the default", method="none")


def test_the_evidence_item_is_typed_and_its_statement_is_templated():
    item = _ref()
    assert msg.statement_for(item) == "sensor: points to sensor (mean_z=2.5 sigma); calls 3"
    assert "statement" not in item.model_dump()
    with pytest.raises(ValidationError):
        _ref(label="the pH probe drifted")  # not a label
    with pytest.raises(ValidationError):
        _ref(rule="we think the sensor is at fault")  # not a rule the code writes
    with pytest.raises(ValidationError):
        _ref(rule="S1")  # the design's shorthand is not the signature's key either
    with pytest.raises(ValidationError):
        _ref(calls=[])  # uncited
    with pytest.raises(ValidationError):
        _ref(calls=[-1])
    with pytest.raises(ValidationError):
        _ref(units={"rms_z": "sigma"})  # a unit for no value
    with pytest.raises(ValidationError):
        _ref(values={"a note": 1.0})  # a value name is an identifier
    assert _ref(label="none").label == "none"  # evidence may point to the null label
    assert _ref(rule="r3", label="structural", units={"mean_z": "kg COD/m3"}).units


def test_the_findings_shapes():
    ok = msg.SensorFinding(statuses={"pH": "quarantined"}, quarantines={"pH": [[44.0, 46.0]]},
                           claim="sensor", channel="pH", confidence="high",
                           evidence=[_ref()])  # fmt: skip
    assert ok.role == "data_quality"
    with pytest.raises(ValidationError):
        msg.SensorFinding(claim="sensor", confidence="high")  # a sensor claim names a channel
    with pytest.raises(ValidationError):
        msg.SensorFinding(claim="none", confidence="high", quarantines={"pH": [[46.0, 44.0]]})
    with pytest.raises(ValidationError):
        msg.SensorFinding(claim="none", confidence="certain")
    with pytest.raises(ValidationError):
        msg.SensorFinding(role="verification", claim="none", confidence="low")  # the role is fixed
    with pytest.raises(ValidationError):
        msg.SensorFinding(claim="none", confidence="low", statuses={"pH": "trusted"})

    inf = msg.InfluentFinding(claim="influent", onset_day=112.0, feed_id="feed_a",
                              mechanism="mislabel", confidence="medium")  # fmt: skip
    assert inf.mechanism == "mislabel"
    with pytest.raises(ValidationError):
        msg.InfluentFinding(claim="influent", confidence="low", mechanism="bad delivery")

    with pytest.raises(ValidationError):
        msg.IdentFinding(subset=[], kinetic_update_allowed=True)
    assert msg.IdentFinding(subset=["k_m_ac"], kinetic_update_allowed=True).subset == ["k_m_ac"]

    est = msg.ParamEstimate(estimate=1.1, lower=0.9, upper=1.3, unit="-", method="fisher")
    cal = msg.CalFinding(claim="parameter", parameters={"k_m_ac": est},
                         bounds_narrowed={"k_m_ac": (0.5, 2.0)}, confidence="medium")  # fmt: skip
    assert cal.parameters["k_m_ac"].unit == "-"  # rule 6: a unit on every quantity
    with pytest.raises(ValidationError):
        msg.ParamEstimate(estimate=1.0, unit="-", method="none", lower=0.5)
    with pytest.raises(ValidationError):
        msg.ParamEstimate(estimate=1.0, lower=2.0, upper=1.0, unit="-", method="fisher")
    with pytest.raises(ValidationError):
        msg.CalFinding(claim="parameter", confidence="low", bounds_narrowed={"k_m_ac": (2.0, 2.0)})
    with pytest.raises(ValidationError):
        msg.CalFinding(claim="kinetics drifted", confidence="low")

    plan = msg.AssayPlan(assay="vfa_profile", day=120.0, unit="kg/m3",
                         separates=("sensor", "parameter"),
                         predicted={"sensor": 0.1, "parameter": 1.4})  # fmt: skip
    assert plan.role == "design"
    with pytest.raises(ValidationError):
        msg.AssayPlan(assay="vfa_profile", day=1.0, unit="kg/m3", separates=("sensor", "sensor"))
    with pytest.raises(ValidationError):
        msg.AssayPlan(assay="vfa_profile", day=1.0, unit="kg/m3", separates=("sensor", "none"),
                      predicted={"influent": 1.0})  # fmt: skip
    with pytest.raises(ValidationError):
        msg.AssayPlan(assay="vfa_profile", day=1.0, separates=("sensor", "none"))  # no unit
    # every quantity states its unit (rule 6) in the schema a model is shown: days, the
    # parameter's unit, the assay's unit
    schemas = {m.__name__: json.dumps(m.model_json_schema()) for m in msg.MESSAGE_MODELS}
    assert "A day of the run, d" in schemas["AssayPlan"]
    assert "The onset day, d" in schemas["InfluentFinding"]
    assert "(start, end) of a window, d" in schemas["SensorFinding"]
    assert "(lower, upper), in the parameter's unit" in schemas["CalFinding"]


def test_the_verdict_shapes_and_the_round_two_claim():
    hold = msg.HoldoutResult(failed=True, call=41)
    fail = msg.Verdict(round=1, verdict="fail", holdout=hold, alternative="structural",
                       separating_test=msg.SeparatingTest(tool="validate", args={"channel": "pH"}),
                       evidence=[_ref(label="structural", rule="r3")])  # fmt: skip
    assert fail.holdout is not None and fail.holdout.failed
    assert msg.Verdict(round=2, verdict="pass").alternative is None
    with pytest.raises(ValidationError):
        msg.Verdict(round=1, verdict="fail", evidence=[_ref()])  # a fail names its alternative
    with pytest.raises(ValidationError):
        msg.Verdict(round=1, verdict="fail", alternative="none")  # and cites its evidence
    with pytest.raises(ValidationError):
        msg.Verdict(round=1, verdict="pass", alternative="none")
    with pytest.raises(ValidationError):
        msg.Verdict(round=1, verdict="abstain", separating_test=msg.SeparatingTest(tool="simulate"))
    with pytest.raises(ValidationError):
        msg.Verdict(round=3, verdict="pass")  # two rounds (Q11)
    with pytest.raises(ValidationError):
        msg.Verdict(round=1, verdict="fail", alternative="the hold-out looks structural",
                    evidence=[_ref()])  # fmt: skip
    with pytest.raises(ValidationError):
        msg.HoldoutResult(failed=True, call=-1)
    # a named test carries no prose, at any depth, by type
    deep = msg.SeparatingTest(tool="simulate",
                              args={"parameters": {"k_m_ac": 1.2}, "scale": "x2",
                                    "bounds": {"K_S_pro": [0.5, 2.0]}})  # fmt: skip
    assert deep.args["bounds"] == {"K_S_pro": [0.5, 2.0]}
    assert msg.SeparatingTest(tool="t", args={"a": {"b": {"c": {"d": 1}}}}).args  # three levels
    for args in (
        {"note": "please rerun the fit with wider bounds"},
        {"nested": {"deep": ["ok_token", "a sentence with spaces"]}},
        {"nested": {"deeper": {"deepest": "a sentence with spaces"}}},
        {"a": {"b": {"c": {"d": {"e": 1}}}}},  # four levels below args: deeper than any tool
    ):
        with pytest.raises(ValidationError):
            msg.SeparatingTest(tool="simulate", args=args)
    with pytest.raises(ValidationError):
        msg.SeparatingTest(tool="run anything")
    assert msg.free_text_fields(msg.SeparatingTest) == []  # the static half covers args too
    # structural is a round-2 claim for calibration (F1); other claims are not restricted
    structural = msg.CalFinding(claim="structural", confidence="medium")
    assert not msg.claim_allowed_in_round(structural, 1)
    assert msg.claim_allowed_in_round(structural, 2)
    assert msg.claim_allowed_in_round(msg.CalFinding(claim="parameter", confidence="low"), 1)
    assert msg.claim_allowed_in_round(msg.Verdict(round=1, verdict="pass"), 1)


def test_the_routing_entry_is_the_coordinators_and_typed():
    entry = msg.RoutingEntry(round=0, to="data_quality", reason="qc_first",
                             grant=msg.Grant(evaluations=40))  # fmt: skip
    assert entry.grant.assays == 0
    with pytest.raises(ValidationError):
        msg.RoutingEntry(round=0, to="coordination", reason="qc_first")  # never to itself
    with pytest.raises(ValidationError):
        msg.RoutingEntry(round=0, to="design", reason="because the fit looked off")
    with pytest.raises(ValidationError):
        msg.Grant(evaluations=-1)


def test_the_label_patterns_match_the_configured_vocabulary_and_pass_rule_ones_scanner(tmp_path):
    from tests.test_truth_isolation import find_truth_references
    from tools.workflow_config import load_p2

    labels = load_p2().p0().labels.model_dump()
    alternatives = re.fullmatch(r"\^\((.*)\)\$", msg.LABEL_OR_NONE_PATTERN).group(1).split("|")
    assert set(alternatives) == set(labels.values())
    # rule 1's scanner is why the vocabulary is a pattern: the initial-state label is also a
    # forbidden module's name, which the scanner refuses as a bare string in workflow code
    bare = tmp_path / "bare.py"
    bare.write_text(f"LABEL = {labels['initial_state']!r}\n", encoding="utf-8")
    assert find_truth_references(bare)
    patterns = tmp_path / "patterns.py"
    patterns.write_text(
        f"LABEL_OR_NONE_PATTERN = {msg.LABEL_OR_NONE_PATTERN!r}\n"
        f"CAL_CLAIM_PATTERN = {msg.CAL_CLAIM_PATTERN!r}\n",
        encoding="utf-8",
    )
    assert find_truth_references(patterns) == []


# ------------------------------------------------------------------ 3. the package


@pytest.mark.parametrize(
    ("module", "allowed"),
    [
        ("evidence.py", {"__future__", "collections", "typing"}),
        ("messages.py", {"__future__", "typing", "pydantic"}),
        (
            "agents.py",
            {"__future__", "json", "math", "typing", "numpy", "pydantic", "tools", "workflows"},
        ),
    ],
)
def test_each_module_of_the_package_imports_only_what_the_jail_has(module: str, allowed: set):
    from tests.test_truth_isolation import find_truth_references

    path = PACKAGE / module
    assert find_truth_references(path) == []
    text = path.read_text(encoding="utf-8")
    imports = set(re.findall(r"^(?:from|import) ([a-z_]+)", text, flags=re.M))
    assert imports <= allowed, sorted(imports - allowed)
    assert (PACKAGE / ".jail-package").is_file()  # the package is the one the jail stages
