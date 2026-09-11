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
    # a later stage cannot change an earlier one -- and since the lead's ruling 1 of
    # 2026-09-11 (prefix-stable child streams) no stage can change another feed's either.
    # fog sorts first: changing its delivery model (to a Markov chain with the same zero
    # fraction, so the plant check still passes) changes fog's own deliveries and nothing
    # else's, and changing its assay tuple changes fog's own assay noise and nobody else's,
    # leaving every delivery, every other feed's assays and the fractionation bit-identical
    gen = config.plants["B"]
    fog = gen.feeds["fog"]
    changed = gen.model_copy(
        update={
            "feeds": gen.feeds
            | {
                "fog": fog.model_copy(
                    update={
                        "delivery": DeliveryModel(
                            model="markov", zero_fraction=0.31, persistence=0.5, source="test"
                        ),
                        "assay_schedule": fog.assay_schedule.model_copy(update={"assays": ("ts",)}),
                    }
                )
            }
        }
    )
    cfg2 = config.model_copy(update={"plants": config.plants | {"B": changed}})
    d = generate_influent(plants["B"], catalogue, cfg2, adm1_params, seed=3, n_days=200)
    assert d.truth.fractionations == a.truth.fractionations
    assert not np.array_equal(d.truth.feeds["fog"].delivered_kg, a.truth.feeds["fog"].delivered_kg)
    for fid in ("high_strength_waste", "primary_sludge", "thickened_was"):
        np.testing.assert_array_equal(
            d.truth.feeds[fid].delivered_kg, a.truth.feeds[fid].delivered_kg
        )
        np.testing.assert_array_equal(d.truth.feeds[fid].ts, a.truth.feeds[fid].ts)
        np.testing.assert_array_equal(
            d.observed.feed_log_kg_wet_d[fid], a.observed.feed_log_kg_wet_d[fid]
        )
    # fewer fog assays used to shift the noise of every later feed's assays (one shared
    # stream); each assay now has its own child stream, so the other feeds' assay values
    # are bit-identical on the same sample days, and only fog's own set changed
    for fid in ("high_strength_waste", "primary_sludge", "thickened_was"):
        before = [r for r in a.observed.assays if r.feed_id == fid]
        after = [r for r in d.observed.assays if r.feed_id == fid]
        assert [(r.sample_day, r.assay, r.value) for r in before] == [
            (r.sample_day, r.assay, r.value) for r in after
        ]
    assert {r.assay for r in d.observed.assays if r.feed_id == "fog"} == {"ts"}
    assert {r.assay for r in a.observed.assays if r.feed_id == "fog"} > {"ts"}


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
    # partial (bicarbonate) alkalinity: all bicarbonate far above pK_a1, none far below
    assert bicarbonate_alkalinity(0.05, 9.0, 6.35) == pytest.approx(2.5, rel=3e-3)
    assert bicarbonate_alkalinity(0.05, 3.0, 6.35) < 0.01
    assert bicarbonate_alkalinity(0.0, 7.0, 6.35) == 0.0


# -------------------------------------------------- the assay describes what is fed

ASSAY_VS_CHARGE_RATIO = 1.5
"""Widest accepted ratio either way between a stream's alkalinity assay and its cation
charge (the lead's M2 ruling, 2026-09-09). Not a tuning knob: the two are the same
quantity by electroneutrality, and the slack is for the declared pH being a rounded
laboratory number rather than the exact root of the charge balance."""

ASSAY_VS_CHARGE_FLOOR = 0.10
"""kg CaCO3/m3 below which the ratio is meaningless and an absolute bound is used
instead. FOG carries no liquor at all -- no inorganic carbon, no ammoniacal N, equal
strong ions -- so both sides are zero and a ratio would be 0/0. The floor is two
orders of magnitude below the smallest real stream (primary sludge, 1.36), so it
cannot quietly admit a stream that has buffering to report.

**It is also the hole the ratio test alone had** (review finding B3, 2026-09-09): an
implementation returning 0.0 for both quantities is skipped by this floor on every
stream and passed the entire suite. :data:`COMMITTED_FEED_ALKALINITY` closes it."""

COMMITTED_FEED_ALKALINITY: dict[str, tuple[float, float]] = {
    #                          assay      charge   kg CaCO3/m3
    "cattle_slurry": (12.5030, 12.5037),
    "fog": (-0.0005, 0.0000),
    "food_waste": (7.5887, 7.7247),
    "grass_silage": (6.3575, 4.8990),
    # the assay moved with the HSW fractionation under the lead's ruling 5 of 2026-09-11
    # (inert 0.05 -> 0.16, classes scaled); it was 10.8735 with the 0.95 centre. The charge
    # reads s_cat, s_ca and TAN, none of which the ruling touched, and is unchanged.
    "high_strength_waste": (10.1750, 10.8720),
    "primary_sludge": (2.5028, 2.5027),
    "thickened_was": (2.0667, 2.0661),
}
"""Golden pins on the absolute value of both M2 quantities, kg CaCO3/m3 at catalogue TS.

These are the numbers ``docs/g1_anchor_report.md`` §3.3 quotes, so the report and the
code cannot drift apart, and **an implementation that returns a constant, a zero or a
copy of the other quantity fails here** rather than sliding through the ratio test.
Update them deliberately, with the reason, when a stream's declared composition moves --
that is the mechanism, not an obstacle to it.

**Moved twice, and these are the reasons.** On 2026-09-10 the lead ruled that ``s_ca`` is
*dissolved* calcium and is derived -- the calcite-saturated value at the declared pH,
solved jointly with the paired ``s_ic`` -- rather than the total-calcium-sized numbers the
catalogue had carried; every stream's charge fell with its calcium and the three derived
streams' assays fell with their re-paired inorganic carbon. Before that, on 2026-09-09,
the lead's B1 ruling corrected
:func:`~sim.influent.generator.feed_cation_charge` to carry the divalent calcium the
simulator is actually fed, which raised every charge, and approved redistributing the four
streams that then breached the band as paired ``s_cat`` + ``s_ic``. Every assay except
FOG's and the high-strength waste's moved with its stream's new inorganic carbon or
declared pH; ``food_waste`` and ``high_strength_waste`` moved on the charge side only,
because only their calcium term changed. The pins fired exactly as intended -- the
redistribution could not land without them being looked at."""


def test_every_feed_assay_describes_the_charge_the_simulator_is_fed(catalogue, adm1_params):
    """The visible alkalinity assay and the fed cation charge are the same quantity.

    **This is M2** (review finding of 2026-09-04, ruled 2026-09-09 as an amendment to
    ruling 3 of 2026-09-03). Ruling 3 raised the high-strength waste's ``s_cat`` from
    0.03 to 0.225 kmol/m3 to reach the anchor's alkalinity. The assay a workflow reads
    was the *bicarbonate* alkalinity of ``s_ic`` alone, which that calibration did not
    touch, so the visible number said 0.0214 kg CaCO3/m3 while the digester was handed
    10.75 -- a factor of **480** on the one stream the whole plant's buffering rests on.

    **Why it is on every stream, not just the HSW.** The failure was not that someone
    mis-typed a number; it was that two descriptions of one stream were free to drift
    apart because nothing compared them. A guard that only watched the stream that had
    already broken would let the next calibration break a different one silently.

    **What it catches.** Run it against the pre-ruling catalogue and it fails on two
    streams: the high-strength waste at **4.00x**, and ``food_waste`` at **0.33x** in
    the other direction (more acetate anion than cations to balance it). Against the
    pre-ruling *assay* -- bicarbonate alone -- the high-strength waste is out by
    **503x**.

    **What it does not catch, measured rather than asserted.** Perturbing ``s_cat`` by
    +/-50 % on the six streams a plant actually feeds gives 12 mutants; **10 fail here,
    1 is skipped by the floor (FOG, which has no liquor) and 1 survives** -- cattle
    slurry at half its cations moves 1.39x to 1.11x, *towards* the centre of the band.
    Perturbing ``s_ic`` or the declared pH is caught where a stream sits near the edge
    of the band and not where it has slack. **1.5x is a band, not an equality**, and a
    move that stays inside it is by design not a failure.

    This paragraph replaces a claim of "10 of 10 on five streams" that this session
    wrote and the review of 2026-09-09 (finding B3) corrected: it was 9 of 10 on the
    five non-FOG streams, and FOG is a Plant B feed, so there are six. A claim stated as
    a measurement has to be reproducible, and that one was not.

    **This test is NOT sufficient on its own** (finding B3). An implementation returning
    0.0 for both quantities is skipped by :data:`ASSAY_VS_CHARGE_FLOOR` on every stream
    and passed the whole suite when it was tried; so does ``total_alkalinity`` returning
    ``feed_cation_charge(...)``, which is exactly the vacuous definition the decisions
    entry claims to have rejected. Those two are killed by
    :func:`test_the_feed_alkalinity_assay_is_pinned_and_the_two_quantities_are_independent`,
    which has to be read as part of this guard rather than as a separate nicety.
    """
    from sim.influent.generator import feed_cation_charge, total_alkalinity

    failures = []
    for name, spec in sorted(catalogue.feeds.items()):
        assay = total_alkalinity(spec, spec.fractionation, adm1_params.physchem)
        charge = feed_cation_charge(spec, adm1_params.physchem)
        if max(abs(assay), abs(charge)) < ASSAY_VS_CHARGE_FLOOR:
            continue
        if assay <= 0.0:
            failures.append(
                f"{name}: assay {assay:.4f} kg CaCO3/m3 is not positive while the "
                f"simulator is fed {charge:.4f} kg CaCO3/m3 of cation charge"
            )
            continue
        ratio = charge / assay
        if not (1.0 / ASSAY_VS_CHARGE_RATIO <= ratio <= ASSAY_VS_CHARGE_RATIO):
            failures.append(
                f"{name}: assay {assay:.4f} kg CaCO3/m3 against charge "
                f"{charge:.4f} kg CaCO3/m3 -- {ratio:.2f}x, outside "
                f"{ASSAY_VS_CHARGE_RATIO:.1f}x (pH {spec.ph}, s_ic {spec.s_ic}, "
                f"s_cat {spec.s_cat}, s_an {spec.s_an}, tan {spec.tan})"
            )
    assert not failures, "assay and fed charge disagree:\n  " + "\n  ".join(failures)


def test_the_charge_consistency_survives_the_whole_range_of_deliveries(
    catalogue, config, adm1_params
):
    """The invariant holds for the assay a workflow READS, not only the catalogue row.

    **This is finding B2** (review of 2026-09-09, ruled 2026-09-10). The guard above is
    evaluated at catalogue solids. The assay a workflow actually reads is taken on a
    *delivery*, whose total solids swing by the generator's ``ts_log_sigma`` -- 0.47 on
    the high-strength waste, the largest in the catalogue. The free acetate scaled with
    that delivery's COD while the declared liquor did not scale at all, so a stream was
    **electroneutral only at catalogue TS** and its implied pH drifted with the weather.
    Measured on real ``AssayRecord``s before the fix: the high-strength waste 15.2 % of
    records outside 1.5x (worst 3.24x, assay spanning 6.12 to 38.03 against a fed charge
    of 11.75), primary sludge 45.1 %, cattle slurry 27.2 %.

    The lead's ruling made every dissolved species scale with the **liquor** rather than
    the solids (:func:`sim.influent.mapping.liquor_fraction`), which is what they are
    physically dissolved in. Both sides of the balance then carry the same factor, so the
    ratio is *exactly* invariant to solids rather than approximately so -- and this test
    asserts that at +/-3 sigma, wider than the +/-2 the ruling asked for, because an exact
    invariance does not need a margin.

    **What it cannot assert, and why that is right.** On the generated record the
    high-strength waste still shows a tail: 9.26 % of ``AssayRecord``s outside 1.5x. That
    is **not** the solids -- with the declared fractionation the ratio is 1.093 at every
    delivery, 0.00 % outside. It is the per-run Dirichlet draw of the *true* fractionation,
    on a stream whose composition is not measured at Muscatine and whose
    ``fractionation_concentration`` of 30 gives its 0.04 VFA share a standard deviation of
    about 0.035. The assay reports the true composition; the charge is computed from the
    declared one; the gap between them is the hidden-truth mismatch this benchmark exists
    to contain, and closing it would mean deleting the thing being measured. It is recorded
    as a finding in ``docs/g1_anchor_report.md``, and the band was **not** widened.
    """
    from sim.influent.generator import feed_cation_charge, total_alkalinity

    physchem = adm1_params.physchem
    sigma = {
        fid: feed.moisture.ts_log_sigma
        for plant in config.plants.values()
        for fid, feed in plant.feeds.items()
    }
    failures = []
    for name, spec in sorted(catalogue.feeds.items()):
        s = sigma.get(name)
        if s is None or abs(feed_cation_charge(spec, physchem)) < ASSAY_VS_CHARGE_FLOOR:
            continue  # not fed by any plant, or carries no liquor at all (FOG)
        for k in (-3.0, -1.0, 0.0, 1.0, 3.0):
            ts = spec.ts * np.exp(k * s)
            assay = total_alkalinity(spec, spec.fractionation, physchem, ts)
            charge = feed_cation_charge(spec, physchem, ts)
            ratio = charge / assay
            if not (1.0 / ASSAY_VS_CHARGE_RATIO <= ratio <= ASSAY_VS_CHARGE_RATIO):
                failures.append(
                    f"{name} at {k:+.0f} sigma (ts {ts:.4f}): assay {assay:.4f} against "
                    f"charge {charge:.4f} -- {ratio:.3f}x, outside {ASSAY_VS_CHARGE_RATIO}x"
                )
    assert not failures, "the charge balance drifts with the delivery:\n  " + "\n  ".join(failures)

    # the invariance is EXACT, not merely inside the band: a scaling applied to one side
    # and not the other would still pass the loop above on most streams
    for name, spec in sorted(catalogue.feeds.items()):
        s = sigma.get(name)
        if s is None or abs(feed_cation_charge(spec, physchem)) < ASSAY_VS_CHARGE_FLOOR:
            continue
        at = [
            feed_cation_charge(spec, physchem, spec.ts * np.exp(k * s))
            / total_alkalinity(spec, spec.fractionation, physchem, spec.ts * np.exp(k * s))
            for k in (-3.0, 0.0, 3.0)
        ]
        assert max(at) - min(at) < 1e-3, (name, at)

    # An invariance test alone cannot tell the correct scaling from NO scaling: a
    # liquor_fraction that always returned 1.0 leaves both sides constant and passes
    # everything above (checked by building that mutant and running it). So assert the
    # physics directly -- a drier delivery carries less water per m3 and therefore less
    # of every solute, and a wetter one more.
    from sim.influent.mapping import feed_concentrations, liquor_fraction

    spec = catalogue.feeds["high_strength_waste"]
    drier, wetter = spec.ts * 1.5, spec.ts * 0.5
    assert liquor_fraction(spec, drier) < 1.0 < liquor_fraction(spec, wetter)
    assert liquor_fraction(spec) == pytest.approx(1.0)
    idx = {n: i for i, n in enumerate(LIQUID_STATE_NAMES)}
    for state in ("S_cat", "S_an", "S_IN", "S_IC", "S_ac"):
        at_drier = feed_concentrations(spec, spec.fractionation, drier)[idx[state]]
        at_wetter = feed_concentrations(spec, spec.fractionation, wetter)[idx[state]]
        assert at_drier < at_wetter, state
    # ... while the particulate classes go the other way, with the solids
    for state in ("X_ch", "X_pr", "X_li", "X_I"):
        at_drier = feed_concentrations(spec, spec.fractionation, drier)[idx[state]]
        at_wetter = feed_concentrations(spec, spec.fractionation, wetter)[idx[state]]
        assert at_drier > at_wetter, state


def test_the_feed_alkalinity_assay_is_pinned_and_the_two_quantities_are_independent(
    catalogue, adm1_params
):
    """The M2 quantities have committed values and are computed from different fields.

    **Written because the ratio guard alone was vacuous** (review finding B3,
    2026-09-09). Two mutants were built and run, not reasoned about, and both passed the
    whole 337-test suite: ``total_alkalinity`` and ``feed_cation_charge`` each returning
    ``0.0`` (every stream then falls under :data:`ASSAY_VS_CHARGE_FLOOR` and is skipped),
    and ``total_alkalinity`` returning ``feed_cation_charge(...)`` -- which is precisely
    the strong-ion-difference definition the decisions entry rejects on the grounds that
    a test of it "could not fail". Nothing anywhere pinned the absolute value of the feed
    alkalinity assay, so nothing could tell the difference.

    Three properties, each killing one class of mutant:

    1. **Committed values.** :data:`COMMITTED_FEED_ALKALINITY` holds both numbers for
       every stream, and they are the numbers ``docs/g1_anchor_report.md`` §3.3 quotes.
       Kills zero, a constant, and a silent formula change.
    2. **Different fields.** ``s_ic`` moves the assay and leaves the charge alone;
       ``s_cat`` moves the charge and leaves the assay alone. Kills the copy mutant --
       if the assay *were* the strong-ion difference, ``s_cat`` would move both.
    3. **Reproduced from the constants**, for one stream, without calling the
       implementation. Kills a wrong equilibrium constant or a missing term.
    """
    from sim.influent.generator import feed_cation_charge, total_alkalinity

    physchem = adm1_params.physchem
    assert set(COMMITTED_FEED_ALKALINITY) == set(catalogue.feeds), (
        "a stream was added or removed; pin it here deliberately"
    )

    # 1. committed absolute values -- a zero, a constant or a copy fails here
    for name, (assay, charge) in sorted(COMMITTED_FEED_ALKALINITY.items()):
        spec = catalogue.feeds[name]
        assert total_alkalinity(spec, spec.fractionation, physchem) == pytest.approx(
            assay, abs=5e-4
        ), name
        assert feed_cation_charge(spec, physchem) == pytest.approx(charge, abs=5e-4), name

    # 2. the two read different fields, so one cannot be the other
    spec = catalogue.feeds["high_strength_waste"]
    more_ic = spec.model_copy(update={"s_ic": spec.s_ic * 2.0})
    more_cat = spec.model_copy(update={"s_cat": spec.s_cat * 2.0})
    base_assay = total_alkalinity(spec, spec.fractionation, physchem)
    base_charge = feed_cation_charge(spec, physchem)
    assert total_alkalinity(more_ic, more_ic.fractionation, physchem) > base_assay * 1.5
    assert feed_cation_charge(more_ic, physchem) == pytest.approx(base_charge)
    assert feed_cation_charge(more_cat, physchem) > base_charge * 1.5
    assert total_alkalinity(more_cat, more_cat.fractionation, physchem) == pytest.approx(base_assay)

    # 3. one stream reproduced from the constants, independently of the implementation
    h = 10.0**-spec.ph
    k_co2, k_ac = 10.0**-6.35, 10.0**-4.76
    s_ac = spec.cod_per_m3 * spec.fractionation.f_vfa / 64.0
    expected = 50.0 * (
        spec.s_ic * k_co2 / (k_co2 + h) + s_ac * k_ac / (k_ac + h) + 10.0**-14.0 / h - h
    )
    assert base_assay == pytest.approx(expected, rel=1e-9)
    assert (10.0**-physchem.pK_a_co2_base, 10.0**-physchem.pK_a_ac) == pytest.approx(
        (k_co2, k_ac)
    ), "the literals above are the ADM1 base constants; if those moved, this must be re-derived"


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


def test_truth_model_integrates_the_generated_influent(
    runs, plants, catalogue, adm1_params, rj2006_state
):
    """Plant C, 30 d of generated influent through ADM1 with the truth N_I: a sane digester.

    Loading-referenced: methane COD produced (days 10-30, dry STP CH4 / 0.35 m3 per kg
    COD) over COD fed lies in a yield band, and doubling the fed COD doubles the methane
    (the BSM2 steady state is not far from this loading, so the window is representative).
    """
    from sim.influent import COD_STATES, truth_parameters

    run = runs["C"]
    inf = run.truth.influent
    truth = truth_parameters(
        adm1_params, catalogue, run.truth.mean_recipe_kg_d, run.truth.fractionations.fractionations
    )
    assert pytest.approx(run.truth.N_I) == truth.stoichiometry.N_I
    cod_idx = [_L[n] for n in COD_STATES]

    def methane_per_cod(scale: float, sane: bool = True) -> tuple[float, float]:
        conc = inf.concentrations[:30].copy()
        conc[:, cod_idx] *= scale
        short = Influent(t=inf.t[:30], concentrations=conc, q=inf.q[:30])
        r = simulate(
            y0=rj2006_state,
            influent=short,
            params=truth,
            plant=declared_geometry(plants["C"]),
            matrix=load_matrix(),
            solver=load_solver_config(),
            t_span=(0.0, 30.0),
            t_eval=np.arange(0.0, 31.0),
        )
        assert r.success and r.stats.n_segments == 30
        assert np.all(np.isfinite(r.y))
        if sane:
            assert 6.8 < r.pH.min() <= r.pH.max() < 7.8
            assert r.q_gas.min() > 0
        ch4_m3_d = r.q_gas_stp_dry * r.p_ch4 / (r.P_gas - r.p_h2o)
        cod_out = float(ch4_m3_d[10:].mean()) / 0.35  # kg COD/d as methane
        cod_in = float((short.q * conc[:, cod_idx].sum(axis=1)).mean())
        return cod_out, cod_in

    out1, in1 = methane_per_cod(1.0)
    assert 0.40 < out1 / in1 < 0.70  # measured 0.55; degradable ~0.6-0.7 less biomass yield
    out2, _ = methane_per_cod(2.0)
    assert 1.7 < out2 / out1 < 2.2  # measured 1.99
    # a 10x overload sours the digester (pH < 5) and fails the yield band: not vacuous
    assert not (0.40 < methane_per_cod(10.0, sane=False)[0] / (10.0 * in1) < 0.70)


def test_weekly_schedule_survives_a_weekend_start(plants, catalogue, config, adm1_params):
    """Assays are anchored to the first eligible day, whatever weekday the horizon starts."""
    counts = {}
    for start_weekday in range(7):
        a = generate_influent(
            plants["A"], catalogue, config, adm1_params, seed=5, n_days=365,
            start_weekday=start_weekday,
        )  # fmt: skip
        silage = [r for r in a.observed.assays if r.feed_id == "grass_silage" and r.assay == "ts"]
        counts[start_weekday] = len(silage)
        assert all(((start_weekday + r.sample_day) % 7) < 5 for r in silage)
        assert len({r.sample_day % 7 for r in silage}) == 1  # one fixed weekday
        # only logged deliveries are sampled: never a record on a day whose log reads 0
        for r in a.observed.assays:
            assert a.observed.feed_log_kg_wet_d[r.feed_id][r.sample_day] > 0.0
        b = generate_influent(
            plants["B"], catalogue, config, adm1_params, seed=5, n_days=365,
            start_weekday=start_weekday,
        )  # fmt: skip
        fog = [r for r in b.observed.assays if r.feed_id == "fog" and r.assay == "cod"]
        assert 40 <= len(fog) <= 53, (start_weekday, len(fog))
    assert min(counts.values()) >= 50 and max(counts.values()) <= 53, counts


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


def test_a_longer_horizon_extends_the_same_realisation(plants, catalogue, config, adm1_params):
    """The lead's ruling 1 (2026-09-11): the generator is prefix-stable in the horizon.

    Until then every block was drawn in sequence from one stream, so a block of length
    ``n_days`` shifted every later block and a change of horizon re-rolled every feed from
    day 0 -- each horizon was a different realisation of the same seed, and the anchored
    ``biogas_mean`` jumped by 5 % between horizons ten days apart
    (docs/f2_horizon_report.md sections 14-15). Now the first n days of a longer run ARE the
    n-day run: deliveries, moisture, the operator's log, the true fractionation and the
    assays, on both a plant with a blend tank and one without.
    """
    for pid in ("B", "A"):
        short = generate_influent(plants[pid], catalogue, config, adm1_params, seed=11, n_days=90)
        longer = generate_influent(plants[pid], catalogue, config, adm1_params, seed=11, n_days=130)
        assert (
            short.truth.fractionations.fractionations == longer.truth.fractionations.fractionations
        )
        for fid, feed in short.truth.feeds.items():
            other = longer.truth.feeds[fid]
            np.testing.assert_array_equal(feed.delivered_kg, other.delivered_kg[:90])
            np.testing.assert_array_equal(feed.ts, other.ts[:90])
            assert feed.unrecorded_days == tuple(d for d in other.unrecorded_days if d < 90)
            assert feed.mislogged_days == tuple(d for d in other.mislogged_days if d < 90)
        np.testing.assert_array_equal(short.truth.influent.q, longer.truth.influent.q[:90])
        np.testing.assert_array_equal(
            short.truth.influent.concentrations, longer.truth.influent.concentrations[:90]
        )
        early = [r for r in longer.observed.assays if r.sample_day < 90]
        assert [(r.feed_id, r.assay, r.sample_day, r.value) for r in short.observed.assays] == [
            (r.feed_id, r.assay, r.sample_day, r.value) for r in early
        ]
        # and the two horizons are still two different runs beyond the shared prefix: the
        # negative control, so this cannot pass on a generator that ignores its horizon
        assert longer.truth.influent.q.size == 130
        assert not np.array_equal(longer.truth.influent.q[90:130], longer.truth.influent.q[50:90])
