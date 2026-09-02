"""Tests for the scenario YAML contract (proposal Appendix B)."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scenarios import (
    Budget,
    CorrectConclusion,
    Fault,
    FaultType,
    Plant,
    Scenario,
    Tier,
    TruthLabel,
    load_scenario,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
S2_03 = REPO_ROOT / "scenarios" / "S2-03.yaml"


def test_example_scenario_loads_with_every_field_from_appendix_b():
    scenario = load_scenario(S2_03)

    assert scenario.id == "S2-03"
    assert scenario.plant is Plant.B
    assert scenario.tier is Tier.A
    assert scenario.level == 2
    assert scenario.duration_days == 180
    assert scenario.truth_label == (TruthLabel.SENSOR,)

    assert len(scenario.faults) == 1
    fault = scenario.faults[0]
    assert fault.type is FaultType.GAS_METER_SCALE
    assert fault.onset_day == 60
    assert fault.magnitude == pytest.approx(1.08)
    assert fault.duration_days is None

    conclusion = scenario.correct_conclusion
    assert conclusion.flag_sensor == "gas_flow"
    assert conclusion.estimate_scale_factor is True
    assert conclusion.kinetic_update_allowed is False
    assert conclusion.abstain_on == ()

    assert scenario.budget == Budget(simulator_evals=4000, wall_clock_min=90, assay_units=2)
    assert scenario.seed is None


def test_example_scenario_round_trips_through_yaml(tmp_path: Path):
    scenario = load_scenario(S2_03)
    dumped = tmp_path / "S2-03.yaml"
    dumped.write_text(yaml.safe_dump(scenario.model_dump(mode="json")), encoding="utf-8")
    assert load_scenario(dumped) == scenario


def test_every_committed_scenario_validates():
    files = sorted((REPO_ROOT / "scenarios").glob("*.yaml"))
    assert files, "no scenario files found"
    for path in files:
        scenario = load_scenario(path)
        assert scenario.id == path.stem, f"{path.name}: id {scenario.id!r} != filename"


def _base() -> dict:
    return yaml.safe_load(S2_03.read_text(encoding="utf-8"))


def test_unknown_top_level_key_is_rejected():
    raw = _base()
    raw["true_parameters"] = {"k_hyd": 0.1}
    with pytest.raises(ValidationError, match="extra"):
        Scenario.model_validate(raw)


def test_unknown_nested_key_is_rejected():
    raw = _base()
    raw["budget"]["tokens"] = 1
    with pytest.raises(ValidationError, match="extra"):
        Scenario.model_validate(raw)


def test_unknown_fault_type_is_rejected():
    raw = _base()
    raw["faults"][0]["type"] = "gas_meter_bias"
    with pytest.raises(ValidationError, match="type"):
        Scenario.model_validate(raw)


def test_fault_after_end_of_run_is_rejected():
    raw = _base()
    raw["faults"][0]["onset_day"] = 181
    with pytest.raises(ValidationError, match="after the run ends"):
        Scenario.model_validate(raw)


def test_none_label_cannot_be_combined():
    raw = _base()
    raw["truth_label"] = ["sensor", "none"]
    with pytest.raises(ValidationError, match="cannot be combined"):
        Scenario.model_validate(raw)


def test_duplicate_labels_are_rejected():
    raw = _base()
    raw["truth_label"] = ["sensor", "sensor"]
    with pytest.raises(ValidationError, match="duplicates"):
        Scenario.model_validate(raw)


def test_structural_scenario_may_not_allow_kinetic_update():
    raw = _base()
    raw["level"] = 6
    raw["truth_label"] = ["structural"]
    raw["faults"] = [{"type": "omitted_sao", "onset_day": 0, "magnitude": 1.0}]
    raw["correct_conclusion"]["kinetic_update_allowed"] = True
    with pytest.raises(ValidationError, match="structural"):
        Scenario.model_validate(raw)


def test_compound_structural_plus_parameter_may_allow_kinetic_update():
    raw = _base()
    raw["id"] = "S7-02"
    raw["level"] = 7
    raw["truth_label"] = ["structural", "parameter"]
    raw["faults"] = [
        {"type": "omitted_sao", "onset_day": 0, "magnitude": 1.0},
        {"type": "ammonia_inhibition_shift", "onset_day": 90, "magnitude": 1.5},
    ]
    raw["correct_conclusion"]["kinetic_update_allowed"] = True
    raw["correct_conclusion"]["abstain_on"] = ["speciation"]
    scenario = Scenario.model_validate(raw)
    assert scenario.correct_conclusion.abstain_on == ("speciation",)


def test_level_zero_clean_scenario_needs_no_faults():
    raw = _base()
    raw["id"] = "S0-01"
    raw["level"] = 0
    raw["truth_label"] = ["none"]
    raw["faults"] = []
    raw["correct_conclusion"] = {"kinetic_update_allowed": True}
    scenario = Scenario.model_validate(raw)
    assert scenario.faults == ()
    assert scenario.correct_conclusion == CorrectConclusion(kinetic_update_allowed=True)


def test_scenario_is_immutable():
    scenario = load_scenario(S2_03)
    with pytest.raises(ValidationError):
        scenario.level = 3  # type: ignore[misc]


def test_bad_id_pattern_is_rejected():
    raw = _base()
    raw["id"] = "scenario-3"
    with pytest.raises(ValidationError, match="pattern"):
        Scenario.model_validate(raw)


def test_non_mapping_file_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected a YAML mapping"):
        load_scenario(path)


def test_fault_model_is_strict_about_negative_onset():
    with pytest.raises(ValidationError):
        Fault(type=FaultType.PH_ELECTRODE_DRIFT, onset_day=-1, magnitude=0.01)
