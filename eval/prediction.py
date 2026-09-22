"""Family A: calibration and prediction quality (proposal §6.7 A).

- **Forecast-window errors** (MAE, RMSE, normalised RMSE, bias) per scored channel, the
  interval coverage at the configured levels, the interval score at the configured alpha
  and the CRPS, all from the state's ``validation`` block -- accepted only when (i) every
  call the block names resolves to a logged ``validate`` line with outcome ``ok`` and
  (ii) the block's hold-out window is the frozen one, ``[T (1 - f), T]`` of
  ``configs/eval.yaml``. Otherwise the metrics are ``None`` and ``forecast_verified``
  says why. The interval metrics carry their source (``final.interval_method``): a CRPS
  from a posterior predictive is reported as ``crps_posterior``, one from any other
  ensemble as ``crps`` only.
- **Mass/charge-balance error** from the state's ``mass_balance`` block, accepted when a
  logged ``mass_balance`` line with outcome ``ok`` exists among the actions.
- **Parameter recovery** -- absolute and relative error of the reported multipliers
  against the truth's, and whether the reported interval covers the truth -- for the
  configured levels only. A Level-6 (or higher) cell is never scored on it
  (``recovery_scored`` is ``False`` and every recovery field ``None``), whatever the state
  reports.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from eval.config import EvalConfig
from eval.records import RunRecords
from eval.trail import logged_ok_calls, resolve_call_index

__all__ = ["frozen_holdout", "score_prediction", "truth_multipliers"]


def frozen_holdout(duration_days: float, holdout_fraction: float) -> tuple[float, float]:
    """The frozen hold-out window ``[T (1 - f), T]``."""
    return duration_days * (1.0 - holdout_fraction), duration_days


def truth_multipliers(
    truth_parameters: Mapping[str, Any], defaults: Mapping[str, float], segment: str
) -> dict[str, float]:
    """The truth's parameters of one segment as multipliers of the model's defaults."""
    segments = truth_parameters.get("segments") or []
    if not segments:
        return {}
    chosen = segments[-1] if segment == "last" else segments[0]
    params = chosen.get("parameters", {})
    out: dict[str, float] = {}
    for group in ("kinetics", "stoichiometry", "physchem"):
        for name, value in (params.get(group) or {}).items():
            base = defaults.get(name)
            if base is not None and float(base) != 0.0:
                out[name] = float(value) / float(base)
    return out


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def score_prediction(
    records: RunRecords, cfg: EvalConfig, defaults: Mapping[str, float]
) -> dict[str, Any]:
    """Family A for one run."""
    pred = cfg.prediction
    out: dict[str, Any] = {
        "forecast_verified": False,
        "forecast_reason": "no state",
        "forecast_window": None,
        "interval_source": None,
        "ensemble": None,
        "constraint_violations": None,
        "balance_verified": False,
        "cod_closure_mean": None,
        "cod_balance_error": None,
        "n_cod_inadmissible": None,
        "charge_drift": None,
        "charge_consistent": None,
        "recovery_scored": records.level in set(pred.recovery_levels),
        "recovery_n": None,
        "recovery_mean_abs_error": None,
        "recovery_mean_rel_error": None,
        "recovery_coverage": None,
        "recovery_at_bound": None,
        "recovery_detail": None,
    }
    score_key = f"{round((1.0 - pred.interval_score_alpha) * 100)}"
    for ch in pred.channels:
        for m in ("mae", "rmse", "nrmse", "bias"):
            out[f"{ch}_{m}"] = None
        for level in pred.coverage_levels:
            out[f"{ch}_coverage_{level}"] = None
        out[f"{ch}_interval_score_{score_key}"] = None
        out[f"{ch}_crps"] = None
        out[f"{ch}_crps_posterior"] = None

    state = records.state
    if state is None:
        out["recovery_scored"] = False
        return out

    # -- the forecast window ----------------------------------------------------------
    window = frozen_holdout(records.duration_days, cfg.windows.holdout_fraction)
    out["forecast_window"] = f"[{window[0]:g}, {window[1]:g}]"
    validation = state.validation
    if validation is None:
        out["forecast_reason"] = "the state carries no validation block"
    else:
        declared = validation.holdout
        same_window = all(
            abs(float(a) - float(b)) <= cfg.windows.tolerance_d
            for a, b in zip(declared, window, strict=True)
        )
        lines = [resolve_call_index(i, state, records.visible_calls) for i in validation.calls]
        resolved = bool(lines) and all(
            line is not None and line.name == pred.validate_tool and line.outcome == "ok"
            for line in lines
        )
        if not same_window:
            out["forecast_reason"] = (
                f"the validation window {list(declared)} is not the frozen "
                f"[{window[0]:g}, {window[1]:g}]"
            )
        elif not resolved:
            out["forecast_reason"] = (
                f"the validation block names no logged ok {pred.validate_tool!r} call"
            )
        else:
            out["forecast_verified"] = True
            out["forecast_reason"] = ""
            out["interval_source"] = state.final.interval_method
            out["ensemble"] = bool(validation.ensemble)
            out["constraint_violations"] = int(validation.constraint_violations)
            posterior = state.final.interval_method == "posterior"
            for ch in pred.channels:
                metrics = validation.metrics.get(ch)
                if not metrics:
                    continue
                for m in ("mae", "rmse", "nrmse", "bias"):
                    out[f"{ch}_{m}"] = _f(metrics.get(m))
                if validation.ensemble:
                    for level in pred.coverage_levels:
                        out[f"{ch}_coverage_{level}"] = _f(metrics.get(f"coverage_{level}"))
                    out[f"{ch}_interval_score_{score_key}"] = _f(
                        metrics.get(f"interval_score_{score_key}")
                    )
                    out[f"{ch}_crps"] = _f(metrics.get("crps"))
                    if posterior:
                        out[f"{ch}_crps_posterior"] = out[f"{ch}_crps"]

    # -- the balance -----------------------------------------------------------------
    balance = state.mass_balance
    if balance and logged_ok_calls(pred.balance_tool, state, records.visible_calls):
        out["balance_verified"] = True
        closure = _f(balance.get("cod_closure_mean"))
        out["cod_closure_mean"] = closure
        out["cod_balance_error"] = None if closure is None else abs(closure)
        n_bad = balance.get("n_cod_inadmissible")
        out["n_cod_inadmissible"] = None if n_bad is None else int(n_bad)
        out["charge_drift"] = _f(balance.get("charge_drift"))
        consistent = balance.get("charge_consistent")
        out["charge_consistent"] = None if consistent is None else bool(consistent)

    # -- parameter recovery, Levels 0-5 only ---------------------------------------
    if not out["recovery_scored"]:
        return out
    truth = truth_multipliers(records.truth_parameters, defaults, pred.truth_segment)
    abs_errors, rel_errors, covered, at_bound, detail = [], [], [], [], []
    for name, est in state.final.parameters.items():
        if name not in truth:
            continue
        true = truth[name]
        abs_errors.append(abs(est.estimate - true))
        rel_errors.append(abs(est.estimate - true) / abs(true) if true != 0.0 else math.nan)
        inside = est.lower is not None and est.upper is not None and est.lower <= true <= est.upper
        covered.append(inside)
        at_bound.append(bool(est.at_bound))
        detail.append(f"{name}:{est.estimate:.3f}/{true:.3f}/{'in' if inside else 'out'}")
    n = len(abs_errors)
    out["recovery_n"] = n
    if n:
        out["recovery_mean_abs_error"] = sum(abs_errors) / n
        finite = [r for r in rel_errors if math.isfinite(r)]
        out["recovery_mean_rel_error"] = sum(finite) / len(finite) if finite else None
        out["recovery_coverage"] = sum(covered) / n
        out["recovery_at_bound"] = sum(at_bound) / n
        out["recovery_detail"] = " ".join(detail)
    return out
