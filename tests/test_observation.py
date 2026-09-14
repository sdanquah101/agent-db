"""The observation model (sim/observation, configs/observation/sensors.yaml).

What is tested and why it cannot pass vacuously:

* the configuration loads, every sensor measures a known channel with its unit and its
  convention declared, and the tiers are **nested masks** (§6.4) — a higher tier only
  adds channels, and removing a sensor from B is shown to fail;
* the two anchored sensor values are re-derived from the Muscatine 1-minute SCADA file
  (temperature noise, gas-flow noise cv, both flatline rates), so the specs cannot drift
  from the data they claim to summarise — and the **noise** half of that is re-derived on
  a fresh clone from the committed 60-day extract, so the anchor is not a promise that
  only holds for whoever fetched the 88.8 MB parent. What the extract cannot carry (the
  rare-event flatline occupancies, the dropout rate) is asserted to be recorded in
  `anchor/derived/muscatine-scada-sensor-statistics.json` and checked against the parent
  when it is present;
* the one **measured** missing rate — Tier C online, from the record's row dropouts — is
  the value the config declares and reaches the resolved sensor model, while every other
  tier and kind keeps its assumed rate;
* the channel arithmetic is checked against hand calculations written down as **literals**
  rather than restated from the implementation — alkalinity as CaCO3, VFA as acetic acid
  (1 kg COD/m3 of acetate is 0.93828 kg/m3), the extension components' contribution to COD
  and to solids, and the ash tracer against its analytical solution; and FOS/TAC against
  the anchor's own VFA and alkalinity columns, with the overload threshold shown to sit
  inside the distribution the plant really visits. A test that restates the implementation
  passes under any global scale error, which is how a factor of 1000 lived in the VFA
  channels until the review of 2026-09-02;
* each sensor effect does what it says: the schedule and lag, unbiased noise of the
  declared size, drift bounded and reset at recalibration, flatline holding the previous
  value, saturation clipping, and **conditional missingness** — gaps are several times
  more likely inside the stress window than outside it, which is the property that makes
  naive interpolation destroy information;
* the three properties the lead made **tier** properties rather than sensor ones — the
  base missing rate, the laboratory turnaround and the recalibration cadence — are read
  from the tier and really differ between tiers, on identical truth and an identical
  sensor set;
* **one seeded stream per sensor**, derived from (run seed, sensor name): same seed same
  record; changing one sensor's spec leaves every other sensor bit-identical; and a shared
  instrument reads the *same* at every tier that carries it, with a different-seed control
  so the equality cannot be satisfied by a model that stopped drawing. That last property
  was false until 2026-09-04 — the stream was serial over `sorted(tier.sensors)`, so a
  tier comparison was also a re-roll — and the test that missed it compared one shared
  object with itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from anchor.ingest_muscatine import (
    DAILY_FILE,
    SCADA_FILE,
    SCADA_WINDOW_FILE,
    load_daily,
    scada_noise_statistics,
    scada_row_gap_statistics,
)
from sim.observation import (
    CHANNEL_UNITS,
    HistorianDropout,
    ObservationConfig,
    TruthChannels,
    ash_trajectory,
    channel_series,
    condition_flags,
    historian_outages,
    load_observation_config,
    observe,
)
from sim.observation.channels import KG_CACO3_PER_KMOL_CHARGE, M_ACETIC
from sim.observation.model import sensor_rng, sensor_stream_key
from sim.observation.schema import (
    MissingnessModel,
    MissingnessPolicy,
    NoiseModel,
    SaturationModel,
    SensorSpec,
)

DEGF_TO_K = 5.0 / 9.0
SCADA_STATISTICS_FILE = (
    Path(__file__).resolve().parent.parent
    / "anchor"
    / "derived"
    / "muscatine-scada-sensor-statistics.json"
)


@pytest.fixture(scope="module")
def config() -> ObservationConfig:
    return load_observation_config()


def _without_missingness(config: ObservationConfig) -> ObservationConfig:
    """The same configuration with no samples lost, from EITHER missingness process.

    There are two: the per-sensor independent policy, and the plant-level historian
    outage shared across a tier's online sensors. A test that asks for no gaps has to
    silence both, or the historian keeps taking days out from under it.
    """
    quiet = config.missingness.model_copy(update={"base_rate_by_tier": dict.fromkeys("ABC", 0.0)})
    no_outage = config.historian.model_copy(update={"rate_by_tier": dict.fromkeys("ABC", 0.0)})
    return config.model_copy(update={"missingness": quiet, "historian": no_outage})


def _flat_channels(n_days: int = 200, stress_from: int | None = None) -> TruthChannels:
    """A synthetic run: constant channels, optionally with a stress window.

    ``stress_from`` raises **true VFA**, which is what the overload flag triggers on since
    the lead's ruling B of 2026-09-09 — the hidden process state, not a reading. The
    titrimetric channels move with it so the record stays self-consistent, but they are not
    what the flag looks at.

    The trigger is a *departure from recent history*, so a step that stays high stops
    firing once the trailing median catches up. That is the property, not a defect: a
    digester that has sat at a high VFA for a month is not in a transient. Tests that need
    the flag raised throughout use :func:`_sawtooth_channels`.
    """
    t = np.arange(float(n_days))
    vfa = np.full(t.size, 1.0)
    if stress_from is not None:
        vfa[stress_from:] = 3.0  # 3x the pre-window level: well over the 2.0x trigger
    alk = np.full(t.size, 5.0)
    # a titrimetric FOS that moves with the true VFA plus the usual bicarbonate carry-over
    fos_titrimetric = 0.7 + 0.3 * vfa
    return TruthChannels(
        t,
        {
            "temperature": np.full(t.size, 311.0),
            "pH": np.full(t.size, 7.30),
            "q_gas_stp_dry": np.full(t.size, 1500.0),
            "ch4_fraction": np.full(t.size, 0.62),
            "alkalinity_total": alk,
            "vfa_total": vfa,
            "tan": np.full(t.size, 1.2),
            "cod_total": np.full(t.size, 40.0),
            "vfa_ac": 0.6 * vfa,
            "vfa_pro": 0.2 * vfa,
            "vfa_bu": 0.1 * vfa,
            "vfa_va": 0.05 * vfa,
            "h2_ppm": np.full(t.size, 12.0),
            "vs": np.full(t.size, 25.0),
            "ts": np.full(t.size, 33.0),
            "vfa_titrimetric": fos_titrimetric,
            "fos_tac": fos_titrimetric / alk,
            "fos_tac_true_vfa": vfa / alk,
        },
    )


def _sawtooth_channels(n_days: int, period: int = 8, high: float = 3.0) -> TruthChannels:
    """A run whose true VFA repeatedly departs from its own recent history.

    A single step raises the overload flag only until the trailing median catches up. A
    sawtooth keeps departing, so the flag fires at a steady rate over a long horizon —
    which is what a test of the *rate* needs.
    """
    channels = _flat_channels(n_days)
    t = channels.t
    vfa = np.where((np.arange(t.size) % period) < 1, high, 1.0)
    alk = channels["alkalinity_total"]
    fos_titrimetric = 0.7 + 0.3 * vfa
    series = {name: channels[name] for name in channels.names}
    series.update(
        {
            "vfa_total": vfa,
            "vfa_ac": 0.6 * vfa,
            "vfa_pro": 0.2 * vfa,
            "vfa_bu": 0.1 * vfa,
            "vfa_va": 0.05 * vfa,
            "vfa_titrimetric": fos_titrimetric,
            "fos_tac": fos_titrimetric / alk,
            "fos_tac_true_vfa": vfa / alk,
        }
    )
    return TruthChannels(t, series)


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
    # resolved per sensor: the same probe is described differently at each tier. NO cell
    # departs from its tier rate - the one measured dropout is a plant-level correlated
    # process and lives in `historian`, not here (lead's ruling 2026-09-03).
    for tier in "ABC":
        for kind in ("online", "lab"):
            model = policy.model_for(tier, kind)
            assert model.base_rate == policy.base_rate_by_tier[tier], (tier, kind)
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
    lost_lab = {}
    for tier in "ABC":
        record = observe(channels, config, tier, seed=5)
        lost[tier] = int(record["ph"].missing.sum()) + int(record["gas_flow"].missing.sum())
        if tier != "A":
            lost_lab[tier] = int(record["alkalinity"].missing.sum()) + int(
                record["cod_total"].missing.sum()
            )
        # the laboratory turnaround is the tier's, and online instruments report at once
        assert np.all(record["ph"].report_t == record["ph"].sample_t)
        if tier != "A":
            weekly = record["alkalinity"]
            assert np.all(weekly.report_t - weekly.sample_t == config.tiers[tier].lab_turnaround_d)
    assert lost["A"] > lost["B"] > lost["C"] > 0
    # the per-sensor structure is 8 %/2 %, and each tier's shared historian outage adds on
    # top, so the online ratio is the composition of the two: 1-(1-.08)(1-.010) over
    # 1-(1-.02)(1-.000966) = 8.92 %/2.10 % = 4.25, not the bare 4.0
    per, shared = config.missingness.base_rate_by_tier, config.historian.rate_by_tier

    def total(tier: str) -> float:
        return 1.0 - (1.0 - per[tier]) * (1.0 - shared[tier])

    assert lost["A"] / lost["C"] == pytest.approx(total("A") / total("C"), rel=0.25)
    # and the laboratory assays, which never pass through the historian, keep the bare
    # assumed structure exactly: 4 % against 2 %
    assert lost_lab["B"] / lost_lab["C"] == pytest.approx(2.0, rel=0.35)


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


def test_the_committed_window_rederives_the_anchored_noise_offline(config):
    """The anchored NOISE comes out of a committed file, so a fresh clone can check it.

    The 88.8 MB SCADA parent is git-ignored, which left
    ``test_anchored_sensor_values_are_rederived_from_the_scada_file`` skipped on every
    machine that had not fetched it - an anchor nobody verifies. The 60-day extract
    (days 240-300, chosen because it reproduces both noise values inside the tolerances
    that test already uses) is committed under ODC-By with its attribution, so the same
    two assertions run everywhere.
    """
    temp = scada_noise_statistics("D1_TEMPERATURE", path=SCADA_WINDOW_FILE)
    gas = scada_noise_statistics("Biogas", path=SCADA_WINDOW_FILE)
    assert temp.n == gas.n == 86_400  # 60 days at one minute, nothing dropped in this window
    assert config.sensors["temperature"].noise.sd_abs == pytest.approx(
        temp.noise_sd * DEGF_TO_K, abs=0.005
    )
    assert config.sensors["gas_flow"].noise.cv == pytest.approx(gas.noise_cv, abs=0.003)
    # and it agrees with the full record it was cut from, which is the point of choosing
    # this window rather than a convenient one
    full = json.loads(SCADA_STATISTICS_FILE.read_text(encoding="utf-8"))["full_record"]
    assert temp.noise_sd == pytest.approx(full["channels"]["D1_TEMPERATURE"]["noise_sd"], rel=0.01)
    assert gas.noise_cv == pytest.approx(full["channels"]["Biogas"]["noise_cv"], rel=0.10)
    # what the window cannot carry is said out loud rather than quietly asserted away:
    # a 60-day window holds no stuck run of 10+ minutes at all
    assert temp.flatline_fraction == 0.0 and gas.flatline_fraction == 0.0
    assert full["channels"]["D1_TEMPERATURE"]["flatline_fraction"] > 0.0


def test_the_config_matches_the_recorded_full_record_statistics(config):
    """Every anchored spec equals the committed derivation of the full SCADA year."""
    recorded = json.loads(SCADA_STATISTICS_FILE.read_text(encoding="utf-8"))
    channels = recorded["full_record"]["channels"]
    temp, gas = channels["D1_TEMPERATURE"], channels["Biogas"]
    assert recorded["source"]["file"] == "SCADA-raw.csv" and len(recorded["source"]["sha256"]) == 64
    assert config.sensors["temperature"].noise.sd_abs == pytest.approx(
        temp["noise_sd"] * DEGF_TO_K, abs=0.005
    )
    assert config.sensors["gas_flow"].noise.cv == pytest.approx(gas["noise_cv"], abs=0.003)
    for name, stats in (("temperature", temp), ("gas_flow", gas)):
        spec = config.sensors[name]
        assert spec.flatline is not None
        declared = spec.flatline.hazard_per_d * spec.flatline.mean_duration_d
        assert declared == pytest.approx(stats["flatline_fraction"], rel=0.25), name
    # the temperature saturation range is the data dictionary's, and its floor is reached
    saturation = config.sensors["temperature"].saturation
    assert saturation is not None
    assert saturation.low == pytest.approx((85.0 - 32.0) * DEGF_TO_K + 273.15, abs=1e-2)
    assert saturation.high == pytest.approx((150.0 - 32.0) * DEGF_TO_K + 273.15, abs=1e-2)


def test_the_measured_dropout_drives_a_correlated_plant_level_process(config):
    """The measured rate belongs to the process it describes, not to a per-sensor rate.

    Whole ROWS are missing from the SCADA record, so both online channels lose exactly the
    same minutes. Carried as an independent per-sensor rate p, two online sensors would
    lose the same sample with probability p^2 = 9.3e-7; in the record it is 1. This asserts
    the number went to the shared process and that the shared process really is shared.
    """
    recorded = json.loads(SCADA_STATISTICS_FILE.read_text(encoding="utf-8"))
    gaps = recorded["full_record"]["row_gaps"]
    assert gaps["n_gaps"] == 19 and gaps["span_d"] == pytest.approx(347.8, abs=0.1)
    historian = config.historian
    assert historian.measured_tiers == ("C",)
    assert historian.rate_by_tier["C"] == pytest.approx(gaps["missing_minute_fraction"], abs=5e-5)
    assert len(historian.gap_lengths_min) == gaps["n_gaps"]
    assert max(historian.gap_lengths_min) == pytest.approx(421.0)
    # the per-sensor policy is untouched: every tier and kind still resolves to its own rate
    policy = config.missingness
    for tier in "ABC":
        for kind in ("online", "lab"):
            assert policy.model_for(tier, kind).base_rate == policy.base_rate_by_tier[tier]

    # ---- the property that matters: online losses are CORRELATED, laboratory ones are not
    channels = _flat_channels(n_days=3_000)
    only_outages = config.model_copy(
        update={
            "missingness": policy.model_copy(
                update={"base_rate_by_tier": dict.fromkeys("ABC", 0.0)}
            )
        }
    )
    record = observe(channels, only_outages, "C", seed=0)
    a, b = record["temperature"].missing, record["gas_flow"].missing
    assert a.sum() > 0, "no outage fired; the test would be vacuous"
    np.testing.assert_array_equal(a, b)  # the same days, not merely the same rate
    # a laboratory assay does not pass through the historian at all
    assert record["alkalinity"].missing.sum() == 0
    # realised rate is the declared one (every observed outage is under a day, so an
    # outage costs exactly the sample it lands on)
    assert a.mean() == pytest.approx(historian.rate_by_tier["C"], rel=0.6)

    # ---- and against the independent alternative, which is what the ruling rejected
    p = historian.rate_by_tier["C"]
    joint_if_independent = p * p
    assert float((a & b).mean()) > 100.0 * joint_if_independent


def test_the_two_missingness_processes_compose_without_replacing_each_other(config):
    """Per-sensor independent losses and shared outages are additive, not alternatives."""
    channels = _flat_channels(n_days=4_000)
    policy = config.missingness
    per_sensor_only = config.model_copy(
        update={
            "historian": config.historian.model_copy(
                update={"rate_by_tier": dict.fromkeys("ABC", 0.0)}
            )
        }
    )
    both = observe(channels, config, "A", seed=3)["gas_flow"].missing
    alone = observe(channels, per_sensor_only, "A", seed=3)["gas_flow"].missing
    # the historian only ever ADDS losses; it never rescues a sample the sensor lost
    assert bool((alone & ~both).sum() == 0)
    assert both.sum() > alone.sum()
    # and the total is the independent composition of the two rates
    per_sensor = policy.base_rate_by_tier["A"]
    shared = config.historian.rate_by_tier["A"]
    expected = 1.0 - (1.0 - per_sensor) * (1.0 - shared)
    assert both.mean() == pytest.approx(expected, rel=0.15)


def test_the_effective_online_loss_is_the_recorded_composite(config):
    """The lead accepted the composite totals as the effective loss; they are recorded here.

    Adding the shared historian process on top of the frozen per-sensor rates raises an
    online sensor's unconditional loss from 8/4/2 % to 8.92/4.48/2.09 %. The lead's ruling
    of 2026-09-03 accepts those as the effective figures and explicitly does NOT
    renormalise the per-sensor rates back down — renormalising would make the historian
    free, which is the opposite of modelling it. This pins both halves: the declared
    inputs, and the loss a run actually shows.
    """
    per = config.missingness.base_rate_by_tier
    shared = config.historian.rate_by_tier
    assert [per[t] for t in "ABC"] == [0.08, 0.04, 0.02]  # frozen, unchanged
    expected = {t: 1.0 - (1.0 - per[t]) * (1.0 - shared[t]) for t in "ABC"}
    assert expected["A"] == pytest.approx(0.0892, abs=5e-5)
    assert expected["B"] == pytest.approx(0.0448, abs=5e-5)
    assert expected["C"] == pytest.approx(0.020947, abs=5e-5)
    # and a run loses at that rate, not at the per-sensor rate
    channels = _flat_channels(n_days=6_000)
    for tier in "ABC":
        record = observe(channels, config, tier, seed=11)
        online = record["gas_flow"].missing.mean()
        assert online == pytest.approx(expected[tier], rel=0.12), tier
        assert online > per[tier] * 0.98, (tier, "the shared process must add, not replace")
    # a laboratory assay never passes through the historian: it loses the bare tier rate.
    # A weekly assay over 6,000 d is ~860 samples, so the realised fraction of a 2 % rate
    # has a standard deviation of ~0.0048 -- the former tolerance (rel 0.25, i.e. +/- 0.005)
    # was one sigma, and the 2026-09-12 re-keying of the sensor streams (blocker 2, option
    # b) landed this seed at 0.0256, 1.2 sigma high. The band is the binomial three-sigma
    # one, which still fails a lab assay that lost at the online composite (0.0209 is not
    # distinguishable from 0.02 at this sample size, so the claim this makes is "the bare
    # rate, not more": a doubled rate fails it).
    lab_series = observe(channels, config, "C", seed=11)["alkalinity"].missing
    lab, n_lab = lab_series.mean(), lab_series.size
    sigma = (per["C"] * (1.0 - per["C"]) / n_lab) ** 0.5
    assert abs(lab - per["C"]) <= 3.0 * sigma, (lab, per["C"], n_lab)
    assert lab < 2.0 * per["C"]


def test_a_historian_rate_must_cover_every_tier_and_carry_its_lengths(config):
    """The outage process is declared completely or not at all."""
    raw = config.historian.model_dump()
    with pytest.raises(ValidationError, match="must cover tiers A, B and C"):
        HistorianDropout.model_validate(raw | {"rate_by_tier": {"A": 0.01, "B": 0.005}})
    with pytest.raises(ValidationError, match="at least one observed outage length"):
        HistorianDropout.model_validate(raw | {"gap_lengths_min": ()})
    with pytest.raises(ValidationError, match=r"literal_error|unknown tiers"):
        HistorianDropout.model_validate(raw | {"measured_tiers": ("D",)})
    # a tier whose rate is zero is legal: it means the plant has no shared outage process
    silent = HistorianDropout.model_validate(raw | {"rate_by_tier": dict.fromkeys("ABC", 0.0)})
    t = np.arange(500.0)
    lost = historian_outages(silent, "C", t, np.random.default_rng(0))
    assert not lost.any()


@pytest.mark.skipif(not SCADA_FILE.exists(), reason="Muscatine SCADA file not fetched")
def test_the_recorded_statistics_are_the_full_files_own(config):
    """When the parent is present, the committed JSON is exactly what it yields."""
    recorded = json.loads(SCADA_STATISTICS_FILE.read_text(encoding="utf-8"))
    for column, values in recorded["full_record"]["channels"].items():
        derived = scada_noise_statistics(column)
        for field, value in values.items():
            assert getattr(derived, field) == pytest.approx(value, rel=1e-9), (column, field)
    gaps = scada_row_gap_statistics()
    for field, value in recorded["full_record"]["row_gaps"].items():
        assert getattr(gaps, field) == pytest.approx(value, rel=1e-9), field


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
    # flatline occupancy: the REALISED mask must reproduce the measured fraction, not the
    # declared product. The mask lasts max(1, round(duration/dt)) samples, so a declared
    # sub-interval duration is rounded up and the two diverge (a 0.4 d episode on a daily
    # sensor realised 2.5x the anchored occupancy until the schema started rejecting it).
    channels = _flat_channels(n_days=20_000)
    quiet = _without_missingness(config)  # the flags are masked by ~missing; isolate them
    for name, stats in (("temperature", temp), ("gas_flow", gas)):
        spec = config.sensors[name]
        assert spec.flatline is not None
        assert spec.flatline.mean_duration_d >= spec.sampling_interval_d
        declared = spec.flatline.hazard_per_d * spec.flatline.mean_duration_d
        assert declared == pytest.approx(stats.flatline_fraction, rel=0.25), name
        held = sum(
            int(observe(channels, quiet, "A", seed=seed)[name].flatlined.sum()) for seed in range(5)
        )
        realised = held / (5 * channels.t.size)
        assert realised == pytest.approx(declared, rel=0.30), (name, realised, declared)
    # the file's CELLS really are pre-cleaned - but its ROWS are not, and those dropouts
    # are what anchors the Tier C online missing rate (lead's ruling 2026-09-03)
    assert temp.missing_fraction == 0.0 and gas.missing_fraction == 0.0
    gaps = scada_row_gap_statistics()
    assert gaps.n_gaps == 19 and 0.0009 < gaps.missing_minute_fraction < 0.0011
    # the measured figure drives the plant-level outage process, not a per-sensor rate
    assert config.historian.rate_by_tier["C"] == pytest.approx(
        gaps.missing_minute_fraction, abs=5e-5
    )
    assert (
        config.missingness.model_for("C", "online").base_rate
        == (config.missingness.base_rate_by_tier["C"])
    )


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
    # VFA as acetic-acid equivalent, against a hand calculation done ONCE, off-line, and
    # written down as a literal: 1 kg COD/m3 of acetate is 1/64 kmol/m3 (acetic acid takes
    # 2 O2 per molecule: C2H4O2 + 2 O2 -> 2 CO2 + 2 H2O, so 64 kg COD/kmol), and at
    # 60.05 kg/kmol that is 0.93828 kg/m3 as acetic acid. Restating the implementation
    # here instead would pass under any global scale error, which is how a factor of 1000
    # survived into the branch (decisions log, "VFA channels were 1000x too small").
    cod_per_kg_acetic = 64.0 / M_ACETIC
    assert cod_per_kg_acetic == pytest.approx(1.0658, abs=1e-4)  # kg COD per kg acetic acid
    ac_cod = result.y[6, i]  # S_ac, kg COD/m3
    assert channels["vfa_ac"][i] == pytest.approx(ac_cod * 0.9382812, rel=1e-6)
    assert channels["vfa_ac"][i] == pytest.approx(ac_cod / 1.0658, rel=1e-3)
    # and the scale is the anchor's: the Muscatine columns are mg/L, i.e. kg/m3 at 5.04
    # (alkalinity) and 1.18 (VFA) at the median, so a healthy digester's channels are
    # units, not micro-units. A digester whose total VFA reads 1e-4 kg/m3 could never
    # raise the 0.40 overload flag, which is exactly the failure this pins.
    assert 0.5 < channels["alkalinity_total"][i] < 20.0
    assert 1e-3 < channels["vfa_total"][i] < 10.0
    # gas conventions differ and both are reported
    assert channels["q_gas_stp_dry"][i] != channels["q_gas_operating"][i]
    assert 0.0 < channels["ch4_fraction"][i] < 1.0
    assert channels["temperature"][0] == geometry.T_op
    # solids need the influent's inert equivalent; without it they are absent
    assert "vs" not in channels and "ts" not in channels


def test_every_extension_component_is_classified_for_cod_and_solids():
    """A new extension component must be placed deliberately, not silently dropped.

    Extension components are appended after the gas states, so the 26-state liquid slice
    misses them: `cod_total` used to omit `X_sao` and `ts` to omit precipitated calcite.
    Both are negligible at a healthy steady state (X_sao ~ 1e-7 kg COD/m3 at Plant B's
    median feed) and both become the signal in the scenarios they belong to — SAO biomass
    growing IS the Level-5 ammonia signature. This asserts that every component the
    extensions config declares is in exactly one of the three tables, so adding one to the
    config without deciding what it contributes fails here rather than vanishing.
    """
    from sim.adm1 import load_extensions
    from sim.observation.channels import (
        EXTENSION_COD_PER_VS,
        EXTENSION_INORGANIC_SOLIDS,
        EXTENSION_NO_SOLIDS,
    )

    declared = {
        component.name: component
        for extension in load_extensions().extensions.values()
        for component in extension.components
    }
    assert {"X_sao", "S_ca", "X_caco3"} <= set(declared)
    tables = (set(EXTENSION_COD_PER_VS), set(EXTENSION_INORGANIC_SOLIDS), set(EXTENSION_NO_SOLIDS))
    for name in declared:
        hits = [name in table for table in tables]
        assert sum(hits) == 1, f"{name} is in {sum(hits)} classification tables, not exactly 1"
    for table in tables:
        assert table <= set(declared), sorted(table - set(declared))
    # the classification follows the config's own declared COD content
    for name, equivalent in EXTENSION_COD_PER_VS.items():
        assert float(declared[name].cod) > 0.0, name
        assert equivalent > 1.0  # kg COD per kg VS, never below unity for organic matter
    for name in EXTENSION_INORGANIC_SOLIDS:
        assert float(declared[name].cod) == 0.0, name


def test_extension_biomass_and_precipitate_reach_the_solids_and_cod_channels(
    adm1_params, rj2006_state
):
    """X_sao counts as COD and as VS; calcite counts as TS and not as VS."""
    from sim.adm1 import compile_extended, load_extensions, load_matrix, load_solver_config
    from sim.adm1.extensions import extended_state, simulate_extended
    from sim.influent import constant_influent, load_feed_fractionation, nominal_mass_rates
    from sim.plants import declared_geometry, load_all_plants

    catalogue = load_feed_fractionation()
    plant = load_all_plants()["C"]
    rates = nominal_mass_rates(plant, catalogue)
    geometry = declared_geometry(plant)
    model = compile_extended(
        adm1_params,
        geometry,
        load_matrix(),
        load_solver_config(),
        load_extensions(),
        ("sao", "precipitation"),
    )
    sao, caco3 = 0.5, 0.02  # kg COD/m3 and kmol/m3, both far above a steady-state trace
    result = simulate_extended(
        y0=extended_state(model, rj2006_state, {"X_sao": sao, "X_caco3": caco3}),
        influent=constant_influent(catalogue, rates),
        model=model,
        t_span=(0.0, 1e-6),  # essentially the initial state: nothing reacts
        t_eval=np.array([0.0]),
    )
    ash = np.zeros(1)
    with_ext = channel_series(result, T_op=geometry.T_op, inert_cod_equivalent=1.2, ash=ash)
    # the same run read as if the extension states were absent
    bare = result.y.copy()
    bare[model.index("X_sao"), :] = 0.0
    bare[model.index("X_caco3"), :] = 0.0
    stripped = channel_series(
        type(result)(
            t=result.t,
            y=bare,
            state_names=result.state_names,
            derived=result.derived,
            success=result.success,
            message=result.message,
            stats=result.stats,
        ),
        T_op=geometry.T_op,
        inert_cod_equivalent=1.2,
        ash=ash,
    )
    assert with_ext["cod_total"][0] - stripped["cod_total"][0] == pytest.approx(sao)
    assert with_ext["vs"][0] - stripped["vs"][0] == pytest.approx(sao / 1.42, rel=1e-9)
    assert with_ext["ts"][0] - stripped["ts"][0] == pytest.approx(sao / 1.42 + caco3 * 100.09)
    # calcite is inorganic: it moves TS but not VS
    assert (with_ext["ts"][0] - with_ext["vs"][0]) == pytest.approx(caco3 * 100.09)


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


@pytest.mark.skipif(not DAILY_FILE.exists(), reason="Muscatine daily file not fetched")
def test_fos_tac_is_on_the_anchor_s_own_scale_and_its_thresholds_are_reachable(config):
    """The channel is kg/m3 over kg CaCO3/m3, the plant's own units — and 0.40 is attainable.

    Two claims the branch made and did not test. First, that our FOS/TAC is the ratio the
    plant reports: the anchor's `Dig1-VFA_mgL / Dig1-alk_mgL` reproduces its own
    `Dig1-FOS-TAC` column, and our channel is that same ratio on the same units, so feeding
    the plant's own VFA and alkalinity through the channel formula must return the plant's
    own column. Second, that the 0.40 overload threshold is reachable at all: a VFA of
    1.0 kg/m3 against the anchor's median alkalinity crosses it, and the anchor's own VFA
    is above 1.0 on more than a third of its days, so the threshold describes a state the
    plant really visits. With the VFA channel 1000x too small (as it was) neither held: a
    souring digester at 10 kg COD/m3 of acetate reached FOS/TAC 0.003 and the flag could
    never fire, silently disabling conditional missingness.
    """
    records = load_daily()
    vfa = np.array([r.dig1_vfa_kg_m3 for r in records if r.dig1_vfa_kg_m3 is not None])
    alk = np.array([r.dig1_alk_kg_caco3_m3 for r in records if r.dig1_alk_kg_caco3_m3 is not None])
    assert vfa.size > 800 and alk.size > 900
    # the plant's own units are ours: kg/m3 and kg CaCO3/m3, order unity
    assert 1.0 < float(np.median(vfa)) < 1.5
    assert 4.5 < float(np.median(alk)) < 5.5
    # our channel's arithmetic on the plant's own numbers gives the plant's own column
    ratios = np.array(
        [
            r.dig1_vfa_kg_m3 / r.dig1_alk_kg_caco3_m3
            for r in records
            if r.dig1_vfa_kg_m3 is not None and r.dig1_alk_kg_caco3_m3 is not None
        ]
    )
    assert float(np.median(ratios)) == pytest.approx(0.23, abs=0.02)
    # and the thresholds sit inside the distribution the plant actually visits
    overload = config.conditions.fos_tac_overload
    assert 0.05 < float((ratios > overload).mean()) < 0.15, "0.40 should be ~the 92nd percentile"
    assert float((ratios > config.conditions.fos_tac_foaming).mean()) > 0.15
    # a VFA the anchor exceeds on a third of its days already crosses the overload flag
    assert 1.0 / float(np.median(alk)) < overload < 3.0 / float(np.median(alk))
    assert float((vfa > 1.0).mean()) > 0.3


def test_the_titrimetric_transfer_function_is_declared_chemistry(config):
    """The lead's ruling A (2026-09-09): no fitted parameter, and the constants are checkable.

    Every number here is derived from the truth model's own equilibrium constants, so the
    test states them and would fail if the transfer function quietly acquired a fitted
    factor or a private constant of its own. The values are the ones the ruling gives.
    """
    import math

    from sim.adm1.defaults import load_parameters
    from sim.adm1.physchem import temperature_corrected
    from sim.observation.channels import (
        TITRIMETRIC_KAPPA,
        TITRATION_pH_LOWER,
        TITRATION_pH_UPPER,
        _acid_fraction,
        titrimetric_fos,
    )

    assert TITRIMETRIC_KAPPA == 1.0, "kappa is frozen: pure chemistry, nothing fitted"
    assert (TITRATION_pH_UPPER, TITRATION_pH_LOWER) == (5.0, 4.4)

    physchem = load_parameters().physchem
    T = 308.48  # Plant B's operating temperature
    tc = temperature_corrected(physchem, T)
    assert -math.log10(tc.K_a_ac) == pytest.approx(4.760, abs=0.001)
    assert -math.log10(tc.K_a_co2) == pytest.approx(6.305, abs=0.001)

    f_ac = _acid_fraction(tc.K_a_ac, 5.0) - _acid_fraction(tc.K_a_ac, 4.4)
    assert f_ac == pytest.approx(0.3309, abs=0.0002)
    assert 1.0 / f_ac == pytest.approx(3.02, abs=0.01)  # the Nordmann formula's own scale-up
    carry = _acid_fraction(tc.K_a_co2, 5.0) - _acid_fraction(tc.K_a_co2, 4.4)
    assert carry == pytest.approx(0.0349, abs=0.0002)

    # A healthy Plant B: S_IC ~0.15 kmol C/m3 and true acetate ~0.09 kg/m3, i.e. 0.0015
    # kmol/m3 -- the carry-over term then dominates the reading, which is the finding.
    n = 5
    s_ic = np.full(n, 0.15)
    acetate_kmol = 0.0015
    vfa = {
        "S_ac": np.full(n, acetate_kmol),
        "S_pro": np.zeros(n),
        "S_bu": np.zeros(n),
        "S_va": np.zeros(n),
    }
    fos = titrimetric_fos(s_ic, vfa, T, physchem)
    only_carry = titrimetric_fos(s_ic, {k: np.zeros(n) for k in vfa}, T, physchem)
    share = float(only_carry[0] / fos[0])
    assert 0.85 < share < 0.95, share  # the ruling's 86-90 %

    # it over-reads true VFA severalfold, which is the whole point
    true_vfa = acetate_kmol * M_ACETIC
    assert fos[0] > 5.0 * true_vfa, (fos[0], true_vfa)

    # and it is linear in each contribution, so a zero digester reads only the free protons
    empty = titrimetric_fos(np.zeros(n), {k: np.zeros(n) for k in vfa}, T, physchem)
    assert 0.0 < float(empty[0]) < 0.01, float(empty[0])


def test_the_true_vfa_channel_is_never_what_a_sensor_reads(config):
    """True VFA stays hidden truth (lead's ruling A): the sensor reads the titration."""
    assert config.sensors["vfa_total"].channel == "vfa_titrimetric"
    reading_true_vfa = [
        name for name, spec in config.sensors.items() if spec.channel == "vfa_total"
    ]
    assert not reading_true_vfa, reading_true_vfa
    # and no sensor reads the true-VFA ratio either
    assert not [n for n, spec in config.sensors.items() if spec.channel == "fos_tac_true_vfa"]


def test_the_overload_threshold_is_the_anchors_own_92nd_percentile(config):
    """The lead's ruling 4 (2026-09-09): 0.40 is percentile-matched, not transferred.

    The threshold used to be defended as "0.40 is about the 92nd percentile", which the test
    above checks only as a band (5-15 % of days above it) — a band wide enough that 0.35 or
    0.45 would also pass. The ruling makes the percentile itself the definition, so this
    recomputes it from the committed anchor file and pins it on **both** digesters.

    The anchor's FOS/TAC is titrimetric, which is the convention the threshold is matched
    in; our own `fos_tac` channel is a true-VFA ratio until the transfer function of ruling 3
    lands. That mismatch is the recorded open item, not something this test can close.

    Measured: Dig1 p92 = 0.402, Dig2 p92 = 0.408. The bound is 0.01, which is what the two
    digesters actually bracket — not the 0.005 a "to two decimal places" reading of the
    ruling would imply, because Dig2's 0.408 rounds to 0.41. Setting the bound to the
    measurement rather than to the claim is the point of having the test at all.
    """
    records = load_daily()
    for digester in (1, 2):
        v = np.array([getattr(r, f"dig{digester}_vfa_kg_m3") for r in records], dtype=float)
        a = np.array([getattr(r, f"dig{digester}_alk_kg_caco3_m3") for r in records], dtype=float)
        ok = np.isfinite(v) & np.isfinite(a) & (a > 0.0)
        assert int(ok.sum()) == 861, (digester, int(ok.sum()))
        ratios = v[ok] / a[ok]
        p92 = float(np.percentile(ratios, 92))
        assert p92 == pytest.approx(config.conditions.fos_tac_overload, abs=0.01), (
            digester,
            p92,
        )
    # the match is to the 92nd specifically: neighbouring percentiles are further away, so
    # this cannot be satisfied by any threshold that happens to sit in the distribution
    v = np.array([r.dig1_vfa_kg_m3 for r in records], dtype=float)
    a = np.array([r.dig1_alk_kg_caco3_m3 for r in records], dtype=float)
    ok = np.isfinite(v) & np.isfinite(a) & (a > 0.0)
    ratios = v[ok] / a[ok]
    target = config.conditions.fos_tac_overload
    best = min(range(50, 100), key=lambda q: abs(float(np.percentile(ratios, q)) - target))
    assert best == 92, best


def test_the_trailing_median_matches_its_own_definition_on_an_irregular_grid():
    """The windowed median is computed by binary search; it must equal the plain definition.

    The original built a boolean mask over the whole series per sample, which is O(n^2) and
    dominated the suite's runtime once the missingness tests needed 6,000- and 20,000-day
    horizons (20,000 days: 0.47 s now). This checks the fast form against the definition it
    replaced, on an *irregular* grid with a real gas cycle — a uniform grid would hide an
    off-by-one in the window bounds.
    """
    rng = np.random.default_rng(0)
    t = np.sort(rng.uniform(0.0, 400.0, 800))
    t[0] = 0.0
    gas = 1500.0 + 600.0 * np.sin(t / 7.0) + rng.normal(0.0, 100.0, t.size)
    fos = 0.2 + 0.3 * np.sin(t / 23.0)
    vfa = 1.0 + 0.8 * np.sin(t / 11.0) + 0.3 * rng.normal(0.0, 1.0, t.size)
    channels = TruthChannels(
        t, {"fos_tac": fos, "q_gas_stp_dry": gas, "vfa_total": np.maximum(vfa, 0.05)}
    )
    window, vfa_window = 14.0, 30.0
    overload, foaming = condition_flags(
        channels,
        vfa_surge_ratio=2.0,
        vfa_median_window_d=vfa_window,
        gas_surge_ratio=1.35,
        gas_median_window_d=window,
        foaming_vfa_ratio=1.0,
    )

    # both windows are trailing and EXCLUDE the current sample (ruling B3 made the gas one
    # match the overload one), so the plain definition is written out once for each series
    def plain(values: np.ndarray, w: float) -> np.ndarray:
        return np.array(
            [
                np.median(values[(t >= ti - w) & (t < ti)]) if (t < ti).any() else values[i]
                for i, ti in enumerate(t)
            ]
        )

    v = np.maximum(vfa, 0.05)
    vfa_reference = plain(v, vfa_window)
    gas_reference = plain(gas, window)
    np.testing.assert_array_equal(overload, v > 2.0 * vfa_reference)
    np.testing.assert_array_equal(foaming, (gas > 1.35 * gas_reference) & (v > vfa_reference))
    assert foaming.any() and overload.any()  # both flags are exercised, not trivially empty
    # and the reported ratio takes no part in either: the same flags without the channel
    without = TruthChannels(t, {"q_gas_stp_dry": gas, "vfa_total": v})
    again = condition_flags(
        without,
        vfa_surge_ratio=2.0,
        vfa_median_window_d=vfa_window,
        gas_surge_ratio=1.35,
        gas_median_window_d=window,
        foaming_vfa_ratio=1.0,
    )
    np.testing.assert_array_equal(again[0], overload)
    np.testing.assert_array_equal(again[1], foaming)


def test_the_overload_reference_excludes_the_current_sample():
    """A large excursion must not be allowed to drag its own reference up and mask itself.

    With the current day included, a spike enters the median it is being compared against.
    On a short window that is enough to hide a real transient, which is precisely the state
    conditional missingness exists to correlate with.
    """
    from sim.observation.channels import trailing_median

    t = np.arange(10.0)
    values = np.ones(10)
    values[4] = values[5] = 10.0  # a transient lasting more than one sample
    reference = trailing_median(values, t, window_d=3.0)
    assert reference[5] == pytest.approx(1.0), reference[5]  # the spike is not in its own median
    assert reference[0] == pytest.approx(values[0])  # no history: its own value, ratio 1

    # and this is not a distinction without a difference: with the current sample INCLUDED
    # the reference at index 5 would be 5.5 rather than 1.0, and the excursion would be
    # compared against itself. A one-sample spike would survive either way (it cannot move
    # a median it is one of six values in) — a sustained transient is what self-masks, and
    # a sustained transient is exactly what conditional missingness is about.
    window = (t >= t[5] - 3.0) & (t <= t[5])
    including = float(np.median(values[window]))
    assert including == pytest.approx(5.5), including
    assert including > 2.0 * reference[5], "inclusion would hide a 10x excursion outright"


def _flags(channels, config):
    """Condition flags at the configured thresholds."""
    return condition_flags(
        channels,
        vfa_surge_ratio=config.conditions.vfa_surge_ratio,
        vfa_median_window_d=config.conditions.vfa_median_window_d,
        gas_surge_ratio=config.conditions.gas_surge_ratio,
        gas_median_window_d=config.conditions.gas_median_window_d,
        foaming_vfa_ratio=config.conditions.foaming_vfa_ratio,
    )


def test_condition_flags_use_only_past_history(config):
    """The overload flag is a departure from recent history, and it never sees the future."""
    channels = _flat_channels(stress_from=100)
    overload, foaming = _flags(channels, config)
    assert not overload[:100].any(), "nothing departs from history before the step"
    assert overload[100], "the step itself is a 3x departure and must fire"
    # ... and it stops firing once the trailing median has caught up, which is the property:
    # a digester that has sat at a high VFA for a month is no longer in a transient
    assert not overload[-1]
    assert not foaming.any()  # a flat gas rate never surges above its own median


def test_the_foaming_flag_needs_a_gas_surge_and_rising_vfa_together(config):
    """Ruling B3 (2026-09-10): foaming is a gas surge WHILE the hidden VFA is above its median.

    Three windows on one record. The gas doubles while the VFA is stepping up: fires. The
    gas doubles again a month later, when the VFA has sat at its new level long enough to
    BE the median: does not fire, because a surge on a settled digester is a good day, not
    a foam. And the VFA step alone, on a flat gas rate, never fires (the test above).
    """
    ratio = config.conditions.gas_surge_ratio
    assert ratio == 1.80 and config.conditions.foaming_vfa_ratio == 1.00  # the ruling's values
    channels = _flat_channels(stress_from=100)
    t = channels.t
    gas = np.full(t.size, 1500.0)
    gas[100:105] = 3000.0  # 2.0x: above the 1.80x cut-off, while the VFA has just stepped
    gas[150:155] = 3000.0  # the same surge, once the VFA has been high for 50 days
    surged = TruthChannels(t, {**{k: channels[k] for k in channels.names}, "q_gas_stp_dry": gas})
    _, foaming = _flags(surged, config)
    assert foaming[100:105].all(), "gas surge + rising VFA is the foaming state"
    assert not foaming[:100].any()
    assert not foaming[150:155].any(), "a gas surge on a settled VFA is not foaming"
    assert not foaming[105:150].any()
    # the two conditions are separately necessary: drop either and the flag goes out
    calm_vfa = {k: surged[k] for k in surged.names}
    calm_vfa["vfa_total"] = np.ones(t.size)
    assert not _flags(TruthChannels(t, calm_vfa), config)[1].any()
    weak_gas = {k: surged[k] for k in surged.names}
    weak_gas["q_gas_stp_dry"] = np.where(gas > 1500.0, 1500.0 * (ratio - 0.01), 1500.0)
    assert not _flags(TruthChannels(t, weak_gas), config)[1].any()
    # the window is trailing and excludes the current day: a surge that persists past the
    # window is its own median and stops firing, exactly as the overload flag does
    long_gas = np.full(t.size, 1500.0)
    long_gas[100:] = 3000.0
    long = TruthChannels(t, {**{k: channels[k] for k in channels.names}, "q_gas_stp_dry": long_gas})
    _, foaming_long = _flags(long, config)
    assert foaming_long[100] and not foaming_long[-1]


def test_the_foaming_flag_reads_the_hidden_state_and_not_the_reported_ratio(config):
    """Ruling B3: the operator's 0.30 stays visible and unwired; the flag never reads it.

    The titrimetric FOS/TAC is pinned far above 0.30 with nothing else happening: no flag.
    Then it is pinned far below 0.30 while the gas surges and the hidden VFA rises: the flag
    fires anyway. A flag that read the ratio would do the opposite in both cases.
    """
    base = _flat_channels(n_days=120)
    t = base.t
    loud = {name: base[name] for name in base.names}
    loud["fos_tac"] = np.full(t.size, 5.0)
    assert not _flags(TruthChannels(t, loud), config)[1].any()

    quiet = {name: base[name] for name in base.names}
    quiet["fos_tac"] = np.full(t.size, 0.001)
    vfa = np.ones(t.size)
    vfa[60:63] = 1.5  # above its median, well under the 2.0x overload cut-off
    gas = np.full(t.size, 1500.0)
    gas[60:63] = 3000.0
    quiet["vfa_total"], quiet["q_gas_stp_dry"] = vfa, gas
    overload, foaming = _flags(TruthChannels(t, quiet), config)
    assert foaming[60:63].all() and foaming.sum() == 3
    assert not overload.any(), "foaming does not require the overload cut-off"
    # and the operator's threshold is still declared, for a workflow to read its record by
    assert config.conditions.fos_tac_foaming == 0.30


def test_the_overload_flag_reads_the_hidden_vfa_and_not_the_reported_ratio(config):
    """The lead's ruling B: the trigger is the process state, not the instrument reading.

    Constructed so the two disagree outright — the titrimetric FOS/TAC is pinned far above
    the operator threshold everywhere while true VFA is flat, and then true VFA surges while
    the reported ratio is pinned far below it. A flag that read the ratio would fire in the
    first case and not the second; the flag that reads the state does the opposite.
    """
    base = _flat_channels(n_days=120)
    t = base.t

    loud_reading = dict.fromkeys(())  # placeholder for clarity below
    loud_reading = {name: base[name] for name in base.names}
    loud_reading["fos_tac"] = np.full(t.size, 5.0)  # >> the 0.40 operator threshold
    overload, _ = _flags(TruthChannels(t, loud_reading), config)
    assert not overload.any(), "a reported ratio must not raise the flag by itself"

    quiet_reading = {name: base[name] for name in base.names}
    vfa = np.ones(t.size)
    vfa[60] = 4.0  # a genuine transient in the hidden state
    quiet_reading["vfa_total"] = vfa
    quiet_reading["fos_tac"] = np.full(t.size, 0.001)  # << the operator threshold
    overload2, _ = _flags(TruthChannels(t, quiet_reading), config)
    assert overload2[60], "a hidden transient must raise the flag whatever the reading says"
    assert overload2.sum() == 1


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


@pytest.mark.parametrize(
    ("name", "value", "discriminating"),
    [
        ("h2_offgas", 12.0, True),  # 1.8 ppm relative against a 1.0 ppm floor: comparable terms
        ("vfa_va", 0.05, False),  # the lead's 0.05 g/L floor dominates at valerate levels
    ],
)
def test_relative_and_absolute_noise_are_independent_draws(config, name, value, discriminating):
    """A sensor declaring both terms gets sqrt((v cv)^2 + sd_abs^2), not the correlated sum.

    Two sensors declare both a relative and an absolute term. The H2 cell is the one that
    *discriminates* between the two forms — its terms are comparable, so the correlated sum
    is 36 % larger than the independent one. Valerate's floor dominates at its own
    concentration (0.0075 relative against 0.05 absolute), so the two forms differ by only
    12 % there and the test checks the magnitude alone; it is included because the floor is
    exactly what the lead added, and a floor silently applied as a *relative* term or
    dropped entirely would fail here.
    """
    spec = config.sensors[name]
    assert spec.noise.cv > 0.0 and spec.noise.sd_abs > 0.0
    channels = _flat_channels(n_days=4000)
    assert channels[spec.channel][0] == value  # the synthetic truth this expectation assumes
    quiet = spec.model_copy(update={"drift": None, "saturation": None})
    cfg = _without_missingness(config).model_copy(
        update={"sensors": {**config.sensors, name: quiet}}
    )
    reported = observe(channels, cfg, "C", seed=17)[name].value
    independent = float(np.hypot(value * spec.noise.cv, spec.noise.sd_abs))
    correlated = value * spec.noise.cv + spec.noise.sd_abs
    assert reported.std() == pytest.approx(independent, rel=0.08)
    if discriminating:
        assert reported.std() < 0.9 * correlated  # the two are far enough apart to tell
    assert reported.mean() == pytest.approx(value, abs=0.15 * independent)


def test_drift_is_bounded_and_reset_by_recalibration(config):
    """The pH probe's random walk stays inside its bound and restarts at recalibration.

    The reset is measured as a **ratio of magnitudes over every boundary and eight seeds**,
    not asserted at four boundaries of one draw. A bounded random walk that is reset is one
    step from zero at a boundary and ``sqrt(30)`` steps from it just before the next, so the
    ratio is ~0.18; a walk that is *not* reset moves one step across a boundary and the
    ratio is ~1. The 0.4 bound discriminates between the two, and no realisation of the
    reset implementation lands near it — which the earlier "smaller than the sample before
    it, or below 0.02" form did not: a boundary step of 0.032 after a quiet 0.0009 is a
    correct reset and failed it.
    """
    channels = _flat_channels(n_days=400)
    spec = config.sensors["ph"]
    assert spec.drift is not None and spec.drift.recalibrated
    assert config.tiers["B"].recalibration_interval_d == 30.0  # the cadence is the tier's
    # isolate the drift: no noise, no fouling, no missingness
    quiet = spec.model_copy(update={"noise": NoiseModel(cv=0.0, sd_abs=1e-12), "fouling": None})
    cfg = _without_missingness(config).model_copy(
        update={"sensors": {**config.sensors, "ph": quiet}}
    )
    at_boundary: list[float] = []
    just_before: list[float] = []
    drifted = 0.0
    for seed in range(8):
        offset = observe(channels, cfg, "B", seed=seed)["ph"].value - 7.30
        assert np.abs(offset).max() <= spec.drift.bound + 1e-9
        drifted = max(drifted, float(np.abs(offset).max()))
        for boundary in range(30, 400, 30):
            at_boundary.append(abs(float(offset[boundary])))
            just_before.append(abs(float(offset[boundary - 1])))
    assert drifted > 0.01  # it does drift
    ratio = float(np.mean(at_boundary) / np.mean(just_before))
    assert ratio < 0.4, ratio  # ~0.18 when reset, ~1.0 when not
    # and the first sample after a boundary is one step from zero, never a month's walk
    step = spec.drift.sd_per_sqrt_d
    assert np.mean(at_boundary) < 1.5 * step, (np.mean(at_boundary), step)


def test_flatline_holds_the_previous_value_and_saturation_clips(config):
    """Pooled over twelve seeds: the temperature probe's flatline is a rare-event process.

    Its occupancy is the anchor's own 0.00077, so a single 3,000-day run contains a stuck
    episode only some of the time and a one-seed test is a coin toss on the stream, not a
    check of the hold.
    """
    channels = _flat_channels(n_days=3000)
    held_total = 0
    for seed in range(12):
        temp = observe(channels, config, "A", seed=seed)["temperature"]
        held = np.flatnonzero(temp.flatlined & ~temp.missing)
        held_total += held.size
        for i in held:
            if i > 0 and not temp.missing[i - 1]:
                assert temp.value[i] == pytest.approx(temp.value[i - 1])
    assert held_total > 0, "no flatline episode occurred at all; the hold was never exercised"
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


def test_a_saturation_flag_never_contradicts_its_own_reading(config):
    """A flatlined sample carries the held reading, so it must carry the held flag too.

    Saturation is a statement about the number the instrument reported. When a truth that
    steps in and out of the readable range meets a flatline episode, the pre-hold value
    could saturate while the value actually reported (the previous one) sits inside the
    range — the record would then tell a workflow the sensor hit its limit while showing it
    a number that did not. Forty seeds over a stepping truth produce 16 such samples if the
    flag is not held with the value.
    """
    spec = config.sensors["temperature"]
    high = spec.saturation.high
    base = _flat_channels(n_days=4000)
    stepped = np.where((np.arange(base.t.size) // 7) % 2 == 0, 311.0, 400.0)
    channels = TruthChannels(base.t, {**{k: base[k] for k in base.names}, "temperature": stepped})
    held = contradictions = 0
    for seed in range(40):
        series = observe(channels, config, "A", seed=seed)["temperature"]
        reported = ~series.missing
        held += int((series.flatlined & reported).sum())
        contradictions += int((series.saturated & reported & (series.value < high - 1e-9)).sum())
    assert held > 50  # the collision the test is about really happens
    assert contradictions == 0


def test_missingness_is_conditional_on_the_process_state(config):
    """The §6.1 property: gaps cluster in the stress window, so interpolation loses information.

    All three sensors here are online probes, so they also pass through the plant-level
    historian, whose loss is **unconditional**. The expected rates are therefore the
    composites ``1 - (1 - per_sensor)(1 - shared)``, not the per-sensor rates, and the
    expected ratio is the ratio of two composites — 3.67 at Tier B, not the bare overload
    multiplier of 4. Both expectations are derived from the config here rather than
    written down, because the earlier form compared the calm-window rate with the
    *per-sensor* 0.04 when the process actually loses 0.0448, and passed only because
    12 % happened to sit inside a 15 % tolerance.

    Pooled over twelve seeds, because the ratio is a ratio of two counts.

    **The stress window is a sawtooth, not a step.** Since the lead's ruling B of
    2026-09-09 the flag fires on a *departure from recent history*, so a step raises it only
    until the trailing median catches up — which is the intended behaviour (a digester that
    has sat at a high VFA for a month is not in a transient) and useless for measuring a
    rate. The second half of this run therefore departs repeatedly, and the calm/stressed
    split is taken from the flag itself rather than from the day index, so the test measures
    the loss rate *conditional on the flag* whatever fraction of days the flag happens to
    cover.
    """
    n_days, stress_from = 6000, 3000
    calm_part = _flat_channels(n_days=n_days)
    saw = _sawtooth_channels(n_days=n_days, period=8, high=3.0)
    series = {name: calm_part[name].copy() for name in calm_part.names}
    for name in series:
        series[name][stress_from:] = saw[name][stress_from:]
    channels = TruthChannels(calm_part.t, series)

    overload, _ = _flags(channels, config)
    assert not overload[:stress_from].any(), "the first half must be calm"
    stressed_fraction = float(overload[stress_from:].mean())
    assert 0.05 < stressed_fraction < 0.9, stressed_fraction  # the flag really fires there

    names = ("ph", "gas_flow", "ch4_fraction")
    lost_before = dict.fromkeys(names, 0)
    lost_after = dict.fromkeys(names, 0)
    seen_before = seen_after = 0
    for seed in range(12):
        record = observe(channels, config, "B", seed=seed)
        for name in names:
            series_ = record[name]
            idx = np.clip(
                np.searchsorted(channels.t, series_.sample_t, side="right") - 1,
                0,
                channels.t.size - 1,
            )
            flagged = overload[idx]
            lost_before[name] += int(series_.missing[~flagged].sum())
            lost_after[name] += int(series_.missing[flagged].sum())
            if name == "ph":
                seen_before += int((~flagged).sum())
                seen_after += int(flagged.sum())
    shared = config.historian.rate_by_tier["B"]

    def composite(per_sensor: float) -> float:
        """The loss an online sensor actually shows: its own, plus the shared outage."""
        return 1.0 - (1.0 - per_sensor) * (1.0 - shared)

    for name in names:
        before = lost_before[name] / seen_before
        after = lost_after[name] / seen_after
        spec = config.missingness.model_for("B", config.sensors[name].kind)
        multiplier = spec.stress_multipliers["overload"]
        expected_before = composite(spec.base_rate)
        expected_after = composite(min(spec.base_rate * multiplier, 1.0))
        assert lost_before[name] > 300 and lost_after[name] > 200, (name, lost_before, lost_after)
        assert after > before, name
        assert after / before == pytest.approx(expected_after / expected_before, rel=0.20), (
            name,
            before,
            after,
        )
        assert before == pytest.approx(expected_before, rel=0.08), (name, before, expected_before)
        # the conditional part is what the §6.1 property is about, and it is the larger
        # of the two: the shared outage alone could not produce a ratio anywhere near this
        assert expected_after / expected_before > 3.0
    # a laboratory assay degrades under the same overload, but far less than an online probe
    lab = config.missingness.model_for("B", "lab")
    online = config.missingness.model_for("B", "online")
    flags = frozenset({"overload"})
    assert lab.rate(flags) < online.rate(flags)
    assert config.sensors["alkalinity"].kind == "lab"


def test_one_seeded_stream_per_sensor(config):
    """Same seed, same record; changing one sensor's spec leaves every other one untouched."""
    channels = _flat_channels(n_days=300)
    a = observe(channels, config, "C", seed=42)
    b = observe(channels, config, "C", seed=42)
    c = observe(channels, config, "C", seed=43)
    for name in a.names:
        np.testing.assert_array_equal(a[name].value, b[name].value)
    assert not np.array_equal(a["ph"].value, c["ph"].value)
    # a sensor's stream is its own, so a change to 'ph' moves nothing else — not the
    # sensors that sort before it, and (unlike the serial stream this replaced) not the
    # ones that sort after it either
    loud = config.sensors["ph"].model_copy(update={"noise": NoiseModel(cv=0.5, sd_abs=0.0)})
    cfg = config.model_copy(update={"sensors": {**config.sensors, "ph": loud}})
    d = observe(channels, cfg, "C", seed=42)
    for other in a.names:
        if other != "ph":
            np.testing.assert_array_equal(a[other].value, d[other].value, err_msg=other)
    assert not np.array_equal(a["ph"].value, d["ph"].value)
    # requesting a subset does not change any value either
    subset = observe(channels, config, "C", seed=42, sensors=["temperature"])
    np.testing.assert_array_equal(subset["temperature"].value, a["temperature"].value)


def test_the_sensor_stream_key_is_stable_and_domain_separated():
    """Golden values. ``hash()`` is salted per process; this derivation must not be.

    If the derivation changes, every archived run's observations change with it, so the
    numbers are pinned rather than merely asserted to be reproducible within one process.
    """
    assert sensor_stream_key("gas_flow") == 7_473_753_770_277_016_189
    assert sensor_stream_key("ph") == 16_920_755_590_877_555_657
    assert sensor_stream_key("gas_flow") != sensor_stream_key("gas_flow ")
    first = sensor_rng(1000, "gas_flow").standard_normal(4)
    np.testing.assert_allclose(first, sensor_rng(1000, "gas_flow").standard_normal(4))
    # the seed and the name both matter, and neither alone decides the stream
    assert not np.array_equal(first, sensor_rng(1001, "gas_flow").standard_normal(4))
    assert not np.array_equal(first, sensor_rng(1000, "ph").standard_normal(4))


def _equal_tier_policy(config: ObservationConfig) -> ObservationConfig:
    """The same configuration with every *tier policy* held equal across tiers.

    What remains different between tiers is then only the sensor **set**, which is what
    §6.4 says a tier is. The recalibration cadence, the laboratory turnaround and the two
    missing rates are declared tier properties and legitimately change a reading; holding
    them equal is what isolates the question this test is asking.
    """
    quiet = _without_missingness(config)
    tiers = {
        t: s.model_copy(update={"recalibration_interval_d": 30.0, "lab_turnaround_d": 2.0})
        for t, s in quiet.tiers.items()
    }
    return quiet.model_copy(update={"tiers": tiers})


def test_a_sensor_reads_the_same_whichever_tier_carries_it(config):
    """§6.4: a tier is a mask on identical truth, so it must not also be a re-roll.

    The serial stream this replaced was consumed over ``sorted(tier.sensors)``, and the
    tiers carry different sets, so a shared instrument's position in the queue changed with
    the tier and it got a different realisation. Measured at one seed before the fix: tier
    A's ``gas_flow`` began 3212.4, nan, 5413.4 and tier C's 3065.9, 5927.2, 5515.3 — the
    same instrument on the same digester, tier A losing a sample tier C kept.

    The three records are generated **separately**, one ``observe`` call each. The old test
    compared one shared object with itself and could not have seen this.
    """
    cfg = _equal_tier_policy(config)
    channels = _flat_channels(n_days=300)
    records = {tier: observe(channels, cfg, tier, seed=7) for tier in "ABC"}

    # the test is only meaningful if the sets really differ, and differ in the way that
    # broke the old scheme: tier C carries sensors that sort BEFORE a shared one
    sets = {t: set(records[t].names) for t in "ABC"}
    assert sets["A"] < sets["B"] < sets["C"]
    assert {"alkalinity", "ch4_fraction", "cod_total"} <= sets["C"] - sets["A"]
    assert "gas_flow" in sets["A"] & sets["C"]

    for lower, upper in (("A", "B"), ("A", "C"), ("B", "C")):
        shared = sorted(sets[lower] & sets[upper])
        assert shared, (lower, upper)
        for name in shared:
            np.testing.assert_array_equal(
                records[lower][name].value,
                records[upper][name].value,
                err_msg=f"{name} differs between tiers {lower} and {upper}",
            )
            np.testing.assert_array_equal(
                records[lower][name].missing, records[upper][name].missing, err_msg=name
            )

    # CONTROL: a different seed must give a different realisation, or the equality above
    # would be satisfied by a model that had stopped drawing anything at all
    other = observe(channels, cfg, "A", seed=8)
    for name in sorted(sets["A"]):
        assert not np.array_equal(records["A"][name].value, other[name].value), name


def test_the_historian_grid_is_the_same_at_every_tier(config):
    """The shared stream is drawn on the finest online schedule, which must not vary.

    If one tier's finest online interval differed, the outage *days* would differ with it
    and the tier comparison would carry a second confound behind the one just removed. The
    rate is a declared tier property and may differ; the grid may not.
    """
    finest = {
        tier: min(
            config.sensors[n].sampling_interval_d
            for n in config.tiers[tier].sensors
            if config.sensors[n].kind == "online"
        )
        for tier in "ABC"
    }
    assert len(set(finest.values())) == 1, finest


def test_a_run_missing_a_channel_is_refused_not_faked(config):
    """Tier C needs the solids channels; a run without them raises rather than inventing them."""
    channels = _flat_channels()
    without = TruthChannels(
        channels.t, {k: channels[k] for k in channels.names if k not in ("vs", "ts")}
    )
    observe(without, config, "B", seed=1)  # Tier B does not need them
    with pytest.raises(ValueError, match="did not compute"):
        observe(without, config, "C", seed=1)
