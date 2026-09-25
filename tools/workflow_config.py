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

__all__ = [
    "WORKFLOW_CONFIG_DIR",
    "ModelSettings",
    "P0Config",
    "P1Config",
    "check_prompt_hash",
    "load_p0",
    "load_p1",
    "load_prompts",
    "load_workflow_config",
    "prompt_digest",
    "sandbox_config",
]

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


# ------------------------------------------------------------------ P1


class P1Calibration(_Frozen):
    """How the harness weights a sample of an observed series (the P0 convention)."""

    min_relative_sd: _Frac
    sd_floor_abs: _Pos


class P1Defaults(_Frozen):
    """What a harness-built tool argument takes when the agent names none."""

    event_load_quantile: Annotated[float, Field(gt=0.0, lt=1.0)]
    balance_window_d: _Pos
    transient_d: _Pos


class Retry(_Frozen):
    """The retry policy of one model turn (every attempt is logged)."""

    max_attempts: _PosInt
    backoff_s: Annotated[float, Field(ge=0.0)]
    max_backoff_s: Annotated[float, Field(ge=0.0)]


class Pricing(_Frozen):
    """USD per million tokens, for reporting the cost of a run (never read by the agent)."""

    input: Annotated[float, Field(ge=0.0)]
    output: Annotated[float, Field(ge=0.0)]
    cache_write: Annotated[float, Field(ge=0.0)]
    cache_read: Annotated[float, Field(ge=0.0)]


class ModelSettings(_Frozen):
    """The model and how it is called: privileged side only (``tools.llm``)."""

    provider: Literal["anthropic", "openai"]
    model_id: str = Field(min_length=1)
    max_tokens: _PosInt
    temperature: Annotated[float, Field(ge=0.0, le=1.0)] | None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None
    prompt_caching: bool
    request_timeout_s: _Pos
    retry: Retry
    pricing_usd_per_mtok: Pricing | None = Field(
        description="USD per million tokens; null when no published price is recorded "
        "(the cost is then reported as unknown, never guessed)"
    )


class Loop(_Frozen):
    """The agent loop's limits."""

    max_turns: _PosInt
    max_tool_calls: _PosInt
    max_total_tokens: _PosInt
    wall_clock_reserve_min: Annotated[float, Field(ge=0.0)]
    conclude_grace_turns: _PosInt
    max_points_shown: _PosInt
    array_preview: _PosInt


class P1Uncertainty(_Frozen):
    """How a reported interval is checked against the call that produced it."""

    z: _Pos
    rel_tolerance: Annotated[float, Field(gt=0.0, lt=0.1)]


class P1Seeds(_Frozen):
    """Rule 4: a stochastic call's seed is ``base`` plus its registry call index."""

    base: int


class Prompts(_Frozen):
    """Prompt files, relative to ``configs/workflows/``."""

    system: str
    task: str


class P1Config(_Frozen):
    """``configs/workflows/p1.yaml``."""

    version: int
    workflow: Literal["p1"]
    workflow_version: str
    labels: Labels
    windows: Windows
    calibration: P1Calibration
    defaults: P1Defaults
    model: ModelSettings
    loop: Loop
    uncertainty: P1Uncertainty
    seeds: P1Seeds
    evidence_keys: dict[str, tuple[str, ...]] = Field(min_length=1)
    prompts: Prompts
    prompt_sha256: str = Field(
        default="",
        description="The prompts' fingerprint (prompt_digest), committed at the freeze; "
        "empty until then. When set, the runner refuses prompts that do not match it",
    )
    runner: Runner


def load_p1(path: Path = WORKFLOW_CONFIG_DIR / "p1.yaml") -> P1Config:
    """Parse and validate ``p1.yaml``."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return P1Config.model_validate(raw)


def load_prompts(config: P1Config, root: Path = WORKFLOW_CONFIG_DIR) -> dict[str, str]:
    """The prompt texts P1's configuration names, by role (``system``, ``task``)."""
    return {
        role: (Path(root) / rel).read_text(encoding="utf-8")
        for role, rel in config.prompts.model_dump().items()
    }


def prompt_digest(prompts: dict[str, str]) -> str:
    """The fingerprint of the prompt texts: sha256 of their sorted-key JSON."""
    import hashlib
    import json

    blob = json.dumps(prompts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def check_prompt_hash(config: P1Config) -> str:
    """The prompts' fingerprint, refused when a committed one does not match it.

    Raises:
        ValueError: If ``prompt_sha256`` is set and differs from the prompts on disk.
    """
    digest = prompt_digest(load_prompts(config))
    if config.prompt_sha256 and config.prompt_sha256 != digest:
        raise ValueError(
            f"the prompts do not match the committed prompt_sha256 ({config.prompt_sha256}); "
            f"they hash to {digest}: a post-freeze prompt change invalidates the runs"
        )
    return digest


def load_workflow_config(workflow: str, path: Path | None = None) -> P0Config | P1Config:
    """The configuration of a workflow by name (``p0`` or ``p1``)."""
    loaders = {"p0": load_p0, "p1": load_p1}
    if workflow not in loaders:
        raise KeyError(f"no configuration schema for workflow {workflow!r}")
    return loaders[workflow]() if path is None else loaders[workflow](path)


def sandbox_config(config: P0Config | P1Config) -> dict[str, Any]:
    """What the runner writes into the sandbox as ``<workflow>_config.json``.

    The configuration itself, plus the declared sensor noise (``cv``, ``sd_abs`` per
    sensor of ``configs/observation/sensors.yaml``) and the declared geometry of every
    plant (``V_liq_m3``, ``T_op_K``), and the controlled abstention vocabulary (term ->
    one-line meaning, ``configs/abstentions.yaml``); nothing keyed by the run, so the same
    document goes into every cell's sandbox. For P1 the ``model`` block stays on the
    privileged side (the agent does not choose its model or sampling) and the prompt
    texts are added under ``prompts`` and the requestable assays' price list under
    ``assay_catalogue``.
    """
    from sim.observation import load_observation_config
    from sim.plants import declared_geometry, load_plant_config
    from state.abstentions import abstention_vocabulary

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
    if isinstance(config, P1Config):
        from tools.config import load_assays

        del payload["model"]
        payload["prompts"] = load_prompts(config)
        # the public price list of requestable assays (proposal §6.4: "at a declared cost
        # and turnaround"), which P0 carries as its own preference list
        payload["assay_catalogue"] = {
            name: {
                "channel": spec.channel,
                "unit_cost": int(spec.unit_cost),
                "turnaround_d": float(spec.turnaround_d),
            }
            for name, spec in load_assays().assays.items()
        }
    payload["sensor_noise"] = noise
    payload["plant_geometry"] = geometry
    payload["abstentions"] = abstention_vocabulary()
    return payload
