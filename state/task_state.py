"""The shared task state (proposal §6.6): one schema for P0, P1 and P2.

"A single JSON schema shared by all workflows: data-quality status, tier, candidate model,
current uncertainty classification (with confidence), approved parameter subset, residual
diagnostics summary, actions taken, tool failures, remaining simulator and assay budget,
validation status. Memory is this state plus the tool-call log; free-text summaries are not
permitted to replace structured results."

**Where it lives and who writes it.** A workflow writes its state to
``runs/<id>/workflows/<workflow>/state.json`` through the registry's ``run.write_output``
(the workflow is jailed and cannot open the run directory itself; the server restricts the
write to that directory). The file must contain nothing that is not derivable from the
visible record and the tool outputs: no scenario id, no seed, no truth label, no baseline,
no timestamp (``tests/test_p0_pipeline.py`` asserts it on P0's output).

**Why a workflow does not import this module.** ``state`` is a forbidden module in the
jail (``tools.sandbox.FORBIDDEN_MODULES``): a workflow builds the JSON to this schema and
the privileged runner validates it with :class:`TaskState` after the launch, so a workflow
that wrote something else fails loudly on the outside. ``TaskState.model_json_schema()`` is
the contract a workflow author reads.

**Free text annotates, never replaces.** Every model here has structured fields for what
the evaluator reads; ``notes`` fields carry prose about them and nothing the evaluator
scores comes from prose.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "LABELS",
    "OUTPUTS_DIR",
    "ActionRef",
    "Classification",
    "DataQualityStatus",
    "EvidenceItem",
    "FinalResult",
    "ParameterEstimate",
    "PlanRecord",
    "RemainingBudgetState",
    "ResidualSummary",
    "ScreeningTrail",
    "TaskState",
    "ToolFailureRecord",
    "ValidationStatus",
]

OUTPUTS_DIR = "workflows"
"""Subdirectory of ``runs/<id>/`` that holds every workflow's own outputs: the task state
lives at ``runs/<id>/workflows/<workflow>/state.json``. Declared here, beside the schema
of what is written there, so that the scorer (``eval/records.py``) reads the name without
importing the registry server (the coordinator's review of PR #19, nit 6); ``tools.server``
re-exports it."""

Label = Literal["sensor", "influent", "state", "parameter", "structural", "none"]
LABELS: tuple[str, ...] = ("sensor", "influent", "state", "parameter", "structural", "none")
"""The uncertainty classes of §6.3, the only values a final label may take."""

_Frac = Annotated[float, Field(ge=0.0, le=1.0)]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActionRef(_Model):
    """One tool call the workflow made, as the call log identifies it (rule 3).

    ``seq`` is the line's sequence number in ``runs/<id>/calls.jsonl`` and ``args_hash``
    its fingerprint, both handed back by the registry with the call (``tools.last_call()``),
    so a workflow's own record of a call matches the log line for line. ``call_index`` is
    the registry's own count before the call (``remaining().n_calls``), from 0 for the
    first call after ``registry.open``.
    """

    step: str = Field(description="Which step of the workflow made the call")
    name: str = Field(description="Tool name")
    version: str = Field(description="Tool version, as logged")
    args_hash: str = Field(description="Fingerprint of the validated arguments, as logged")
    seq: int | None = Field(description="Sequence number of the line in calls.jsonl")
    call_index: int = Field(ge=0, description="The registry's call count before this call")
    outcome: Literal["ok", "error", "budget_exceeded"] = Field(
        description="As the workflow experienced it (an injected failure looks like ok)"
    )
    detail: str = Field(default="", description="Error text, if any; never an argument value")


class DataQualityStatus(_Model):
    """What QC decided about one sensor."""

    status: Literal["ok", "quarantined", "excluded", "flagged", "absent"] = Field(
        description="ok: used as is; quarantined: some windows dropped; excluded: not in the "
        "objective; flagged: reported as a sensor fault; absent: not at this tier"
    )
    flags: tuple[str, ...] = Field(default=(), description="QC finding codes")
    missing_fraction: _Frac | None = None
    quarantined_windows: tuple[tuple[float, float], ...] = Field(
        default=(), description="[start, end] d dropped from the series"
    )
    in_objective: bool = Field(description="Whether the sensor weights the calibration")
    notes: str = ""


class EvidenceItem(_Model):
    """One piece of evidence behind the classification, tied to the calls it rests on."""

    rule: str = Field(description="The attribution rule that read it, e.g. R1b")
    label: Label = Field(description="Which class this evidence points to")
    statement: str = Field(description="What was found, in words")
    values: dict[str, float | str | bool | None] = Field(
        default_factory=dict, description="The numbers the statement rests on"
    )
    calls: tuple[int, ...] = Field(default=(), description="call_index of the calls it came from")


class Classification(_Model):
    """The current uncertainty classification (§6.6) with its confidence."""

    label: Label
    secondary_labels: tuple[Label, ...] = Field(
        default=(), description="Other rules that fired, for compound rows"
    )
    confidence: _Frac
    rule: str = Field(description="The rule that set the label")
    evidence: tuple[EvidenceItem, ...] = ()
    flag_sensor: str | None = Field(default=None, description="The sensor reported as faulty")
    scale_factor: dict[str, float] = Field(
        default_factory=dict, description="Estimated sensor scale factors, by sensor"
    )
    revise_influent_mapping: bool = False
    recommend_structural_review: bool = False
    kinetic_update: bool = Field(
        default=False, description="Whether the final estimates are offered as a kinetic update"
    )


class ScreeningTrail(_Model):
    """How the approved subset was reached (§6.2: sensitivity is not identifiability)."""

    declared: tuple[str, ...] = Field(description="The full calibratable set")
    morris_ranking: tuple[str, ...] = ()
    morris_kept: tuple[str, ...] = ()
    sobol_kept: tuple[str, ...] = ()
    sobol_total_order: dict[str, float] = Field(default_factory=dict)
    sobol_interactions: tuple[tuple[str, str, float], ...] = Field(
        default=(), description="Largest second-order indices, (a, b, S2)"
    )
    fisher_dropped: tuple[str, ...] = ()
    fisher_relative_crlb: dict[str, float | None] = Field(default_factory=dict)
    profiled: dict[str, bool] = Field(
        default_factory=dict, description="Parameter -> identifiable, where a profile was run"
    )
    approved: tuple[str, ...] = Field(description="The approved subset")


class ResidualSummary(_Model):
    """Residual structure of one calibrated output after the fit."""

    n: int
    bias_z: float = Field(description="Mean residual over its standard error")
    rmse_z: float = Field(description="RMS standardised residual")
    serially_structured: bool
    lag1_autocorrelation: float
    trend_slope_per_d: float
    most_explanatory: str | None
    covariate_eta2: dict[str, float] = Field(default_factory=dict)
    step_z: float | None = Field(
        default=None, description="Largest before/after mean difference in time, in se units"
    )
    step_day: float | None = None
    early_bias_z: float | None = Field(default=None, description="Bias in the first window")
    late_bias_z: float | None = None


class ToolFailureRecord(_Model):
    """A tool that did not deliver: an error, a refusal, or a result unfit to use."""

    step: str
    name: str
    call_index: int | None = None
    kind: Literal["error", "budget_exceeded", "not_converged", "unusable"]
    message: str
    fallback: str = Field(description="What the workflow did instead")


class RemainingBudgetState(_Model):
    """The envelope left at the end of the run, from ``tools.remaining()``."""

    simulator_evals: int
    simulator_evals_total: int
    simulator_evals_used: int
    wall_clock_min: float
    wall_clock_min_total: float
    assay_units: int
    assay_units_total: int
    assay_units_used: int
    n_calls: int


class ValidationStatus(_Model):
    """What ``validate`` said on the frozen hold-out window."""

    holdout: tuple[float, float] = Field(description="[start, end] d")
    ensemble: bool
    ensemble_size: int = 0
    metrics: dict[str, dict[str, float | None]] = Field(
        default_factory=dict, description="Output -> mae, rmse, nrmse, bias, coverage_50, ..."
    )
    constraint_violations: int = 0
    calls: tuple[int, ...] = ()


class ParameterEstimate(_Model):
    """One final parameter estimate with its interval and where the interval came from."""

    estimate: float
    lower: float | None
    upper: float | None
    method: Literal["posterior", "profile", "fisher", "none"]
    at_bound: bool = False
    unit: str = ""


class PlanRecord(_Model):
    """The sizes the workflow chose and the fallbacks it took (design §4)."""

    sizes: dict[str, int | float | bool | None] = Field(default_factory=dict)
    fallbacks: tuple[str, ...] = ()
    guards_tripped: tuple[str, ...] = ()
    eval_seconds_assumed: float | None = None
    steps_completed: tuple[str, ...] = ()
    steps_skipped: dict[str, str] = Field(default_factory=dict)


class FinalResult(_Model):
    """The final label and the final estimates (what the evaluator scores)."""

    label: Label
    secondary_labels: tuple[Label, ...] = ()
    confidence: _Frac
    parameters: dict[str, ParameterEstimate] = Field(default_factory=dict)
    interval_method: Literal["posterior", "profile", "fisher", "none"]
    abstentions: tuple[str, ...] = ()
    completed: bool = Field(description="Whether the workflow reached its last step")


class TaskState(_Model):
    """The task state of one workflow run (§6.6)."""

    schema_version: str = Field(default="1.0")
    workflow: str = Field(description="p0, p1 or p2")
    workflow_version: str
    run_id: str
    plant: str
    tier: str
    duration_days: float
    calibration_window: tuple[float, float]
    holdout_window: tuple[float, float]
    candidate_model: str = Field(description="Registered model name")
    model_parameters: tuple[str, ...] = Field(description="The model's calibratable set")
    calibrated_outputs: tuple[str, ...] = Field(description="Channels in the objective")
    data_quality: dict[str, DataQualityStatus]
    mass_balance: dict[str, float | bool | None] = Field(default_factory=dict)
    classification: Classification
    screening: ScreeningTrail
    residuals: dict[str, ResidualSummary] = Field(default_factory=dict)
    actions: tuple[ActionRef, ...]
    tool_failures: tuple[ToolFailureRecord, ...] = ()
    budget: RemainingBudgetState
    validation: ValidationStatus | None = None
    assay_checks: tuple[dict[str, float | str | bool | None], ...] = ()
    abstentions: tuple[str, ...] = ()
    final: FinalResult
    plan: PlanRecord
    notes_seen: tuple[dict[str, int | str], ...] = Field(
        default=(), description="Operator notes as data: day, author, length; never the text"
    )
    annotations: tuple[str, ...] = Field(
        default=(), description="Free text about the structured fields; replaces none of them"
    )
