"""Calibration: constrained multistart least squares, differential evolution, CMA-ES (§6.2).

All three minimise the same weighted SSR of :class:`~tools.impl._common.FitProblem` inside
the same bounds, with an explicit seed for the starts or the population (rule 4), and
report the same :class:`~tools.schemas.FitOutput`: the optimum, its cost, the
Jacobian-based covariance where the optimum is interior (``sigma^2 (J^T J)^-1`` with
``sigma^2 = chi2 / (n - k)``), and which parameters ended within 1 % of a bound.

- **fit_lsq**: ``scipy.optimize.least_squares`` from ``n_starts`` Latin-hypercube points
  plus the given start. The deterministic baseline.
- **fit_de**: ``scipy.optimize.differential_evolution`` with a fixed seed, population
  and generation budget; no polishing (a workflow that wants a local polish calls
  ``fit_lsq`` from the DE optimum, so the evaluations stay counted).
- **fit_cmaes**: ``cma.CMAEvolutionStrategy`` (Hansen), seeded, with a fixed evaluation
  budget and box bounds.
"""

from __future__ import annotations

import warnings

import numpy as np
from scipy.optimize import differential_evolution, least_squares

from tools.models import BudgetExhausted
from tools.registry import ToolContext
from tools.schemas import FitCMAESInput, FitDEInput, FitLSQInput, FitOutput

from ._common import FitProblem, ceiling, fit_problem, latin_hypercube

__all__ = ["cmaes_cost", "de_cost", "lsq_cost", "run_cmaes", "run_de", "run_lsq"]


def _covariance(
    problem: FitProblem, x: np.ndarray, chi2: float, ctx: ToolContext
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """``sigma^2 (J^T J)^-1`` at an interior optimum, or ``(None, None)``."""
    k = x.size
    if problem.n_data <= k:
        return None, None
    conf = ctx.configs.identifiability.fisher
    try:
        jac = problem.jacobian(x, conf.relative_step, conf.abs_step)
    except BudgetExhausted:
        return None, None
    jtj = jac.T @ jac
    if np.linalg.matrix_rank(jtj, tol=conf.rank_tolerance * max(np.abs(jtj).max(), 1e-300)) < k:
        return None, None
    sigma2 = chi2 / (problem.n_data - k)
    cov = sigma2 * np.linalg.inv(jtj)
    return cov, np.sqrt(np.clip(np.diag(cov), 0.0, None))


def _at_bound(problem: FitProblem, x: np.ndarray) -> tuple[str, ...]:
    width = problem.upper - problem.lower
    near = (x - problem.lower <= 0.01 * width) | (problem.upper - x <= 0.01 * width)
    return tuple(name for name, flag in zip(problem.parameters, near, strict=True) if flag)


def _output(
    method: str,
    problem: FitProblem,
    x: np.ndarray,
    chi2: float,
    starts_chi2: np.ndarray,
    converged: bool,
    message: str,
    ctx: ToolContext,
) -> FitOutput:
    cov, sd = _covariance(problem, x, chi2, ctx)
    return FitOutput(
        method=method,
        parameters=problem.parameters,
        theta=x,
        lower=problem.lower,
        upper=problem.upper,
        chi2=float(chi2),
        n_data=problem.n_data,
        covariance=cov,
        sd=sd,
        at_bound=_at_bound(problem, x),
        starts_chi2=starts_chi2,
        converged=converged,
        message=message,
        n_evaluations=problem.model.calls,
    )


# ------------------------------------------------------------------ lsq


def lsq_cost(inp: FitLSQInput, ctx: ToolContext) -> int:
    """``n_starts x max_nfev`` plus the covariance's ``2k``."""
    conf = ctx.configs.fitters.lsq
    n_starts = ceiling(inp.n_starts, conf.n_starts, "n_starts")
    nfev = ceiling(inp.max_nfev_per_start, conf.max_nfev_per_start, "max_nfev_per_start")
    # least_squares may evaluate a few times beyond max_nfev for the Jacobian of the last step
    return n_starts * (nfev + 2 * len(inp.parameters) + 1) + 2 * len(inp.parameters)


def run_lsq(inp: FitLSQInput, ctx: ToolContext) -> FitOutput:
    """Multistart bounded least squares."""
    conf = ctx.configs.fitters.lsq
    model = ctx.model(inp.model)
    problem = fit_problem(model, inp.data, inp.parameters, inp.bounds, inp.start)
    n_starts = ceiling(inp.n_starts, conf.n_starts, "n_starts")
    nfev = ceiling(inp.max_nfev_per_start, conf.max_nfev_per_start, "max_nfev_per_start")
    x0 = problem.theta_full[problem.idx]
    starts = [x0]
    if n_starts > 1:
        starts.extend(latin_hypercube(n_starts - 1, problem.lower, problem.upper, inp.seed))
    best_cost, best_x, best_msg, best_ok = np.inf, x0, "", False
    costs = []
    for start in starts:
        sol = least_squares(
            problem.residuals,
            np.clip(start, problem.lower, problem.upper),
            bounds=(problem.lower, problem.upper),
            method=conf.method,
            loss=conf.loss,
            max_nfev=nfev,
            ftol=conf.ftol,
            xtol=conf.xtol,
            gtol=conf.gtol,
        )
        cost = 2.0 * float(sol.cost)
        costs.append(cost)
        if cost < best_cost:
            best_cost, best_x, best_msg, best_ok = cost, sol.x, str(sol.message), bool(sol.success)
    return _output("fit_lsq", problem, best_x, best_cost, np.asarray(costs), best_ok, best_msg, ctx)


# ------------------------------------------------------------------ de


def de_cost(inp: FitDEInput, ctx: ToolContext) -> int:
    """``(max_generations + 1) x popsize x k`` plus the covariance's ``2k``."""
    conf = ctx.configs.fitters.de
    popsize = ceiling(inp.popsize, conf.popsize, "popsize")
    gens = ceiling(inp.max_generations, conf.max_generations, "max_generations")
    k = len(inp.parameters)
    return (gens + 1) * popsize * k + 2 * k


def run_de(inp: FitDEInput, ctx: ToolContext) -> FitOutput:
    """Differential evolution with a fixed seed, population and generation budget."""
    conf = ctx.configs.fitters.de
    model = ctx.model(inp.model)
    problem = fit_problem(model, inp.data, inp.parameters, inp.bounds, inp.start)
    popsize = ceiling(inp.popsize, conf.popsize, "popsize")
    gens = ceiling(inp.max_generations, conf.max_generations, "max_generations")
    history: list[float] = []

    def callback(intermediate_result: object, convergence: float | None = None) -> None:
        fun = getattr(intermediate_result, "fun", None)
        if fun is None:
            # scipy < 1.12 passes xk; recompute is one evaluation, so skip the history
            return
        history.append(float(fun))

    result = differential_evolution(
        problem.chi2,
        bounds=list(zip(problem.lower, problem.upper, strict=True)),
        strategy=conf.strategy,
        maxiter=gens,
        popsize=popsize,
        tol=conf.tol,
        mutation=tuple(conf.mutation),
        recombination=conf.recombination,
        seed=np.random.default_rng(inp.seed),
        polish=False,
        init=conf.init,
        x0=problem.theta_full[problem.idx],
        callback=callback,
    )
    return _output(
        "fit_de",
        problem,
        np.asarray(result.x, dtype=float),
        float(result.fun),
        np.asarray(history, dtype=float),
        bool(result.success),
        str(result.message),
        ctx,
    )


# ------------------------------------------------------------------ cma-es


def cmaes_cost(inp: FitCMAESInput, ctx: ToolContext) -> int:
    """``max_evaluations`` plus one generation's overshoot and the covariance's ``2k``."""
    conf = ctx.configs.fitters.cmaes
    max_evals = ceiling(inp.max_evaluations, conf.max_evaluations, "max_evaluations")
    k = len(inp.parameters)
    popsize = conf.popsize if conf.popsize is not None else 4 + int(3 * np.log(max(k, 1)))
    return max_evals + popsize + 2 * k


def run_cmaes(inp: FitCMAESInput, ctx: ToolContext) -> FitOutput:
    """CMA-ES inside the bounds with a fixed evaluation budget."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # cma warns about the absent matplotlib on import
        import cma

    conf = ctx.configs.fitters.cmaes
    model = ctx.model(inp.model)
    problem = fit_problem(model, inp.data, inp.parameters, inp.bounds, inp.start)
    max_evals = ceiling(inp.max_evaluations, conf.max_evaluations, "max_evaluations")
    width = problem.upper - problem.lower
    x0 = problem.theta_full[problem.idx]
    options = {
        "bounds": [list(problem.lower), list(problem.upper)],
        "seed": int(inp.seed) + 1,  # cma treats seed 0 as "draw one from the clock"
        "maxfevals": max_evals,
        "tolfun": conf.tolfun,
        "tolx": conf.tolx,
        "verbose": -9,
        "verb_log": 0,
    }
    if conf.popsize is not None:
        options["popsize"] = conf.popsize
    es = cma.CMAEvolutionStrategy(list(x0), float(conf.sigma0_fraction * width.min()), options)
    history: list[float] = []
    while not es.stop():
        candidates = es.ask()
        values = [problem.chi2(np.asarray(c, dtype=float)) for c in candidates]
        es.tell(candidates, values)
        history.append(float(min(values)))
    best_x = np.clip(np.asarray(es.result.xbest, dtype=float), problem.lower, problem.upper)
    best_cost = float(es.result.fbest)
    stop = es.stop()
    return _output(
        "fit_cmaes",
        problem,
        best_x,
        best_cost,
        np.asarray(history, dtype=float),
        bool(stop and "maxfevals" not in stop),
        ", ".join(f"{key}={value}" for key, value in stop.items()),
        ctx,
    )
