"""Ingest the Muscatine WRRF files into unit-explicit records and §8 step-2 statistics.

The daily file (``anchor/raw/iowa-muscatine-wrrf/LABS-raw.csv``, ODC-By 1.0; see
``anchor/MANIFEST.json``) reports volumes in gallons, temperatures in degrees Fahrenheit,
biogas in cubic feet per minute and concentrations in mg/L or per cent w/w. Raw files
are never edited (``anchor/README.md``); every conversion happens here with the unit in
the field name (CLAUDE.md rule 6). The biogas column carries an explicit
"reference conditions unknown" flag: the data dictionary states neither temperature nor
pressure for the cubic feet.

The daily statistics computed here are the ones the influent generator's Plant B/C blocks
declare (``configs/influent/generator.yaml``): delivery-day fractions, weekday patterns,
lognormal parameters of the delivered volume on delivery days, lag-1 autocorrelations,
seasonal amplitudes from monthly means, and the spread and persistence of the feed
assays. ``tests/test_generator.py`` re-derives the configuration from this module so the
config cannot drift from the data it claims to summarise.

The **one-minute SCADA file** (``SCADA-raw.csv``, 500,400 rows, 2022-03-18 to
2023-02-28, 88.8 MB and therefore git-ignored) carries what the *observation model*
needs (proposal §6.1): the high-frequency scatter of the digester-temperature and
biogas-flow sensors, how often those channels flatline or sit at an instrument limit,
and the rate and length of the dropouts in the record.
:func:`load_scada`, :func:`sensor_noise_statistics` and :func:`dropout_statistics`
compute them; ``scripts/muscatine_scada_observation.py`` writes them to
``anchor/derived/muscatine-scada-sensor-statistics.json`` together with a committed
60-day extract (``anchor/derived/muscatine-scada-window.csv.gz``), and
``tests/test_observe.py`` re-derives the extract's statistics offline (decisions log,
2026-09-02, "SCADA statistics: a committed window plus a recorded full-year JSON").

Pure functions over the parsed rows; the only I/O is :func:`load_daily` and
:func:`load_scada`.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DAILY_FILE",
    "GAL_TO_M3",
    "SCADA_FILE",
    "SCADA_WINDOW_FILE",
    "AssayStatistics",
    "DailyRecord",
    "DeliveryStatistics",
    "DropoutStatistics",
    "ScadaSeries",
    "SensorNoiseStatistics",
    "assay_statistics",
    "delivery_statistics",
    "dropout_statistics",
    "load_daily",
    "load_scada",
    "seasonal_amplitude_from_monthly_means",
    "sensor_noise_statistics",
]

_RAW_DIR = Path(__file__).resolve().parent / "raw" / "iowa-muscatine-wrrf"
DAILY_FILE = _RAW_DIR / "LABS-raw.csv"
SCADA_FILE = _RAW_DIR / "SCADA-raw.csv"
SCADA_WINDOW_FILE = Path(__file__).resolve().parent / "derived" / "muscatine-scada-window.csv.gz"
GAL_TO_M3 = 0.00378541
CFM_TO_M3_PER_D = 0.0283168 * 1440.0
MG_PER_L_TO_KG_PER_M3 = 1e-3
DEGF_TO_K_STEP = 5.0 / 9.0
"""Kelvin per degree Fahrenheit — the factor for *differences* and standard deviations."""


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


# ------------------------------------------------------- the 1-minute SCADA file


DEGF_TO_K_OFFSET = 273.15 - 32.0 * DEGF_TO_K_STEP
"""Kelvin at 0 degrees Fahrenheit: ``K = F * DEGF_TO_K_STEP + DEGF_TO_K_OFFSET``."""


@dataclass(frozen=True)
class ScadaColumn:
    """How one SCADA column is converted to SI and what its instrument limits are."""

    name: str
    """Name of the converted series (carries its unit, CLAUDE.md rule 6)."""
    scale: float
    offset: float
    unit: str
    limits_raw: tuple[float, float]
    """The "acceptable values" of the provider's data dictionary, in the file's unit."""

    def convert(self, values: np.ndarray) -> np.ndarray:
        """Convert a raw column to :attr:`unit`."""
        return values * self.scale + self.offset

    @property
    def limits(self) -> tuple[float, float]:
        """The instrument limits in :attr:`unit`."""
        low, high = self.limits_raw
        return low * self.scale + self.offset, high * self.scale + self.offset


#: SCADA columns the observation model is anchored to (``SCADA-data-dictionary.csv``).
SCADA_COLUMNS: dict[str, ScadaColumn] = {
    "D1_TEMPERATURE": ScadaColumn("dig1_T_K", DEGF_TO_K_STEP, DEGF_TO_K_OFFSET, "K", (85.0, 150.0)),
    "D2_TEMPERATURE": ScadaColumn("dig2_T_K", DEGF_TO_K_STEP, DEGF_TO_K_OFFSET, "K", (85.0, 150.0)),
    "Biogas": ScadaColumn(
        "biogas_m3_d",
        CFM_TO_M3_PER_D,
        0.0,
        "m3/d (reference conditions unknown)",
        (0.0, 1120.0),
    ),
}


@dataclass(frozen=True)
class ScadaSeries:
    """The SCADA log as sorted minute-resolution series in SI units.

    The file is **not** in chronological order (the 2023 block precedes 2022) and has
    whole rows missing where the providers deleted assumed power surges, so ``minute``
    is the sorted time index and is not contiguous.
    """

    start: dt.datetime
    """Timestamp of the first row (local plant time, as recorded)."""
    minute: np.ndarray
    """Minutes since ``start``, strictly increasing, with gaps where rows are absent."""
    columns: dict[str, np.ndarray]
    """Converted series keyed by the name in :data:`SCADA_COLUMNS`."""
    units: dict[str, str]
    """Unit of every entry of :attr:`columns` (CLAUDE.md rule 6)."""
    limits: dict[str, tuple[float, float]]
    """Instrument limits from the provider's data dictionary, in the converted unit."""

    @property
    def span_d(self) -> float:
        """Time from the first to the last row, d."""
        return float(self.minute[-1] - self.minute[0]) / 1440.0


@contextmanager
def _open_text(path: Path) -> Iterator[TextIO]:
    """Open a plain or gzipped CSV as text."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as fh:
            yield fh
    else:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            yield fh


def load_scada(path: Path = SCADA_FILE) -> ScadaSeries:
    """Parse the 1-minute SCADA file (or the committed window extract) into SI series.

    Only the columns of :data:`SCADA_COLUMNS` that the file carries are returned;
    temperatures become kelvin and the biogas flow m3/d at the meter's own, unstated
    reference conditions (the unit string says so).

    Args:
        path: ``SCADA-raw.csv`` or a ``.csv.gz`` extract with the same column names.

    Returns:
        The sorted series.

    Raises:
        ValueError: If the file carries none of the known columns.
    """
    with _open_text(path) as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)
    index = {name: i for i, name in enumerate(header)}
    present = [c for c in SCADA_COLUMNS if c in index]
    if not present:
        raise ValueError(f"{path}: none of {sorted(SCADA_COLUMNS)} is present")
    stamps = np.array(
        [dt.datetime.strptime(r[index["Timestamp"]], "%Y-%m-%d %H:%M:%S") for r in rows]
    )
    order = np.argsort(stamps, kind="stable")
    stamps = stamps[order]
    start = stamps[0]
    minute = np.array([(s - start).total_seconds() / 60.0 for s in stamps])
    columns: dict[str, np.ndarray] = {}
    units: dict[str, str] = {}
    limits: dict[str, tuple[float, float]] = {}
    for column in present:
        spec = SCADA_COLUMNS[column]
        col = index[column]
        raw = np.array(
            [math.nan if _float(r[col]) is None else float(r[col]) for r in rows], dtype=float
        )
        columns[spec.name] = spec.convert(raw[order])
        units[spec.name] = spec.unit
        limits[spec.name] = spec.limits
    return ScadaSeries(start=start, minute=minute, columns=columns, units=units, limits=limits)


@dataclass(frozen=True)
class SensorNoiseStatistics:
    """High-frequency behaviour of one SCADA channel (the observation model's anchor)."""

    channel: str
    unit: str
    n_samples: int
    median: float
    """Median of the channel over the record, in ``unit``."""
    robust_sd: float
    """Measurement noise, in ``unit``: ``1.4826 MAD(diff) / sqrt(2)`` over consecutive
    one-minute samples. The robust scale of the one-minute differences rejects the real
    process excursions that inflate the plain sd, and dividing by sqrt(2) turns the
    difference of two independent readings back into one reading's sd."""
    relative_sd: float
    """``robust_sd / median``, -."""
    resolution: float
    """Smallest non-zero step between consecutive samples, in ``unit`` (the recorded
    quantisation of the channel)."""
    repeat_fraction: float
    """Fraction of consecutive one-minute pairs with an identical value, -."""
    flatline_episodes_per_d: float
    """Rate of runs of identical values at least ``min_run_min`` long, 1/d."""
    flatline_mean_duration_min: float
    """Mean length of those runs, min."""
    at_lower_limit_fraction: float
    """Fraction of samples at or below the instrument's lower limit, -."""
    at_upper_limit_fraction: float
    """Fraction of samples at or above the instrument's upper limit, -."""


def _runs_of_true(flags: np.ndarray) -> np.ndarray:
    """Lengths of the maximal runs of ``True`` in a boolean array."""
    runs: list[int] = []
    current = 0
    for flag in flags:
        if flag:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return np.array(runs, dtype=float)


def sensor_noise_statistics(
    series: ScadaSeries, channel: str, min_run_min: int = 10
) -> SensorNoiseStatistics:
    """Noise, quantisation, flatlining and limit-hitting of one SCADA channel.

    Only consecutive samples one minute apart enter the difference statistics, so the
    record's dropouts do not masquerade as noise.

    Args:
        series: The parsed SCADA series.
        channel: Key of :attr:`ScadaSeries.columns`.
        min_run_min: Shortest run of identical values counted as a flatline episode, min.

    Returns:
        The statistics of that channel.
    """
    values = series.columns[channel]
    finite = np.isfinite(values)
    adjacent = (np.diff(series.minute) == 1.0) & finite[:-1] & finite[1:]
    steps = np.diff(values)[adjacent]
    mad = float(np.median(np.abs(steps - np.median(steps))))
    non_zero = np.abs(steps[steps != 0.0])
    same = steps == 0.0
    runs = _runs_of_true(same) + 1.0  # a run of k equal differences is k+1 equal samples
    long_runs = runs[runs >= min_run_min]
    low, high = series.limits[channel]
    good = values[finite]
    return SensorNoiseStatistics(
        channel=channel,
        unit=series.units[channel],
        n_samples=int(good.size),
        median=float(np.median(good)),
        robust_sd=1.4826 * mad / math.sqrt(2.0),
        relative_sd=1.4826 * mad / math.sqrt(2.0) / float(np.median(good)),
        resolution=float(non_zero.min()) if non_zero.size else 0.0,
        repeat_fraction=float(same.mean()),
        flatline_episodes_per_d=float(long_runs.size) / series.span_d,
        flatline_mean_duration_min=float(long_runs.mean()) if long_runs.size else 0.0,
        at_lower_limit_fraction=float(np.mean(good <= low)),
        at_upper_limit_fraction=float(np.mean(good >= high)),
    )


@dataclass(frozen=True)
class DropoutStatistics:
    """Gaps in the SCADA record: how often the log loses samples and for how long.

    The providers deleted 485 rows "assumed to be power surges" (``README.txt``), so
    these are the dropouts of the *published* record; the plant's own logger may have
    lost more. The observation model uses them as the base missingness of a continuously
    logged channel and says so in ``configs/observe/observation.yaml``.
    """

    n_rows: int
    span_d: float
    n_gaps: int
    gaps_per_d: float
    missing_minute_fraction: float
    """Missing minutes divided by the minutes the record spans, -."""
    median_gap_min: float
    p90_gap_min: float
    max_gap_min: float


def dropout_statistics(series: ScadaSeries) -> DropoutStatistics:
    """Rate and length distribution of the gaps between consecutive SCADA rows."""
    steps = np.diff(series.minute)
    gaps = steps[steps > 1.0] - 1.0
    span_min = float(series.minute[-1] - series.minute[0]) + 1.0
    return DropoutStatistics(
        n_rows=int(series.minute.size),
        span_d=series.span_d,
        n_gaps=int(gaps.size),
        gaps_per_d=float(gaps.size) / series.span_d,
        missing_minute_fraction=float(gaps.sum()) / span_min,
        median_gap_min=float(np.median(gaps)) if gaps.size else 0.0,
        p90_gap_min=float(np.percentile(gaps, 90)) if gaps.size else 0.0,
        max_gap_min=float(gaps.max()) if gaps.size else 0.0,
    )
