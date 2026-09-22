"""Following a claim back to the log (rule 3): actions, sequence numbers, log lines.

A task state names each call it made the way the visible log does (``ActionRef``: the
line's ``seq`` and ``args_hash``), and an evidence item names the actions it rests on by
``call_index``. A claim is *supported* when that chain closes on a logged line with the
same name and hash and outcome ``ok``; every family reads the chain through these helpers
rather than trusting the state's own numbers.
"""

from __future__ import annotations

from collections.abc import Iterable

from eval.records import RunRecords
from state.provenance import CallRecord
from state.task_state import ActionRef, TaskState

__all__ = ["logged_ok_calls", "resolve_action", "resolve_call_index", "workflow_records"]


def resolve_action(action: ActionRef, visible: tuple[CallRecord, ...]) -> CallRecord | None:
    """The visible log line an action names, if the line agrees with it, else ``None``.

    The line must exist at ``seq``, carry the same tool name and argument hash, and have
    the outcome the action claims. A mismatch on any of them is an action that does not
    describe a logged call.
    """
    if action.seq is None or action.seq < 0 or action.seq >= len(visible):
        return None
    line = visible[action.seq]
    if line.seq != action.seq:  # a log whose positions and numbers disagree is not a record
        return None
    if line.name != action.name or line.args_hash != action.args_hash:
        return None
    if line.outcome != action.outcome:
        return None
    return line


def resolve_call_index(
    call_index: int, state: TaskState, visible: tuple[CallRecord, ...]
) -> CallRecord | None:
    """The logged line behind ``call_index`` (an evidence item's reference), or ``None``."""
    action = next((a for a in state.actions if a.call_index == call_index), None)
    if action is None:
        return None
    return resolve_action(action, visible)


def logged_ok_calls(
    name: str, state: TaskState, visible: tuple[CallRecord, ...]
) -> list[CallRecord]:
    """Every action of tool ``name`` that resolves to a logged ``ok`` line."""
    out = []
    for action in state.actions:
        if action.name != name:
            continue
        line = resolve_action(action, visible)
        if line is not None and line.outcome == "ok":
            out.append(line)
    return out


def workflow_records(records: RunRecords, clock_record: str) -> list[CallRecord]:
    """The truth-side records of the workflow's own calls: everything after the clock start.

    The harness's generation calls precede ``registry.open``; when the workflow was run
    more than once on the same run, the last opening is the one scored.
    """
    calls = records.truth_calls
    opened = [i for i, r in enumerate(calls) if r.name == clock_record]
    if not opened:
        return []
    return list(calls[opened[-1] + 1 :])


def clock_start(records: RunRecords, clock_record: str) -> CallRecord | None:
    """The last ``registry.open`` record of the truth-side log, or ``None``."""
    opened = [r for r in records.truth_calls if r.name == clock_record]
    return opened[-1] if opened else None


def names_of(lines: Iterable[CallRecord]) -> set[str]:
    """Tool names of a set of log lines."""
    return {line.name for line in lines}
