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

The journal (the review of ``0b9f210``):

- every report reads it, so a stopped cell is listed (``driver_stopped``, "stopped or
  still running") even when no driver has started since (SF-1);
- it is read across every part's file, so a resume under another part count still finds
  the stopped attempt (SF-2);
- each attempt that returns adds a line with its completion and error, so an earlier
  attempt's real error survives when a later one is the attempt stopped (N-1);
- a start line is flushed and synced before the workflow starts, and a torn last line is
  read as an in-flight attempt, never skipped (N-2); a line written after a torn one
  starts on a new line, never glued onto the fragment (the review of ``024da41``, SF-1).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal["counted", "unfinished_live", "unfinished_twice", "driver_stopped"]


def append_synced(path: Path, text: str) -> None:
    """Append ``text`` to ``path``, flushed and synced before returning.

    Never glued onto a torn last line, which would lose it or merge it into another
    record (the review of ``024da41``, SF-1): a newline is written first if the file does
    not end in one. The journal, the results and the unfinished records all append this
    way (B4, 2026-10-19), so a stop between two writes loses at most the one being made.
    """
    path = Path(path)
    torn = False
    if path.is_file() and path.stat().st_size > 0:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            torn = fh.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(("\n" if torn else "") + text)
        fh.flush()
        os.fsync(fh.fileno())


def write_synced(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` whole, through a synced temporary file and a rename."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


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
    """The in-flight journal: a line per attempt before its workflow starts, one as it returns.

    Written to ``path``; read from ``path`` and every file in ``others`` (the other parts'
    journals), so a cell's attempts are found whichever part count journalled them.
    """

    STOPPED = "the driver stopped during this attempt: no result was recorded"
    STILL = "stopped or still running"
    TORN = ("<torn journal line>", -1)
    """The key of a torn line naming no cell: an in-flight attempt of an unknown cell."""

    def __init__(self, path: Path, others: Sequence[Path] = ()) -> None:
        """Journal into ``path``; read it and ``others``."""
        self.path = Path(path)
        self.paths = sorted({self.path, *map(Path, others)})

    def _write(self, line: dict[str, Any]) -> None:
        # the cell and seed first, so a torn line still names them (N-2)
        append_synced(self.path, json.dumps(line, default=str) + "\n")

    def start(self, cell: str, replicate: int, attempt: int, run_id: str) -> None:
        """Record that attempt ``attempt`` of ``(cell, replicate)`` is about to run."""
        self._write({"cell": cell, "replicate": replicate, "event": "start",
                     "attempt": attempt, "run_id": run_id,
                     "started": datetime.now(UTC).isoformat(timespec="seconds")})  # fmt: skip

    def finish(self, cell: str, replicate: int, attempt: int, run_id: str,
               summary: dict[str, Any]) -> None:  # fmt: skip
        """Record that the attempt returned, with the runner's completion and error (N-1)."""
        self._write({"cell": cell, "replicate": replicate, "event": "returned",
                     "attempt": attempt, "run_id": run_id,
                     "completed": bool(summary.get("completed")),
                     "error": summary.get("error", ""),
                     "failure_reason": summary.get("failure_reason", "")})  # fmt: skip

    @staticmethod
    def _torn(raw: str) -> dict[str, Any]:
        """What a torn line still names: the cell and seed if written, else nothing.

        Its ``event`` is ``None`` when the line was torn before it: a start or a return.
        """
        cell = re.search(r'"cell": "((?:[^"\\]|\\.)*)"', raw)
        rep = re.search(r'"replicate": (\d+)', raw)
        event = re.search(r'"event": "(start|returned)"', raw)
        attempt = re.search(r'"attempt": (\d+)', raw)
        run_id = re.search(r'"run_id": "([^"]*)"', raw)
        key = (cell.group(1), int(rep.group(1))) if cell and rep else InFlight.TORN
        return {"cell": key[0], "replicate": key[1],
                "event": event.group(1) if event else None,
                "attempt": int(attempt.group(1)) if attempt else None,
                "run_id": run_id.group(1) if run_id else None, "torn": raw}  # fmt: skip

    def orphans(self, settled: set[tuple[str, int]]) -> dict[tuple[str, int], list[dict]]:
        """Each unsettled cell's journalled attempts, as unfinished records, oldest first.

        ``settled`` holds the cells with a result or an unfinished record; any other cell
        in the journal was left by a stopped driver (or is running now). An attempt that
        returned keeps its own error; one that never returned is ``driver_stopped``. A torn
        line is an in-flight attempt: of its cell if it names one, else under
        :data:`TORN`, which a driver must stop on (N-2).
        """
        by_cell: dict[tuple[str, int], dict[int, dict]] = {}
        returned: dict[tuple[str, int], set[int]] = {}
        for path in self.paths:
            if not path.is_file():
                continue
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                try:
                    x = json.loads(raw)
                    key = (str(x["cell"]), int(x["replicate"]))
                except (ValueError, KeyError, TypeError):
                    x = self._torn(raw)
                    key = (x["cell"], x["replicate"])
                if key in settled:
                    continue
                attempts = by_cell.setdefault(key, {})
                done = returned.setdefault(key, set())
                n = x.get("attempt")
                latest = max(attempts, default=0)
                if n is None and "torn" in x and latest and latest not in done \
                        and x.get("event") != "start":  # fmt: skip
                    # a cell's attempts are sequential: a line after a start that has not
                    # returned is that attempt's return line, torn, not a new attempt (B4,
                    # N-b); the attempt stays one that never returned
                    continue
                n = int(n) if n is not None else latest + 1
                if x.get("event") == "returned":
                    done.add(n)
                    if "torn" in x:  # a torn return line: its completion is unknown
                        continue
                    if n in attempts and not attempts[n]["summary"]["completed"]:
                        attempts[n]["summary"].update(
                            {"error": x.get("error") or self.STOPPED,
                             "failure_reason": x.get("failure_reason") or "run_failed"}
                            if not x.get("completed") else
                            {"error": f"{self.STOPPED} (the run returned completed)"})  # fmt: skip
                    continue
                attempts[n] = {
                    "cell": key[0], "replicate": key[1], "attempt": n,
                    "run_id": x.get("run_id"), "outcome": "pending", "rule": None,
                    "summary": {"completed": False, "error": self.STOPPED,
                                "failure_reason": "driver_stopped"},
                }  # fmt: skip
                if "torn" in x:
                    attempts[n]["summary"]["error"] = f"{self.STOPPED} (a torn journal line)"
        return {k: [v[n] for n in sorted(v)] for k, v in by_cell.items() if v}


def stopped(orphans: dict[tuple[str, int], list[dict]]) -> list[dict[str, Any]]:
    """The report's entries for a journal's orphans: unfinished, stopped or still running.

    Every report adds these to its unfinished cells (the review of ``0b9f210``, SF-1), so a
    stopped cell is listed whether or not a driver has started since.
    """
    return [
        {"cell": cell, "replicate": rep, "note": InFlight.STILL,
         **Attempted("driver_stopped", list(prior)).failure()}
        for (cell, rep), prior in sorted(orphans.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    ]  # fmt: skip


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
