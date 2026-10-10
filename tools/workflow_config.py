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
    "Frozen",
    "ModelSettings",
    "P0Config",
    "P1Config",
    "P2Config",
    "check_brief_hash",
    "check_frozen",
    "check_prompt_hash",
    "load_p0",
    "load_p1",
    "load_p2",
    "load_p2_templates",
    "load_prompts",
    "load_workflow_config",
    "model_system_text",
    "prompt_digest",
    "sandbox_config",
    "system_digest",
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
    force_include: tuple[str, ...] = Field(
        default=(),
        description="Parameters added to the approved subset after the Fisher step, so "
        "they are always fitted. OFF (empty) in configs/workflows/p0.yaml and in every "
        "baseline run. Only the positive-control ladder's rung R3 sets it, as a "
        "declared experimenter variant (docs/positive_control.md). An empty value is "
        "left out of the sandbox's p0_config.json, so the jail sees the same bytes as "
        "before the key existed.",
    )


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


class DurationGuard(_Frozen):
    """The per-call duration guard (the coordinator's decision of 2026-09-29)."""

    seconds_per_evaluation_default: Annotated[float, Field(gt=0.0)]
    min_evaluations_measured: _PosInt
    safety_factor: Annotated[float, Field(ge=1.0)]
    tools: tuple[str, ...] = Field(min_length=1)


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
    brief: str | None = Field(
        default=None,
        description="The expert brief, appended to the system prompt in the expert-brief "
        "arm only (the lead's ruling of 2026-09-28); absent in the plain P1 arm",
    )


class Frozen(_Frozen):
    """The freeze record of P1 (the lead's word of 2026-09-30): what was frozen, verbatim.

    Every field is checked against the configuration and the prompts on disk before a run
    (:func:`check_frozen`); a mismatch refuses the run, because a post-freeze change to a
    prompt or a model setting invalidates the runs (the P1 prompt rule of 2026-09-24).
    """

    date: str = Field(min_length=1)
    word: str = Field(min_length=1, description="The lead's word, as relayed")
    prompt_sha256: str = Field(min_length=64, max_length=64)
    system_sha256: str = Field(
        min_length=64,
        max_length=64,
        description="The sha256 of the system text the model is sent (the summaries' value)",
    )
    model_id: str = Field(min_length=1)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None
    max_tokens: _PosInt
    retry: Retry


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
    duration_guard: DurationGuard
    uncertainty: P1Uncertainty
    seeds: P1Seeds
    evidence_keys: dict[str, tuple[str, ...]] = Field(min_length=1)
    prompts: Prompts
    prompt_sha256: str = Field(
        default="",
        description="The prompts' fingerprint (prompt_digest), committed at the freeze; "
        "empty until then. When set, the runner refuses prompts that do not match it",
    )
    brief_sha256: str = Field(
        default="",
        description="The expert brief's fingerprint (sha256 of the file), committed at the "
        "freeze; empty until then. When set, the runner refuses a brief that does not match it",
    )
    frozen: Frozen | None = Field(
        default=None,
        description="The freeze record (the frozen P1 only; None in a development arm). "
        "When set, the runner refuses a run whose prompts or model settings differ from it",
    )
    runner: Runner
    prompt_root: Path | None = Field(
        default=None,
        exclude=True,
        description="Where the prompt paths resolve: the directory the yaml was loaded from "
        "(set by load_p1; never in the file, never in the jail payload). None means "
        "configs/workflows/",
    )


def load_p1(path: Path = WORKFLOW_CONFIG_DIR / "p1.yaml") -> P1Config:
    """Parse and validate ``p1.yaml``.

    The prompt paths in the file resolve against the file's own directory
    (``prompt_root``), so a configuration loaded from a worktree or a copy hashes and
    sends the prompts beside it, never the repository's (the review of ``dbf2e45``,
    2026-09-30, note 2). ``prompt_root`` is not a field of the file.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    if "prompt_root" in raw:
        raise ValueError(f"{path}: prompt_root is set by the loader, not the file")
    return P1Config.model_validate({**raw, "prompt_root": path.resolve().parent})


def load_prompts(config: P1Config, root: Path | None = None) -> dict[str, str]:
    """The prompt texts P1's configuration names, by role.

    ``system`` and ``task`` always; ``brief`` only in the expert-brief arm, whose
    configuration names one. The paths resolve against ``root`` if given, else the
    directory the configuration was loaded from, else ``configs/workflows/``.
    """
    base = Path(root) if root is not None else config.prompt_root or WORKFLOW_CONFIG_DIR
    return {
        role: (base / rel).read_text(encoding="utf-8")
        for role, rel in config.prompts.model_dump().items()
        if rel is not None
    }


def model_system_text(prompts: dict[str, str]) -> str:
    """The system text the model is sent: the system prompt, then the brief when there is one.

    The brief is appended on the privileged side, so the jailed agent and the gateway's
    system-text check see one text; ``prompt_sha256`` covers the system and task prompts
    only, so the brief arm shares it with the plain arm and differs in ``brief_sha256``.
    """
    brief = prompts.get("brief")
    if brief:
        return prompts["system"].rstrip("\n") + "\n\n" + brief
    return prompts["system"]


def prompt_digest(prompts: dict[str, str]) -> str:
    """The fingerprint of the system and task prompts: sha256 of their sorted-key JSON.

    The brief, when present, is fingerprinted separately (``check_brief_hash``).
    """
    import hashlib
    import json

    core = {role: prompts[role] for role in ("system", "task")}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def check_brief_hash(config: P1Config) -> str:
    """The expert brief's fingerprint (empty when the arm has no brief), refused on a mismatch.

    Raises:
        ValueError: If ``brief_sha256`` is set and the brief on disk does not hash to it,
            or is set while the configuration names no brief.
    """
    import hashlib

    brief = load_prompts(config).get("brief")
    digest = hashlib.sha256(brief.encode("utf-8")).hexdigest() if brief else ""
    if config.brief_sha256 and config.brief_sha256 != digest:
        raise ValueError(
            f"the brief does not match the committed brief_sha256 ({config.brief_sha256}); "
            f"it hashes to {digest or 'nothing (no brief is configured)'}: a post-freeze "
            "change invalidates the runs"
        )
    return digest


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


def system_digest(system: str) -> str:
    """The sha256 of the system text the model is sent (as ``tools.llm.system_digest``)."""
    import hashlib

    return hashlib.sha256(system.encode("utf-8")).hexdigest()


def check_frozen(config: P1Config) -> Frozen | None:
    """The freeze record, refused when the configuration or the prompts on disk differ from it.

    Raises:
        ValueError: Naming the first field of the record that the configuration breaks.
    """
    frozen = config.frozen
    if frozen is None:
        return None
    prompts = load_prompts(config)
    found = {
        "prompt_sha256": prompt_digest(prompts),
        "system_sha256": system_digest(model_system_text(prompts)),
        "model_id": config.model.model_id,
        "effort": config.model.effort,
        "max_tokens": config.model.max_tokens,
        "retry": config.model.retry,
    }
    if config.prompt_sha256 != frozen.prompt_sha256:
        raise ValueError(
            f"prompt_sha256 ({config.prompt_sha256!r}) is not the frozen record's "
            f"({frozen.prompt_sha256}): the frozen P1 commits one hash"
        )
    for key, value in found.items():
        if getattr(frozen, key) != value:
            raise ValueError(
                f"frozen.{key} is {getattr(frozen, key)!r} but the configuration and the "
                f"prompts on disk give {value!r}: a post-freeze change invalidates the runs"
            )
    return frozen


def tool_size_ceilings() -> dict[str, dict[str, Any]]:
    """The registry's size ceilings per sized tool, from ``configs/tools/`` (see the guard)."""
    from tools.config import load_fitters, load_gsa, load_identifiability, load_mcmc, load_voi

    fitters, gsa, ident, mcmc, voi = (
        load_fitters(),
        load_gsa(),
        load_identifiability(),
        load_mcmc(),
        load_voi(),
    )
    return {
        "gsa_morris": {"n_trajectories": int(gsa.morris.n_trajectories)},
        "gsa_sobol": {
            "n_samples": int(gsa.sobol.n_samples),
            "second_order": bool(gsa.sobol.second_order),
        },
        "profile_likelihood": {
            "n_grid": int(ident.profile.n_grid),
            "n_starts": int(ident.profile.n_starts),
            "max_nfev_per_start": int(ident.profile.max_nfev_per_start),
        },
        "fit_lsq": {
            "n_starts": int(fitters.lsq.n_starts),
            "max_nfev_per_start": int(fitters.lsq.max_nfev_per_start),
        },
        "fit_de": {
            "popsize": int(fitters.de.popsize),
            "max_generations": int(fitters.de.max_generations),
        },
        "fit_cmaes": {
            "max_evaluations": int(fitters.cmaes.max_evaluations),
            "popsize": None if fitters.cmaes.popsize is None else int(fitters.cmaes.popsize),
        },
        "bayes_mcmc": {"n_walkers": int(mcmc.n_walkers), "n_steps": int(mcmc.n_steps)},
        "voi_assay": {"n_outer": int(voi.n_outer), "n_inner": int(voi.n_inner)},
    }


# ------------------------------------------------------------------ P2


_Roles = Literal[
    "data_quality",
    "influent",
    "identifiability",
    "calibration",
    "design",
    "verification",
    "coordination",
]
DECISION_POINTS: tuple[str, ...] = (
    "dq.trust",
    "dq.assay",
    "dq.coupled",
    "influent.onset",
    "influent.window",
    "influent.mechanism",
    "ident.subset",
    "cal.accept",
    "cal.bound",
    "cal.split",
    "design.assay",
    "verify.differential",
)
"""The twelve decision points of ``docs/p2_design.md`` §2."""


class P2Role(_Frozen):
    """One role's tool allow-list (design §6.1)."""

    tools: tuple[str, ...]


class P2RoleSwitches(_Frozen):
    """Which specialist roles run (design §8)."""

    data_quality: bool
    influent: bool
    identifiability: bool
    calibration: bool
    design: bool


class P2Ablation(_Frozen):
    """The ablation switches of design §8: true = on."""

    verifier: bool
    coordinator: bool
    persistent_state: bool
    self_correction: bool
    roles: P2RoleSwitches


class P2Onset(_Frozen):
    """The influent onset test's sizes (design §2.3; the re-reviews' N1 and R1)."""

    min_windows_before: Annotated[int, Field(ge=2)]
    every_window_after: bool
    min_windows_after: Annotated[int, Field(ge=1)]


class P2Holdout(_Frozen):
    """When the verifier calls the hold-out failed (design §12, question 3)."""

    min_channels_failed: _PosInt


class P2Caps(_Frozen):
    """The live decider's per-run caps, enforced by the privileged gateway (F-E).

    A request that would take the run past any of them is refused before it is sent,
    and the run abstains (``abstain:model_cap``).
    """

    max_requests: _PosInt = Field(description="Model requests per run (P1's 60 turns)")
    max_total_tokens: _PosInt = Field(description="Input + cache + output tokens per run")
    max_usd: _Pos = Field(description="USD per run at the declared prices")
    input_chars_per_token: _Pos = Field(
        description="Characters per token assumed when projecting a request's input "
        "before it is sent; low is conservative"
    )


class P2Frozen(_Frozen):
    """The freeze of P2's decision layer (deliverable 3, F-E), checked before every run.

    Every template's text, every decision's output schema and every decision's tool, by
    sha256, and the model settings; :func:`tools.p2_live.check_p2_frozen` recomputes them
    and refuses a run on any difference.
    """

    date: str
    word: str
    templates_sha256: dict[str, str]
    schemas_sha256: dict[str, str]
    tools_sha256: dict[str, str]
    model_id: str
    effort: str | None
    max_tokens: int
    retry: Retry


class P2Config(_Frozen):
    """``configs/workflows/p2.yaml``; P0's settings come from ``p0_config``, not retyped."""

    version: int
    workflow: Literal["p2"]
    workflow_version: str
    p0_config: str = Field(description="P0's configuration file, beside this one")
    decider: Literal["offline"] = Field(
        description="offline: every decision point takes its code fallback. The file "
        "cannot select a live decider: only the runner's explicit live flag does"
    )
    model: ModelSettings = Field(description="The live decider's model (P1's frozen settings)")
    caps: P2Caps
    frozen: P2Frozen | None = None
    roles: dict[_Roles, P2Role]
    ablation: P2Ablation
    coupled_channels: dict[str, tuple[str, ...]]
    forced_candidates: dict[Literal["A", "B", "C"], tuple[str, ...]]
    onset: P2Onset
    biomass_scales: tuple[_Pos, _Pos]
    holdout: P2Holdout
    templates: dict[str, str]
    runner: Runner
    config_dir: Path = Field(default=WORKFLOW_CONFIG_DIR, exclude=True)

    @model_validator(mode="after")
    def _complete(self) -> P2Config:
        missing = set(_Roles.__args__) - set(self.roles)
        if missing:
            raise ValueError(f"roles without an allow-list: {sorted(missing)}")
        if set(self.templates) != set(DECISION_POINTS):
            raise ValueError(
                f"templates must name exactly the decision points {list(DECISION_POINTS)}"
            )
        return self

    def p0(self) -> P0Config:
        """P0's configuration, whose thresholds, windows, sizes and seeds P2 shares."""
        return load_p0(self.config_dir / self.p0_config)


def load_p2(path: Path = WORKFLOW_CONFIG_DIR / "p2.yaml") -> P2Config:
    """Parse and validate ``p2.yaml``; its files resolve beside it."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return P2Config.model_validate({**raw, "config_dir": path.parent})


def load_p2_templates(config: P2Config) -> dict[str, dict[str, str]]:
    """Every decision point's template: its text and the text's sha256 (design §6.3)."""
    import hashlib

    out = {}
    for point in DECISION_POINTS:
        text = (config.config_dir / config.templates[point]).read_text(encoding="utf-8")
        out[point] = {"text": text, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return out


def load_workflow_config(workflow: str, path: Path | None = None) -> P0Config | P1Config | P2Config:
    """The configuration of a workflow by name (``p0``, ``p1`` or ``p2``)."""
    loaders = {"p0": load_p0, "p1": load_p1, "p2": load_p2}
    if workflow not in loaders:
        raise KeyError(f"no configuration schema for workflow {workflow!r}")
    return loaders[workflow]() if path is None else loaders[workflow](path)


def sandbox_config(config: P0Config | P1Config | P2Config, *, live: bool = False) -> dict[str, Any]:
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
    if live and not isinstance(config, P2Config):
        raise ValueError("only P2 has a live flag")
    if isinstance(config, P2Config):
        from tools.config import load_assays

        # the model, its caps and the freeze stay on the privileged side; the jail is told
        # only which decider runs, and it is live only on the runner's explicit flag
        for key in ("model", "caps", "frozen"):
            payload.pop(key, None)
        payload["decider"] = "live" if live else "offline"

        p0 = sandbox_config(config.p0())
        for key in ("sensor_noise", "plant_geometry", "abstentions"):
            p0.pop(key)
        payload["p0"] = p0
        payload["templates"] = load_p2_templates(config)
        payload["assay_catalogue"] = {
            name: {
                "channel": spec.channel,
                "unit_cost": int(spec.unit_cost),
                "turnaround_d": float(spec.turnaround_d),
            }
            for name, spec in load_assays().assays.items()
        }
    elif isinstance(config, P1Config):
        from tools.config import load_assays

        del payload["model"]
        # the freeze record repeats the model settings: privileged side only, as the block
        payload.pop("frozen", None)
        prompts = load_prompts(config)
        payload["prompts"] = {
            "system": model_system_text(prompts),  # the brief, when the arm has one, joined
            "task": prompts["task"],
        }
        # the public price list of requestable assays (proposal §6.4: "at a declared cost
        # and turnaround"), which P0 carries as its own preference list
        # the size ceilings the registry applies to a sized call (its default when the
        # agent omits a size, its maximum otherwise): what the duration guard's estimate
        # of the registry's evaluation bound needs (the coordinator's decision of 2026-09-29)
        payload["tool_size_ceilings"] = tool_size_ceilings()
        payload["assay_catalogue"] = {
            name: {
                "channel": spec.channel,
                "unit_cost": int(spec.unit_cost),
                "turnaround_d": float(spec.turnaround_d),
            }
            for name, spec in load_assays().assays.items()
        }
    elif not payload["screening"].get("force_include"):
        payload["screening"].pop("force_include", None)
    payload["sensor_noise"] = noise
    payload["plant_geometry"] = geometry
    payload["abstentions"] = abstention_vocabulary()
    return payload
