"""Schemas and loaders for ``configs/tools/*.yaml``.

Every numerical setting a tool has -- trajectories, samples, multistarts, tolerances,
chain lengths, thresholds, prices -- lives in those files and nowhere in code (CLAUDE.md
conventions). Each file has a frozen Pydantic schema here so that a typo cannot silently
fall back to a default, and one loader, so that the tools and the tests read the same
numbers.

This module imports nothing from :mod:`sim`: it is shared with the workflow-side client
stub through :mod:`tools.schemas`, which needs only the shapes, never the files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "CONFIG_DIR",
    "AssayCatalogue",
    "AssaySpec",
    "DataQCConfig",
    "FiltersConfig",
    "FittedModelConfig",
    "FittersConfig",
    "GSAConfig",
    "IdentifiabilityConfig",
    "MCMCConfig",
    "RegistryConfig",
    "ResidualDiagConfig",
    "VOIConfig",
    "ValidateConfig",
    "load_assays",
    "load_data_qc",
    "load_filters",
    "load_fitted_model",
    "load_fitters",
    "load_gsa",
    "load_identifiability",
    "load_mass_balance",
    "load_mcmc",
    "load_registry",
    "load_residual_diag",
    "load_validate",
    "load_voi",
]

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs" / "tools"

_Pos = Annotated[float, Field(gt=0.0)]
_NonNeg = Annotated[float, Field(ge=0.0)]
_PosInt = Annotated[int, Field(gt=0)]
_Frac = Annotated[float, Field(ge=0.0, le=1.0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _mapping(path: Path) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping, got {type(raw).__name__}")
    return raw


# ------------------------------------------------------------------ registry


class RegistryConfig(_Frozen):
    """``registry.yaml``: the registry's own version and every tool's version string."""

    version: int
    registry_version: str
    tool_versions: dict[str, str]


def load_registry(path: Path = CONFIG_DIR / "registry.yaml") -> RegistryConfig:
    """Parse ``registry.yaml``."""
    return RegistryConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ the fitted model


class ParameterBounds(_Frozen):
    """Admissible range of one calibratable parameter, as a multiplier of its default."""

    lower: _Pos = Field(description="Lower bound of the multiplier, -")
    upper: _Pos = Field(description="Upper bound of the multiplier, -")
    group: Literal["kinetics", "stoichiometry", "physchem"] = Field(
        description="Which ADM1 parameter group the name belongs to"
    )

    @model_validator(mode="after")
    def _ordered(self) -> ParameterBounds:
        if self.lower >= self.upper:
            raise ValueError(f"lower {self.lower} must be below upper {self.upper}")
        if not self.lower <= 1.0 <= self.upper:
            raise ValueError("the default multiplier 1.0 must lie inside the bounds")
        return self


class FittedModelConfig(_Frozen):
    """``model.yaml``: the fitted ADM1 as the registry exposes it."""

    version: int
    parameters: dict[str, ParameterBounds]
    burn_in_days: _Pos = Field(description="Burn-in length before the record, d")
    burn_in_output_interval_d: _Pos = Field(description="Burn-in output spacing, d")
    reference_window_d: _Pos = Field(
        description="Window of the feed log the burn-in recipe is the mean of, d"
    )
    output_interval_d: _Pos = Field(description="Output spacing of the fitted model, d")
    initial_extension_states: dict[str, _NonNeg]
    influent_extension_states: dict[str, _NonNeg]
    outputs: tuple[str, ...] = Field(description="Observation channels the model reports")

    @model_validator(mode="after")
    def _outputs_unique(self) -> FittedModelConfig:
        if len(set(self.outputs)) != len(self.outputs):
            raise ValueError("outputs must be unique")
        if not self.parameters:
            raise ValueError("at least one calibratable parameter is needed")
        return self


def load_fitted_model(path: Path = CONFIG_DIR / "model.yaml") -> FittedModelConfig:
    """Parse ``model.yaml``."""
    return FittedModelConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ assays


class AssaySpec(_Frozen):
    """Price, turnaround and source channel of one requestable assay."""

    channel: str = Field(description="Truth channel the assay samples (sim.observation.channels)")
    sensor: str = Field(description="Lab sensor whose noise model applies (configs/observation)")
    unit_cost: _PosInt = Field(description="Cost in assay units of the scenario budget, -")
    turnaround_d: Annotated[int, Field(ge=0)] = Field(description="Report day minus sample day, d")
    companions: dict[str, str] = Field(
        default_factory=dict,
        description="Further channels returned with the same request, name -> lab sensor",
    )


class AssayCatalogue(_Frozen):
    """``assays.yaml``: what a workflow may request and at what price."""

    version: int
    assays: dict[str, AssaySpec]


def load_assays(path: Path = CONFIG_DIR / "assays.yaml") -> AssayCatalogue:
    """Parse ``assays.yaml``."""
    return AssayCatalogue.model_validate(_mapping(path))


# ------------------------------------------------------------------ data_qc


class DataQCConfig(_Frozen):
    """``data_qc.yaml``."""

    version: int
    flatline_min_samples: Annotated[int, Field(ge=2)]
    spike_mad_multiplier: _Pos
    spike_window_samples: Annotated[int, Field(ge=3)]
    drift_min_samples: Annotated[int, Field(ge=3)]
    drift_signal_to_noise: _Pos
    event_missing_ratio: _Pos
    event_min_samples: _PosInt

    @model_validator(mode="after")
    def _odd_window(self) -> DataQCConfig:
        if self.spike_window_samples % 2 == 0:
            raise ValueError("spike_window_samples must be odd")
        return self


def load_data_qc(path: Path = CONFIG_DIR / "data_qc.yaml") -> DataQCConfig:
    """Parse ``data_qc.yaml``."""
    return DataQCConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ mass_balance


class MassBalanceConfig(_Frozen):
    """``mass_balance.yaml``."""

    version: int
    cod_per_m3_ch4_stp: _Pos = Field(description="kg COD per m3 CH4 at 0 degC, 1 atm")
    kg_n_per_kmol: _Pos
    kg_caco3_per_keq: _Pos
    cod_closure_band: _Frac
    n_closure_expected: tuple[_Frac, _Frac]
    charge_drift_band: _Frac
    min_samples_per_window: _PosInt


def load_mass_balance(path: Path = CONFIG_DIR / "mass_balance.yaml") -> MassBalanceConfig:
    """Parse ``mass_balance.yaml``."""
    return MassBalanceConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ gsa


class MorrisConfig(_Frozen):
    """Morris screening ceilings."""

    n_trajectories: _PosInt
    n_levels: Annotated[int, Field(ge=2)]

    @model_validator(mode="after")
    def _even_levels(self) -> MorrisConfig:
        if self.n_levels % 2:
            raise ValueError("n_levels must be even (Morris 1991)")
        return self


class SobolConfig(_Frozen):
    """Sobol design ceilings."""

    n_samples: _PosInt
    second_order: bool
    bootstrap_resamples: Annotated[int, Field(ge=0)]
    confidence_level: Annotated[float, Field(gt=0.0, lt=1.0)]

    @model_validator(mode="after")
    def _power_of_two(self) -> SobolConfig:
        if self.n_samples & (self.n_samples - 1):
            raise ValueError("n_samples must be a power of two (scrambled Sobol sequence)")
        return self


class GSAConfig(_Frozen):
    """``gsa.yaml``."""

    version: int
    morris: MorrisConfig
    sobol: SobolConfig


def load_gsa(path: Path = CONFIG_DIR / "gsa.yaml") -> GSAConfig:
    """Parse ``gsa.yaml``."""
    return GSAConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ identifiability


class ProfileConfig(_Frozen):
    """Profile-likelihood ceilings and thresholds."""

    n_grid: Annotated[int, Field(ge=3)]
    n_starts: _PosInt
    max_nfev_per_start: _PosInt
    confidence_level: Annotated[float, Field(gt=0.0, lt=1.0)]
    flat_fraction: Annotated[float, Field(gt=0.0, lt=1.0)]
    ftol: _Pos
    xtol: _Pos
    gtol: _Pos


class FisherConfig(_Frozen):
    """Fisher-information settings."""

    relative_step: _Pos
    abs_step: _Pos
    rank_tolerance: _Pos
    condition_warning: _Pos


class IdentifiabilityConfig(_Frozen):
    """``identifiability.yaml``."""

    version: int
    profile: ProfileConfig
    fisher: FisherConfig


def load_identifiability(
    path: Path = CONFIG_DIR / "identifiability.yaml",
) -> IdentifiabilityConfig:
    """Parse ``identifiability.yaml``."""
    return IdentifiabilityConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ fitters


class LSQConfig(_Frozen):
    """Multistart least-squares ceilings."""

    n_starts: _PosInt
    max_nfev_per_start: _PosInt
    method: Literal["trf", "dogbox"]
    ftol: _Pos
    xtol: _Pos
    gtol: _Pos
    loss: Literal["linear", "soft_l1", "huber", "cauchy", "arctan"]


class DEConfig(_Frozen):
    """Differential-evolution ceilings."""

    popsize: _PosInt
    max_generations: _PosInt
    tol: _NonNeg
    mutation: tuple[float, float]
    recombination: _Frac
    strategy: str
    init: Literal["latinhypercube", "sobol", "halton", "random"]


class CMAESConfig(_Frozen):
    """CMA-ES ceilings."""

    max_evaluations: _PosInt
    sigma0_fraction: Annotated[float, Field(gt=0.0, le=1.0)]
    popsize: _PosInt | None
    tolfun: _Pos
    tolx: _Pos


class FittersConfig(_Frozen):
    """``fitters.yaml``."""

    version: int
    lsq: LSQConfig
    de: DEConfig
    cmaes: CMAESConfig


def load_fitters(path: Path = CONFIG_DIR / "fitters.yaml") -> FittersConfig:
    """Parse ``fitters.yaml``."""
    return FittersConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ mcmc


class InjectedFailureConfig(_Frozen):
    """How the Level-8 non-converged payload is built."""

    n_walkers: Annotated[int, Field(ge=2)]
    n_steps: Annotated[int, Field(ge=2)]
    spread_fraction: _Frac
    jitter_fraction: _Frac


class MCMCConfig(_Frozen):
    """``mcmc.yaml``."""

    version: int
    n_walkers: Annotated[int, Field(ge=4)]
    n_steps: Annotated[int, Field(ge=2)]
    burn_in_fraction: Annotated[float, Field(ge=0.0, lt=1.0)]
    thin: _PosInt
    max_samples_returned: _PosInt
    rhat_threshold: Annotated[float, Field(gt=1.0)]
    ess_floor: _PosInt
    initial_ball_fraction: Annotated[float, Field(gt=0.0, le=1.0)]
    ar1_rho_default: Annotated[float, Field(ge=-1.0, le=1.0)]
    heteroscedastic_cv_default: _NonNeg
    injected_failure: InjectedFailureConfig

    @model_validator(mode="after")
    def _even_walkers(self) -> MCMCConfig:
        if self.n_walkers % 2:
            raise ValueError("n_walkers must be even (emcee's stretch move)")
        return self


def load_mcmc(path: Path = CONFIG_DIR / "mcmc.yaml") -> MCMCConfig:
    """Parse ``mcmc.yaml``."""
    return MCMCConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ validate


class Constraint(_Frozen):
    """Admissible range of one predicted output."""

    lower: float | None = None
    upper: float | None = None


class ValidateConfig(_Frozen):
    """``validate.yaml``."""

    version: int
    coverage_levels: tuple[Annotated[float, Field(gt=0.0, lt=1.0)], ...]
    constraints: dict[str, Constraint]


def load_validate(path: Path = CONFIG_DIR / "validate.yaml") -> ValidateConfig:
    """Parse ``validate.yaml``."""
    return ValidateConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ residual_diag


class ResidualDiagConfig(_Frozen):
    """``residual_diag.yaml``."""

    version: int
    n_bins: Annotated[int, Field(ge=2)]
    min_per_bin: _PosInt
    structure_p_value: Annotated[float, Field(gt=0.0, lt=1.0)]
    autocorrelation_threshold: Annotated[float, Field(gt=0.0, lt=1.0)]
    runs_p_value: Annotated[float, Field(gt=0.0, lt=1.0)]


def load_residual_diag(path: Path = CONFIG_DIR / "residual_diag.yaml") -> ResidualDiagConfig:
    """Parse ``residual_diag.yaml``."""
    return ResidualDiagConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ filters


class EnKFConfig(_Frozen):
    """Ensemble Kalman filter ceilings."""

    n_ensemble: Annotated[int, Field(ge=2)]
    inflation: Annotated[float, Field(ge=1.0)]
    parameter_random_walk: _NonNeg


class MHEConfig(_Frozen):
    """Moving-horizon estimation ceilings."""

    horizon_steps: _PosInt
    max_nfev: _PosInt
    arrival_cost_weight: _NonNeg


class FiltersConfig(_Frozen):
    """``filters.yaml``."""

    version: int
    enkf: EnKFConfig
    mhe: MHEConfig


def load_filters(path: Path = CONFIG_DIR / "filters.yaml") -> FiltersConfig:
    """Parse ``filters.yaml``."""
    return FiltersConfig.model_validate(_mapping(path))


# ------------------------------------------------------------------ voi


class VOIConfig(_Frozen):
    """``voi.yaml``."""

    version: int
    n_outer: _PosInt
    n_inner: _PosInt


def load_voi(path: Path = CONFIG_DIR / "voi.yaml") -> VOIConfig:
    """Parse ``voi.yaml``."""
    return VOIConfig.model_validate(_mapping(path))
