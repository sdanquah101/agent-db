"""Unfinished P2 runs are rerun, never scored (the lead's rulings of 2026-10-19).

"A run that crashes or is stopped should not be recorded as no fault. It must be rerun."

- A run is **finished** when the runner saw it complete (``summary.completed``: the task
  state's ``final.completed`` and a clean exit) and its report's outcome is not
  ``pending``. Anything else (a crash, a kill, an unexpected exception, no state, no
  report) is **unfinished**: not a result. It is never pooled, scored or counted as an
  abstention.
- **Offline**, an unfinished run is rerun **once**, automatically, with the same cell and
  seed (the generation is regenerated into the same store, which starts its logs over).
  If the rerun also fails to finish, the driver stops; nothing is scored for that cell and
  seed, and it is reported to the coordinator.
- **Live**, an unfinished run is **never** rerun automatically: a rerun is a new live call,
  which needs the lead's approval relayed by the coordinator. The driver stops, marks the
  run unfinished and reports it.

The first attempt's outputs are set aside beside the run (``workflows/p2.unfinished-1/``,
with that attempt's visible ``calls.jsonl``) before the rerun regenerates the cell, so the
report can name what failed.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Status = Literal["counted", "unfinished_live", "unfinished_twice"]


def finished(record: dict[str, Any]) -> bool:
    """Whether a run's record is a result: the runner saw it complete and it is not pending."""
    summary = record.get("summary") or {}
    completed = summary.get("completed", record.get("completed"))
    return (
        bool(completed)
        and record.get("outcome") not in (None, "pending")
        and (record.get("rule") != "pending")
    )


@dataclass
class Attempted:
    """What came of running one cell and seed: the counted record, or the unfinished ones."""

    status: Status
    attempts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def record(self) -> dict[str, Any] | None:
        """The record to count, if any: only a finished run's."""
        return self.attempts[-1] if self.status == "counted" else None

    def failure(self) -> dict[str, Any]:
        """The report of an unfinished cell: each attempt's run id and error."""
        return {
            "status": self.status,
            "attempts": [
                {
                    "run_id": a.get("run_id"),
                    "completed": bool((a.get("summary") or {}).get("completed",
                                                                   a.get("completed"))),
                    "error": (a.get("summary") or {}).get("error", a.get("error", "")),
                    "failure_reason": (a.get("summary") or {}).get("failure_reason", ""),
                    "rule": a.get("rule"),
                }
                for a in self.attempts
            ],
        }  # fmt: skip


def run_counted(
    attempt: Callable[[int], dict[str, Any]],
    *,
    live: bool,
    is_finished: Callable[[dict[str, Any]], bool] = finished,
) -> Attempted:
    """Run one cell and seed under the rerun rule; ``attempt(n)`` runs attempt ``n`` (1 or 2).

    Returns:
        ``counted`` with the finished record last; ``unfinished_live`` after one unfinished
        live attempt (no rerun); ``unfinished_twice`` after an unfinished offline attempt and
        an unfinished rerun.
    """
    first = attempt(1)
    if is_finished(first):
        return Attempted("counted", [first])
    if live:
        return Attempted("unfinished_live", [first])
    second = attempt(2)
    if is_finished(second):
        return Attempted("counted", [first, second])
    return Attempted("unfinished_twice", [first, second])


def set_aside(run_root: Path, attempt: int) -> Path | None:
    """Keep an unfinished attempt's outputs and visible log before the cell is regenerated."""
    out = run_root / "workflows" / "p2"
    if not out.is_dir():
        return None
    dest = run_root / "workflows" / f"p2.unfinished-{attempt}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(out), str(dest))
    calls = run_root / "calls.jsonl"
    if calls.is_file():
        shutil.copy2(calls, dest / "calls.jsonl")
    return dest
