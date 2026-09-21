"""residual_diag: residual structure by feed batch, load, temperature and time (§6.2).

A residual is evidence about *where* error entered, not an instruction to refit kinetics
(CLAUDE.md, domain reminders). This tool asks whether the residual is structured along
each covariate it is given -- binned means with a one-way ANOVA and ``eta^2`` (the share
of residual variance between bins) -- and whether it is structured in time: lag-1
autocorrelation, Durbin-Watson, the Wald-Wolfowitz runs test on the sign, and a linear
trend with its p-value. The covariate with the largest ``eta^2`` among the structured ones
is named ``most_explanatory``. Costs no simulator evaluation.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import f_oneway, linregress, norm

from tools.registry import ToolArgumentError, ToolContext
from tools.schemas import ResidualDiagInput, ResidualDiagOutput
from tools.schemas.tools import Covariate, CovariateStructure

__all__ = ["residual_diag_cost", "run_residual_diag", "runs_test"]


def residual_diag_cost(inp: ResidualDiagInput, ctx: ToolContext) -> int:
    """No simulator evaluation."""
    return 0


def runs_test(signs: np.ndarray) -> float:
    """Two-sided p-value of the Wald-Wolfowitz runs test on a boolean sequence."""
    n1 = int(signs.sum())
    n2 = int(signs.size - n1)
    if n1 == 0 or n2 == 0:
        return 1.0
    runs = 1 + int(np.sum(signs[1:] != signs[:-1]))
    mean = 1.0 + 2.0 * n1 * n2 / (n1 + n2)
    var = 2.0 * n1 * n2 * (2.0 * n1 * n2 - n1 - n2) / ((n1 + n2) ** 2 * (n1 + n2 - 1))
    if var <= 0.0:
        return 1.0
    z = (runs - mean) / np.sqrt(var)
    return float(2.0 * norm.sf(abs(z)))


def _bins(
    cov: Covariate, at: np.ndarray, n_bins: int, min_per_bin: int
) -> tuple[np.ndarray, np.ndarray | None, list[str]]:
    """Bin index per residual, the edges (numeric) and labels."""
    values = np.interp(at, cov.t, cov.value) if not cov.categorical else _nearest(cov, at)
    if cov.categorical:
        levels = np.unique(values)
        index = np.searchsorted(levels, values)
        return index, None, [f"{cov.name}={lv:g}" for lv in levels]
    finite = np.isfinite(values)
    edges = np.quantile(values[finite], np.linspace(0.0, 1.0, n_bins + 1))
    edges = np.unique(edges)
    if edges.size < 2:
        return np.zeros(values.size, dtype=int), edges, [f"{cov.name} all"]
    index = np.clip(np.searchsorted(edges, values, side="right") - 1, 0, edges.size - 2)
    labels = [f"{cov.name} in [{edges[i]:.4g}, {edges[i + 1]:.4g}]" for i in range(edges.size - 1)]
    return index, edges, labels


def _nearest(cov: Covariate, at: np.ndarray) -> np.ndarray:
    idx = np.clip(np.searchsorted(cov.t, at, side="right") - 1, 0, cov.t.size - 1)
    return cov.value[idx]


def run_residual_diag(inp: ResidualDiagInput, ctx: ToolContext) -> ResidualDiagOutput:
    """Residual structure in time and along every covariate."""
    conf = ctx.configs.residual_diag
    t = np.asarray(inp.t, dtype=float)
    r = np.asarray(inp.residual, dtype=float)
    if t.shape != r.shape or t.ndim != 1:
        raise ToolArgumentError("t and residual must be 1-D arrays of the same length")
    keep = np.isfinite(r)
    t, r = t[keep], r[keep]
    n = int(r.size)
    if n < 4:
        raise ToolArgumentError("at least four finite residuals are needed")
    mean, sd = float(r.mean()), float(r.std(ddof=1))
    centred = r - mean
    denom = float(np.dot(centred, centred))
    lag1 = float(np.dot(centred[1:], centred[:-1]) / denom) if denom > 0 else 0.0
    dw = float(np.sum(np.diff(r) ** 2) / denom) if denom > 0 else 2.0
    runs_p = runs_test(r > np.median(r))
    reg = linregress(t, r)
    serial = bool(abs(lag1) > conf.autocorrelation_threshold or runs_p < conf.runs_p_value)

    n_bins = conf.n_bins if inp.n_bins is None else int(inp.n_bins)
    structures = []
    for cov in inp.covariates:
        index, edges, labels = _bins(cov, t, n_bins, conf.min_per_bin)
        groups = [r[index == b] for b in range(len(labels))]
        kept = [
            (lab, g) for lab, g in zip(labels, groups, strict=True) if g.size >= conf.min_per_bin
        ]
        if len(kept) < 2:
            structures.append(
                CovariateStructure(
                    name=cov.name,
                    bin_edges=edges,
                    bin_labels=tuple(lab for lab, _ in kept),
                    bin_mean=np.array([g.mean() for _, g in kept]),
                    bin_se=np.array(
                        [g.std(ddof=1) / np.sqrt(g.size) if g.size > 1 else np.nan for _, g in kept]
                    ),
                    bin_n=np.array([g.size for _, g in kept], dtype=float),
                    eta_squared=0.0,
                    p_value=1.0,
                    structured=False,
                )
            )
            continue
        grand = np.concatenate([g for _, g in kept])
        ss_total = float(np.sum((grand - grand.mean()) ** 2))
        ss_between = float(sum(g.size * (g.mean() - grand.mean()) ** 2 for _, g in kept))
        eta2 = ss_between / ss_total if ss_total > 0 else 0.0
        if all(np.allclose(g, g[0]) for _, g in kept):
            p = 1.0
        else:
            p = float(f_oneway(*[g for _, g in kept]).pvalue)
            p = p if np.isfinite(p) else 1.0
        structures.append(
            CovariateStructure(
                name=cov.name,
                bin_edges=edges,
                bin_labels=tuple(lab for lab, _ in kept),
                bin_mean=np.array([g.mean() for _, g in kept]),
                bin_se=np.array([g.std(ddof=1) / np.sqrt(g.size) for _, g in kept]),
                bin_n=np.array([g.size for _, g in kept], dtype=float),
                eta_squared=float(eta2),
                p_value=p,
                structured=bool(p < conf.structure_p_value),
            )
        )
    structured = [s for s in structures if s.structured]
    most = max(structured, key=lambda s: s.eta_squared).name if structured else None
    return ResidualDiagOutput(
        n=n,
        mean=mean,
        sd=sd,
        lag1_autocorrelation=lag1,
        durbin_watson=dw,
        runs_p_value=runs_p,
        trend_slope_per_d=float(reg.slope),
        trend_p_value=float(reg.pvalue),
        serially_structured=serial,
        covariates=tuple(structures),
        most_explanatory=most,
    )
