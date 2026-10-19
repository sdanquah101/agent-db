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

The first attempt's outputs are set aside beside the run (``workflows/p2.unfinished-N/``,
the next free N, with that attempt's visible ``calls.jsonl``) before the rerun regenerates
the cell, so the report can name what failed; an offline cell unfinished twice has its last
attempt set aside too, so nothing unfinished stays at ``workflows/p2``.

**A stopped driver** (the review of ``b837c64``, S-2). Each attempt is journalled in an
in-flight file before its workflow starts. At start-up, a cell with an in-flight attempt
but no result and no unfinished record **is** an unfinished attempt: live, it is recorded
unfinished and the driver stops (no rerun without approval); offline, it counts as that
attempt, so at most one rerun follows in all.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal["counted", "unfinished_live", "unfinished_twice"]


def read_unfinished(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """Every unfinished record in ``paths`` (JSON-lines files or single JSON files)."""
    out: list[dict[str, Any]] = []
    for path in sorted(paths):
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            out += [json.loads(x) for x in text.splitlines() if x.strip()]
        elif text.strip():
            out.append(json.loads(text))
    return out


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
                    "failure_reason": (a.get("summary") or {}).get(
                        "failure_reason", a.get("failure_reason", "")
                    ),
                    "rule": a.get("rule"),
                }
                for a in self.attempts
            ],
        }  # fmt: skip


def run_counted(
    attempt: Callable[[int], dict[str, Any]],
    *,
    live: bool,
    prior: Sequence[dict[str, Any]] = (),
    is_finished: Callable[[dict[str, Any]], bool] = finished,
) -> Attempted:
    """Run one cell and seed under the rerun rule; ``attempt(n)`` runs attempt ``n``.

    ``prior`` holds attempts already made and unfinished (a stopped driver's, from the
    in-flight journal): they count, so a live cell with one is not run again, and an
    offline cell with one gets only its rerun.

    Returns:
        ``counted`` with the finished record last; ``unfinished_live`` after one unfinished
        live attempt (no rerun); ``unfinished_twice`` after an unfinished offline attempt and
        an unfinished rerun.
    """
    attempts = list(prior)
    limit = 1 if live else 2
    while len(attempts) < limit:
        record = attempt(len(attempts) + 1)
        attempts.append(record)
        if is_finished(record):
            return Attempted("counted", attempts)
    return Attempted("unfinished_live" if live else "unfinished_twice", attempts)


class InFlight:
    """The in-flight journal: one line per attempt, written before its workflow starts."""

    STOPPED = "the driver stopped during this attempt: no result was recorded"

    def __init__(self, path: Path) -> None:
        """Journal into ``path`` (a JSON-lines file in the store)."""
        self.path = Path(path)

    def start(self, cell: str, replicate: int, attempt: int, run_id: str) -> None:
        """Record that attempt ``attempt`` of ``(cell, replicate)`` is about to run."""
        line = {"cell": cell, "replicate": replicate, "attempt": attempt, "run_id": run_id,
                "started": datetime.now(UTC).isoformat(timespec="seconds")}  # fmt: skip
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")

    def orphans(self, settled: set[tuple[str, int]]) -> dict[tuple[str, int], list[dict]]:
        """Each unsettled cell's journalled attempts, as unfinished records, oldest first.

        ``settled`` holds the cells with a result or an unfinished record; any other cell
        in the journal was left by a stopped driver.
        """
        if not self.path.is_file():
            return {}
        by_cell: dict[tuple[str, int], dict[int, dict]] = {}
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            x = json.loads(raw)
            key = (str(x["cell"]), int(x["replicate"]))
            if key in settled:
                continue
            by_cell.setdefault(key, {})[int(x["attempt"])] = {
                "cell": key[0], "replicate": key[1], "attempt": int(x["attempt"]),
                "run_id": x["run_id"], "outcome": "pending", "rule": None,
                "summary": {"completed": False, "error": self.STOPPED,
                            "failure_reason": "driver_stopped"},
            }  # fmt: skip
        return {k: [v[n] for n in sorted(v)] for k, v in by_cell.items()}


def set_aside(run_root: Path, attempt: int) -> Path | None:
    """Keep an unfinished attempt's outputs and visible log before the cell is regenerated.

    Into ``workflows/p2.unfinished-N``, ``N`` the attempt or the next free number after it:
    an earlier set-aside is never overwritten (the review of ``b837c64``, S-2).
    """
    out = run_root / "workflows" / "p2"
    if not out.is_dir():
        return None
    n = attempt
    while (run_root / "workflows" / f"p2.unfinished-{n}").exists():
        n += 1
    dest = run_root / "workflows" / f"p2.unfinished-{n}"
    shutil.move(str(out), str(dest))
    calls = run_root / "calls.jsonl"
    if calls.is_file():
        shutil.copy2(calls, dest / "calls.jsonl")
    return dest
