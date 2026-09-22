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

**The workflow-visible projection carries no wall-clock.** A :class:`CallLog` opened with
``projection=True`` writes its records without ``t_utc`` and without ``runtime_s`` (final
review at ``99a8947``, findings F1 and F3, 2026-09-10). The timestamp of a generation call
is the cell's position in the generation order, and the generation order was a function of
the public library and a committed seed, so a workflow that sorted the run set by any
visible timestamp recovered every cell's rung; and the runtime of the burn-in alone marked
the one two-zone row (0.55 s against 1.53 s at 40 d). The truth-side log keeps both — rule 3
wants a runtime, and the evaluator reads that log — and the visible one keeps the sequence,
the name, the version, the hash and the outcome.

**Hashing.** :func:`args_hash` canonicalises a mapping to sorted-key JSON with numpy
arrays reduced to ``(shape, dtype, sha256 of the bytes)``, so the same arguments always
give the same hash on the same platform and different arguments practically never
collide. It is a fingerprint, not a serialisation: the arguments cannot be recovered from
it, which is also why logging it leaks no hidden truth.

Nothing here reads or writes ``truth_store/<id>/``.
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
    t_utc: str | None
    """ISO-8601 UTC timestamp of the moment the call returned; ``None`` in a projection."""
    name: str
    """Tool name, e.g. ``sim.simulate_extended`` or ``bayes_mcmc``."""
    version: str
    """Version string of the tool, so a re-run with a changed tool is visible."""
    args_hash: str
    runtime_s: float | None
    """Wall-clock seconds the call took; ``None`` in a projection."""
    outcome: Outcome
    detail: str = ""
    """Free text: an error message, a solver message, or a note. Never an argument value."""
    n_evaluations: int | None = None
    """Simulator evaluations the call was charged by the registry's meter; ``None`` in a
    projection and in the harness's own records. The evaluation suite's meter of §6.7 C
    (the evaluation session, 2026-09-22): rule 3 says evaluation reads logs only, and until
    this field no log carried a per-call count, so the cost of a run was the workflow's
    self-report copied from its task state."""
    assay_units: int | None = None
    """Assay units the call spent at the catalogue price; ``None`` in a projection."""

    def to_json(self) -> str:
        """The record as one JSON line (no trailing newline).

        A projection record has no ``t_utc``, no ``runtime_s``, no ``n_evaluations`` and no
        ``assay_units`` key at all, rather than a null: the key's absence is the statement.
        """
        payload: dict[str, Any] = {"seq": self.seq}
        if self.t_utc is not None:
            payload["t_utc"] = self.t_utc
        payload.update(name=self.name, version=self.version, args_hash=self.args_hash)
        if self.runtime_s is not None:
            payload["runtime_s"] = round(self.runtime_s, 6)
        payload.update(outcome=self.outcome, detail=self.detail)
        if self.n_evaluations is not None:
            payload["n_evaluations"] = int(self.n_evaluations)
        if self.assay_units is not None:
            payload["assay_units"] = int(self.assay_units)
        return json.dumps(payload, separators=(",", ":"))

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
            t_utc=None if raw.get("t_utc") is None else str(raw["t_utc"]),
            name=str(raw["name"]),
            version=str(raw["version"]),
            args_hash=str(raw["args_hash"]),
            runtime_s=None if raw.get("runtime_s") is None else float(raw["runtime_s"]),
            outcome=raw["outcome"],
            detail=str(raw.get("detail", "")),
            n_evaluations=None if raw.get("n_evaluations") is None else int(raw["n_evaluations"]),
            assay_units=None if raw.get("assay_units") is None else int(raw["assay_units"]),
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

    def __init__(
        self, run_dir: str | Path, *, fresh: bool = False, projection: bool = False
    ) -> None:
        """Open (or create) the call log of a run directory.

        Args:
            run_dir: The directory the log lives in.
            fresh: Start the file over. The harness passes this at the start of a
                generation, because a generated cell's log is the record of *that*
                generation: before 2026-09-10 a regenerated cell appended to its previous
                log, so one cell generated twice carried ``seq`` 0..9 while its index line
                was de-duplicated (review finding, no ruling needed). A later writer --
                the tool registry appending a workflow's calls -- leaves this ``False``
                and continues the sequence, which is the behaviour the docstring above
                promises.
            projection: Write records without a timestamp or a runtime (the
                workflow-visible log; see the module docstring). The truth-side log and a
                workflow's own later calls carry both.
        """
        self.path = Path(run_dir) / self.FILENAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.projection = projection
        if fresh and self.path.exists():
            self.path.unlink()
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
        *,
        n_evaluations: int | None = None,
        assay_units: int | None = None,
    ) -> CallRecord:
        """Write one record and return it.

        The line is flushed before returning, so a run killed mid-scenario still has
        every call that completed. The two meter counts are kept only by a full log; a
        projection drops them as it drops the timestamp and the runtime.
        """
        record = CallRecord(
            seq=self._seq,
            t_utc=None if self.projection else datetime.now(UTC).isoformat(timespec="milliseconds"),
            name=name,
            version=version,
            args_hash=args_hash(args),
            runtime_s=None if self.projection else float(runtime_s),
            outcome=outcome,
            detail=detail,
            n_evaluations=None if self.projection or n_evaluations is None else int(n_evaluations),
            assay_units=None if self.projection or assay_units is None else int(assay_units),
        )
        return self._write(record)

    def copy(self, record: CallRecord) -> CallRecord:
        """Append a record written elsewhere, under this file's next sequence number.

        The tiers of one cell share one integration of the truth (§6.4), so the calls that
        produced it are written into every tier's log rather than only the first's (final
        review, finding F4, 2026-09-10): the evaluator reads logs only, and a log that
        showed no integration for two of three tiers was not the record it claimed to be.
        A projection drops the copied record's timestamp and runtime as it drops its own.
        """
        copied = CallRecord(
            seq=self._seq,
            t_utc=None if self.projection else record.t_utc,
            name=record.name,
            version=record.version,
            args_hash=record.args_hash,
            runtime_s=None if self.projection else record.runtime_s,
            outcome=record.outcome,
            detail=record.detail,
            n_evaluations=None if self.projection else record.n_evaluations,
            assay_units=None if self.projection else record.assay_units,
        )
        return self._write(copied)

    def _write(self, record: CallRecord) -> CallRecord:
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
