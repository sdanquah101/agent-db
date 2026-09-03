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
   (``docs/decisions.md``, 2026-09-02). Pinning the failure is deliberate. A test that
   merely allowed it would let someone "fix" the gap by widening a bound or tuning a feed
   value and never notice; this one fails if the numbers move in *either* direction, which
   is the only way a known-bad row stays honest.

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
    output_panel,
    report_block,
)
from tests.conftest import REPO_ROOT

REPORT = REPO_ROOT / "docs" / "g1_anchor_report.md"

pytestmark = pytest.mark.skipif(not anchor_available(), reason="Muscatine daily file not present")


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
    assert not vfa.passed and not fos.passed
    assert 0.0 < vfa.ratio < 0.25, vfa.ratio  # the generated median is at most a quarter
    assert 0.0 < fos.ratio < 0.5, fos.ratio
    assert 0.005 < fos.generated < 0.12, fos.generated  # the recorded 0.01-0.07 band, widened
    assert 0.20 < fos.anchor < 0.26, fos.anchor  # and the anchor's own 0.23


def test_plant_b_sours_on_a_material_fraction_of_seeds(panel):
    """The finding of this session, pinned so it cannot be forgotten or quietly fixed.

    Plant B acidifies on several of the twelve declared Level-0 seeds under the frozen feed
    catalogue and influent generator. It reproduces without the harness (declared geometry,
    published initial state, no burn-in), so it is a property of the configuration; and
    ``tests/test_plausibility.py`` missed it because it tests one seed.

    If a change makes Plant B sound on every seed, this test fails and the report, the
    decisions log and the benchmark card must be updated to say so — which is the point.
    """
    sound = [r for r in panel if r.sound]
    assert len(panel) == len(OUTPUT_PANEL_SEEDS) == 12
    assert 4 <= len(sound) <= 10, [r.seed for r in sound]
    soured = [r for r in panel if not r.sound]
    assert soured, "Plant B no longer sours; update docs/g1_anchor_report.md and decisions.md"
    for run in soured:
        assert run.statistics["digester_pH_median"] < 6.0
        assert run.statistics["ch4_fraction_median"] < 0.55
    for run in sound:
        assert run.statistics["digester_pH_median"] > 6.8
        assert run.statistics["ch4_fraction_median"] > 0.60


def test_the_overload_flag_is_all_or_nothing_across_the_panel(panel):
    """The Level-4 informative-missingness row needs the flags to fire, and they barely do.

    The review of PR #11 predicted the overload flag would fire on far fewer simulated days
    than the anchor's ~8 %. Measured on the panel, the picture is bimodal rather than
    uniformly low: **five of the seven sound runs never raise it at all** and the other two
    raise it on 8.6 % and 9.3 % of days, which is about the plant's own rate; every soured
    run raises it on more than half of its days, and three of the five on every day.

    So S4-02, the row whose whole subject is instruments failing during the transients that
    identify the process, has nothing to act on in most healthy runs and far too much in a
    crashed one. Pinned here because it is a property of the truth model, not of the
    missingness code, and because a change that fixes it must update the record.
    """
    sound = sorted(r.statistics["overload_day_fraction"] for r in panel if r.sound)
    soured = sorted(r.statistics["overload_day_fraction"] for r in panel if not r.sound)
    assert sound[len(sound) // 2] == 0.0, sound  # the median sound run never overloads
    assert sum(f == 0.0 for f in sound) >= len(sound) // 2, sound
    assert 0.05 < max(sound) < 0.15, sound  # ... and the ones that do are near the plant's 8 %
    assert min(soured) > 0.5, soured


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
