"""The privileged runner: a workflow on a generated run, through the registry and the jail.

``run_workflow(run_id, "p0")`` opens the run's registry (:func:`tools.open_registry`: the
truth-side index, the budget, the Level-8 directive, the fitted model), writes the
workflow's configuration into a fresh sandbox (:func:`tools.workflow_config.sandbox_config`:
the declared settings, sensor noise and plant geometry, nothing of the run), launches the
workflow script in the jail (:func:`tools.sandbox.launch`) with the run's directory served
read-only and ``runs/<id>/workflows/<name>/`` as its one writable place, validates the
task state it wrote against :class:`state.task_state.TaskState`, and records the cell's
cost beside it in ``summary.json`` (wall-clock, evaluations, assay units, completion, the
final label) from this side -- the evaluations, assay units and call count from the
registry's own meter, not from the state (:class:`WorkflowResult`).

**Nothing hidden enters the jail.** The sandbox holds the stub, the script, the
configuration document and the socket; the run's directory is served through the run
view; the truth store is never mounted, named or passed. The sandbox root must lie
outside the repository and the run store (the launcher refuses otherwise); by default a
temporary directory of the host.

The command line runs one cell or a batch over the truth-side index::

    python -m tools.runner --workflow p0 --run <id> --runs-root runs
    python -m tools.runner --workflow p0 --all --level 0-5 --plant B --tier A

The batch writes one row per cell to ``reports/<workflow>_pilot.csv`` (the pilot table
of ``docs/p0_design.md`` §5), with the cell's truth label beside the workflow's final
label -- that table is evaluator-side and lives under ``reports/``, never under a run.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from scenarios.schema import Scenario, load_scenario
from sim.run.layout import INDEX_FILE, RUNS_ROOT, RunPaths, truth_store_for
from state.task_state import TaskState
from tools.privileged import SCENARIOS_DIR, open_registry
from tools.registry import Registry
from tools.sandbox import REPO_ROOT, SandboxError, launch
from tools.server import OUTPUTS_DIR
from tools.workflow_config import load_p0, sandbox_config

__all__ = ["WORKFLOWS", "WorkflowResult", "batch", "main", "run_workflow", "write_table"]

WORKFLOWS: dict[str, Path] = {"p0": REPO_ROOT / "workflows" / "p0_scripted" / "pipeline.py"}
"""The workflow scripts the runner knows, by name."""

REPORTS_DIR = REPO_ROOT / "reports"


@dataclass
class WorkflowResult:
    """What one cell cost and what the workflow concluded (``summary.json``).

    The cost fields (``simulator_evals_used``, ``assay_units_used``, ``n_calls``, the
    totals) are read from the **registry's meter** on this, the privileged, side after the
    launch -- never from the workflow's task state, which is its self-report (the evaluation
    session, 2026-09-22, on follow-up (d) of milestone 5: rule 3 says evaluation reads logs
    only). The self-reported counts are kept beside them, so the evaluator can score a
    misreport; ``tokens_used`` is the field an LLM workflow's runner fills.
    """

    run_id: str
    workflow: str
    completed: bool
    returncode: int | None
    wall_s: float
    simulator_evals_used: int | None
    simulator_evals_total: int | None
    assay_units_used: int | None
    assay_units_total: int | None
    wall_clock_min_total: float | None
    n_calls: int | None
    label: str | None
    cost_source: str = "registry_meter"
    self_reported_simulator_evals_used: int | None = None
    self_reported_assay_units_used: int | None = None
    self_reported_n_calls: int | None = None
    tokens_used: int | None = None
    secondary_labels: list[str] = field(default_factory=list)
    confidence: float | None = None
    flag_sensor: str | None = None
    abstentions: list[str] = field(default_factory=list)
    interval_method: str | None = None
    approved: list[str] = field(default_factory=list)
    steps_completed: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)
    tool_failures: list[str] = field(default_factory=list)
    state_valid: bool = False
    error: str = ""
    stderr_tail: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe."""
        return asdict(self)


def _fresh_sandbox(sandbox_root: Path | None, workflow: str) -> Path:
    """A new sandbox directory, short-named: the socket inside it is an AF_UNIX path.

    Raises:
        ValueError: If the socket path would exceed what the kernel accepts (108 bytes).
    """
    if sandbox_root is None:
        box = Path(tempfile.mkdtemp(prefix=f"adb-{workflow}-"))
    else:
        root = Path(sandbox_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        box = Path(tempfile.mkdtemp(prefix=f"{workflow}-", dir=root))
    if len(str(box / "registry.sock").encode()) >= 100:
        shutil.rmtree(box, ignore_errors=True)
        raise ValueError(
            f"sandbox root {box.parent} is too deep for a Unix socket path; give a shorter one"
        )
    return box


def run_workflow(
    run_id: str,
    workflow: str = "p0",
    *,
    runs_root: Path = RUNS_ROOT,
    truth_store: Path | None = None,
    sandbox_root: Path | None = None,
    timeout_s: float | None = None,
    scenario: Scenario | None = None,
    keep_sandbox: bool = False,
    config_path: Path | None = None,
) -> WorkflowResult:
    """Run one workflow on one generated run.

    Args:
        run_id: The opaque run id.
        workflow: A key of :data:`WORKFLOWS`.
        runs_root: Root of the run store.
        truth_store: Root of the truth store (default: the sibling of ``runs_root``).
        sandbox_root: Where to make the sandbox directory (default: the host's temporary
            directory). Must lie outside the repository and the run store's parent.
        timeout_s: Kill the jail after this long (default: the cell's wall-clock allowance
            plus ``runner.timeout_margin_min``).
        scenario: The run's scenario, if the caller holds it (else the truth-side index).
        keep_sandbox: Leave the sandbox directory behind for inspection.
        config_path: A different ``p0.yaml`` (tests).

    Returns:
        The result; ``summary.json`` is written beside the workflow's outputs.

    Raises:
        KeyError: Unknown workflow.
        SandboxError: The jail could not be built (the workflow was not run).
    """
    if workflow not in WORKFLOWS:
        raise KeyError(f"unknown workflow {workflow!r}; known: {sorted(WORKFLOWS)}")
    store = truth_store_for(runs_root) if truth_store is None else Path(truth_store)
    paths = RunPaths.for_run(run_id, runs_root, store)
    config = load_p0() if config_path is None else load_p0(config_path)
    registry = open_registry(run_id, runs_root=runs_root, truth_store=store, scenario=scenario)
    if timeout_s is None:
        timeout_s = (registry.budget.wall_clock_min + config.runner.timeout_margin_min) * 60.0
    box = _fresh_sandbox(sandbox_root, workflow)
    (box / "cwd").mkdir(exist_ok=True)
    (box / "cwd" / "p0_config.json").write_text(
        json.dumps(sandbox_config(config), indent=1, sort_keys=True), encoding="utf-8"
    )
    started = time.perf_counter()
    returncode: int | None = None
    error = ""
    stderr = ""
    try:
        result = launch(
            WORKFLOWS[workflow],
            registry,
            sandbox=box,
            run_dir=paths.root,
            timeout_s=timeout_s,
            workflow=workflow,
        )
        returncode, stderr = result.returncode, result.stderr
        if returncode != 0:
            error = f"the workflow exited with status {returncode}"
    except subprocess.TimeoutExpired:
        error = f"the workflow was killed after {timeout_s:.0f} s"
    except SandboxError as exc:
        error = f"SandboxError: {exc}"
        raise
    finally:
        wall_s = time.perf_counter() - started
        if not keep_sandbox:
            shutil.rmtree(box, ignore_errors=True)
    summary = _summarise(paths, workflow, wall_s, returncode, error, stderr, registry=registry)
    out_dir = paths.root / OUTPUTS_DIR / workflow
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(summary.as_dict(), indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def _summarise(
    paths: RunPaths,
    workflow: str,
    wall_s: float,
    returncode: int | None,
    error: str,
    stderr: str,
    *,
    registry: Registry,
) -> WorkflowResult:
    """The summary of one launch: the meter's cost, the state's conclusion.

    The cost fields come from ``registry`` (its meter, on this side of the socket) whatever
    the state says; the state supplies the conclusion and its own counts as a self-report.
    """
    state_path = paths.root / OUTPUTS_DIR / workflow / "state.json"
    metered = registry.remaining()
    result = WorkflowResult(
        run_id=paths.root.name,
        workflow=workflow,
        completed=False,
        returncode=returncode,
        wall_s=round(wall_s, 3),
        simulator_evals_used=registry.evaluations_used,
        simulator_evals_total=int(metered.simulator_evals_total),
        assay_units_used=registry.assay_units_used,
        assay_units_total=int(metered.assay_units_total),
        wall_clock_min_total=float(metered.wall_clock_min_total),
        n_calls=int(metered.n_calls),
        label=None,
        error=error,
        stderr_tail=stderr[-2000:],
    )
    if not state_path.is_file():
        result.error = result.error or "the workflow wrote no state"
        return result
    try:
        state = TaskState.model_validate_json(state_path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        result.error = (result.error + "; " if result.error else "") + f"state.json invalid: {exc}"
        return result
    result.state_valid = True
    result.completed = bool(state.final.completed) and returncode == 0
    result.self_reported_simulator_evals_used = state.budget.simulator_evals_used
    result.self_reported_assay_units_used = state.budget.assay_units_used
    result.self_reported_n_calls = state.budget.n_calls
    result.label = state.final.label
    result.secondary_labels = list(state.final.secondary_labels)
    result.confidence = state.final.confidence
    result.flag_sensor = state.classification.flag_sensor
    result.abstentions = list(state.final.abstentions)
    result.interval_method = state.final.interval_method
    result.approved = list(state.screening.approved)
    result.steps_completed = list(state.plan.steps_completed)
    result.fallbacks = list(state.plan.fallbacks)
    result.tool_failures = [f"{f.name}:{f.kind}" for f in state.tool_failures]
    return result


# ------------------------------------------------------------------ the batch


def _index(truth_store: Path) -> list[dict[str, Any]]:
    index = truth_store / INDEX_FILE
    if not index.is_file():
        raise FileNotFoundError(f"{index} does not exist; generate the matrix first")
    rows = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _levels(spec: str | None) -> set[int] | None:
    if not spec:
        return None
    out: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def select_cells(
    truth_store: Path,
    *,
    scenarios: Sequence[str] | None = None,
    plants: Sequence[str] | None = None,
    tiers: Sequence[str] | None = None,
    levels: str | None = None,
    library: dict[str, Scenario] | None = None,
) -> list[dict[str, Any]]:
    """The index rows matching the filters, in index order, each with its scenario."""
    lib = library if library is not None else {}
    wanted_levels = _levels(levels)
    out = []
    for row in _index(truth_store):
        sid = str(row["scenario_id"])
        if scenarios and sid not in set(scenarios):
            continue
        if plants and str(row["plant"]) not in set(plants):
            continue
        if tiers and str(row["tier"]) not in set(tiers):
            continue
        if sid not in lib:
            lib[sid] = load_scenario(SCENARIOS_DIR / f"{sid}.yaml")
        if wanted_levels is not None and lib[sid].level not in wanted_levels:
            continue
        out.append({**row, "scenario": lib[sid]})
    return out


def _truth_multipliers(paths: RunPaths) -> dict[str, float]:
    """The truth's last-segment parameters as multipliers of the BSM2 defaults."""
    from sim.adm1 import load_parameters

    base = load_parameters().namespace()
    payload = json.loads(paths.truth_parameters.read_text(encoding="utf-8"))
    segment = payload["segments"][-1]["parameters"]
    out: dict[str, float] = {}
    for group in ("kinetics", "stoichiometry", "physchem"):
        for name, value in segment.get(group, {}).items():
            if name in base and float(base[name]) != 0.0:
                out[name] = float(value) / float(base[name])
    return out


def table_row(cell: dict[str, Any], paths: RunPaths, result: WorkflowResult) -> dict[str, Any]:
    """One row of the pilot table: the cell, its answer key, the cost and the conclusion."""
    scenario: Scenario = cell["scenario"]
    truth_labels = [str(t) for t in scenario.truth_label]
    row: dict[str, Any] = {
        "run_id": result.run_id,
        "scenario_id": scenario.id,
        "level": scenario.level,
        "plant": cell["plant"],
        "tier": cell["tier"],
        "truth_label": "+".join(truth_labels),
        "final_label": result.label or "",
        "label_match": (result.label in truth_labels) if result.label else False,
        "secondary_labels": "+".join(result.secondary_labels),
        "flag_sensor": result.flag_sensor or "",
        "correct_flag_sensor": scenario.correct_conclusion.flag_sensor or "",
        "completed": result.completed,
        "wall_s": result.wall_s,
        "wall_clock_min_budget": scenario.budget.wall_clock_min,
        "evals_used": result.simulator_evals_used,
        "evals_budget": scenario.budget.simulator_evals,
        "assay_units_used": result.assay_units_used,
        "assay_units_budget": scenario.budget.assay_units,
        "n_calls": result.n_calls,
        "interval_method": result.interval_method or "",
        "approved": "+".join(result.approved),
        "abstentions": "+".join(result.abstentions),
        "fallbacks": len(result.fallbacks),
        "tool_failures": "+".join(result.tool_failures),
        "error": result.error,
        "recovery": "",
    }
    # parameter recovery where scored: Levels 0-5 only, never Level 6 (§6.7 A)
    state_path = paths.root / OUTPUTS_DIR / result.workflow / "state.json"
    if scenario.level <= 5 and state_path.is_file() and result.state_valid:
        state = TaskState.model_validate_json(state_path.read_text(encoding="utf-8"))
        truth = _truth_multipliers(paths)
        parts = []
        for name, est in state.final.parameters.items():
            if name not in truth:
                continue
            covered = (
                est.lower is not None
                and est.upper is not None
                and est.lower <= truth[name] <= est.upper
            )
            inside = "in" if covered else "out"
            parts.append(f"{name}:{est.estimate:.3f}/{truth[name]:.3f}/{inside}")
        row["recovery"] = " ".join(parts)
    return row


TABLE_COLUMNS = [
    "run_id", "scenario_id", "level", "plant", "tier", "truth_label", "final_label",
    "label_match", "secondary_labels", "flag_sensor", "correct_flag_sensor", "completed",
    "wall_s", "wall_clock_min_budget", "evals_used", "evals_budget", "assay_units_used",
    "assay_units_budget", "n_calls", "interval_method", "approved", "abstentions",
    "fallbacks", "tool_failures", "error", "recovery",
]  # fmt: skip


def write_table(rows: Sequence[dict[str, Any]], path: Path) -> None:
    """Write (or extend, replacing rows of the same run id) the machine-readable table."""
    existing: dict[str, dict[str, Any]] = {}
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                existing[row["run_id"]] = row
    for row in rows:
        existing[str(row["run_id"])] = {k: row.get(k, "") for k in TABLE_COLUMNS}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TABLE_COLUMNS)
        writer.writeheader()
        for run_id in sorted(existing):
            writer.writerow(existing[run_id])


def batch(
    cells: Sequence[dict[str, Any]],
    workflow: str,
    *,
    runs_root: Path,
    truth_store: Path,
    table: Path | None,
    sandbox_root: Path | None = None,
    keep_sandbox: bool = False,
) -> list[dict[str, Any]]:
    """Run the workflow on every cell, writing the table after each.

    A stopped batch keeps the rows it wrote.
    """
    rows = []
    for cell in cells:
        run_id = str(cell["run_id"])
        paths = RunPaths.for_run(run_id, runs_root, truth_store)
        print(
            f"{cell['scenario_id']} plant {cell['plant']} tier {cell['tier']} ({run_id}) ...",
            flush=True,
        )
        try:
            result = run_workflow(
                run_id,
                workflow,
                runs_root=runs_root,
                truth_store=truth_store,
                sandbox_root=sandbox_root,
                scenario=cell["scenario"],
                keep_sandbox=keep_sandbox,
            )
        except SandboxError as exc:
            print(f"  SANDBOX ERROR: {exc}", flush=True)
            raise
        row = table_row(cell, paths, result)
        rows.append(row)
        if table is not None:
            write_table([row], table)
        print(
            f"  -> {row['final_label'] or '-'} (truth {row['truth_label']}), "
            f"{'completed' if row['completed'] else 'INCOMPLETE'} in {row['wall_s']:.0f} s, "
            f"{row['evals_used']}/{row['evals_budget']} evals, "
            f"{row['assay_units_used']}/{row['assay_units_budget']} assay units"
            + (f"; {row['error']}" if row["error"] else ""),
            flush=True,
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    """Command line: one run, or a batch over the index."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workflow", default="p0", choices=sorted(WORKFLOWS))
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--truth-store", type=Path, default=None)
    parser.add_argument("--sandbox-root", type=Path, default=None)
    parser.add_argument("--run", action="append", default=None, help="run id (repeatable)")
    parser.add_argument("--all", action="store_true", help="every cell of the index")
    parser.add_argument("--scenario", action="append", default=None)
    parser.add_argument("--plant", action="append", default=None)
    parser.add_argument("--tier", action="append", default=None)
    parser.add_argument("--level", default=None, help="e.g. 0-5 or 0,2,8")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--table", type=Path, default=None, help="CSV to write rows to")
    parser.add_argument("--keep-sandbox", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    runs_root = Path(args.runs_root)
    store = truth_store_for(runs_root) if args.truth_store is None else Path(args.truth_store)
    if not args.run and not (args.all or args.scenario or args.plant or args.tier or args.level):
        parser.error("give --run <id> or a selection (--all, --scenario, --plant, --tier, --level)")
    cells = select_cells(
        store, scenarios=args.scenario, plants=args.plant, tiers=args.tier, levels=args.level
    )
    if args.run:
        wanted = set(args.run)
        cells = [c for c in cells if c["run_id"] in wanted]
        missing = wanted - {c["run_id"] for c in cells}
        if missing:
            parser.error(f"not in the index: {sorted(missing)}")
    if args.limit is not None:
        cells = cells[: args.limit]
    if args.dry_run:
        for cell in cells:
            print(
                f"{cell['scenario_id']} plant {cell['plant']} tier {cell['tier']} {cell['run_id']}"
            )
        print(f"{len(cells)} cells")
        return 0
    table = args.table
    if table is None:
        table = REPORTS_DIR / f"{args.workflow}_pilot.csv"
    rows = batch(
        cells,
        args.workflow,
        runs_root=runs_root,
        truth_store=store,
        table=table,
        sandbox_root=args.sandbox_root,
        keep_sandbox=args.keep_sandbox,
    )
    done = sum(1 for r in rows if r["completed"])
    print(f"{done}/{len(rows)} cells completed; table at {table}")
    return 0 if done == len(rows) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
