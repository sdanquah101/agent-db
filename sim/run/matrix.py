"""The generation matrix of §7: which scenarios run on which plant at which tier.

The design is not "every scenario everywhere". Proposal §7 and §11 split it in two:

* **The factorial core** is Plants **B and C**, the two dataset-anchored plants, over the
  **16 non-ammonia** scenarios at **all three tiers** - 96 cells.
* **Plant A** is statistics-anchored, reported separately, and contributes no rows to the
  factorial. It runs the **Level 2-5** scenarios at **Tier A only**, plus the **three
  ammonia** scenarios, which run *nowhere else*: the Level-5 inhibition shift, the Level-6
  omitted-SAO row and their Level-7 compound. Muscatine's free ammonia is an order of
  magnitude below the pathway-shift window and Plant A's is inside it (decisions log,
  2026-09-02), so those three rows are meaningless anywhere but Plant A - 18 cells.

**One interpretation, flagged.** §7 pins Tier A for Plant A's "Level 2-5 scenarios" and is
silent on the tier of the three ammonia rows. They run here at **all three tiers**, because
an ammonia-inhibition shift and an omitted oxidative pathway are diagnosed through TAN, VFA
speciation and off-gas hydrogen — none of which Tier A carries — so confining them to Tier A
would make the only plant that can host them unable to answer them. Recorded in
``docs/decisions.md`` and flagged to the lead.

**Truth is integrated once per (plant, scenario).** A tier is a mask (§6.4), so the three
tiers of a cell share one integration, which is both three times cheaper and the only way
to *guarantee* the property rather than hope two integrations agree.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from scenarios.schema import Scenario, load_scenario
from sim.plants import load_plant_config
from sim.run.layout import RUNS_ROOT, store_salt, truth_store_for

__all__ = [
    "ALL_TIERS",
    "AMMONIA_SCENARIOS",
    "FACTORIAL_PLANTS",
    "PLANT_A_LEVELS",
    "SCENARIO_DIR",
    "Cell",
    "CellResult",
    "generate_matrix",
    "load_library",
    "matrix_cells",
]

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "scenarios"

AMMONIA_SCENARIOS: tuple[str, ...] = ("S5-01", "S6-01", "S6-04", "S7-02")
"""The rows that run on Plant A alone (§6.3, §7).

``S6-04`` is the lead's "S6-01b" (ruling 1, 2026-09-09): the same SAO omission as S6-01 on
Plant A's *adapted* baseline, where the omitted pathway carries no flux and the correct
conclusion is that no structural residual is detectable. It belongs here for the same
reason the other three do — it is staged on a declared Plant A baseline and there is no
Muscatine equivalent — and it runs at all three tiers as they do, adding 3 cells.
"""

FACTORIAL_PLANTS: tuple[str, ...] = ("B", "C")
"""The dataset-anchored pair that carries the factorial (§8)."""

PLANT_A_LEVELS: tuple[int, ...] = (2, 3, 4, 5)
"""The rungs Plant A runs at Tier A, beyond the ammonia rows (§7)."""

ALL_TIERS: tuple[str, ...] = ("A", "B", "C")


def load_library(directory: Path = SCENARIO_DIR) -> dict[str, Scenario]:
    """Every scenario YAML in the library, keyed by id and validated.

    Raises:
        ValueError: If two files declare the same id.
    """
    library: dict[str, Scenario] = {}
    for path in sorted(Path(directory).glob("S*.yaml")):
        scenario = load_scenario(path)
        if scenario.id in library:
            raise ValueError(f"duplicate scenario id {scenario.id!r} at {path}")
        library[scenario.id] = scenario
    return library


@dataclass(frozen=True)
class Cell:
    """One generation cell: a scenario on a plant at a tier, with its seed."""

    scenario_id: str
    plant: str
    tier: str
    seed: int
    replicate: int = 0

    @property
    def key(self) -> tuple[str, str, int, int]:
        """The (plant, scenario, seed, replicate) group whose tiers share one truth."""
        return (self.plant, self.scenario_id, self.seed, self.replicate)

    def __str__(self) -> str:
        """``S2-03 on plant B at tier A`` — for reports and test ids."""
        return f"{self.scenario_id} on plant {self.plant} at tier {self.tier}"


def _tiers_for_plant_a(scenario: Scenario) -> tuple[str, ...]:
    """Which tiers Plant A runs a scenario at (the union of the two §7 rules)."""
    tiers: set[str] = set()
    if scenario.level in PLANT_A_LEVELS:
        tiers.add("A")
    if scenario.id in AMMONIA_SCENARIOS:
        tiers.update(ALL_TIERS)
    return tuple(sorted(tiers))


def matrix_cells(
    library: dict[str, Scenario] | None = None,
    *,
    replicates: int = 1,
) -> list[Cell]:
    """Every cell of the §7 matrix, in a stable order.

    Args:
        library: The scenario library (default: read from ``scenarios/``).
        replicates: Seed replicates per cell (§7 uses 5 for the final runs; generation
            for gate G1 uses 1).

    Returns:
        The cells, sorted by scenario, plant, tier and replicate.

    Raises:
        ValueError: If a scenario carries no seed (CLAUDE.md rule 4).
    """
    scenarios = library if library is not None else load_library()
    cells: list[Cell] = []
    for scenario_id, scenario in sorted(scenarios.items()):
        if scenario.seed is None:
            raise ValueError(f"scenario {scenario_id} carries no seed")
        for replicate in range(replicates):
            plants: dict[str, tuple[str, ...]] = {}
            if scenario_id not in AMMONIA_SCENARIOS:
                for plant in FACTORIAL_PLANTS:
                    plants[plant] = ALL_TIERS
            for tiers in (_tiers_for_plant_a(scenario),):
                if tiers:
                    plants["A"] = tiers
            for plant, tiers in sorted(plants.items()):
                cells.extend(
                    Cell(scenario_id, plant, tier, scenario.seed, replicate) for tier in tiers
                )
    return sorted(cells, key=lambda c: (c.scenario_id, c.plant, c.tier, c.replicate))


@dataclass(frozen=True)
class CellResult:
    """What happened when one cell was generated.

    ``ok`` is whether the cell *generated* — the integrator succeeded and the files were
    written. ``sound`` is whether what it generated is a working digester
    (:func:`sim.run.harness.assess_health`). The two are separate on purpose: a soured run
    generates perfectly well and is still useless as a benchmark case, and gate G1 needs
    both counts rather than one.
    """

    cell: Cell
    run_id: str | None
    ok: bool
    wall_s: float
    detail: str = ""
    sound: bool | None = None
    pH_median: float = float("nan")
    ch4_fraction_mean: float = float("nan")

    def __str__(self) -> str:
        """One line for the generation report."""
        status = "ok" if self.ok else "FAILED"
        health = "" if self.sound is None else (" sound" if self.sound else " SOURED")
        return (
            f"{self.cell}: {status}{health} in {self.wall_s:.1f} s "
            f"({self.run_id or '-'}) pH={self.pH_median:.2f} ch4={self.ch4_fraction_mean:.3f} "
            f"{self.detail}"
        )


MATRIX_ORDER_SEED = 20260910
"""Seed of the generation-order shuffle when there is **no store** to key it with (a
``write=False`` generation). Fixed and declared, so such a run is reproducible.

It is **not** what keys the order of a written matrix. The final review of ``99a8947``
(finding F1, 2026-09-10) showed that a shuffle seeded with a committed constant over the
public library is a reproducible permutation — the reviewer reproduced it — so a sort of
the run set by any visible timestamp mapped position to cell exactly, a public salt over a
public space (the same class as B1). A written matrix is shuffled with a key derived from
the store's secret salt (:func:`execution_order`), and no visible file carries a timestamp
any more (:mod:`sim.run.manifest`, :mod:`state.provenance`)."""


def execution_order(cells: Sequence[Cell], key: bytes | None) -> list[list[Cell]]:
    """The truth groups of ``cells`` in the order they are generated.

    Args:
        cells: The cells to generate.
        key: The store's secret salt, or ``None`` for a generation that writes nothing.

    Returns:
        The groups (one per shared truth, :func:`_groups`) in execution order: a
        permutation seeded from the salt when there is one, from
        :data:`MATRIX_ORDER_SEED` otherwise.
    """
    groups = [group for _, group in _groups(cells)]
    if key is None:
        seed = MATRIX_ORDER_SEED
    else:
        digest = hashlib.sha256(b"ad-agentbench/matrix-order|" + key).digest()
        seed = int.from_bytes(digest[:8], "big")
    np.random.default_rng(seed).shuffle(groups)
    return groups


def _groups(cells: Sequence[Cell]) -> Iterator[tuple[tuple[str, str, int, int], list[Cell]]]:
    """Cells grouped by the (plant, scenario, seed, replicate) that shares one truth."""
    ordered: dict[tuple[str, str, int, int], list[Cell]] = {}
    for cell in cells:
        ordered.setdefault(cell.key, []).append(cell)
    yield from ordered.items()


def generate_matrix(
    cells: Sequence[Cell],
    *,
    runs_root: Path = RUNS_ROOT,
    library: dict[str, Scenario] | None = None,
    write: bool = True,
    stop_on_error: bool = False,
) -> list[CellResult]:
    """Generate every cell, sharing one truth integration across the tiers of a cell.

    Args:
        cells: The cells to generate.
        runs_root: Root of the run store.
        library: The scenario library (default: read from ``scenarios/``).
        write: Whether to write run directories.
        stop_on_error: Re-raise the first failure instead of recording it.

    Returns:
        One result per cell, in the order the cells were given.

    Raises:
        Exception: Whatever the harness raised, when ``stop_on_error`` is set.
    """
    from sim.run.harness import generate_cells

    scenarios = library if library is not None else load_library()
    results: dict[Cell, CellResult] = {}
    # The cells arrive sorted by scenario id, so generating them in that order would stamp
    # the run set in ladder order. The EXECUTION order is a shuffle of the truth groups
    # keyed with the store's secret salt (finding F1: a committed seed was a reproducible
    # permutation); the results are still returned in the order the cells were given. A
    # no-write generation has no store and falls back to the declared constant seed.
    key = store_salt(truth_store_for(runs_root)) if write else None
    for group in execution_order(cells, key):
        plant_id, scenario_id, seed, replicate = group[0].key
        scenario = scenarios[scenario_id]
        plant = load_plant_config(plant_id)
        tiers = [c.tier for c in group]
        started = time.perf_counter()
        try:
            runs = generate_cells(
                scenario,
                plant,
                tiers,
                seed=seed,
                replicate=replicate,
                runs_root=runs_root,
                write=write,
            )
        except Exception as exc:
            if stop_on_error:
                raise
            elapsed = time.perf_counter() - started
            for cell in group:
                results[cell] = CellResult(
                    cell, None, False, elapsed / len(group), f"{type(exc).__name__}: {exc}"
                )
            continue
        for cell, run in zip(group, runs, strict=True):
            results[cell] = CellResult(
                cell,
                run.run_id,
                run.truth.solver_success,
                run.wall_s,
                run.truth.solver_message,
                sound=run.truth.health.sound,
                pH_median=run.truth.health.pH_median,
                ch4_fraction_mean=run.truth.health.ch4_fraction_mean,
            )
    return [results[cell] for cell in cells]


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the matrix from the command line.

    ``python -m sim.run.matrix --runs-root runs`` writes every cell; ``--scenario`` and
    ``--plant`` narrow it; ``--dry-run`` prints the cells without integrating anything.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--scenario", action="append", default=None, help="scenario id filter")
    parser.add_argument("--plant", action="append", default=None, help="plant id filter")
    parser.add_argument("--tier", action="append", default=None, help="tier filter")
    parser.add_argument("--replicates", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cells = matrix_cells(replicates=args.replicates)
    if args.scenario:
        cells = [c for c in cells if c.scenario_id in set(args.scenario)]
    if args.plant:
        cells = [c for c in cells if c.plant in set(args.plant)]
    if args.tier:
        cells = [c for c in cells if c.tier in set(args.tier)]

    if args.dry_run:
        for cell in cells:
            print(cell)
        print(f"{len(cells)} cells")
        return 0

    results = generate_matrix(cells, runs_root=args.runs_root)
    failed = [r for r in results if not r.ok]
    soured = [r for r in results if r.ok and r.sound is False]
    for result in results:
        print(result)
    print(f"{len(results) - len(failed)}/{len(results)} cells generated")
    print(f"{len(results) - len(failed) - len(soured)}/{len(results)} are sound digesters")
    if soured:
        print("SOURED cells (generated, but not a working digester):")
        for result in soured:
            print(f"  {result.cell} ({result.run_id})")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
