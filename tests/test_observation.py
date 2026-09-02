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
* the three properties the lead made **tier** properties rather than sensor ones — the
  base missing rate, the laboratory turnaround and the recalibration cadence — are read
  from the tier and really differ between tiers, on identical truth and an identical
  sensor set;
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
from sim.observation.schema import (
    MissingnessModel,
    MissingnessPolicy,
    NoiseModel,
    SaturationModel,
    SensorSpec,
)

DEGF_TO_K = 5.0 / 9.0


@pytest.fixture(scope="module")
def config() -> ObservationConfig:
    return load_observation_config()


def _without_missingness(config: ObservationConfig) -> ObservationConfig:
    """The same configuration with no samples lost — missingness is now a tier policy."""
    quiet = config.missingness.model_copy(update={"base_rate_by_tier": dict.fromkeys("ABC", 0.0)})
    return config.model_copy(update={"missingness": quiet})


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
    policy = config.missingness.model_dump()
    with pytest.raises(ValidationError, match="must cover tiers A, B and C"):
        MissingnessPolicy.model_validate(policy | {"base_rate_by_tier": {"A": 0.08, "B": 0.04}})
    with pytest.raises(ValidationError, match="must cover 'online' and 'lab'"):
        MissingnessPolicy.model_validate(
            policy | {"stress_multipliers_by_kind": {"online": {"overload": 4.0}}}
        )


def test_missingness_rate_compounds_and_caps():
    m = MissingnessModel(base_rate=0.1, stress_multipliers={"overload": 3.0, "foaming": 5.0})
    assert m.rate(frozenset()) == pytest.approx(0.1)
    assert m.rate(frozenset({"overload"})) == pytest.approx(0.3)
    assert m.rate(frozenset({"overload", "foaming"})) == pytest.approx(1.0)  # capped


def test_missingness_and_turnaround_are_tier_properties(config):
    """The lead's decision of 2026-09-02, as declared and as resolved per sensor.

    A tier is the plant's monitoring capability: the constrained plant loses the most
    samples and waits the longest for a laboratory result. The stress multipliers are the
    other way round — they belong to the *kind* of instrument, so they are identical
    across tiers and an online probe degrades far more than a grab sample.
    """
    policy = config.missingness
    assert [policy.base_rate_by_tier[t] for t in "ABC"] == [0.08, 0.04, 0.02]
    assert [config.tiers[t].lab_turnaround_d for t in "ABC"] == [7.0, 3.0, 1.0]
    assert [config.tiers[t].recalibration_interval_d for t in "ABC"] == [90.0, 30.0, 30.0]
    online = policy.stress_multipliers_by_kind["online"]
    lab = policy.stress_multipliers_by_kind["lab"]
    assert online == {"overload": 4.0, "foaming": 3.0}
    assert lab == {"overload": 1.5, "foaming": 1.5}
    for flag in ("overload", "foaming"):
        assert online[flag] > lab[flag], flag
    # resolved per sensor: the same probe is described differently at each tier
    for tier in "ABC":
        for kind in ("online", "lab"):
            model = policy.model_for(tier, kind)
            assert model.base_rate == policy.base_rate_by_tier[tier]
            assert model.stress_multipliers == policy.stress_multipliers_by_kind[kind]
    assert policy.model_for("A", "online").rate(frozenset({"overload"})) == pytest.approx(0.32)


def test_the_tier_sets_the_missing_rate_the_lag_and_the_recalibration_cadence(config):
    """Observed: identical truth and identical sensors, three tiers, three windows onto it.

    Read at the tiers' shared sensors only, so nothing here can come from a difference in
    the sensor set. Tier C is the last 6,000-day realisation; the counts are large enough
    that the ordering is not a coincidence (Tier A loses ~480 of 6,000 pH samples, Tier C
    ~120, and a Poisson standard error on either is under 25).
    """
    channels = _flat_channels(n_days=6000)
    lost = {}
    for tier in "ABC":
        record = observe(channels, config, tier, seed=5)
        lost[tier] = int(record["ph"].missing.sum()) + int(record["gas_flow"].missing.sum())
        # the laboratory turnaround is the tier's, and online instruments report at once
        assert np.all(record["ph"].report_t == record["ph"].sample_t)
        if tier != "A":
            weekly = record["alkalinity"]
            assert np.all(weekly.report_t - weekly.sample_t == config.tiers[tier].lab_turnaround_d)
    assert lost["A"] > lost["B"] > lost["C"] > 0
    assert lost["A"] / lost["C"] == pytest.approx(4.0, rel=0.25)  # 8 % against 2 %


def test_the_recalibration_cadence_is_the_tier_s(config):
    """Only the tier's cadence changes: same tier, same sensors, same stream, same draws.

    A random walk of daily step ``s`` reset every ``T`` days has mean square offset
    ``s^2 T / 2``, so quarterly recalibration leaves an offset ``sqrt(3)`` times the size
    of monthly. Both stay far inside the probe's 0.5 pH bound, so the bound does not
    confound the comparison.
    """
    channels = _flat_channels(n_days=6000)
    spec = config.sensors["ph"]
    assert spec.drift is not None and spec.drift.recalibrated
    quiet = spec.model_copy(update={"noise": NoiseModel(cv=0.0, sd_abs=1e-12), "fouling": None})
    base = _without_missingness(config).model_copy(
        update={"sensors": {**config.sensors, "ph": quiet}}
    )
    offsets = {}
    for interval in (30.0, 90.0):
        tier = base.tiers["A"].model_copy(update={"recalibration_interval_d": interval})
        cfg = base.model_copy(update={"tiers": {**base.tiers, "A": tier}})
        offsets[interval] = observe(channels, cfg, "A", seed=5)["ph"].value - 7.30
    step = spec.drift.sd_per_sqrt_d
    # the walk restarts from zero at every boundary of the declared cadence, and only there
    for interval, offset in offsets.items():
        boundaries = np.arange(int(interval), offset.size, int(interval))
        assert np.abs(offset[boundaries]).max() <= 5.0 * step, interval
        assert np.abs(offset).max() > 10.0 * step  # it does drift in between
        assert np.abs(offset).max() < spec.drift.bound  # and never reaches the bound
    ratio = np.sqrt(np.mean(offsets[90.0] ** 2) / np.mean(offsets[30.0] ** 2))
    assert ratio == pytest.approx(np.sqrt(3.0), rel=0.25)
    # up to the first reset the two are the same walk, drawn from the same stream
    np.testing.assert_allclose(offsets[30.0][:30], offsets[90.0][:30])


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
    assert np.all(weekly.report_t - weekly.sample_t == config.tiers["C"].lab_turnaround_d)
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
    assert spec.drift is not None and not spec.drift.recalibrated
    no_drift = spec.model_copy(update={"drift": None, "flatline": None})
    cfg = config.model_copy(update={"sensors": {**config.sensors, "temperature": no_drift}})
    quiet = observe(channels, cfg, "B", seed=7)["temperature"]
    resid = quiet.value[~quiet.missing] - 311.0
    assert abs(resid.mean()) < 0.01
    assert resid.std() == pytest.approx(spec.noise.sd_abs, rel=0.15)
    temp = record["temperature"]
    ok_t = ~temp.missing & ~temp.flatlined
    assert np.abs(temp.value[ok_t] - 311.0).max() < spec.drift.bound + 5 * spec.noise.sd_abs


def test_relative_and_absolute_noise_are_independent_draws(config):
    """A sensor declaring both terms gets sqrt((v cv)^2 + sd_abs^2), not the correlated sum."""
    spec = config.sensors["h2_offgas"]
    assert spec.noise.cv > 0.0 and spec.noise.sd_abs > 0.0  # the one sensor with both
    value = 12.0
    channels = _flat_channels(n_days=4000)
    quiet = spec.model_copy(update={"drift": None, "saturation": None})
    cfg = _without_missingness(config).model_copy(
        update={"sensors": {**config.sensors, "h2_offgas": quiet}}
    )
    reported = observe(channels, cfg, "C", seed=17)["h2_offgas"].value
    independent = float(np.hypot(value * spec.noise.cv, spec.noise.sd_abs))
    correlated = value * spec.noise.cv + spec.noise.sd_abs
    assert reported.std() == pytest.approx(independent, rel=0.08)
    assert reported.std() < 0.9 * correlated  # the two are far enough apart to tell
    assert reported.mean() == pytest.approx(value, rel=0.02)


def test_drift_is_bounded_and_reset_by_recalibration(config):
    """The pH probe's random walk stays inside its bound and jumps back at recalibration."""
    channels = _flat_channels(n_days=400)
    spec = config.sensors["ph"]
    assert spec.drift is not None and spec.drift.recalibrated
    assert config.tiers["B"].recalibration_interval_d == 30.0  # the cadence is the tier's
    # isolate the drift: no noise, no fouling, no missingness
    quiet = spec.model_copy(update={"noise": NoiseModel(cv=0.0, sd_abs=1e-12), "fouling": None})
    cfg = _without_missingness(config).model_copy(
        update={"sensors": {**config.sensors, "ph": quiet}}
    )
    value = observe(channels, cfg, "B", seed=3)["ph"].value
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
    """The §6.1 property: gaps cluster in the stress window, so interpolation loses information.

    All three sensors here are online probes, so the expected ratio is the online overload
    multiplier, 4. Pooled over twelve seeds, because the ratio is a ratio of two counts:
    at Tier B each sensor loses ~1,400 samples in the 3,000 calm days and ~5,700 in the
    3,000 overloaded ones. Per seed the estimator has sd ~0.42, so pooling twelve gives a
    standard error near 0.12 and the 20 % tolerance (+/- 0.8) is a ~6 sd bound rather than
    a rubber stamp. Over forty seeds it converges to 3.96 +/- 0.07 (pH), 4.12 +/- 0.07
    (gas flow) and 3.92 +/- 0.06 (CH4), so the implementation is unbiased.
    """
    channels = _flat_channels(n_days=6000, stress_from=3000)
    names = ("ph", "gas_flow", "ch4_fraction")
    lost_before = dict.fromkeys(names, 0)
    lost_after = dict.fromkeys(names, 0)
    seen_before = seen_after = 0
    for seed in range(12):
        record = observe(channels, config, "B", seed=seed)
        for name in names:
            series = record[name]
            calm = series.sample_t < 3000
            lost_before[name] += int(series.missing[calm].sum())
            lost_after[name] += int(series.missing[~calm].sum())
            if name == "ph":
                seen_before += int(calm.sum())
                seen_after += int((~calm).sum())
    for name in names:
        before = lost_before[name] / seen_before
        after = lost_after[name] / seen_after
        spec = config.missingness.model_for("B", config.sensors[name].kind)
        expected = spec.stress_multipliers["overload"]
        assert lost_before[name] > 300 and lost_after[name] > 600, (name, lost_before, lost_after)
        assert after > before, name
        assert after / before == pytest.approx(expected, rel=0.20), (name, before, after)
        assert before == pytest.approx(spec.base_rate, rel=0.15), name
    # a laboratory assay degrades under the same overload, but far less than an online probe
    lab = config.missingness.model_for("B", "lab")
    online = config.missingness.model_for("B", "online")
    flags = frozenset({"overload"})
    assert lab.rate(flags) < online.rate(flags)
    assert config.sensors["alkalinity"].kind == "lab"


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
