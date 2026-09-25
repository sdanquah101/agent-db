"""``configs/eval.yaml``: every threshold, window, mapping and seed the scorer uses.

Nothing numerical lives in the scoring code (CLAUDE.md conventions); the bootstrap seed
is declared here (rule 4). The prior bounds of the fitted model's parameters are read from
``configs/tools/model.yaml`` through :func:`tools.config.load_fitted_model`, the same
declaration the registry's sampler uses for its box prior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CONFIG_DIR", "EVAL_CONFIG", "EvalConfig", "load_eval_config"]

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"
EVAL_CONFIG = CONFIG_DIR / "eval.yaml"

_Frac = Annotated[float, Field(ge=0.0, le=1.0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WindowsConfig(_Frozen):
    """The frozen hold-out window."""

    holdout_fraction: _Frac
    tolerance_d: Annotated[float, Field(ge=0.0)]


class PredictionConfig(_Frozen):
    """Family A."""

    channels: tuple[str, ...]
    coverage_levels: tuple[int, ...]
    interval_score_alpha: Annotated[float, Field(gt=0.0, lt=1.0)]
    validate_tool: str
    balance_tool: str
    recovery_levels: tuple[int, ...]
    truth_segment: Literal["last", "first"]


class ClaimSources(_Frozen):
    """Which tools return which claimed quantity."""

    by_value_key: dict[str, tuple[str, ...]]
    by_rule: dict[str, tuple[str, ...]]


class EarnedAbstention(_Frozen):
    """An abstention that counts only when the logs show ``tool`` failed (ruling D2).

    The evidence is the LAST logged call of ``tool`` that ran (a budget refusal runs
    nothing). It failed when its outcome, on the visible or the truth-side line, is one
    of ``failed_outcomes``, or its line's ``detail`` is one of ``failed_details`` (the
    registry notes a result that reports ``converged=False``). The workflow's own
    ``tool_failures`` are never evidence.
    """

    tool: str
    failed_outcomes: tuple[str, ...]
    failed_details: tuple[str, ...]


class AttributionConfig(_Frozen):
    """Family B."""

    partial_credit: Literal["jaccard"]
    prior_interval_mass: _Frac
    kinetic_group: str
    abstention_labels: tuple[str, ...]
    earned_abstentions: dict[str, EarnedAbstention] = {}
    unmapped_claim: Literal["unsupported", "supported"]
    claim_sources: ClaimSources


class EfficiencyConfig(_Frozen):
    """Family C."""

    clock_record: str
    uncertainty_reduction_clip: float


class ReliabilityConfig(_Frozen):
    """Family D."""

    invalid_action_prefixes: tuple[str, ...]
    verifier_rejection_names: tuple[str, ...]


class BootstrapConfig(_Frozen):
    """The §7 bootstrap."""

    n_resamples: Annotated[int, Field(ge=1)]
    interval: Annotated[float, Field(gt=0.0, lt=1.0)]
    seed: int


class AggregateConfig(_Frozen):
    """The aggregate table."""

    group_by: tuple[str, ...]
    bootstrap: BootstrapConfig


class DistinguishabilityConfig(_Frozen):
    """The admissible-set analysis (docs/distinguishability.md, method version 4)."""

    method_version: Annotated[int, Field(ge=1)]
    margin: Annotated[float, Field(gt=0.0)]
    sensitivity_margin: Annotated[float, Field(gt=0.0)]
    lr_alpha: _Frac
    n_alternatives: Annotated[int, Field(ge=1)]
    look_elsewhere: bool
    none_admissible_rate_min: _Frac
    sim_timeout_s: Annotated[float, Field(gt=0.0)]
    sensor_onset_every_d: Annotated[float, Field(gt=0.0)]
    flatline_durations_d: tuple[Annotated[float, Field(gt=0.0)], ...]
    delivery_every_d: Annotated[float, Field(gt=0.0)]
    delivery_multiples: tuple[float, ...]
    window_onset_every_d: Annotated[float, Field(gt=0.0)]
    mislabel_durations_d: tuple[Annotated[float, Field(gt=0.0)], ...]
    mislabel_concentrations: tuple[float, ...]
    moisture_durations_d: tuple[Annotated[float, Field(gt=0.0)], ...]
    moisture_changes: tuple[float, ...]
    biomass_multipliers: tuple[float, ...]
    parameter_onset_every_d: Annotated[float, Field(gt=0.0)]
    parameter_multipliers: tuple[float, ...]
    structural_min_visibility: Annotated[float, Field(ge=0.0)]


class EvalConfig(_Frozen):
    """``configs/eval.yaml``."""

    version: int
    windows: WindowsConfig
    prediction: PredictionConfig
    attribution: AttributionConfig
    distinguishability: DistinguishabilityConfig
    efficiency: EfficiencyConfig
    reliability: ReliabilityConfig
    aggregate: AggregateConfig


def load_eval_config(path: Path = EVAL_CONFIG) -> EvalConfig:
    """Parse and validate ``eval.yaml``.

    Raises:
        ValueError: If the file is not a YAML mapping.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return EvalConfig.model_validate(raw)
