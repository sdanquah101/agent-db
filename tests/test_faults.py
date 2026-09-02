"""Fault injection (sim/faults) and the Level-6 imperfect-mixing truth variant.

What is tested and why it cannot pass vacuously:

* every :class:`~scenarios.schema.FaultType` has declared magnitude semantics with a unit
  and a layer, the benchmark-card table covers the closed set, and out-of-range
  magnitudes are refused;
* a scenario routes to the right layers — the Appendix-B gas-meter example touches the
  observation layer and nothing else;
* each layer's applier does what the semantics say: the influent faults change the truth
  but not the log (unrecorded), the log's basis but not the catalogue (mislabelled), and
  the solids trend (moisture); the parameter fault splits the run at its onset and moves
  only the named constants; the state fault scales biomass only; the structural fault
  removes an extension from the fitted model while the truth keeps it;
* **a faulted run differs from its clean twin only by the fault** — the influent
  generator's and the observation model's own draws are untouched, because the fault
  layer has its own stream;
* the two-zone reactor wired in as the ``imperfect_mixing`` truth variant reduces to the
  ideal CSTR at magnitude 0 and otherwise produces a *load-dependent* residual against
  the CSTR, which is the signature the Level-6 row asks for.
"""

from __future__ import annotations

import numpy as np
import pytest

from scenarios.schema import (
    Budget,
    CorrectConclusion,
    Fault,
    FaultType,
    Scenario,
    TruthLabel,
    load_scenario,
)
from sim.adm1 import (
    compile_extended,
    extended_state,
    load_extensions,
    load_matrix,
    load_parameters,
    load_solver_config,
    simulate_extended,
)
from sim.faults import (
    FAULT_SEMANTICS,
    FaultInjectionConfig,
    InfluentFaults,
    MislabelledFeed,
    MoistureRamp,
    ObservationFaults,
    UnrecordedDelivery,
    apply_state_faults,
    benchmark_card_rows,
    build_plan,
    declared_faults,
    fitted_extensions,
    load_fault_config,
    parameter_segments,
    semantics_for,
    truth_mixing,
)
from sim.influent import (
    generate_influent,
    load_feed_fractionation,
    load_generator_config,
)
from sim.observation import (
    DriftModel,
    NoiseModel,
    channel_series,
    channels_from_two_zone,
    load_observation_config,
    observe,
)
from sim.plants import declared_geometry, load_all_plants
from sim.plants.mixing import compile_two_zone, initial_state, simulate_two_zone
from tests.conftest import REPO_ROOT
from tests.test_observation import _flat_channels

BUDGET = Budget(simulator_evals=1000, wall_clock_min=10.0, assay_units=0)
PLANT_B_FEEDS = ("primary_sludge", "thickened_was", "high_strength_waste", "fog")


def _scenario(
    *faults: Fault,
    level: int = 2,
    labels: tuple[TruthLabel, ...] = (TruthLabel.SENSOR,),
    **kwargs: object,
) -> Scenario:
    """A minimal scenario carrying the given faults."""
    defaults = {
        "id": "S9-01",
        "plant": "B",
        "tier": "B",
        "level": level,
        "duration_days": 200.0,
        "truth_label": labels,
        "faults": faults,
        "correct_conclusion": CorrectConclusion(kinetic_update_allowed=False),
        "budget": BUDGET,
        "seed": 4,
    }
    return Scenario.model_validate(defaults | kwargs)


# ------------------------------------------------------------------ semantics


def test_every_fault_type_has_semantics_with_a_unit_and_a_layer():
    assert set(FAULT_SEMANTICS) == set(FaultType)
    layers = set()
    for fault, spec in FAULT_SEMANTICS.items():
        assert spec.fault is fault
        assert spec.magnitude_unit, fault
        assert spec.description.endswith("."), fault
        layers.add(spec.layer)
    assert layers == {"influent", "parameter", "state", "structure", "observation", "workflow"}
    rows = benchmark_card_rows()
    assert len(rows) == len(FaultType)
    assert all(len(r) == 4 for r in rows)


def test_the_benchmark_card_carries_the_generated_fault_table():
    """The module claims the card cannot drift from the code; this is what makes that true.

    `sim/faults/schema.py` says "benchmark_card_rows renders the table, so the card and the
    code cannot drift apart". Rendering it is not enough — nothing forced the rendered rows
    into `docs/benchmark_card.md`, so the claim held only by the author's diligence. The
    card carries the table between generated markers and this compares the two verbatim.
    """
    card = (REPO_ROOT / "docs" / "benchmark_card.md").read_text(encoding="utf-8")
    start = card.index("<!-- BEGIN GENERATED: fault semantics -->")
    end = card.index("<!-- END GENERATED: fault semantics -->")
    block = card[start:end].splitlines()[3:]  # marker, header, separator
    expected = [
        f"| `{fault}` | {layer} | {unit} | {desc} |"
        for fault, layer, unit, desc in benchmark_card_rows()
    ]
    assert block == expected, (
        "docs/benchmark_card.md is out of date with sim.faults.benchmark_card_rows(); "
        "regenerate the block between the GENERATED markers"
    )


def test_magnitudes_outside_the_declared_range_are_refused():
    spec = semantics_for(FaultType.GAS_METER_SCALE)
    spec.validate_magnitude(1.08)
    with pytest.raises(ValueError, match="above the maximum"):
        spec.validate_magnitude(5.0)
    with pytest.raises(ValueError, match="below the minimum"):
        semantics_for(FaultType.IMPERFECT_MIXING).validate_magnitude(-0.1)
    with pytest.raises(ValueError, match="above the maximum"):
        build_plan(
            _scenario(Fault(type=FaultType.GAS_METER_SCALE, onset_day=10.0, magnitude=9.0)),
            PLANT_B_FEEDS,
        )


def test_the_appendix_b_scenario_routes_to_the_observation_layer_only():
    scenario = load_scenario("scenarios/S2-03.yaml")
    plan = build_plan(scenario, PLANT_B_FEEDS)
    assert plan.layers == ("observation",)
    assert plan.observation.scales == {"gas_flow": (60.0, 1.08)}
    assert not plan.influent and not plan.parameter and not plan.state and not plan.structure
    assert declared_faults(scenario) == {"observation": ["gas_meter_scale"]}


def test_faults_route_to_their_layers():
    plan = build_plan(
        _scenario(
            Fault(type=FaultType.UNRECORDED_DELIVERY, onset_day=50.0, magnitude=3.0),
            Fault(type=FaultType.AMMONIA_INHIBITION_SHIFT, onset_day=80.0, magnitude=0.5),
            Fault(type=FaultType.BIOMASS_MISINITIALISED, onset_day=0.0, magnitude=0.2),
            Fault(type=FaultType.OMITTED_SAO, onset_day=0.0, magnitude=0.0),
            Fault(type=FaultType.TOOL_FAILURE, onset_day=0.0, magnitude=0.3),
            level=7,
            labels=(TruthLabel.INFLUENT, TruthLabel.PARAMETER, TruthLabel.STATE),
        ),
        PLANT_B_FEEDS,
    )
    assert plan.layers == ("influent", "parameter", "state", "structure", "workflow")
    assert plan.influent.unrecorded == (UnrecordedDelivery("fog", 50, 3.0),)  # last feed
    assert plan.parameter.multipliers == ((80.0, "K_I_nh3", 0.5),)
    assert plan.state.biomass_multiplier == 0.2
    assert plan.structure.omit_from_fitted == ("sao",)
    assert plan.workflow.tool_failure == (("bayes_mcmc", 0.3),)
    assert plan.influent.seed == 5  # scenario seed + 1: its own stream


def test_the_influent_target_feed_can_be_named_explicitly():
    """The default is the last feed id, which depends on the caller's order; naming wins."""
    fault = Fault(type=FaultType.UNRECORDED_DELIVERY, onset_day=10.0, magnitude=2.0)
    scenario = _scenario(fault, level=3, labels=(TruthLabel.INFLUENT,))
    assert build_plan(scenario, PLANT_B_FEEDS).influent.unrecorded[0].feed_id == "fog"
    assert (
        build_plan(scenario, sorted(PLANT_B_FEEDS)).influent.unrecorded[0].feed_id
        == "thickened_was"
    )  # order-dependent by default, which is why a caller may name the feed
    named = build_plan(scenario, PLANT_B_FEEDS, target_feed="high_strength_waste")
    assert named.influent.unrecorded[0].feed_id == "high_strength_waste"
    with pytest.raises(ValueError, match="not one of"):
        build_plan(scenario, PLANT_B_FEEDS, target_feed="cattle_slurry")


def test_the_mixing_shaping_constants_are_configuration_not_code():
    """The bypass ratio and exchange rate are DESIGN data the lead can review."""
    config = load_fault_config()
    assert config.imperfect_mixing.bypass_of_stagnant == pytest.approx(0.2)
    assert config.imperfect_mixing.exchange_per_d == pytest.approx(1.0)
    plan = build_plan(
        _scenario(
            Fault(type=FaultType.IMPERFECT_MIXING, onset_day=0.0, magnitude=0.25),
            level=6,
            labels=(TruthLabel.STRUCTURAL,),
        ),
        PLANT_B_FEEDS,
    )
    assert truth_mixing(plan).bypass_fraction == pytest.approx(0.05)
    # a different configuration changes the structure, so the file is load-bearing
    other = FaultInjectionConfig.model_validate(
        {"version": 1, "imperfect_mixing": {"bypass_of_stagnant": 0.4, "exchange_per_d": 2.0}}
    )
    structure = truth_mixing(plan, other)
    assert structure.bypass_fraction == pytest.approx(0.10)
    assert structure.exchange_rate == pytest.approx(2.0)


# ------------------------------------------------------------------ appliers


def test_parameter_fault_splits_the_run_and_moves_only_its_own_constants():
    params = load_parameters()
    plan = build_plan(
        _scenario(
            Fault(type=FaultType.HYDROLYSIS_REGIME_CHANGE, onset_day=60.0, magnitude=0.4),
            level=5,
            labels=(TruthLabel.PARAMETER,),
        ),
        PLANT_B_FEEDS,
    )
    segments = parameter_segments(plan, params)
    assert [(s, e) for s, e, _ in segments] == [(0.0, 60.0), (60.0, 200.0)]
    before, after = segments[0][2], segments[1][2]
    assert before.kinetics == params.kinetics
    for name in ("k_hyd_ch", "k_hyd_pr", "k_hyd_li"):
        assert getattr(after.kinetics, name) == pytest.approx(0.4 * getattr(params.kinetics, name))
    # nothing else moves
    unchanged = after.kinetics.model_dump()
    for name in ("k_hyd_ch", "k_hyd_pr", "k_hyd_li"):
        unchanged[name] = getattr(params.kinetics, name)
    assert unchanged == params.kinetics.model_dump()
    assert after.stoichiometry == params.stoichiometry and after.physchem == params.physchem
    # with no parameter fault there is exactly one segment
    plain = parameter_segments(build_plan(_scenario(), PLANT_B_FEEDS), params)
    assert len(plain) == 1 and plain[0][2].kinetics == params.kinetics


def test_state_fault_scales_biomass_only():
    plan = build_plan(
        _scenario(
            Fault(type=FaultType.BIOMASS_MISINITIALISED, onset_day=0.0, magnitude=0.1),
            level=4,
            labels=(TruthLabel.STATE,),
        ),
        PLANT_B_FEEDS,
    )
    names = ("S_su", "X_ch", "X_su", "X_ac", "X_h2", "X_I", "S_cat")
    y0 = np.arange(1.0, len(names) + 1.0)
    y = apply_state_faults(y0, plan, names)
    assert y[0] == y0[0] and y[1] == y0[1] and y[5] == y0[5] and y[6] == y0[6]
    for i in (2, 3, 4):
        assert y[i] == pytest.approx(0.1 * y0[i])
    np.testing.assert_array_equal(y0, np.arange(1.0, len(names) + 1.0))  # not modified in place


def test_structural_fault_removes_the_extension_from_the_fitted_model_only():
    """The truth keeps every extension its plant declares; the fitted model loses one."""
    plants = load_all_plants()
    truth_extensions = plants["A"].truth_model.extensions
    plan = build_plan(
        _scenario(
            Fault(type=FaultType.OMITTED_SAO, onset_day=0.0, magnitude=0.0),
            plant="A",
            level=6,
            labels=(TruthLabel.STRUCTURAL,),
        ),
        ("cattle_slurry", "grass_silage"),
    )
    fitted = fitted_extensions(plan, truth_extensions)
    assert "sao" in truth_extensions and "sao" not in fitted
    assert set(fitted) == set(truth_extensions) - {"sao"}
    # with no structural fault the fitted model gets the truth's list unchanged
    assert fitted_extensions(build_plan(_scenario(), PLANT_B_FEEDS), truth_extensions) == tuple(
        truth_extensions
    )


# ------------------------------------------------- the fault is the only difference


def test_influent_faults_change_the_truth_without_disturbing_the_baseline_draws():
    """A faulted run and its clean twin differ only by the fault.

    The generator's own draws are untouched because the fault layer has its own stream.
    """
    catalogue = load_feed_fractionation()
    generator = load_generator_config()
    plant = load_all_plants()["A"]
    params = load_parameters()
    kwargs = dict(seed=3, n_days=140)
    clean = generate_influent(plant, catalogue, generator, params, **kwargs)
    faults = InfluentFaults(
        mislabelled=(MislabelledFeed("grass_silage", 40.0, 80.0, 20.0),),
        unrecorded=(UnrecordedDelivery("grass_silage", 50, 3.0),),
        moisture=(MoistureRamp("cattle_slurry", 20.0, 120.0, -0.3),),
        seed=99,
    )
    dirty = generate_influent(plant, catalogue, generator, params, faults=faults, **kwargs)

    # the run's own draws are untouched
    assert dirty.truth.fractionations == clean.truth.fractionations
    np.testing.assert_array_equal(
        dirty.truth.feeds["grass_silage"].mislogged_days,
        clean.truth.feeds["grass_silage"].mislogged_days,
    )
    # unrecorded: truth up, log unchanged, and the day is recorded as unrecorded truth
    silage_truth = dirty.truth.feeds["grass_silage"].delivered_kg
    assert silage_truth[50] > clean.truth.feeds["grass_silage"].delivered_kg[50]
    assert dirty.observed.feed_log_kg_wet_d["grass_silage"][50] == pytest.approx(
        clean.observed.feed_log_kg_wet_d["grass_silage"][50]
    )
    assert 50 in dirty.truth.feeds["grass_silage"].unrecorded_days
    # moisture: wetter by the end of the window, unchanged before the onset
    slurry = dirty.truth.feeds["cattle_slurry"].ts
    base = clean.truth.feeds["cattle_slurry"].ts
    assert slurry[10] == pytest.approx(base[10])
    assert slurry[125] == pytest.approx(0.7 * base[125], rel=1e-9)
    # mislabelled, on its own: the influent differs inside the window and nowhere else
    only_mislabelled = InfluentFaults(
        mislabelled=(MislabelledFeed("grass_silage", 40.0, 80.0, 20.0),), seed=99
    )
    windowed = generate_influent(
        plant, catalogue, generator, params, faults=only_mislabelled, **kwargs
    )
    conc = windowed.truth.influent.concentrations
    base_conc = clean.truth.influent.concentrations
    assert not np.allclose(conc[60], base_conc[60])
    np.testing.assert_allclose(conc[5], base_conc[5])
    np.testing.assert_allclose(conc[100], base_conc[100])
    # COD moves between classes without the delivered mass changing
    np.testing.assert_allclose(
        windowed.truth.feeds["grass_silage"].delivered_kg,
        clean.truth.feeds["grass_silage"].delivered_kg,
    )
    # the catalogue itself is untouched
    assert load_feed_fractionation().feeds["grass_silage"] == catalogue.feeds["grass_silage"]


def test_observation_faults_change_the_record_without_disturbing_the_stream():
    """A sensor fault moves the reading only; noise, gaps and every other sensor are identical."""
    config = load_observation_config()
    channels = _flat_channels(n_days=200)
    clean = observe(channels, config, "B", seed=1)
    faults = ObservationFaults(
        scales={"gas_flow": (60.0, 1.08)},
        ramps={"ph": (30.0, -0.01)},
        flatlines={"ch4_fraction": (100.0, 106.0)},
    )
    dirty = observe(channels, config, "B", seed=1, faults=faults)

    gas_clean, gas_dirty = clean["gas_flow"], dirty["gas_flow"]
    np.testing.assert_array_equal(gas_clean.missing, gas_dirty.missing)
    ok = ~gas_clean.missing
    before = gas_clean.sample_t[ok] < 60.0
    np.testing.assert_allclose(gas_dirty.value[ok][before], gas_clean.value[ok][before])
    ratio = gas_dirty.value[ok][~before] / gas_clean.value[ok][~before]
    np.testing.assert_allclose(ratio, 1.08, rtol=1e-9)
    # the pH ramp accumulates from its onset and is zero before it
    ph_clean, ph_dirty = clean["ph"], dirty["ph"]
    delta = ph_dirty.value - ph_clean.value
    assert np.nanmax(np.abs(delta[:30])) < 1e-12
    assert delta[-1] < -0.1
    # the forced flatline holds the value over its window. A sample lost to missingness is
    # reported as missing rather than flatlined (the flags are masked by ~missing), so the
    # claim is that every sample in the window is one or the other, and every *reported*
    # one is flatlined and holds the same value.
    ch4 = dirty["ch4_fraction"]
    window = (ch4.sample_t >= 101.0) & (ch4.sample_t < 106.0)
    assert (ch4.flatlined | ch4.missing)[window].all()
    reported = window & ~ch4.missing
    assert reported.any()
    assert ch4.flatlined[reported].all()
    held = ch4.value[reported]
    np.testing.assert_allclose(held, held[0])
    # every other sensor is bit-identical
    for name in ("alkalinity", "cod_total", "tan", "temperature", "vfa_total"):
        np.testing.assert_array_equal(clean[name].value, dirty[name].value)
    with pytest.raises(ValueError, match="unknown sensors"):
        observe(
            channels, config, "B", seed=1, faults=ObservationFaults(scales={"nope": (1.0, 2.0)})
        )


def test_the_ph_drift_fault_is_a_sawtooth_not_a_ramp_to_infinity():
    """§6.3 Level 2 is "drift then step-recalibration" — a calibration fault ends at calibration.

    The injected ramp used to accumulate from its onset to the end of the horizon, so a
    -0.01 pH/d fault over 200 days ended 1.7 pH units low with no step anywhere and the
    scenario's whole signature was missing. It is now reset on the tier's cadence like the
    electrode's intrinsic drift, so the reading walks away and jumps back.
    """
    config = load_observation_config()
    channels = _flat_channels(n_days=200)
    quiet = config.sensors["ph"].model_copy(
        update={"noise": NoiseModel(cv=0.0, sd_abs=1e-12), "fouling": None, "drift": None}
    )
    # drift=None removes the random walk but also `recalibrated`; keep the flag by giving a
    # zero-scale walk, so the ramp still sees a recalibrated instrument
    quiet = quiet.model_copy(
        update={"drift": DriftModel(sd_per_sqrt_d=0.0, bound=0.5, recalibrated=True)}
    )
    policy = config.missingness.model_copy(update={"base_rate_by_tier": dict.fromkeys("ABC", 0.0)})
    cfg = config.model_copy(
        update={"sensors": {**config.sensors, "ph": quiet}, "missingness": policy}
    )
    interval = cfg.tiers["B"].recalibration_interval_d
    assert interval == 30.0
    faults = ObservationFaults(ramps={"ph": (0.0, -0.01)})
    offset = observe(channels, cfg, "B", seed=1, faults=faults)["ph"].value - 7.30

    # bounded by one cadence of ramp, not by the horizon
    assert np.abs(offset).max() == pytest.approx(0.01 * (interval - 1.0), abs=1e-6)
    assert np.abs(offset).max() < 0.35  # 200 d of un-reset ramp would be 2.0
    # and it really is a sawtooth: it walks down within a cycle and steps back at each
    # recalibration boundary
    for boundary in (30, 60, 90, 120, 150, 180):
        assert offset[boundary - 1] == pytest.approx(-0.01 * (interval - 1.0), abs=1e-6)
        assert offset[boundary] == pytest.approx(0.0, abs=1e-9)
    # a sensor that is NOT recalibrated keeps the un-reset ramp
    never = quiet.model_copy(
        update={"drift": DriftModel(sd_per_sqrt_d=0.0, bound=0.5, recalibrated=False)}
    )
    cfg2 = cfg.model_copy(update={"sensors": {**cfg.sensors, "ph": never}})
    plain = observe(channels, cfg2, "B", seed=1, faults=faults)["ph"].value - 7.30
    assert plain[-1] == pytest.approx(-0.01 * 199.0, abs=1e-6)


def test_random_gaps_adds_gaps_that_carry_no_information_about_the_state():
    """Level 1 must be MCAR: the ADDED gaps must be as likely in the stress window as outside.

    Scaling the base rate scales the stressed rate by the same factor, so every added gap
    would be `overload_multiplier` times more likely under stress — as informative as the
    originals, and indistinguishable from the Level-4 `informative_missingness` fault that
    exists precisely to be the informative one. The added term is therefore unconditional.
    """
    config = load_observation_config()
    channels = _flat_channels(n_days=8000, stress_from=4000)
    base_rate = config.missingness.base_rate_by_tier["B"]
    multiplier = config.missingness.stress_multipliers_by_kind["online"]["overload"]
    faults = ObservationFaults(missing_scale=3.0)
    added_calm = added_stress = calm_n = stress_n = 0
    for seed in range(6):
        clean = observe(channels, config, "B", seed=seed)["gas_flow"]
        dirty = observe(channels, config, "B", seed=seed, faults=faults)["gas_flow"]
        calm = clean.sample_t < 4000
        added_calm += int(dirty.missing[calm].sum() - clean.missing[calm].sum())
        added_stress += int(dirty.missing[~calm].sum() - clean.missing[~calm].sum())
        calm_n += int(calm.sum())
        stress_n += int((~calm).sum())
    rate_calm = added_calm / calm_n
    rate_stress = added_stress / stress_n
    # the added rate is (scale - 1) x base, the same in both windows
    assert rate_calm == pytest.approx(2.0 * base_rate, rel=0.15)
    assert rate_stress / rate_calm == pytest.approx(1.0, abs=0.20), (rate_calm, rate_stress)
    # which is a real distinction: scaling the base rate would have made it `multiplier`
    assert multiplier > 2.0
    # the conditional structure itself is untouched — the CLEAN gaps still cluster
    clean_ratio = (
        clean.missing[~calm].mean() / clean.missing[calm].mean()  # last seed is enough here
    )
    assert clean_ratio == pytest.approx(multiplier, rel=0.35)


# --------------------------------------- the Level-6 imperfect-mixing truth variant


def _mixing_run(stagnant: float, feed_scale: float, days: float = 60.0):
    """Plant C under a mixing structure, at a scaled constant feed; returns the effluent COD."""
    from sim.influent import constant_influent, nominal_mass_rates, truth_parameters

    catalogue = load_feed_fractionation()
    plant = load_all_plants()["C"]
    params = load_parameters()
    rates = {k: v * feed_scale for k, v in nominal_mass_rates(plant, catalogue).items()}
    influent = constant_influent(catalogue, rates)
    truth = truth_parameters(params, catalogue, rates)
    geometry = declared_geometry(plant)
    plan = build_plan(
        _scenario(
            Fault(type=FaultType.IMPERFECT_MIXING, onset_day=0.0, magnitude=stagnant),
            plant="C",
            level=6,
            labels=(TruthLabel.STRUCTURAL,),
        )
        if stagnant > 0.0
        else _scenario(),
        ("primary_sludge", "thickened_was"),
    )
    mixing = truth_mixing(plan)
    model = compile_two_zone(
        truth, geometry, load_matrix(), load_solver_config(), load_extensions(),
        plant.truth_model.extensions, mixing,
    )  # fmt: skip
    from tests.conftest import RJ2006_GAS_STATE  # noqa: F401  (imported for clarity)

    y0 = initial_state(model, _base_state())
    result = simulate_two_zone(
        y0=y0, influent=influent, model=model, t_span=(0.0, days), t_eval=np.array([days])
    )
    assert result.success
    return result, mixing


def _base_state() -> np.ndarray:
    """The R&J 2006 29-state vector (the probe harness's steady state)."""
    import importlib.util
    import sys

    from sim.adm1.model import state_vector
    from tests.conftest import CANDIDATES_DIR, RJ2006_GAS_STATE

    spec = importlib.util.spec_from_file_location("probe_common", CANDIDATES_DIR / "common.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["probe_common"] = module
    spec.loader.exec_module(module)
    return state_vector(module.STEADY_STATE_RJ2006, RJ2006_GAS_STATE)


def test_imperfect_mixing_is_the_cstr_at_magnitude_zero():
    """Magnitude 0 gives the ideal CSTR the plant contract declares, exactly."""
    plan = build_plan(_scenario(), PLANT_B_FEEDS)
    assert truth_mixing(plan).ideal
    zero = build_plan(
        _scenario(
            Fault(type=FaultType.IMPERFECT_MIXING, onset_day=0.0, magnitude=0.0),
            level=6,
            labels=(TruthLabel.STRUCTURAL,),
        ),
        PLANT_B_FEEDS,
    )
    assert truth_mixing(zero).ideal
    # and the two-zone reactor at that structure reproduces the extended model bit for bit
    result, _structure = _mixing_run(0.0, 1.0, days=30.0)
    catalogue = load_feed_fractionation()
    from sim.influent import constant_influent, nominal_mass_rates, truth_parameters

    plant = load_all_plants()["C"]
    rates = nominal_mass_rates(plant, catalogue)
    params = truth_parameters(load_parameters(), catalogue, rates)
    geometry = declared_geometry(plant)
    model = compile_extended(
        params, geometry, load_matrix(), load_solver_config(), load_extensions(),
        plant.truth_model.extensions,
    )  # fmt: skip
    reference = simulate_extended(
        y0=extended_state(model, _base_state(), {}),
        influent=constant_influent(catalogue, rates),
        model=model,
        t_span=(0.0, 30.0),
        t_eval=np.array([30.0]),
    )
    np.testing.assert_allclose(result.y[:, -1], reference.y[:, -1], rtol=1e-10)


def test_two_zone_channels_come_from_where_the_instrument_is():
    """A grab sample is the effluent — including its alkalinity, so FOS/TAC is one liquid.

    Three places disagree under a bypass and each channel must come from its own:
    the shared headspace (gas), the probe in the reactor (pH, free ammonia) and the grab
    sample (alkalinity, VFA, COD, TAN, solids). Taking VFA from the sample while taking
    alkalinity from the reactor — which is what happens if the effluent's speciation is not
    computed — leaves FOS/TAC a ratio across two different liquids, and FOS/TAC is what
    raises the overload and foaming flags behind the missingness model.
    """
    T_op = load_all_plants()["C"].temperature.setpoint_K
    # magnitude 0: no bypass, so sample and reactor are the same liquid, exactly
    ideal, structure = _mixing_run(0.0, 1.0, days=30.0)
    assert structure.bypass_fraction == 0.0
    same = channels_from_two_zone(ideal, T_op=T_op)
    reactor_only = channel_series(ideal.active, T_op=T_op)
    for name in same.names:
        np.testing.assert_allclose(same[name], reactor_only[name], rtol=1e-12, err_msg=name)

    # with a bypass the sampled channels move and the reactor's channels do not
    result, structure = _mixing_run(0.30, 1.0, days=60.0)
    assert structure.bypass_fraction > 0.0
    sampled = channels_from_two_zone(result, T_op=T_op)
    reactor = channel_series(result.active, T_op=T_op)
    # the probe and the headspace are in the reactor: identical
    for name in ("pH", "free_ammonia", "q_gas_stp_dry", "ch4_fraction", "temperature"):
        np.testing.assert_allclose(sampled[name], reactor[name], rtol=1e-12, err_msg=name)
    # the grab sample is the effluent: alkalinity moves with it, not with the reactor
    assert sampled["alkalinity_total"][-1] != pytest.approx(reactor["alkalinity_total"][-1])
    assert sampled["vfa_total"][-1] > reactor["vfa_total"][-1]  # bypassed feed carries acetate
    # and FOS/TAC is the ratio of the two SAMPLED quantities, not a mixture of liquids
    assert sampled["fos_tac"][-1] == pytest.approx(
        sampled["vfa_total"][-1] / sampled["alkalinity_total"][-1]
    )
    hybrid = sampled["vfa_total"][-1] / reactor["alkalinity_total"][-1]
    assert sampled["fos_tac"][-1] != pytest.approx(hybrid, rel=1e-3)  # the two really differ

    # the contract is enforced, not merely honoured by this one caller
    with pytest.raises(ValueError, match="effluent needs effluent_derived"):
        channel_series(result.active, T_op=T_op, effluent=result.effluent)


def test_imperfect_mixing_gives_a_load_dependent_residual():
    """§6.3 Level 6: a load-proportional residual against the CSTR, not a kinetic signature.

    A bypass sends a fraction of the influent straight to the effluent, so the COD that
    escapes unreacted — and the gas that is therefore not made — scales with the load.
    Measured here at 0.6x, 1.0x and 1.4x the declared feed: the gas deficit is 24.7, 41.2
    and 57.9 m3/d, i.e. proportional to within a few per cent, while the *relative*
    deficit stays near 6 % (the feed concentration is unchanged, only its flow). A
    residual that grows with throughput this way is what tells an analyst the fault is
    hydraulic rather than kinetic.
    """
    deficits, relative = {}, {}
    for scale in (0.6, 1.0, 1.4):
        ideal, _ = _mixing_run(0.0, scale)
        mixed, structure = _mixing_run(0.30, scale)
        assert structure.stagnant_fraction == pytest.approx(0.30)
        assert structure.bypass_fraction == pytest.approx(0.06)  # a fifth of the stagnant share
        gas_ideal = float(ideal.active.derived["q_gas_stp_dry"][-1])
        gas_mixed = float(mixed.active.derived["q_gas_stp_dry"][-1])
        deficits[scale] = gas_ideal - gas_mixed
        relative[scale] = deficits[scale] / gas_ideal
        # the effluent also carries unreacted feed past the reactor
        assert np.sum(mixed.effluent[:, -1]) > np.sum(ideal.effluent[:, -1])
    assert deficits[1.4] > deficits[1.0] > deficits[0.6] > 0.0, deficits
    assert all(0.03 < r < 0.10 for r in relative.values()), relative  # a real signal
    # proportional to the load, to within 10 %
    for scale in (0.6, 1.4):
        assert deficits[scale] / deficits[1.0] == pytest.approx(scale, rel=0.10), deficits
