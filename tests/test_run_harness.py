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

import json

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
from sim.run.harness import generate_cells, generate_run, load_harness_config, simulate_truth
from sim.run.layout import RunPaths, run_id
from sim.run.manifest import REDACTED_FIELDS, PublicManifest, RunManifest
from sim.run.seeds import STREAM_ORDER, RunSeeds
from state.provenance import CallLog, args_hash, read_calls
from tests.conftest import REPO_ROOT

SCENARIOS = REPO_ROOT / "scenarios"
SHORT_DAYS = 40.0
"""Horizon of the runs generated here. Long enough to exercise every stage, short enough
that the file is not the slowest in the suite."""


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
    root = tmp_path_factory.mktemp("runs")
    return generate_run(_short("S0-01"), "B", plant=load_plant_config("C"), runs_root=root)


# ------------------------------------------------------------------ 1. layout


def test_the_run_directory_is_the_declared_layout(clean_run):
    paths = clean_run.paths
    for path in (
        paths.manifest,
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
    assert paths.truth.name == "truth"
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
    first = run_id("S2-03", "B", "A", 1023)
    assert first == run_id("S2-03", "B", "A", 1023)
    assert first != run_id("S2-03", "B", "B", 1023)
    assert first != run_id("S2-01", "B", "A", 1023)
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


@pytest.mark.parametrize("plant_id", ["B", "C"])
def test_the_burn_in_has_converged_on_the_factorial_plants(adm1_params, plant_id):
    """Independent of the harness: the same burn-in run 50 % longer reaches the same state.

    If the burn-in were not converged, a scenario would begin on a transient no fault
    caused and Level-4's mis-initialised biomass would be indistinguishable from it.
    Checked on Plants B and C, which carry the factorial; Plant A is a different story and
    has its own test below.

    States below 1e-3 kg COD/m3 are compared on an absolute floor rather than relatively:
    the SAO biomass washes out towards zero on these plants (X_sao ~ 1e-7 at Plant B), and
    a state that is decaying to nothing has a large *relative* change and no consequence.
    """
    cfg = load_harness_config()
    _, at_declared = _burn_in_to(plant_id, cfg.burn_in_days, adm1_params)
    _, at_longer = _burn_in_to(plant_id, cfg.burn_in_days * 1.5, adm1_params)
    scale = np.maximum(np.abs(at_declared.y[:, -1]), 1e-3)
    drift = np.abs(at_longer.y[:, -1] - at_declared.y[:, -1]) / scale
    assert drift.max() < 0.05, (plant_id, drift.max(), int(drift.argmax()))
    assert abs(at_longer.derived["pH"][-1] - at_declared.derived["pH"][-1]) < 0.005
    gas_a = float(at_declared.derived["q_gas_stp_dry"][-1])
    gas_b = float(at_longer.derived["q_gas_stp_dry"][-1])
    assert abs(gas_b - gas_a) / gas_a < 0.01


def test_plant_a_is_mid_succession_at_the_burn_in_length_and_that_is_the_point(adm1_params):
    """Plant A does NOT converge in 200 d, and lengthening the burn-in breaks three rows.

    Its free ammonia is inside the pathway-shift window, so the acetoclastic population is
    slowly losing to syntrophic acetate oxidation. The succession completes at ~800 d with
    the acetoclasts gone entirely - and from *that* state the Level-5 ammonia-inhibition
    fault has nothing to act on: doubling K_I_nh3 changes the gas rate by 0.002 % and
    acetate not at all, so S5-01, S6-01 and S7-02 would all be inert.

    This test is what stops someone "fixing" the convergence by lengthening the burn-in.
    It fails if the configured burn-in no longer leaves a mixed community, and it fails if
    the ammonia fault stops producing a signal there. See configs/runs/harness.yaml and
    docs/decisions.md, "Burn-in length, and Plant A's SAO succession".
    """
    cfg = load_harness_config()
    model, at_burn_in = _burn_in_to("A", cfg.burn_in_days, adm1_params)
    names = model.state_names
    x_ac = float(at_burn_in.y[names.index("X_ac"), -1])
    x_sao = float(at_burn_in.y[names.index("X_sao"), -1])
    nh3_mg_per_l = float(at_burn_in.derived["S_nh3"][-1]) * 14.007 * 1000.0

    assert 150.0 < nh3_mg_per_l < 300.0, nh3_mg_per_l  # inside the pathway-shift window
    assert x_ac > 0.1, x_ac  # a mixed community, not a pure-SAO one
    assert x_sao > 0.1, x_sao  # ... and SAO has genuinely established
    assert 0.2 < x_ac / x_sao < 5.0, (x_ac, x_sao)

    # and the succession really is still running: the acetoclasts are on their way out
    _, at_longer = _burn_in_to("A", 800.0, adm1_params)
    assert float(at_longer.y[names.index("X_ac"), -1]) < 0.01 * x_ac

    # the fault this state exists for produces a signal from here, and not from there
    def response(y0: np.ndarray, multiplier: float) -> tuple[float, float]:
        plant = load_plant_config("A")
        catalogue = load_feed_fractionation()
        kinetics = adm1_params.kinetics.model_copy(
            update={"K_I_nh3": adm1_params.kinetics.K_I_nh3 * multiplier}
        )
        shifted = compile_extended(
            adm1_params.model_copy(update={"kinetics": kinetics}),
            declared_geometry(plant),
            load_matrix(),
            load_solver_config(),
            load_extensions(),
            plant.truth_model.extensions,
        )
        out = simulate_extended(
            y0=y0,
            influent=constant_influent(catalogue, nominal_mass_rates(plant, catalogue)),
            model=shifted,
            t_span=(0.0, 120.0),
            t_eval=np.array([120.0]),
        )
        return float(out.derived["q_gas_stp_dry"][-1]), float(out.y[6, -1])  # gas, S_ac

    gas_0, ac_0 = response(at_burn_in.y[:, -1], 1.0)
    gas_1, ac_1 = response(at_burn_in.y[:, -1], 2.0)
    assert (gas_1 - gas_0) / gas_0 > 0.01, (gas_0, gas_1)  # measured +2.2 %
    assert (ac_0 - ac_1) / ac_0 > 0.10, (ac_0, ac_1)  # measured -19 %

    late_0, late_ac_0 = response(at_longer.y[:, -1], 1.0)
    late_1, late_ac_1 = response(at_longer.y[:, -1], 2.0)
    assert abs(late_1 - late_0) / late_0 < 0.001  # inert from the converged state
    assert abs(late_ac_1 - late_ac_0) / late_ac_0 < 0.001


def test_the_scenario_starts_from_the_burn_in_state(clean_run):
    """With no state fault the scenario's first state IS the burn-in's last."""
    np.testing.assert_array_equal(clean_run.truth.initial_state, clean_run.truth.burn_in_state)
    np.testing.assert_allclose(clean_run.truth.y[:, 0], clean_run.truth.initial_state, rtol=1e-10)


# ------------------------------------------------------------------ 3. tiers


def test_tiers_are_masks_on_identical_truth(tmp_path):
    """§6.4. Same digester, three windows: the channels must be bit-identical."""
    runs = generate_cells(
        _short("S1-01"), load_plant_config("C"), ["A", "B", "C"], runs_root=tmp_path
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

    runs = generate_cells(_short("S0-01"), load_plant_config("C"), ["A", "C"], runs_root=tmp_path)
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
    run = generate_run(scenario, "A", plant=load_plant_config("C"), runs_root=tmp_path)
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
    """The Level-8 note must not be identifiable by the existence of a notes file."""
    from sim.run.artifacts import read_operator_notes

    clean = generate_run(_short("S0-01"), "B", plant=load_plant_config("C"), runs_root=tmp_path)
    adversarial = generate_run(
        _short("S8-02"), "B", plant=load_plant_config("C"), runs_root=tmp_path
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
    run = generate_run(_short("S8-01"), "B", plant=load_plant_config("C"), runs_root=tmp_path)
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


def test_the_tier_is_not_part_of_the_seed_derivation(tmp_path):
    """Otherwise a tier would be a different digester, not a different window on one."""
    runs = generate_cells(
        _short("S0-01"), load_plant_config("C"), ["A", "B"], runs_root=tmp_path, write=False
    )
    assert runs[0].manifest.seeds == runs[1].manifest.seeds
    assert runs[0].truth.geometry == runs[1].truth.geometry


def test_a_scenario_without_a_seed_is_refused(tmp_path):
    """CLAUDE.md rule 4: no implicit seeds."""
    scenario = _short("S0-01").model_copy(update={"seed": None})
    with pytest.raises(ValueError, match="carries no seed"):
        generate_run(scenario, "A", plant=load_plant_config("C"), runs_root=tmp_path, write=False)


# ------------------------------------------------------------------ 6. provenance


def test_every_simulator_call_is_logged(clean_run):
    """CLAUDE.md rule 3, on the harness's own calls."""
    records = read_calls(clean_run.paths.root)
    names = [r.name for r in records]
    assert "sim.generate_influent" in names
    assert "sim.burn_in" in names
    assert any(n.startswith("sim.simulate_truth_segment") for n in names)
    assert "sim.channel_series" in names
    assert "sim.observe" in names
    assert [r.seq for r in records] == list(range(len(records)))
    for record in records:
        assert record.outcome == "ok"
        assert record.runtime_s >= 0.0
        assert len(record.args_hash) == 16


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
    written = RunManifest.read(clean_run.paths.manifest)
    assert written == clean_run.manifest
    public = written.public()
    payload = json.loads(clean_run.paths.manifest.read_text(encoding="utf-8"))
    assert payload["scenario_id"] == "S0-01"  # it is in the file...
    assert "scenario_id" not in public.model_dump()  # ...and not in the projection
    assert public.plant == "C" and public.tier == "B"
    assert public.configs.versions["observation_sensors"] >= 2
    assert public.git_sha


def test_the_index_maps_opaque_ids_back_to_cells(clean_run):
    index = clean_run.paths.root.parent / "index.jsonl"
    entries = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
    mine = [e for e in entries if e["run_id"] == clean_run.run_id]
    assert mine and mine[0]["scenario_id"] == "S0-01" and mine[0]["plant"] == "C"


def test_run_paths_are_declared_in_one_place(tmp_path):
    paths = RunPaths.for_run("run_abc", tmp_path).create()
    assert paths.truth.is_dir() and paths.observations.is_dir()
    assert paths.truth_states.parent == paths.truth
    assert paths.sensors.parent == paths.observations
