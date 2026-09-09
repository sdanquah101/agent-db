"""The scenario library is the ladder of proposal §6.3, and the matrix is the design of §7.

Two things are checked here, and both are checked against the *proposal*, not against the
code that implements them:

* every row of the §6.3 table exists as a validated YAML with an answer key, and every
  magnitude it declares is inside the admissible range ``sim/faults/schema.py`` publishes
  for its fault type;
* the generation matrix has the shape §7 describes — 16 non-ammonia scenarios x 3 tiers x
  2 dataset-anchored plants for the factorial, Plant A separate and contributing no rows
  to it, and the three ammonia scenarios nowhere but Plant A.

The counts below are written as literals taken from the proposal, so a change to
``sim/run/matrix.py`` that quietly drops or duplicates cells fails here rather than being
restated by the test.
"""

from __future__ import annotations

from collections import Counter

import pytest

from scenarios.schema import FaultType, Scenario, TruthLabel
from sim.faults.schema import FAULT_SEMANTICS
from sim.run.matrix import (
    ALL_TIERS,
    AMMONIA_SCENARIOS,
    FACTORIAL_PLANTS,
    load_library,
    matrix_cells,
)

#: Rows per level in the §6.3 table: Level 0 and 1 have one each, Level 2 has three
#: (pH drift, gas-meter bias, flatlined analyser), Level 3 three, Level 4 two, Level 5
#: two, Level 6 FOUR, Level 7 two, Level 8 two. Twenty in total.
#:
#: Level 6 gained S6-04 on the lead's ruling 1 of 2026-09-09 (the row the lead named
#: "S6-01b"; the frozen id pattern admits no letter suffix). It is S6-01's omission staged
#: on the ADAPTED baseline, where the omitted pathway carries no flux and the correct
#: conclusion is that no structural residual is detectable. §9.3's milestone row and gate
#: G1 quote nineteen, which was the count before that ruling.
LADDER_ROWS_PER_LEVEL = {0: 1, 1: 1, 2: 3, 3: 3, 4: 2, 5: 2, 6: 4, 7: 2, 8: 2}
LADDER_TOTAL = 20


@pytest.fixture(scope="module")
def library() -> dict[str, Scenario]:
    return load_library()


def test_the_library_is_the_twenty_row_ladder(library):
    assert len(library) == LADDER_TOTAL, sorted(library)
    assert sum(LADDER_ROWS_PER_LEVEL.values()) == LADDER_TOTAL
    by_level = Counter(s.level for s in library.values())
    assert dict(sorted(by_level.items())) == LADDER_ROWS_PER_LEVEL


def test_every_scenario_carries_a_unique_explicit_seed(library):
    """CLAUDE.md rule 4: no stochastic component may run unseeded."""
    seeds = [s.seed for s in library.values()]
    assert all(seed is not None for seed in seeds), {k: v.seed for k, v in library.items()}
    assert len(set(seeds)) == len(seeds), sorted(seeds)


def test_every_scenario_says_what_a_workflow_should_notice(library):
    """The `notes` field is the maintainer's statement of the row's discriminator."""
    for scenario in library.values():
        assert scenario.notes, scenario.id
        assert "notice" in scenario.notes.lower(), scenario.id


def test_every_magnitude_is_inside_its_declared_admissible_range(library):
    """Checked against FAULT_SEMANTICS directly, not by calling build_plan.

    `build_plan` validates magnitudes too, so asking it would be asking the code under
    test. This reads the published table and compares.
    """
    checked = 0
    for scenario in library.values():
        for fault in scenario.faults:
            spec = FAULT_SEMANTICS[fault.type]
            if spec.magnitude_min is not None:
                assert fault.magnitude >= spec.magnitude_min, (scenario.id, fault.type)
            if spec.magnitude_max is not None:
                assert fault.magnitude <= spec.magnitude_max, (scenario.id, fault.type)
            assert fault.onset_day <= scenario.duration_days, (scenario.id, fault.type)
            checked += 1
    assert checked >= LADDER_TOTAL  # every row but Level 0 injects at least one fault


def test_every_fault_type_in_the_closed_enum_appears_somewhere(library):
    """The enum is closed on purpose; a type nothing exercises is a scenario that is missing."""
    used = {f.type for s in library.values() for f in s.faults}
    assert used == set(FaultType), sorted(str(t) for t in set(FaultType) - used)


#: The one structural row whose correct conclusion is that there is nothing to review.
#: S6-04 is S6-01's omission on the baseline where the omitted pathway carries no flux, so
#: `recommend_structural_review: false` is its ANSWER KEY (lead's ruling 1, 2026-09-09).
#: Named explicitly rather than skipped by a property, so that a row which quietly stopped
#: asking for a review could not join it by accident.
STRUCTURAL_ROWS_WITH_NOTHING_TO_REVIEW = frozenset({"S6-04"})


def test_structural_rows_abstain_and_ask_for_a_structural_review(library):
    """Level 6 is never scored on parameter recovery (CLAUDE.md, domain reminders).

    Every structural row abstains. Every structural row also asks for a structural review,
    with exactly one declared exception: the row where the omitted pathway carries no flux,
    and where asking for a review would be the error the row exists to catch.
    """
    asked = set()
    for scenario in library.values():
        if TruthLabel.STRUCTURAL not in scenario.truth_label:
            continue
        assert scenario.correct_conclusion.abstain_on, scenario.id
        if scenario.correct_conclusion.recommend_structural_review:
            asked.add(scenario.id)
        else:
            assert scenario.id in STRUCTURAL_ROWS_WITH_NOTHING_TO_REVIEW, scenario.id
        if TruthLabel.PARAMETER not in scenario.truth_label:
            assert not scenario.correct_conclusion.kinetic_update_allowed, scenario.id
    # the exception is an exception: the other structural rows still ask
    assert asked and not (asked & STRUCTURAL_ROWS_WITH_NOTHING_TO_REVIEW)


def test_the_two_sao_rows_are_the_same_fault_on_two_declared_baselines(library):
    """The pair is the point (lead's ruling 1, 2026-09-09).

    A benchmark that only asks "find the structural fault" rewards a workflow that always
    answers "structural". S6-01 and S6-04 inject the SAME omission on the SAME plant and
    differ in one declared property — which baseline the digester is in — so §6.7 B can
    tell a diagnosis from a reflex.
    """
    bites, quiet = library["S6-01"], library["S6-04"]
    assert (
        [f.type for f in bites.faults] == [f.type for f in quiet.faults] == [FaultType.OMITTED_SAO]
    )
    assert str(bites.plant) == str(quiet.plant) == "A"
    assert bites.level == quiet.level == 6
    assert bites.baseline == "unadapted" and quiet.baseline == "adapted"
    # opposite answer keys, which is the whole of it
    assert bites.correct_conclusion.recommend_structural_review
    assert not quiet.correct_conclusion.recommend_structural_review
    assert bites.seed != quiet.seed


def test_only_parameter_rows_allow_a_kinetic_update(library):
    """Everything else counts a kinetic move as the false kinetic drift of Appendix A."""
    for scenario in library.values():
        allowed = scenario.correct_conclusion.kinetic_update_allowed
        is_parameter = TruthLabel.PARAMETER in scenario.truth_label
        is_clean = TruthLabel.NONE in scenario.truth_label
        assert allowed == (is_parameter or is_clean), (scenario.id, allowed)


def test_sensor_rows_name_the_sensor_and_influent_rows_revise_the_mapping(library):
    """One exception, and it is principled rather than a weakening.

    `informative_missingness` is not one instrument going wrong: it scales the conditional
    loss rate of *every* instrument, so there is no sensor to name and the §6.3 conclusion
    for that row is "recognise missing transient; abstain or widen". Every other
    sensor-labelled row names the instrument at fault.
    """
    for scenario in library.values():
        labels = set(scenario.truth_label)
        whole_instrument_set = {f.type for f in scenario.faults} == {
            FaultType.INFORMATIVE_MISSINGNESS
        }
        if TruthLabel.SENSOR in labels and not whole_instrument_set:
            assert scenario.correct_conclusion.flag_sensor, scenario.id
        if TruthLabel.SENSOR in labels and whole_instrument_set:
            assert scenario.correct_conclusion.flag_sensor is None, scenario.id
            assert scenario.correct_conclusion.abstain_on, scenario.id
        if TruthLabel.INFLUENT in labels:
            assert scenario.correct_conclusion.revise_influent_mapping, scenario.id
        if labels == {TruthLabel.NONE}:
            assert scenario.correct_conclusion.flag_sensor is None, scenario.id
            assert not scenario.correct_conclusion.revise_influent_mapping, scenario.id


def test_the_ammonia_rows_are_the_plant_a_only_set(library):
    """§6.3: the Level-5 inhibition shift, the Level-6 omitted SAO and their compound.

    Four rows since the lead's ruling 1 of 2026-09-09 added S6-04, the second staging of
    the omitted-SAO row. All four run on Plant A alone: syntrophic acetate oxidation only
    matters where free ammonia suppresses the acetoclastic route, which is Plant A's
    envelope and not Muscatine's.
    """
    inhibition = {
        s.id
        for s in library.values()
        if any(f.type is FaultType.AMMONIA_INHIBITION_SHIFT for f in s.faults)
    }
    sao = {s.id for s in library.values() if any(f.type is FaultType.OMITTED_SAO for f in s.faults)}
    assert inhibition | sao == set(AMMONIA_SCENARIOS)
    assert len(AMMONIA_SCENARIOS) == 4
    for sid in AMMONIA_SCENARIOS:
        assert str(library[sid].plant) == "A", sid


# ------------------------------------------------------------------ the matrix


def test_the_matrix_has_the_shape_of_section_7():
    """§7: 16 scenarios x 3 tiers x 2 plants for the factorial, Plant A separate."""
    cells = matrix_cells()
    factorial = [c for c in cells if c.plant in FACTORIAL_PLANTS]
    plant_a = [c for c in cells if c.plant == "A"]

    assert len(factorial) == 16 * len(ALL_TIERS) * len(FACTORIAL_PLANTS) == 96
    assert not [c for c in factorial if c.scenario_id in AMMONIA_SCENARIOS]
    for plant in FACTORIAL_PLANTS:
        per_plant = {c.scenario_id for c in factorial if c.plant == plant}
        assert len(per_plant) == 16, sorted(per_plant)
        for scenario_id in per_plant:
            tiers = sorted(
                c.tier for c in factorial if c.plant == plant and c.scenario_id == scenario_id
            )
            assert tiers == list(ALL_TIERS), (plant, scenario_id, tiers)

    # Plant A: Levels 2-5 at Tier A only, plus the three ammonia rows at every tier.
    library = load_library()
    level_2_to_5 = {s.id for s in library.values() if 2 <= s.level <= 5}
    assert len(level_2_to_5) == 10
    for scenario_id in level_2_to_5 - set(AMMONIA_SCENARIOS):
        tiers = sorted(c.tier for c in plant_a if c.scenario_id == scenario_id)
        assert tiers == ["A"], (scenario_id, tiers)
    for scenario_id in AMMONIA_SCENARIOS:
        tiers = sorted(c.tier for c in plant_a if c.scenario_id == scenario_id)
        assert tiers == list(ALL_TIERS), (scenario_id, tiers)
    # (10 Level-2..5 rows less S5-01, which is an ammonia row) x Tier A, plus the four
    # ammonia rows x three tiers. S6-04 is Level 6, so it is not in the Level-2..5 set.
    assert len(plant_a) == (10 - 1) * 1 + 4 * 3 == 21
    assert len(cells) == 96 + 21 == 117


def test_tiers_of_one_cell_share_one_truth_integration():
    """A tier is a mask (§6.4), so the three tiers of a cell are one run of the digester."""
    cells = matrix_cells()
    keys = {c.key for c in cells}
    assert len(keys) == 45, len(keys)  # 16 x 2 factorial + 13 distinct Plant A scenarios
    for key in keys:
        group = [c for c in cells if c.key == key]
        assert len({c.tier for c in group}) == len(group)  # no tier twice in a group


def test_cells_are_stable_and_ordered():
    """The matrix is deterministic: the same call gives the same list, in the same order."""
    assert matrix_cells() == matrix_cells()
    cells = matrix_cells()
    assert cells == sorted(cells, key=lambda c: (c.scenario_id, c.plant, c.tier, c.replicate))


def test_replicates_multiply_the_cells_without_changing_their_identity():
    one = matrix_cells(replicates=1)
    five = matrix_cells(replicates=5)
    assert len(five) == 5 * len(one)
    assert {(c.scenario_id, c.plant, c.tier) for c in five} == {
        (c.scenario_id, c.plant, c.tier) for c in one
    }
    assert sorted({c.replicate for c in five}) == [0, 1, 2, 3, 4]
