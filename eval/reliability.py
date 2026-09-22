"""Family D: workflow reliability (proposal §6.7 D).

Completion is the runner's verdict (``summary.json``: the state says it reached its last
step *and* the process exited 0); a run the runner never launched, or that wrote no
state, is not completed and stays in the denominator. The counts are read from the
truth-side log of the workflow's own calls: invalid-action attempts (arguments that did
not validate, refusals beyond the budget), tool-call errors (the tool raised), injected
failures (the Level-8 directive, which the visible log hides), verifier rejections (a
registry record name reserved for P2) and retries (a call repeated with the same name and
argument hash). Variance across seeds is an aggregate quantity (:mod:`eval.aggregate`).
"""

from __future__ import annotations

from typing import Any

from eval.config import EvalConfig
from eval.records import RunRecords
from eval.trail import workflow_records

__all__ = ["score_reliability"]


def score_reliability(records: RunRecords, cfg: EvalConfig) -> dict[str, Any]:
    """Family D for one run."""
    rel = cfg.reliability
    calls = workflow_records(records, cfg.efficiency.clock_record)
    summary = records.summary or {}
    invalid = 0
    errors = 0
    injected = 0
    budget_refusals = 0
    seen: set[tuple[str, str]] = set()
    retries = 0
    for r in calls:
        key = (r.name, r.args_hash)
        if key in seen:
            retries += 1
        seen.add(key)
        if r.outcome == "budget_exceeded":
            invalid += 1
            budget_refusals += 1
        elif r.outcome == "error":
            if any(r.detail.startswith(p) for p in rel.invalid_action_prefixes):
                invalid += 1
            else:
                errors += 1
        elif r.outcome == "injected_failure":
            injected += 1
    verifier = sum(1 for r in calls if r.name in set(rel.verifier_rejection_names))
    state = records.state
    return {
        "launched": records.launched,
        "completed": bool(summary.get("completed", False)),
        "state_valid": state is not None,
        "returncode": summary.get("returncode"),
        "runner_error": summary.get("error", "") if summary else "not launched",
        "invalid_actions": invalid,
        "budget_refusals": budget_refusals,
        "tool_errors": errors,
        "injected_failures": injected,
        "tool_failures_recorded": None if state is None else len(state.tool_failures),
        "verifier_rejections": verifier,
        "retries": retries,
        "fallbacks": None if state is None else len(state.plan.fallbacks),
        "guards_tripped": None if state is None else len(state.plan.guards_tripped),
        "steps_completed": None if state is None else len(state.plan.steps_completed),
        "problems": "; ".join(records.problems),
    }
