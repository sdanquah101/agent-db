"""Family C: information efficiency (proposal §6.7 C).

Every counter is read from the registry's records -- the truth-side log's per-call meter
counts (``n_evaluations``, ``assay_units``, ``runtime_s``, the ``registry.open`` clock
start) and the runner's ``summary.json``, whose cost fields the runner takes from the
same meter -- never from the workflow's task state. The state's own numbers are compared
with the meter and a disagreement is reported (``self_report_mismatch``), which is what
"evaluation reads logs only" (rule 3) has to hold against once a workflow could misreport.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eval.attribution import prior_interval
from eval.config import EvalConfig
from eval.records import RunRecords
from eval.trail import clock_start, workflow_records
from tools.config import FittedModelConfig

__all__ = ["score_efficiency"]


def _utc(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def score_efficiency(
    records: RunRecords, cfg: EvalConfig, model: FittedModelConfig
) -> dict[str, Any]:
    """Family C for one run."""
    eff = cfg.efficiency
    calls = workflow_records(records, eff.clock_record)
    opened = clock_start(records, eff.clock_record)
    evaluations = sum(int(r.n_evaluations or 0) for r in calls)
    assay_units = sum(int(r.assay_units or 0) for r in calls)
    tool_runtime = sum(float(r.runtime_s or 0.0) for r in calls)
    span: float | None = None
    if opened is not None and calls:
        t0, t1 = _utc(opened.t_utc), _utc(calls[-1].t_utc)
        if t0 is not None and t1 is not None:
            span = (t1 - t0).total_seconds()

    summary = records.summary or {}
    out: dict[str, Any] = {
        "simulator_evals": evaluations,
        "simulator_evals_budget": summary.get("simulator_evals_total"),
        "simulator_evals_fraction": None,
        "assay_units": assay_units,
        "assay_units_budget": summary.get("assay_units_total"),
        "wall_clock_s": summary.get("wall_s"),
        "wall_clock_budget_min": summary.get("wall_clock_min_total"),
        "wall_clock_fraction": None,
        "log_span_s": span,
        "tool_runtime_s": tool_runtime,
        "n_calls": len(calls),
        "tokens": summary.get("tokens_used"),
        "cost_source": summary.get("cost_source"),
        "meter_agrees_with_summary": None,
        "self_report_mismatch": None,
        "uncertainty_reduction": None,
        "uncertainty_reduction_per_assay_unit": None,
    }
    budget = out["simulator_evals_budget"]
    if budget:
        out["simulator_evals_fraction"] = evaluations / float(budget)
    allowance = out["wall_clock_budget_min"]
    if allowance and out["wall_clock_s"] is not None:
        out["wall_clock_fraction"] = float(out["wall_clock_s"]) / (60.0 * float(allowance))
    if summary:
        out["meter_agrees_with_summary"] = (
            summary.get("simulator_evals_used") == evaluations
            and summary.get("assay_units_used") == assay_units
        )
    state = records.state
    if state is not None:
        out["self_report_mismatch"] = (
            state.budget.simulator_evals_used != evaluations
            or state.budget.assay_units_used != assay_units
        )
        # uncertainty reduction against the declared prior, per parameter reported
        reductions = []
        for name, est in state.final.parameters.items():
            bounds = model.parameters.get(name)
            if bounds is None or est.lower is None or est.upper is None:
                continue
            lo, hi = prior_interval(bounds.lower, bounds.upper, cfg.attribution.prior_interval_mass)
            if hi <= lo:
                continue
            reductions.append(
                max(1.0 - (est.upper - est.lower) / (hi - lo), eff.uncertainty_reduction_clip)
            )
        if reductions:
            out["uncertainty_reduction"] = sum(reductions) / len(reductions)
            if assay_units > 0:
                out["uncertainty_reduction_per_assay_unit"] = (
                    out["uncertainty_reduction"] / assay_units
                )
    return out
