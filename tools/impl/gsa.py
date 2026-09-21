"""Global sensitivity analysis: Morris screening and Sobol indices (proposal §6.2).

Both are implemented here rather than through SALib (decisions log, 2026-09-21: SALib
pulls in pandas, matplotlib and multiprocess for two estimators of a few dozen lines) and
tested against analytic indices -- a linear-additive function for Morris, the Ishigami
function for Sobol, and scipy's own ``sobol_indices`` as an independent cross-check.

**Morris** (Morris 1991; Campolongo et al. 2007): ``r`` trajectories on a ``p``-level
grid of the unit hypercube, step ``delta = p / (2 (p - 1))``, one elementary effect per
parameter per trajectory, ``mu``, ``mu*`` and ``sigma`` per output summary. Effects are
per unit of the **normalised** parameter range, so a parameter's ``mu*`` is the change of
the output across its whole admissible range. Cost ``r (k + 1)``.

**Sobol** (Saltelli et al. 2010 design; Jansen 1999 estimators): matrices ``A``, ``B``
and ``AB_i`` (``A`` with column ``i`` from ``B``), first order
``S_i = mean(f(B) (f(AB_i) - f(A))) / V`` and total order
``ST_i = mean((f(A) - f(AB_i))^2) / (2 V)``; with ``second_order`` the ``BA_i`` matrices
are added and ``S_ij = (mean(f(BA_i) f(AB_j)) - f0^2) / V - S_i - S_j`` (Saltelli 2002).
The base sample is a scrambled Sobol sequence (``scipy.stats.qmc``, seeded). Cost
``N (2k + 2)`` with second order, ``N (k + 2)`` without. Confidence half-widths are
bootstrap percentiles over the sample index.
"""

from __future__ import annotations

import warnings

import numpy as np
from scipy.stats import qmc

from tools.models import MeteredModel, summarise
from tools.registry import ToolArgumentError, ToolContext
from tools.schemas import (
    GSAMorrisInput,
    GSAMorrisOutput,
    GSASobolInput,
    GSASobolOutput,
)
from tools.schemas.tools import MorrisIndices, SobolIndices

from ._common import ceiling, resolve_bounds

__all__ = [
    "morris_cost",
    "morris_trajectories",
    "run_morris",
    "run_sobol",
    "sobol_cost",
    "sobol_indices",
]


def _summaries(
    model: MeteredModel,
    theta_rows: np.ndarray,
    outputs: tuple[str, ...],
    summary: str,
    window: tuple[float, float] | None,
) -> np.ndarray:
    """``(n_rows, n_outputs)`` scalar summaries of the model at every row."""
    for name in outputs:
        if name not in model.output_names:
            raise ToolArgumentError(f"{name!r} is not an output of model {model.name!r}")
    out = np.empty((theta_rows.shape[0], len(outputs)))
    for i, theta in enumerate(theta_rows):
        result = model.evaluate(theta)
        for j, name in enumerate(outputs):
            out[i, j] = summarise(result[name], model.t, summary, window)
    return out


def _window(inp: GSAMorrisInput | GSASobolInput) -> tuple[float, float] | None:
    return None if inp.window is None else (inp.window.start, inp.window.end)


# ------------------------------------------------------------------ Morris


def morris_trajectories(
    r: int, k: int, p: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray, float]:
    """``r`` Morris trajectories on the unit hypercube.

    Returns:
        ``(points, order, delta)``: ``points`` is ``(r, k + 1, k)``; ``order[i, s]`` is
        the parameter that changes between point ``s`` and ``s + 1`` of trajectory ``i``.
    """
    delta = p / (2.0 * (p - 1))
    grid = np.arange(p) / (p - 1)
    # a base point must leave room for a step of +delta: the levels 0 .. p/2 - 1
    base_levels = grid[grid <= 1.0 - delta + 1e-12]
    points = np.empty((r, k + 1, k))
    order = np.empty((r, k), dtype=int)
    for i in range(r):
        x = rng.choice(base_levels, size=k)
        signs = rng.choice([-1.0, 1.0], size=k)
        # a negative step needs the base moved up so the point stays inside the cube
        x = np.where(signs < 0, x + delta, x)
        perm = rng.permutation(k)
        points[i, 0] = x
        for s, j in enumerate(perm):
            x = x.copy()
            x[j] += signs[j] * delta
            points[i, s + 1] = x
            order[i, s] = j
    return points, order, delta


def morris_cost(inp: GSAMorrisInput, ctx: ToolContext) -> int:
    """``r (k + 1)`` evaluations."""
    r = ceiling(inp.n_trajectories, ctx.configs.gsa.morris.n_trajectories, "n_trajectories")
    return r * (len(inp.parameters) + 1)


def run_morris(inp: GSAMorrisInput, ctx: ToolContext) -> GSAMorrisOutput:
    """Morris screening of the named parameters."""
    model = ctx.model(inp.model)
    conf = ctx.configs.gsa.morris
    r = ceiling(inp.n_trajectories, conf.n_trajectories, "n_trajectories")
    p = conf.n_levels if inp.n_levels is None else int(inp.n_levels)
    if p % 2:
        raise ToolArgumentError("n_levels must be even")
    idx, lower, upper = resolve_bounds(model, inp.parameters)
    k = idx.size
    rng = np.random.default_rng(inp.seed)
    points, order, delta = morris_trajectories(r, k, p, rng)

    theta_rows = np.tile(model.defaults, (r * (k + 1), 1))
    unit = points.reshape(r * (k + 1), k)
    theta_rows[:, idx] = lower + unit * (upper - lower)
    values = _summaries(model, theta_rows, inp.outputs, inp.summary, _window(inp))
    values = values.reshape(r, k + 1, len(inp.outputs))

    effects = np.empty((r, k, len(inp.outputs)))
    for i in range(r):
        for s in range(k):
            j = order[i, s]
            sign = np.sign(points[i, s + 1, j] - points[i, s, j])
            effects[i, j] = sign * (values[i, s + 1] - values[i, s]) / delta

    results = []
    for o, name in enumerate(inp.outputs):
        ee = effects[:, :, o]
        mu = ee.mean(axis=0)
        mu_star = np.abs(ee).mean(axis=0)
        sigma = ee.std(axis=0, ddof=1) if r > 1 else np.zeros(k)
        ranking = tuple(inp.parameters[j] for j in np.argsort(-mu_star, kind="stable"))
        results.append(
            MorrisIndices(output=name, mu=mu, mu_star=mu_star, sigma=sigma, ranking=ranking)
        )
    units = {name: model.output_units.get(name, "-") for name in inp.outputs}
    return GSAMorrisOutput(
        parameters=tuple(inp.parameters),
        results=tuple(results),
        n_trajectories=r,
        n_evaluations=model.calls,
        units=units,
    )


# ------------------------------------------------------------------ Sobol


def sobol_indices(
    fA: np.ndarray,
    fB: np.ndarray,
    fAB: np.ndarray,
    fBA: np.ndarray | None,
) -> tuple[float, np.ndarray, np.ndarray, np.ndarray | None]:
    """Jansen / Saltelli estimators from the evaluated design.

    Args:
        fA: ``(N,)`` outputs on ``A``.
        fB: ``(N,)`` outputs on ``B``.
        fAB: ``(k, N)`` outputs on ``AB_i``.
        fBA: ``(k, N)`` outputs on ``BA_i``, or ``None``.

    Returns:
        ``(variance, S1, ST, S2)``; ``S2`` is ``(k, k)`` with NaN on the diagonal, or
        ``None`` without the second-order matrices.
    """
    k = fAB.shape[0]
    both = np.concatenate([fA, fB])
    f0 = both.mean()
    variance = float(both.var(ddof=0))
    # centred on the design's own mean, as SALib does: the estimators are unbiased either
    # way and the centred forms have the smaller finite-sample variance
    fA, fB, fAB = fA - f0, fB - f0, fAB - f0
    fBA = None if fBA is None else fBA - f0
    if variance <= 0.0:
        return 0.0, np.zeros(k), np.zeros(k), (np.full((k, k), np.nan) if fBA is not None else None)
    s1 = np.array([np.mean(fB * (fAB[i] - fA)) for i in range(k)]) / variance
    st = np.array([np.mean((fA - fAB[i]) ** 2) for i in range(k)]) / (2.0 * variance)
    s2 = None
    if fBA is not None:
        s2 = np.full((k, k), np.nan)
        for i in range(k):
            for j in range(i + 1, k):
                vij = np.mean(fBA[i] * fAB[j])
                s2[i, j] = s2[j, i] = vij / variance - s1[i] - s1[j]
    return variance, s1, st, s2


def sobol_cost(inp: GSASobolInput, ctx: ToolContext) -> int:
    """``N (2k + 2)`` with second order, ``N (k + 2)`` without."""
    conf = ctx.configs.gsa.sobol
    n = ceiling(inp.n_samples, conf.n_samples, "n_samples")
    second = conf.second_order if inp.second_order is None else inp.second_order
    k = len(inp.parameters)
    return n * ((2 * k + 2) if second else (k + 2))


def run_sobol(inp: GSASobolInput, ctx: ToolContext) -> GSASobolOutput:
    """Variance-based indices, first, total and (optionally) second order."""
    model = ctx.model(inp.model)
    conf = ctx.configs.gsa.sobol
    n = ceiling(inp.n_samples, conf.n_samples, "n_samples")
    second = conf.second_order if inp.second_order is None else bool(inp.second_order)
    idx, lower, upper = resolve_bounds(model, inp.parameters)
    k = idx.size

    sampler = qmc.Sobol(d=2 * k, scramble=True, seed=np.random.default_rng(inp.seed))
    base = sampler.random(n)
    a_unit, b_unit = base[:, :k], base[:, k:]
    designs = [a_unit, b_unit]
    for i in range(k):
        ab = a_unit.copy()
        ab[:, i] = b_unit[:, i]
        designs.append(ab)
    if second:
        for i in range(k):
            ba = b_unit.copy()
            ba[:, i] = a_unit[:, i]
            designs.append(ba)
    unit = np.concatenate(designs, axis=0)
    theta_rows = np.tile(model.defaults, (unit.shape[0], 1))
    theta_rows[:, idx] = lower + unit * (upper - lower)
    values = _summaries(model, theta_rows, inp.outputs, inp.summary, _window(inp))

    results = []
    rng = np.random.default_rng(np.random.SeedSequence([inp.seed, 1]))
    for o, name in enumerate(inp.outputs):
        col = values[:, o]
        fA, fB = col[:n], col[n : 2 * n]
        fAB = col[2 * n : (2 + k) * n].reshape(k, n)
        fBA = col[(2 + k) * n :].reshape(k, n) if second else None
        variance, s1, st, s2 = sobol_indices(fA, fB, fAB, fBA)
        # bootstrap over the sample index
        s1_b, st_b, s2_b = [], [], []
        for _ in range(conf.bootstrap_resamples):
            pick = rng.integers(0, n, size=n)
            _, b1, bt, b2 = sobol_indices(
                fA[pick], fB[pick], fAB[:, pick], None if fBA is None else fBA[:, pick]
            )
            s1_b.append(b1)
            st_b.append(bt)
            if b2 is not None:
                s2_b.append(b2)
        alpha = 1.0 - conf.confidence_level

        def half_width(samples: list[np.ndarray], alpha: float = alpha) -> np.ndarray:
            if not samples:
                return np.full_like(samples[0] if samples else np.zeros(k), np.nan)
            stack = np.stack(samples)
            with warnings.catch_warnings():
                # the second-order matrix carries NaN on its diagonal by construction
                warnings.filterwarnings("ignore", "All-NaN slice", RuntimeWarning)
                lo = np.nanpercentile(stack, 100 * alpha / 2, axis=0)
                hi = np.nanpercentile(stack, 100 * (1 - alpha / 2), axis=0)
            return (hi - lo) / 2.0

        s1_conf = half_width(s1_b) if s1_b else np.full(k, np.nan)
        st_conf = half_width(st_b) if st_b else np.full(k, np.nan)
        s2_conf = (half_width(s2_b) if s2_b else np.full((k, k), np.nan)) if second else None
        ranking = tuple(inp.parameters[j] for j in np.argsort(-st, kind="stable"))
        results.append(
            SobolIndices(
                output=name,
                variance=variance,
                S1=s1,
                S1_conf=s1_conf,
                ST=st,
                ST_conf=st_conf,
                S2=s2,
                S2_conf=s2_conf,
                ranking=ranking,
            )
        )
    units = {name: model.output_units.get(name, "-") for name in inp.outputs}
    return GSASobolOutput(
        parameters=tuple(inp.parameters),
        results=tuple(results),
        n_samples=n,
        n_evaluations=model.calls,
        units=units,
    )
