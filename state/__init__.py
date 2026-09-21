"""Shared task-state schema, provenance logger and the workflow-facing run view (§6.6).

One JSON schema is shared by all workflows; memory is this state plus the tool-call
log. Free-text summaries may not replace structured results.

* :mod:`state.provenance` — the append-only ``runs/<id>/calls.jsonl`` every tool call is
  logged to (CLAUDE.md rule 3), shared by the run harness and the tool registry.
* :mod:`state.run_view` — the only way a workflow reaches a run: observations and the
  redacted manifest, with hidden truth not merely refused but unnameable (rule 1).
* :mod:`state.task_state` — the shared task-state schema a workflow's ``state.json`` is
  validated against on the privileged side.
"""

from state.provenance import CallLog, CallRecord, args_hash, read_calls
from state.run_view import RunView, TruthAccessError, open_run
from state.task_state import TaskState

__all__ = [
    "CallLog",
    "CallRecord",
    "RunView",
    "TaskState",
    "TruthAccessError",
    "args_hash",
    "open_run",
    "read_calls",
]
