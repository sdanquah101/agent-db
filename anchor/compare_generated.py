"""Gate G1's realism check: generated statistics against the Muscatine anchor.

Gate G1 (proposal §11) is "*every scenario generates, with hidden truth logged separately
from observations, and the influent statistics match the anchor within declared
tolerance*". This module is the last clause, and its whole discipline is in one word:
**declared**. :data:`TOLERANCES` is written before anything is measured, every entry says
where its bound comes from, and :func:`compare` then reports pass or fail without a bound
ever being adjusted to suit a number. ``docs/g1_anchor_report.md`` is generated from the
result and ``tests/test_g1_anchor.py`` recomputes it, so the report cannot rot and a
tolerance cannot be widened quietly — widening one changes a test.

**Two families.** *Influent* statistics come from a two-year draw of the generator alone
(no digester), which is the same construction ``tests/test_generator.py`` uses; *output*
statistics come from a **panel** of twelve clean Level-0 truth runs through the full chain,
each labelled sound or soured. Both are seeded explicitly and deterministic.

**The panel exists because of what the first run found.** Measuring one Level-0 run turned
out to measure a crashed digester: before the changes of 2026-09-03, Plant B acidified on
5 of 12 seeds. Two corrections fixed it — the feed's strong-cation content calibrated to
the anchor's own digester alkalinity, and the blend tank the plant has always had, added to
the plant contract — and the panel is now uniformly sound. It stays, because "no seed
sours" is a claim that needs a panel to support it, and because the output rows are taken
across the runs that are working digesters. The tolerances were not touched when the
measurement changed.

**What this does NOT re-test.** ``tests/test_generator.py`` already pins Plant B's
per-stream delivery statistics against ``anchor.ingest_muscatine`` in detail, and
``tests/test_plausibility.py`` already pins the biogas envelope. Those rows appear here
because gate G1 asks for the whole table in one place, but the detailed assertions stay
where they are; this module extends them with the **output** statistics — pH, alkalinity,
VFA, FOS/TAC, loading — that nothing has compared until now.

**One row is expected to fail, and must not be made to pass.** The independent review of
PR #11 recorded that the simulated FOS/TAC distribution sits well below the plant's: a
healthy simulated digester is at 0.01-0.07 against the anchor's median of 0.23, and even
at 2.5x feed Plant B reaches only 0.15. That is a realism gap in the truth model, not a
threshold to move. It is declared here with the same factor-of-two band any dimensionless
ratio would get, measured, and reported as a failure; ``docs/g1_anchor_report.md`` says
what closing it would take.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from anchor.ingest_muscatine import DAILY_FILE, DailyRecord, delivery_statistics, load_daily
from scenarios.schema import load_scenario
from sim.influent import (
    feed_cod_per_m3,
    generate_influent,
    load_feed_fractionation,
    load_generator_config,
    organic_loading_rate,
)
from sim.plants import load_plant_config

__all__ = [
    "ANCHOR_DIGESTERS",
    "INFLUENT_DAYS",
    "OUTPUT_DAYS",
    "OUTPUT_PANEL_SEEDS",
    "TOLERANCES",
    "Comparison",
    "PanelRun",
    "Tolerance",
    "anchor_available",
    "anchor_statistics",
    "compare",
    "extract_block",
    "generated_influent_statistics",
    "generated_output_statistics",
    "match_count",
    "output_panel",
    "render_panel",
    "render_report",
    "report_block",
]

ANCHOR_DIGESTERS = 2
"""The plant runs two parallel digesters; the benchmark models one and gives it half the
plant feed (``configs/plants/plant_B.yaml``)."""

INFLUENT_DAYS = 730
"""Two years of generator draw, as ``tests/test_generator.py`` uses."""

OUTPUT_DAYS = 180
"""Horizon of each panel run, matching the horizon most of the scenario ladder uses."""

OUTPUT_PANEL_SEEDS: tuple[int, ...] = tuple(range(1000, 1024))
"""The twenty-four base seeds of the output panel. Declared, contiguous and arbitrary: they
are not chosen for the runs they produce, which is the point (see :func:`output_panel`).

Widened from twelve on 2026-09-03, when the lead made "zero souring on clean Level-0 seeds"
the acceptance condition for Plant B: twelve seeds could show a 40 % failure rate but could
not support a claim that the rate is zero."""

INFLUENT_SEED = 7
"""Seed of the influent draw. The same seed ``tests/test_generator.py`` uses, so the two
descriptions of the same generator are descriptions of the same realisation."""

SETTLING_DAYS = 30
"""Days dropped from the head of the output run before any statistic is taken. The harness
burns in first, so this is a margin rather than a start-up transient."""

FEED_COLUMNS: Mapping[str, str] = {
    "primary_sludge": "ps_m3",
    "thickened_was": "twas_m3",
    "high_strength_waste": "hsw_m3",
    "fog": "fog_m3",
}
VS_COLUMNS: Mapping[str, str] = {
    "primary_sludge": "ps_vs_kg_kg",
    "thickened_was": "twas_vs_kg_kg",
    "high_strength_waste": "hsw_vs_kg_kg",
}

CFM_TO_M3_PER_D = 0.0283168 * 1440.0


# ------------------------------------------------------------------ tolerances


@dataclass(frozen=True)
class Tolerance:
    """A bound declared **before** the comparison, with the reason it is that size."""

    name: str
    unit: str
    kind: Literal["relative", "absolute", "ratio_band"]
    bound: float | tuple[float, float]
    """Relative fraction, absolute value in ``unit``, or ``(low, high)`` on generated/anchor."""
    rationale: str
    gate: bool = True
    """Whether G1 turns on this row. A row outside the gate is reported and not gating —
    used where the anchor measures something the simulator only partly corresponds to."""
    calibrated: bool = False
    """Whether a simulator input was **fitted to this very anchor column**.

    Such a row is not evidence: it says the fit converged, not that the simulator agrees
    with a measurement it was not shown. It is still reported — the fit could have failed,
    and a large residual would be a real finding — but it is labelled ``calibrated to
    anchor`` rather than ``pass`` and :func:`match_count` excludes it, so it can never be
    counted as one of the anchor matches (the lead's ruling M1, 2026-09-04)."""

    def check(self, generated: float, anchor: float) -> bool:
        """Whether a measured pair is inside this bound."""
        if not (math.isfinite(generated) and math.isfinite(anchor)):
            return False
        if self.kind == "absolute":
            return abs(generated - anchor) <= float(self.bound)
        if self.kind == "relative":
            return anchor != 0.0 and abs(generated - anchor) / abs(anchor) <= float(self.bound)
        low, high = self.bound  # type: ignore[misc]
        return anchor != 0.0 and low <= generated / anchor <= high

    def describe(self) -> str:
        """The bound as it appears in the report."""
        if self.kind == "absolute":
            return f"+/- {self.bound:g} {self.unit}"
        if self.kind == "relative":
            return f"+/- {float(self.bound) * 100:g} %"
        low, high = self.bound  # type: ignore[misc]
        return f"ratio in [{low:g}, {high:g}]"


def _feed_tolerances() -> list[Tolerance]:
    """Per-stream influent bounds, all inherited from the tests that already apply them."""
    out: list[Tolerance] = []
    for feed in FEED_COLUMNS:
        out += [
            Tolerance(
                f"feed_volume_median_{feed}",
                "m3/d per digester",
                "relative",
                0.15,
                "inherited from tests/test_generator.py, which already applies rel=0.15 to "
                "this exact quantity; not a bound invented here",
            ),
            Tolerance(
                f"feed_volume_log_sigma_{feed}",
                "- (sd of ln amount on delivery days)",
                "relative",
                0.30,
                "inherited from tests/test_generator.py (rel=0.3): a spread statistic on a "
                "few hundred delivery days is itself noisy at the 10 % level",
            ),
            Tolerance(
                f"delivery_zero_fraction_{feed}",
                "- (fraction of days with no delivery)",
                "absolute",
                0.04,
                "inherited from tests/test_generator.py (abs=0.04): four percentage points "
                "is ~1.5 sd of a proportion estimated on 730 days",
            ),
        ]
    return out


#: Every bound, declared before the comparison was run (see the module docstring).
TOLERANCES: tuple[Tolerance, ...] = (
    *_feed_tolerances(),
    Tolerance(
        "total_feed_flow_median",
        "m3/d per digester",
        "relative",
        0.15,
        "inherited from tests/test_generator.py, which pins the generated total against "
        "the plant's declared median at rel=0.15",
    ),
    Tolerance(
        "vs_fraction_primary_sludge",
        "kg VS/kg wet",
        "relative",
        0.20,
        "the catalogue's TS and VS/TS for this stream are design values with sources, not "
        "fits to this column; 20 % is the band inside which the catalogue and the plant's "
        "own laboratory describe the same sludge",
    ),
    Tolerance(
        "vs_fraction_thickened_was",
        "kg VS/kg wet",
        "relative",
        0.20,
        "the catalogue's TS and VS/TS for this stream are design values with sources, not "
        "fits to this column; 20 % is the band inside which the catalogue and the plant's "
        "own laboratory describe the same sludge",
    ),
    Tolerance(
        "vs_fraction_high_strength_waste",
        "kg VS/kg wet",
        "relative",
        0.25,
        "the same argument as the two sludges - design values with sources rather than "
        "fits - widened to 25 % because the plant's high-strength waste is a blend of "
        "trucked receipts whose composition the daily file shows varying by ~70 % day to day",
    ),
    Tolerance(
        "hsw_cod_concentration",
        "kg COD/m3",
        "relative",
        0.25,
        "the catalogue's HSW entry was set from this column, so this row is PARTLY "
        "CIRCULAR and is declared as a regression guard rather than as evidence: it "
        "catches a fractionation draw or a COD-equivalent change that moves the feed away "
        "from the anchor, and proves nothing about realism on its own",
    ),
    Tolerance(
        "organic_loading_rate",
        "kg VS/m3/d",
        "relative",
        0.30,
        "the anchor value is built from the plant's own feed volumes and its own measured "
        "VS fractions, with FOG (which the plant does not assay) taken from the "
        "catalogue; 30 % carries that one substituted stream",
    ),
    Tolerance(
        "biogas_mean",
        "m3/d per digester at the meter's conditions",
        "ratio_band",
        (0.6, 1.5),
        "inherited from tests/test_plausibility.py, which applies 0.6-1.5 to the "
        "generator-driven run and 0.6-1.4 to the constant-recipe one. The band is wide "
        "because the plant's meter states neither temperature nor pressure for its cubic "
        "feet (anchor/ingest_muscatine.py) and our conversion assumes standard conditions",
    ),
    Tolerance(
        "digester_pH_median",
        "pH units",
        "absolute",
        0.40,
        "the probe's own noise is 0.02 and a working digester's day-to-day pH moves by "
        "~0.2, so 0.4 is about twice the plant's own spread: inside it, the simulated "
        "digester is in the same operating regime; outside it, it is not",
    ),
    Tolerance(
        "alkalinity_median",
        "kg CaCO3/m3",
        "relative",
        0.35,
        "CALIBRATED TO THIS COLUMN, so it is not an independent match. The bound was "
        "declared when the feed's cation load was a design value; under the lead's ruling 3 "
        "(2026-09-03) the Muscatine feeds' `S_cat` was then fitted to this very statistic, "
        "and the earlier rationale - that alkalinity follows design values `s_ic` and "
        "`S_cat` 'rather than fits' - became false. The row is kept and reported because a "
        "large residual would still be a finding (the fit could have failed, or moved with "
        "a later change), and excluded from the anchor-match count because agreeing with "
        "the column you were fitted to is not evidence",
        calibrated=True,
    ),
    Tolerance(
        "vfa_median",
        "kg/m3 as acetic acid",
        "ratio_band",
        (0.25, 4.0),
        "residual VFA is the least identifiable output of a converged ADM1 - it is a small "
        "difference of large production and consumption terms - and the plant's titrimetric "
        "method over-reads true VFA. A factor of four either way is deliberately generous, "
        "so a failure here would be unambiguous. IT FAILS, and the bound is deliberately "
        "NOT widened to accommodate that: see docs/vfa_gap.md, which measured that no value "
        "of k_m_ac closes the gap (the model is bistable and the anchor lies between the "
        "branches) and concluded it is a measurement-convention question",
    ),
    Tolerance(
        "fos_tac_median",
        "- (VFA as acetic over alkalinity as CaCO3)",
        "ratio_band",
        (0.5, 2.0),
        "a factor of two, the natural band for a dimensionless stress ratio. THIS ROW IS "
        "EXPECTED TO FAIL: the independent review of PR #11 recorded that a healthy "
        "simulated digester sits at 0.01-0.07 against the plant's median 0.23. It is "
        "declared at the same width every other ratio gets, measured, and reported as a "
        "failure. Moving the bound to make it pass would be the one thing this module "
        "exists to prevent. It got WORSE (0.021 -> 0.013) when the feed alkalinity was "
        "calibrated to the anchor, which is expected and correct rather than a regression: "
        "alkalinity is the denominator, so the discrepancy now sits wholly in the numerator "
        "(docs/vfa_gap.md)",
    ),
)

_BY_NAME: Mapping[str, Tolerance] = {t.name: t for t in TOLERANCES}


# ------------------------------------------------------------------ measurement


@dataclass(frozen=True)
class Comparison:
    """One measured pair against its declared bound."""

    name: str
    unit: str
    generated: float
    anchor: float
    tolerance: Tolerance

    @property
    def passed(self) -> bool:
        """Whether the pair is inside the declared bound."""
        return self.tolerance.check(self.generated, self.anchor)

    @property
    def ratio(self) -> float:
        """Generated over anchor, or NaN when the anchor is zero."""
        return self.generated / self.anchor if self.anchor else float("nan")


def _median(values: Sequence[float | None]) -> float:
    """Median of the measured values of a daily column, ignoring blanks and zeros."""
    arr = np.array([v for v in values if v is not None and v > 0.0], dtype=float)
    return float(np.median(arr)) if arr.size else float("nan")


def anchor_statistics(records: Sequence[DailyRecord] | None = None) -> dict[str, float]:
    """The plant's own numbers, per digester where the column is a plant total.

    Args:
        records: The parsed daily file (default: read it).

    Returns:
        Statistic name -> value, in the units of :data:`TOLERANCES`.
    """
    rows = records if records is not None else load_daily()
    catalogue = load_feed_fractionation()
    out: dict[str, float] = {}

    total = np.zeros(len(rows))
    for feed, column in FEED_COLUMNS.items():
        stats = delivery_statistics(rows, column, per_unit=ANCHOR_DIGESTERS)
        out[f"feed_volume_median_{feed}"] = stats.nonzero_median
        out[f"feed_volume_log_sigma_{feed}"] = stats.log_sigma
        out[f"delivery_zero_fraction_{feed}"] = stats.zero_fraction
        total += (
            np.nan_to_num(np.array([getattr(r, column) or 0.0 for r in rows]), nan=0.0)
            / ANCHOR_DIGESTERS
        )
    out["total_feed_flow_median"] = float(np.median(total[total > 0.0]))

    for feed, column in VS_COLUMNS.items():
        out[f"vs_fraction_{feed}"] = _median([getattr(r, column) for r in rows])
    out["hsw_cod_concentration"] = _median([r.hsw_cod_kg_m3 for r in rows])

    # Organic load from the plant's own volumes and its own VS assays. FOG is the one
    # stream the plant does not assay, so its VS comes from the catalogue and the
    # tolerance carries that substitution.
    plant = load_plant_config("B")
    vs_per_m3: dict[str, float] = {}
    for feed in FEED_COLUMNS:
        spec = catalogue.feeds[feed]
        measured = out.get(f"vs_fraction_{feed}")
        vs_kg_per_kg = (
            measured if measured is not None and math.isfinite(measured) else spec.vs_per_kg_wet
        )
        vs_per_m3[feed] = vs_kg_per_kg * spec.density
    load = sum(
        vs_per_m3[feed]
        * float(np.nanmean([getattr(r, col) or 0.0 for r in rows]))
        / ANCHOR_DIGESTERS
        for feed, col in FEED_COLUMNS.items()
    )
    out["organic_loading_rate"] = load / plant.geometry.V_liq_declared

    biogas = np.array([r.biogas_m3_d for r in rows if r.biogas_m3_d is not None], dtype=float)
    out["biogas_mean"] = float(biogas.mean()) / ANCHOR_DIGESTERS
    out["digester_pH_median"] = _median([r.dig1_pH for r in rows])
    out["alkalinity_median"] = _median([r.dig1_alk_kg_caco3_m3 for r in rows])
    out["vfa_median"] = _median([r.dig1_vfa_kg_m3 for r in rows])
    paired = np.array(
        [
            (r.dig1_vfa_kg_m3, r.dig1_alk_kg_caco3_m3)
            for r in rows
            if r.dig1_vfa_kg_m3 and r.dig1_alk_kg_caco3_m3
        ],
        dtype=float,
    )
    out["fos_tac_median"] = (
        float(np.median(paired[:, 0] / paired[:, 1])) if paired.size else float("nan")
    )
    return out


def generated_influent_statistics(
    plant_id: str = "B", n_days: int = INFLUENT_DAYS, seed: int = INFLUENT_SEED
) -> dict[str, float]:
    """Feed statistics of a two-year generator draw, with no digester attached."""
    from sim.adm1 import load_parameters

    plant = load_plant_config(plant_id)
    catalogue = load_feed_fractionation()
    run = generate_influent(
        plant, catalogue, load_generator_config(), load_parameters(), seed=seed, n_days=n_days
    )
    out: dict[str, float] = {}
    for feed in FEED_COLUMNS:
        if feed not in run.truth.feeds:
            continue
        density = catalogue.feeds[feed].density
        m3 = run.truth.feeds[feed].delivered_kg / density
        nonzero = m3[m3 > 0.0]
        out[f"feed_volume_median_{feed}"] = float(np.median(nonzero))
        out[f"feed_volume_log_sigma_{feed}"] = float(np.log(nonzero).std())
        out[f"delivery_zero_fraction_{feed}"] = float(np.mean(m3 == 0.0))
        spec = catalogue.feeds[feed]
        ts = run.truth.feeds[feed].ts
        out[f"vs_fraction_{feed}"] = float(np.mean(ts) * spec.vs_of_ts)
    out["total_feed_flow_median"] = float(np.median(run.truth.influent.q))

    spec = catalogue.feeds["high_strength_waste"]
    frac = run.truth.fractionations["high_strength_waste"]
    out["hsw_cod_concentration"] = float(
        feed_cod_per_m3(spec, frac, float(np.mean(run.truth.feeds["high_strength_waste"].ts)))
    )
    out["organic_loading_rate"] = organic_loading_rate(
        catalogue, run.truth.mean_recipe_kg_d, plant.geometry.V_liq_declared
    )
    return out


@dataclass(frozen=True)
class PanelRun:
    """One clean Level-0 run of the output panel, with its verdict and its statistics."""

    seed: int
    sound: bool
    statistics: Mapping[str, float]


def output_panel(
    plant_id: str = "B",
    n_days: int = OUTPUT_DAYS,
    seeds: Sequence[int] = OUTPUT_PANEL_SEEDS,
    scenario_path: Path | None = None,
) -> list[PanelRun]:
    """Clean Level-0 runs at several seeds, each labelled sound or soured.

    **Why a panel and not one run.** The first version of this module measured a single
    Level-0 run at the scenario's own seed. That run turned out to be one of the Plant B
    seeds that acidifies (see :func:`sim.run.harness.assess_health` and
    ``docs/g1_anchor_report.md``), so every output statistic described a crashed digester
    and every output row failed for the wrong reason. The panel is the fix: it measures
    the *rate* at which the plant sours as well as what it looks like when it does not.
    The declared tolerances were not touched when this changed — only what is measured
    against them, and this paragraph is the record of that.

    Each run is the Level-0 scenario at the requested horizon on the requested plant, so
    it exercises the simulator exactly as a benchmark cell does: burn-in, hidden volume
    error, stochastic influent and all.
    """
    from sim.run.harness import simulate_truth
    from sim.run.seeds import RunSeeds

    scenario = load_scenario(scenario_path or Path("scenarios/S0-01.yaml"))
    plant = load_plant_config(plant_id)
    out: list[PanelRun] = []
    for seed in seeds:
        one = scenario.model_copy(update={"duration_days": float(n_days), "seed": int(seed)})
        truth = simulate_truth(one, plant, RunSeeds.derive(seed, plant_id))
        settled = truth.channels.t >= SETTLING_DAYS
        channel = truth.channels
        out.append(
            PanelRun(
                seed=int(seed),
                sound=truth.health.sound,
                statistics={
                    "biogas_mean": float(np.mean(channel["q_gas_stp_dry"][settled])),
                    "digester_pH_median": float(np.median(channel["pH"][settled])),
                    "alkalinity_median": float(np.median(channel["alkalinity_total"][settled])),
                    "vfa_median": float(np.median(channel["vfa_total"][settled])),
                    "fos_tac_median": float(np.median(channel["fos_tac"][settled])),
                    "ch4_fraction_median": float(np.median(channel["ch4_fraction"][settled])),
                    "overload_day_fraction": float(np.mean(truth.overload[settled])),
                    "foaming_day_fraction": float(np.mean(truth.foaming[settled])),
                    "fos_tac_exceedance_fraction": float(
                        np.mean(channel["fos_tac"][settled] > 0.40)
                    ),
                },
            )
        )
    return out


def generated_output_statistics(
    plant_id: str = "B",
    n_days: int = OUTPUT_DAYS,
    seeds: Sequence[int] = OUTPUT_PANEL_SEEDS,
    panel: Sequence[PanelRun] | None = None,
) -> dict[str, float]:
    """The panel's statistics, taken across the runs that are working digesters.

    A soured run says nothing about whether the simulator resembles a plant; it says the
    simulator crashed. So the comparison is made on the sound runs, and the soured fraction
    is reported alongside as ``sound_run_fraction`` rather than being averaged away.

    Raises:
        RuntimeError: If no run in the panel is a working digester, in which case there is
            nothing to compare and the caller must be told so rather than shown a median
            of crashes.
    """
    runs = list(panel if panel is not None else output_panel(plant_id, n_days, seeds))
    sound = [r for r in runs if r.sound]
    if not sound:
        raise RuntimeError(
            f"every run of the {plant_id} output panel soured; there is no working digester "
            "to compare against the anchor"
        )
    names = sound[0].statistics.keys()
    out = {name: float(np.median([r.statistics[name] for r in sound])) for name in names}
    out["sound_run_fraction"] = len(sound) / len(runs)
    return out


def compare(
    generated: Mapping[str, float] | None = None,
    anchor: Mapping[str, float] | None = None,
) -> list[Comparison]:
    """Every declared row, measured.

    Args:
        generated: Pre-computed generated statistics (default: compute both families).
        anchor: Pre-computed anchor statistics (default: read the daily file).

    Returns:
        One comparison per entry of :data:`TOLERANCES` that both sides measure, in
        declaration order.
    """
    if generated is None:
        generated = {**generated_influent_statistics(), **generated_output_statistics()}
    if anchor is None:
        anchor = anchor_statistics()
    out = []
    for tol in TOLERANCES:
        if tol.name not in generated or tol.name not in anchor:
            continue
        out.append(
            Comparison(
                name=tol.name,
                unit=tol.unit,
                generated=float(generated[tol.name]),
                anchor=float(anchor[tol.name]),
                tolerance=tol,
            )
        )
    return out


def anchor_available(path: Path = DAILY_FILE) -> bool:
    """Whether the Muscatine daily file is present.

    It is committed (small enough, and its licence permits redistribution), but a shallow
    or filtered checkout can leave it absent, so the report and its test skip rather than
    fail when it is not there.
    """
    return Path(path).is_file()


def match_count(comparisons: Sequence[Comparison]) -> tuple[int, int, int]:
    """How many rows the simulator matched **without having been fitted to them**.

    Args:
        comparisons: The measured rows.

    Returns:
        ``(matched, independent, calibrated)``: how many independent rows are inside their
        bound, how many independent rows there are, and how many were excluded because a
        simulator input was calibrated to the anchor column they compare against.
    """
    independent = [c for c in comparisons if not c.tolerance.calibrated]
    calibrated = len(comparisons) - len(independent)
    return sum(1 for c in independent if c.passed), len(independent), calibrated


def render_report(
    comparisons: Sequence[Comparison], extra: Mapping[str, float] | None = None
) -> str:
    """The comparison table of ``docs/g1_anchor_report.md``.

    Args:
        comparisons: The measured rows.
        extra: Additional generated statistics reported without an anchor row (methane
            content, the condition-flag occupancies), which the anchor does not measure.

    Returns:
        Markdown: the comparison table, then the unanchored observations.
    """
    lines = [
        "| Statistic | Unit | Generated | Anchor | Ratio | Declared tolerance | Result |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for c in comparisons:
        ratio = "-" if not math.isfinite(c.ratio) else f"{c.ratio:.2f}"
        if c.tolerance.calibrated:
            # never "pass": a simulator input was fitted to this very column
            result = "calibrated to anchor" if c.passed else "**FAIL (calibrated)**"
        else:
            result = "pass" if c.passed else "**FAIL**"
        gate = "" if c.tolerance.gate else " (not gating)"
        lines.append(
            f"| `{c.name}` | {c.unit} | {c.generated:.4g} | {c.anchor:.4g} | {ratio} | "
            f"{c.tolerance.describe()}{gate} | {result} |"
        )
    matched, independent, calibrated = match_count(comparisons)
    plural = "row was" if calibrated == 1 else "rows were"
    lines += [
        "",
        f"**{matched} of {independent} independent rows are inside their declared "
        f"tolerance.** A further {calibrated} {plural} calibrated to the very anchor "
        "column it is compared against, and is excluded from that count: agreeing with a "
        "column you were fitted to is not evidence.",
    ]
    if extra:
        lines += [
            "",
            "| Generated statistic with no anchor row | Value |",
            "|---|---:|",
        ]
        lines += [f"| `{k}` | {v:.4g} |" for k, v in sorted(extra.items())]
    return "\n".join(lines)


def render_panel(panel: Sequence[PanelRun]) -> str:
    """The per-seed health table: which Level-0 runs are working digesters and which are not.

    The overload column is reported **per run and pooled** because the lead's ruling 4 of
    2026-09-09 requires it: the Level-4 ``informative_missingness`` row scales this flag, so
    how often it fires on a *healthy* digester is what says whether that row has anything to
    act on. It is reported under whichever FOS/TAC convention is in force when the panel is
    generated — today a true-VFA ratio against a titrimetric threshold (benchmark card
    §5.3), which is exactly why the number is small.
    """
    lines = [
        "| Base seed | Verdict | median pH | mean CH4 | median VFA (kg/m3) | median FOS/TAC "
        "| overload days |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for run in panel:
        verdict = "sound" if run.sound else "**soured**"
        s = run.statistics
        lines.append(
            f"| {run.seed} | {verdict} | {s['digester_pH_median']:.2f} | "
            f"{s['ch4_fraction_median']:.3f} | {s['vfa_median']:.3f} | "
            f"{s['fos_tac_median']:.3f} | {s['overload_day_fraction'] * 100:.2f} % |"
        )
    sound = [r for r in panel if r.sound]
    lines.append("")
    lines.append(f"**{len(sound)} of {len(panel)} runs are working digesters.**")
    if sound:
        rates = [float(r.statistics["overload_day_fraction"]) for r in sound]
        pooled = sum(rates) / len(rates)
        firing = sum(1 for r in rates if r > 0.0)
        lines += [
            "",
            f"**Overload flag across the {len(sound)} SOUND runs**: pooled "
            f"{pooled * 100:.2f} % of days, per-run min {min(rates) * 100:.2f} %, max "
            f"{max(rates) * 100:.2f} %; it fires on at least one day in {firing} of "
            f"{len(sound)} runs. The anchor's own exceedance is 8.25 % (Dig1) and 9.18 % "
            "(Dig2). The simulated figure is low because `fos_tac` is a true-VFA ratio "
            "measured against a threshold percentile-matched to a *titrimetric* column; "
            "the transfer function that would reconcile them is approved and not yet "
            "implemented (benchmark card §5.3).",
        ]
    return "\n".join(lines)


REPORT_BEGIN = "<!-- BEGIN GENERATED: g1 anchor comparison -->"
REPORT_END = "<!-- END GENERATED: g1 anchor comparison -->"


def report_block(
    comparisons: Sequence[Comparison],
    panel: Sequence[PanelRun],
    extra: Mapping[str, float],
) -> str:
    """The whole generated block of the report, between its markers.

    ``tests/test_g1_anchor.py`` recomputes this and compares it with the committed
    ``docs/g1_anchor_report.md`` verbatim, so the report cannot drift from the code that
    produced it — the same construction the benchmark card's fault table uses.
    """
    return "\n".join(
        [
            REPORT_BEGIN,
            "",
            "### Comparison against the declared tolerances",
            "",
            render_report(comparisons, extra),
            "",
            "### The output panel, run by run",
            "",
            render_panel(panel),
            "",
            REPORT_END,
        ]
    )


def extract_block(markdown: str) -> str:
    """The generated block of a report file, markers included.

    Raises:
        ValueError: If the markers are missing or out of order.
    """
    start = markdown.find(REPORT_BEGIN)
    end = markdown.find(REPORT_END)
    if start < 0 or end < start:
        raise ValueError("the report has no generated block between its markers")
    return markdown[start : end + len(REPORT_END)]
