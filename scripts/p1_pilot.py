"""The P1 development-pilot driver: one process per cell, a few lanes, nothing else running.

Usage::

    python -m scripts.p1_pilot <store> <results.jsonl> [--lanes N] [--config p1.yaml]
        SID:PLANT:TIER ...

Each cell runs in its own subprocess (``--one``), so the registry server of a cell that
the runner kills dies with that cell's process and cannot compute on beside the next one.
At most ``--lanes`` cells run at once (default 3 on a 4-core container). The key comes
from ``OPENAI_API_KEY`` in the environment and is never written anywhere. Every finished
cell appends one JSON line to the results file: the runner's summary and the evaluator's
diagnostic row (development only; never a sweep score, never beside P0).

Operating rules (the coordinator's decision of 2026-09-29, after the killed runs of
2026-09-28):

- **Nothing else runs on the container beside live cells**: no test suite, no other
  batch. A test suite doubled the cost of a simulator evaluation and drove cells into
  the runner's kill margin. Run ``ruff``, ``ruff format --check`` and the full suite
  *before* a batch, never beside one.
- Cells run from a clean, committed checkout (``PYTHONPATH`` at a worktree of the head
  the report names), so every summary records that commit.
- ``--config`` names another P1 configuration for the arm (the expert brief, or an old
  prompt copied beside a configuration whose ``prompts`` point at it); the default is
  ``configs/workflows/p1.yaml``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def run_one(store: Path, sid: str, plant: str, tier: str, config: str | None) -> dict:
    """Generate the cell in ``store`` and run P1 on it; the row for the results file."""
    from eval.records import load_records
    from eval.score import Scorer
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from tools.runner import REPO_ROOT, run_workflow

    t0 = time.time()
    row: dict = {"scenario_id": sid, "plant": plant, "tier": tier, "config": config}
    try:
        scenario = load_scenario(REPO_ROOT / "scenarios" / f"{sid}.yaml")
        run = generate_run(scenario, tier, plant=load_plant_config(plant), runs_root=store / "runs")
        row["run_id"] = run.run_id
        result = run_workflow(
            run.run_id,
            "p1",
            runs_root=store / "runs",
            scenario=scenario,
            config_path=Path(config) if config else None,
        )
        row["summary"] = result.as_dict()
        records = load_records(run.run_id, "p1", runs_root=store / "runs")
        row["score"] = dict(Scorer().score(records))
    except Exception as exc:  # a failed cell is recorded and the batch goes on
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["traceback"] = traceback.format_exc()[-2000:]
    row["driver_wall_s"] = round(time.time() - t0, 1)
    return row


def _child(store: Path, out: Path, cell: str, config: str | None, log_dir: Path) -> str:
    """Run one cell in a subprocess of this interpreter; append its row; return a line."""
    sid, plant, tier = cell.split(":")
    log = log_dir / f"{sid}_{plant}{tier}.log"
    cmd = [sys.executable, "-m", "scripts.p1_pilot", "--one", str(store), str(out), cell]
    if config:
        cmd += ["--config", config]
    with log.open("a", encoding="utf-8") as fh:
        code = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, check=False).returncode
    return f"{cell} exited {code} (log {log})"


def main(argv: list[str] | None = None) -> int:
    """The command line."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("store", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("cells", nargs="+", help="SID:PLANT:TIER")
    ap.add_argument("--lanes", type=int, default=3)
    ap.add_argument("--config", default=None, help="another P1 configuration (an arm)")
    ap.add_argument("--one", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    args.store.mkdir(parents=True, exist_ok=True)
    if args.one:
        (sid, plant, tier) = args.cells[0].split(":")
        row = run_one(args.store, sid, plant, tier, args.config)
        with args.out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        print(f"{sid} {plant}/{tier} done in {row['driver_wall_s']} s", flush=True)
        return 0
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 2
    log_dir = args.store / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, args.lanes)) as pool:
        for line in pool.map(
            lambda c: _child(args.store, args.out, c, args.config, log_dir), args.cells
        ):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
