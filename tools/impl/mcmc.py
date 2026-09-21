"""bayes_mcmc: reduced-parameter MCMC with a configurable likelihood (§6.2).

emcee's affine-invariant ensemble sampler (Foreman-Mackey et al. 2013; decisions log,
2026-09-21) over a uniform box prior on the bounds, with the likelihood chosen per call:

- ``gaussian``: independent residuals, ``sd`` per point from the series;
- ``heteroscedastic``: ``sd_i = sd_i + cv |prediction_i|``;
- ``ar1``: the residuals of each series are an AR(1) process with lag-1 correlation
  ``rho`` (given, or the config default), so the log-likelihood is that of the whitened
  innovations.

**Convergence is reported, never assumed** (the Level-8 row exists to test exactly this).
Split-R-hat (Gelman et al. 2013, ch. 11: each walker's chain split in two) and the
effective sample size from the autocorrelation time (Goodman & Weare's integrated
autocorrelation over the walker-mean chain, emcee's estimator) are computed per
parameter; ``converged`` is true only when every R-hat is below the threshold and every
ESS above the floor. The output carries the samples regardless, marked by that flag.

**The injected failure** (:func:`failure_payload`) is what a sampler that has not
converged looks like: a few dispersed walkers that barely move, so the diagnostics
computed on them -- by the same functions -- give R-hat far above 1.1 and a tiny ESS. It
is a return value, not an exception, with ``converged=False`` and a warning string; a
workflow that reports its quantiles as a posterior has failed the row.
"""

from __future__ import annotations

import numpy as np

from tools.config import MCMCConfig
from tools.registry import ToolContext
from tools.schemas import BayesMCMCInput, BayesMCMCOutput

from ._common import FitProblem, ceiling, fit_problem

__all__ = ["effective_sample_size", "failure_payload", "mcmc_cost", "run_mcmc", "split_rhat"]


# ------------------------------------------------------------------ diagnostics


def split_rhat(chains: np.ndarray) -> np.ndarray:
    """Split Gelman-Rubin R-hat per parameter for ``(n_steps, n_chains, k)`` chains."""
    n, _, k = chains.shape
    half = n // 2
    if half < 2:
        return np.full(k, np.inf)
    split = np.concatenate([chains[:half], chains[half : 2 * half]], axis=1)  # (half, 2m, k)
    n_s = split.shape[0]
    chain_means = split.mean(axis=0)  # (2m, k)
    chain_vars = split.var(axis=0, ddof=1)  # (2m, k)
    between = n_s * chain_means.var(axis=0, ddof=1)
    within = chain_vars.mean(axis=0)
    var_hat = (n_s - 1) / n_s * within + between / n_s
    with np.errstate(divide="ignore", invalid="ignore"):
        rhat = np.sqrt(var_hat / within)
    return np.where(np.isfinite(rhat), rhat, np.inf)


def _autocovariance(x: np.ndarray) -> np.ndarray:
    """Autocovariance of one 1-D chain at every lag, FFT-based, normalised so lag 0 is s^2."""
    n = x.size
    x = x - x.mean()
    size = 1 << (2 * n - 1).bit_length()
    f = np.fft.rfft(x, n=size)
    acov = np.fft.irfft(f * np.conjugate(f))[:n] / n
    return acov * n / (n - 1)


def effective_sample_size(chains: np.ndarray) -> np.ndarray:
    """Multi-chain ESS per parameter for ``(n_steps, n_chains, k)`` chains.

    The estimator of Gelman et al. (2013, ch. 11) as Stan implements it: the lag-``t``
    correlation of the *mixture* of chains is ``1 - (W - mean_m acov_{t,m}) / var_hat``,
    with ``W`` the mean within-chain variance and ``var_hat`` the pooled variance estimate
    that also feeds R-hat; the integrated autocorrelation time is summed over Geyer's
    initial monotone positive sequence, and ``ESS = n m / tau``. A set of chains that have
    not mixed has a tiny ``W`` against a large ``var_hat``, so every lag correlates near 1
    and the ESS collapses to the order of the number of chains -- which is what a
    non-converged sampler should report, and what the walker-averaged estimator of emcee
    would miss.
    """
    n, m, k = chains.shape
    ess = np.empty(k)
    for j in range(k):
        x = chains[:, :, j]
        if n < 4:
            ess[j] = float(m)
            continue
        chain_var = x.var(axis=0, ddof=1)
        w = float(chain_var.mean())
        b = float(n * x.mean(axis=0).var(ddof=1)) if m > 1 else 0.0
        var_hat = (n - 1) / n * w + b / n
        if not np.isfinite(var_hat) or var_hat <= 0.0:
            ess[j] = float(n * m)
            continue
        acov = np.stack([_autocovariance(x[:, c]) for c in range(m)], axis=1)
        rho = 1.0 - (w - acov.mean(axis=1)) / var_hat
        tau = -1.0
        previous = np.inf
        t = 0
        while t + 1 < n:
            pair = rho[t] + rho[t + 1]
            if pair <= 0.0:
                break
            pair = min(pair, previous)
            previous = pair
            tau += 2.0 * pair
            t += 2
        ess[j] = float(min(n * m / max(tau, 1e-12), n * m))
    return ess


def _summary(
    problem: FitProblem, flat: np.ndarray, chains: np.ndarray, conf: MCMCConfig, **rest: object
) -> BayesMCMCOutput:
    rhat = split_rhat(chains)
    ess = effective_sample_size(chains)
    converged = bool(np.all(rhat < conf.rhat_threshold) and np.all(ess > conf.ess_floor))
    q = {
        name: np.quantile(flat, p, axis=0)
        for name, p in (("q05", 0.05), ("q25", 0.25), ("q50", 0.5), ("q75", 0.75), ("q95", 0.95))
    }
    if flat.shape[0] > conf.max_samples_returned:
        keep = np.linspace(0, flat.shape[0] - 1, conf.max_samples_returned).astype(int)
        returned = flat[keep]
    else:
        returned = flat
    return BayesMCMCOutput(
        parameters=problem.parameters,
        mean=flat.mean(axis=0),
        sd=flat.std(axis=0, ddof=1) if flat.shape[0] > 1 else np.zeros(flat.shape[1]),
        quantiles=q,
        rhat=rhat,
        ess=ess,
        converged=converged,
        samples=returned,
        **rest,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ the sampler


def mcmc_cost(inp: BayesMCMCInput, ctx: ToolContext) -> int:
    """``n_walkers x (n_steps + 1)`` evaluations."""
    conf = ctx.configs.mcmc
    walkers = ceiling(inp.n_walkers, conf.n_walkers, "n_walkers")
    steps = ceiling(inp.n_steps, conf.n_steps, "n_steps")
    return walkers * (steps + 1)


def _log_likelihood_factory(problem: FitProblem, inp: BayesMCMCInput, ctx: ToolContext):  # noqa: ANN202
    conf = ctx.configs.mcmc
    rho = conf.ar1_rho_default if inp.ar1_rho is None else float(inp.ar1_rho)
    cv = (
        conf.heteroscedastic_cv_default
        if inp.heteroscedastic_cv is None
        else float(inp.heteroscedastic_cv)
    )
    t_model = problem.model.t

    def log_likelihood(x: np.ndarray) -> float:
        outputs = problem.predict(x)
        total = 0.0
        for series in problem.data:
            obs = series.observed
            pred = np.interp(series.t[obs], t_model, outputs[series.output])
            sd = series.sd_per_point[obs]
            if inp.likelihood == "heteroscedastic":
                sd = sd + cv * np.abs(pred)
            r = series.value[obs] - pred
            if inp.likelihood == "ar1" and r.size > 1:
                z = r / sd
                innov = z[1:] - rho * z[:-1]
                total += -0.5 * (z[0] ** 2 + np.sum(innov**2) / (1.0 - rho**2))
                total += -np.sum(np.log(sd)) - 0.5 * (r.size - 1) * np.log(1.0 - rho**2)
            else:
                total += -0.5 * np.sum((r / sd) ** 2) - np.sum(np.log(sd))
        return float(total)

    return log_likelihood


def run_mcmc(inp: BayesMCMCInput, ctx: ToolContext) -> BayesMCMCOutput:
    """Sample the posterior of the named parameters with emcee."""
    import emcee

    conf = ctx.configs.mcmc
    model = ctx.model(inp.model)
    problem = fit_problem(model, inp.data, inp.parameters, inp.bounds, inp.start)
    k = len(inp.parameters)
    walkers = ceiling(inp.n_walkers, conf.n_walkers, "n_walkers")
    steps = ceiling(inp.n_steps, conf.n_steps, "n_steps")
    if walkers < 2 * k:
        walkers = 2 * k + (2 * k) % 2  # emcee's minimum, kept even
    log_likelihood = _log_likelihood_factory(problem, inp, ctx)
    lower, upper = problem.lower, problem.upper

    def log_prob(x: np.ndarray) -> float:
        if np.any(x < lower) or np.any(x > upper):
            return -np.inf
        value = log_likelihood(x)
        return value if np.isfinite(value) else -np.inf

    rng = np.random.default_rng(inp.seed)
    width = upper - lower
    centre = problem.theta_full[problem.idx]
    p0 = centre + conf.initial_ball_fraction * width * rng.uniform(-1.0, 1.0, size=(walkers, k))
    p0 = np.clip(p0, lower + 1e-9 * width, upper - 1e-9 * width)

    sampler = emcee.EnsembleSampler(walkers, k, log_prob)
    sampler.random_state = np.random.RandomState(inp.seed).get_state()
    sampler.run_mcmc(p0, steps, progress=False, skip_initial_state_check=True)
    chains = sampler.get_chain()  # (steps, walkers, k)
    log_probs = sampler.get_log_prob()
    burn = int(conf.burn_in_fraction * steps)
    kept = chains[burn :: conf.thin]
    flat = kept.reshape(-1, k)
    return _summary(
        problem,
        flat,
        kept,
        conf,
        acceptance_fraction=float(np.mean(sampler.acceptance_fraction)),
        log_prob_max=float(np.max(log_probs)),
        n_walkers=walkers,
        n_steps=steps,
        n_evaluations=model.calls,
        warning=""
        if np.all(split_rhat(kept) < conf.rhat_threshold)
        else "chains have not converged",
    )


def failure_payload(
    inp: BayesMCMCInput, ctx: ToolContext, rng: np.random.Generator
) -> BayesMCMCOutput:
    """The Level-8 payload: chains that have not converged, from the same diagnostics.

    A handful of walkers scattered across the box, each jittering in place: R-hat far
    above the threshold, ESS near the number of walkers, quantiles that are the spread of
    the walkers rather than a posterior. No model evaluation is made and none is charged.
    """
    conf = ctx.configs.mcmc.injected_failure
    model = ctx.model(inp.model)
    problem = fit_problem(model, inp.data, inp.parameters, inp.bounds, inp.start)
    k = len(inp.parameters)
    width = problem.upper - problem.lower
    centre = problem.theta_full[problem.idx]
    anchors = centre + conf.spread_fraction * width * rng.uniform(
        -0.5, 0.5, size=(conf.n_walkers, k)
    )
    anchors = np.clip(anchors, problem.lower, problem.upper)
    jitter = (
        conf.jitter_fraction * width * rng.standard_normal(size=(conf.n_steps, conf.n_walkers, k))
    )
    chains = np.clip(anchors[None, :, :] + jitter, problem.lower, problem.upper)
    flat = chains.reshape(-1, k)
    return _summary(
        problem,
        flat,
        chains,
        ctx.configs.mcmc,
        acceptance_fraction=float(rng.uniform(0.01, 0.05)),
        log_prob_max=float("nan"),
        n_walkers=conf.n_walkers,
        n_steps=conf.n_steps,
        n_evaluations=0,
        warning="chains have not converged: R-hat above threshold, ESS below floor",
    )
