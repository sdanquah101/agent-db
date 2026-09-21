"""voi_assay: expected information gain of each requestable assay (§6.2, RQ4).

For each assay in ``configs/tools/assays.yaml``, the model is evaluated at ``n_outer``
posterior draws to get the predicted assay value on the requested day; with the assay's
declared noise (``sd = sqrt((cv v)^2 + sd_abs^2)`` at the predicted value, from the lab
sensor's noise model) the expected information gain on the parameters is the nested Monte
Carlo estimator

    EIG = E_theta E_{y | theta} [ log p(y | theta) - log (1/M) sum_j p(y | theta_j) ],

with the inner sum over ``n_inner`` further draws (Ryan et al. 2016). The known-answer
test is the Gaussian case: a linear model with a Gaussian posterior has
``EIG = 0.5 ln(1 + var(prediction) / var(noise))``. EIG per unit cost ranks the assays.
Cost ``n_outer + n_inner`` evaluations per call (shared across assays: one evaluation
gives every channel).
"""

from __future__ import annotations

import numpy as np

from tools.registry import ToolArgumentError, ToolContext
from tools.schemas import VOIAssayInput, VOIAssayOutput
from tools.schemas.tools import AssayVOI

from ._common import ceiling

__all__ = ["gaussian_eig", "run_voi", "voi_cost"]


def voi_cost(inp: VOIAssayInput, ctx: ToolContext) -> int:
    """``n_outer + n_inner`` evaluations."""
    conf = ctx.configs.voi
    return ceiling(inp.n_outer, conf.n_outer, "n_outer") + ceiling(
        inp.n_inner, conf.n_inner, "n_inner"
    )


def gaussian_eig(
    predictions_outer: np.ndarray,
    predictions_inner: np.ndarray,
    noise_sd: np.ndarray,
    rng: np.random.Generator,
) -> float:
    """Nested Monte Carlo EIG for a Gaussian observation of a scalar prediction.

    Args:
        predictions_outer: ``(n_outer,)`` predicted values at outer draws.
        predictions_inner: ``(n_inner,)`` predicted values at inner draws.
        noise_sd: ``(n_outer,)`` noise sd at each outer prediction.
        rng: Stream of the simulated observations.
    """
    y = predictions_outer + noise_sd * rng.standard_normal(predictions_outer.shape)
    log_lik = -0.5 * ((y - predictions_outer) / noise_sd) ** 2 - np.log(noise_sd)
    # marginal: average the likelihood over the inner draws, at each inner draw's own noise
    sd_inner = np.interp(
        predictions_inner, np.sort(predictions_outer), noise_sd[np.argsort(predictions_outer)]
    )
    diff = (y[:, None] - predictions_inner[None, :]) / sd_inner[None, :]
    log_terms = -0.5 * diff**2 - np.log(sd_inner)[None, :]
    log_marg = np.logaddexp.reduce(log_terms, axis=1) - np.log(predictions_inner.size)
    return float(np.mean(log_lik - log_marg))


def run_voi(inp: VOIAssayInput, ctx: ToolContext) -> VOIAssayOutput:
    """EIG per assay on the requested day."""
    conf = ctx.configs.voi
    model = ctx.model(inp.model)
    catalogue = ctx.configs.assays
    names = tuple(inp.assays) if inp.assays else tuple(sorted(catalogue.assays))
    for name in names:
        if name not in catalogue.assays:
            raise ToolArgumentError(
                f"unknown assay {name!r}; the catalogue has {sorted(catalogue.assays)}"
            )
    samples = np.asarray(inp.samples, dtype=float)
    if samples.ndim != 2 or samples.shape[1] != len(inp.parameters):
        raise ToolArgumentError("samples must be (n, k) with one column per named parameter")
    idx = model.index(inp.parameters)
    n_outer = ceiling(inp.n_outer, conf.n_outer, "n_outer")
    n_inner = ceiling(inp.n_inner, conf.n_inner, "n_inner")
    rng = np.random.default_rng(inp.seed)
    t = model.t
    if inp.day > t[-1] + 1e-9 or inp.day < t[0] - 1e-9:
        raise ToolArgumentError(f"day {inp.day} lies outside the model's grid [{t[0]}, {t[-1]}]")

    noise = _noise_models(ctx)
    channels = {}
    for name in names:
        spec = catalogue.assays[name]
        if spec.channel not in model.output_names:
            raise ToolArgumentError(
                f"assay {name!r} samples {spec.channel!r}, not an output of {model.name!r}"
            )
        channels[name] = spec

    def draw(n: int) -> dict[str, np.ndarray]:
        picks = rng.integers(0, samples.shape[0], size=n)
        out = {name: np.empty(n) for name in names}
        for i, pick in enumerate(picks):
            theta = model.defaults.copy()
            theta[idx] = samples[pick]
            result = model.evaluate(theta)
            for name in names:
                out[name][i] = np.interp(inp.day, t, result[channels[name].channel])
        return out

    outer = draw(n_outer)
    inner = draw(n_inner)
    results = []
    for name in names:
        spec = channels[name]
        cv, sd_abs = noise.get(spec.sensor, (0.0, 0.0))
        pred_o, pred_i = outer[name], inner[name]
        sd = np.sqrt((cv * np.abs(pred_o)) ** 2 + sd_abs**2)
        sd = np.maximum(sd, 1e-12)
        eig = gaussian_eig(pred_o, pred_i, sd, rng)
        results.append(
            AssayVOI(
                assay=name,
                channel=spec.channel,
                unit_cost=spec.unit_cost,
                eig_nats=max(eig, 0.0),
                eig_per_unit=max(eig, 0.0) / spec.unit_cost,
                predictive_sd=float(np.std(pred_o, ddof=1)) if pred_o.size > 1 else 0.0,
                noise_sd=float(np.mean(sd)),
            )
        )
    ranking = tuple(r.assay for r in sorted(results, key=lambda r: -r.eig_per_unit))
    return VOIAssayOutput(
        day=inp.day, results=tuple(results), ranking=ranking, n_evaluations=model.calls
    )


def _noise_models(ctx: ToolContext) -> dict[str, tuple[float, float]]:
    """``sensor -> (cv, sd_abs)`` from the assay server if present, else from the model's units."""
    server = ctx.assay_server
    if server is not None and hasattr(server, "noise_models"):
        return dict(server.noise_models())
    return {}
