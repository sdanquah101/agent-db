"""Schema and loader of ``configs/workflows/p0.yaml``, and what the runner hands the jail.

P0's every threshold, size and seed lives in that file (CLAUDE.md conventions; rule 4).
The jailed pipeline cannot read YAML (no ``yaml`` in the sandbox) nor the repository, so
the privileged runner writes the configuration into the sandbox as JSON, together with
the two declared things the pipeline needs that are not in the run's record: the
**declared instrument noise** of every sensor (``configs/observation/sensors.yaml``:
``cv``, ``sd_abs``, the drift bound and the drift sd, design §1.1) and the **declared
geometry** of every plant
(``configs/plants/``, the liquid volume and the set point). Both are the visible
contract of §6.1 and the benchmark card §4.1, the same for every cell, and carry nothing
of a run's truth, scenario or seeds (:func:`sandbox_config` is tested to hand over
nothing else).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["WORKFLOW_CONFIG_DIR", "P0Config", "load_p0", "sandbox_config"]

WORKFLOW_CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs" / "workflows"

_Pos = Annotated[float, Field(gt=0.0)]
_Frac = Annotated[float, Field(ge=0.0, le=1.0)]
_PosInt = Annotated[int, Field(gt=0)]
_NonNegInt = Annotated[int, Field(ge=0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Labels(_Frozen):
    """The six uncertainty classes as the evaluator spells them (§6.3)."""

    sensor: Literal["sensor"]
    influent: Literal["influent"]
    initial_state: Literal["state"]
    parameter: Literal["parameter"]
    structural: Literal["structural"]
    none: Literal["none"]


class Windows(_Frozen):
    """The calibration window and the frozen hold-out."""

    calibration_start_d: Annotated[float, Field(ge=0.0)]
    holdout_fraction: Annotated[float, Field(gt=0.0, lt=1.0)]


class Calibration(_Frozen):
    """Which sensors weight the objective and how."""

    channels: tuple[str, ...] = Field(min_length=1)
    primary_channel: str
    min_relative_sd: _Frac
    sd_floor_abs: _Pos

    @model_validator(mode="after")
    def _primary_in_channels(self) -> Calibration:
        if self.primary_channel not in self.channels:
            raise ValueError("primary_channel must be one of the calibration channels")
        if "temperature" in self.channels:
            raise ValueError("temperature never enters the objective (design §3.1)")
        return self


class QC(_Frozen):
    """The exclusion rules (design §3.1)."""

    event_load_quantile: Annotated[float, Field(gt=0.0, lt=1.0)]
    flatline_flag_d: _Pos
    drift_bound_factor: _Pos
    min_samples: _PosInt


class MassBalance(_Frozen):
    """Closure windows."""

    window_d: _Pos


class GSA(_Frozen):
    """Screening sizes."""

    morris_trajectories: _PosInt
    sobol_samples: _PosInt
    summary: Literal["mean", "final", "max", "min"]

    @model_validator(mode="after")
    def _power_of_two(self) -> GSA:
        if self.sobol_samples & (self.sobol_samples - 1):
            raise ValueError("sobol_samples must be a power of two")
        return self


class Screening(_Frozen):
    """Subset rules (design §3.2)."""

    morris_min_relative: _Frac
    morris_keep: _PosInt
    sobol_min_total: _Frac
    min_subset: _PosInt


class Identifiability(_Frozen):
    """Design §3.3."""

    max_relative_crlb: _Pos
    profile_grid: Annotated[int, Field(ge=3)]
    profile_starts: _PosInt


class Fit(_Frozen):
    """Design §3.4."""

    lsq_starts: _PosInt
    lsq_max_nfev_per_start: _PosInt
    de_popsize: _PosInt
    de_generations: _PosInt
    second_pass: bool


class MCMC(_Frozen):
    """Design §3.5."""

    walkers: Annotated[int, Field(ge=4)]
    steps: Annotated[int, Field(ge=2)]
    likelihood: Literal["gaussian", "ar1", "heteroscedastic"]

    @model_validator(mode="after")
    def _even(self) -> MCMC:
        if self.walkers % 2:
            raise ValueError("walkers must be even")
        return self


class Uncertainty(_Frozen):
    """Interval half-width in sd units."""

    z: _Pos


class Assays(_Frozen):
    """Design §3.6."""

    max_requests: _NonNegInt
    disagreement_z: _Pos
    preference: tuple[str, ...] = Field(min_length=1)


class Validate(_Frozen):
    """Design step 10."""

    ensemble_size: _NonNegInt


class Confidence(_Frozen):
    """Confidence by how many rules fired."""

    single: _Frac
    multiple: _Frac
    none: _Frac


class Attribution(_Frozen):
    """Design §3.7."""

    sensor_bias_z: _Pos
    sensor_step_z: _Pos
    clean_bias_z: _Pos
    balance_windows_min: _PosInt
    feed_eta2_min: _Frac
    structural_channels_min: _PosInt
    structural_rmse_z_min: _Pos
    parameter_step_z: _Pos
    parameter_channels_min: _PosInt
    step_day_tolerance_d: _Pos
    transient_d: _Pos
    state_bias_z: _Pos
    confidence: Confidence


class Plan(_Frozen):
    """Design §4."""

    eval_seconds_assumed: _Pos
    step_share: Annotated[float, Field(gt=0.0, le=1.0)]
    profile_share: Annotated[float, Field(gt=0.0, le=1.0)]
    profile_evals_per_point: _PosInt
    morris_min_trajectories: _PosInt
    sobol_min_samples: _PosInt
    de_min_generations: _PosInt
    mcmc_min_steps: Annotated[int, Field(ge=2)]
    ensemble_min: Annotated[int, Field(ge=2)]
    wall_clock_reserve_min: Annotated[float, Field(ge=0.0)]


class Seeds(_Frozen):
    """Rule 4: one declared seed per stochastic call."""

    morris: int
    sobol: int
    profile: int
    lsq: int
    de: int
    mcmc: int
    ensemble: int


class Runner(_Frozen):
    """What the privileged runner needs beyond the pipeline's own settings."""

    timeout_margin_min: Annotated[float, Field(ge=0.0)] = Field(
        description="Minutes past the cell's wall-clock allowance before the jail is killed"
    )


class P0Config(_Frozen):
    """``configs/workflows/p0.yaml``."""

    version: int
    workflow: Literal["p0"]
    workflow_version: str
    labels: Labels
    windows: Windows
    calibration: Calibration
    qc: QC
    mass_balance: MassBalance
    gsa: GSA
    screening: Screening
    identifiability: Identifiability
    fit: Fit
    mcmc: MCMC
    uncertainty: Uncertainty
    assays: Assays
    validation: Validate
    attribution: Attribution
    plan: Plan
    seeds: Seeds
    runner: Runner


def load_p0(path: Path = WORKFLOW_CONFIG_DIR / "p0.yaml") -> P0Config:
    """Parse and validate ``p0.yaml``."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return P0Config.model_validate(raw)


def sandbox_config(config: P0Config) -> dict[str, Any]:
    """What the runner writes into the sandbox as ``p0_config.json``.

    The configuration itself, plus the declared sensor noise (``cv``, ``sd_abs`` per
    sensor of ``configs/observation/sensors.yaml``) and the declared geometry of every
    plant (``V_liq_m3``, ``T_op_K``); nothing keyed by the run, so the same document goes
    into every cell's sandbox.
    """
    from sim.observation import load_observation_config
    from sim.plants import declared_geometry, load_plant_config

    observation = load_observation_config()
    noise = {}
    for name, spec in observation.sensors.items():
        entry: dict[str, float | None] = {
            "cv": float(spec.noise.cv),
            "sd_abs": float(spec.noise.sd_abs),
            "drift_bound": None,
            "drift_sd_per_sqrt_d": None,
        }
        if spec.drift is not None:
            entry["drift_bound"] = float(spec.drift.bound)
            entry["drift_sd_per_sqrt_d"] = float(spec.drift.sd_per_sqrt_d)
        noise[name] = entry
    geometry = {}
    for plant_id in ("A", "B", "C"):
        g = declared_geometry(load_plant_config(plant_id))
        geometry[plant_id] = {"V_liq_m3": float(g.V_liq), "T_op_K": float(g.T_op)}
    payload = config.model_dump(mode="json")
    payload["sensor_noise"] = noise
    payload["plant_geometry"] = geometry
    return payload
