"""The provenance log: one line per tool call in ``runs/<id>/calls.jsonl`` (CLAUDE.md rule 3).

"Every tool call is logged (name, version, args hash, runtime, outcome) to
``runs/<id>/calls.jsonl``. Evaluation reads logs only."

The file is **append-only JSON Lines**, which is the whole design: the run harness writes
its own simulator calls here while it builds a run, and the tool registry (a later
milestone) appends a workflow's calls to the *same* file without having to know what is
already in it. Nothing rewrites a line, so a partially written run still parses up to its
last complete record, and two writers that open the file in sequence cannot corrupt each
other's entries.

**What a line is.** :class:`CallRecord` — sequence number, UTC timestamp, tool name and
version, a hash of the arguments, the runtime in seconds, an outcome, and an optional
detail string. Arguments themselves are *not* logged: they can be whole trajectories, and
a benchmark that stored them would make ``calls.jsonl`` the size of the run. The hash is
enough to tell two calls apart and to spot a repeat, which is what the metrics of §6.7 C
need.

**Hashing.** :func:`args_hash` canonicalises a mapping to sorted-key JSON with numpy
arrays reduced to ``(shape, dtype, sha256 of the bytes)``, so the same arguments always
give the same hash on the same platform and different arguments practically never
collide. It is a fingerprint, not a serialisation: the arguments cannot be recovered from
it, which is also why logging it leaks no hidden truth.

Nothing here reads or writes ``runs/<id>/truth/``.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

import numpy as np

__all__ = ["CallLog", "CallRecord", "Outcome", "args_hash", "read_calls"]

Outcome = Literal["ok", "error", "budget_exceeded", "injected_failure"]
"""How a call ended. ``injected_failure`` is the Level-8 ``tool_failure`` fault, which is
distinguished from a genuine ``error`` so that §6.7 D can count real tool errors."""


def _canonical(value: Any) -> Any:
    """A JSON-safe, order-stable rendering of one argument value."""
    if isinstance(value, np.ndarray):
        return {
            "__ndarray__": {
                "shape": list(value.shape),
                "dtype": str(value.dtype),
                "sha256": hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest(),
            }
        }
    if isinstance(value, np.generic):
        return _canonical(value.item())
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, str | bytes):
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    if isinstance(value, list | tuple | set | frozenset):
        items = sorted(value, key=repr) if isinstance(value, set | frozenset) else value
        return [_canonical(v) for v in items]
    if isinstance(value, float | int | bool) or value is None:
        return value
    return repr(value)


def args_hash(args: Mapping[str, Any]) -> str:
    """A 16-hex-character fingerprint of a call's arguments.

    Deterministic in the argument *values*, not in the order they were passed. Numpy
    arrays contribute their shape, dtype and a hash of their bytes rather than their
    contents, so hashing a 30 x 365 trajectory costs microseconds.

    Args:
        args: The call's keyword arguments.

    Returns:
        The first 16 hex characters of the SHA-256 of the canonical form.
    """
    blob = json.dumps(_canonical(dict(args)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class CallRecord:
    """One logged call. The unit of ``calls.jsonl`` and the unit evaluation reads."""

    seq: int
    """Position in the file, from 0. Continues across writers appending to one run."""
    t_utc: str
    """ISO-8601 UTC timestamp of the moment the call returned."""
    name: str
    """Tool name, e.g. ``sim.simulate_extended`` or ``bayes_mcmc``."""
    version: str
    """Version string of the tool, so a re-run with a changed tool is visible."""
    args_hash: str
    runtime_s: float
    outcome: Outcome
    detail: str = ""
    """Free text: an error message, a solver message, or a note. Never an argument value."""

    def to_json(self) -> str:
        """The record as one JSON line (no trailing newline)."""
        return json.dumps(
            {
                "seq": self.seq,
                "t_utc": self.t_utc,
                "name": self.name,
                "version": self.version,
                "args_hash": self.args_hash,
                "runtime_s": round(self.runtime_s, 6),
                "outcome": self.outcome,
                "detail": self.detail,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, line: str) -> Self:
        """Parse one line of ``calls.jsonl``.

        Raises:
            ValueError: If the line is not a JSON object with the record's fields.
        """
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"call record must be a JSON object, got {type(raw).__name__}")
        return cls(
            seq=int(raw["seq"]),
            t_utc=str(raw["t_utc"]),
            name=str(raw["name"]),
            version=str(raw["version"]),
            args_hash=str(raw["args_hash"]),
            runtime_s=float(raw["runtime_s"]),
            outcome=raw["outcome"],
            detail=str(raw.get("detail", "")),
        )


class CallLog:
    """Append-only writer for one run's ``calls.jsonl``.

    Opened on the run directory, not on the file, so every writer agrees on the name. The
    sequence number continues from whatever is already in the file, which is what lets the
    harness write its simulator calls now and the tool registry append a workflow's calls
    to the same run later.

    Example:
        >>> log = CallLog(run_dir)                       # doctest: +SKIP
        >>> with log.record("sim.simulate_extended", "1.0", {"days": 180}) as call:
        ...     result = simulate(...)                   # doctest: +SKIP
        ...     call.detail = result.message
    """

    FILENAME = "calls.jsonl"

    def __init__(self, run_dir: str | Path) -> None:
        """Open (or create) the call log of a run directory."""
        self.path = Path(run_dir) / self.FILENAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = sum(1 for _ in self.path.open(encoding="utf-8")) if self.path.exists() else 0

    @property
    def n_calls(self) -> int:
        """Number of records written to this file so far, by any writer."""
        return self._seq

    def append(
        self,
        name: str,
        version: str,
        args: Mapping[str, Any],
        runtime_s: float,
        outcome: Outcome,
        detail: str = "",
    ) -> CallRecord:
        """Write one record and return it.

        The line is flushed before returning, so a run killed mid-scenario still has
        every call that completed.
        """
        record = CallRecord(
            seq=self._seq,
            t_utc=datetime.now(UTC).isoformat(timespec="milliseconds"),
            name=name,
            version=version,
            args_hash=args_hash(args),
            runtime_s=float(runtime_s),
            outcome=outcome,
            detail=detail,
        )
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")
        self._seq += 1
        return record

    @contextmanager
    def record(self, name: str, version: str, args: Mapping[str, Any]) -> Iterator[_PendingCall]:
        """Time a call and log it, whether it returns or raises.

        The yielded object carries a writable ``detail`` and ``outcome``; an exception
        inside the block is logged as ``error`` with its message and then re-raised, so a
        failure is never absent from the log.

        Yields:
            The pending call, for setting ``detail`` and ``outcome``.
        """
        pending = _PendingCall()
        started = time.perf_counter()
        try:
            yield pending
        except Exception as exc:
            self.append(
                name,
                version,
                args,
                time.perf_counter() - started,
                "error",
                f"{type(exc).__name__}: {exc}",
            )
            raise
        self.append(
            name, version, args, time.perf_counter() - started, pending.outcome, pending.detail
        )


@dataclass
class _PendingCall:
    """Mutable handle a :meth:`CallLog.record` block writes its outcome into."""

    outcome: Outcome = "ok"
    detail: str = ""


def read_calls(run_dir: str | Path) -> list[CallRecord]:
    """Every record of a run's call log, in file order.

    Raises:
        FileNotFoundError: If the run has no call log.
    """
    path = Path(run_dir) / CallLog.FILENAME
    with path.open(encoding="utf-8") as fh:
        return [CallRecord.from_json(line) for line in fh if line.strip()]
