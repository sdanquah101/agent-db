"""The procedural P2 freeze check: one cell gives the same calls at the base and at the head.

The lead's Q9 ruling B (2026-10-29): the agent arm's verifier reserve is built in
``tools/registry.py``, which every arm runs through. P0, P1 and the procedural P2 set no
reserve and tag no call, so their records cannot change. This check runs the procedural
P2 cell of ``tests/test_p2_workflow.py`` (S0-01, plant C, tier B, 30 days, 300
evaluations) at the reviewed base (``origin/main`` unless ``P2_FREEZE_BASE`` names another
ref) in a temporary worktree and at this checkout, back to back, through one standalone
cell runner, and compares the visible ``calls.jsonl`` projections (seq, name, version, args
hash, outcome, detail; ``tests/test_p0_freeze.py``'s fields) and the arm's label and rule.
The control: the agent arm (``configs/workflows/p2_agents.yaml``, offline) on the same cell
at this checkout, whose calls differ from the procedural arm's.

About half an hour (three jailed runs); deselected by default: ``pytest -m p2_freeze``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CALL_FIELDS = ("seq", "name", "version", "args_hash", "outcome", "detail")
AGENTS_YAML = "configs/workflows/p2_agents.yaml"

# One runner for both heads, written outside either tree; it imports the tree that
# PYTHONPATH names. The cell is tests/test_p2_workflow.py's jailed fixture's.
_RUNNER = """
import json, sys
from pathlib import Path
from scenarios.schema import load_scenario
from sim.plants import load_plant_config
from sim.run.harness import generate_run
from tools.runner import REPO_ROOT, run_workflow
store, config = Path(sys.argv[1]), sys.argv[2]
s = load_scenario(REPO_ROOT / "scenarios" / "S0-01.yaml")
budget = s.budget.model_copy(update={"simulator_evals": 300, "wall_clock_min": 45.0})
s = s.model_copy(update={"duration_days": 30.0, "budget": budget})
run = generate_run(s, "B", plant=load_plant_config("C"), runs_root=store / "runs")
kw = {"config_path": REPO_ROOT / config} if config else {}
result = run_workflow(run.run_id, "p2", runs_root=store / "runs", scenario=s, **kw)
print(json.dumps({"run_id": run.run_id, "completed": result.completed, "error": result.error}))
"""


def run_cell_at(tree: Path, store: Path, runner: Path, config: str = "") -> tuple[dict, list]:
    """Run the cell with the code of ``tree``; the arm's report and its visible calls."""
    env = {**os.environ, "PYTHONPATH": str(tree)}
    out = subprocess.run(
        [sys.executable, str(runner), str(store), config],
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
    report = json.loads((run_dir / "workflows" / "p2" / "report.json").read_text("utf-8"))
    calls = [json.loads(x) for x in (run_dir / "calls.jsonl").read_text("utf-8").splitlines()]
    return report, calls


def _projection(calls: list[dict]) -> list[tuple]:
    return [tuple(c.get(k) for k in CALL_FIELDS) for c in calls]


@pytest.mark.p2_freeze
def test_the_procedural_p2_cell_is_the_same_run_at_the_base_and_at_the_head(tmp_path):
    base_ref = os.environ.get("P2_FREEZE_BASE", "origin/main")
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
        base_report, base_calls = run_cell_at(base, tmp_path / "store_base", runner)
        head_report, head_calls = run_cell_at(REPO, tmp_path / "store_head", runner)
        agent_report, agent_calls = run_cell_at(REPO, tmp_path / "store_agent", runner, AGENTS_YAML)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(base)],
            cwd=REPO,
            check=False,
            capture_output=True,
        )
    assert base_calls  # two empty call logs must not pass the comparison
    assert _projection(base_calls) == _projection(head_calls)
    verdict = ("label", "rule")
    assert [base_report[k] for k in verdict] == [head_report[k] for k in verdict]
    # the control: the agent arm's record on the same cell is not the procedural arm's
    assert agent_calls and _projection(agent_calls) != _projection(head_calls)
    assert agent_report["spend"]["reserves"]["verification"]["simulator_evals_total"] == 80
