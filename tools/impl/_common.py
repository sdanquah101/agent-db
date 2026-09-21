"""Helpers shared by the tool implementations: ceilings, bounds, residuals, starts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.stats import qmc

from tools.models import MeteredModel
from tools.registry import ToolArgumentError
from tools.schemas import ObservedSeries

__all__ = [
    "FitProblem",
    "ceiling",
    "fit_problem",
    "latin_hypercube",
    "resolve_bounds",
]


def ceiling(value: int | None, limit: int, name: str) -> int:
    """A workflow-supplied count, defaulted to and capped at the config's ceiling.

    Raises:
        ToolArgumentError: If the value exceeds the ceiling.
    """
    if value is None:
        return int(limit)
    if value > limit:
        raise ToolArgumentError(f"{name}={value} exceeds the configured ceiling {limit}")
    return int(value)


def resolve_bounds(
    model: MeteredModel,
    parameters: Sequence[str],
    bounds: Mapping[str, tuple[float, float]] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(idx, lower, upper)`` of the named parameters, tightened by ``bounds``.

    Raises:
        ToolArgumentError: On an unknown parameter, a duplicate, or bounds outside the
            model's own.
    """
    if len(set(parameters)) != len(parameters):
        raise ToolArgumentError(f"duplicate parameter names in {list(parameters)}")
    idx = model.index(parameters)
    lower = model.lower[idx].copy()
    upper = model.upper[idx].copy()
    for name, (lo, hi) in (bounds or {}).items():
        if name not in parameters:
            raise ToolArgumentError(f"bounds given for {name!r}, which is not being fitted")
        j = list(parameters).index(name)
        if lo >= hi:
            raise ToolArgumentError(f"bounds of {name!r} must satisfy lower < upper")
        if lo < lower[j] - 1e-12 or hi > upper[j] + 1e-12:
            raise ToolArgumentError(
                f"bounds of {name!r} ({lo}, {hi}) lie outside the model's "
                f"({lower[j]}, {upper[j]}); a workflow may tighten bounds, not widen them"
            )
        lower[j], upper[j] = float(lo), float(hi)
    return idx, lower, upper


def latin_hypercube(n: int, lower: np.ndarray, upper: np.ndarray, seed: int) -> np.ndarray:
    """``(n, k)`` Latin-hypercube points in the box, seeded (rule 4)."""
    k = lower.size
    sampler = qmc.LatinHypercube(d=k, seed=np.random.default_rng(seed))
    unit = sampler.random(n)
    return qmc.scale(unit, lower, upper)


@dataclass
class FitProblem:
    """A weighted least-squares problem: free parameters against observed series."""

    model: MeteredModel
    parameters: tuple[str, ...]
    idx: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    theta_full: np.ndarray
    """The full parameter vector; free entries are overwritten at each evaluation."""
    data: tuple[ObservedSeries, ...]
    n_data: int

    def full(self, x: np.ndarray) -> np.ndarray:
        """The full parameter vector with the free parameters set to ``x``."""
        theta = self.theta_full.copy()
        theta[self.idx] = np.asarray(x, dtype=float)
        return theta

    def predict(self, x: np.ndarray) -> dict[str, np.ndarray]:
        """The model's outputs at ``x`` (one charged evaluation)."""
        return self.model.evaluate(self.full(x))

    def residuals_of(self, outputs: Mapping[str, np.ndarray]) -> np.ndarray:
        """Weighted residuals ``(observed - predicted) / sd`` over every series, concatenated."""
        parts = []
        t_model = self.model.t
        for series in self.data:
            obs = series.observed
            pred = np.interp(series.t[obs], t_model, outputs[series.output])
            parts.append((series.value[obs] - pred) / series.sd_per_point[obs])
        return np.concatenate(parts) if parts else np.zeros(0)

    def residuals(self, x: np.ndarray) -> np.ndarray:
        """Weighted residuals at ``x`` (one charged evaluation)."""
        return self.residuals_of(self.predict(x))

    def chi2(self, x: np.ndarray) -> float:
        """Weighted sum of squared residuals at ``x`` (one charged evaluation)."""
        r = self.residuals(x)
        return float(np.dot(r, r))

    def jacobian(self, x: np.ndarray, relative_step: float, abs_step: float) -> np.ndarray:
        """Central-difference Jacobian of the residuals, ``(n_data, k)`` (2k evaluations)."""
        x = np.asarray(x, dtype=float)
        k = x.size
        cols = []
        for j in range(k):
            h = max(relative_step * abs(x[j]), abs_step)
            xp, xm = x.copy(), x.copy()
            xp[j] = min(x[j] + h, self.upper[j])
            xm[j] = max(x[j] - h, self.lower[j])
            span = xp[j] - xm[j]
            if span <= 0.0:
                raise ToolArgumentError(f"parameter {self.parameters[j]!r} has zero-width bounds")
            cols.append((self.residuals(xp) - self.residuals(xm)) / span)
        return np.stack(cols, axis=1)


def fit_problem(
    model: MeteredModel,
    data: Sequence[ObservedSeries],
    parameters: Sequence[str],
    bounds: Mapping[str, tuple[float, float]] | None = None,
    start: Mapping[str, float] | None = None,
    checker: Callable[[str], None] | None = None,
) -> FitProblem:
    """Build the least-squares problem, validating outputs and bounds.

    Raises:
        ToolArgumentError: If a series names an output the model does not have, has no
            observed sample, or the start lies outside the bounds.
    """
    idx, lower, upper = resolve_bounds(model, parameters, bounds)
    n_data = 0
    for series in data:
        if series.output not in model.output_names:
            raise ToolArgumentError(
                f"series observes {series.output!r}, which model {model.name!r} does not "
                f"output; it has {list(model.output_names)}"
            )
        if series.observed.size == 0:
            raise ToolArgumentError(f"series on {series.output!r} has no observed sample")
        if checker is not None:
            checker(series.output)
        n_data += int(series.observed.size)
    theta = model.theta_from(dict(start or {}))
    x0 = theta[idx]
    if np.any(x0 < lower) or np.any(x0 > upper):
        raise ToolArgumentError("the starting point lies outside the bounds")
    return FitProblem(
        model=model,
        parameters=tuple(parameters),
        idx=idx,
        lower=lower,
        upper=upper,
        theta_full=theta,
        data=tuple(data),
        n_data=n_data,
    )
