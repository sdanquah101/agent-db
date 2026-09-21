"""data_qc: unit and timestamp checks, flatline / spike / drift detectors, missingness by event.

Rule-based, no learning (§6.2). Each detector is the simplest thing an engineer would
script, with its threshold in ``configs/tools/data_qc.yaml``:

- **flatline**: a run of ``flatline_min_samples`` or more consecutive identical readings;
- **spike**: ``|x - rolling median| > k x 1.4826 x MAD`` of the same residual, a robust
  z-score that a single outlier cannot inflate;
- **drift**: a Theil-Sen slope over the observed samples whose total excursion across the
  record exceeds ``drift_signal_to_noise`` times the residual sd around it;
- **missingness by event**: the missing rate inside the given event windows over the rate
  outside; above ``event_missing_ratio`` the gaps are called informative (§6.1: instruments
  fail during foaming and overload, so the gaps coincide with the transients).

Costs no simulator evaluation.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import theilslopes

from tools.registry import ToolContext
from tools.schemas import DataQCInput, DataQCOutput
from tools.schemas.tools import QCSeries, Segment, SeriesQC

__all__ = ["data_qc_cost", "flatline_segments", "rolling_median", "run_data_qc", "spike_mask"]


def data_qc_cost(inp: DataQCInput, ctx: ToolContext) -> int:
    """No simulator evaluation."""
    return 0


def flatline_segments(t: np.ndarray, value: np.ndarray, min_samples: int) -> list[Segment]:
    """Runs of at least ``min_samples`` consecutive identical observed values."""
    segments: list[Segment] = []
    n = value.size
    i = 0
    while i < n:
        if not np.isfinite(value[i]):
            i += 1
            continue
        j = i
        while j + 1 < n and np.isfinite(value[j + 1]) and value[j + 1] == value[i]:
            j += 1
        if j - i + 1 >= min_samples:
            segments.append(Segment(start=float(t[i]), end=float(t[j]), n_samples=int(j - i + 1)))
        i = j + 1
    return segments


def rolling_median(x: np.ndarray, window: int) -> np.ndarray:
    """Centred rolling median of an observed series, NaN-aware, edges shrunk."""
    half = window // 2
    out = np.empty_like(x)
    for i in range(x.size):
        chunk = x[max(0, i - half) : i + half + 1]
        chunk = chunk[np.isfinite(chunk)]
        out[i] = np.median(chunk) if chunk.size else np.nan
    return out


def spike_mask(value: np.ndarray, window: int, multiplier: float) -> np.ndarray:
    """Samples whose robust z-score against the rolling median exceeds ``multiplier``."""
    med = rolling_median(value, window)
    resid = value - med
    finite = np.isfinite(resid)
    if finite.sum() < 3:
        return np.zeros(value.shape, dtype=bool)
    mad = np.median(np.abs(resid[finite] - np.median(resid[finite]))) * 1.4826
    if mad <= 0.0:
        # a series that is mostly constant: any departure is a spike relative to zero spread,
        # but a floor of the finite resolution keeps ties out of it
        mad = np.finfo(float).eps
    return finite & (np.abs(resid) > multiplier * mad)


def _drift(
    t: np.ndarray, value: np.ndarray, min_samples: int, snr: float
) -> tuple[float | None, float | None, bool]:
    obs = np.isfinite(value)
    if obs.sum() < min_samples:
        return None, None, False
    slope, intercept, _, _ = theilslopes(value[obs], t[obs])
    fitted = intercept + slope * t[obs]
    resid_sd = float(np.std(value[obs] - fitted, ddof=1))
    excursion = abs(slope) * (t[obs][-1] - t[obs][0])
    ratio = float(excursion / resid_sd) if resid_sd > 0 else float("inf") if excursion > 0 else 0.0
    return float(slope), ratio, bool(ratio > snr)


def _one(series: QCSeries, inp: DataQCInput, ctx: ToolContext) -> SeriesQC:
    conf = ctx.configs.data_qc
    t, value = series.t, series.value
    flags: list[str] = []
    unit_declared = bool(series.unit.strip())
    if not unit_declared:
        flags.append("no_unit")
    monotone = bool(t.size < 2 or np.all(np.diff(t) > 0))
    if not monotone:
        flags.append("timestamps_not_monotone")
    missing = ~np.isfinite(value)
    n_missing = int(missing.sum())
    longest = 0.0
    i = 0
    while i < t.size:
        if missing[i]:
            j = i
            while j + 1 < t.size and missing[j + 1]:
                j += 1
            span = float(t[j] - t[i]) + (float(np.median(np.diff(t))) if t.size > 1 else 0.0)
            longest = max(longest, span)
            i = j + 1
        else:
            i += 1

    min_flat = (
        conf.flatline_min_samples if inp.flatline_min_samples is None else inp.flatline_min_samples
    )
    flat = flatline_segments(t, value, min_flat)
    if flat:
        flags.append("flatline")
    mult = (
        conf.spike_mad_multiplier if inp.spike_mad_multiplier is None else inp.spike_mad_multiplier
    )
    spikes = spike_mask(value, conf.spike_window_samples, mult)
    if spikes.any():
        flags.append("spikes")
    slope, ratio, drift = _drift(t, value, conf.drift_min_samples, conf.drift_signal_to_noise)
    if drift:
        flags.append("drift")

    ratio_missing: float | None = None
    informative = False
    if inp.event_windows:
        inside = np.zeros(t.shape, dtype=bool)
        for w in inp.event_windows:
            inside |= (t >= w.start) & (t <= w.end)
        if inside.sum() >= conf.event_min_samples and (~inside).sum() >= conf.event_min_samples:
            rate_in = float(missing[inside].mean())
            rate_out = float(missing[~inside].mean())
            if rate_out > 0.0:
                ratio_missing = rate_in / rate_out
            else:
                ratio_missing = float("inf") if rate_in > 0.0 else 1.0
            informative = bool(ratio_missing > conf.event_missing_ratio)
            if informative:
                flags.append("informative_missingness")

    return SeriesQC(
        name=series.name,
        unit_declared=unit_declared,
        timestamps_monotone=monotone,
        n_samples=int(t.size),
        n_missing=n_missing,
        missing_fraction=float(n_missing / t.size) if t.size else 0.0,
        longest_gap_d=longest,
        flatlines=tuple(flat),
        spikes=t[spikes],
        drift_slope_per_d=slope,
        drift_signal_to_noise=ratio,
        drift_flag=drift,
        event_missing_ratio=ratio_missing,
        informative_missingness=informative,
        flags=tuple(flags),
    )


def run_data_qc(inp: DataQCInput, ctx: ToolContext) -> DataQCOutput:
    """Check every series."""
    results = tuple(_one(s, inp, ctx) for s in inp.series)
    flagged = tuple(r.name for r in results if r.flags)
    return DataQCOutput(results=results, flagged=flagged)
