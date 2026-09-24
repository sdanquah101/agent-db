"""Pydantic schema for the scenario YAML contract (proposal Appendix B, §6.3).

A scenario is the declarative unit of the benchmark: it fixes a plant, an
instrumentation tier, a duration, the faults injected into the hidden truth model, the
ground-truth uncertainty-class label, the conclusion a workflow is expected to reach,
and the budget every workflow is held to.

Workflows never read these files. The simulator reads the ``faults`` block to build a
run; the evaluator reads ``truth_label`` and ``correct_conclusion`` to score one
(proposal §6.7). Keeping both in one file is deliberate — a scenario and its answer key
version together — but it is also why nothing under ``workflows/`` may load this module
with a scenario path.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Plant(StrEnum):
    """Virtual plant configuration (proposal §6.1).

    Attributes:
        A: Agricultural co-digestion (cattle slurry + grass silage), mesophilic CSTR, high
            ammonia; statistics-anchored; runs the ammonia scenarios.
        B: Municipal-sludge digester co-digesting high-strength waste and FOG, mesophilic,
            with load swings; Muscatine-anchored (proposal v0.3, decision 2026-09-02).
        C: Sewage-sludge digester, the same digester as B fed only its sludge streams
            (controlled pair); closest to ADM1's origin, serves as an easy control.
    """

    A = "A"
    B = "B"
    C = "C"


class Tier(StrEnum):
    """Instrumentation tier — an observation mask on identical underlying truth (§6.4).

    Attributes:
        A: Feed mass, reactor temperature, daily pH, daily corrected biogas volume,
            weekly TS/VS.
        B: Tier A plus continuous CH4 fraction, weekly alkalinity, total VFA, TAN, COD.
        C: Tier B plus VFA speciation, richer fractionation, off-gas H2/H2S, periodic
            activity tests.
    """

    A = "A"
    B = "B"
    C = "C"


class TruthLabel(StrEnum):
    """Ground-truth uncertainty class: where the discrepancy actually entered (§6.3)."""

    SENSOR = "sensor"
    INFLUENT = "influent"
    STATE = "state"
    PARAMETER = "parameter"
    STRUCTURAL = "structural"
    NONE = "none"


class FaultType(StrEnum):
    """Injectable faults, one per row of the scenario ladder (proposal §6.3).

    The set is closed on purpose: adding a scenario class is a design decision that
    belongs in ``docs/decisions.md``, not a free-text string in a YAML file.
    """

    # Level 1 — noise and missingness
    SENSOR_NOISE = "sensor_noise"
    RANDOM_GAPS = "random_gaps"
    # Level 2 — sensor faults
    PH_ELECTRODE_DRIFT = "ph_electrode_drift"
    GAS_METER_SCALE = "gas_meter_scale"
    CH4_ANALYSER_FLATLINE = "ch4_analyser_flatline"
    # Level 3 — influent faults
    FEED_MISLABELLED = "feed_mislabelled"
    UNRECORDED_DELIVERY = "unrecorded_delivery"
    MOISTURE_DRIFT = "moisture_drift"
    # Level 4 — state faults
    BIOMASS_MISINITIALISED = "biomass_misinitialised"
    INFORMATIVE_MISSINGNESS = "informative_missingness"
    # Level 5 — parameter faults
    AMMONIA_INHIBITION_SHIFT = "ammonia_inhibition_shift"
    HYDROLYSIS_REGIME_CHANGE = "hydrolysis_regime_change"
    # Level 6 — structural mismatch (present in truth, absent from the fitted model)
    OMITTED_SAO = "omitted_sao"
    OMITTED_PRECIPITATION = "omitted_precipitation"
    IMPERFECT_MIXING = "imperfect_mixing"
    # Level 8 — workflow robustness
    TOOL_FAILURE = "tool_failure"
    ADVERSARIAL_LOG_NOTE = "adversarial_log_note"


class Fault(BaseModel):
    """One injected fault: what, when it starts, and how large.

    ``magnitude`` is deliberately dimensionless-by-convention rather than typed per
    fault: its meaning is fixed by ``type`` and documented in the benchmark card (for
    ``gas_meter_scale`` it is a multiplicative scale factor, for
    ``ph_electrode_drift`` it is pH units per day, and so on). The simulator, not this
    schema, is authoritative for that mapping.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: FaultType = Field(description="Which fault to inject.")
    onset_day: Annotated[float, Field(ge=0.0)] = Field(
        description="Simulated day on which the fault becomes active (d, from t=0)."
    )
    magnitude: float = Field(
        description="Fault size; units are fixed by `type` (see the benchmark card)."
    )
    duration_days: Annotated[float, Field(gt=0.0)] | None = Field(
        default=None,
        description="Length of the fault episode (d). None means it persists to the "
        "end of the run.",
    )


class CorrectConclusion(BaseModel):
    """The answer key: what a workflow ought to conclude (§6.3, scored in §6.7 B)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    flag_sensor: str | None = Field(
        default=None,
        description="Name of the sensor that should be flagged, or None if no sensor "
        "fault should be reported.",
    )
    estimate_scale_factor: bool = Field(
        default=False,
        description="Whether the workflow should estimate a sensor scale/bias factor.",
    )
    kinetic_update_allowed: bool = Field(
        description="Whether moving a kinetic parameter is a correct action. False "
        "means any such move counts towards the false kinetic-drift rate (Appendix A).",
    )
    abstain_on: tuple[str, ...] = Field(
        default=(),
        description="Quantities the data cannot support, on which the final report "
        "should decline to make a claim.",
    )
    revise_influent_mapping: bool = Field(
        default=False,
        description="Whether the correct action is to revise the feed fractionation "
        "mapping rather than the model.",
    )
    recommend_structural_review: bool = Field(
        default=False,
        description="Whether the correct conclusion is that the model structure, not "
        "its parameters, is at fault.",
    )

    @model_validator(mode="after")
    def _check_abstentions(self) -> Self:
        """Reject an ``abstain_on`` term outside the controlled vocabulary.

        The vocabulary is ``configs/abstentions.yaml`` (ruling A3 of 2026-09-24): the
        evaluator matches abstentions by exact name, so a term a workflow cannot spell is
        an abstention nobody can score.

        Raises:
            ValueError: If a term is not in the vocabulary or is repeated.
        """
        from state.abstentions import abstention_vocabulary

        vocabulary = abstention_vocabulary()
        unknown = [term for term in self.abstain_on if term not in vocabulary]
        if unknown:
            raise ValueError(
                f"abstain_on terms {unknown} are not in the controlled vocabulary "
                "(configs/abstentions.yaml)"
            )
        if len(set(self.abstain_on)) != len(self.abstain_on):
            raise ValueError(f"abstain_on repeats a term: {list(self.abstain_on)}")
        return self


class Budget(BaseModel):
    """The envelope every workflow is held to for this scenario (§6.2, §7).

    Enforced in the tool registry, not in workflows, and identical across P0, P1 and P2
    for a given (scenario, tier) cell.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    simulator_evals: Annotated[int, Field(gt=0)] = Field(
        description="Maximum number of simulator evaluations (count)."
    )
    wall_clock_min: Annotated[float, Field(gt=0.0)] = Field(
        description="Maximum wall-clock allowance (minutes)."
    )
    assay_units: Annotated[int, Field(ge=0)] = Field(
        description="Assay budget the workflow may spend on requested lab assays "
        "(dimensionless cost units, priced in configs/)."
    )


class Scenario(BaseModel):
    """A single benchmark case: plant, tier, injected faults, and its answer key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(pattern=r"^S\d+-\d{2}$")] = Field(
        description="Scenario identifier, e.g. 'S2-03' (S<level>-<index>)."
    )
    plant: Plant = Field(description="Which virtual plant the scenario runs on.")
    tier: Tier = Field(description="Instrumentation tier (observation mask).")
    level: Annotated[int, Field(ge=0, le=8)] = Field(
        description="Rung of the difficulty ladder (0-8, proposal §6.3)."
    )
    duration_days: Annotated[float, Field(gt=0.0)] = Field(
        description="Simulated duration of the scenario (d)."
    )
    truth_label: tuple[TruthLabel, ...] = Field(
        min_length=1, description="Ground-truth uncertainty class(es)."
    )
    faults: tuple[Fault, ...] = Field(
        default=(), description="Faults injected into the hidden truth model."
    )
    correct_conclusion: CorrectConclusion = Field(description="What a workflow ought to conclude.")
    budget: Budget = Field(description="Simulator, wall-clock and assay budget.")
    baseline: str | None = Field(
        default=None,
        description="Declared plant baseline this scenario is staged on "
        "(sim.plants.schema.Baseline). None means the plant's `default_baseline`. A "
        "Level-6 structural row is only meaningful if the omitted pathway carries flux in "
        "the truth, and which baseline the plant is in decides that (lead's ruling 1, "
        "2026-09-09).",
    )
    seed: int | None = Field(
        default=None,
        description="Base seed for this scenario. None means the seed is supplied by "
        "the run harness; no stochastic component may run unseeded (CLAUDE.md rule 4).",
    )
    notes: str | None = Field(
        default=None, description="Free-text note for maintainers. Never shown to a workflow."
    )

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        """Reject scenarios that are internally contradictory.

        Returns:
            The validated scenario.

        Raises:
            ValueError: If a fault starts after the run ends, if `none` is combined
                with a real uncertainty class, if a label is repeated, or if a
                structural scenario permits kinetic updates.
        """
        for fault in self.faults:
            if fault.onset_day > self.duration_days:
                raise ValueError(
                    f"fault {fault.type!s} has onset_day={fault.onset_day} after the "
                    f"run ends at duration_days={self.duration_days}"
                )

        labels = self.truth_label
        if len(set(labels)) != len(labels):
            raise ValueError(f"truth_label contains duplicates: {labels}")
        if TruthLabel.NONE in labels and len(labels) > 1:
            raise ValueError(f"truth_label 'none' cannot be combined with another class: {labels}")

        if TruthLabel.NONE in labels and self.level >= 2:
            raise ValueError(
                f"level {self.level} scenarios inject an attributable fault, so "
                "truth_label 'none' is inconsistent"
            )

        # A structural scenario is never scored on parameter recovery (CLAUDE.md,
        # "Domain reminders"), so allowing a kinetic update as *correct* would make the
        # false kinetic-drift metric unscoreable.
        if (
            TruthLabel.STRUCTURAL in labels
            and TruthLabel.PARAMETER not in labels
            and self.correct_conclusion.kinetic_update_allowed
        ):
            raise ValueError(
                "a purely structural scenario must not set kinetic_update_allowed=true"
            )
        return self


def load_scenario(path: str | Path) -> Scenario:
    """Load and validate a scenario YAML file.

    Args:
        path: Path to the scenario definition.

    Returns:
        The validated scenario.

    Raises:
        ValueError: If the file does not contain a single YAML mapping.
        pydantic.ValidationError: If the mapping does not satisfy the schema.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping, got {type(raw).__name__}")
    return Scenario.model_validate(raw)
