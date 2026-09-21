"""Every tool of §6.2 against a known answer.

Each test states the analytic result it checks and where it comes from, so that a
numerical mistake in a tool fails against mathematics rather than against a golden value
produced by the same code:

- Morris on a linear-additive function: the elementary effects *are* the coefficients,
  ``mu = mu* = a_i (range_i)``, ``sigma = 0``; on a product the sigma is non-zero.
- Sobol on Ishigami (a = 7, b = 0.1): the closed-form indices (Sobol & Levitan 1999), and
  scipy's own ``sobol_indices`` as an independent estimator on the same function.
- Profile likelihood and Fisher information on a linear-Gaussian model with a
  non-identifiable direction (``y = a + b``): flat profile, rank-one FIM with null
  direction ``(1, -1) / sqrt 2``, correlation -1; on ``y = a t + b`` both are identifiable.
- The fitters recover the parameters of synthetic data generated with the same model at a
  known seed.
- MCMC coverage on a Gaussian target: the 90 % interval covers the truth at the nominal
  rate over seeds, and the posterior mean matches the analytic one.
- EnKF on a linear system against the exact Kalman filter; MHE recovers a constant
  parameter of that system.
- ``validate`` against hand-computed MAE / RMSE / bias / coverage / interval score / CRPS.
- ``data_qc`` on a series with a planted flatline, spike, drift and event gaps.
- ``mass_balance`` on a balanced synthetic digester (closure 0) and an unrecorded delivery.
- ``residual_diag`` on residuals that depend on load, and on white noise.
- ``voi_assay`` against the Gaussian closed form ``0.5 ln(1 + var_pred / var_noise)``.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import norm, sobol_indices, uniform

from tools import AnalyticModel, AnalyticStateSpaceModel, Budget, make_registry
from tools.impl.gsa import sobol_indices as our_sobol
from tools.impl.validate import crps_ensemble
from tools.schemas import ObservedSeries, Window
from tools.schemas.tools import Covariate, QCSeries

BIG = Budget(10**7, 10**6, 100)
T = np.linspace(0.0, 10.0, 21)


def reg_with(**models: AnalyticModel):
    return make_registry(budget=BIG, seed=1, models=models)


def scalar_model(name, k, f, lower=0.0, upper=1.0):
    return AnalyticModel(
        name=name,
        parameter_names=tuple(f"x{i}" for i in range(k)),
        defaults=np.full(k, 0.5 * (lower + upper)),
        lower=np.full(k, lower),
        upper=np.full(k, upper),
        function=lambda th: {"y": np.array([f(th)])},
        output_names=("y",),
    )


# ------------------------------------------------------------------ Morris


def test_morris_elementary_effects_of_a_linear_function_are_its_coefficients():
    a = np.array([3.0, -1.0, 0.5])
    reg = reg_with(lin=scalar_model("lin", 3, lambda x: float(a @ x), lower=-2.0, upper=2.0))
    out = reg.call(
        "gsa_morris", model="lin", parameters=("x0", "x1", "x2"), outputs=("y",),
        n_trajectories=6, seed=3,
    )  # fmt: skip
    res = out.results[0]
    np.testing.assert_allclose(res.mu, a * 4.0, atol=1e-10)  # range is 4
    np.testing.assert_allclose(res.mu_star, np.abs(a) * 4.0, atol=1e-10)
    np.testing.assert_allclose(res.sigma, 0.0, atol=1e-9)
    assert res.ranking == ("x0", "x1", "x2")
    assert out.n_evaluations == 6 * 4


def test_morris_sigma_is_non_zero_on_an_interaction():
    reg = reg_with(prod=scalar_model("prod", 2, lambda x: float(x[0] * x[1])))
    out = reg.call(
        "gsa_morris",
        model="prod",
        parameters=("x0", "x1"),
        outputs=("y",),
        n_trajectories=10,
        seed=5,
    )
    res = out.results[0]
    assert np.all(res.sigma > 0.05)
    # E[x1] = 0.5 over the levels, so mu* of x0 is about 0.5
    assert res.mu_star[0] == pytest.approx(0.5, abs=0.2)


# ------------------------------------------------------------------ Sobol


def ishigami(x: np.ndarray, a: float = 7.0, b: float = 0.1) -> float:
    return float(np.sin(x[0]) + a * np.sin(x[1]) ** 2 + b * x[2] ** 4 * np.sin(x[0]))


def ishigami_analytic(a: float = 7.0, b: float = 0.1) -> dict[str, np.ndarray]:
    v1 = 0.5 * (1.0 + b * np.pi**4 / 5.0) ** 2
    v2 = a**2 / 8.0
    v13 = b**2 * np.pi**8 * (1.0 / 18.0 - 1.0 / 50.0)
    v = v1 + v2 + v13
    return {
        "S1": np.array([v1, v2, 0.0]) / v,
        "ST": np.array([v1 + v13, v2, v13]) / v,
        "S13": v13 / v,
        "V": v,
    }


def test_sobol_indices_of_ishigami_match_the_closed_form_and_scipy():
    reg = reg_with(ish=scalar_model("ish", 3, ishigami, lower=-np.pi, upper=np.pi))
    out = reg.call(
        "gsa_sobol", model="ish", parameters=("x0", "x1", "x2"), outputs=("y",),
        n_samples=2048, second_order=True, seed=9,
    )  # fmt: skip
    res = out.results[0]
    exact = ishigami_analytic()
    np.testing.assert_allclose(res.S1, exact["S1"], atol=0.05)
    np.testing.assert_allclose(res.ST, exact["ST"], atol=0.05)
    assert res.S2[0, 2] == pytest.approx(exact["S13"], abs=0.06)
    assert abs(res.S2[0, 1]) < 0.06 and abs(res.S2[1, 2]) < 0.06
    assert res.variance == pytest.approx(exact["V"], rel=0.1)
    assert res.ranking == ("x0", "x1", "x2")  # by total order: ST1 > ST2 > ST3
    assert out.n_evaluations == 2048 * 8
    assert np.all(res.S1_conf > 0) and np.all(res.S1_conf < 0.1)

    # scipy's estimator on the same function: an independent implementation
    def f(x: np.ndarray) -> np.ndarray:
        return np.sin(x[0]) + 7.0 * np.sin(x[1]) ** 2 + 0.1 * x[2] ** 4 * np.sin(x[0])

    sp = sobol_indices(
        func=f, n=2048, dists=[uniform(loc=-np.pi, scale=2 * np.pi)] * 3,
        rng=np.random.default_rng(0),
    )  # fmt: skip
    np.testing.assert_allclose(res.S1, sp.first_order, atol=0.06)
    np.testing.assert_allclose(res.ST, sp.total_order, atol=0.06)


def test_the_sobol_estimators_are_exact_on_an_additive_function():
    """For f = x0 + 2 x1: S1 = (1, 4)/5, ST = S1, S2 = 0, whatever the design."""
    from scipy.stats import qmc

    n, k = 4096, 2
    base = qmc.Sobol(d=2 * k, scramble=True, seed=1).random(n)
    a, b = base[:, :k], base[:, k:]
    w = np.array([1.0, 2.0])
    f = lambda m: m @ w  # noqa: E731
    fab = np.stack([f(np.where(np.arange(k) == i, b, a)) for i in range(k)])
    fba = np.stack([f(np.where(np.arange(k) == i, a, b)) for i in range(k)])
    _, s1, st, s2 = our_sobol(f(a), f(b), fab, fba)
    np.testing.assert_allclose(s1, [0.2, 0.8], atol=0.03)
    np.testing.assert_allclose(st, [0.2, 0.8], atol=0.03)
    assert abs(s2[0, 1]) < 0.03


# ------------------------------------------------------------------ identifiability


def two_parameter_models():
    """``y = a + b`` (non-identifiable) and ``y = a t + b`` (identifiable), same grid."""
    common = dict(
        parameter_names=("a", "b"), defaults=np.array([1.0, 1.0]),
        lower=np.array([-4.0, -4.0]), upper=np.array([6.0, 6.0]), output_names=("y",), t=T,
    )  # fmt: skip
    ridge = AnalyticModel(
        name="ridge", function=lambda th: {"y": np.full(T.size, th[0] + th[1])}, **common
    )
    slope = AnalyticModel(name="slope", function=lambda th: {"y": th[0] * T + th[1]}, **common)
    return ridge, slope


def data_from(model, theta, seed=0, sd=0.2):
    rng = np.random.default_rng(seed)
    y = model.evaluate(np.asarray(theta))["y"]
    return ObservedSeries(output="y", t=T, value=y + sd * rng.standard_normal(T.size), sd=sd)


def test_the_profile_is_flat_along_a_ridge_and_closed_when_identifiable():
    ridge, slope = two_parameter_models()
    reg = reg_with(ridge=ridge, slope=slope)
    flat = reg.call(
        "profile_likelihood", model="ridge", data=(data_from(ridge, [2.0, 1.0]),),
        parameters=("a", "b"), profile="a", center={"a": 2.0, "b": 1.0},
        grid=np.linspace(-2.0, 5.0, 9), n_starts=2, seed=1,  # b = 3 - a stays inside its bounds
    )  # fmt: skip
    assert flat.flat and not flat.identifiable
    assert flat.interval == (None, None)
    assert np.ptp(flat.chi2) < 1e-6
    # b compensates exactly: a + b stays at the data's mean along the whole profile
    ridge_data = data_from(ridge, [2.0, 1.0])
    np.testing.assert_allclose(
        flat.best_fit_per_point.sum(axis=1), ridge_data.value.mean(), atol=1e-4
    )

    slope_data = data_from(slope, [2.0, 1.0])
    a_hat = np.polyfit(T, slope_data.value, 1)[0]
    closed = reg.call(
        "profile_likelihood", model="slope", data=(slope_data,),
        parameters=("a", "b"), profile="a", center={"a": float(a_hat), "b": 1.0},
        grid=np.linspace(1.85, 2.15, 31), n_starts=2, seed=1,
    )  # fmt: skip
    assert closed.identifiable and not closed.flat
    lo, hi = closed.interval
    # the 95 % interval of a from OLS: a_hat +/- 1.96 sd(a_hat), sd = 0.2 / sqrt(sum (t - tbar)^2)
    sd_a = 0.2 / np.sqrt(np.sum((T - T.mean()) ** 2))
    assert lo is not None and hi is not None and lo < a_hat < hi
    assert hi - lo == pytest.approx(2 * 1.96 * sd_a, rel=0.2)
    assert closed.grid[np.argmin(closed.chi2)] == pytest.approx(a_hat, abs=0.01)
    assert closed.chi2_min < closed.threshold


def test_fisher_information_finds_the_null_direction_of_the_ridge():
    ridge, slope = two_parameter_models()
    reg = reg_with(ridge=ridge, slope=slope)
    fim = reg.call(
        "fisher_info", model="ridge", data=(data_from(ridge, [2.0, 1.0]),), parameters=("a", "b")
    )
    assert fim.rank == 1
    assert fim.null_directions.shape == (1, 2)
    np.testing.assert_allclose(np.abs(fim.null_directions[0]), [1, 1] / np.sqrt(2), atol=1e-6)
    assert fim.correlation[0, 1] == pytest.approx(-1.0, abs=1e-6)
    assert fim.ill_conditioned and not np.isfinite(fim.condition_number)
    assert np.all(np.isinf(fim.crlb_sd))
    # FIM of y = a + b with n points at sd 0.2: every entry n / sd^2
    np.testing.assert_allclose(fim.fim, np.full((2, 2), T.size / 0.04), rtol=1e-6)
    assert fim.n_evaluations == 4

    ok = reg.call(
        "fisher_info", model="slope", data=(data_from(slope, [2.0, 1.0]),), parameters=("a", "b")
    )
    assert ok.rank == 2 and not ok.ill_conditioned
    # J = [t, 1] / sd: FIM = [[sum t^2, sum t], [sum t, n]] / sd^2
    expected = np.array([[np.sum(T**2), np.sum(T)], [np.sum(T), T.size]]) / 0.04
    np.testing.assert_allclose(ok.fim, expected, rtol=1e-6)
    np.testing.assert_allclose(ok.crlb_sd, np.sqrt(np.diag(np.linalg.inv(expected))), rtol=1e-6)


# ------------------------------------------------------------------ fitters


@pytest.mark.parametrize(
    "tool, extra",
    [
        ("fit_lsq", {"n_starts": 4}),
        ("fit_de", {"popsize": 8, "max_generations": 60}),
        ("fit_cmaes", {"max_evaluations": 800}),
    ],
)
def test_the_fitters_recover_known_parameters_from_synthetic_data(tool, extra):
    _, slope = two_parameter_models()
    reg = reg_with(slope=slope)
    truth = np.array([2.5, -0.7])
    data = data_from(slope, truth, seed=4, sd=0.1)
    out = reg.call(
        tool, model="slope", data=(data,), parameters=("a", "b"), seed=2,
        start={"a": 0.0, "b": 3.0}, **extra,
    )  # fmt: skip
    # the least-squares optimum of y = a t + b is the OLS solution
    x = np.stack([T, np.ones_like(T)], axis=1)
    ols = np.linalg.lstsq(x, data.value, rcond=None)[0]
    np.testing.assert_allclose(out.theta, ols, atol=2e-2)
    np.testing.assert_allclose(out.theta, truth, atol=0.1)
    assert out.chi2 < 2 * T.size
    assert out.at_bound == ()
    assert out.n_evaluations > 0
    if out.sd is not None:
        # sigma^2 (X^T X)^-1 with sigma^2 = chi2 / (n - k), in weighted units
        sigma2 = out.chi2 / (T.size - 2)
        cov = sigma2 * np.linalg.inv(x.T @ x / 0.01)
        np.testing.assert_allclose(out.sd, np.sqrt(np.diag(cov)), rtol=0.05)


def test_fit_lsq_reports_a_parameter_at_its_bound():
    _, slope = two_parameter_models()
    reg = reg_with(slope=slope)
    data = data_from(slope, [4.0, 0.0], seed=1, sd=0.05)  # b settles at ~5, inside its bounds
    out = reg.call(
        "fit_lsq", model="slope", data=(data,), parameters=("a", "b"), seed=1, n_starts=2,
        bounds={"a": (-1.0, 3.0)},
    )  # fmt: skip
    assert out.at_bound == ("a",)
    assert out.theta[0] == pytest.approx(3.0, abs=1e-6)


# ------------------------------------------------------------------ mcmc


def test_mcmc_recovers_a_gaussian_posterior_and_its_intervals_cover():
    """y_i = mu + e_i, e ~ N(0, sd^2), flat prior: posterior N(ybar, sd^2 / n)."""
    n, sd = 25, 0.5
    grid = np.arange(n, dtype=float)
    model = AnalyticModel(
        name="mean", parameter_names=("mu",), defaults=np.array([0.0]), lower=np.array([-10.0]),
        upper=np.array([10.0]), function=lambda th: {"y": np.full(n, th[0])},
        output_names=("y",), t=grid,
    )  # fmt: skip
    reg = reg_with(mean=model)
    covered = 0
    seeds = range(16)
    for seed in seeds:
        rng = np.random.default_rng(100 + seed)
        y = 1.3 + sd * rng.standard_normal(n)
        data = ObservedSeries(output="y", t=grid, value=y, sd=sd)
        out = reg.call(
            "bayes_mcmc", model="mean", data=(data,), parameters=("mu",),
            start={"mu": float(y.mean())}, n_walkers=16, n_steps=1500, seed=seed,
        )  # fmt: skip
        assert out.converged, (out.rhat, out.ess)
        post_sd = sd / np.sqrt(n)
        assert out.mean[0] == pytest.approx(y.mean(), abs=3 * post_sd / np.sqrt(out.ess[0]) + 0.02)
        assert out.sd[0] == pytest.approx(post_sd, rel=0.25)
        if out.quantiles["q05"][0] <= 1.3 <= out.quantiles["q95"][0]:
            covered += 1
    # 90 % nominal over 16 seeds: binomial(16, 0.9) has P(X < 12) < 0.01
    assert covered >= 12


def test_mcmc_likelihood_variants_run_and_agree_on_an_uncorrelated_series():
    _, slope = two_parameter_models()
    reg = reg_with(slope=slope)
    data = data_from(slope, [2.0, 1.0], seed=3, sd=0.2)
    means = {}
    for lik in ("gaussian", "ar1", "heteroscedastic"):
        out = reg.call(
            "bayes_mcmc", model="slope", data=(data,), parameters=("a", "b"), likelihood=lik,
            start={"a": 2.0, "b": 1.0}, n_walkers=16, n_steps=1500, seed=1, ar1_rho=0.1,
            heteroscedastic_cv=0.01,
        )  # fmt: skip
        means[lik] = out.mean
        assert out.converged
    for lik in ("ar1", "heteroscedastic"):
        np.testing.assert_allclose(means[lik], means["gaussian"], atol=0.1)


# ------------------------------------------------------------------ filters


def linear_system(n_steps: int = 40, phi: float = 0.9, drive: float = 0.0):
    """x_{k+1} = phi x_k + drive, y_k = x_k; phi is the slow parameter."""
    return AnalyticStateSpaceModel(
        name="ar", state_names=("x",), observation_names=("y",),
        transition_fn=lambda x, th, k: th[0] * x + drive, observe_fn=lambda x, th, k: x,
        n_steps=n_steps, parameter_names=("phi",), defaults=np.array([phi]),
        lower=np.array([0.5]), upper=np.array([1.0]),
    )  # fmt: skip


def kalman(y, phi, q, r, m0, p0):
    means, variances = [], []
    m, p = m0, p0
    for k, yk in enumerate(y):
        if k > 0:
            m, p = phi * m, phi**2 * p + q**2
        if np.isfinite(yk):
            gain = p / (p + r**2)
            m, p = m + gain * (yk - m), (1 - gain) * p
        means.append(m)
        variances.append(p)
    return np.array(means), np.array(variances)


def test_the_enkf_tracks_the_kalman_filter_on_a_linear_system():
    n, phi, q, r = 40, 0.9, 0.1, 0.3
    rng = np.random.default_rng(0)
    x = np.empty(n)
    x[0] = 2.0
    for k in range(1, n):
        x[k] = phi * x[k - 1] + q * rng.standard_normal()
    y = x + r * rng.standard_normal(n)
    y[10:13] = np.nan  # a gap
    reg = make_registry(budget=BIG, seed=1, state_space_models={"ar": linear_system(n, phi)})
    out = reg.call(
        "filter_enkf", model="ar", observations=y[:, None], observation_sd=[r], process_sd=[q],
        initial_mean=[0.0], initial_sd=[2.0], n_ensemble=400, seed=2,
    )  # fmt: skip
    km, kv = kalman(y, phi, q, r, 0.0, 4.0)
    np.testing.assert_allclose(out.mean[:, 0], km, atol=0.12)
    np.testing.assert_allclose(out.sd[:, 0], np.sqrt(kv), atol=0.05)
    assert out.n_evaluations == 400 * (n - 1)


def test_the_enkf_and_mhe_estimate_the_slow_parameter():
    """A driven system, x -> 1 / (1 - phi) = 5, so the level keeps identifying phi."""
    n, phi, q, r = 60, 0.8, 0.02, 0.1
    rng = np.random.default_rng(5)
    x = np.empty(n)
    x[0] = 3.0
    for k in range(1, n):
        x[k] = phi * x[k - 1] + 1.0 + q * rng.standard_normal()
    y = x + r * rng.standard_normal(n)
    reg = make_registry(
        budget=BIG, seed=1, state_space_models={"ar": linear_system(n, 0.7, drive=1.0)}
    )
    enkf = reg.call(
        "filter_enkf", model="ar", observations=y[:, None], observation_sd=[r], process_sd=[q],
        initial_mean=[3.0], initial_sd=[0.5], parameters=("phi",), n_ensemble=200, seed=3,
    )  # fmt: skip
    assert enkf.parameter_mean[-1, 0] == pytest.approx(phi, abs=0.03)
    mhe = reg.call(
        "filter_mhe", model="ar", observations=y[:, None], observation_sd=[r], process_sd=[q],
        initial_mean=[3.0], initial_sd=[0.5], parameters=("phi",), horizon_steps=8,
    )  # fmt: skip
    np.testing.assert_allclose(mhe.mean[5:, 0], x[5:], atol=0.15)
    assert mhe.parameter_estimate[-1, 0] == pytest.approx(phi, abs=0.03)


# ------------------------------------------------------------------ validate


def test_validate_matches_hand_computed_metrics():
    reg = reg_with()
    t = np.array([0.0, 1.0, 2.0, 3.0])
    obs = ObservedSeries(output="pH", t=t, value=[7.0, 7.2, 6.9, 7.1], sd=0.05)
    pred = np.array([7.1, 7.0, 6.9, 7.3])
    out = reg.call("validate", observed=(obs,), t=t, predicted={"pH": pred})
    m = out.results[0]
    err = pred - obs.value
    assert m.mae == pytest.approx(np.mean(np.abs(err)))
    assert m.rmse == pytest.approx(np.sqrt(np.mean(err**2)))
    assert m.bias == pytest.approx(np.mean(err))
    assert m.nrmse == pytest.approx(m.rmse / np.std(obs.value, ddof=1))
    assert m.coverage == {"50": None, "90": None} and m.crps is None
    assert m.constraint_violations == 0 and not out.ensemble

    # an ensemble: two members straddling the truth exactly on every point
    ens = np.stack([obs.value - 0.1, obs.value + 0.1, obs.value - 0.1, obs.value + 0.1] * 25)
    out = reg.call("validate", observed=(obs,), t=t, predicted={"pH": ens})
    m = out.results[0]
    assert out.ensemble
    assert m.coverage["90"] == 1.0
    assert m.bias == pytest.approx(0.0, abs=1e-12)
    # interval score of a [y - 0.1, y + 0.1] interval that always covers: its width
    assert m.interval_score["90"] == pytest.approx(0.2, abs=1e-9)
    # CRPS of a two-point ensemble {y - d, y + d} at y: E|X - y| - E|X - X'|/2 = d - d/2
    assert m.crps == pytest.approx(0.05, abs=1e-9)
    # a constraint violation: pH 15 in one member at one point
    bad = ens.copy()
    bad[0, 0] = 15.0
    out = reg.call("validate", observed=(obs,), t=t, predicted={"pH": bad})
    assert out.results[0].constraint_violations == 1


def test_crps_of_a_gaussian_ensemble_matches_the_closed_form():
    """CRPS of N(0, 1) at y: y (2 Phi(y) - 1) + 2 phi(y) - 1/sqrt(pi) (Gneiting & Raftery 2007)."""
    rng = np.random.default_rng(0)
    samples = rng.standard_normal((20000, 1))
    at_zero = 2 * norm.pdf(0) - 1 / np.sqrt(np.pi)
    assert crps_ensemble(samples, np.array([0.0])) == pytest.approx(at_zero, abs=0.01)
    # and at y = 1: 2 phi(1) + (2 Phi(1) - 1) - 1/sqrt(pi)
    exact = 1 * (2 * norm.pdf(1) + 2 * norm.cdf(1) - 1) - 1 / np.sqrt(np.pi)
    assert crps_ensemble(samples, np.array([1.0])) == pytest.approx(exact, abs=0.01)


# ------------------------------------------------------------------ data_qc


def test_data_qc_finds_the_planted_flatline_spike_drift_and_event_gaps():
    reg = reg_with()
    rng = np.random.default_rng(0)
    t = np.arange(120, dtype=float)
    clean = 7.0 + 0.02 * rng.standard_normal(t.size)
    flat = clean.copy()
    flat[40:47] = flat[40]
    spike = clean.copy()
    spike[60] += 1.0
    drift = clean + 0.01 * t
    gaps = clean.copy()
    gaps[80:95] = np.nan
    gaps[[3, 50]] = np.nan
    out = reg.call(
        "data_qc",
        series=(
            QCSeries(name="clean", t=t, value=clean, unit="pH"),
            QCSeries(name="flat", t=t, value=flat, unit="pH"),
            QCSeries(name="spike", t=t, value=spike, unit="pH"),
            QCSeries(name="drift", t=t, value=drift, unit="pH"),
            QCSeries(name="gaps", t=t, value=gaps, unit="pH"),
            QCSeries(name="nounit", t=t, value=clean, unit=""),
        ),
        event_windows=(Window(start=80.0, end=95.0),),
    )
    by = {r.name: r for r in out.results}
    assert by["clean"].flags == ()
    assert by["flat"].flags == ("flatline",)
    assert by["flat"].flatlines[0].start == 40.0 and by["flat"].flatlines[0].n_samples == 7
    assert by["spike"].flags == ("spikes",)
    np.testing.assert_array_equal(by["spike"].spikes, [60.0])
    assert by["drift"].flags == ("drift",)
    assert by["drift"].drift_slope_per_d == pytest.approx(0.01, abs=0.002)
    assert "informative_missingness" in by["gaps"].flags
    assert by["gaps"].n_missing == 17 and by["gaps"].longest_gap_d == 15.0
    assert by["gaps"].event_missing_ratio > 10
    assert by["nounit"].flags == ("no_unit",)
    assert set(out.flagged) == {"flat", "spike", "drift", "gaps", "nounit"}


# ------------------------------------------------------------------ mass_balance


def test_mass_balance_closes_on_a_balanced_digester_and_opens_on_an_unrecorded_delivery():
    reg = reg_with()
    t = np.arange(60, dtype=float)
    q = np.full(t.size, 50.0)  # m3/d
    cod_in = np.full(t.size, 2000.0)  # kg COD/d
    # 60 % of the COD leaves as methane, 40 % in the effluent, every day
    ch4_m3 = 0.6 * 2000.0 / 2.857
    gas = ObservedSeries(output="gas", t=t, value=np.full(t.size, ch4_m3 / 0.65), sd=1.0)
    ch4 = ObservedSeries(output="ch4", t=t, value=np.full(t.size, 0.65), sd=0.01)
    cod_out = ObservedSeries(output="cod", t=t, value=np.full(t.size, 0.4 * 2000.0 / 50.0), sd=0.1)
    tan = ObservedSeries(output="tan", t=t, value=np.full(t.size, 1.0), sd=0.05)
    windows = (Window(start=0, end=29), Window(start=30, end=59))
    common = dict(
        windows=windows, t=t, q_in_m3_d=q, cod_in_kg_d=cod_in, tkn_in_kg_n_d=np.full(t.size, 80.0),
        gas_flow=gas, ch4_fraction=ch4, cod_out=cod_out, tan_out=tan, V_liq_m3=1800.0, T_op_K=308.0,
    )  # fmt: skip
    out = reg.call("mass_balance", **common)
    assert out.admissible
    for w in out.windows:
        assert w.cod_closure == pytest.approx(0.0, abs=1e-9)
        assert w.cod_admissible
        # 80 kg N/d in, 50 kg N/d out as TAN: closure 0.375 = the organic-N share, expected
        assert w.n_closure == pytest.approx(0.375)
        assert w.n_admissible
    # a digestate that carries MORE ammoniacal N out than the feed's TKN violates the balance
    hot = dict(common)
    hot["tan_out"] = ObservedSeries(output="tan", t=t, value=np.full(t.size, 2.0), sd=0.05)
    assert not reg.call("mass_balance", **hot).windows[0].n_admissible
    # the second half fed an extra 40 % that never entered the log: the balance opens
    heavy = dict(common)
    heavy["cod_in_kg_d"] = np.where(t >= 30, 2000.0 / 1.4, 2000.0)
    out = reg.call("mass_balance", **heavy)
    assert out.windows[0].cod_admissible and not out.windows[1].cod_admissible
    assert out.windows[1].cod_closure == pytest.approx(1 - 1.4, abs=1e-9)
    assert not out.admissible


def test_mass_balance_charge_consistency_from_ph_alkalinity_vfa_and_tan():
    reg = reg_with()
    t = np.arange(40, dtype=float)
    series = lambda v, sd=0.01: ObservedSeries(output="x", t=t, value=np.full(t.size, v), sd=sd)  # noqa: E731
    out = reg.call(
        "mass_balance", windows=(Window(start=0, end=19), Window(start=20, end=39)), t=t,
        q_in_m3_d=np.full(t.size, 50.0), cod_in_kg_d=np.full(t.size, 2000.0),
        tkn_in_kg_n_d=np.full(t.size, 80.0), ph=series(7.2), alkalinity=series(5.0),
        vfa=series(0.5), tan_out=series(1.5), V_liq_m3=1800.0, T_op_K=308.0,
    )  # fmt: skip
    sid = out.windows[0].implied_sid_keq_m3
    # bicarbonate (5.0 / 50.04 minus the VFA anion) + VFA anion - NH4+ (1.5 / 14.007 at pH 7.2)
    vfa_ion = (0.5 / 60.05) / (1 + 10**-7.2 / 10**-4.76)
    nh4 = (1.5 / 14.007) / (1 + 10**-9.25 / 10**-7.2)
    assert sid == pytest.approx(5.0 / 50.04 - nh4, abs=1e-6)
    assert vfa_ion > 0
    assert out.charge_drift == pytest.approx(0.0, abs=1e-12) and out.charge_consistent


# ------------------------------------------------------------------ residual_diag


def test_residual_diag_names_the_covariate_that_explains_the_residual():
    reg = reg_with()
    rng = np.random.default_rng(2)
    t = np.arange(100, dtype=float)
    load = rng.uniform(1.0, 3.0, size=t.size)
    temp = 308.0 + 0.5 * rng.standard_normal(t.size)
    structured = 0.5 * (load - 2.0) + 0.05 * rng.standard_normal(t.size)
    out = reg.call(
        "residual_diag", t=t, residual=structured,
        covariates=(
            Covariate(name="load", t=t, value=load),
            Covariate(name="temperature", t=t, value=temp),
        ),
    )  # fmt: skip
    by = {c.name: c for c in out.covariates}
    assert by["load"].structured and by["load"].eta_squared > 0.8
    assert not by["temperature"].structured
    assert out.most_explanatory == "load"
    assert not out.serially_structured  # the load draws are iid, so the residual is too
    white = 0.1 * rng.standard_normal(t.size)
    out = reg.call(
        "residual_diag", t=t, residual=white,
        covariates=(Covariate(name="load", t=t, value=load),),
    )  # fmt: skip
    assert out.most_explanatory is None and not out.serially_structured
    assert abs(out.lag1_autocorrelation) < 0.25
    # an AR(1) residual is serially structured
    ar = np.empty(t.size)
    ar[0] = 0.0
    for k in range(1, t.size):
        ar[k] = 0.9 * ar[k - 1] + 0.1 * rng.standard_normal()
    out = reg.call("residual_diag", t=t, residual=ar)
    assert out.serially_structured and out.lag1_autocorrelation > 0.6
    # a categorical covariate (feed batch id) is grouped by value
    batch = (t // 25).astype(float)
    by_batch = 0.3 * (batch - 1.5) + 0.05 * rng.standard_normal(t.size)
    out = reg.call(
        "residual_diag", t=t, residual=by_batch,
        covariates=(Covariate(name="batch", t=t, value=batch, categorical=True),),
    )  # fmt: skip
    assert out.covariates[0].structured and len(out.covariates[0].bin_labels) == 4


# ------------------------------------------------------------------ voi_assay


class FakeAssayServer:
    """Only the noise models, for the pure test."""

    def __init__(self, noise: dict[str, tuple[float, float]]) -> None:
        """Hold the ``sensor -> (cv, sd_abs)`` table."""
        self._noise = noise

    def noise_models(self) -> dict[str, tuple[float, float]]:
        return dict(self._noise)


def test_voi_of_a_gaussian_predictive_matches_the_closed_form():
    """EIG = 0.5 ln(1 + var_pred / var_noise) for a Gaussian predictive and Gaussian noise.

    ``tan`` on day 5 equals the parameter itself; the posterior is N(1, 0.3^2) and the
    assay's sd_abs is 0.2, so EIG = 0.5 ln(1 + 0.09 / 0.04) = 0.589 nats.
    """
    model = AnalyticModel(
        name="m", parameter_names=("k",), defaults=np.array([1.0]), lower=np.array([-5.0]),
        upper=np.array([5.0]),
        function=lambda th: {"tan": np.full(11, th[0]), "alkalinity_total": np.full(11, 3.0)},
        output_names=("tan", "alkalinity_total"), t=T[:11],
    )  # fmt: skip
    reg = make_registry(
        budget=BIG, seed=1, models={"m": model},
        assay_server=FakeAssayServer({"tan": (0.0, 0.2), "alkalinity": (0.05, 0.0)}),
    )  # fmt: skip
    rng = np.random.default_rng(0)
    samples = 1.0 + 0.3 * rng.standard_normal((5000, 1))
    out = reg.call(
        "voi_assay", model="m", samples=samples, parameters=("k",), day=5.0,
        assays=("tan", "alkalinity"), n_outer=200, n_inner=200, seed=4,
    )  # fmt: skip
    by = {r.assay: r for r in out.results}
    assert by["tan"].eig_nats == pytest.approx(0.5 * np.log(1 + 0.09 / 0.04), abs=0.08)
    assert by["alkalinity"].eig_nats == pytest.approx(0.0, abs=0.05)  # it does not depend on k
    assert out.ranking[0] == "tan"
    assert out.n_evaluations == 400
