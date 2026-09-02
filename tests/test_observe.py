"""The observation model (sim/observe, configs/observe/observation.yaml).

What is tested and why it cannot pass vacuously:

* the catalogue loads and is a **contract**: every channel has a unit, a wet/dry basis, an
  instrument that exists, and either a truth quantity or a stated reason why it cannot be
  produced; gas channels carry standard conditions; a zero-lag assay has to say so;
* **tiers are masks over one catalogue**, not three catalogues: A is contained in B is
  contained in C, and a channel's observed series is bit for bit the same at every tier
  that shows it (the child stream is keyed on the catalogue, not the tier);
* every Plant B/C sensor number marked `muscatine_scada` equals the value derived from the
  SCADA year (`anchor/derived/muscatine-scada-sensor-statistics.json`), those statistics
  are **re-derived offline from the committed 60-day window**, and, when the 88.8 MB file
  is present, from the file itself; every Plant A number is marked assumed;
* the seeded chain does what the module docstring says, term by term: noise unbiased at
  the declared scale, drift bounded, fouling and flatline episodes visible in the record,
  saturation clipped and flagged, quantisation applied, assay lag and weekday schedule
  honoured;
* **missingness is conditional**: with the same seed and the same truth, raising the VFA
  of the truth raises the missing rate of the stress-sensitive channels and leaves the
  insensitive ones (the thermowell) alone;
* the truth series carry their units, gas volumes are the dry STP ones (never the BSM2
  wet q_gas), and the ash tracer closes against its analytical steady state;
* nothing under `sim/observe` writes a file (CLAUDE.md rule 1).
"""

from __future__ import annotations

import ast
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pytest

from anchor.ingest_muscatine import (
    SCADA_FILE,
    SCADA_WINDOW_FILE,
    dropout_statistics,
    load_scada,
    sensor_noise_statistics,
)
from sim.adm1 import load_matrix, load_solver_config, simulate
from sim.influent import (
    generate_influent,
    load_feed_fractionation,
    load_generator_config,
    truth_parameters,
)
from sim.observe import (
    TIER_ORDER,
    Basis,
    ChannelKind,
    SensorEffect,
    SensorFault,
    ash_concentration,
    load_observation_config,
    observe,
    reactor_ash,
    sample_times,
    stress_indicator,
    truth_channels,
)
from sim.observe.model import _bounded_walk
from sim.plants import declared_geometry, load_all_plants

REPO_ROOT = Path(__file__).resolve().parent.parent
STATISTICS_FILE = REPO_ROOT / "anchor" / "derived" / "muscatine-scada-sensor-statistics.json"
HORIZON_D = 60


@pytest.fixture(scope="module")
def config():
    return load_observation_config()


@pytest.fixture(scope="module")
def plants():
    return load_all_plants()


@pytest.fixture(scope="module")
def catalogue():
    return load_feed_fractionation()


@pytest.fixture(scope="module")
def scada_statistics() -> dict:
    return json.loads(STATISTICS_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def truth(plants, catalogue, adm1_params, rj2006_state):
    """Plant C, 60 d of generated influent through the truth model, as truth channels."""
    run = generate_influent(
        plants["C"], catalogue, load_generator_config(), adm1_params, seed=7, n_days=HORIZON_D
    )
    params = truth_parameters(
        adm1_params, catalogue, run.truth.mean_recipe_kg_d, run.truth.fractionations.fractionations
    )
    geometry = declared_geometry(plants["C"])
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
    config = load_observation_config()
    ash = reactor_ash(catalogue, run.truth, geometry.V_liq, result.t)
    return truth_channels(result, params, geometry, config.solids, ash), run


# ------------------------------------------------------------------- the catalogue


def test_every_channel_declares_a_unit_a_basis_and_an_instrument(config):
    for name, channel in config.channels.items():
        assert channel.unit, name
        assert channel.instrument in config.instruments, name
        assert isinstance(channel.basis, Basis), name
        gas = name in {"biogas_volume", "ch4_fraction", "offgas_h2", "offgas_h2s"}
        assert (channel.standard_conditions is not None) is gas, name
        if channel.truth_quantity is None:
            assert len(channel.unavailable_reason) > 40, name


def test_unavailable_channels_are_declared_and_excluded(config):
    unavailable = [c for c in config.channels.values() if not c.available]
    assert {c.name for c in unavailable} == {"feed_mass", "offgas_h2s"}
    # h2s: the truth model has no sulfur, and the reason says so
    assert "sulfur" in config.channels["offgas_h2s"].unavailable_reason
    assert "offgas_h2s" not in {c.name for c in config.channels_for_tier("C")}
    assert "offgas_h2s" in {c.name for c in config.channels_for_tier("C", available_only=False)}


def test_tiers_are_nested_masks_over_one_catalogue(config):
    seen: set[str] = set()
    for tier in TIER_ORDER:
        names = {c.name for c in config.channels_for_tier(tier)}
        assert seen <= names, f"tier {tier} drops a channel of the tier below"
        seen = names
    tier_a = {c.name for c in config.channels_for_tier("A")}
    tier_c = {c.name for c in config.channels_for_tier("C")}
    # the §6.4 additions actually land where the proposal puts them
    assert {"ph", "biogas_volume", "reactor_temperature", "ts", "vs"} <= tier_a
    assert {"ch4_fraction", "alkalinity", "vfa_total", "tan", "cod_total"} <= tier_c - tier_a
    assert {"vfa_acetate", "offgas_h2", "activity_ac", "tkn"} <= tier_c


def test_a_zero_lag_assay_must_say_so(config):
    spec = config.channels["alkalinity"]
    assert spec.lag_d == 0 and "same day" in spec.source
    with pytest.raises(ValueError, match="zero-lag assay"):
        spec.model_copy(update={"source": "no reason given"}).model_validate(
            spec.model_dump() | {"source": "no reason given"}
        )


def test_plant_a_instruments_are_all_assumed_and_b_equals_c(config):
    for key in config.instruments:
        model_a = config.instrument_for("A", key)
        if key == "operator_log":
            continue
        assert model_a.assumed, f"Plant A {key}: a statistics-anchored plant has no data"
        assert config.instrument_for("B", key) == config.instrument_for("C", key)
    # and the override machinery really overrides
    assert (
        config.instrument_for("A", "gas_meter").noise_cv
        > config.instrument_for("B", "gas_meter").noise_cv
    )


def test_an_unknown_override_field_is_rejected(config):
    bad = config.model_copy(deep=True)
    bad.plants["A"].instruments["gas_meter"]["not_a_field"] = 1.0
    with pytest.raises(Exception, match="not_a_field"):
        bad.instrument_for("A", "gas_meter")


# ------------------------------------------------- anchored to the Muscatine SCADA year


def test_config_matches_the_derived_scada_statistics(config, scada_statistics):
    """Every Plant B/C number marked muscatine_scada is the derived one."""
    sensors = scada_statistics["full_record"]["sensors"]
    dropouts = scada_statistics["full_record"]["dropouts"]
    probe = config.instrument_for("B", "temperature_probe")
    temperature = sensors["dig1_T_K"]
    assert probe.noise_sd_abs == pytest.approx(temperature["robust_sd"], rel=1e-3)
    assert probe.resolution == pytest.approx(temperature["resolution"], rel=1e-3)
    # the configuration rounds the derived values to three significant figures
    assert probe.flatline.onset_per_d == pytest.approx(
        temperature["flatline_episodes_per_d"], rel=1e-2
    )
    assert probe.flatline.mean_duration_d == pytest.approx(
        temperature["flatline_mean_duration_min"] / 1440.0, rel=1e-2
    )
    assert probe.missingness.base_probability == pytest.approx(
        dropouts["missing_minute_fraction"], rel=1e-3
    )
    meter = config.instrument_for("B", "gas_meter")
    biogas = sensors["biogas_m3_d"]
    assert meter.noise_cv == pytest.approx(biogas["relative_sd"], rel=1e-2)
    assert meter.flatline.onset_per_d == pytest.approx(biogas["flatline_episodes_per_d"], rel=1e-2)
    assert meter.missingness.base_probability == pytest.approx(
        dropouts["missing_minute_fraction"], rel=1e-3
    )
    # the instrument limits are the provider's data-dictionary range, and the record
    # actually reaches the lower one, so saturation is not a hypothetical
    assert probe.saturation.minimum == pytest.approx((85.0 - 32.0) * 5 / 9 + 273.15, abs=1e-2)
    assert temperature["at_lower_limit_fraction"] > 0.0
    assert meter.saturation.maximum == pytest.approx(1120.0 * 0.0283168 * 1440.0, rel=1e-4)


def test_scada_statistics_are_re_derived_from_the_committed_window(scada_statistics):
    """Offline re-derivation: the committed 60-day extract reproduces the year's noise.

    The window is committed precisely so this check needs no 88.8 MB download. It is
    representative for the high-frequency statistics and NOT for the dropouts (18 of the
    record's 19 gaps fall in the first 90 days), which is why the configuration takes the
    dropout rate from the full record; that difference is asserted here too, so the
    reason stays visible.
    """
    window = load_scada(SCADA_WINDOW_FILE)
    full = scada_statistics["full_record"]["sensors"]
    for channel, tolerance in (("dig1_T_K", 0.25), ("dig2_T_K", 0.35), ("biogas_m3_d", 0.35)):
        derived = sensor_noise_statistics(window, channel)
        assert derived.robust_sd == pytest.approx(full[channel]["robust_sd"], rel=tolerance)
        assert derived.relative_sd == pytest.approx(full[channel]["relative_sd"], rel=tolerance)
        assert derived.repeat_fraction == pytest.approx(full[channel]["repeat_fraction"], abs=0.03)
        assert json.loads(STATISTICS_FILE.read_text(encoding="utf-8"))["window"]["sensors"][
            channel
        ]["robust_sd"] == pytest.approx(derived.robust_sd, rel=1e-9)
    assert sensor_noise_statistics(window, "dig1_T_K").resolution == pytest.approx(
        full["dig1_T_K"]["resolution"], rel=1e-6
    )
    gaps = dropout_statistics(window)
    assert gaps.gaps_per_d > 3.0 * scada_statistics["full_record"]["dropouts"]["gaps_per_d"]


@pytest.mark.skipif(not SCADA_FILE.exists(), reason="the 88.8 MB SCADA file is not present")
def test_scada_statistics_are_re_derived_from_the_full_file(scada_statistics):
    series = load_scada(SCADA_FILE)
    for channel, recorded in scada_statistics["full_record"]["sensors"].items():
        derived = sensor_noise_statistics(series, channel)
        for field, value in recorded.items():
            if isinstance(value, str):
                continue
            assert getattr(derived, field) == pytest.approx(value, rel=1e-9), (channel, field)
    gaps = dropout_statistics(series)
    for field, value in scada_statistics["full_record"]["dropouts"].items():
        assert getattr(gaps, field) == pytest.approx(value, rel=1e-9), field


# ------------------------------------------------------------------- the truth series


def test_truth_channels_carry_units_and_the_dry_stp_gas_convention(truth, config):
    channels, _ = truth
    for name, series in channels.values.items():
        assert channels.units[name], name
        assert np.all(np.isfinite(series)), name
    needed = {c.truth_quantity for c in config.channels_for_tier("C")}
    assert needed <= set(channels.values), needed - set(channels.values)
    # the reported biogas is the dry STP volume, never the wet BSM2 q_gas at T_op
    assert channels.units["biogas_volume"] == "m3/d"
    assert 0.5 < channels.values["ch4_fraction"].mean() < 0.75
    assert channels.values["vs"].max() <= 1.0  # a dry-basis fraction
    # VFA are the acids, not COD: acetate mass is below its COD
    assert np.all(channels.values["vfa_acetate"] < channels.values["vfa_total"] * 1.0001)


def test_ash_tracer_reaches_the_analytical_steady_state():
    """A conservative tracer at constant feed approaches the influent concentration."""
    t = np.arange(0.0, 200.0)
    q = np.full_like(t, 50.0)
    u = np.full_like(t, 12.0)
    x = ash_concentration(t, u, q, V_liq=1000.0, initial=0.0)
    assert x[0] == 0.0
    assert x[-1] == pytest.approx(12.0, rel=1e-3)
    # one HRT (20 d) gets 1 - 1/e of the way there
    assert x[20] == pytest.approx(12.0 * (1.0 - math.exp(-1.0)), rel=1e-6)


def test_solids_use_the_declared_convention(truth, config):
    channels, _ = truth
    assert config.solids.include_vfa_in_vs is False
    assert set(config.solids.cod_per_vs) == {
        "carbohydrate",
        "protein",
        "lipid",
        "inert",
        "biomass",
        "composite",
    }
    ts, vs = channels.values["ts"], channels.values["vs"]
    assert np.all(ts > 0.0) and np.all((vs > 0.4) & (vs < 0.95))


# ----------------------------------------------------------------- the sensor chain


def test_the_same_seed_reproduces_the_run_and_a_different_seed_does_not(truth, config):
    channels, _ = truth
    a = observe(channels, config, "C", "C", seed=11)
    b = observe(channels, config, "C", "C", seed=11)
    c = observe(channels, config, "C", "C", seed=12)
    for name, series in a.observed.sensors.items():
        assert np.array_equal(series.value, b.observed.sensors[name].value, equal_nan=True)
    assert not np.array_equal(
        a.observed.sensors["ph"].value, c.observed.sensors["ph"].value, equal_nan=True
    )


def test_a_tier_is_the_richer_tier_with_columns_removed(truth, config):
    channels, _ = truth
    low = observe(channels, config, "C", "A", seed=11)
    high = observe(channels, config, "C", "C", seed=11)
    assert set(low.observed.sensors) < set(high.observed.sensors)
    for name, series in low.observed.sensors.items():
        assert np.array_equal(series.value, high.observed.sensors[name].value, equal_nan=True)
    low_assays = {(a.channel, a.sample_day, a.value) for a in low.observed.assays}
    high_assays = {(a.channel, a.sample_day, a.value) for a in high.observed.assays}
    assert low_assays < high_assays


def test_reconfiguring_one_channel_leaves_the_others_bitwise_identical(truth, config):
    channels, _ = truth
    base = observe(channels, config, "C", "C", seed=11)
    louder = config.model_copy(deep=True)
    louder.plants["C"].instruments["ph_electrode"] = {"noise_sd_abs": 1.0}
    changed = observe(channels, louder, "C", "C", seed=11)
    assert not np.array_equal(
        base.observed.sensors["ph"].value, changed.observed.sensors["ph"].value, equal_nan=True
    )
    for name in ("reactor_temperature", "biogas_volume", "ch4_fraction", "offgas_h2"):
        assert np.array_equal(
            base.observed.sensors[name].value,
            changed.observed.sensors[name].value,
            equal_nan=True,
        )


def test_noise_is_unbiased_at_the_declared_scale(truth, config):
    """The biogas meter's reported values scatter about the truth at its declared cv."""
    channels, _ = truth
    quiet = config.model_copy(deep=True)
    quiet.plants["C"].instruments["gas_meter"] = {
        "drift": {"sd_per_sqrt_d": 0.0},
        "flatline": {"onset_per_d": 0.0},
        "missingness": {"base_probability": 0.0, "stress_sensitivity": 0.0},
    }
    run = observe(channels, quiet, "C", "A", seed=3)
    series = run.observed.sensors["biogas_volume"]
    true = channels.at("biogas_volume", series.t)
    relative = series.value / true - 1.0
    cv = quiet.instrument_for("C", "gas_meter").noise_cv
    assert abs(relative.mean()) < 0.5 * cv
    assert 0.6 * cv < relative.std() < 1.6 * cv


def test_drift_is_a_bounded_random_walk():
    z = np.random.default_rng(0).standard_normal(20_000)
    dt = np.ones_like(z)
    walk = _bounded_walk(z, dt, sd_per_sqrt_d=0.5, bound=0.3)
    assert np.all(np.abs(walk) <= 0.3 + 1e-12)
    assert walk.std() > 0.05  # it moves; a clamp at 0 would also satisfy the bound
    assert np.all(_bounded_walk(z, dt, sd_per_sqrt_d=0.0, bound=0.3) == 0.0)


def test_fouling_flatlining_and_saturation_appear_in_the_record(truth, config):
    channels, _ = truth
    dirty = config.model_copy(deep=True)
    dirty.plants["C"].instruments["ph_electrode"] = {
        "fouling": {"onset_per_d": 0.05, "mean_duration_d": 5.0, "offset": -0.5},
        "flatline": {"onset_per_d": 0.05, "mean_duration_d": 3.0},
        "saturation": {"minimum": 7.0, "maximum": 14.0},
        "missingness": {"base_probability": 0.0, "stress_sensitivity": 0.0},
        "drift": {"sd_per_sqrt_d": 0.0},
        "noise_sd_abs": 0.0,
    }
    run = observe(channels, dirty, "C", "A", seed=5)
    series = run.observed.sensors["ph"]
    kinds = {e.kind for e in run.truth.episodes if e.channel == "ph"}
    assert {"fouling", "flatline"} <= kinds
    assert run.truth.saturated["ph"].any()  # the fouling offset pushes pH below 7.0
    assert series.value.min() >= 7.0  # and the reading is clipped there
    # a flat-lined sample repeats the previous reported value exactly
    flat = next(e for e in run.truth.episodes if e.channel == "ph" and e.kind == "flatline")
    k = int(np.searchsorted(series.t, flat.start_d))
    assert series.value[k] == series.value[k - 1]


def test_quantisation_is_applied(truth, config):
    channels, _ = truth
    run = observe(channels, config, "C", "A", seed=5)
    probe = config.instrument_for("C", "temperature_probe")
    values = run.observed.sensors["reactor_temperature"].value
    residual = np.abs(values / probe.resolution - np.round(values / probe.resolution))
    assert np.nanmax(residual) < 1e-6


def test_assays_honour_their_schedule_lag_and_units(truth, config):
    channels, _ = truth
    run = observe(channels, config, "C", "C", seed=5, start_weekday=5)
    by_channel: dict[str, list] = {}
    for record in run.observed.assays:
        by_channel.setdefault(record.channel, []).append(record)
    for name, records in by_channel.items():
        spec = config.channels[name]
        assert spec.kind is ChannelKind.ASSAY
        assert {r.unit for r in records} == {spec.unit}
        assert all(r.report_day == r.sample_day + spec.lag_d for r in records)
        if spec.weekdays_only:
            assert all((5 + r.sample_day) % 7 < 5 for r in records)  # started on a Saturday
        days = sorted(r.sample_day for r in records)
        assert all((b - a) % spec.interval_d == 0 for a, b in itertools.pairwise(days))
    assert by_channel["activity_ac"]  # the 28-day test fires inside a 60-day horizon
    assert len(by_channel["ts"]) > len(by_channel["activity_ac"])


def test_sample_times_anchor_a_weekly_schedule_to_the_first_weekday(config):
    spec = config.channels["ts"]
    for start_weekday in range(7):
        times = sample_times(spec, 60.0, start_weekday)
        assert times.size >= 8, start_weekday
        assert all((start_weekday + int(t)) % 7 < 5 for t in times)
    assert sample_times(config.channels["ph"], 3.0, 0).tolist() == [0.0, 1.0, 2.0]


# ------------------------------------------------------- conditional missingness (§6.1)


def test_missingness_is_conditional_on_the_truth_state(truth, config):
    """Sensors fail during a VFA excursion - and only the channels declared sensitive do."""
    channels, _ = truth
    stressed = channels.values["vfa_total"].copy()
    stressed[30:45] *= 8.0  # a foaming/overload episode: three doublings
    hard = type(channels)(
        t=channels.t, values={**channels.values, "vfa_total": stressed}, units=channels.units
    )
    calm = observe(channels, config, "C", "B", seed=17)
    upset = observe(hard, config, "C", "B", seed=17)
    assert (
        stress_indicator(hard, config.stress).max()
        > stress_indicator(channels, config.stress).max()
    )

    for name in ("ph", "ch4_fraction"):
        t = calm.observed.sensors[name].t
        window = (t >= 30.0) & (t < 45.0)
        p_calm = calm.truth.missing_probability[name][window]
        p_upset = upset.truth.missing_probability[name][window]
        assert p_upset.mean() > 3.0 * p_calm.mean(), name
        assert upset.observed.sensors[name].observed_fraction < (
            calm.observed.sensors[name].observed_fraction
        ), name
    # the thermowell probe declares no sensitivity, so nothing about it moves
    assert np.array_equal(
        calm.truth.missing_probability["reactor_temperature"],
        upset.truth.missing_probability["reactor_temperature"],
    )
    assert np.array_equal(
        calm.observed.sensors["reactor_temperature"].value,
        upset.observed.sensors["reactor_temperature"].value,
        equal_nan=True,
    )
    # and the gaps land where the excursion is, so interpolating over them hides the
    # transient (the hourly analyser has the sample count to show it)
    missing = upset.observed.sensors["ch4_fraction"].missing
    t = upset.observed.sensors["ch4_fraction"].t
    inside = missing[(t >= 30) & (t < 45)].mean()
    outside = missing[t < 30].mean()
    assert inside > 5.0 * outside > 0.0


def test_the_stress_indicator_is_zero_on_a_flat_run(config):
    from sim.observe.truth import TruthChannels

    t = np.arange(0.0, 30.0)
    flat = TruthChannels(
        t=t,
        values={"vfa_total": np.full_like(t, 0.5), "biogas_volume": np.full_like(t, 600.0)},
        units={"vfa_total": "kg/m3", "biogas_volume": "m3/d"},
    )
    assert stress_indicator(flat, config.stress).max() == pytest.approx(0.0)


# ------------------------------------------------------------- injected sensor faults


def test_an_injected_scale_fault_reaches_only_its_channel_and_only_after_onset(truth, config):
    channels, _ = truth
    fault = SensorFault(
        channel="biogas_volume",
        effect=SensorEffect.SCALE,
        onset_d=30.0,
        magnitude=1.08,
        label="gas_meter_scale",
    )
    base = observe(channels, config, "C", "B", seed=21)
    faulted = observe(channels, config, "C", "B", seed=21, faults=[fault])
    a = base.observed.sensors["biogas_volume"]
    b = faulted.observed.sensors["biogas_volume"]
    before = a.t < 30.0
    assert np.array_equal(a.value[before], b.value[before], equal_nan=True)
    ratio = b.value[~before] / a.value[~before]
    assert np.nanmedian(ratio) == pytest.approx(1.08, rel=1e-6)
    for name in ("ph", "reactor_temperature", "ch4_fraction"):
        assert np.array_equal(
            base.observed.sensors[name].value,
            faulted.observed.sensors[name].value,
            equal_nan=True,
        )


# ------------------------------------------------------------------ rule 1 hygiene


_WRITERS = {"open", "write_text", "write_bytes", "to_csv", "dump", "safe_dump", "savetxt", "save"}


def _write_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
            if name in _WRITERS:
                found.append(f"{path.name}:{node.lineno}: {name}")
    return found


@pytest.mark.parametrize("package", ["observe", "faults"])
def test_truth_producing_packages_never_write_files(package, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("from pathlib import Path\nPath('x').write_text('truth')\nopen('y', 'w')\n")
    assert len(_write_calls(bad)) == 2  # the checker sees both patterns
    modules = sorted((REPO_ROOT / "sim" / package).glob("*.py"))
    assert modules
    assert not [c for m in modules for c in _write_calls(m)]
