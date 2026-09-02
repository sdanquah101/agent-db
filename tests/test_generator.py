"""The influent generator (sim/influent/generator.py, configs/influent/generator.yaml).

What is tested and why it cannot pass vacuously:

* the generator statistics load, agree with the frozen plant contracts (feed sets,
  delivery kinds, zero-day fractions, units, continuous medians), and every Plant B/C
  number marked ``muscatine_daily`` is re-derived from the committed daily file through
  ``anchor/ingest_muscatine.py`` within a stated tolerance (dataset-anchored means
  regenerable from the data);
* one seeded stream, consumed in the documented order: same seed gives the same run,
  different seeds differ, the true-fractionation draw is the same head as
  ``sample_true_fractionations``, and a later stage (another feed's mis-logs, assay
  noise) cannot change an earlier one;
* the delivery process reproduces the plant's patterns (weekday silage, Markov HSW,
  weekend-free FOG) and the anchor's zero fractions, medians and spreads;
* the operator log differs from the truth exactly where the generator says it does
  (unrecorded deliveries, mis-logged masses) and nowhere else;
* the influent series is the flow-weighted mix of the true deliveries with the true
  fractionation and moisture, sample-and-hold, and the truth model integrates it;
* assays carry units and basis, arrive with the declared lag, are unbiased around the
  true value, and the TKN assay is the per-feed one the fitted model cannot reproduce.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from anchor.ingest_muscatine import DAILY_FILE, assay_statistics, delivery_statistics, load_daily
from sim.adm1 import LIQUID_STATE_NAMES, Influent, load_matrix, load_solver_config, simulate
from sim.influent import (
    ASSAY_NAMES,
    GENERATOR_CONFIG,
    check_generator_against_plant,
    feed_concentrations,
    feed_tkn,
    generate_influent,
    implied_tkn,
    load_feed_fractionation,
    load_generator_config,
    sample_true_fractionations,
)
from sim.influent.generator import (
    ASSAY_UNITS,
    AssaySchedule,
    DeliveryModel,
    GeneratorConfig,
    bicarbonate_alkalinity,
    seasonal_factor,
)
from sim.plants import declared_geometry, load_all_plants

_L = {n: i for i, n in enumerate(LIQUID_STATE_NAMES)}
PER_UNIT = 2
FEED_COLUMNS = {
    "primary_sludge": "ps_m3",
    "thickened_was": "twas_m3",
    "high_strength_waste": "hsw_m3",
    "fog": "fog_m3",
}
ASSAY_COLUMNS = {
    "primary_sludge": "ps_vs_kg_kg",
    "thickened_was": "twas_vs_kg_kg",
    "high_strength_waste": "hsw_vs_kg_kg",
}


@pytest.fixture(scope="module")
def catalogue():
    return load_feed_fractionation()


@pytest.fixture(scope="module")
def config():
    return load_generator_config()


@pytest.fixture(scope="module")
def plants():
    return load_all_plants()


@pytest.fixture(scope="module")
def runs(plants, catalogue, config, adm1_params):
    return {
        pid: generate_influent(plants[pid], catalogue, config, adm1_params, seed=7, n_days=730)
        for pid in plants
    }


# ------------------------------------------------------------------ configuration


def test_config_loads_and_agrees_with_every_plant(config, plants, catalogue):
    assert set(config.plants) == set(plants) and set(config.assays) == set(ASSAY_NAMES)
    for pid, cfg in plants.items():
        check_generator_against_plant(config.plants[pid], cfg, catalogue)
    # B and C share the sludge statistics (controlled pair)
    for fid in ("primary_sludge", "thickened_was"):
        b = config.plants["B"].feeds[fid].model_dump()
        c = config.plants["C"].feeds[fid].model_dump()
        for block in ("delivery", "amount", "moisture", "logging", "assay_schedule"):
            b[block].pop("source"), c[block].pop("source")
        assert b == c, fid
    text = GENERATOR_CONFIG.read_text(encoding="utf-8")
    assert "ASSUMED" in text  # assumptions are flagged, not hidden


def test_config_rejections(config, plants, catalogue):
    with pytest.raises(ValidationError, match="zero_fraction"):
        DeliveryModel(model="markov", zero_fraction=0.0, persistence=0.5)
    with pytest.raises(ValidationError, match="persistence"):
        DeliveryModel(model="markov", zero_fraction=0.1, persistence=1.0)
    with pytest.raises(ValidationError, match="distinct days"):
        DeliveryModel(model="weekday", days=(0, 0))
    with pytest.raises(ValidationError, match="unique"):
        AssaySchedule(interval_d=1, weekdays_only=False, assays=("ts", "ts"))
    raw = config.model_dump()
    raw["plants"]["A"]["plant_id"] = "B"
    with pytest.raises(ValidationError, match="declares plant_id"):
        GeneratorConfig.model_validate(raw)
    raw = config.model_dump()
    del raw["assays"]["ph"]
    with pytest.raises(ValidationError, match="assay models missing"):
        GeneratorConfig.model_validate(raw)
    gen_b = config.plants["B"]
    with pytest.raises(ValueError, match="generator is for plant"):
        check_generator_against_plant(gen_b, plants["A"], catalogue)
    with pytest.raises(ValueError, match="generator feeds"):
        gen_c = config.plants["C"].model_copy(update={"feeds": gen_b.feeds})
        check_generator_against_plant(gen_c, plants["C"], catalogue)
    hsw = gen_b.feeds["high_strength_waste"]
    bad = gen_b.model_copy(
        update={
            "feeds": gen_b.feeds
            | {
                "high_strength_waste": hsw.model_copy(
                    update={
                        "delivery": hsw.delivery.model_copy(update={"zero_fraction": 0.3}),
                    }
                )
            }
        }
    )
    with pytest.raises(ValueError, match="zero-day fraction"):
        check_generator_against_plant(bad, plants["B"], catalogue)
    ps = gen_b.feeds["primary_sludge"]
    bad = gen_b.model_copy(
        update={
            "feeds": gen_b.feeds
            | {
                "primary_sludge": ps.model_copy(
                    update={"amount": ps.amount.model_copy(update={"nonzero_median": 60.0})}
                )
            }
        }
    )
    with pytest.raises(ValueError, match="nonzero median"):
        check_generator_against_plant(bad, plants["B"], catalogue)
    with pytest.raises(ValueError, match="n_days"):
        generate_influent(plants["A"], catalogue, config, None, seed=1, n_days=0)


@pytest.mark.skipif(not DAILY_FILE.exists(), reason="Muscatine daily file not present")
def test_plant_b_statistics_are_rederived_from_the_muscatine_daily_file(config):
    """Every `muscatine_daily` number of the Plant B block comes out of the ingest module."""
    records = load_daily()
    assert len(records) == 1103
    gen = config.plants["B"]
    for fid, column in FEED_COLUMNS.items():
        stats = delivery_statistics(records, column, per_unit=PER_UNIT)
        g = gen.feeds[fid]
        assert g.delivery.expected_zero_fraction == pytest.approx(stats.zero_fraction, abs=0.03)
        assert g.amount.nonzero_median == pytest.approx(stats.nonzero_median, rel=0.03), fid
        assert g.amount.log_sigma == pytest.approx(stats.log_sigma, abs=0.03), fid
        assert g.amount.lag1 == pytest.approx(stats.amount_lag1, abs=0.03), fid
        if g.amount.seasonal_amplitude > 0.0:
            assert g.amount.seasonal_peak_doy == pytest.approx(stats.seasonal_peak_doy, abs=45)
            assert g.amount.seasonal_amplitude <= stats.seasonal_amplitude + 0.03
            assert g.amount.seasonal_amplitude >= 0.5 * stats.seasonal_amplitude
        if g.delivery.model == "markov":
            assert g.delivery.persistence == pytest.approx(stats.indicator_lag1, abs=0.03)
            assert stats.mean_zero_run_d == pytest.approx(
                1.0
                / (1.0 - (stats.zero_fraction + stats.indicator_lag1 * (1 - stats.zero_fraction))),
                rel=0.1,
            )
        if g.delivery.model == "weekday":  # FOG: weekends off, a few weekday skips
            weekend = stats.zero_fraction_by_weekday[5:]
            assert min(weekend) > 0.9 and max(stats.zero_fraction_by_weekday[:5]) < 0.1
    for fid, column in ASSAY_COLUMNS.items():
        stats = assay_statistics(records, column)
        m = gen.feeds[fid].moisture
        assert m.ts_log_sigma == pytest.approx(stats.log_sigma, abs=0.04), fid
        assert m.lag1 == pytest.approx(stats.lag1_log, abs=0.03), fid
        sched = gen.feeds[fid].assay_schedule
        weekend = stats.measured_fraction_by_weekday[5:]
        assert sched.weekdays_only == (max(weekend) < 0.1), fid


# ------------------------------------------------------------- determinism / stream


def test_same_seed_same_run_and_the_stream_order_is_as_documented(
    plants, catalogue, config, adm1_params
):
    a = generate_influent(plants["B"], catalogue, config, adm1_params, seed=3, n_days=200)
    b = generate_influent(plants["B"], catalogue, config, adm1_params, seed=3, n_days=200)
    c = generate_influent(plants["B"], catalogue, config, adm1_params, seed=4, n_days=200)
    assert a.truth.fractionations == b.truth.fractionations != c.truth.fractionations
    for fid in a.truth.feeds:
        np.testing.assert_array_equal(
            a.truth.feeds[fid].delivered_kg, b.truth.feeds[fid].delivered_kg
        )
        assert not np.array_equal(a.truth.feeds[fid].delivered_kg, c.truth.feeds[fid].delivered_kg)
    assert a.observed.assays == b.observed.assays != c.observed.assays
    np.testing.assert_array_equal(a.truth.influent.concentrations, b.truth.influent.concentrations)
    # the true-fractionation draw is the head of the stream: identical to the seed-only API
    ids = [f.name for f in plants["B"].feeds]
    assert a.truth.fractionations == sample_true_fractionations(catalogue, ids, 3)
    # a later stage cannot change an earlier one: thickened_was (sorted last) mis-logs
    # and the assay noise leave fog / hsw / primary deliveries and the fractionation untouched
    gen = config.plants["B"]
    twas = gen.feeds["thickened_was"]
    changed = gen.model_copy(
        update={
            "feeds": gen.feeds
            | {
                "thickened_was": twas.model_copy(
                    update={
                        "logging": twas.logging.model_copy(update={"mislog_probability": 0.5}),
                        "assay_schedule": twas.assay_schedule.model_copy(update={"interval_d": 3}),
                    }
                )
            }
        }
    )
    cfg2 = config.model_copy(update={"plants": config.plants | {"B": changed}})
    d = generate_influent(plants["B"], catalogue, cfg2, adm1_params, seed=3, n_days=200)
    assert d.truth.fractionations == a.truth.fractionations
    for fid in ("fog", "high_strength_waste", "primary_sludge"):
        np.testing.assert_array_equal(
            d.truth.feeds[fid].delivered_kg, a.truth.feeds[fid].delivered_kg
        )
        np.testing.assert_array_equal(
            d.observed.feed_log_kg_wet_d[fid], a.observed.feed_log_kg_wet_d[fid]
        )
    assert len(d.truth.feeds["thickened_was"].mislogged_days) > len(
        a.truth.feeds["thickened_was"].mislogged_days
    )
    # assay records of the unchanged feeds are identical (noise drawn after all deliveries,
    # per feed in sorted order, so fog / hsw / primary noise precedes thickened_was)
    for fid in ("fog", "high_strength_waste", "primary_sludge"):
        assert [r for r in d.observed.assays if r.feed_id == fid] == [
            r for r in a.observed.assays if r.feed_id == fid
        ]


# ----------------------------------------------------------------- delivery process


def test_plant_a_silage_is_a_weekday_batch_and_slurry_is_daily(runs, plants):
    run = runs["A"]
    silage = run.truth.feeds["grass_silage"].delivered_kg
    slurry = run.truth.feeds["cattle_slurry"].delivered_kg
    day = np.arange(run.truth.n_days)
    weekend = (day % 7) >= 5  # start_weekday 0 = Monday
    # weekends: only the (rare) unrecorded deliveries
    assert set(np.flatnonzero(silage[weekend] > 0)) <= {
        np.flatnonzero(weekend).tolist().index(t)
        for t in run.truth.feeds["grass_silage"].unrecorded_days
        if weekend[t]
    }
    assert np.all(silage[~weekend] > 0)
    assert np.all(slurry > 0)
    logged = run.observed.feed_log_kg_wet_d["grass_silage"]
    assert np.median(logged[~weekend]) == pytest.approx(2000.0, rel=0.05)
    assert np.median(slurry) == pytest.approx(14.5 * 1000.0, rel=0.05)
    # the plant's declared zero-day fraction is reproduced
    silage_stream = next(f for f in plants["A"].feeds if f.name == "grass_silage")
    assert np.mean(logged == 0) == pytest.approx(silage_stream.zero_days_fraction, abs=0.02)


@pytest.mark.skipif(not DAILY_FILE.exists(), reason="Muscatine daily file not present")
def test_plant_b_generated_deliveries_match_the_anchor_statistics(runs, plants):
    """Generated 2-year series vs the daily file: zero fractions, medians, spreads, runs."""
    records = load_daily()
    run = runs["B"]
    day = np.arange(run.truth.n_days)
    for fid, column in FEED_COLUMNS.items():
        stats = delivery_statistics(records, column, per_unit=PER_UNIT)
        spec_density = 950.0 if fid == "fog" else 1000.0
        m3 = run.observed.feed_log_kg_wet_d[fid] / spec_density
        assert np.mean(m3 == 0) == pytest.approx(stats.zero_fraction, abs=0.04), fid
        nz = m3[m3 > 0]
        assert np.median(nz) == pytest.approx(stats.nonzero_median, rel=0.15), fid
        assert np.log(nz).std() == pytest.approx(stats.log_sigma, rel=0.3), fid
    fog = run.observed.feed_log_kg_wet_d["fog"]
    assert np.mean(fog[(day % 7) >= 5] == 0) > 0.95
    hsw = run.truth.feeds["high_strength_waste"].delivered_kg
    runs_of_zero = np.diff(np.flatnonzero(np.diff(np.r_[1, hsw > 0, 1]) != 0))[::2]
    assert runs_of_zero.mean() == pytest.approx(
        delivery_statistics(records, "hsw_m3", PER_UNIT).mean_zero_run_d, rel=0.5
    )
    # the plant's declared total feed flow is reproduced to within the parts-vs-sum gap
    assert np.median(run.truth.influent.q) == pytest.approx(
        plants["B"].hydraulics.feed_flow_m3_d.median, rel=0.15
    )


def test_seasonal_and_ar1_primitives():
    day = np.arange(365)
    s = seasonal_factor(day, start_doy=1, amplitude=0.25, peak_doy=250.0)
    assert s.max() == pytest.approx(np.exp(0.25)) and np.argmax(s) == 249
    assert s.min() == pytest.approx(np.exp(-0.25), rel=1e-3)
    assert np.all(seasonal_factor(day, 1, 0.0, 0.0) == 1.0)
    # alkalinity proxy: all bicarbonate far above pK_a1, none far below
    assert bicarbonate_alkalinity(0.05, 9.0, 6.35) == pytest.approx(2.5, rel=3e-3)
    assert bicarbonate_alkalinity(0.05, 3.0, 6.35) < 0.01
    assert bicarbonate_alkalinity(0.0, 7.0, 6.35) == 0.0


# ---------------------------------------------------------- truth vs operator log


def test_log_differs_from_truth_only_at_unrecorded_and_mislogged_days(runs):
    for run in runs.values():
        for fid, ft in run.truth.feeds.items():
            logged = run.observed.feed_log_kg_wet_d[fid]
            unrec = np.zeros(run.truth.n_days, dtype=bool)
            unrec[list(ft.unrecorded_days)] = True
            mis = np.zeros(run.truth.n_days, dtype=bool)
            mis[list(ft.mislogged_days)] = True
            same = ~unrec & ~mis
            np.testing.assert_array_equal(logged[same], ft.delivered_kg[same])
            assert np.all(ft.delivered_kg[unrec] > logged[unrec])  # extra mass never logged
            assert np.all(logged[mis] != ft.delivered_kg[mis]) and np.all(logged[mis] > 0)
            assert ft.delivered_kg.shape == logged.shape == (run.truth.n_days,)
    b = runs["B"].truth.feeds
    assert b["primary_sludge"].unrecorded_days == () and b["high_strength_waste"].unrecorded_days
    assert 0 < len(b["fog"].mislogged_days) < 0.1 * runs["B"].truth.n_days


# ------------------------------------------------------------- influent series


def test_influent_is_the_flow_weighted_mix_of_true_deliveries(runs, catalogue):
    run = runs["B"]
    inf = run.truth.influent
    assert inf.interpolation == "hold" and inf.t.shape == (run.truth.n_days,)
    for t in (0, 100, 500):
        q = 0.0
        c = np.zeros(len(LIQUID_STATE_NAMES))
        for fid, ft in run.truth.feeds.items():
            spec = catalogue.feeds[fid]
            qk = ft.delivered_kg[t] / spec.density
            if qk > 0:
                c += qk * feed_concentrations(spec, run.truth.fractionations[fid], float(ft.ts[t]))
                q += qk
        assert inf.q[t] == pytest.approx(q)
        np.testing.assert_allclose(inf.concentrations[t], c / q, rtol=1e-12)
    assert np.all(inf.q > 0) and inf.concentrations[:, _L["X_xc"]].max() == 0.0
    assert run.truth.s_ca.shape == (run.truth.n_days,) and run.truth.s_ca.min() > 0
    # the truth N_I is the recipe's, between the per-feed values
    values = [catalogue.feeds[f].inert_N_I for f in run.truth.feeds]
    assert min(values) < run.truth.N_I < max(values)
    assert pytest.approx(0.06 / 14.0) == runs["C"].truth.N_I
    assert pytest.approx(0.001) == runs["A"].truth.N_I
    # moisture varies between deliveries and drifts with the season
    ts = run.truth.feeds["high_strength_waste"].ts
    assert ts.std() / ts.mean() > 0.2
    slurry_ts = runs["A"].truth.feeds["cattle_slurry"].ts
    summer = slurry_ts[200:260].mean()
    winter = slurry_ts[[*range(0, 30), *range(340, 400)]].mean()
    assert summer > winter  # driest deliveries in late summer (peak_doy 230)


def test_truth_model_integrates_the_generated_influent(runs, plants, adm1_params, rj2006_state):
    """Plant C, 30 d of generated influent, standard ADM1 sample-and-hold: a sane digester."""
    run = runs["C"]
    inf = run.truth.influent
    short = Influent(t=inf.t[:30], concentrations=inf.concentrations[:30], q=inf.q[:30])
    r = simulate(
        y0=rj2006_state,
        influent=short,
        params=adm1_params,
        plant=declared_geometry(plants["C"]),
        matrix=load_matrix(),
        solver=load_solver_config(),
        t_span=(0.0, 30.0),
        t_eval=np.arange(0.0, 31.0),
    )
    assert r.success and r.stats.n_segments == 30
    assert 6.8 < r.pH.min() <= r.pH.max() < 7.8
    assert r.q_gas.min() > 0 and np.all(np.isfinite(r.y))


# --------------------------------------------------------------------- assays


def test_assays_carry_units_lag_and_are_unbiased_and_tkn_is_the_per_feed_one(
    runs, catalogue, config, adm1_params
):
    run = runs["B"]
    assert run.observed.assays == tuple(
        sorted(run.observed.assays, key=lambda r: (r.report_day, r.feed_id, r.assay))
    )
    for rec in run.observed.assays:
        assert (rec.unit, rec.basis) == ASSAY_UNITS[rec.assay]
        assert rec.report_day - rec.sample_day == config.assays[rec.assay].lag_d
        assert rec.feed_id in run.truth.feeds
    # HSW is sampled on weekdays only, when delivered; FOG weekly
    day = np.arange(run.truth.n_days)
    hsw = [r for r in run.observed.assays if r.feed_id == "high_strength_waste" and r.assay == "ts"]
    assert all((r.sample_day % 7) < 5 for r in hsw)
    assert all(run.truth.feeds["high_strength_waste"].delivered_kg[r.sample_day] > 0 for r in hsw)
    fog = [r for r in run.observed.assays if r.feed_id == "fog" and r.assay == "cod"]
    assert all(r.sample_day % 7 == 0 for r in fog) and len(fog) > 50
    assert not any(r.assay == "alkalinity" for r in run.observed.assays if r.feed_id == "fog")
    # unbiased: the mean reported TS of primary sludge is the mean true TS on sampled days
    ps = [r for r in run.observed.assays if r.feed_id == "primary_sludge" and r.assay == "ts"]
    truth_ts = np.array([run.truth.feeds["primary_sludge"].ts[r.sample_day] for r in ps])
    assert np.mean([r.value for r in ps]) == pytest.approx(truth_ts.mean(), rel=0.01)
    assert np.std([r.value / t for r, t in zip(ps, truth_ts, strict=True)]) == pytest.approx(
        config.assays["ts"].cv, rel=0.2
    )
    # pH has absolute noise; VS is the catalogue's (dry basis)
    ph = [r.value for r in run.observed.assays if r.feed_id == "primary_sludge" and r.assay == "ph"]
    assert np.std(ph) == pytest.approx(config.assays["ph"].sd_abs, rel=0.2)
    vs = [r.value for r in run.observed.assays if r.feed_id == "primary_sludge" and r.assay == "vs"]
    assert np.mean(vs) == pytest.approx(catalogue.feeds["primary_sludge"].vs_of_ts, rel=0.01)
    # TKN: the per-feed (truth) value, not the BSM2-implied one, for a non-sludge feed
    spec = catalogue.feeds["high_strength_waste"]
    frac = run.truth.fractionations["high_strength_waste"]
    tkn = [
        r for r in run.observed.assays if r.feed_id == "high_strength_waste" and r.assay == "tkn"
    ]
    ts_hsw = run.truth.feeds["high_strength_waste"].ts
    n_aa = adm1_params.stoichiometry.N_aa
    ratio = np.array(
        [r.value / feed_tkn(spec, n_aa, frac, float(ts_hsw[r.sample_day])) for r in tkn]
    )
    assert ratio.mean() == pytest.approx(1.0, abs=0.01)
    fitted = implied_tkn(spec, adm1_params.stoichiometry)
    own = feed_tkn(spec, adm1_params.stoichiometry.N_aa)
    assert abs(fitted - own) / own > 0.15
    assert len(day) == run.truth.n_days
