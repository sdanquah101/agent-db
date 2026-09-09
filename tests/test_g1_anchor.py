"""Gate G1's realism check, as a test that recomputes the report.

``docs/g1_anchor_report.md`` is the deliverable; this is what stops it rotting. The block
between the report's markers is recomputed here and compared verbatim with the committed
file, exactly as ``tests/test_faults.py`` does for the benchmark card's fault table.

Three things are asserted, and the third is the awkward one:

1. **The influent statistics are inside their declared tolerances.** That is gate G1's
   literal criterion, and it passes.
2. **The tolerances are declared, not fitted.** Every entry of ``TOLERANCES`` carries a
   rationale, and the ones borrowed from existing tests really are the numbers those tests
   apply — checked against the test files themselves, so widening a bound "for consistency"
   does not go unnoticed.
3. **The recorded gaps are pinned in both directions.** This used to read "the rows that
   fail are asserted to fail": the simulated VFA and FOS/TAC sat far below the plant's, and
   the failure and its size were pinned so that nobody could "fix" the gap by widening a
   bound or tuning a feed value without a test noticing. That worked exactly as intended —
   the gap closed, this test failed, and the record was updated with the reason. What
   closed it was **not** the model: our FOS/TAC was computed from true VFA and the plant's
   from a titrimetric FOS, so the row compared two different assays. Since the lead's
   ruling A of 2026-09-09 both sides are titrimetric (declared chemistry, no fitted
   parameter), and what is pinned now is the **residual ~1.5x gap** that remains, in both
   directions. The **alkalinity** row is inside its bound by calibration to that very
   column and is never counted as a match.

The panel of Level-0 runs costs ~90 s, so it is a module fixture.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from anchor.compare_generated import (
    OUTPUT_PANEL_SEEDS,
    TOLERANCES,
    anchor_available,
    anchor_statistics,
    compare,
    extract_block,
    generated_influent_statistics,
    generated_output_statistics,
    match_count,
    output_panel,
    render_report,
    report_block,
)
from tests.conftest import REPO_ROOT

REPORT = REPO_ROOT / "docs" / "g1_anchor_report.md"

pytestmark = [
    pytest.mark.g1,
    pytest.mark.skipif(not anchor_available(), reason="Muscatine daily file not present"),
]


@pytest.fixture(scope="module")
def panel():
    return output_panel()


@pytest.fixture(scope="module")
def measured(panel):
    generated = {**generated_influent_statistics(), **generated_output_statistics(panel=panel)}
    return generated, anchor_statistics()


@pytest.fixture(scope="module")
def comparisons(measured):
    return compare(*measured)


# ------------------------------------------------------------------ 1. the gate


def test_every_influent_statistic_is_inside_its_declared_tolerance(comparisons):
    """Gate G1: "the influent statistics match the anchor within declared tolerance"."""
    influent = [
        c
        for c in comparisons
        if c.name.startswith(("feed_volume", "delivery_zero", "vs_fraction", "hsw_cod"))
        or c.name in {"total_feed_flow_median", "organic_loading_rate"}
    ]
    assert len(influent) >= 17, len(influent)
    outside = [
        (c.name, c.generated, c.anchor, c.tolerance.describe()) for c in influent if not c.passed
    ]
    assert not outside, outside


def test_the_biogas_the_simulator_makes_is_the_biogas_the_plant_measures(comparisons):
    biogas = next(c for c in comparisons if c.name == "biogas_mean")
    assert biogas.passed, (biogas.generated, biogas.anchor)


# ------------------------------------------------------------------ 2. declared, not fitted


def test_every_tolerance_carries_a_rationale():
    for tol in TOLERANCES:
        assert tol.rationale and len(tol.rationale) > 40, tol.name
        assert tol.kind in {"relative", "absolute", "ratio_band"}


def test_the_inherited_bounds_are_the_ones_the_other_tests_apply():
    """The feed rows borrow their bounds; this checks they were not quietly widened.

    ``tests/test_generator.py`` applies rel=0.15 to the delivery medians, rel=0.3 to the
    log spreads and abs=0.04 to the zero fractions, and ``tests/test_plausibility.py``
    applies 0.6-1.5 to the generator-driven biogas ratio. Those literals are read out of
    the test files rather than restated here.
    """
    generator = (REPO_ROOT / "tests" / "test_generator.py").read_text(encoding="utf-8")
    plausibility = (REPO_ROOT / "tests" / "test_plausibility.py").read_text(encoding="utf-8")
    assert "rel=0.15" in generator and "rel=0.3)" in generator and "abs=0.04" in generator
    assert '0.6 < d["q_gas_stp_dry"][settled].mean() / measured < 1.5' in plausibility

    by_name = {t.name: t for t in TOLERANCES}
    assert by_name["feed_volume_median_fog"].bound == 0.15
    assert by_name["feed_volume_log_sigma_fog"].bound == 0.30
    assert by_name["delivery_zero_fraction_fog"].bound == 0.04
    assert by_name["biogas_mean"].bound == (0.6, 1.5)


def test_a_row_calibrated_to_the_anchor_is_never_counted_as_a_match(comparisons):
    """The lead's ruling M1 (2026-09-04): a fit is not evidence.

    ``alkalinity_median`` is the case: under ruling 3 of 2026-09-03 the Muscatine feeds'
    `S_cat` was fitted to this very column, so the row agreeing with it says the fit
    converged, not that the simulator reproduces a measurement it was not shown. It stays
    in the report — a large residual would still be a finding — but it is labelled
    ``calibrated to anchor``, never ``pass``, and it is out of the match count.
    """
    calibrated = [t for t in TOLERANCES if t.calibrated]
    assert [t.name for t in calibrated] == ["alkalinity_median"]
    assert "CALIBRATED" in calibrated[0].rationale
    # the superseded rationale asserted the opposite; it may be quoted as superseded, but
    # not stated. It read "...which the catalogue carries as design values ... rather than
    # fits", and the row must not be able to drift back to claiming that.
    assert "which the catalogue carries as design values" not in calibrated[0].rationale
    assert "became false" in calibrated[0].rationale

    matched, independent, excluded = match_count(comparisons)
    assert excluded == 1
    assert independent == len(comparisons) - 1
    # every independent row is inside its bound since the VFA convention was corrected
    # (lead's ruling A, 2026-09-09); before that, vfa_median and fos_tac_median were not
    assert matched == independent, (matched, independent)
    rendered = render_report(comparisons)
    assert "| calibrated to anchor |" in rendered
    assert f"**{matched} of {independent} independent rows" in rendered
    # and the count really excludes it: adding it back would change the total
    assert matched < sum(1 for c in comparisons if c.passed)


def test_a_tolerance_actually_bites():
    """A bound that accepted anything would make every row above meaningless."""
    by_name = {t.name: t for t in TOLERANCES}
    relative = by_name["total_feed_flow_median"]
    assert relative.check(100.0, 95.0)
    assert not relative.check(150.0, 95.0)
    absolute = by_name["digester_pH_median"]
    assert absolute.check(7.0, 7.27)
    assert not absolute.check(6.0, 7.27)
    band = by_name["fos_tac_median"]
    assert band.check(0.30, 0.23)
    assert not band.check(0.04, 0.23)
    assert not band.check(float("nan"), 0.23)


# ------------------------------------------------------------------ 3. the recorded gaps


def test_the_vfa_rows_now_compare_like_with_like_and_the_residual_gap_is_pinned(comparisons):
    """The recorded realism gap, after the convention on our side was corrected.

    **History, because this test used to assert the opposite.** It pinned `vfa_median` and
    `fos_tac_median` as FAILING, and their size in both directions, so that closing the gap
    would fail a test and force the record to be updated rather than letting a quiet tuning
    pass unnoticed. That is exactly what happened, and this is the updated record.

    What changed is **not** the model and **not** a bound. Our `fos_tac` was computed from
    TRUE VFA and the anchor's from a TITRIMETRIC FOS, so the row compared two different
    assays and was a factor of 17.5 out for that reason. Since the lead's ruling A of
    2026-09-09 both sides are titrimetric. The transfer function has no fitted parameter —
    kappa frozen at 1.0, every equilibrium constant the truth model's own — so this is a
    measurement model being made correct, not a gap being closed by tuning.

    **No kinetic parameter has moved at any point**, and `docs/vfa_gap.md` still holds: the
    true-VFA gap cannot be closed by fitting, because the model is bistable in `k_m_ac` and
    the anchor lies between the branches. That is now a finding about the model rather than
    a failing row.

    A residual gap of about 1.5x remains and is pinned here in both directions, so it can
    neither grow nor be quietly tuned to 1.0.
    """
    by_name = {c.name: c for c in comparisons}
    vfa, fos = by_name["vfa_median"], by_name["fos_tac_median"]
    alkalinity = by_name["alkalinity_median"]

    # the alkalinity row is inside its bound by CALIBRATION to this very column, so it is
    # reported and never counted as a match (the lead's ruling M1)
    assert alkalinity.tolerance.calibrated
    assert alkalinity.passed, (alkalinity.generated, alkalinity.anchor)

    # both VFA rows are now inside their (untouched) bounds
    assert vfa.passed and fos.passed, (vfa.ratio, fos.ratio)
    assert by_name["vfa_median"].tolerance.bound == (0.25, 4.0)  # never widened
    assert by_name["fos_tac_median"].tolerance.bound == (0.5, 2.0)  # never widened

    # ... and the RESIDUAL gap is pinned in both directions. It is a real remaining
    # discrepancy, not a success: the simulator still carries less titratable acid than the
    # plant. If it closes, or widens, the record must be updated with it.
    assert 0.55 < vfa.ratio < 0.80, vfa.ratio
    assert 0.50 < fos.ratio < 0.80, fos.ratio
    residual = vfa.anchor / vfa.generated
    assert 1.25 < residual < 1.85, residual  # ~1.5x, was 17.5x on the true-VFA convention

    # the anchor is unchanged, which is what makes the ratios comparable with the record
    assert 1.1 < vfa.anchor < 1.25, vfa.anchor
    assert 0.20 < fos.anchor < 0.26, fos.anchor


def test_the_titrimetric_reading_is_mostly_bicarbonate_and_that_is_the_finding(panel):
    """The lead's ruling D: the convention MASKS the dynamics it is meant to report.

    An earlier diagnosis called this a "variance deficit" in the model. That was wrong and
    is not recorded as a model finding: true VFA is if anything MORE variable than the
    plant's FOS/TAC. What is flat is the titrimetric reading, and it is flat *because* most
    of it is bicarbonate carry-over tracking slowly-varying alkalinity.

    This is the measurement that makes the claim checkable rather than asserted, and it is
    also the independent justification for triggering conditional missingness on the hidden
    state (ruling B) rather than on this reading.
    """
    sound = [r for r in panel if r.sound]
    assert sound

    titrimetric = np.array([r.statistics["vfa_median"] for r in sound])
    true_vfa = np.array([r.statistics["vfa_true_median"] for r in sound])
    # the reading is several times the true VFA, and overwhelmingly so
    assert (titrimetric > 5.0 * true_vfa).all(), (titrimetric, true_vfa)

    # the reading is flat while the process is not: the titrimetric FOS/TAC's spread across
    # the panel is far smaller than the true-VFA ratio's
    fos = np.array([r.statistics["fos_tac_median"] for r in sound])
    true_ratio = np.array([r.statistics["fos_tac_true_vfa_median"] for r in sound])
    spread = float(fos.std() / fos.mean())
    true_spread = float(true_ratio.std() / true_ratio.mean())
    assert spread < true_spread, (spread, true_spread)


def test_no_clean_level_0_seed_sours(panel):
    """The lead's acceptance condition for Plant B (ruling 1, 2026-09-03).

    Before the changes of that date, Plant B acidified on 5 of 12 clean Level-0 seeds.
    Two independent corrections were made and **either one alone is sufficient**, measured
    on the twelve-seed panel with the other held back:

    ============================  ==========  ==========
    ..                            no tank     with tank
    ============================  ==========  ==========
    original strong cations       7/12 sound  12/12
    anchor-calibrated cations     12/12       12/12
    ============================  ==========  ==========

    with the worst-case minimum pH going 4.50 -> 6.53 (tank alone), 7.06 (calibration
    alone) and 7.13 (both). The panel is now twenty-four seeds, because twelve could show a
    40 % failure rate but could not support a claim that the rate is zero.

    This asserts the condition itself, and the margin: a run that merely scrapes over the
    soundness threshold would satisfy "no seed sours" while being one bad week from not.
    """
    assert len(panel) == len(OUTPUT_PANEL_SEEDS) == 24
    soured = [r.seed for r in panel if not r.sound]
    assert not soured, f"clean Level-0 seeds that soured: {soured}"
    ph = [r.statistics["digester_pH_median"] for r in panel]
    ch4 = [r.statistics["ch4_fraction_median"] for r in panel]
    assert min(ph) > 7.0, min(ph)  # not merely above the 6.5 threshold
    assert min(ch4) > 0.65, min(ch4)
    assert max(ph) < 7.7, max(ph)  # ... and not over-buffered into a different plant


def test_the_missingness_trigger_fires_at_about_the_anchors_own_rate(panel):
    """The lead's ruling B (2026-09-09), and the scenario it gives back to the benchmark.

    **This test used to assert the opposite** — that the overload flag fired on *no day at
    all* on a healthy Plant B, which meant conditional missingness (§6.1) and the whole of
    the Level-4 `informative_missingness` row (S4-02) had nothing to act on. That was
    pinned as a real cost, and it is now paid back.

    Two changes did it, neither of them to the digester. The flag triggers on the **hidden
    process state** — true VFA above 2.00x its own 30-day trailing median — instead of on a
    reported ratio; and the reported ratio it used to read is 86-90 % bicarbonate carry-over,
    which *masks* the VFA dynamics the flag exists to detect. The trigger now fires on about
    the same fraction of days the plant's own FOS/TAC column exceeds its 92nd percentile, at
    a cut-off nobody tuned.

    Both rates are pinned, because they are different things (ruling C) and either drifting
    would matter.
    """
    assert all(r.sound for r in panel)

    trigger = sorted(r.statistics["overload_day_fraction"] for r in panel)
    pooled = sum(trigger) / len(trigger)
    # the anchor's own exceedance is 7.78-9.18 % depending on the digester and the filter
    assert 0.05 < pooled < 0.11, trigger
    assert all(f > 0.0 for f in trigger), trigger  # EVERY sound run has stressed days now
    assert min(trigger) > 0.01 and max(trigger) < 0.25, trigger
    # ... which is what S4-02 needs: a fault that scales this flag has something to scale
    assert sum(f > 0.02 for f in trigger) == len(trigger), trigger

    # the OPERATOR-VISIBLE threshold is a separate quantity and still fires rarely, because
    # the simulated titrimetric FOS/TAC distribution sits ~1.5x below the plant's. That is
    # the residual gap, recorded rather than closed by moving the threshold.
    operator = sorted(r.statistics["fos_tac_exceedance_fraction"] for r in panel)
    assert sum(operator) / len(operator) < 0.02, operator
    assert pooled > 10.0 * (sum(operator) / len(operator)), (pooled, operator)


# ------------------------------------------------------------------ the report


def test_the_report_exists_and_its_generated_block_is_current(comparisons, panel, measured):
    """The committed report is what this code produces today, character for character."""
    generated, _ = measured
    extra = {k: v for k, v in generated.items() if k not in {c.name for c in comparisons}}
    expected = report_block(comparisons, panel, extra)
    committed = extract_block(REPORT.read_text(encoding="utf-8"))
    assert committed == expected, (
        "docs/g1_anchor_report.md is stale; regenerate it with `python scripts/g1_report.py`"
    )


def test_the_report_says_what_closing_the_gap_would_take():
    """The task of a report is not only to record a number.

    **This guard caught a real omission and the report was fixed, not the test.** The
    original required "declared before anything was measured", "fos/tac", "sour" and
    "closing". The titrimetric convention of 2026-09-09 took the gap from 17.5x to 1.52x,
    the report was rewritten around that, and the section on what closing the REMAINDER
    would take went with it — so "closing" disappeared and this failed. The report now has
    §6.1, which says what the residual is (non-VFA titratable species ADM1 does not carry)
    and what closing it would take (a fitted kappa, rejected because ruling M1 would then
    exclude the row from the match count; or a new extension, Phase 2 at the earliest).

    The four original phrases are **kept**, because relaxing an assertion to make a rewrite
    pass is the one thing this guard exists to prevent. They are joined by the substance a
    reader now needs, each paired with the reason it is required — a single keyword can be
    satisfied by the keyword alone, which is how the section came to be missing while three
    of the four phrases still matched.
    """
    text = REPORT.read_text(encoding="utf-8").lower()
    required = {
        # the four the guard has always required
        "the tolerances are declared in advance": "declared before anything was measured",
        "the ratio is named": "fos/tac",
        "the souring history is kept": "sour",
        "what closing the gap would take is stated": "closing",
        # and the substance the rewrite made necessary
        "the two conventions are named": "titrimetric",
        "the reading is mostly bicarbonate": "carry-over",
        "the residual gap is quantified": "1.52",
        "kinetics are shown not to close it": "bistable",
        "the discipline is stated": "no kinetic parameter",
        "the gap list is cited": "vfa_gap.md",
        "the threshold's basis is given": "92nd percentile",
    }
    missing = {why: phrase for why, phrase in required.items() if phrase not in text}
    assert not missing, missing


def test_the_report_is_generated_by_a_script_that_exists():
    assert (REPO_ROOT / "scripts" / "g1_report.py").is_file()
    assert Path(REPORT).is_file()
