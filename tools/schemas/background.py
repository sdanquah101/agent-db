"""The declared background: the null band of a clean record, per plant and tier.

Decision 1 of ``docs/decisions.md`` (2026-09-30): the benchmark publishes, per plant and
per tier, what a **clean** record on that plant looks like under the tools' own fitted
model -- the COD-closure band and the per-channel standardised-residual envelope (mean and
RMS of ``(observed - predicted) / declared sd``) at the default parameters and after a
declared screened fit -- computed offline from seeded clean generator runs and served by
the registry tool ``declared_background``. A workflow reads it the way it reads the
declared instrument noise: as the reference a fault has to exceed.

These models are shared with the workflow-side stub, so this module imports only the
standard library, numpy and pydantic. Every numeric field states its unit (rule 6): the
``z`` quantities are dimensionless multiples of the declared measurement sd, closures are
fractions of the COD (or TKN) fed, and counts are counts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from tools.schemas.base import ToolInput, ToolOutput, Window

__all__ = [
    "BackgroundProcedure",
    "BandRecord",
    "BandStat",
    "ChannelBand",
    "DeclaredBackgroundInput",
    "DeclaredBackgroundOutput",
    "IntBand",
    "ZBand",
]

Plant = Literal["A", "B", "C"]
Tier = Literal["A", "B", "C"]


class BandStat(ToolOutput):
    """The spread of one quantity over the clean runs that define the band."""

    n: int = Field(description="Runs (or windows) the statistic is over, count")
    mean: float = Field(description="Mean over the runs, in the quantity's unit")
    sd: float | None = Field(description="Sample sd over the runs; None below two runs")
    min: float = Field(description="Smallest value seen on a clean run")
    max: float = Field(description="Largest value seen on a clean run")


class IntBand(ToolOutput):
    """The spread of a count over the clean runs."""

    n: int = Field(description="Runs the statistic is over, count")
    mean: float = Field(description="Mean count over the runs")
    min: int = Field(description="Smallest count seen on a clean run")
    max: int = Field(description="Largest count seen on a clean run")


class ZBand(ToolOutput):
    """One channel's standardised residual over the clean runs, at one parameter vector."""

    mean_z: BandStat = Field(
        description="Mean of (observed - predicted) / declared sd over the calibration "
        "window, per run; dimensionless (multiples of the declared measurement sd)"
    )
    rms_z: BandStat = Field(
        description="Root mean square of (observed - predicted) / declared sd over the "
        "calibration window, per run; dimensionless"
    )


class ChannelBand(ToolOutput):
    """The residual envelope of one sensor's channel: at the defaults and after the fit."""

    channel: str = Field(description="The model output the sensor observes")
    unit: str = Field(description="Unit of the observed channel (rule 6)")
    in_objective: bool = Field(
        description="Whether the sensor weighted the declared screened fit (P0's "
        "calibration channels; temperature never)"
    )
    n_samples: IntBand = Field(description="Observed samples in the calibration window")
    at_defaults: ZBand = Field(description="Residual at the default parameter vector (1.0)")
    after_fit: ZBand = Field(description="Residual at the optimum of the declared screened fit")


class BackgroundProcedure(ToolOutput):
    """How the band was computed: every size, window and seed, declared."""

    scenario: str = Field(description="The clean Level-0 row the records are generated from")
    seeds: tuple[int, ...] = Field(
        description="Base seeds of the clean generator runs; disjoint from the library's"
    )
    plant_a_baselines: tuple[str, ...] = Field(
        description="The declared Plant A community states the band pools (its union)"
    )
    calibration_start_d: float = Field(description="Calibration window start, d")
    holdout_fraction: float = Field(
        description="The frozen hold-out fraction; the band reads [start, T (1 - f)] only, -"
    )
    balance_window_d: float = Field(description="Width of each COD-closure window, d")
    min_relative_sd: float = Field(
        description="Floor on a sample's sd as a fraction of the series' median |value|, -"
    )
    sd_floor_abs: float = Field(description="Absolute floor on a sample's sd, channel unit")
    objective_channels: tuple[str, ...] = Field(
        description="Sensors that weight the fit when the tier carries them"
    )
    screening: str = Field(description="How the fitted subset was chosen")
    morris_trajectories: int = Field(description="Morris trajectories of the screen, count")
    morris_min_relative: float = Field(
        description="mu* over the largest mu* of an output a parameter needs to stay, -"
    )
    morris_seed: int = Field(description="Seed of the Morris trajectories (rule 4)")
    gsa_summary: str = Field(description="The scalar of each output the screen is on")
    max_relative_crlb: float = Field(
        description="CRLB sd over the bound width above which a parameter is dropped, -"
    )
    subset_max: int = Field(description="Cap on the fitted subset, count")
    subset_min: int = Field(description="Floor on the fitted subset, count")
    fit: str = Field(description="The fitter")
    lsq_starts: int = Field(description="Multistarts of the fit, count")
    lsq_max_nfev_per_start: int = Field(description="Evaluations per start, count")
    fit_seed: int = Field(description="Seed handed to the fitter (rule 4)")
    budget_simulator_evals: int = Field(description="Evaluation budget of one background run")
    budget_wall_clock_min: float = Field(description="Wall-clock budget of one run, min")


class BandRecord(ToolOutput):
    """The band of one (plant, tier): balance closure and the per-channel envelopes."""

    n_runs: int = Field(description="Clean generator runs the band is over, count")
    horizon_d: float = Field(description="Record length of those runs, d (the plant's)")
    calibration_window: Window = Field(description="The window every statistic is over, d")
    balance_window_d: float = Field(description="Width of each closure window, d")
    n_cod_windows: int = Field(description="Closure windows inside the calibration window")
    n_cod_evaluable: IntBand | None = Field(
        description="Windows with a gas, CH4 and COD record (None: the tier has none)"
    )
    n_cod_inadmissible: IntBand | None = Field(
        description="Windows whose COD closure left the tool's admissible band, per run"
    )
    cod_closure: BandStat | None = Field(
        description="Per-run mean COD closure (in - out) / in over the evaluable windows, -"
    )
    cod_closure_worst: BandStat | None = Field(
        description="Per-run closure of the window with the largest |closure|, sign kept, -"
    )
    cod_closure_windows: BandStat | None = Field(
        description="Every evaluable window's COD closure, pooled over the runs, -"
    )
    n_closure: BandStat | None = Field(
        description="Per-run mean N closure (TKN in - TAN out) / TKN in, -"
    )
    charge_drift: BandStat | None = Field(
        description="Relative range of the implied strong-ion difference across windows, -"
    )
    charge_consistent_fraction: float | None = Field(
        description="Share of the runs the tool called charge-consistent, -"
    )
    n_fitted: IntBand = Field(description="Parameters the screened fit moved, per run")
    fitted_parameters: dict[str, int] = Field(
        description="How many runs each parameter was in the fitted subset of"
    )
    fit_at_bound_fraction: float = Field(
        description="Share of the runs whose fit ended with a parameter within 1 % of a bound"
    )
    channels: dict[str, ChannelBand] = Field(
        description="Sensor name -> its residual envelope at the defaults and after the fit"
    )


class DeclaredBackgroundInput(ToolInput):
    """Which plant and tier to read the declared background of. Costs no evaluation."""

    plant: Plant = Field(description="The declared plant of the run's redacted manifest")
    tier: Tier = Field(description="The instrumentation tier of the run's redacted manifest")


class DeclaredBackgroundOutput(BandRecord):
    """The declared background of a (plant, tier), with the procedure that produced it.

    Per plant and tier only, never per cell or scenario: the same answer on every run of
    that plant at that tier (rule 1; decision 1 of 2026-09-30).
    """

    plant: Plant
    tier: Tier
    procedure: BackgroundProcedure
    units: dict[str, str] = Field(description="Unit of every quantity in the band (rule 6)")
