"""validate: hold-out forecast metrics, coverage, interval score, CRPS, constraints (§6.7 A).

The verifier's tool. A prediction is either a point series or a predictive ensemble
``(n_samples, n_t)``; the ensemble metrics (coverage at the configured levels, the
interval score of Gneiting & Raftery 2007, the CRPS as the energy form
``E|X - y| - 0.5 E|X - X'|``) are reported only for an ensemble. Constraint violations
count predicted points outside the admissible range of the output
(``configs/tools/validate.yaml``); a negative concentration or a pH of 15 is a violation
whatever its error. Costs no simulator evaluation.
"""

from __future__ import annotations

import numpy as np

from tools.registry import ToolArgumentError, ToolContext
from tools.schemas import ValidateInput, ValidateOutput
from tools.schemas.tools import OutputMetrics

__all__ = ["crps_ensemble", "interval_score", "run_validate", "validate_cost"]


def validate_cost(inp: ValidateInput, ctx: ToolContext) -> int:
    """No simulator evaluation."""
    return 0


def interval_score(lower: np.ndarray, upper: np.ndarray, y: np.ndarray, alpha: float) -> float:
    """Mean interval score of central ``(1 - alpha)`` intervals (Gneiting & Raftery 2007)."""
    width = upper - lower
    below = np.maximum(lower - y, 0.0)
    above = np.maximum(y - upper, 0.0)
    return float(np.mean(width + 2.0 / alpha * below + 2.0 / alpha * above))


def crps_ensemble(samples: np.ndarray, y: np.ndarray) -> float:
    """Mean CRPS of an ensemble ``(n_samples, n_t)`` against observations ``(n_t,)``."""
    n = samples.shape[0]
    term1 = np.mean(np.abs(samples - y[None, :]), axis=0)
    # E|X - X'| over all pairs, per time point
    sorted_s = np.sort(samples, axis=0)
    ranks = np.arange(1, n + 1)[:, None]
    term2 = 2.0 * np.sum((2 * ranks - n - 1) * sorted_s, axis=0) / (n * n)
    return float(np.mean(term1 - 0.5 * term2))


def run_validate(inp: ValidateInput, ctx: ToolContext) -> ValidateOutput:
    """Score predictions against every observed series."""
    conf = ctx.configs.validate
    t_pred = np.asarray(inp.t, dtype=float)
    results = []
    ensemble = False
    n_total = 0
    for series in inp.observed:
        if series.output not in inp.predicted:
            raise ToolArgumentError(f"no prediction given for observed output {series.output!r}")
        pred = np.asarray(inp.predicted[series.output], dtype=float)
        if pred.ndim == 1:
            if pred.shape != t_pred.shape:
                raise ToolArgumentError(f"prediction of {series.output!r} does not match t")
            pred = pred[None, :]
        elif pred.ndim != 2 or pred.shape[1] != t_pred.size:
            raise ToolArgumentError(
                f"prediction of {series.output!r} must be (n_t,) or (n_samples, n_t)"
            )
        is_ensemble = pred.shape[0] > 1
        ensemble = ensemble or is_ensemble

        obs = series.observed
        t_obs, y = series.t[obs], series.value[obs]
        if inp.holdout is not None:
            inside = (t_obs >= inp.holdout.start) & (t_obs <= inp.holdout.end)
            t_obs, y = t_obs[inside], y[inside]
        if t_obs.size == 0:
            raise ToolArgumentError(
                f"no observed sample of {series.output!r} in the hold-out window"
            )
        at_obs = np.stack([np.interp(t_obs, t_pred, row) for row in pred])  # (n_samples, n)
        point = at_obs.mean(axis=0) if is_ensemble else at_obs[0]
        err = point - y
        sd_obs = float(np.std(y, ddof=1)) if y.size > 1 else np.nan
        rmse = float(np.sqrt(np.mean(err**2)))

        coverage: dict[str, float | None] = {}
        scores: dict[str, float | None] = {}
        crps = None
        if is_ensemble:
            for level in conf.coverage_levels:
                alpha = 1.0 - level
                lo = np.quantile(at_obs, alpha / 2, axis=0)
                hi = np.quantile(at_obs, 1 - alpha / 2, axis=0)
                key = f"{round(level * 100)}"
                coverage[key] = float(np.mean((y >= lo) & (y <= hi)))
                scores[key] = interval_score(lo, hi, y, alpha)
            crps = crps_ensemble(at_obs, y)
        else:
            for level in conf.coverage_levels:
                key = f"{round(level * 100)}"
                coverage[key] = None
                scores[key] = None

        constraint = conf.constraints.get(series.output)
        violations = 0
        if constraint is not None:
            if constraint.lower is not None:
                violations += int(np.sum(at_obs < constraint.lower))
            if constraint.upper is not None:
                violations += int(np.sum(at_obs > constraint.upper))

        n_total += int(y.size)
        results.append(
            OutputMetrics(
                output=series.output,
                n=int(y.size),
                mae=float(np.mean(np.abs(err))),
                rmse=rmse,
                nrmse=float(rmse / sd_obs) if np.isfinite(sd_obs) and sd_obs > 0 else float("nan"),
                bias=float(np.mean(err)),
                coverage=coverage,
                interval_score=scores,
                crps=crps,
                constraint_violations=violations,
            )
        )
    return ValidateOutput(results=tuple(results), n_total=n_total, ensemble=ensemble)
