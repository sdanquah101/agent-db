"""The scorer's command line: ``python -m eval ...``.

Score one run, a list of runs, or a batch selected from the truth-side index::

    python -m eval --workflow p0 --run <id> --out reports/one.csv
    python -m eval --workflow p0 --all --out reports/p0_pilot_scored.csv
    python -m eval --workflow p0 --level 0 --level 1 --plant B --out reports/l01.csv

Writes the per-run table (``<out>.csv`` and ``<out>.json``) and the aggregate per cell
(``<out>_aggregate.csv`` and ``.json``). Reads records only (:mod:`eval.records`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from eval.aggregate import aggregate
from eval.records import selected_runs
from eval.score import Scorer, score_runs
from eval.tables import write_tables
from sim.run.layout import RUNS_ROOT, truth_store_for

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Score a run or a batch and write the tables."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workflow", default="p0")
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--truth-store", type=Path, default=None)
    parser.add_argument("--run", action="append", default=None, help="run id (repeatable)")
    parser.add_argument("--all", action="store_true", help="every scored run of the index")
    parser.add_argument("--scenario", action="append", default=None)
    parser.add_argument("--plant", action="append", default=None)
    parser.add_argument("--tier", action="append", default=None)
    parser.add_argument("--level", action="append", type=int, default=None)
    parser.add_argument("--out", type=Path, required=True, help="per-run CSV to write")
    args = parser.parse_args(argv)

    runs_root = Path(args.runs_root)
    store = truth_store_for(runs_root) if args.truth_store is None else Path(args.truth_store)
    run_ids = selected_runs(
        store,
        runs_root=runs_root,
        workflow=args.workflow,
        run_ids=args.run,
        scenarios=args.scenario,
        plants=args.plant,
        tiers=args.tier,
        levels=args.level,
        everything=args.all,
    )
    if not run_ids:
        parser.error("no run selected: give --run <id>, --all or a filter")
    scorer = Scorer()
    rows = score_runs(run_ids, args.workflow, runs_root=runs_root, truth_store=store, scorer=scorer)
    write_tables(rows, args.out)
    agg = aggregate(rows, scorer.config.aggregate)
    out = Path(args.out)
    write_tables(agg, out.with_name(out.stem + "_aggregate" + out.suffix))
    done = sum(1 for r in rows if r.get("completed"))
    exact = sum(1 for r in rows if r.get("attribution_exact") is True)
    print(
        f"{len(rows)} runs scored ({done} completed, {exact} exact attributions); "
        f"tables at {out} and {out.with_name(out.stem + '_aggregate' + out.suffix)}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
