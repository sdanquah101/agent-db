"""The run harness: does a generated run have the properties gate G1 rests on?

Seven claims, each checked against something other than the code that makes it:

1. **The layout is the declared one.** Every file :mod:`sim.run.layout` names exists, and
   nothing hidden has leaked into ``observations/``.
2. **The burn-in has converged.** Measured, not assumed: a burn-in of 1.5x the configured
   length reaches the same state, so the scenario does not start on a transient the
   configuration happens to end in the middle of.
3. **Tiers are masks on identical truth** (§6.4): two tiers of one cell have bit-identical
   truth channels, and the higher tier's sensor set contains the lower's.
4. **The faults do what their magnitudes say.** The Level-4 biomass multiplier is read
   back off the state vector and compared with the number in the YAML; the Level-5
   parameter fault is read back off the segment parameters the same way. Neither test asks
   the applier what it did.
5. **The seeds are one per stream and the tier is not one of them.**
6. **Every simulator call is logged** (CLAUDE.md rule 3), and a second writer appending to
   the same run continues the sequence rather than restarting it, which is what the tool
   registry will do in a later milestone.
7. **The manifest partitions exactly** into the fields a workflow sees and the fields it
   must not, so neither side can gain a field the other forgets.

Runs are generated at short horizons into ``tmp_path``; each costs a few seconds.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat

import numpy as np
import pytest

from scenarios.schema import load_scenario
from sim.adm1 import (
    compile_extended,
    extended_state,
    load_extensions,
    load_initial_state,
    load_matrix,
    load_solver_config,
    simulate_extended,
)
from sim.influent import constant_influent, load_feed_fractionation, nominal_mass_rates
from sim.plants import declared_geometry, load_plant_config
from sim.plants.truth import load_plant_truth
from sim.run.harness import (
    NO_WRITE_KEY,
    VISIBLE_MTIME,
    apply_adaptation,
    generate_cells,
    generate_run,
    load_harness_config,
    simulate_truth,
)
from sim.run.layout import SALT_FILE, RunPaths, run_id, store_salt, truth_store_for
from sim.run.manifest import REDACTED_FIELDS, PublicManifest, RunManifest
from sim.run.matrix import Cell, execution_order, generate_matrix, matrix_cells
from sim.run.seeds import STREAM_ORDER, RunSeeds
from state.provenance import CallLog, args_hash, read_calls
from tests.conftest import REPO_ROOT

SCENARIOS = REPO_ROOT / "scenarios"
SHORT_DAYS = 40.0
"""Horizon of the runs generated here. Long enough to exercise every stage, short enough
that the file is not the slowest in the suite."""
TEST_SALT = bytes.fromhex("ad" * 32)
"""A fixed store salt for the tests that pin the id derivation (finding B1)."""


def _short(scenario_id: str, days: float = SHORT_DAYS):
    """A library scenario shortened for the tests, with its faults' onsets kept in range."""
    scenario = load_scenario(SCENARIOS / f"{scenario_id}.yaml")
    faults = tuple(
        f.model_copy(update={"onset_day": min(f.onset_day, days / 2)}) for f in scenario.faults
    )
    return scenario.model_copy(update={"duration_days": days, "faults": faults})


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory):
    """One clean Level-0 run on Plant C (the lightest plant), written to disk."""
    # the truth store is the run store's sibling, so each test gets its own parent
    root = tmp_path_factory.mktemp("store") / "runs"
    return generate_run(_short("S0-01"), "B", plant=load_plant_config("C"), runs_root=root)


# ------------------------------------------------------------------ 1. layout


def test_the_run_directory_is_the_declared_layout(clean_run):
    paths = clean_run.paths
    for path in (
        paths.manifest,
        paths.truth_manifest,
        paths.calls,
        paths.truth_parameters,
        paths.truth_influent,
        paths.truth_fractionation,
        paths.truth_geometry,
        paths.truth_states,
        paths.truth_channels,
        paths.truth_faults,
        paths.sensors,
        paths.feed_log,
        paths.feed_assays,
        paths.operator_notes,
    ):
        assert path.is_file(), path
    # hidden truth is its own top-level tree, not a subdirectory of the run: a workflow
    # rooted at the observations has nothing to escape to (the lead's ruling, 2026-09-04)
    assert paths.truth.parent.name == "truth_store"
    assert paths.root not in paths.truth.parents
    assert paths.observations.name == "observations"


def test_no_truth_file_sits_in_the_observations_directory(clean_run):
    """The two regions are written by two functions; this is the check that they stayed apart."""
    written = {p.name for p in clean_run.paths.observations.rglob("*") if p.is_file()}
    assert written == {"sensors.json", "feed_log.csv", "feed_assays.csv", "operator_notes.json"}


#: Vocabulary that only the hidden-truth record has any reason to use. Deliberately not
#: the bare word "fault": an operator note may legitimately say a pump was at fault, and a
#: test that forbade the word would be testing the note catalogue's prose rather than the
#: rule-1 boundary.
_TRUTH_VOCABULARY = (
    "truth",
    "truth_label",
    "correct_conclusion",
    "fault_layers",
    "omit_from_fitted",
    "biomass_multiplier",
    "stagnant_fraction",
    "mislabelled",
    "unrecorded",
    "k_i_nh3",
    "v_liq_true",
)


def test_the_observations_never_carry_a_hidden_quantity(clean_run):
    """A blunt substring sweep over everything a workflow can read.

    The true active volume, the realised volume error and the fault record's own
    vocabulary must not appear anywhere in the visible region — not in a value, not in a
    key, not in a note.
    """
    blob = "\n".join(
        p.read_text(encoding="utf-8")
        for p in clean_run.paths.observations.rglob("*")
        if p.is_file()
    )
    truth = clean_run.truth
    assert f"{truth.geometry.V_liq_true:.6g}" not in blob
    assert f"{truth.geometry.error_fraction:.6g}" not in blob
    for forbidden in _TRUTH_VOCABULARY:
        assert forbidden not in blob.lower(), forbidden


def test_no_operator_note_in_the_catalogue_could_trip_that_sweep():
    """The sweep above must test the boundary, not the note catalogue's word choice.

    Every benign note is checked here directly, over the whole catalogue rather than the
    handful a single run happens to draw — otherwise a note added later would make the
    sweep fail on a seed nobody ran.
    """
    from sim.run.notes import load_log_notes

    catalogue = load_log_notes()
    for note in (*catalogue.benign, catalogue.adversarial_for("S8-02")):
        for forbidden in _TRUTH_VOCABULARY:
            assert forbidden not in note.lower(), (forbidden, note)


def test_the_run_id_is_deterministic_and_says_nothing_about_the_scenario():
    """Proposal §10 mitigates scenario-name leakage; a directory name is a name too."""
    first = run_id("S2-03", "B", "A", 1023, key=TEST_SALT)
    assert first == run_id("S2-03", "B", "A", 1023, key=TEST_SALT)
    assert first != run_id("S2-03", "B", "B", 1023, key=TEST_SALT)
    assert first != run_id("S2-01", "B", "A", 1023, key=TEST_SALT)
    # and the same cell under another store's salt is another id entirely (finding B1)
    assert first != run_id("S2-03", "B", "A", 1023, key=bytes.fromhex("42" * 32))
    with pytest.raises(ValueError, match="no key"):
        run_id("S2-03", "B", "A", 1023, key=b"")
    assert first.startswith("run_") and len(first) == len("run_") + 12
    for leak in ("S2-03", "s2-03", "gas", "sensor"):
        assert leak not in first


# ------------------------------------------------------------------ 2. burn-in


def _burn_in_to(plant_id: str, days: float, params):
    """Integrate one plant's burn-in to ``days`` and return the model and the final state."""
    plant = load_plant_config(plant_id)
    catalogue = load_feed_fractionation()
    model = compile_extended(
        params,
        declared_geometry(plant),
        load_matrix(),
        load_solver_config(),
        load_extensions(),
        plant.truth_model.extensions,
    )
    result = simulate_extended(
        y0=extended_state(
            model, load_initial_state(), load_harness_config().initial_extension_states
        ),
        influent=constant_influent(catalogue, nominal_mass_rates(plant, catalogue)),
        model=model,
        t_span=(0.0, days),
        t_eval=np.array([days]),
    )
    assert result.success, plant_id
    return model, result


def test_the_published_initial_state_config_matches_the_probe_module(probe_common):
    """`configs/adm1/initial_state_rj2006.yaml` is a transcription; this pins it as one.

    The Rosen & Jeppsson (2006) Table-5 state lived only in
    `scripts/adm1_candidates/common.py`, which is disposable probe code that `sim/` may not
    import (decision 2026-09-02). Moving it into `configs/` created a second copy, and a
    second copy of a number is a drift risk unless something compares them.
    """
    from sim.adm1.schema import LIQUID_STATE_NAMES, STATE_NAMES
    from tests.conftest import RJ2006_GAS_STATE

    vector = load_initial_state()
    assert vector.shape == (len(STATE_NAMES),)
    for i, name in enumerate(LIQUID_STATE_NAMES):
        assert vector[i] == pytest.approx(probe_common.STEADY_STATE_RJ2006[name], rel=0), name
    for i, name in enumerate(STATE_NAMES[len(LIQUID_STATE_NAMES) :], len(LIQUID_STATE_NAMES)):
        assert vector[i] == pytest.approx(RJ2006_GAS_STATE[name], rel=0), name


@pytest.mark.parametrize("plant_id", ["A", "B", "C"])
def test_the_burn_in_has_converged_on_every_plant(adm1_params, plant_id):
    """Independent of the harness: the same burn-in run 50 % longer reaches the same state.

    If the burn-in were not converged, a scenario would begin on a transient no fault
    caused and Level-4's mis-initialised biomass would be indistinguishable from it.
    Checked on all three plants. It used to exclude Plant A, whose acetoclasts washed out
    slowly at the ADM1 default so that no burn-in length converged without making the
    ammonia scenarios inert; Plant A's declared adaptation (the lead's ruling 2 of
    2026-09-03) removed that, and with it the 200-d workaround.

    States below 1e-3 kg COD/m3 are compared on an absolute floor rather than relatively:
    the SAO biomass washes out towards zero on these plants (X_sao ~ 1e-7 at Plant B), and
    a state that is decaying to nothing has a large *relative* change and no consequence.
    """
    cfg = load_harness_config()
    params = apply_adaptation(adm1_params, load_plant_config(plant_id))
    _, at_declared = _burn_in_to(plant_id, cfg.burn_in_days, params)
    _, at_longer = _burn_in_to(plant_id, cfg.burn_in_days * 1.5, params)
    scale = np.maximum(np.abs(at_declared.y[:, -1]), 1e-3)
    drift = np.abs(at_longer.y[:, -1] - at_declared.y[:, -1]) / scale
    assert drift.max() < 0.05, (plant_id, drift.max(), int(drift.argmax()))
    assert abs(at_longer.derived["pH"][-1] - at_declared.derived["pH"][-1]) < 0.005
    gas_a = float(at_declared.derived["q_gas_stp_dry"][-1])
    gas_b = float(at_longer.derived["q_gas_stp_dry"][-1])
    assert abs(gas_b - gas_a) / gas_a < 0.01


def test_plant_a_is_a_stable_adapted_digester_and_the_pathways_exclude(adm1_params):
    """Plant A's declared adaptation, and the competition it does *not* resolve.

    The lead's ruling 2 asked for a steady state with both acetoclastic and syntrophic
    populations present. Measured, no such state exists at any adapted constant: the two
    compete for one substrate, so one excludes the other, and the exchange point sits an
    order of magnitude below the adapted range. This pins both halves of that finding —
    the plant IS a stable adapted digester, and it is acetoclastic rather than mixed —
    because the scenario design (transitions rather than a mixed baseline) rests on it.

    It replaces the guard on the 200-d burn-in workaround, which the same ruling removed.
    """
    plant = load_plant_config("A")
    record = load_plant_truth(plant)
    block = record.baseline(plant.default_baseline).adaptation
    assert block is not None and block.K_I_nh3 is not None
    adapted = block.K_I_nh3
    assert 0.02 <= adapted <= 0.05, adapted  # the lead's ruled range
    assert adapted > 10.0 * adm1_params.kinetics.K_I_nh3  # far above the sludge default

    params = apply_adaptation(adm1_params, plant)
    assert params.kinetics.K_I_nh3 == pytest.approx(adapted)
    for other in ("B", "C"):
        untouched = apply_adaptation(adm1_params, load_plant_config(other))
        assert untouched.kinetics.K_I_nh3 == pytest.approx(adm1_params.kinetics.K_I_nh3)

    model, at_burn_in = _burn_in_to("A", load_harness_config().burn_in_days, params)
    names = model.state_names
    adapted_ac = float(at_burn_in.y[names.index("X_ac"), -1])
    adapted_sao = float(at_burn_in.y[names.index("X_sao"), -1])
    nh3_mg_per_l = float(at_burn_in.derived["S_nh3"][-1]) * 14.007 * 1000.0
    assert nh3_mg_per_l > 150.0, nh3_mg_per_l  # still a high-ammonia digester
    assert adapted_ac > 0.5, adapted_ac  # the adapted acetoclasts hold their own...
    assert adapted_sao < 1e-3, adapted_sao  # ... and exclude the oxidisers entirely

    # at the ADM1 default the winner flips, which is what makes a loss of adaptation a
    # pathway shift rather than a nudge. The acetoclasts are still on their way out at the
    # burn-in length rather than gone (they reach ~0 by 1000 d), so the comparison is with
    # the adapted run and not with zero.
    _, unadapted = _burn_in_to("A", load_harness_config().burn_in_days, adm1_params)
    unadapted_ac = float(unadapted.y[names.index("X_ac"), -1])
    assert float(unadapted.y[names.index("X_sao"), -1]) > 0.5
    assert unadapted_ac < 0.1 * adapted_ac, (unadapted_ac, adapted_ac)


def test_plant_a_declares_two_baselines_and_they_are_different_digesters():
    """The lead's ruling 1 of 2026-09-09, and the property S6-01 now rests on.

    S6-01 was inert: the omitted SAO pathway carried no flux at Plant A's adapted,
    acetoclastic baseline, so denying it to the fitted model produced no residual. The fix
    is a **declared second baseline**, not a burn-in length and not a scenario edit — so
    what has to hold is that the two baselines really are different digesters and that each
    scenario is staged on the one its answer key assumes.

    Measured here rather than restated: on the unadapted baseline syntrophic oxidation
    carries the acetate flux, on the adapted one the acetoclasts do, and the acetate
    concentrations differ by nearly an order of magnitude while both stay sound.
    """
    plant = load_plant_config("A")
    names = {b.name for b in plant.baselines}
    assert names == {"adapted", "unadapted"}, names
    assert plant.default_baseline == "adapted"
    # what each baseline IS lives truth-side (lead's ruling B5, 2026-09-10), keyed by the
    # names the visible contract declares
    record = load_plant_truth(plant)
    assert record.baseline("adapted").adaptation.K_I_nh3 == pytest.approx(0.02)
    assert record.baseline("unadapted").adaptation is None  # the ADM1 default
    with pytest.raises(ValueError, match="declares no baseline"):
        plant.baseline("no-such-baseline")
    with pytest.raises(ValueError, match="has no baseline"):
        record.baseline("no-such-baseline")

    # the scenarios are staged where their answer keys assume
    staged = {load_scenario(SCENARIOS / f"{s}.yaml").baseline for s in ("S5-01", "S7-02")}
    assert staged == {"adapted"}, staged
    assert load_scenario(SCENARIOS / "S6-01.yaml").baseline == "unadapted"
    assert load_scenario(SCENARIOS / "S6-04.yaml").baseline == "adapted"

    # ... and they really are two digesters
    measured = {}
    for name in ("adapted", "unadapted"):
        scenario = _short("S0-01", days=60.0).model_copy(update={"plant": "A", "baseline": name})
        truth = simulate_truth(scenario, plant, RunSeeds.derive(1000, "A"))
        idx = {s: truth.state_names.index(s) for s in ("X_ac", "X_sao")}
        settled = truth.channels.t >= 20.0
        measured[name] = {
            "X_ac": float(truth.y[idx["X_ac"], -1]),
            "X_sao": float(truth.y[idx["X_sao"], -1]),
            "acetate": float(np.median(truth.channels["vfa_ac"][settled])),
            "sound": truth.health.sound,
        }

    adapted, unadapted = measured["adapted"], measured["unadapted"]
    assert adapted["sound"] and unadapted["sound"], measured  # two working digesters
    # the adapted one is acetoclastic: the pathway S6-04 omits carries nothing
    assert adapted["X_ac"] > 100.0 * adapted["X_sao"], adapted
    # the unadapted one is SAO-dominated: the pathway S6-01 omits carries everything
    assert unadapted["X_sao"] > 100.0 * unadapted["X_ac"], unadapted
    # and the difference is visible in the record, which is what makes S6-01 diagnosable
    assert unadapted["acetate"] > 3.0 * adapted["acetate"], measured


def test_the_feed_reseeds_syntrophic_oxidisers_so_a_washed_out_pathway_can_return():
    """ADM1 has no immigration, and a population at exactly zero can never come back.

    Without a trace of oxidisers in the feed, Plant A's loss-of-adaptation rows produce no
    pathway shift at all — acetate accumulates while nothing grows to consume it — and the
    Level-6/7 structural rows are inert because the fitted model omits a pathway carrying
    no flux. This pins the term's presence and its size: enough to survive, far too small
    to matter where it is not selected for.
    """
    seeded = load_harness_config().influent_extension_states.get("X_sao")
    assert seeded is not None and 0.0 < seeded <= 1e-3, seeded


def test_the_scenario_starts_from_the_burn_in_state(clean_run):
    """With no state fault the scenario's first state IS the burn-in's last."""
    np.testing.assert_array_equal(clean_run.truth.initial_state, clean_run.truth.burn_in_state)
    np.testing.assert_allclose(clean_run.truth.y[:, 0], clean_run.truth.initial_state, rtol=1e-10)


# ------------------------------------------------------------------ 3. tiers


def test_tiers_are_masks_on_identical_truth(tmp_path):
    """§6.4. Same digester, three windows: the channels must be bit-identical."""
    runs = generate_cells(
        _short("S1-01"), load_plant_config("C"), ["A", "B", "C"], runs_root=tmp_path / "runs"
    )
    a, b, c = runs
    for name in a.truth.channels.names:
        np.testing.assert_array_equal(a.truth.channels[name], b.truth.channels[name], err_msg=name)
        np.testing.assert_array_equal(a.truth.channels[name], c.truth.channels[name], err_msg=name)
    np.testing.assert_array_equal(a.truth.y, c.truth.y)
    assert set(a.record.names) < set(b.record.names) < set(c.record.names)
    # ... and three different run directories, each self-contained
    assert len({r.run_id for r in runs}) == 3
    for run in runs:
        assert run.paths.truth_states.is_file()


def test_a_tiers_feed_assays_are_the_tiers_own(tmp_path):
    """The mask is applied when the observations are written, not by the generator."""
    from sim.run.artifacts import read_feed_assays

    runs = generate_cells(
        _short("S0-01"), load_plant_config("C"), ["A", "C"], runs_root=tmp_path / "runs"
    )
    tier_a = {r["assay"] for r in read_feed_assays(runs[0].paths.feed_assays)}
    tier_c = {r["assay"] for r in read_feed_assays(runs[1].paths.feed_assays)}
    assert tier_a <= {"ts", "vs"}
    assert tier_a < tier_c
    assert {"cod", "tkn"} <= tier_c


# ------------------------------------------------------------------ 4. faults


def test_the_state_fault_scales_exactly_the_biomass_it_declares(tmp_path):
    """Read the multiplier back off the state vector and compare with the YAML's 0.25."""
    scenario = _short("S4-01")
    magnitude = next(f.magnitude for f in scenario.faults)
    assert magnitude == 0.25  # pins the scenario file, not the applier
    run = generate_run(scenario, "A", plant=load_plant_config("C"), runs_root=tmp_path / "runs")
    truth = run.truth
    biomass = {"X_su", "X_aa", "X_fa", "X_c4", "X_pro", "X_ac", "X_h2", "X_sao"}
    for i, name in enumerate(truth.state_names):
        expected = truth.burn_in_state[i] * (magnitude if name in biomass else 1.0)
        assert truth.initial_state[i] == pytest.approx(expected, rel=1e-12), name
    # and the digester really is short of biomass at the start
    i_ac = truth.state_names.index("X_ac")
    assert truth.y[i_ac, 0] < 0.5 * truth.burn_in_state[i_ac]


def test_the_parameter_fault_segments_the_run_at_its_onset(tmp_path):
    """Level 5: the run is integrated in two segments and the constant really changes."""
    scenario = _short("S5-02", days=60.0)
    magnitude = next(f.magnitude for f in scenario.faults)
    onset = next(f.onset_day for f in scenario.faults)
    plant = load_plant_config("C")
    truth = simulate_truth(scenario, plant, RunSeeds.derive(scenario.seed, "C"))
    assert len(truth.segments) == 2
    assert truth.segments[0][1] == pytest.approx(onset)
    before, after = truth.segments[0][2].kinetics, truth.segments[1][2].kinetics
    for name in ("k_hyd_ch", "k_hyd_pr", "k_hyd_li"):
        assert getattr(after, name) == pytest.approx(getattr(before, name) * magnitude)
    # nothing else moved
    assert after.k_m_ac == pytest.approx(before.k_m_ac)
    # and the trajectory is continuous across the boundary: one state, two segments
    assert truth.t.size == len(np.unique(truth.t))
    assert truth.t[0] == 0.0 and truth.t[-1] == pytest.approx(scenario.duration_days)


def test_a_structural_row_keeps_the_extension_in_the_truth_and_denies_it_to_the_fitted_model(
    tmp_path,
):
    """§6.3 Level 6: the truth model is never the one that loses the mechanism."""
    plant = load_plant_config("B")
    scenario = _short("S6-02")
    truth = simulate_truth(scenario, plant, RunSeeds.derive(scenario.seed, "B"))
    assert "precipitation" in plant.truth_model.extensions
    assert "X_caco3" in truth.state_names  # the truth still carries the calcite state
    assert "precipitation" not in truth.fitted_extensions
    assert set(truth.fitted_extensions) == set(plant.truth_model.extensions) - {"precipitation"}


def test_the_mixing_row_makes_the_truth_reactor_two_zone(tmp_path):
    """Level 6, imperfect mixing: the stagnant fraction is the scenario's magnitude."""
    scenario = _short("S6-03")
    magnitude = next(f.magnitude for f in scenario.faults)
    truth = simulate_truth(scenario, load_plant_config("C"), RunSeeds.derive(scenario.seed, "C"))
    assert not truth.mixing.ideal
    assert truth.mixing.stagnant_fraction == pytest.approx(magnitude)
    assert truth.mixing.bypass_fraction == pytest.approx(magnitude / 5.0)  # configs/faults
    # the truth trajectory really carries two zones: the stagnant zone's liquid states are
    # appended with a `_stag` suffix, so the vector is longer than a single-zone run's
    assert truth.y.shape[0] == len(truth.state_names)
    stagnant = [n for n in truth.state_names if n.endswith("_stag")]
    assert len(stagnant) == 29, len(stagnant)  # 26 standard liquid + 3 extension components
    assert "X_ac_stag" in truth.state_names
    # and the two zones are genuinely different liquids by the end of the run
    i, j = truth.state_names.index("S_ac"), truth.state_names.index("S_ac_stag")
    assert truth.y[i, -1] != pytest.approx(truth.y[j, -1], rel=1e-6)


def test_every_run_carries_operator_notes_and_only_one_carries_the_false_one(tmp_path):
    """A clean run has a benign log; only the adversarial row has the false-cause note.

    The clean run is 100 d here rather than SHORT_DAYS: benign notes fall on each day
    independently at 6 per 100 d (the prefix-stable log of 2026-09-12, blocker 2, option b),
    so a 40-d run is empty with probability 0.94^40 = 8 %, and this seed's 40-d run was; at
    100 d the chance is 0.2 % and the claim "a clean run still has an operator log" is a
    property of the design rather than of one seed.
    """
    """The Level-8 note must not be identifiable by the existence of a notes file."""
    from sim.run.artifacts import read_operator_notes

    clean = generate_run(
        _short("S0-01", days=100.0), "B", plant=load_plant_config("C"), runs_root=tmp_path / "runs"
    )
    adversarial = generate_run(
        _short("S8-02"), "B", plant=load_plant_config("C"), runs_root=tmp_path / "runs"
    )
    clean_notes = read_operator_notes(clean.paths.operator_notes)
    bad_notes = read_operator_notes(adversarial.paths.operator_notes)
    assert clean_notes, "a clean run must still have an operator log"
    assert {n["author"] for n in clean_notes} == {"operator"}
    assert "process_engineer" in {n["author"] for n in bad_notes}
    claim = next(n for n in bad_notes if n["author"] == "process_engineer")["text"]
    assert "hydrolysis" in claim.lower()  # it points at the kinetics, which is the trap


def test_the_workflow_fault_never_reaches_the_observations(tmp_path):
    """Level 8: knowing in advance which tool will fail is the answer to that row."""
    run = generate_run(
        _short("S8-01"), "B", plant=load_plant_config("C"), runs_root=tmp_path / "runs"
    )
    assert run.workflow_faults == (("bayes_mcmc", 1.0),)
    blob = "\n".join(
        p.read_text(encoding="utf-8") for p in run.paths.observations.rglob("*") if p.is_file()
    )
    assert "bayes_mcmc" not in blob
    assert "bayes_mcmc" in run.paths.truth_faults.read_text(encoding="utf-8")


# ------------------------------------------------------------------ 5. seeds


def test_one_seed_per_stream_in_the_documented_order():
    seeds = RunSeeds.derive(1001, "B")
    values = [getattr(seeds, name) for name in STREAM_ORDER]
    assert len(set(values)) == len(STREAM_ORDER) == 5
    assert seeds == RunSeeds.derive(1001, "B")  # deterministic
    assert RunSeeds.derive(1001, "C") != seeds  # two plants are two digesters
    assert RunSeeds.derive(1002, "B") != seeds
    assert RunSeeds.derive(1001, "B", replicate=1) != seeds
    with pytest.raises(ValueError, match="unknown plant"):
        RunSeeds.derive(1, "D")


def test_the_seed_derivation_and_the_run_id_are_pinned():
    """Golden values, because nothing else notices when the derivation moves.

    Every test above says the derivation is *self-consistent*: same input, same output;
    different input, different output. All of that stays true if the stream order is
    reversed or the id salt is edited — and then every archived run's geometry seed is
    silently some other stream's, and every run directory is somewhere else. The numbers
    below are the contract with runs already on disk. If a change to `sim/run/seeds.py` or
    `sim/run/layout.py` fails this test, that is the point: it means the change re-rolls
    or relocates existing runs, and the record has to be updated deliberately.
    """
    assert STREAM_ORDER == ("geometry", "influent", "fault", "observation", "notes")
    seeds = RunSeeds.derive(1023, "B")
    assert tuple(getattr(seeds, name) for name in STREAM_ORDER) == (
        3_049_135_782,
        836_221_657,
        1_492_633_085,
        2_781_476_975,
        768_714_809,
    )
    assert RunSeeds.derive(1000, "A").as_dict() == {
        "base": 1000,
        "plant": "A",
        "replicate": 0,
        "geometry": 4_020_735_467,
        "influent": 1_099_728_727,
        "fault": 396_874_550,
        "observation": 3_216_793_928,
        "notes": 3_960_606_638,
    }
    # golden pins under a FIXED TEST SALT: the id is a keyed HMAC since finding B1
    # (2026-09-10), so the pins are of the derivation, not of any real store's ids
    assert run_id("S2-03", "B", "A", 1023, key=TEST_SALT) == "run_a1a25365de1b"
    assert run_id("S0-01", "C", "B", 1000, key=TEST_SALT) == "run_ff27b029a42d"
    assert run_id("S2-03", "B", "A", 1023, replicate=1, key=TEST_SALT) == "run_6f9f3f9f4667"


def test_the_tier_is_not_part_of_the_seed_derivation(tmp_path):
    """Otherwise a tier would be a different digester, not a different window on one."""
    runs = generate_cells(
        _short("S0-01"),
        load_plant_config("C"),
        ["A", "B"],
        runs_root=tmp_path / "runs",
        write=False,
    )
    assert runs[0].manifest.seeds == runs[1].manifest.seeds
    assert runs[0].truth.geometry == runs[1].truth.geometry


def test_a_scenario_without_a_seed_is_refused(tmp_path):
    """CLAUDE.md rule 4: no implicit seeds."""
    scenario = _short("S0-01").model_copy(update={"seed": None})
    with pytest.raises(ValueError, match="carries no seed"):
        generate_run(
            scenario, "A", plant=load_plant_config("C"), runs_root=tmp_path / "runs", write=False
        )


# ------------------------------------------------------------ 5b. determinism, end to end
#
# The seed tests above check the seed *derivation*. Nothing checked that the pipeline those
# seeds drive is itself deterministic: an unseeded `default_rng()` anywhere inside it, a
# dependence on dictionary or set iteration order, or a `hash()` of a string would leave
# every test above green and still make two generations of one cell differ.


def _fingerprint(run) -> str:
    """A hash of everything one generated run produced — truth and observations alike."""
    import hashlib

    h = hashlib.sha256()
    truth = run.truth
    for array in (truth.t, truth.y, truth.burn_in_state, truth.initial_state, truth.ash):
        h.update(np.ascontiguousarray(np.asarray(array, dtype=float)).tobytes())
    for name in truth.channels.names:
        h.update(name.encode())
        h.update(np.ascontiguousarray(truth.channels[name]).tobytes())
    h.update(f"{truth.geometry.V_liq_true!r}|{truth.geometry.error_fraction!r}".encode())
    for name in run.record.names:
        series = run.record[name]
        h.update(name.encode())
        h.update(np.ascontiguousarray(np.nan_to_num(series.value, nan=-1.0)).tobytes())
        h.update(series.missing.tobytes())
    for note in run.notes:
        h.update(repr(note.as_dict()).encode())
    return h.hexdigest()


def test_a_cell_generates_identically_twice(tmp_path):
    """Two generations of one cell, from scratch, are bit-identical throughout."""
    scenario = _short("S2-03")
    plant = load_plant_config("C")
    first = generate_run(scenario, "B", plant=plant, runs_root=tmp_path / "a", write=True)
    second = generate_run(scenario, "B", plant=plant, runs_root=tmp_path / "b", write=True)

    assert first.run_id == second.run_id
    assert _fingerprint(first) == _fingerprint(second)
    # and the files on disk agree byte for byte, which the objects above do not guarantee
    for relative in ("sensors.json", "feed_log.csv", "feed_assays.csv", "operator_notes.json"):
        assert (first.paths.observations / relative).read_bytes() == (
            second.paths.observations / relative
        ).read_bytes(), relative
    # the manifest differs only in the two fields that describe *when* it was written
    a = json.loads(first.paths.truth_manifest.read_text(encoding="utf-8"))
    b = json.loads(second.paths.truth_manifest.read_text(encoding="utf-8"))
    for volatile in ("created_utc", "git_sha"):
        a.pop(volatile), b.pop(volatile)
    assert a == b


def test_a_cell_generates_identically_in_a_fresh_process(tmp_path):
    """The same cell, in a subprocess, under a different string-hash salt.

    ``PYTHONHASHSEED`` changes ``hash()`` for every str, bytes and frozenset in the
    process. Anything in the pipeline that derived a stream, an ordering or a key from
    ``hash()`` would produce a different run here and be invisible to the in-process test
    above — which is exactly the trap ``sensor_stream_key`` exists to avoid. Two salts, so
    the comparison is between two genuinely different hashing regimes.
    """
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, %r)
        from pathlib import Path
        from tests.test_run_harness import _fingerprint, _short
        from sim.plants import load_plant_config
        from sim.run.harness import generate_run
        run = generate_run(
            _short("S2-03"), "B", plant=load_plant_config("C"),
            runs_root=Path(sys.argv[1]) / "runs", write=False,
        )
        print(run.run_id, _fingerprint(run))
        """
    ) % str(REPO_ROOT)

    # One store for all three generations: run ids are keyed by the store's salt (finding
    # B1, 2026-09-10), so the id is only expected to agree within a store. The record --
    # the fingerprint -- must agree regardless. The salts are created here, up front: a
    # no-write generation creates nothing itself (finding F5) and would otherwise key its
    # id with the fixed no-write key in both stores.
    store_salt(truth_store_for(tmp_path / "runs"))
    store_salt(truth_store_for(tmp_path / "elsewhere" / "runs"))
    outputs = []
    for hash_seed in ("0", "12345"):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "PYTHONHASHSEED": hash_seed},
            timeout=600,
        )
        assert result.returncode == 0, result.stderr[-4000:]
        outputs.append(result.stdout.strip().splitlines()[-1])
    assert outputs[0] == outputs[1], outputs

    here = generate_run(
        _short("S2-03"),
        "B",
        plant=load_plant_config("C"),
        runs_root=tmp_path / "runs",
        write=False,
    )
    assert outputs[0] == f"{here.run_id} {_fingerprint(here)}"
    # ... and the same cell in a different store is the same record under a different id.
    elsewhere = generate_run(
        _short("S2-03"),
        "B",
        plant=load_plant_config("C"),
        runs_root=tmp_path / "elsewhere" / "runs",
        write=False,
    )
    assert _fingerprint(elsewhere) == _fingerprint(here)
    assert elsewhere.run_id != here.run_id


# ------------------------------------------------------------------ 6. provenance


@pytest.fixture(scope="module")
def three_tiers(tmp_path_factory):
    """One cell at all three tiers, sharing one integration (§6.4)."""
    root = tmp_path_factory.mktemp("tiers") / "runs"
    return generate_cells(_short("S0-01"), load_plant_config("C"), ["A", "B", "C"], runs_root=root)


def _assert_complete_logs(run) -> None:
    full = read_calls(run.paths.truth)
    visible = read_calls(run.paths.root)
    full_names = [r.name for r in full]
    assert "sim.generate_influent" in full_names
    assert "sim.burn_in" in full_names
    assert any(n.startswith("sim.simulate_truth_segment") for n in full_names)
    assert "sim.channel_series" in full_names
    assert full_names[-1] == "sim.observe" and full_names.count("sim.observe") == 1
    assert [r.name for r in visible] == [
        "sim.generate_influent",
        "sim.burn_in",
        "sim.simulate_truth",
        "sim.channel_series",
        "sim.observe",
    ]
    for records in (full, visible):
        assert [r.seq for r in records] == list(range(len(records)))
        for record in records:
            assert record.outcome == "ok"
            assert len(record.args_hash) == 16
    # the truth-side log carries the wall-clock rule 3 asks for; the projection does not
    for record in full:
        assert record.runtime_s is not None and record.runtime_s >= 0.0
        assert record.t_utc is not None
    for record in visible:
        assert record.runtime_s is None and record.t_utc is None


def test_every_simulator_call_is_logged(clean_run):
    """CLAUDE.md rule 3, on the harness's own calls -- in BOTH logs.

    The full log in ``truth_store/<id>/`` carries every call with its real arguments,
    segment by segment. The visible log in ``runs/<id>/`` carries the same calls, in the
    same order, with the same outcomes -- rule 3 is satisfied for a workflow -- but its
    integration is one record and its argument hashes say nothing the visible manifest
    does not (review finding B2, 2026-09-10; see the next test for the proof), and it
    carries no timestamp and no runtime (findings F1 and F3).
    """
    _assert_complete_logs(clean_run)


def test_every_tier_of_a_cell_carries_the_shared_integration_in_its_own_log(three_tiers):
    """Finding F4: the tiers share one integration, and every tier's log must show it.

    Before 2026-09-10 the second and third tiers' logs held only ``sim.observe``: the
    evaluator, which reads logs only, saw no integration behind two tiers of every cell.
    """
    assert [r.manifest.tier for r in three_tiers] == ["A", "B", "C"]
    for run in three_tiers:
        _assert_complete_logs(run)
    # the copied records are the SAME calls: identical hashes up to the observation, which
    # is each tier's own; and the truth-side copies keep the original timestamps
    visible = [read_calls(r.paths.root) for r in three_tiers]
    full = [read_calls(r.paths.truth) for r in three_tiers]
    for other in (1, 2):
        assert [r.args_hash for r in visible[other][:-1]] == [r.args_hash for r in visible[0][:-1]]
        assert [r.args_hash for r in full[other][:-1]] == [r.args_hash for r in full[0][:-1]]
        assert [r.t_utc for r in full[other][:-1]] == [r.t_utc for r in full[0][:-1]]
        assert visible[other][-1].args_hash != visible[0][-1].args_hash  # a different tier


def _visible_hashes_from_the_visible_record(run) -> list[str]:
    """What every visible args_hash MUST equal, computed from public facts alone.

    Only the redacted manifest a workflow can read and the committed harness config are
    used here -- no scenario id, no seed, no fault plan, no mixing structure. If the
    harness ever hashes anything else into the visible log, this stops matching.
    """
    public = PublicManifest.model_validate(json.loads(run.paths.manifest.read_text()))
    cfg = load_harness_config()
    n_days = round(public.duration_days)
    return [
        args_hash({"plant": public.plant, "n_days": n_days}),
        args_hash({"plant": public.plant, "days": cfg.burn_in_days}),
        args_hash({"plant": public.plant, "n_days": n_days}),
        args_hash({"n_times": int(run.truth.channels.t.size)}),
        args_hash({"tier": public.tier}),
    ]


def test_the_visible_log_says_nothing_the_manifest_does_not(clean_run):
    """Finding B2: the visible call log used to invert to the scenario id.

    ``runs/<id>/calls.jsonl`` is workflow-visible, and its ``args_hash`` covered the
    scenario id, the segment index and span, the derived seeds, the fault plans and the
    realised mixing structure -- all drawn from small public spaces, so
    ``75fbaaa4b387afcc`` gave ``('S0-01', 0, 0.0, 180.0)`` on a real run. Now every visible
    hash is reproducible from the redacted manifest and the committed config alone, which
    is asserted by reproducing them; and the truth-side log still carries the scenario id,
    which is the negative control -- a redaction that emptied both logs would pass the
    first half and fail this.
    """
    visible = read_calls(clean_run.paths.root)
    assert [r.args_hash for r in visible] == _visible_hashes_from_the_visible_record(clean_run)
    # negative control: the FULL log is not redacted -- its hashes differ from the visible
    # ones, and its channel_series record hashes the scenario id in
    full = read_calls(clean_run.paths.truth)
    assert {r.args_hash for r in full}.isdisjoint({r.args_hash for r in visible})
    manifest = RunManifest.model_validate(json.loads(clean_run.paths.truth_manifest.read_text()))
    channel = next(r for r in full if r.name == "sim.channel_series")
    assert channel.args_hash == args_hash(
        {
            "scenario": manifest.scenario_id,
            "n_times": int(clean_run.truth.channels.t.size),
            "ideal_mixing": clean_run.truth.mixing.ideal,
        }
    )


def test_the_visible_log_collapses_the_segments(tmp_path):
    """Finding B2: the NUMBER of segment records said whether a parameter fault existed.

    A Level-5 row integrates in two segments around its onset; a Level-0 row in one. The
    full log records each segment; the visible log records one integration either way.
    """
    scenario = load_scenario(SCENARIOS / "S5-01.yaml")
    onset = min(f.onset_day for f in scenario.faults)
    faulted = scenario.model_copy(update={"duration_days": float(onset + 10)})
    run = generate_run(faulted, "B", runs_root=tmp_path / "runs")
    assert len(run.truth.segments) >= 2, "S5-01 must integrate in at least two segments"
    full = read_calls(run.paths.truth)
    visible = read_calls(run.paths.root)
    assert sum(r.name == "sim.simulate_truth_segment" for r in full) == len(run.truth.segments)
    assert sum(r.name == "sim.simulate_truth" for r in visible) == 1
    assert not any(r.name.startswith("sim.simulate_truth_segment") for r in visible)
    # and the one visible record says nothing about how long the integration took: the
    # runtime alone marked the two-zone row (finding F3), so the projection carries none
    integration = next(r for r in visible if r.name == "sim.simulate_truth")
    assert integration.runtime_s is None and integration.t_utc is None
    assert all(r.runtime_s is not None for r in full if r.name == "sim.simulate_truth_segment")


def test_regenerating_a_cell_starts_its_logs_over(tmp_path):
    """A regenerated cell's logs are the record of this generation, not an append.

    One cell generated twice used to carry seq 0..9: the index was de-duplicated, the log
    was not (review, 2026-09-10).
    """
    root = tmp_path / "runs"
    first = generate_run(_short("S0-01"), "A", plant=load_plant_config("C"), runs_root=root)
    n_visible = len(read_calls(first.paths.root))
    n_full = len(read_calls(first.paths.truth))
    again = generate_run(_short("S0-01"), "A", plant=load_plant_config("C"), runs_root=root)
    assert again.paths.root == first.paths.root  # same cell, same directory
    assert len(read_calls(again.paths.root)) == n_visible
    assert len(read_calls(again.paths.truth)) == n_full
    assert [r.seq for r in read_calls(again.paths.root)] == list(range(n_visible))


def test_faulted_and_unfaulted_visible_logs_are_indistinguishable_in_structure(clean_run, tmp_path):
    """Finding B2, the lead's addition: the visible log must not reveal a split integration.

    Same record count, same names, same field set for S0-01 and S5-01.
    """
    scenario = load_scenario(SCENARIOS / "S5-01.yaml")
    onset = min(f.onset_day for f in scenario.faults)
    faulted = generate_run(
        scenario.model_copy(update={"duration_days": float(onset + 10)}),
        "B",
        runs_root=tmp_path / "runs",
    )
    assert len(faulted.truth.segments) >= 2 and len(clean_run.truth.segments) == 1
    unfaulted_log = [json.loads(line) for line in clean_run.paths.calls.read_text().splitlines()]
    faulted_log = [json.loads(line) for line in faulted.paths.calls.read_text().splitlines()]
    assert len(faulted_log) == len(unfaulted_log)
    assert [r["name"] for r in faulted_log] == [r["name"] for r in unfaulted_log]
    assert [set(r) for r in faulted_log] == [set(r) for r in unfaulted_log]
    assert not any("segment" in r["name"] for r in faulted_log)


# ------------------------------------------------------ 7. the run id (finding B1)


def _public_tuple_space():
    """Every (scenario, plant, tier, seed, replicate) a committed cell could be."""
    scenarios = [load_scenario(path) for path in sorted(SCENARIOS.glob("S*.yaml"))]
    for sc in scenarios:
        for plant in ("A", "B", "C"):
            for tier in ("A", "B", "C"):
                for replicate in range(3):
                    yield sc.id, plant, tier, sc.seed, replicate


def test_two_stores_give_every_cell_a_different_id():
    """Finding B1 (a): the same cell under two salts is two ids, for every cell."""
    salt_1, salt_2 = bytes.fromhex("11" * 32), bytes.fromhex("22" * 32)
    cells = list(_public_tuple_space())
    assert len(cells) > 100
    ids_1 = [run_id(*c[:4], replicate=c[4], key=salt_1) for c in cells]
    ids_2 = [run_id(*c[:4], replicate=c[4], key=salt_2) for c in cells]
    assert all(a != b for a, b in zip(ids_1, ids_2, strict=True))
    assert len(set(ids_1)) == len(cells) and len(set(ids_2)) == len(cells)  # no collisions


def _json_keys_and_leaves(node) -> tuple[list[str], list[object]]:
    """Every key and every leaf value of a JSON document, in document order."""
    keys: list[str] = []
    leaves: list[object] = []
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            keys.extend(item)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        else:
            leaves.append(item)
    return keys, leaves


def test_no_visible_file_carries_the_salt_or_the_cell(clean_run):
    """Finding B1 (b): nothing under runs/<id>/ carries the salt, the scenario id or the seed.

    The salt is looked for as bytes and as hex, the seed as any integer JSON value, and
    "seed"/"scenario" as any key or log field -- in any form.
    """
    salt = store_salt(truth_store_for(clean_run.paths.root.parent))
    assert (truth_store_for(clean_run.paths.root.parent) / SALT_FILE).is_file()
    scenario = load_scenario(SCENARIOS / "S0-01.yaml")
    seed = int(scenario.seed)
    files = [f for f in clean_run.paths.root.rglob("*") if f.is_file()]
    assert files
    for path in files:
        raw = path.read_bytes()
        assert salt not in raw, path
        text = raw.decode("utf-8", "replace")
        assert salt.hex() not in text.lower(), path
        assert scenario.id not in text, path
        if path.suffix == ".json":
            keys, values = _json_keys_and_leaves(json.loads(text))
            assert not any("seed" in k.lower() for k in keys), (path, keys)
            assert seed not in [v for v in values if isinstance(v, int)], path
        elif path.suffix == ".jsonl":
            for line in text.splitlines():
                assert "seed" not in line.lower() and "scenario" not in line.lower(), path


def test_the_brute_force_inversion_recovers_nothing_without_the_salt(clean_run):
    """Finding B1 (c): the review's attack, run for real.

    Enumerate the public tuple space, hash it every way an attacker without the salt
    could, and match against a real id.
    """
    target = clean_run.run_id
    cells = list(_public_tuple_space())
    # the pre-ruling scheme: sha256 over the repository-literal salt and the tuple
    old = {
        "run_" + hashlib.sha256(f"ad-agentbench/g1|{s}|{p}|{t}|{d}|{r}".encode()).hexdigest()[:12]
        for s, p, t, d, r in cells
    }
    assert target not in old
    # a keyed guess without the key: every plausible wrong key recovers nothing
    for guess in (bytes.fromhex("00" * 32), b"ad-agentbench/g1", TEST_SALT):
        assert target not in {run_id(*c[:4], replicate=c[4], key=guess) for c in cells}
    # negative control: WITH the store's salt the enumeration finds the cell, exactly once
    salt = store_salt(truth_store_for(clean_run.paths.root.parent))
    hits = [c for c in cells if run_id(*c[:4], replicate=c[4], key=salt) == target]
    assert len(hits) == 1 and hits[0][0] == "S0-01", hits


def test_the_loader_has_no_route_to_the_scenario_files(clean_run):
    """Finding B5 (iii): the workflow loader has no route to scenarios/.

    It is rooted at runs/<id>/observations and cannot reach the scenario files any more
    than it can reach the truth store.
    """
    from state.run_view import TruthAccessError, open_run

    view = open_run(clean_run.paths.root)
    for relative in (
        "../../scenarios/S0-01.yaml",
        "../../../scenarios/S0-01.yaml",
        "/scenarios",
        "../../sim/plants/truth/plant_A.yaml",
    ):
        with pytest.raises((TruthAccessError, FileNotFoundError)):
            view.read_text(relative)
    assert not any("scenario" in f.lower() for f in view.files)


# ------------------------------------------------ 8. no visible wall-clock (finding F1)


_ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def test_no_visible_file_carries_a_timestamp(three_tiers):
    """Finding F1: nothing a workflow can read says when the run was generated.

    Not the manifest (``created_utc`` is redacted), not the call log (``t_utc`` is gone
    from the projection), and not the files' modification times, which are all set to one
    fixed instant. The truth-side manifest and log carry both: the negative control.
    """
    for run in three_tiers:
        public = PublicManifest.model_validate(json.loads(run.paths.manifest.read_text()))
        assert not hasattr(public, "created_utc")
        assert "created_utc" in REDACTED_FIELDS
        for path in run.paths.root.rglob("*"):
            assert abs(path.stat().st_mtime - VISIBLE_MTIME) < 1.0, path
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                assert not _ISO_TIMESTAMP.search(text), (path, _ISO_TIMESTAMP.search(text))
        assert abs(run.paths.root.stat().st_mtime - VISIBLE_MTIME) < 1.0
        # the negative control: the truth store still says when
        complete = json.loads(run.paths.truth_manifest.read_text())
        assert _ISO_TIMESTAMP.search(complete["created_utc"])
        assert all(_ISO_TIMESTAMP.search(r.t_utc) for r in read_calls(run.paths.truth))
        assert abs(run.paths.truth_manifest.stat().st_mtime - VISIBLE_MTIME) > 86400.0


def test_the_execution_order_is_keyed_by_the_store_salt():
    """Finding F1: a shuffle seeded with a committed constant is a public permutation.

    The reviewer reproduced it and mapped position to cell. The order of a written matrix
    is now keyed with the store's secret salt: two stores generate the same cells in two
    different orders, neither of which is the library order, and a generation with no
    store falls back to the declared constant seed and is reproducible.
    """
    cells = matrix_cells()
    library_order = [group for _, group in _library_groups(cells)]
    salt_1, salt_2 = bytes.fromhex("11" * 32), bytes.fromhex("22" * 32)
    order_1 = execution_order(cells, salt_1)
    order_2 = execution_order(cells, salt_2)
    order_none = execution_order(cells, None)
    for order in (order_1, order_2, order_none):
        assert {tuple(g) for g in order} == {tuple(g) for g in library_order}  # a permutation
        assert len(order) == len(library_order) and order != library_order
    assert order_1 != order_2 and order_1 != order_none and order_2 != order_none
    assert execution_order(cells, salt_1) == order_1  # deterministic in the salt
    assert execution_order(cells, None) == order_none  # ... and without one


def _library_groups(cells):
    """The truth groups in library order, as generate_matrix received them before F1."""
    ordered: dict[tuple, list] = {}
    for cell in cells:
        ordered.setdefault(cell.key, []).append(cell)
    return list(ordered.items())


def test_two_stores_generate_the_same_cells_in_their_own_orders(tmp_path):
    """Finding F1, end to end: the order on disk follows the store's salt, not the library.

    Two stores with two salts generate the same small matrix; the truth-side
    ``created_utc`` (the only timestamp left) orders each store's runs exactly as
    :func:`execution_order` predicts for its salt -- so the wiring is asserted rather than
    inferred from the two orders happening to differ.
    """
    plant = load_plant_config("C")
    library = {"S0-01": _short("S0-01"), "S2-03": _short("S2-03")}
    library["S0-01"] = library["S0-01"].model_copy(update={"plant": "C"})
    library["S2-03"] = library["S2-03"].model_copy(update={"plant": "C"})
    cells = [Cell("S0-01", "C", "A", 1000, 0), Cell("S2-03", "C", "A", 1023, 0)]
    del plant
    # two salts whose predicted orders differ, chosen by construction rather than by luck:
    # with two groups a random pair of salts would agree half the time
    first = bytes.fromhex("11" * 32)
    second = next(
        bytes.fromhex(f"{i:02x}" * 32)
        for i in range(2, 64)
        if execution_order(cells, bytes.fromhex(f"{i:02x}" * 32)) != execution_order(cells, first)
    )
    orders = {}
    for salt in (first, second):
        root = tmp_path / salt.hex()[:4] / "runs"
        store = truth_store_for(root)
        store.mkdir(parents=True)
        (store / SALT_FILE).write_bytes(salt)
        results = generate_matrix(cells, runs_root=root, library=library)
        assert all(r.ok for r in results)
        by_time = sorted(
            results,
            key=lambda r: json.loads(RunPaths.for_run(r.run_id, root).truth_manifest.read_text())[
                "created_utc"
            ],
        )
        orders[salt] = [r.cell for r in by_time]
        predicted = [group[0] for group in execution_order(cells, salt)]
        assert orders[salt] == predicted, (orders[salt], predicted)
        # and the visible side of both runs says nothing about the order
        for r in results:
            paths = RunPaths.for_run(r.run_id, root)
            assert "created_utc" not in json.loads(paths.manifest.read_text())
            assert all("t_utc" not in line for line in paths.calls.read_text().splitlines())
    assert len({tuple(o) for o in orders.values()}) == 2, orders


# ----------------------------------------------- 9. a no-write generation (finding F5)


def test_a_no_write_generation_writes_nothing(tmp_path):
    """Finding F5: ``write=False`` used to create the store's salt on the way past."""
    root = tmp_path / "store" / "runs"
    run = generate_run(
        _short("S0-01"), "B", plant=load_plant_config("C"), runs_root=root, write=False
    )
    assert not (tmp_path / "store").exists(), sorted((tmp_path / "store").rglob("*"))
    assert run.run_id == run_id("S0-01", "C", "B", _short("S0-01").seed, key=NO_WRITE_KEY)
    # a store that has a salt keys the no-write id with it, so the two agree
    store_salt(truth_store_for(root))
    again = generate_run(
        _short("S0-01"), "B", plant=load_plant_config("C"), runs_root=root, write=False
    )
    assert again.run_id != run.run_id
    assert (
        again.run_id
        == generate_run(_short("S0-01"), "B", plant=load_plant_config("C"), runs_root=root).run_id
    )


def test_the_salt_is_created_unreadable_to_others(tmp_path):
    """Finding F5: the salt is a secret, so its file mode is 0600, not the default 0644."""
    store = tmp_path / "truth_store"
    key = store_salt(store)
    assert len(key) == 32
    assert stat.S_IMODE((store / SALT_FILE).stat().st_mode) == 0o600
    assert store_salt(store) == key  # read back, not regenerated
    assert store_salt(tmp_path / "other", create=False) is None
    assert not (tmp_path / "other").exists()


def test_a_second_writer_continues_the_sequence(tmp_path):
    """The tool registry appends a workflow's calls to the same file in a later milestone."""
    first = CallLog(tmp_path)
    first.append("sim.simulate", "1.0", {"days": 1}, 0.1, "ok")
    first.append("sim.simulate", "1.0", {"days": 2}, 0.1, "ok")
    second = CallLog(tmp_path)  # a fresh writer on the same run
    assert second.n_calls == 2
    second.append("bayes_mcmc", "1.0", {"chains": 4}, 1.0, "injected_failure", "not converged")
    records = read_calls(tmp_path)
    assert [r.seq for r in records] == [0, 1, 2]
    assert records[-1].outcome == "injected_failure"


def test_a_raising_call_is_logged_before_the_exception_escapes(tmp_path):
    log = CallLog(tmp_path)
    with pytest.raises(ZeroDivisionError), log.record("t", "1.0", {"a": 1}):
        raise ZeroDivisionError("boom")
    (record,) = read_calls(tmp_path)
    assert record.outcome == "error" and "boom" in record.detail


def test_the_args_hash_is_a_fingerprint_of_values_not_of_order():
    assert args_hash({"a": 1, "b": 2}) == args_hash({"b": 2, "a": 1})
    assert args_hash({"a": 1}) != args_hash({"a": 2})
    assert args_hash({"a": np.arange(5)}) == args_hash({"a": np.arange(5)})
    assert args_hash({"a": np.arange(5)}) != args_hash({"a": np.arange(6)})
    assert len(args_hash({})) == 16


# ------------------------------------------------------------------ the manifest


def test_the_public_manifest_carries_no_redacted_field():
    """Every field of the full manifest is either public or explicitly redacted."""
    full = set(RunManifest.model_fields)
    public = set(PublicManifest.model_fields)
    assert public & REDACTED_FIELDS == set()
    assert full >= REDACTED_FIELDS
    assert full == public | REDACTED_FIELDS, full.symmetric_difference(public | REDACTED_FIELDS)


def test_the_written_manifest_round_trips_and_projects(clean_run):
    """Two files: the complete manifest in the truth store, the projection under runs/."""
    written = RunManifest.read(clean_run.paths.truth_manifest)
    assert written == clean_run.manifest
    stored = json.loads(clean_run.paths.truth_manifest.read_text(encoding="utf-8"))
    assert stored["scenario_id"] == "S0-01"  # it is in the truth store's file...

    public = written.public()
    visible = json.loads(clean_run.paths.manifest.read_text(encoding="utf-8"))
    assert "scenario_id" not in visible  # ...and not in the one a workflow can open
    assert visible == json.loads(public.model_dump_json())
    assert public.plant == "C" and public.tier == "B"
    assert public.configs.versions["observation_sensors"] >= 2
    assert public.git_sha


def test_the_index_maps_opaque_ids_back_to_cells(clean_run):
    index = clean_run.paths.truth.parent / "index.jsonl"
    entries = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
    mine = [e for e in entries if e["run_id"] == clean_run.run_id]
    assert mine and mine[0]["scenario_id"] == "S0-01" and mine[0]["plant"] == "C"
    # the index names the scenario of every run, so it belongs in the truth store, not
    # one level above a directory a workflow is handed
    assert not (clean_run.paths.root.parent / "index.jsonl").exists()


def test_regenerating_a_cell_does_not_duplicate_its_index_line(tmp_path):
    """A run id is a hash of its cell, so a regenerated cell overwrites its own directory.

    An index that merely appended would carry the cell twice and an evaluator counting its
    lines would over-count every regenerated cell.
    """
    from sim.run.manifest import write_index_entry

    index = tmp_path / "index.jsonl"
    write_index_entry(index, {"run_id": "run_a", "scenario_id": "S0-01", "tier": "A"})
    write_index_entry(index, {"run_id": "run_b", "scenario_id": "S1-01", "tier": "A"})
    write_index_entry(index, {"run_id": "run_a", "scenario_id": "S0-01", "tier": "B"})

    entries = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
    assert [e["run_id"] for e in entries] == ["run_a", "run_b"], "one line per run id"
    assert entries[0]["tier"] == "B", "and it is the latest write, not the first"


def test_run_paths_are_declared_in_one_place(tmp_path):
    paths = RunPaths.for_run("run_abc", tmp_path / "runs").create()
    assert paths.truth.is_dir() and paths.observations.is_dir()
    assert paths.truth_states.parent == paths.truth
    assert paths.truth_manifest.parent == paths.truth
    assert paths.sensors.parent == paths.observations
    assert paths.truth == tmp_path / "truth_store" / "run_abc"
