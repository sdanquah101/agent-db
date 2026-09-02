"""Ingest the Muscatine WRRF daily file into unit-explicit records and §8 step-2 statistics.

The daily file (``anchor/raw/iowa-muscatine-wrrf/LABS-raw.csv``, ODC-By 1.0; see
``anchor/MANIFEST.json``) reports volumes in gallons, temperatures in degrees Fahrenheit,
biogas in cubic feet per minute and concentrations in mg/L or per cent w/w. Raw files
are never edited (``anchor/README.md``); every conversion happens here with the unit in
the field name (CLAUDE.md rule 6). The biogas column carries an explicit
"reference conditions unknown" flag: the data dictionary states neither temperature nor
pressure for the cubic feet.

The statistics computed here are the ones the influent generator's Plant B/C blocks
declare (``configs/influent/generator.yaml``): delivery-day fractions, weekday patterns,
lognormal parameters of the delivered volume on delivery days, lag-1 autocorrelations,
seasonal amplitudes from monthly means, and the spread and persistence of the feed
assays. ``tests/test_generator.py`` re-derives the configuration from this module so the
config cannot drift from the data it claims to summarise.

Pure functions over the parsed rows; the only I/O is :func:`load_daily`.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DAILY_FILE",
    "GAL_TO_M3",
    "SCADA_FILE",
    "AssayStatistics",
    "DailyRecord",
    "DeliveryStatistics",
    "ScadaChannelStatistics",
    "assay_statistics",
    "delivery_statistics",
    "load_daily",
    "scada_noise_statistics",
    "seasonal_amplitude_from_monthly_means",
]

DAILY_FILE = Path(__file__).resolve().parent / "raw" / "iowa-muscatine-wrrf" / "LABS-raw.csv"
SCADA_FILE = Path(__file__).resolve().parent / "raw" / "iowa-muscatine-wrrf" / "SCADA-raw.csv"
GAL_TO_M3 = 0.00378541
CFM_TO_M3_PER_D = 0.0283168 * 1440.0
MG_PER_L_TO_KG_PER_M3 = 1e-3


class DailyRecord(BaseModel):
    """One day of the Muscatine daily file with explicit units; missing values are None."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    date: dt.date
    twas_m3: float | None = Field(description="Thickened WAS fed, m3/d, plant total")
    ps_m3: float | None = Field(description="Primary sludge fed, m3/d, plant total")
    hsw_m3: float | None = Field(description="High-strength waste fed, m3/d, plant total")
    fog_m3: float | None = Field(description="FOG received, m3/d, plant total")
    dig1_T_K: float | None = Field(description="Digester 1 temperature, K")
    dig2_T_K: float | None = Field(description="Digester 2 temperature, K")
    dig1_pH: float | None = Field(description="Digester 1 pH, pH units")
    dig2_pH: float | None = Field(description="Digester 2 pH, pH units")
    srt_d: float | None = Field(description="Solids retention time as reported, d")
    hsw_vs_kg_kg: float | None = Field(description="HSW volatile solids, kg VS/kg wet (w/w)")
    hsw_cod_kg_m3: float | None = Field(description="HSW chemical oxygen demand, kg COD/m3")
    dig1_alk_kg_caco3_m3: float | None = Field(description="Digester 1 alkalinity, kg CaCO3/m3")
    dig2_alk_kg_caco3_m3: float | None = Field(description="Digester 2 alkalinity, kg CaCO3/m3")
    dig1_vfa_kg_m3: float | None = Field(description="Digester 1 total VFA, kg/m3 (as reported)")
    dig2_vfa_kg_m3: float | None = Field(description="Digester 2 total VFA, kg/m3 (as reported)")
    twas_vs_kg_kg: float | None = Field(description="TWAS volatile solids, kg VS/kg wet (w/w)")
    ps_vs_kg_kg: float | None = Field(description="PS volatile solids, kg VS/kg wet (w/w)")
    biogas_m3_d: float | None = Field(description="Biogas, m3/d at the meter's conditions")
    biogas_reference_conditions_known: bool = Field(
        default=False,
        description="False: the data dictionary states no T or P for the cubic feet",
    )


def _float(value: str) -> float | None:
    value = value.strip()
    if value in ("", "NA", "NaN"):
        return None
    return float(value)


def _scaled(value: str, factor: float) -> float | None:
    v = _float(value)
    return None if v is None else v * factor


def _degf_to_k(value: str) -> float | None:
    v = _float(value)
    return None if v is None else (v - 32.0) * 5.0 / 9.0 + 273.15


def load_daily(path: Path = DAILY_FILE) -> list[DailyRecord]:
    """Parse the daily file into unit-explicit records (the only I/O in this module)."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        out.append(
            DailyRecord(
                date=dt.date(int(r["Year"]), int(r["Month"]), int(r["Day"])),
                twas_m3=_scaled(r["V-TWAS_gal"], GAL_TO_M3),
                ps_m3=_scaled(r["V-PS_gal"], GAL_TO_M3),
                hsw_m3=_scaled(r["V-HSW_gal"], GAL_TO_M3),
                fog_m3=_scaled(r["FOG_gal"], GAL_TO_M3),
                dig1_T_K=_degf_to_k(r["Dig1-T_degF"]),
                dig2_T_K=_degf_to_k(r["Dig2-T_degF"]),
                dig1_pH=_float(r["Dig1-pH"]),
                dig2_pH=_float(r["Dig2-pH"]),
                srt_d=_float(r["SRT"]),
                hsw_vs_kg_kg=_scaled(r["HSW-VS_percent"], 0.01),
                hsw_cod_kg_m3=_scaled(r["HSW-COD_mgL"], MG_PER_L_TO_KG_PER_M3),
                dig1_alk_kg_caco3_m3=_scaled(r["Dig1-alk_mgL"], MG_PER_L_TO_KG_PER_M3),
                dig2_alk_kg_caco3_m3=_scaled(r["Dig2-alk_mgL"], MG_PER_L_TO_KG_PER_M3),
                dig1_vfa_kg_m3=_scaled(r["Dig1-VFA_mgL"], MG_PER_L_TO_KG_PER_M3),
                dig2_vfa_kg_m3=_scaled(r["Dig2-VFA_mgL"], MG_PER_L_TO_KG_PER_M3),
                twas_vs_kg_kg=_scaled(r["TWAS-VS_percent"], 0.01),
                ps_vs_kg_kg=_scaled(r["PS-VS_percent"], 0.01),
                biogas_m3_d=_scaled(r["Biogas"], CFM_TO_M3_PER_D),
            )
        )
    return out


def _series(records: Sequence[DailyRecord], field: str) -> np.ndarray:
    return np.array(
        [math.nan if getattr(r, field) is None else float(getattr(r, field)) for r in records]
    )


def _lag1(x: np.ndarray) -> float:
    """Lag-1 autocorrelation of a series with NaNs dropped (pairs of consecutive kept values)."""
    v = x[np.isfinite(x)]
    v = v - v.mean()
    return float((v[:-1] * v[1:]).sum() / (v * v).sum())


def seasonal_amplitude_from_monthly_means(
    values: np.ndarray, dates: Sequence[dt.date]
) -> tuple[float, float]:
    """Half the log ratio of the highest to the lowest monthly mean, and the peak day of year.

    Returns ``(amplitude, peak_doy)`` with the peak at mid-month of the highest mean.
    """
    months = np.array([d.month for d in dates])
    means = np.array([np.nanmean(values[months == m]) for m in range(1, 13)])
    amplitude = 0.5 * math.log(float(means.max()) / float(means.min()))
    peak_month = int(np.argmax(means)) + 1
    peak_doy = (dt.date(2021, peak_month, 15) - dt.date(2021, 1, 1)).days + 1
    return amplitude, float(peak_doy)


@dataclass(frozen=True)
class DeliveryStatistics:
    """Delivery pattern of one feed stream (plant total unless ``per_unit`` divides it)."""

    n_days: int
    zero_fraction: float
    """Fraction of days with no delivery, -."""
    zero_fraction_by_weekday: tuple[float, ...]
    """Fraction of no-delivery days per weekday (Monday first), -."""
    indicator_lag1: float
    """Lag-1 autocorrelation of the delivery indicator, -."""
    mean_zero_run_d: float
    """Mean length of a run of no-delivery days, d."""
    nonzero_median: float
    """Median amount on delivery days, m3/d (per modelled unit)."""
    log_sigma: float
    """sd of ln(amount) on delivery days, -."""
    amount_lag1: float
    """Lag-1 autocorrelation of the daily amount (zeros included), -."""
    seasonal_amplitude: float
    """Half the log ratio of the highest to the lowest monthly mean, -."""
    seasonal_peak_doy: float
    """Day of year of the highest monthly mean (mid-month), d."""


def delivery_statistics(
    records: Sequence[DailyRecord], field: str, per_unit: int = 1
) -> DeliveryStatistics:
    """Delivery-day and amount statistics of a feed volume column.

    Args:
        records: The parsed daily file.
        field: ``twas_m3``, ``ps_m3``, ``hsw_m3`` or ``fog_m3``.
        per_unit: Number of parallel digesters the plant total is divided by.
    """
    x = _series(records, field)
    x = np.nan_to_num(x, nan=0.0) / per_unit
    delivered = x > 0.0
    weekdays = np.array([r.date.weekday() for r in records])
    by_wd = tuple(float(np.mean(~delivered[weekdays == d])) for d in range(7))
    runs: list[int] = []
    run = 0
    for d in delivered:
        if not d:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    nz = x[delivered]
    amp, peak = seasonal_amplitude_from_monthly_means(x, [r.date for r in records])
    return DeliveryStatistics(
        n_days=int(x.size),
        zero_fraction=float(np.mean(~delivered)),
        zero_fraction_by_weekday=by_wd,
        indicator_lag1=_lag1(delivered.astype(float)) if (~delivered).any() else 0.0,
        mean_zero_run_d=float(np.mean(runs)) if runs else 0.0,
        nonzero_median=float(np.median(nz)),
        log_sigma=float(np.log(nz).std()),
        amount_lag1=_lag1(x),
        seasonal_amplitude=amp,
        seasonal_peak_doy=peak,
    )


@dataclass(frozen=True)
class AssayStatistics:
    """Spread and persistence of a measured concentration or solids column."""

    n: int
    median: float
    log_sigma: float
    """sd of ln(value) over the measured days, -."""
    lag1_log: float
    """Lag-1 autocorrelation of ln(value) over consecutive *measurements* (missing days
    dropped, so a pair may span a weekend), -."""
    measured_fraction_by_weekday: tuple[float, ...]
    """Fraction of days with a measurement per weekday (Monday first), -."""


def assay_statistics(records: Sequence[DailyRecord], field: str) -> AssayStatistics:
    """Statistics of an assay column (zeros and missing values are not measurements)."""
    x = _series(records, field)
    x = np.where(x > 0.0, x, np.nan)
    weekdays = np.array([r.date.weekday() for r in records])
    measured = np.isfinite(x)
    v = x[measured]
    return AssayStatistics(
        n=int(v.size),
        median=float(np.median(v)),
        log_sigma=float(np.log(v).std()),
        lag1_log=_lag1(np.log(x)),
        measured_fraction_by_weekday=tuple(
            float(np.mean(measured[weekdays == d])) for d in range(7)
        ),
    )


@dataclass(frozen=True)
class ScadaChannelStatistics:
    """Sensor statistics of one 1-minute SCADA channel (the observation model's anchor).

    The noise estimate is robust by construction: the first difference of a smooth signal
    plus white noise has standard deviation ``sqrt(2) sigma``, and the MAD of that
    difference is insensitive to the real process movement underneath and to outliers.
    """

    n: int
    mean: float
    """Mean of the finite samples, in the channel's own raw unit."""
    noise_sd: float
    """Robust 1-minute noise standard deviation, raw unit."""
    noise_cv: float
    """Noise standard deviation over the mean, -."""
    flatline_fraction: float
    """Fraction of samples inside a run of >= `flatline_min_samples` identical values, -."""
    longest_flatline_samples: int
    missing_fraction: float


def scada_noise_statistics(
    column: str, path: Path = SCADA_FILE, flatline_min_samples: int = 10
) -> ScadaChannelStatistics:
    """Noise, flatline and missingness of one SCADA channel, read in a single pass.

    The file is ~89 MB, so it is streamed rather than loaded; only the running quantities
    and the first differences are kept.

    Args:
        column: Column name, e.g. ``"D1_TEMPERATURE"`` or ``"Biogas"``.
        path: The SCADA file (git-ignored; fetch with ``python -m anchor.fetch``).
        flatline_min_samples: Run length at which a repeated value counts as a flatline.

    Returns:
        The channel's statistics.

    Raises:
        KeyError: If the column is not in the file.
    """
    values: list[float] = []
    n_rows = n_missing = 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or column not in reader.fieldnames:
            raise KeyError(f"{column!r} is not a column of {path.name}")
        for row in reader:
            n_rows += 1
            raw = (row.get(column) or "").strip()
            try:
                values.append(float(raw))
            except ValueError:
                n_missing += 1
    a = np.array(values, dtype=float)
    a = a[np.isfinite(a)]
    diff = np.diff(a)
    noise_sd = float(1.4826 * np.median(np.abs(diff - np.median(diff))) / math.sqrt(2.0))
    same = np.diff(a) == 0.0
    in_run = np.zeros(a.size, dtype=bool)
    longest = run = 0
    for i, flag in enumerate(same):
        run = run + 1 if flag else 0
        longest = max(longest, run + 1 if flag else 0)
        if run + 1 >= flatline_min_samples and flag:
            in_run[i - run : i + 2] = True
    mean = float(a.mean())
    return ScadaChannelStatistics(
        n=int(a.size),
        mean=mean,
        noise_sd=noise_sd,
        noise_cv=noise_sd / mean if mean else float("nan"),
        flatline_fraction=float(in_run.mean()),
        longest_flatline_samples=int(longest),
        missing_fraction=n_missing / n_rows if n_rows else 0.0,
    )
