"""The P0 freeze golden: run the pilot cell S0-01 B/A and print its normalised digests.

Usage::

    python -m scripts.p0_freeze_golden <store>

The digests are what ``tests/test_p0_freeze.py`` compares a re-run against: the
positive-control driver's normalised state (``scripts.positive_control._normalise``, the
run id masked) and the summary without its volatile fields. The golden was made at
``3ea1dee``, before the infrastructure changes of 2026-09-29 (the coordinator's decision);
regenerate it only on the lead's word, since a new golden hides a P0 change.

Run it alone on the machine: P0's plan reads the measured evaluation rate.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from scripts.positive_control import _normalise

CELL = ("S0-01", "B", "A")
# summary fields that differ between two runs of the same cell for reasons the freeze does
# not cover: the clock, the checkout, the run and store paths, the process's stderr
VOLATILE_SUMMARY = frozenset({"wall_s", "git_commit", "stderr_tail", "run_id", "error"})
READABLE_KEYS = ("final_label", "label", "evals_used", "simulator_evals_used", "n_calls")


def normalised_state_digest(state: dict, run_id: str) -> str:
    """The positive-control normalisation, the run id masked, as one sha256."""
    text = json.dumps(_normalise(state), sort_keys=True).replace(run_id, "<run>")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalised_summary(summary: dict, run_id: str) -> dict:
    """The summary without its volatile fields, the run id masked."""
    kept = {k: v for k, v in summary.items() if k not in VOLATILE_SUMMARY}
    return json.loads(json.dumps(kept, sort_keys=True).replace(run_id, "<run>"))


def summary_digest(summary: dict, run_id: str) -> str:
    """The normalised summary as one sha256."""
    text = json.dumps(normalised_summary(summary, run_id), sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_cell(store: Path) -> tuple[str, dict, dict]:
    """Generate the cell into ``store`` and run P0 on it; the run id, state and summary."""
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from tools.runner import REPO_ROOT, run_workflow
    from tools.server import OUTPUTS_DIR

    sid, plant, tier = CELL
    scenario = load_scenario(REPO_ROOT / "scenarios" / f"{sid}.yaml")
    run = generate_run(scenario, tier, plant=load_plant_config(plant), runs_root=store / "runs")
    result = run_workflow(run.run_id, "p0", runs_root=store / "runs", scenario=scenario)
    if not result.completed or result.error:
        raise RuntimeError(f"P0 did not complete: {result.error!r}\n{result.stderr_tail}")
    out = run.paths.root / OUTPUTS_DIR / "p0"
    state = json.loads((out / "state.json").read_text("utf-8"))
    summary = json.loads((out / "summary.json").read_text("utf-8"))
    return run.run_id, state, summary


def digests_of(out_dir: Path, run_id: str) -> dict:
    """The digests and readable keys of an existing P0 output directory."""
    state = json.loads((out_dir / "state.json").read_text("utf-8"))
    summary = json.loads((out_dir / "summary.json").read_text("utf-8"))
    return {
        "run_id": run_id,
        "state_sha256": normalised_state_digest(state, run_id),
        "summary_sha256": summary_digest(summary, run_id),
        "readable": {k: summary.get(k) for k in READABLE_KEYS if k in summary},
    }


def main(argv: list[str] | None = None) -> int:
    """Run the cell and print the digests as JSON."""
    from tools.server import OUTPUTS_DIR

    store = Path((argv or sys.argv[1:])[0])
    run_id, _state, _summary = run_cell(store)
    out = store / "runs" / run_id / OUTPUTS_DIR / "p0"
    print(json.dumps(digests_of(out, run_id), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
