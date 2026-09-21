"""Practical identifiability: profile likelihood and Fisher information (§6.2, review §13).

Sensitivity is not identifiability: a parameter the output is sensitive to may still be
unidentifiable because another compensates for it. These two tools ask that question of
the *data*.

**profile_likelihood** (Raue et al. 2009): for each grid value of the profiled parameter,
the weighted SSR is minimised over the remaining free parameters from several starts
(a seeded Latin hypercube plus a warm start from the previous grid point), giving the
profile ``chi2(p)``. The confidence interval is where the profile lies below
``chi2_min + chi2_{1, 1 - alpha}``; a profile that never rises above the threshold on one
side is open there (practically non-identifiable in that direction), and one whose whole
rise across the grid is below ``flat_fraction`` of the threshold is **flat**.

**fisher_info**: ``FIM = J^T J`` on the weighted residuals (so the data weights are the
information), from central differences at the point of linearisation. Its eigenvalues
tell which directions the data inform; an eigenvalue below ``rank_tolerance`` of the
largest is a null direction, and the parameter correlation comes from the pseudo-inverse.
Cost ``2k`` evaluations.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import chi2 as chi2_dist

from tools.registry import ToolArgumentError, ToolContext
from tools.schemas import (
    FisherInfoInput,
    FisherInfoOutput,
    ProfileLikelihoodInput,
    ProfileLikelihoodOutput,
)

from ._common import ceiling, fit_problem, latin_hypercube

__all__ = ["fisher_cost", "profile_cost", "run_fisher", "run_profile"]


def profile_cost(inp: ProfileLikelihoodInput, ctx: ToolContext) -> int:
    """``n_grid x n_starts x max_nfev`` (plus one evaluation per start for the cost)."""
    conf = ctx.configs.identifiability.profile
    n_grid = len(inp.grid) if inp.grid is not None else ceiling(inp.n_grid, conf.n_grid, "n_grid")
    n_starts = ceiling(inp.n_starts, conf.n_starts, "n_starts")
    return n_grid * n_starts * (conf.max_nfev_per_start + 1)


def run_profile(inp: ProfileLikelihoodInput, ctx: ToolContext) -> ProfileLikelihoodOutput:
    """Profile one parameter of a fit."""
    conf = ctx.configs.identifiability.profile
    model = ctx.model(inp.model)
    problem = fit_problem(model, inp.data, inp.parameters, start=inp.center)
    n_starts = ceiling(inp.n_starts, conf.n_starts, "n_starts")
    j = list(inp.parameters).index(inp.profile)
    free = [i for i in range(len(inp.parameters)) if i != j]

    if inp.grid is not None:
        grid = np.asarray(inp.grid, dtype=float)
        if grid.ndim != 1 or grid.size < 3:
            raise ToolArgumentError("grid must be a 1-D array of at least three values")
        if np.any(grid < problem.lower[j]) or np.any(grid > problem.upper[j]):
            raise ToolArgumentError(f"grid leaves the bounds of {inp.profile!r}")
        grid = np.sort(grid)
    else:
        n_grid = ceiling(inp.n_grid, conf.n_grid, "n_grid")
        grid = np.linspace(problem.lower[j], problem.upper[j], n_grid)

    x_center = problem.theta_full[problem.idx].copy()
    lower_free, upper_free = problem.lower[free], problem.upper[free]
    chi2 = np.empty(grid.size)
    best = np.empty((grid.size, len(inp.parameters)))

    def solve_at(p_value: float, starts: list[np.ndarray]) -> tuple[float, np.ndarray]:
        def residuals(x_free: np.ndarray) -> np.ndarray:
            x = x_center.copy()
            x[j] = p_value
            x[free] = x_free
            return problem.residuals(x)

        best_cost, best_x = np.inf, None
        for x0 in starts:
            if not free:
                r = residuals(np.zeros(0))
                cost, x_opt = float(np.dot(r, r)), np.zeros(0)
            else:
                sol = least_squares(
                    residuals,
                    np.clip(x0, lower_free, upper_free),
                    bounds=(lower_free, upper_free),
                    max_nfev=conf.max_nfev_per_start,
                    ftol=conf.ftol,
                    xtol=conf.xtol,
                    gtol=conf.gtol,
                )
                cost, x_opt = 2.0 * float(sol.cost), sol.x
            if cost < best_cost:
                best_cost, best_x = cost, x_opt
        x = x_center.copy()
        x[j] = p_value
        x[free] = best_x
        return best_cost, x

    # start the sweep at the grid point nearest the centre and walk outwards both ways,
    # warm-starting each point from its neighbour, so a profile follows its own valley
    start_index = int(np.argmin(np.abs(grid - x_center[j])))
    order = [start_index]
    lo, hi = start_index - 1, start_index + 1
    while lo >= 0 or hi < grid.size:
        if hi < grid.size:
            order.append(hi)
            hi += 1
        if lo >= 0:
            order.append(lo)
            lo -= 1
    lhs = latin_hypercube(max(n_starts - 1, 0), lower_free, upper_free, inp.seed) if free else []
    previous: dict[int, np.ndarray] = {}
    for g in order:
        warm = []
        if g - 1 in previous:
            warm.append(previous[g - 1][free])
        if g + 1 in previous:
            warm.append(previous[g + 1][free])
        if not warm:
            warm.append(x_center[free])
        starts = warm[: max(1, n_starts)] + [row for row in lhs][: max(n_starts - len(warm), 0)]
        chi2[g], best[g] = solve_at(float(grid[g]), starts)
        previous[g] = best[g]

    chi2_min = float(chi2.min())
    threshold = chi2_min + float(chi2_dist.ppf(conf.confidence_level, df=1))
    inside = chi2 <= threshold
    g_min = int(np.argmin(chi2))
    left = g_min
    while left - 1 >= 0 and inside[left - 1]:
        left -= 1
    right = g_min
    while right + 1 < grid.size and inside[right + 1]:
        right += 1
    # the bounds are where the profile crosses the threshold, interpolated linearly
    # between the last grid point inside and the first outside, so an interval narrower
    # than the grid spacing is still reported with a width rather than as one point
    lower_ci = None if left == 0 else _crossing(grid, chi2, left, left - 1, threshold)
    upper_ci = (
        None if right == grid.size - 1 else _crossing(grid, chi2, right, right + 1, threshold)
    )
    rise = float(chi2.max() - chi2_min)
    flat = rise < conf.flat_fraction * (threshold - chi2_min)
    identifiable = lower_ci is not None and upper_ci is not None and not flat
    return ProfileLikelihoodOutput(
        parameter=inp.profile,
        grid=grid,
        chi2=chi2,
        chi2_min=chi2_min,
        threshold=threshold,
        interval=(lower_ci, upper_ci),
        identifiable=identifiable,
        flat=flat,
        best_fit_per_point=best,
        n_evaluations=model.calls,
    )


def _crossing(grid: np.ndarray, chi2: np.ndarray, inside: int, outside: int, level: float) -> float:
    """Where the profile crosses ``level`` between an inside and an outside grid point."""
    rise = chi2[outside] - chi2[inside]
    if rise <= 0.0:
        return float(grid[inside])
    frac = (level - chi2[inside]) / rise
    return float(grid[inside] + np.clip(frac, 0.0, 1.0) * (grid[outside] - grid[inside]))


def fisher_cost(inp: FisherInfoInput, ctx: ToolContext) -> int:
    """``2k`` evaluations for the central differences."""
    return 2 * len(inp.parameters)


def run_fisher(inp: FisherInfoInput, ctx: ToolContext) -> FisherInfoOutput:
    """The Fisher information at a point, its conditioning and null directions."""
    conf = ctx.configs.identifiability.fisher
    model = ctx.model(inp.model)
    problem = fit_problem(model, inp.data, inp.parameters, start=inp.at)
    x = problem.theta_full[problem.idx]
    jac = problem.jacobian(x, conf.relative_step, conf.abs_step)
    fim = jac.T @ jac
    eigenvalues, eigenvectors = np.linalg.eigh(fim)
    order = np.argsort(-eigenvalues)
    eigenvalues, eigenvectors = eigenvalues[order], eigenvectors[:, order]
    eigenvalues = np.maximum(eigenvalues, 0.0)
    largest = float(eigenvalues[0]) if eigenvalues.size else 0.0
    if largest <= 0.0:
        rank = 0
        null = np.eye(len(inp.parameters))
        condition = np.inf
    else:
        informed = eigenvalues > conf.rank_tolerance * largest
        rank = int(informed.sum())
        null = eigenvectors[:, ~informed].T
        smallest = float(eigenvalues[informed].min())
        condition = float(largest / smallest) if rank == len(inp.parameters) else np.inf
    # the correlation comes from a regularised inverse rather than the pseudo-inverse: on a
    # ridge the pseudo-inverse reports +1 (the inverse of the informed direction alone),
    # while the limit of (FIM + eps I)^-1 reports the -1 of two parameters that compensate,
    # which is the reading an identifiability analysis needs
    cov = np.linalg.inv(
        fim + conf.rank_tolerance * max(largest, conf.abs_step) * np.eye(fim.shape[0])
    )
    sd = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = cov / np.outer(sd, sd)
    corr = np.where(np.isfinite(corr), corr, np.nan)
    np.fill_diagonal(corr, 1.0)
    crlb = sd.copy()
    for direction in null:
        crlb[np.abs(direction) > 1e-8] = np.inf
    return FisherInfoOutput(
        parameters=tuple(inp.parameters),
        fim=fim,
        eigenvalues=eigenvalues,
        eigenvectors=eigenvectors,
        condition_number=condition,
        rank=rank,
        null_directions=null,
        correlation=corr,
        crlb_sd=crlb,
        ill_conditioned=bool(not np.isfinite(condition) or condition > conf.condition_warning),
        n_evaluations=model.calls,
    )
