"""The aggregate per cell (proposal §7): means, rates and bootstrap intervals.

Rows are grouped by the configured keys (the (scenario, plant, tier, workflow) cell). For
every numeric column the group's ``n`` (rows with a value), mean and, where more than one
row carries a value, a seeded percentile-bootstrap interval of the mean; a boolean column
is a rate, with the same interval. Variance across seeds (§6.7 D) is the standard
deviation over the rows of the group. Kept boring on purpose: numpy only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from eval.config import AggregateConfig

__all__ = ["aggregate", "bootstrap_mean_interval"]


def bootstrap_mean_interval(
    values: np.ndarray, *, n_resamples: int, interval: float, seed: int
) -> tuple[float, float]:
    """A central percentile-bootstrap interval of the mean, from an explicit seed."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, values.size, size=(n_resamples, values.size))
    means = values[idx].mean(axis=1)
    tail = (1.0 - interval) / 2.0
    return float(np.quantile(means, tail)), float(np.quantile(means, 1.0 - tail))


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, str):
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def aggregate(rows: Sequence[dict[str, Any]], cfg: AggregateConfig) -> list[dict[str, Any]]:
    """One aggregate row per group, with ``<metric>_n``, ``_mean``, ``_sd``, ``_lo``, ``_hi``."""
    keys = tuple(cfg.group_by)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(tuple(row.get(k) for k in keys), []).append(row)
    columns: list[str] = []
    for row in rows:
        for name in row:
            if name not in keys and name not in columns:
                columns.append(name)
    boot = cfg.bootstrap
    out = []
    for key, members in sorted(groups.items(), key=lambda kv: tuple(str(k) for k in kv[0])):
        agg: dict[str, Any] = dict(zip(keys, key, strict=True))
        agg["n_runs"] = len(members)
        agg["n_completed"] = sum(1 for m in members if m.get("completed") is True)
        for column in columns:
            values = np.array(
                [v for v in (_numeric(m.get(column)) for m in members) if v is not None]
            )
            if values.size == 0:
                continue
            agg[f"{column}_n"] = int(values.size)
            agg[f"{column}_mean"] = float(values.mean())
            if values.size > 1:
                agg[f"{column}_sd"] = float(values.std(ddof=1))
                lo, hi = bootstrap_mean_interval(
                    values,
                    n_resamples=boot.n_resamples,
                    interval=boot.interval,
                    seed=boot.seed,
                )
                agg[f"{column}_lo"] = lo
                agg[f"{column}_hi"] = hi
        out.append(agg)
    return out
