"""The fault-injection API (sim/faults, configs/faults/faults.yaml).

There is a test **per fault type** of the closed ladder, and each one asks the same two
questions: does the fault change what proposal §6.3 says it should, and does it leave
everything else alone — bitwise wherever the comparison can be made bitwise (the same
seed, the same truth, one thing different).

The layer tables are checked for totality first, so a fault type added to
:class:`scenarios.schema.FaultType` without a layer, a magnitude meaning and a
configuration block fails here rather than silently doing nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from scenarios.schema import Budget, CorrectConclusion, Fault, FaultType, Scenario, TruthLabel
from sim.adm1 import (
    STATE_NAMES,
    load_matrix,
    load_solver_config,
    simulate,
)
from sim.faults import (
    FAULT_LAYER,
    FAULT_MAGNITUDE,
    FaultLayer,
    compile_faults,
    load_faults_config,
    magnitude_table,
    mislabelled_fractionation,
)
from sim.influent import (
    generate_influent,
    load_feed_fractionation,
    load_generator_config,
    truth_parameters,
)
from sim.observe import (
    SensorEffect,
    load_observation_config,
    observe,
    reactor_ash,
    truth_channels,
)
from sim.plants import declared_geometry, load_all_plants
from sim.plants.mixing import compile_two_zone, initial_state, simulate_two_zone

HORIZON_D = 60
ONSET_D = 30.0


@pytest.fixture(scope="module")
def config():
    return load_faults_config()


@pytest.fixture(scope="module")
def plants():
    return load_all_plants()


@pytest.fixture(scope="module")
def catalogue():
    return load_feed_fractionation()


@pytest.fixture(scope="module")
def observation():
    return load_observation_config()


def scenario_with(
    fault_type: FaultType,
    config,
    *,
    plant: str = "B",
    magnitude: float | None = None,
    onset_day: float = ONSET_D,
    duration_days: float | None = None,
) -> Scenario:
    """A minimal scenario carrying one fault at its configured default magnitude."""
    bounds = config.bounds_for(fault_type)
    labels: dict[FaultLayer, tuple[TruthLabel, ...]] = {
        FaultLayer.SENSOR: (TruthLabel.SENSOR,),
        FaultLayer.INFLUENT: (TruthLabel.INFLUENT,),
        FaultLayer.STATE: (TruthLabel.STATE,),
        FaultLayer.PARAMETER: (TruthLabel.PARAMETER,),
        FaultLayer.STRUCTURAL: (TruthLabel.STRUCTURAL,),
        FaultLayer.WORKFLOW: (TruthLabel.SENSOR,),
    }
    layer = FAULT_LAYER[fault_type]
    return Scenario(
        id="S9-01",
        plant=plant,
        tier="C",
        level=5 if layer is FaultLayer.PARAMETER else 3,
        duration_days=float(HORIZON_D),
        truth_label=labels[layer],
        faults=(
            Fault(
                type=fault_type,
                onset_day=onset_day,
                magnitude=bounds.default if magnitude is None else magnitude,
                duration_days=duration_days,
            ),
        ),
        correct_conclusion=CorrectConclusion(kinetic_update_allowed=layer is FaultLayer.PARAMETER),
        budget=Budget(simulator_evals=1000, wall_clock_min=30.0, assay_units=2),
    )


def compile_one(fault_type: FaultType, config, plants, catalogue, params, **kwargs: object):
    plant_id = kwargs.pop("plant", "B")
    scenario = scenario_with(fault_type, config, plant=plant_id, **kwargs)
    return compile_faults(scenario, config, plants[plant_id], catalogue, params, n_days=HORIZON_D)


# ------------------------------------------------------------------ the layer tables


def test_every_fault_type_has_a_layer_a_magnitude_meaning_and_a_config_block(config):
    assert set(FAULT_LAYER) == set(FaultType)
    assert set(FAULT_MAGNITUDE) == set(FaultType)
    for fault_type in FaultType:
        block = getattr(config, FAULT_LAYER[fault_type].value)
        assert fault_type in block, fault_type
        spec = FAULT_MAGNITUDE[fault_type]
        assert spec.unit and len(spec.meaning) > 30, fault_type
    rows = magnitude_table()
    assert len(rows) == len(FaultType)
    assert {r[1] for r in rows} == {layer.value for layer in FaultLayer}


def test_the_layers_match_the_ladder_of_6_3():
    """Each §6.3 row is applied where its ground-truth label says the error entered."""
    assert FAULT_LAYER[FaultType.GAS_METER_SCALE] is FaultLayer.SENSOR
    assert FAULT_LAYER[FaultType.FEED_MISLABELLED] is FaultLayer.INFLUENT
    assert FAULT_LAYER[FaultType.BIOMASS_MISINITIALISED] is FaultLayer.STATE
    assert FAULT_LAYER[FaultType.AMMONIA_INHIBITION_SHIFT] is FaultLayer.PARAMETER
    assert FAULT_LAYER[FaultType.OMITTED_SAO] is FaultLayer.STRUCTURAL
    assert FAULT_LAYER[FaultType.TOOL_FAILURE] is FaultLayer.WORKFLOW
    # informative missingness is labelled state/sensor in the ladder but is applied at the
    # sensor layer, because what it changes is the instruments' failure hazard
    assert FAULT_LAYER[FaultType.INFORMATIVE_MISSINGNESS] is FaultLayer.SENSOR


@pytest.mark.parametrize("fault_type", list(FaultType))
def test_a_magnitude_outside_the_configured_bounds_is_rejected(
    fault_type, config, plants, catalogue, adm1_params
):
    bounds = config.bounds_for(fault_type)
    if bounds is None:  # the two omission faults use no magnitude
        assert fault_type in (FaultType.OMITTED_SAO, FaultType.OMITTED_PRECIPITATION)
        return
    plant = "A" if fault_type is FaultType.OMITTED_SAO else "B"
    over = bounds.maximum + abs(bounds.maximum) + 1.0
    with pytest.raises(ValueError, match="outside the configured bounds"):
        compile_one(fault_type, config, plants, catalogue, adm1_params, plant=plant, magnitude=over)


def test_no_faults_compiles_to_no_variant(config, plants, catalogue, adm1_params):
    scenario = scenario_with(FaultType.GAS_METER_SCALE, config).model_copy(
        update={"faults": (), "truth_label": (TruthLabel.NONE,), "level": 1}
    )
    compiled = compile_faults(
        scenario, config, plants["B"], catalogue, adm1_params, n_days=HORIZON_D
    )
    assert not compiled.sensor and not compiled.influent and not compiled.workflow
    assert not compiled.state.multipliers and compiled.parameters.constant
    assert compiled.structural.mixing.ideal and not compiled.structural.omitted
    assert compiled.structural.fitted_extensions == compiled.structural.truth_extensions
    assert not compiled.touches_truth


# ------------------------------------------------------------------- sensor faults


@pytest.fixture(scope="module")
def truth(plants, catalogue, adm1_params, rj2006_state):
    """Plant B, 60 d, as truth channels plus the generated influent run."""
    run = generate_influent(
        plants["B"], catalogue, load_generator_config(), adm1_params, seed=4, n_days=HORIZON_D
    )
    params = truth_parameters(
        adm1_params, catalogue, run.truth.mean_recipe_kg_d, run.truth.fractionations.fractionations
    )
    geometry = declared_geometry(plants["B"])
    result = simulate(
        y0=rj2006_state,
        influent=run.truth.influent,
        params=params,
        plant=geometry,
        matrix=load_matrix(),
        solver=load_solver_config(),
        t_span=(0.0, float(HORIZON_D)),
        t_eval=np.arange(0.0, HORIZON_D + 1.0),
    )
    assert result.success
    observation = load_observation_config()
    ash = reactor_ash(catalogue, run.truth, geometry.V_liq, result.t)
    return truth_channels(result, params, geometry, observation.solids, ash), run


def _observe(truth_channels_, observation, faults=()):
    return observe(truth_channels_, observation, "B", "C", seed=31, faults=faults)


def test_gas_meter_scale_scales_only_the_gas_meter_only_after_onset(
    truth, config, plants, catalogue, adm1_params, observation
):
    channels, _ = truth
    compiled = compile_one(FaultType.GAS_METER_SCALE, config, plants, catalogue, adm1_params)
    (fault,) = compiled.sensor
    assert fault.channel == "biogas_volume" and fault.effect is SensorEffect.SCALE
    base = _observe(channels, observation)
    faulted = _observe(channels, observation, compiled.sensor)
    a, b = base.observed.sensors["biogas_volume"], faulted.observed.sensors["biogas_volume"]
    before = a.t < ONSET_D
    assert np.array_equal(a.value[before], b.value[before], equal_nan=True)
    assert np.nanmedian(b.value[~before] / a.value[~before]) == pytest.approx(1.08, rel=1e-6)
    _assert_other_channels_identical(base, faulted, {"biogas_volume"})
    assert not compiled.touches_truth  # a sensor fault never reaches the truth


def test_ph_electrode_drift_drifts_then_recalibrates(
    truth, config, plants, catalogue, adm1_params, observation
):
    channels, _ = truth
    compiled = compile_one(
        FaultType.PH_ELECTRODE_DRIFT, config, plants, catalogue, adm1_params, duration_days=20.0
    )
    (fault,) = compiled.sensor
    assert fault.channel == "ph" and fault.magnitude < 0.0
    base = _observe(channels, observation)
    faulted = _observe(channels, observation, compiled.sensor)
    a, b = base.observed.sensors["ph"], faulted.observed.sensors["ph"]
    offset = b.value - a.value
    during = (a.t >= ONSET_D) & (a.t < ONSET_D + 20.0)
    # a slow negative drift that grows linearly while the episode lasts
    assert np.all(offset[during] <= 1e-9)
    late = a.t == ONSET_D + 19.0
    # the electrode records to 0.01 pH, so the offset is the drift rounded to that
    assert offset[late][0] == pytest.approx(fault.magnitude * 19.0, abs=0.01)
    # and a step recalibration at the end: the reading is the unfaulted one again
    after = a.t >= ONSET_D + 20.0
    assert np.array_equal(a.value[after], b.value[after], equal_nan=True)
    assert np.array_equal(a.value[a.t < ONSET_D], b.value[a.t < ONSET_D], equal_nan=True)
    _assert_other_channels_identical(base, faulted, {"ph"})


def test_ch4_analyser_flatline_holds_its_last_reading_for_the_declared_days(
    truth, config, plants, catalogue, adm1_params, observation
):
    channels, _ = truth
    compiled = compile_one(FaultType.CH4_ANALYSER_FLATLINE, config, plants, catalogue, adm1_params)
    (fault,) = compiled.sensor
    assert fault.duration_d == 6.0  # §6.3: "constant value for 6 days"
    base = _observe(channels, observation)
    faulted = _observe(channels, observation, compiled.sensor)
    a, b = base.observed.sensors["ch4_fraction"], faulted.observed.sensors["ch4_fraction"]
    during = (a.t >= ONSET_D) & (a.t < ONSET_D + 6.0)
    held = b.value[during]
    assert np.nanmax(held) == np.nanmin(held) and np.nanstd(a.value[during]) > 0.0
    outside = ~during
    assert np.array_equal(a.value[outside], b.value[outside], equal_nan=True)
    _assert_other_channels_identical(base, faulted, {"ch4_fraction"})


def test_sensor_noise_widens_every_channel_and_touches_no_truth(
    truth, config, plants, catalogue, adm1_params, observation
):
    channels, _ = truth
    compiled = compile_one(FaultType.SENSOR_NOISE, config, plants, catalogue, adm1_params)
    (fault,) = compiled.sensor
    assert fault.channel is None and fault.effect is SensorEffect.NOISE
    base = _observe(channels, observation)
    faulted = _observe(channels, observation, compiled.sensor)
    quiet = base.observed.sensors["biogas_volume"]
    loud = faulted.observed.sensors["biogas_volume"]
    truth_at = channels.at("biogas_volume", quiet.t)
    after = quiet.t >= ONSET_D
    assert np.nanstd((loud.value / truth_at)[after]) > 1.5 * np.nanstd(
        (quiet.value / truth_at)[after]
    )
    # before the onset the instrument is the declared one, bit for bit
    assert np.array_equal(quiet.value[~after], loud.value[~after], equal_nan=True)
    assert not compiled.touches_truth
    # the fault is applied before the run: the truth series are the same object
    assert channels.values["biogas_volume"] is channels.values["biogas_volume"]


def test_random_gaps_lose_samples_at_random_on_every_channel(
    truth, config, plants, catalogue, adm1_params, observation
):
    channels, _ = truth
    compiled = compile_one(FaultType.RANDOM_GAPS, config, plants, catalogue, adm1_params)
    base = _observe(channels, observation)
    faulted = _observe(channels, observation, compiled.sensor)
    for name, series in faulted.observed.sensors.items():
        after = series.t >= ONSET_D
        added = series.missing[after].mean() - base.observed.sensors[name].missing[after].mean()
        assert added > 0.03, name  # the declared 0.10, minus what was already missing
        before = series.t < ONSET_D
        assert np.array_equal(
            series.value[before], base.observed.sensors[name].value[before], equal_nan=True
        ), name


def test_informative_missingness_strengthens_the_coupling_and_nothing_else(
    truth, config, plants, catalogue, adm1_params, observation
):
    channels, _ = truth
    compiled = compile_one(
        FaultType.INFORMATIVE_MISSINGNESS, config, plants, catalogue, adm1_params, onset_day=0.0
    )
    base = _observe(channels, observation)
    faulted = _observe(channels, observation, compiled.sensor)
    stress = np.interp(base.observed.sensors["ph"].t, base.truth.stress_t, base.truth.stress)
    p_base = base.truth.missing_probability["ph"]
    p_faulted = faulted.truth.missing_probability["ph"]
    assert np.all(p_faulted >= p_base - 1e-12)
    assert p_faulted[stress > 0.5].mean() > 3.0 * p_base[stress > 0.5].mean()
    # a channel that declares no sensitivity is untouched, stress or no stress
    assert np.array_equal(
        base.truth.missing_probability["reactor_temperature"],
        faulted.truth.missing_probability["reactor_temperature"],
    )


def _assert_other_channels_identical(base, faulted, changed: set[str]) -> None:
    for name, series in base.observed.sensors.items():
        if name in changed:
            continue
        assert np.array_equal(series.value, faulted.observed.sensors[name].value, equal_nan=True), (
            name
        )
    base_assays = {
        (a.channel, a.sample_day, a.value) for a in base.observed.assays if a.channel not in changed
    }
    faulted_assays = {
        (a.channel, a.sample_day, a.value)
        for a in faulted.observed.assays
        if a.channel not in changed
    }
    assert base_assays == faulted_assays


# ----------------------------------------------------------------- influent faults


def _generate(plants, catalogue, adm1_params, modifiers=None):
    return generate_influent(
        plants["B"],
        catalogue,
        load_generator_config(),
        adm1_params,
        seed=4,
        n_days=HORIZON_D,
        modifiers=modifiers,
    )


def test_the_modifier_hook_is_inert_when_no_fault_is_compiled(plants, catalogue, adm1_params):
    """A run with an empty modifier mapping is bit for bit the run without one."""
    a = _generate(plants, catalogue, adm1_params)
    b = _generate(plants, catalogue, adm1_params, modifiers={})
    for feed_id, feed in a.truth.feeds.items():
        assert np.array_equal(feed.delivered_kg, b.truth.feeds[feed_id].delivered_kg)
        assert np.array_equal(feed.ts, b.truth.feeds[feed_id].ts)
    assert np.array_equal(a.truth.influent.concentrations, b.truth.influent.concentrations)
    assert a.observed.assays == b.observed.assays


def test_moisture_drift_wets_one_feed_from_its_onset_and_nothing_else(
    config, plants, catalogue, adm1_params
):
    onset = 10.0  # the ramp is 30 d and has to finish inside the 60-day horizon
    compiled = compile_one(
        FaultType.MOISTURE_DRIFT, config, plants, catalogue, adm1_params, onset_day=onset
    )
    (feed_id,) = compiled.influent
    base = _generate(plants, catalogue, adm1_params)
    wet = _generate(plants, catalogue, adm1_params, modifiers=compiled.influent)
    day = np.arange(HORIZON_D)
    before = day < onset
    ts_base = base.truth.feeds[feed_id].ts
    ts_wet = wet.truth.feeds[feed_id].ts
    assert np.array_equal(ts_base[before], ts_wet[before])
    # the drift ramps over 30 d and then holds the full 15 % drop
    assert ts_wet[-1] == pytest.approx(ts_base[-1] * 0.85, rel=1e-9)
    half = int(onset) + 15
    assert ts_wet[half] == pytest.approx(ts_base[half] * 0.925, rel=1e-9)
    # VS per delivery falls with it (§6.3: "moisture drift lowers VS per delivery")...
    assert (
        wet.truth.influent.concentrations[-1].sum() < base.truth.influent.concentrations[-1].sum()
    )
    # ...and the delivered masses and every other feed are untouched, bit for bit
    assert np.array_equal(
        base.truth.feeds[feed_id].delivered_kg, wet.truth.feeds[feed_id].delivered_kg
    )
    for other in set(base.truth.feeds) - {feed_id}:
        assert np.array_equal(base.truth.feeds[other].ts, wet.truth.feeds[other].ts)
        assert np.array_equal(
            base.truth.feeds[other].delivered_kg, wet.truth.feeds[other].delivered_kg
        )


def test_unrecorded_delivery_adds_unlogged_mass_that_the_log_never_shows(
    config, plants, catalogue, adm1_params
):
    compiled = compile_one(FaultType.UNRECORDED_DELIVERY, config, plants, catalogue, adm1_params)
    (feed_id,) = compiled.influent
    base = _generate(plants, catalogue, adm1_params)
    faulted = _generate(plants, catalogue, adm1_params, modifiers=compiled.influent)
    extra = set(faulted.truth.feeds[feed_id].unrecorded_days) - set(
        base.truth.feeds[feed_id].unrecorded_days
    )
    assert len(extra) >= 3 and min(extra) >= ONSET_D  # 30 d at 0.2/d, binomial mean 6
    # the truth carries more mass; the operator's log is unchanged, which is the point
    assert (
        faulted.truth.feeds[feed_id].delivered_kg.sum()
        > base.truth.feeds[feed_id].delivered_kg.sum()
    )
    assert np.array_equal(
        base.observed.feed_log_kg_wet_d[feed_id], faulted.observed.feed_log_kg_wet_d[feed_id]
    )
    for other in set(base.truth.feeds) - {feed_id}:
        assert np.array_equal(
            base.truth.feeds[other].delivered_kg, faulted.truth.feeds[other].delivered_kg
        )


def test_feed_mislabelled_shifts_the_true_fractionation_not_the_catalogue(
    config, plants, catalogue, adm1_params
):
    base = _generate(plants, catalogue, adm1_params)
    compiled = compile_faults(
        scenario_with(FaultType.FEED_MISLABELLED, config),
        config,
        plants["B"],
        catalogue,
        adm1_params,
        n_days=HORIZON_D,
        true_fractionations=base.truth.fractionations.fractionations,
    )
    (feed_id,) = compiled.influent
    faulted = _generate(plants, catalogue, adm1_params, modifiers=compiled.influent)
    drawn = base.truth.fractionations[feed_id]
    mislabelled = faulted.truth.fractionations[feed_id]
    assert mislabelled.f_xi == pytest.approx(drawn.f_xi + 0.15, rel=1e-9)
    assert mislabelled.f_ch < drawn.f_ch and mislabelled.f_pr < drawn.f_pr
    assert sum(mislabelled.as_tuple()) == pytest.approx(1.0, abs=1e-12)
    # the catalogue an operator reads is untouched
    assert (
        catalogue.feeds[feed_id].fractionation
        == load_feed_fractionation().feeds[feed_id].fractionation
    )
    for other in set(base.truth.fractionations.fractionations) - {feed_id}:
        assert base.truth.fractionations[other] == faulted.truth.fractionations[other]
    # ... and the deliveries are the same batches, so only the composition moved
    assert np.array_equal(
        base.truth.feeds[feed_id].delivered_kg, faulted.truth.feeds[feed_id].delivered_kg
    )


def test_mislabelling_cannot_move_more_cod_than_the_classes_carry(catalogue):
    fractionation = catalogue.feeds["fog"].fractionation
    with pytest.raises(ValueError, match="cannot move"):
        mislabelled_fractionation(fractionation, 0.99, ("f_ch", "f_pr"), "f_xi")
    with pytest.raises(ValueError, match="not COD fractions"):
        mislabelled_fractionation(fractionation, 0.1, ("f_nonsense",), "f_xi")


# -------------------------------------------------------------------- state fault


def test_biomass_misinitialised_halves_the_biomass_and_leaves_the_rest_bitwise(
    config, plants, catalogue, adm1_params, rj2006_state
):
    compiled = compile_one(FaultType.BIOMASS_MISINITIALISED, config, plants, catalogue, adm1_params)
    y0 = compiled.state.apply(rj2006_state, STATE_NAMES)
    biomass = set(config.state[FaultType.BIOMASS_MISINITIALISED].states)
    assert biomass == set(compiled.state.multipliers)
    for i, name in enumerate(STATE_NAMES):
        if name in biomass:
            assert y0[i] == rj2006_state[i] * 0.5
        else:
            assert y0[i] == rj2006_state[i]  # bitwise
    assert not np.shares_memory(y0, rj2006_state)
    with pytest.raises(ValueError, match="unknown states"):
        compiled.state.apply(rj2006_state, tuple(n + "x" for n in STATE_NAMES))


# --------------------------------------------------------------- parameter faults


@pytest.mark.parametrize(
    ("fault_type", "group", "names"),
    [
        (FaultType.AMMONIA_INHIBITION_SHIFT, "kinetics", ("K_I_nh3",)),
        (FaultType.HYDROLYSIS_REGIME_CHANGE, "kinetics", ("k_hyd_ch", "k_hyd_pr", "k_hyd_li")),
    ],
)
def test_a_parameter_fault_moves_its_own_parameters_only_and_within_bounds(
    fault_type, group, names, config, plants, catalogue, adm1_params
):
    onset = 10.0  # the acclimation ramp has to finish inside the horizon
    compiled = compile_one(fault_type, config, plants, catalogue, adm1_params, onset_day=onset)
    spec = config.parameter[fault_type]
    schedule = compiled.parameters
    assert set(names) == set(spec.parameters)

    before = schedule.at(onset - 1.0)
    assert before is adm1_params  # nothing is copied, let alone changed, before the onset
    after = schedule.at(float(HORIZON_D) - 1.0)
    for name in names:
        base_value = getattr(getattr(adm1_params, group), name)
        assert getattr(getattr(after, group), name) == pytest.approx(
            base_value * spec.magnitude.default, rel=1e-12
        )
    # every other parameter is bit for bit the base set, and the base object is untouched
    changed = {(group, n) for n in names}
    for block in ("stoichiometry", "kinetics", "physchem"):
        for field, value in getattr(adm1_params, block).model_dump().items():
            if (block, field) in changed:
                continue
            assert getattr(getattr(after, block), field) == value, (block, field)
    assert load_faults_config() == config  # the config object is not mutated either

    if spec.transition_d > 0.0:  # acclimation ramps, a particle-size change steps
        middle = schedule.at(onset + spec.transition_d / 2.0)
        value = getattr(getattr(middle, group), names[0])
        base_value = getattr(getattr(adm1_params, group), names[0])
        assert base_value < value < base_value * spec.magnitude.default
        assert onset + 1.0 in schedule.breakpoints((0.0, float(HORIZON_D)))
    else:
        assert schedule.at(onset + 0.5) == schedule.at(float(HORIZON_D) - 1.0)
        assert schedule.breakpoints((0.0, float(HORIZON_D))) == (0.0, onset)


def test_a_parameter_fault_ends_with_its_episode(config, plants, catalogue, adm1_params):
    compiled = compile_one(
        FaultType.HYDROLYSIS_REGIME_CHANGE,
        config,
        plants,
        catalogue,
        adm1_params,
        duration_days=10.0,
    )
    assert compiled.parameters.at(ONSET_D + 5.0) is not adm1_params
    assert compiled.parameters.at(ONSET_D + 10.0) is adm1_params
    assert ONSET_D + 10.0 in compiled.parameters.breakpoints((0.0, float(HORIZON_D)))


# -------------------------------------------------------------- structural faults


@pytest.mark.parametrize(
    ("fault_type", "extension", "plant"),
    [(FaultType.OMITTED_SAO, "sao", "A"), (FaultType.OMITTED_PRECIPITATION, "precipitation", "B")],
)
def test_an_omission_denies_the_fitted_model_an_extension_the_truth_keeps(
    fault_type, extension, plant, config, plants, catalogue, adm1_params
):
    compiled = compile_one(
        fault_type, config, plants, catalogue, adm1_params, plant=plant, magnitude=1.0
    )
    declared = tuple(plants[plant].truth_model.extensions)
    assert compiled.structural.truth_extensions == declared  # the truth is untouched
    assert compiled.structural.omitted == (extension,)
    assert set(compiled.structural.fitted_extensions) == set(declared) - {extension}
    assert compiled.structural.mixing.ideal
    assert not compiled.sensor and not compiled.influent and compiled.parameters.constant


def test_omitting_an_extension_a_plant_does_not_run_is_an_error(
    config, plants, catalogue, adm1_params
):
    plain = plants["B"].model_copy(
        update={"truth_model": plants["B"].truth_model.model_copy(update={"extensions": ()})}
    )
    scenario = scenario_with(FaultType.OMITTED_SAO, config, magnitude=1.0)
    with pytest.raises(ValueError, match="does not run"):
        compile_faults(scenario, config, plain, catalogue, adm1_params, n_days=HORIZON_D)


def test_imperfect_mixing_is_the_two_zone_truth_variant(
    config, plants, catalogue, adm1_params, rj2006_state
):
    compiled = compile_one(FaultType.IMPERFECT_MIXING, config, plants, catalogue, adm1_params)
    spec = config.structural[FaultType.IMPERFECT_MIXING]
    mixing = compiled.structural.mixing
    assert mixing.stagnant_fraction == spec.magnitude.default
    assert mixing.bypass_fraction == spec.bypass_fraction
    assert mixing.exchange_rate == spec.exchange_rate
    assert not mixing.ideal
    # the fitted model keeps every extension: this fault is in the reactor, not the model
    assert compiled.structural.fitted_extensions == compiled.structural.truth_extensions

    # and it is a real change to the truth: 20 d of the same feed through the two-zone
    # reactor differs from the CSTR, in a load-dependent way
    from sim.adm1 import load_extensions
    from sim.influent import constant_influent, nominal_mass_rates

    geometry = declared_geometry(plants["B"])
    influent = constant_influent(catalogue, nominal_mass_rates(plants["B"], catalogue))
    matrix, solver, extensions = load_matrix(), load_solver_config(), load_extensions()
    outputs = {}
    for label, structure in (("cstr", type(mixing).cstr()), ("rtd", mixing)):
        model = compile_two_zone(adm1_params, geometry, matrix, solver, extensions, (), structure)
        result = simulate_two_zone(
            y0=initial_state(model, rj2006_state),
            influent=influent,
            model=model,
            t_span=(0.0, 20.0),
            t_eval=np.array([20.0]),
        )
        assert result.success
        outputs[label] = result.final()
    assert outputs["cstr"]["q_gas"] != pytest.approx(outputs["rtd"]["q_gas"], rel=1e-6)


# ---------------------------------------------------------------- workflow faults


@pytest.mark.parametrize("fault_type", [FaultType.TOOL_FAILURE, FaultType.ADVERSARIAL_LOG_NOTE])
def test_a_workflow_fault_is_carried_and_never_applied(
    fault_type, config, plants, catalogue, adm1_params
):
    compiled = compile_one(fault_type, config, plants, catalogue, adm1_params)
    (carried,) = compiled.workflow
    assert carried.type is fault_type and carried.onset_d == ONSET_D
    if fault_type is FaultType.TOOL_FAILURE:
        assert carried.target == "bayes_mcmc"  # §6.3 names the tool
    else:
        assert carried.note and "Operator note" in carried.note
    # nothing in the simulator moves
    assert not compiled.sensor and not compiled.influent and not compiled.state.multipliers
    assert compiled.parameters.constant and compiled.structural.mixing.ideal
    assert not compiled.structural.omitted and not compiled.touches_truth
