"""The P0 freeze check: one pilot cell gives the same run at the reviewed base and at the head.

The coordinator's decision of 2026-09-29, amended by the review of ``cc256fd``: a stored
golden is machine-bound, because P0 sizes its plan from the measured seconds per
evaluation (the ``3ea1dee`` golden's 202 evaluations became 271 on the reviewer's
machine). So the check is a same-machine, same-session comparison of two heads: the
pilot cell S0-01 plant B tier A runs at the reviewed base (``origin/main`` unless
``P0_FREEZE_BASE`` names another ref) in a temporary worktree and at this checkout,
back to back, through one standalone cell runner; the positive-control driver's
normalised states (``scripts.positive_control._normalise``, run ids masked) and the
visible ``calls.jsonl`` projections (seq, name, version, args hash, outcome, detail)
must be equal.

It takes about two hours and must run alone on the machine (P0's plan reads the measured
evaluation rate), so it is deselected by default: ``pytest -m p0_freeze``, before any
live P1 cell. It does not touch ``workflows/p0_scripted/`` or ``configs/workflows/p0.yaml``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.p0_freeze_golden import CELL, normalised_state_digest

REPO = Path(__file__).resolve().parents[1]
CALL_FIELDS = ("seq", "name", "version", "args_hash", "outcome", "detail")

# One runner for both heads, written outside either tree so that the base ref needs no
# file this branch added; it imports the tree that PYTHONPATH names.
_RUNNER = """
import json, sys
from pathlib import Path
from scenarios.schema import load_scenario
from sim.plants import load_plant_config
from sim.run.harness import generate_run
from tools.runner import REPO_ROOT, run_workflow
store, sid, plant, tier = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
scenario = load_scenario(REPO_ROOT / "scenarios" / f"{sid}.yaml")
run = generate_run(scenario, tier, plant=load_plant_config(plant), runs_root=store / "runs")
result = run_workflow(run.run_id, "p0", runs_root=store / "runs", scenario=scenario)
print(json.dumps({"run_id": run.run_id, "completed": result.completed, "error": result.error}))
"""


def run_cell_at(tree: Path, store: Path, runner: Path) -> tuple[str, dict, list[dict]]:
    """Run the cell with the code of ``tree``; the run id, its state and its visible calls."""
    env = {**os.environ, "PYTHONPATH": str(tree)}
    out = subprocess.run(
        [sys.executable, str(runner), str(store), *CELL],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    last = json.loads(out.stdout.strip().splitlines()[-1])
    assert last["completed"] and not last["error"], last
    run_dir = store / "runs" / last["run_id"]
    state = json.loads((run_dir / "workflows" / "p0" / "state.json").read_text("utf-8"))
    calls = [json.loads(x) for x in (run_dir / "calls.jsonl").read_text("utf-8").splitlines()]
    return last["run_id"], state, calls


def _projection(calls: list[dict]) -> list[tuple]:
    return [tuple(c.get(k) for k in CALL_FIELDS) for c in calls]


@pytest.mark.p0_freeze
def test_the_p0_pilot_cell_is_the_same_run_at_the_base_and_at_the_head(tmp_path):
    base_ref = os.environ.get("P0_FREEZE_BASE", "origin/main")
    base = tmp_path / "base"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(base), base_ref],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    try:
        runner = tmp_path / "run_cell.py"
        runner.write_text(_RUNNER, encoding="utf-8")
        # back to back, each alone: the base first, then this checkout
        base_id, base_state, base_calls = run_cell_at(base, tmp_path / "store_base", runner)
        head_id, head_state, head_calls = run_cell_at(REPO, tmp_path / "store_head", runner)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(base)],
            cwd=REPO,
            check=False,
            capture_output=True,
        )
    assert base_state["final"]["label"] == head_state["final"]["label"]
    assert base_calls  # two empty call logs must not pass the comparison (review of 78ecb03)
    assert _projection(base_calls) == _projection(head_calls)
    assert normalised_state_digest(base_state, base_id) == normalised_state_digest(
        head_state, head_id
    )
