"""The records one run is scored from, and nothing else (proposal §6.7; CLAUDE.md rule 3).

A :class:`RunRecords` is loaded from exactly these files:

==========================================  ==============================================
``truth_store/<id>/manifest.json``          the complete manifest (plant, tier, horizon)
``truth_store/<id>/faults.json``            the answer key: ``truth_label``, the level, the
                                            scenario's ``correct_conclusion``
``truth_store/<id>/parameters.json``        the true parameters per integration segment
``truth_store/<id>/calls.jsonl``            the truth-side log: timestamps, runtimes, the
                                            registry's meter counts, ``injected_failure``
``runs/<id>/calls.jsonl``                   the visible log the workflow's actions name
``runs/<id>/workflows/<wf>/state.json``     the §6.6 task state
``runs/<id>/workflows/<wf>/summary.json``   what the runner recorded from its side
``truth_store/index.jsonl``                 the map from run id to its cell (optional)
``truth_store/<id>/admissible.json``        the distinguishability analysis's admissible
                                            label set (optional; docs/distinguishability.md)
==========================================  ==============================================

Nothing here imports :mod:`workflows`, reads a scenario file or a plant, or evaluates a
model: the scorer is a reader of records. A missing or invalid record is a field of the
result (``state`` is ``None``, ``problems`` says why), never an exception, because a failed
run stays in the denominator (§6.7 D).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sim.run.layout import INDEX_FILE, RUNS_ROOT, RunPaths, truth_store_for
from state.provenance import CallRecord, read_calls
from state.task_state import OUTPUTS_DIR, TaskState

__all__ = ["RunRecords", "index_entries", "load_records", "runs_with_output", "selected_runs"]


@dataclass(frozen=True)
class RunRecords:
    """Everything the scorer reads about one run of one workflow."""

    run_id: str
    workflow: str
    scenario_id: str
    level: int
    plant: str
    tier: str
    seed: int | None
    replicate: int
    duration_days: float
    truth_labels: tuple[str, ...]
    correct_conclusion: dict[str, Any]
    truth_parameters: dict[str, Any]
    """``parameters.json`` as written by the harness (segments, fitted extensions)."""
    state: TaskState | None
    """The validated task state, or ``None`` when absent or invalid."""
    state_raw: dict[str, Any] | None
    summary: dict[str, Any] | None
    visible_calls: tuple[CallRecord, ...]
    truth_calls: tuple[CallRecord, ...]
    problems: tuple[str, ...] = field(default=())
    """Why a record is missing or unusable, in words; empty for a complete run."""
    admissible: dict[str, Any] | None = None
    """``admissible.json`` when the distinguishability analysis has run on this cell."""

    @property
    def launched(self) -> bool:
        """Whether the runner ever launched this workflow on the run (it wrote a summary)."""
        return self.summary is not None


def _json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return raw if isinstance(raw, dict) else None


def index_entries(truth_store: Path) -> list[dict[str, Any]]:
    """Every line of the truth-side index (empty when there is none)."""
    index = Path(truth_store) / INDEX_FILE
    if not index.is_file():
        return []
    out = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def load_records(
    run_id: str,
    workflow: str,
    *,
    runs_root: Path = RUNS_ROOT,
    truth_store: Path | None = None,
) -> RunRecords:
    """Load the records of one run.

    Raises:
        FileNotFoundError: If the truth store has no entry for the run (there is nothing to
            score against; every other absence is a ``problem`` of the result).
    """
    store = truth_store_for(runs_root) if truth_store is None else Path(truth_store)
    paths = RunPaths.for_run(run_id, runs_root, store)
    problems: list[str] = []

    manifest = _json(paths.truth_manifest)
    faults = _json(paths.truth_faults)
    if manifest is None or faults is None:
        missing = [
            f"{path.name} is {'missing' if not path.is_file() else 'not a JSON object'}"
            for path, doc in ((paths.truth_manifest, manifest), (paths.truth_faults, faults))
            if doc is None
        ]
        raise FileNotFoundError(f"{paths.truth}: {'; '.join(missing)} (nothing to score against)")
    parameters = _json(paths.truth_parameters) or {}
    if not parameters:
        problems.append("truth parameters.json missing")

    entry = next((e for e in index_entries(store) if e.get("run_id") == run_id), {})

    out_dir = paths.root / OUTPUTS_DIR / workflow
    state_raw = _json(out_dir / "state.json")
    state: TaskState | None = None
    if state_raw is None:
        problems.append("state.json missing or not a JSON object")
    else:
        try:
            state = TaskState.model_validate(state_raw)
        except ValidationError as exc:
            problems.append(f"state.json invalid: {exc.error_count()} error(s)")
    summary = _json(out_dir / "summary.json")
    if summary is None:
        problems.append("summary.json missing (the runner never launched this workflow)")

    visible: tuple[CallRecord, ...] = ()
    truth_calls: tuple[CallRecord, ...] = ()
    try:
        visible = tuple(read_calls(paths.root))
    except (FileNotFoundError, ValueError):
        problems.append("visible calls.jsonl missing or unreadable")
    try:
        truth_calls = tuple(read_calls(paths.truth))
    except (FileNotFoundError, ValueError):
        problems.append("truth-side calls.jsonl missing or unreadable")

    return RunRecords(
        run_id=run_id,
        workflow=workflow,
        scenario_id=str(faults.get("scenario_id", entry.get("scenario_id", ""))),
        level=int(faults.get("level", entry.get("level", manifest.get("level", -1)))),
        plant=str(manifest.get("plant", entry.get("plant", ""))),
        tier=str(manifest.get("tier", entry.get("tier", ""))),
        seed=None if entry.get("seed") is None else int(entry["seed"]),
        replicate=int(entry.get("replicate", 0)),
        duration_days=float(manifest.get("duration_days", 0.0)),
        truth_labels=tuple(str(x) for x in faults.get("truth_label", ())),
        correct_conclusion=dict(faults.get("correct_conclusion", {})),
        truth_parameters=parameters,
        state=state,
        state_raw=state_raw,
        summary=summary,
        visible_calls=visible,
        truth_calls=truth_calls,
        problems=tuple(problems),
        admissible=_json(paths.truth / "admissible.json"),
    )


def runs_with_output(runs_root: Path, workflow: str) -> list[str]:
    """Run ids under ``runs_root`` on which the workflow left an output directory."""
    root = Path(runs_root)
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / OUTPUTS_DIR / workflow).is_dir()
    )


def selected_runs(
    truth_store: Path,
    *,
    runs_root: Path,
    workflow: str,
    run_ids: Sequence[str] | None = None,
    scenarios: Sequence[str] | None = None,
    plants: Sequence[str] | None = None,
    tiers: Sequence[str] | None = None,
    levels: Sequence[int] | None = None,
    everything: bool = False,
) -> list[str]:
    """The run ids a command line selects, in index order.

    An explicit ``run_ids`` list is taken as given (a run never launched is then scored as
    not completed); a filter or ``everything`` selects the index entries matching it on
    which the workflow left an output directory.
    """
    if run_ids:
        return list(dict.fromkeys(run_ids))
    with_output = set(runs_with_output(runs_root, workflow))
    out = []
    for entry in index_entries(truth_store):
        rid = str(entry.get("run_id"))
        if rid not in with_output:
            continue
        if scenarios and str(entry.get("scenario_id")) not in set(scenarios):
            continue
        if plants and str(entry.get("plant")) not in set(plants):
            continue
        if tiers and str(entry.get("tier")) not in set(tiers):
            continue
        if levels is not None and int(entry.get("level", -1)) not in set(levels):
            continue
        if not (everything or scenarios or plants or tiers or levels is not None):
            continue
        out.append(rid)
    return out
