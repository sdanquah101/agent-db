"""What each fault type means, at which layer it is applied, and what its magnitude is.

The scenario schema (:mod:`scenarios.schema`) deliberately leaves the meaning of a
fault's ``magnitude`` to the simulator ("the simulator, not this schema, is authoritative
for that mapping"). This module *is* that authority: :data:`FAULT_LAYER` says where each
fault type of the closed :class:`~scenarios.schema.FaultType` enum is applied, and
:data:`FAULT_MAGNITUDE` says what its magnitude means and in what unit. The benchmark
card is generated from these two tables, so the contract cannot drift from the code.

The layers follow proposal §6.3's ground-truth labels, because *where* a fault is applied
is exactly what a workflow has to recover:

===============  =========================================================================
Layer            Applied to
===============  =========================================================================
``sensor``       the observation model (:mod:`sim.observe`) — the truth is untouched
``influent``     the influent generator's parameters and the catalogue -> influent mapping
``state``        the initial state vector of the truth run
``parameter``    the truth model's parameters, bounded and time-varying
``structural``   which model *the fitted side* gets, or the reactor's mixing structure
``workflow``     nothing here: carried in the compiled record for the tool registry
===============  =========================================================================

Numbers (default magnitudes, bounds, the mixing bands, the acclimation time) are DESIGN
content and live in ``configs/faults/faults.yaml``, not here.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scenarios.schema import FaultType

_Pos = Annotated[float, Field(gt=0.0)]
_NonNeg = Annotated[float, Field(ge=0.0)]


class FaultLayer(StrEnum):
    """The layer of the simulator a fault is applied at."""

    SENSOR = "sensor"
    INFLUENT = "influent"
    STATE = "state"
    PARAMETER = "parameter"
    STRUCTURAL = "structural"
    WORKFLOW = "workflow"


FAULT_LAYER: Mapping[FaultType, FaultLayer] = {
    FaultType.SENSOR_NOISE: FaultLayer.SENSOR,
    FaultType.RANDOM_GAPS: FaultLayer.SENSOR,
    FaultType.PH_ELECTRODE_DRIFT: FaultLayer.SENSOR,
    FaultType.GAS_METER_SCALE: FaultLayer.SENSOR,
    FaultType.CH4_ANALYSER_FLATLINE: FaultLayer.SENSOR,
    FaultType.INFORMATIVE_MISSINGNESS: FaultLayer.SENSOR,
    FaultType.FEED_MISLABELLED: FaultLayer.INFLUENT,
    FaultType.UNRECORDED_DELIVERY: FaultLayer.INFLUENT,
    FaultType.MOISTURE_DRIFT: FaultLayer.INFLUENT,
    FaultType.BIOMASS_MISINITIALISED: FaultLayer.STATE,
    FaultType.AMMONIA_INHIBITION_SHIFT: FaultLayer.PARAMETER,
    FaultType.HYDROLYSIS_REGIME_CHANGE: FaultLayer.PARAMETER,
    FaultType.OMITTED_SAO: FaultLayer.STRUCTURAL,
    FaultType.OMITTED_PRECIPITATION: FaultLayer.STRUCTURAL,
    FaultType.IMPERFECT_MIXING: FaultLayer.STRUCTURAL,
    FaultType.TOOL_FAILURE: FaultLayer.WORKFLOW,
    FaultType.ADVERSARIAL_LOG_NOTE: FaultLayer.WORKFLOW,
}
"""Which layer each fault type is applied at. Total over :class:`FaultType`."""

#: ``informative_missingness`` carries the ground-truth label ``state``/``sensor`` in the
#: §6.3 ladder because the *cause* is a process transient; it is nevertheless applied at
#: the sensor layer (it strengthens the coupling the observation model already has).


class MagnitudeSpec(BaseModel):
    """What a fault's ``magnitude`` means, in what unit, and whether a duration applies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit: str = Field(description="Unit of the magnitude, or '-' when dimensionless")
    meaning: str = Field(description="One sentence: what the number does")
    duration_used: bool = Field(description="Whether `duration_days` changes the injection")


FAULT_MAGNITUDE: Mapping[FaultType, MagnitudeSpec] = {
    FaultType.SENSOR_NOISE: MagnitudeSpec(
        unit="-",
        meaning="Multiplier on every instrument's noise scale while the fault is active.",
        duration_used=True,
    ),
    FaultType.RANDOM_GAPS: MagnitudeSpec(
        unit="-",
        meaning="Probability added to every channel's per-sample missing probability.",
        duration_used=True,
    ),
    FaultType.PH_ELECTRODE_DRIFT: MagnitudeSpec(
        unit="pH units/d",
        meaning=(
            "Slope of the pH reading's drift from onset (negative drifts low). The offset "
            "disappears when the episode ends: that is the step recalibration of §6.3."
        ),
        duration_used=True,
    ),
    FaultType.GAS_METER_SCALE: MagnitudeSpec(
        unit="-",
        meaning="Multiplicative scale error of the biogas meter (1.08 = reads 8 % high).",
        duration_used=True,
    ),
    FaultType.CH4_ANALYSER_FLATLINE: MagnitudeSpec(
        unit="-",
        meaning=(
            "Multiplier on the value the analyser freezes at (1.0 = it holds its last "
            "reading). The episode lasts `duration_days`."
        ),
        duration_used=True,
    ),
    FaultType.INFORMATIVE_MISSINGNESS: MagnitudeSpec(
        unit="-",
        meaning=(
            "Multiplier on every channel's stress sensitivity, so instruments fail harder "
            "during foaming and overload."
        ),
        duration_used=True,
    ),
    FaultType.FEED_MISLABELLED: MagnitudeSpec(
        unit="kg COD/kg COD",
        meaning=(
            "COD share of the affected feed moved from the degradable classes into the "
            "particulate inerts in the TRUTH; the catalogue the operator reads is unchanged."
        ),
        duration_used=False,
    ),
    FaultType.UNRECORDED_DELIVERY: MagnitudeSpec(
        unit="1/d",
        meaning=(
            "Probability per day of an extra delivery that never enters the log, added to "
            "the affected feed's generator statistics from the onset day."
        ),
        duration_used=True,
    ),
    FaultType.MOISTURE_DRIFT: MagnitudeSpec(
        unit="-",
        meaning=(
            "Factor the affected feed's true total solids is multiplied by, reached "
            "linearly over the configured ramp from the onset day (0.85 = 15 % wetter)."
        ),
        duration_used=True,
    ),
    FaultType.BIOMASS_MISINITIALISED: MagnitudeSpec(
        unit="-",
        meaning="Factor every biomass state of the initial condition is multiplied by.",
        duration_used=False,
    ),
    FaultType.AMMONIA_INHIBITION_SHIFT: MagnitudeSpec(
        unit="-",
        meaning=(
            "Factor the acetoclastic free-ammonia inhibition constant K_I_nh3 moves to, "
            "reached linearly over the configured acclimation time from the onset day."
        ),
        duration_used=True,
    ),
    FaultType.HYDROLYSIS_REGIME_CHANGE: MagnitudeSpec(
        unit="-",
        meaning=(
            "Factor the three hydrolysis constants k_hyd_ch/pr/li step to at the onset day "
            "(a feed particle-size change is abrupt)."
        ),
        duration_used=True,
    ),
    FaultType.OMITTED_SAO: MagnitudeSpec(
        unit="-",
        meaning=(
            "Not used (any value is accepted and ignored): the truth keeps its SAO "
            "extension and the FITTED model is denied it. The truth's physics never change."
        ),
        duration_used=False,
    ),
    FaultType.OMITTED_PRECIPITATION: MagnitudeSpec(
        unit="-",
        meaning=(
            "Not used: the truth keeps its precipitation extension and the FITTED model is "
            "denied it."
        ),
        duration_used=False,
    ),
    FaultType.IMPERFECT_MIXING: MagnitudeSpec(
        unit="-",
        meaning=(
            "Stagnant share of the liquid volume in the two-zone truth variant "
            "(sim/plants/mixing.py); the bypass fraction and exchange rate come from "
            "configs/faults/faults.yaml."
        ),
        duration_used=False,
    ),
    FaultType.TOOL_FAILURE: MagnitudeSpec(
        unit="-",
        meaning=(
            "Carried, not applied here: the fraction of calls to the affected tool that "
            "fail, for the tool registry to honour."
        ),
        duration_used=True,
    ),
    FaultType.ADVERSARIAL_LOG_NOTE: MagnitudeSpec(
        unit="-",
        meaning=(
            "Carried, not applied here: which note of configs/faults/faults.yaml the run "
            "layer puts in the operator log (an index)."
        ),
        duration_used=False,
    ),
}
"""Magnitude semantics of every fault type. Total over :class:`FaultType`."""


class MagnitudeBounds(BaseModel):
    """Admissible range of a fault's magnitude, and its default (DESIGN content)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default: float = Field(description="Magnitude used when a scenario does not state one")
    minimum: float = Field(description="Smallest admissible magnitude")
    maximum: float = Field(description="Largest admissible magnitude")
    source: str = Field(default="", description="Where the numbers come from")

    @model_validator(mode="after")
    def _ordered(self) -> MagnitudeBounds:
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError(
                f"need minimum <= default <= maximum, got {self.minimum}, {self.default}, "
                f"{self.maximum}"
            )
        return self

    def check(self, magnitude: float, label: str) -> float:
        """Return the magnitude, raising if it is outside the declared band.

        Raises:
            ValueError: If the magnitude is out of bounds. A truth parameter that a
                scenario could move arbitrarily far would not be a *bounded* fault.
        """
        if not self.minimum <= magnitude <= self.maximum:
            raise ValueError(
                f"{label}: magnitude {magnitude} outside the configured bounds "
                f"[{self.minimum}, {self.maximum}]"
            )
        return magnitude


class SensorFaultTarget(BaseModel):
    """Which observation channel a sensor fault acts on, and how."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: str | None = Field(
        description="Observation channel, or null for every channel of the tier"
    )
    effect: Literal["scale", "drift", "offset", "flatline", "noise", "gap", "stress_coupling"]
    magnitude: MagnitudeBounds
    default_duration_d: _Pos | None = Field(
        default=None, description="Episode length used when a scenario states none, d"
    )


class ParameterFaultSpec(BaseModel):
    """Which truth parameters a parameter fault moves, how fast, and within what band."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group: Literal["kinetics", "stoichiometry", "physchem"] = Field(
        description="Parameter group of sim.adm1.schema.ADM1Parameters"
    )
    parameters: tuple[str, ...] = Field(description="Field names moved by the same factor")
    magnitude: MagnitudeBounds
    transition_d: _NonNeg = Field(
        description="Time over which the factor is reached linearly from the onset, d "
        "(0 = a step; acclimation is not instantaneous, a particle-size change is)"
    )
    source: str = ""


class InfluentFaultSpec(BaseModel):
    """How an influent fault changes the generator's parameters or the true fractionation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    magnitude: MagnitudeBounds
    transition_d: _NonNeg = Field(
        default=0.0, description="Ramp from the onset day to the full effect, d"
    )
    shift_from: tuple[str, ...] = Field(
        default=(),
        description="COD fractions the mislabel takes from (proportionally to their size)",
    )
    shift_to: str = Field(default="", description="COD fraction the mislabel moves the share into")
    source: str = ""


class StateFaultSpec(BaseModel):
    """Which states a state fault multiplies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    states: tuple[str, ...] = Field(description="State names multiplied by the magnitude")
    magnitude: MagnitudeBounds
    source: str = ""


class StructuralFaultSpec(BaseModel):
    """What a structural fault denies the fitted model, or how it mixes the truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    omit_extension: str | None = Field(
        default=None,
        description="Extension the FITTED model is denied; the truth keeps it unchanged",
    )
    magnitude: MagnitudeBounds | None = Field(
        default=None, description="Bounds of the magnitude, when the fault uses one"
    )
    bypass_fraction: _NonNeg | None = Field(
        default=None, description="Influent short-circuiting to the effluent, - (mixing)"
    )
    exchange_rate: _NonNeg | None = Field(
        default=None, description="Stagnant-zone exchange rate, 1/d (mixing)"
    )
    source: str = ""


class WorkflowFaultSpec(BaseModel):
    """A workflow-layer fault: carried for the registry, never applied to the simulator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    magnitude: MagnitudeBounds
    target: str = Field(default="", description="Tool the failure applies to, for tool_failure")
    notes: tuple[str, ...] = Field(
        default=(), description="Adversarial operator notes the run layer may inject"
    )
    source: str = ""


class FaultsConfig(BaseModel):
    """``configs/faults/faults.yaml``: every fault type's DESIGN parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    sensor: dict[FaultType, SensorFaultTarget]
    influent: dict[FaultType, InfluentFaultSpec]
    state: dict[FaultType, StateFaultSpec]
    parameter: dict[FaultType, ParameterFaultSpec]
    structural: dict[FaultType, StructuralFaultSpec]
    workflow: dict[FaultType, WorkflowFaultSpec]

    @model_validator(mode="after")
    def _covers_every_fault_at_its_layer(self) -> FaultsConfig:
        blocks: dict[FaultLayer, Mapping[FaultType, object]] = {
            FaultLayer.SENSOR: self.sensor,
            FaultLayer.INFLUENT: self.influent,
            FaultLayer.STATE: self.state,
            FaultLayer.PARAMETER: self.parameter,
            FaultLayer.STRUCTURAL: self.structural,
            FaultLayer.WORKFLOW: self.workflow,
        }
        for layer, block in blocks.items():
            declared = {f for f, lay in FAULT_LAYER.items() if lay is layer}
            if set(block) != declared:
                missing = sorted(f.value for f in declared - set(block))
                extra = sorted(f.value for f in set(block) - declared)
                raise ValueError(
                    f"{layer.value} block: missing {missing}, unexpected {extra} "
                    "(sim.faults.schema.FAULT_LAYER is the authority)"
                )
        return self

    def bounds_for(self, fault_type: FaultType) -> MagnitudeBounds | None:
        """The magnitude bounds of a fault type, or ``None`` when it uses no magnitude."""
        layer = FAULT_LAYER[fault_type]
        block = getattr(self, layer.value)
        spec = block[fault_type]
        return getattr(spec, "magnitude", None)
