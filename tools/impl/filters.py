"""filter_enkf and filter_mhe: sequential state estimation with bounded slow parameters.

Both work on a registered :class:`~tools.models.StateSpaceModel` (a one-step transition
and an observation map on an ensemble), which is how the Level-4 row's "state estimation
converges; parameters unchanged" is answered without refitting kinetics.

**EnKF** (Evensen 2003, stochastic form with perturbed observations): the state is
augmented with the named slow parameters, each member is propagated, inflated, and updated
with the Kalman gain from the ensemble covariances; parameters are clipped to their
bounds after every analysis. Missing observations (NaN) are skipped for that step. Every
member propagation is one transition; the tool charges ``n_ensemble x n_steps``.

**MHE** (Rao et al. 2003): over a sliding window of ``horizon_steps``, the window's first
state and the slow parameters are chosen to minimise the weighted misfit of the window's
observations plus an arrival cost on the first state (its distance from the previous
window's estimate over the initial sd); the states inside the window follow the
deterministic transition. ``least_squares`` with bounds, one transition per step per
residual evaluation.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from tools.models import EvaluationMeter, StateSpaceModel
from tools.registry import ToolArgumentError, ToolContext
from tools.schemas import FilterEnKFInput, FilterEnKFOutput, FilterMHEInput, FilterMHEOutput

from ._common import ceiling

__all__ = ["enkf_cost", "mhe_cost", "run_enkf", "run_mhe"]


def _check(model: StateSpaceModel, inp: FilterEnKFInput | FilterMHEInput) -> tuple[int, int, int]:
    n_state = len(model.state_names)
    n_obs = len(model.observation_names)
    y = np.asarray(inp.observations, dtype=float)
    if y.ndim != 2 or y.shape[1] != n_obs:
        raise ToolArgumentError(f"observations must be (n_steps, {n_obs}), got {y.shape}")
    if y.shape[0] > model.n_steps:
        raise ToolArgumentError(
            f"model {model.name!r} has {model.n_steps} steps, {y.shape[0]} observed"
        )
    for name, size in (
        ("observation_sd", n_obs),
        ("process_sd", n_state),
        ("initial_mean", n_state),
        ("initial_sd", n_state),
    ):
        if getattr(inp, name).shape != (size,):
            raise ToolArgumentError(f"{name} must have shape ({size},)")
    for p in inp.parameters:
        if p not in model.parameter_names:
            raise ToolArgumentError(f"{p!r} is not a parameter of {model.name!r}")
    return n_state, n_obs, y.shape[0]


def _parameter_box(
    model: StateSpaceModel, inp: FilterEnKFInput | FilterMHEInput
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    idx = np.array([list(model.parameter_names).index(p) for p in inp.parameters], dtype=int)
    lower = np.asarray(model.lower, dtype=float)[idx] if idx.size else np.zeros(0)
    upper = np.asarray(model.upper, dtype=float)[idx] if idx.size else np.zeros(0)
    if inp.parameter_lower is not None:
        lower = np.maximum(lower, np.asarray(inp.parameter_lower, dtype=float))
    if inp.parameter_upper is not None:
        upper = np.minimum(upper, np.asarray(inp.parameter_upper, dtype=float))
    return idx, lower, upper


def enkf_cost(inp: FilterEnKFInput, ctx: ToolContext) -> int:
    """``n_ensemble x n_steps`` transitions."""
    n = ceiling(inp.n_ensemble, ctx.configs.filters.enkf.n_ensemble, "n_ensemble")
    return n * int(np.asarray(inp.observations).shape[0])


def run_enkf(inp: FilterEnKFInput, ctx: ToolContext) -> FilterEnKFOutput:
    """Stochastic EnKF with augmented slow parameters."""
    conf = ctx.configs.filters.enkf
    model = ctx.state_space(inp.model)
    n_state, n_obs, n_steps = _check(model, inp)
    n_ens = ceiling(inp.n_ensemble, conf.n_ensemble, "n_ensemble")
    p_idx, p_lower, p_upper = _parameter_box(model, inp)
    n_par = p_idx.size
    rng = np.random.default_rng(inp.seed)
    meter: EvaluationMeter = ctx.meter

    theta_base = np.asarray(model.defaults, dtype=float).copy()
    x = inp.initial_mean + inp.initial_sd * rng.standard_normal((n_ens, n_state))
    if n_par:
        p_centre = 0.5 * (p_lower + p_upper)
        params = p_centre + (p_upper - p_lower) / 4.0 * rng.standard_normal((n_ens, n_par))
        params = np.clip(params, p_lower, p_upper)
    else:
        params = np.zeros((n_ens, 0))
    y = np.asarray(inp.observations, dtype=float)
    r_sd = np.asarray(inp.observation_sd, dtype=float)
    q_sd = np.asarray(inp.process_sd, dtype=float)

    means = np.empty((n_steps, n_state))
    sds = np.empty((n_steps, n_state))
    p_means = np.empty((n_steps, n_par)) if n_par else None
    p_sds = np.empty((n_steps, n_par)) if n_par else None

    def observe_all(x: np.ndarray, params: np.ndarray, k: int) -> np.ndarray:
        out = np.empty((n_ens, n_obs))
        for i in range(n_ens):
            theta = theta_base.copy()
            theta[p_idx] = params[i]
            out[i] = model.observe(x[i : i + 1], theta, k)[0]
        return out

    for k in range(n_steps):
        if k > 0:
            meter.charge(n_ens)
            new = np.empty_like(x)
            for i in range(n_ens):
                theta = theta_base.copy()
                theta[p_idx] = params[i]
                new[i] = model.transition(x[i : i + 1], theta, k - 1)[0]
            x = new + q_sd * rng.standard_normal(x.shape)
            if n_par and conf.parameter_random_walk > 0.0:
                params = params + conf.parameter_random_walk * (
                    p_upper - p_lower
                ) * rng.standard_normal(params.shape)
                params = np.clip(params, p_lower, p_upper)
        # analysis
        observed = np.isfinite(y[k])
        aug = np.concatenate([x, params], axis=1)
        aug_mean = aug.mean(axis=0)
        aug = aug_mean + conf.inflation * (aug - aug_mean)
        if observed.any():
            hx = observe_all(aug[:, :n_state], aug[:, n_state:], k)[:, observed]
            a = aug - aug.mean(axis=0)
            hy = hx - hx.mean(axis=0)
            p_xy = a.T @ hy / (n_ens - 1)
            p_yy = hy.T @ hy / (n_ens - 1) + np.diag(r_sd[observed] ** 2)
            gain = p_xy @ np.linalg.pinv(p_yy)
            perturbed = y[k, observed] + r_sd[observed] * rng.standard_normal(
                (n_ens, int(observed.sum()))
            )
            aug = aug + (perturbed - hx) @ gain.T
        x = aug[:, :n_state]
        params = np.clip(aug[:, n_state:], p_lower, p_upper) if n_par else params
        means[k] = x.mean(axis=0)
        sds[k] = x.std(axis=0, ddof=1)
        if n_par:
            p_means[k] = params.mean(axis=0)
            p_sds[k] = params.std(axis=0, ddof=1)
    return FilterEnKFOutput(
        t=np.asarray(model.t, dtype=float)[:n_steps],
        mean=means,
        sd=sds,
        parameter_mean=p_means,
        parameter_sd=p_sds,
        n_evaluations=n_ens * max(n_steps - 1, 0),
    )


def mhe_cost(inp: FilterMHEInput, ctx: ToolContext) -> int:
    """``n_steps x max_nfev x horizon`` transitions (upper bound)."""
    conf = ctx.configs.filters.mhe
    horizon = ceiling(inp.horizon_steps, conf.horizon_steps, "horizon_steps")
    n_steps = int(np.asarray(inp.observations).shape[0])
    k = len(inp.parameters)
    return n_steps * (conf.max_nfev + 2 * (k + 10)) * horizon


def run_mhe(inp: FilterMHEInput, ctx: ToolContext) -> FilterMHEOutput:
    """Moving-horizon estimation of the state and the slow parameters."""
    conf = ctx.configs.filters.mhe
    model = ctx.state_space(inp.model)
    n_state, _, n_steps = _check(model, inp)
    horizon = ceiling(inp.horizon_steps, conf.horizon_steps, "horizon_steps")
    p_idx, p_lower, p_upper = _parameter_box(model, inp)
    n_par = p_idx.size
    meter: EvaluationMeter = ctx.meter
    theta_base = np.asarray(model.defaults, dtype=float).copy()
    y = np.asarray(inp.observations, dtype=float)
    r_sd = np.asarray(inp.observation_sd, dtype=float)
    s_lower = (
        np.full(n_state, -np.inf)
        if inp.state_lower is None
        else np.asarray(inp.state_lower, dtype=float)
    )
    s_upper = (
        np.full(n_state, np.inf)
        if inp.state_upper is None
        else np.asarray(inp.state_upper, dtype=float)
    )

    prior_mean = np.asarray(inp.initial_mean, dtype=float).copy()
    prior_sd = np.asarray(inp.initial_sd, dtype=float).copy()
    p_est = 0.5 * (p_lower + p_upper) if n_par else np.zeros(0)
    estimates = np.empty((n_steps, n_state))
    p_estimates = np.empty((n_steps, n_par)) if n_par else None
    costs = np.empty(n_steps)
    window_states: list[np.ndarray] = []

    for k in range(n_steps):
        start = max(0, k - horizon + 1)
        steps = list(range(start, k + 1))
        first_guess = window_states[0] if window_states and start > 0 else prior_mean
        if start > 0 and len(window_states) > 1:
            first_guess = window_states[1] if len(window_states) >= horizon else window_states[0]

        def residuals(
            z: np.ndarray, steps: list[int] = steps, first_guess: np.ndarray = first_guess
        ) -> np.ndarray:
            x0 = z[:n_state]
            theta = theta_base.copy()
            theta[p_idx] = z[n_state:]
            parts = [np.sqrt(conf.arrival_cost_weight) * (x0 - first_guess) / prior_sd]
            x = x0[None, :]
            for j, step in enumerate(steps):
                if j > 0:
                    meter.charge(1)
                    x = model.transition(x, theta, step - 1)
                observed = np.isfinite(y[step])
                if observed.any():
                    hx = model.observe(x, theta, step)[0]
                    parts.append((y[step, observed] - hx[observed]) / r_sd[observed])
            return np.concatenate(parts)

        z0 = np.concatenate([np.clip(first_guess, s_lower, s_upper), p_est])
        lower = np.concatenate([s_lower, p_lower])
        upper = np.concatenate([s_upper, p_upper])
        sol = least_squares(residuals, z0, bounds=(lower, upper), max_nfev=conf.max_nfev)
        x0 = sol.x[:n_state]
        p_est = sol.x[n_state:]
        theta = theta_base.copy()
        theta[p_idx] = p_est
        # roll the window forward to recover the states at every step
        x = x0[None, :]
        window_states = [x0]
        for step in steps[1:]:
            meter.charge(1)
            x = model.transition(x, theta, step - 1)
            window_states.append(x[0])
        estimates[k] = window_states[-1]
        if n_par:
            p_estimates[k] = p_est
        costs[k] = 2.0 * float(sol.cost)
    return FilterMHEOutput(
        t=np.asarray(model.t, dtype=float)[:n_steps],
        mean=estimates,
        parameter_estimate=p_estimates,
        chi2=costs,
        n_evaluations=int(meter.used),
    )
