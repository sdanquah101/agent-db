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
3. **The rows that fail are asserted to fail.** The simulated VFA and FOS/TAC distributions
   sit far below the plant's; that is a recorded realism gap in the truth model
   (``docs/decisions.md``). Pinning the failure is deliberate. A test that merely allowed
   it would let someone "fix" the gap by widening a bound or tuning a feed value and never
   notice; this one fails if the numbers move in *either* direction, which is the only way
   a known-bad row stays honest. The **alkalinity** half of that gap is closed, by the
   calibration the lead approved on 2026-09-03, and is now asserted to *pass*.

The panel of Level-0 runs costs ~90 s, so it is a module fixture.
"""

from __future__ import annotations

from pathlib import Path

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
    assert matched == independent - 2  # vfa_median and fos_tac_median, and nothing else
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


def test_the_vfa_and_fos_tac_rows_still_fail_and_by_how_much(comparisons):
    """The recorded realism gap, pinned in both directions.

    A healthy simulated digester carries far less residual VFA than the plant, so FOS/TAC
    is far below the plant's median. The decisions log of 2026-09-02 recorded 0.01-0.07
    against an anchor median of 0.23. This asserts the failure *and* its size, so closing
    the gap fails this test and forces the record to be updated rather than letting a
    quiet tuning pass unnoticed.
    """
    by_name = {c.name: c for c in comparisons}
    vfa, fos = by_name["vfa_median"], by_name["fos_tac_median"]
    alkalinity = by_name["alkalinity_median"]
    # the alkalinity half of the gap IS closed — but by CALIBRATION to this very column,
    # so the residual says the fit converged and not that the simulator agrees with a
    # measurement it was not shown (the lead's ruling M1)
    assert alkalinity.tolerance.calibrated
    assert alkalinity.passed, (alkalinity.generated, alkalinity.anchor)
    assert not vfa.passed and not fos.passed
    assert 0.0 < vfa.ratio < 0.25, vfa.ratio  # the generated median is at most a quarter
    assert 0.0 < fos.ratio < 0.5, fos.ratio
    assert 0.005 < fos.generated < 0.05, fos.generated
    assert 0.20 < fos.anchor < 0.26, fos.anchor  # and the anchor's own 0.23


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


def test_the_overload_flag_never_fires_on_a_healthy_plant_b(panel):
    """The measured consequence of the VFA gap, and it costs the benchmark a scenario.

    The overload flag fires when FOS/TAC exceeds 0.40. Across the whole panel of sound runs
    it fires on **no day at all**, against ~8 % of the plant's own days. Conditional
    missingness — the §6.1 property that instruments fail during the transients that
    identify the process, and the entire subject of the Level-4 `informative_missingness`
    row (S4-02) — therefore has nothing to act on anywhere on a healthy Plant B.

    Pinned because it is a property of the truth model rather than of the missingness code,
    and because whatever closes the VFA gap must update this record.
    """
    assert all(r.sound for r in panel)
    overload = sorted(r.statistics["overload_day_fraction"] for r in panel)
    assert overload[len(overload) // 2] == 0.0, overload  # the median run: never
    assert sum(f == 0.0 for f in overload) > 0.5 * len(overload), overload  # most runs: never
    assert max(overload) < 0.05, overload  # the worst run: 3.3 %, against the plant's ~8 %
    assert max(r.statistics["fos_tac_median"] for r in panel) < 0.05


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
    """The task of a report is not only to record the failure."""
    text = REPORT.read_text(encoding="utf-8").lower()
    for phrase in ("declared before anything was measured", "fos/tac", "sour", "closing"):
        assert phrase in text, phrase


def test_the_report_is_generated_by_a_script_that_exists():
    assert (REPO_ROOT / "scripts" / "g1_report.py").is_file()
    assert Path(REPORT).is_file()
