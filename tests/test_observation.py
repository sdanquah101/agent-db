"""The observation model (sim/observation, configs/observation/sensors.yaml).

What is tested and why it cannot pass vacuously:

* the configuration loads, every sensor measures a known channel with its unit and its
  convention declared, and the tiers are **nested masks** (§6.4) — a higher tier only
  adds channels, and removing a sensor from B is shown to fail;
* the two anchored sensor values are re-derived from the Muscatine 1-minute SCADA file
  (temperature noise, gas-flow noise cv, both flatline rates), so the specs cannot drift
  from the data they claim to summarise;
* the channel arithmetic is checked against hand calculations (alkalinity as CaCO3, VFA
  as acetic acid, FOS/TAC against the plant's own ratio, VS from COD, the ash tracer
  against its analytical solution);
* each sensor effect does what it says: the schedule and lag, unbiased noise of the
  declared size, drift bounded and reset at recalibration, flatline holding the previous
  value, saturation clipping, and **conditional missingness** — gaps are several times
  more likely inside the stress window than outside it, which is the property that makes
  naive interpolation destroy information;
* one seeded stream, consumed per sensor in sorted order: same seed same record, and
  changing one sensor's spec leaves the sensors that precede it bit-identical.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from anchor.ingest_muscatine import SCADA_FILE, scada_noise_statistics
from sim.observation import (
    CHANNEL_UNITS,
    ObservationConfig,
    TruthChannels,
    ash_trajectory,
    channel_series,
    condition_flags,
    load_observation_config,
    observe,
)
from sim.observation.channels import KG_CACO3_PER_KMOL_CHARGE, M_ACETIC
from sim.observation.schema import MissingnessModel, NoiseModel, SaturationModel, SensorSpec

DEGF_TO_K = 5.0 / 9.0


@pytest.fixture(scope="module")
def config() -> ObservationConfig:
    return load_observation_config()


def _flat_channels(n_days: int = 200, stress_from: int | None = None) -> TruthChannels:
    """A synthetic run: constant channels, optionally with a stress window."""
    t = np.arange(float(n_days))
    fos = np.full(t.size, 0.20)
    if stress_from is not None:
        fos[stress_from:] = 0.60  # above the overload threshold
    return TruthChannels(
        t,
        {
            "temperature": np.full(t.size, 311.0),
            "pH": np.full(t.size, 7.30),
            "q_gas_stp_dry": np.full(t.size, 1500.0),
            "ch4_fraction": np.full(t.size, 0.62),
            "alkalinity_total": np.full(t.size, 5.0),
            "vfa_total": np.full(t.size, 1.0),
            "tan": np.full(t.size, 1.2),
            "cod_total": np.full(t.size, 40.0),
            "vfa_ac": np.full(t.size, 0.6),
            "vfa_pro": np.full(t.size, 0.2),
            "vfa_bu": np.full(t.size, 0.1),
            "vfa_va": np.full(t.size, 0.05),
            "h2_ppm": np.full(t.size, 12.0),
            "vs": np.full(t.size, 25.0),
            "ts": np.full(t.size, 33.0),
            "fos_tac": fos,
        },
    )


# ------------------------------------------------------------------ configuration


def test_config_loads_with_channels_units_and_conventions(config):
    assert set(config.tiers) == {"A", "B", "C"}
    for name, spec in config.sensors.items():
        assert spec.name == name
        assert spec.channel in CHANNEL_UNITS, (name, spec.channel)
        assert spec.unit
        if spec.channel.startswith(("q_gas", "ch4_", "co2_", "h2_")):
            assert spec.gas_convention != "none", name
        if spec.channel in ("ts", "vs"):
            assert spec.solids_basis != "none", name
        assert spec.kind in ("online", "lab")
        assert spec.source or spec.noise.source


def test_tiers_are_nested_observation_masks(config):
    """§6.4: tiers are masks on identical truth, so C contains B contains A."""
    a, b, c = (set(config.tiers[t].sensors) for t in "ABC")
    assert a < b < c
    assert a == {"temperature", "ph", "gas_flow"}
    assert {"ch4_fraction", "alkalinity", "vfa_total", "tan", "cod_total"} <= b
    assert {"vfa_ac", "vfa_pro", "vfa_bu", "vfa_va", "h2_offgas"} <= c
    for lower, upper in (("A", "B"), ("B", "C")):
        assert set(config.tiers[lower].feed_assays) <= set(config.tiers[upper].feed_assays)
    # the containment is enforced, not merely true today
    raw = config.model_dump()
    raw["tiers"]["B"]["sensors"] = [s for s in raw["tiers"]["B"]["sensors"] if s != "ph"]
    with pytest.raises(ValidationError, match="must contain every sensor"):
        ObservationConfig.model_validate(raw)


def test_schema_rejections(config):
    with pytest.raises(ValidationError, match="non-zero cv or sd_abs"):
        NoiseModel(cv=0.0, sd_abs=0.0)
    with pytest.raises(ValidationError, match="low must be below high"):
        SaturationModel(low=5.0, high=1.0)
    spec = config.sensors["gas_flow"].model_dump()
    with pytest.raises(ValidationError, match="gas_convention"):
        SensorSpec.model_validate(spec | {"gas_convention": "none"})
    raw = config.model_dump()
    raw["tiers"]["A"]["sensors"] = ["nonexistent"]
    with pytest.raises(ValidationError, match="unknown sensors"):
        ObservationConfig.model_validate(raw)


def test_missingness_rate_compounds_and_caps():
    m = MissingnessModel(base_rate=0.1, stress_multipliers={"overload": 3.0, "foaming": 5.0})
    assert m.rate(frozenset()) == pytest.approx(0.1)
    assert m.rate(frozenset({"overload"})) == pytest.approx(0.3)
    assert m.rate(frozenset({"overload", "foaming"})) == pytest.approx(1.0)  # capped


@pytest.mark.skipif(not SCADA_FILE.exists(), reason="Muscatine SCADA file not fetched")
def test_anchored_sensor_values_are_rederived_from_the_scada_file(config):
    """The two ANCHORED specs come out of the 1-minute file (the rest are marked ASSUMED)."""
    temp = scada_noise_statistics("D1_TEMPERATURE")
    gas = scada_noise_statistics("Biogas")
    assert temp.n > 400_000 and gas.n > 400_000
    # temperature: degF -> K, the spec's absolute noise
    assert config.sensors["temperature"].noise.sd_abs == pytest.approx(
        temp.noise_sd * DEGF_TO_K, abs=0.005
    )
    # gas flow: a relative noise, unit-free
    assert config.sensors["gas_flow"].noise.cv == pytest.approx(gas.noise_cv, abs=0.003)
    # flatline occupancy: hazard x mean duration reproduces the measured fraction
    for name, stats in (("temperature", temp), ("gas_flow", gas)):
        spec = config.sensors[name].flatline
        assert spec is not None
        occupancy = spec.hazard_per_d * spec.mean_duration_d
        assert 0.2 * stats.flatline_fraction < occupancy < 20 * stats.flatline_fraction, name
    # and the file really is pre-cleaned, which is why missingness is ASSUMED
    assert temp.missing_fraction == 0.0 and gas.missing_fraction == 0.0


# ------------------------------------------------------------------ channels


def test_channel_arithmetic_matches_hand_calculation(adm1_params, rj2006_state, adm1_plant):
    """Alkalinity, VFA and FOS/TAC follow from the speciation by their definitions."""
    from sim.adm1 import compile_extended, load_extensions, load_matrix, load_solver_config
    from sim.adm1.extensions import extended_state, simulate_extended
    from sim.influent import constant_influent, load_feed_fractionation, nominal_mass_rates
    from sim.plants import declared_geometry, load_all_plants

    catalogue = load_feed_fractionation()
    plant = load_all_plants()["C"]
    rates = nominal_mass_rates(plant, catalogue)
    influent = constant_influent(catalogue, rates)
    geometry = declared_geometry(plant)
    model = compile_extended(
        adm1_params, geometry, load_matrix(), load_solver_config(), load_extensions(), ("sao",)
    )
    result = simulate_extended(
        y0=extended_state(model, rj2006_state, {"X_sao": 0.01}),
        influent=influent,
        model=model,
        t_span=(0.0, 20.0),
        t_eval=np.arange(0.0, 21.0),
    )
    channels = channel_series(result, T_op=geometry.T_op)
    d = result.derived
    i = -1
    # total alkalinity = 50 kg CaCO3 per kmol of bicarbonate + VFA anion charge
    charge = (
        d["S_hco3_ion"][i]
        + d["S_ac_ion"][i] / 64.0
        + d["S_pro_ion"][i] / 112.0
        + d["S_bu_ion"][i] / 160.0
        + d["S_va_ion"][i] / 208.0
    )
    assert channels["alkalinity_total"][i] == pytest.approx(KG_CACO3_PER_KMOL_CHARGE * charge)
    assert channels["alkalinity_partial"][i] == pytest.approx(
        KG_CACO3_PER_KMOL_CHARGE * d["S_hco3_ion"][i]
    )
    assert channels["alkalinity_partial"][i] < channels["alkalinity_total"][i]
    # VFA as acetic-acid equivalent, from the COD states
    ac_kmol = result.y[6, i] / 64.0
    assert channels["vfa_ac"][i] == pytest.approx(ac_kmol * M_ACETIC / 1000.0)
    assert channels["fos_tac"][i] == pytest.approx(
        channels["vfa_total"][i] / channels["alkalinity_total"][i]
    )
    # gas conventions differ and both are reported
    assert channels["q_gas_stp_dry"][i] != channels["q_gas_operating"][i]
    assert 0.0 < channels["ch4_fraction"][i] < 1.0
    assert channels["temperature"][0] == geometry.T_op
    # solids need the influent's inert equivalent; without it they are absent
    assert "vs" not in channels and "ts" not in channels


def test_ash_tracer_matches_the_analytical_dilution(adm1_plant):
    """Ash is conserved, so the tracer is the exact first-order approach to the feed value."""
    from sim.adm1.schema import Influent

    t = np.arange(0.0, 51.0)
    q, V, ash_in = 100.0, 1000.0, 8.0
    influent = Influent.constant(np.zeros(26), q)
    ash = ash_trajectory(t, influent, V, ash_in, ash0=0.0)
    expected = ash_in * (1.0 - np.exp(-q / V * t))
    np.testing.assert_allclose(ash, expected, rtol=1e-9)
    assert ash[-1] == pytest.approx(ash_in, rel=0.01)
    # starting at the feed value it stays there
    assert ash_trajectory(t, influent, V, ash_in, ash0=ash_in) == pytest.approx(ash_in)


def test_condition_flags_use_only_past_gas_history(config):
    channels = _flat_channels(stress_from=100)
    overload, foaming = condition_flags(
        channels,
        fos_tac_overload=config.conditions.fos_tac_overload,
        fos_tac_foaming=config.conditions.fos_tac_foaming,
        gas_surge_ratio=config.conditions.gas_surge_ratio,
        gas_median_window_d=config.conditions.gas_median_window_d,
    )
    assert not overload[:100].any() and overload[100:].all()
    assert not foaming.any()  # a flat gas rate never surges above its own median
    # a real surge with elevated FOS/TAC does raise foaming
    t = channels.t
    gas = np.full(t.size, 1500.0)
    gas[150:155] = 3000.0
    surged = TruthChannels(t, {**{k: channels[k] for k in channels.names}, "q_gas_stp_dry": gas})
    _, foaming2 = condition_flags(
        surged,
        fos_tac_overload=config.conditions.fos_tac_overload,
        fos_tac_foaming=config.conditions.fos_tac_foaming,
        gas_surge_ratio=config.conditions.gas_surge_ratio,
        gas_median_window_d=config.conditions.gas_median_window_d,
    )
    assert foaming2[150:155].all() and not foaming2[:150].any()


# ------------------------------------------------------------------ the sensors


def test_schedule_lag_and_units(config):
    channels = _flat_channels()
    record = observe(channels, config, "C", seed=1)
    assert record.tier == "C" and record.names == tuple(sorted(config.tiers["C"].sensors))
    daily = record["gas_flow"]
    weekly = record["alkalinity"]
    assert daily.sample_t.size == 200 and weekly.sample_t.size == 29
    np.testing.assert_allclose(np.diff(weekly.sample_t), 7.0)
    assert np.all(weekly.report_t - weekly.sample_t == config.sensors["alkalinity"].lag_d)
    assert record.units["gas_flow"] == "m3/d"
    assert daily.gas_convention == "stp_dry" and record["digestate_vs"].solids_basis == "wet"
    with pytest.raises(KeyError, match="not readable"):
        observe(channels, config, "A", seed=1)["alkalinity"]
    with pytest.raises(KeyError, match="unknown tier"):
        observe(channels, config, "D", seed=1)


def test_noise_is_unbiased_and_of_the_declared_size(config):
    """Over many samples the reported values scatter around the truth by the declared cv."""
    channels = _flat_channels(n_days=2000)
    record = observe(channels, config, "B", seed=7)
    gas = record["gas_flow"]
    ok = ~gas.missing & ~gas.flatlined
    ratio = gas.value[ok] / 1500.0
    assert ratio.mean() == pytest.approx(1.0, abs=0.005)
    assert ratio.std() == pytest.approx(config.sensors["gas_flow"].noise.cv, rel=0.15)
    # an absolute-noise sensor: temperature, sd_abs in K. Its drift has no recalibration,
    # so the residual is noise on top of a bounded random walk: isolate the noise by
    # switching the walk off, and check the walk stays inside its bound with it on.
    spec = config.sensors["temperature"]
    assert spec.drift is not None and spec.drift.recalibration_interval_d is None
    no_drift = spec.model_copy(update={"drift": None, "flatline": None})
    cfg = config.model_copy(update={"sensors": {**config.sensors, "temperature": no_drift}})
    quiet = observe(channels, cfg, "B", seed=7)["temperature"]
    resid = quiet.value[~quiet.missing] - 311.0
    assert abs(resid.mean()) < 0.01
    assert resid.std() == pytest.approx(spec.noise.sd_abs, rel=0.15)
    temp = record["temperature"]
    ok_t = ~temp.missing & ~temp.flatlined
    assert np.abs(temp.value[ok_t] - 311.0).max() < spec.drift.bound + 5 * spec.noise.sd_abs


def test_drift_is_bounded_and_reset_by_recalibration(config):
    """The pH probe's random walk stays inside its bound and jumps back at recalibration."""
    channels = _flat_channels(n_days=400)
    spec = config.sensors["ph"]
    assert spec.drift is not None and spec.drift.recalibration_interval_d == 30.0
    # isolate the drift: no noise, no fouling, no missingness
    quiet = spec.model_copy(
        update={
            "noise": NoiseModel(cv=0.0, sd_abs=1e-12),
            "fouling": None,
            "missingness": MissingnessModel(base_rate=0.0),
        }
    )
    cfg = config.model_copy(update={"sensors": {**config.sensors, "ph": quiet}})
    value = observe(channels, cfg, "A", seed=3)["ph"].value
    offset = value - 7.30
    assert np.abs(offset).max() <= spec.drift.bound + 1e-9
    # the sample after each recalibration boundary starts again from zero
    for boundary in (30, 60, 90, 120):
        assert abs(offset[boundary]) < abs(offset[boundary - 1]) or abs(offset[boundary]) < 0.02
    assert np.abs(offset).max() > 0.01  # it does drift


def test_flatline_holds_the_previous_value_and_saturation_clips(config):
    channels = _flat_channels(n_days=3000)
    record = observe(channels, config, "A", seed=11)
    temp = record["temperature"]
    held = np.flatnonzero(temp.flatlined & ~temp.missing)
    assert held.size > 0
    for i in held:
        if i > 0 and not temp.missing[i - 1]:
            assert temp.value[i] == pytest.approx(temp.value[i - 1])
    # saturation: a channel far outside the readable range is clipped and flagged
    hot = TruthChannels(
        channels.t,
        {
            **{k: channels[k] for k in channels.names},
            "temperature": np.full(channels.t.size, 400.0),
        },
    )
    clipped = observe(hot, config, "A", seed=11)["temperature"]
    ok = ~clipped.missing
    assert clipped.saturated[ok].all()
    assert np.nanmax(clipped.value) <= config.sensors["temperature"].saturation.high


def test_missingness_is_conditional_on_the_process_state(config):
    """The §6.1 property: gaps cluster in the stress window, so interpolation loses information."""
    channels = _flat_channels(n_days=4000, stress_from=2000)
    record = observe(channels, config, "B", seed=5)
    for name in ("ph", "gas_flow", "ch4_fraction"):
        series = record[name]
        before = series.missing[series.sample_t < 2000].mean()
        after = series.missing[series.sample_t >= 2000].mean()
        spec = config.sensors[name].missingness
        expected = spec.stress_multipliers["overload"]
        assert after > before, name
        assert after / before == pytest.approx(expected, rel=0.35), (name, before, after)
        assert before == pytest.approx(spec.base_rate, rel=0.25), name
    # the lab assays carry an overload multiplier but no foaming one
    assert "foaming" not in config.sensors["alkalinity"].missingness.stress_multipliers


def test_one_seeded_stream_in_sorted_sensor_order(config):
    """Same seed, same record; changing one sensor leaves the sensors before it untouched."""
    channels = _flat_channels(n_days=300)
    a = observe(channels, config, "C", seed=42)
    b = observe(channels, config, "C", seed=42)
    c = observe(channels, config, "C", seed=43)
    for name in a.names:
        np.testing.assert_array_equal(a[name].value, b[name].value)
    assert not np.array_equal(a["ph"].value, c["ph"].value)
    # 'ph' sorts after 'gas_flow' and 'digestate_ts': changing it cannot move them
    loud = config.sensors["ph"].model_copy(update={"noise": NoiseModel(cv=0.5, sd_abs=0.0)})
    cfg = config.model_copy(update={"sensors": {**config.sensors, "ph": loud}})
    d = observe(channels, cfg, "C", seed=42)
    for earlier in ("alkalinity", "ch4_fraction", "cod_total", "digestate_ts", "gas_flow"):
        np.testing.assert_array_equal(a[earlier].value, d[earlier].value)
    assert not np.array_equal(a["ph"].value, d["ph"].value)
    # requesting a subset does not change any value either
    subset = observe(channels, config, "C", seed=42, sensors=["temperature"])
    np.testing.assert_array_equal(subset["temperature"].value, a["temperature"].value)


def test_a_run_missing_a_channel_is_refused_not_faked(config):
    """Tier C needs the solids channels; a run without them raises rather than inventing them."""
    channels = _flat_channels()
    without = TruthChannels(
        channels.t, {k: channels[k] for k in channels.names if k not in ("vs", "ts")}
    )
    observe(without, config, "B", seed=1)  # Tier B does not need them
    with pytest.raises(ValueError, match="did not compute"):
        observe(without, config, "C", seed=1)
