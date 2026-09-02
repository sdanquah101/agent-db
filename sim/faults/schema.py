"""What every fault magnitude means, and which layer of the simulator applies it (§6.1, §6.3).

The scenario schema deliberately leaves the meaning of ``Fault.magnitude`` to the
simulator ("its meaning is fixed by ``type`` and documented in the benchmark card ... The
simulator, not this schema, is authoritative for that mapping",
:class:`scenarios.schema.Fault`). **This module is that mapping**: one
:class:`FaultSemantics` entry per :class:`~scenarios.schema.FaultType`, giving the unit of
the magnitude, its admissible range, the layer that applies it, and the sentence the
benchmark card prints. :func:`benchmark_card_rows` renders the table, so the card and the
code cannot drift apart.

**Layers.** A fault is applied where the thing it corrupts actually lives, which is also
what its truth label means (§6.3):

===============  ===========================================================
``influent``     the influent generator's inputs — what is fed and what the
                 operator's log says was fed (truth label *influent*)
``parameter``    a truth-model parameter that changes at the onset day, so the
                 run is integrated in segments (truth label *parameter*)
``state``        the initial state handed to the integrator (truth label *state*)
``structure``    the truth model has a mechanism the fitted model lacks — an
                 extension, or the two-zone reactor (truth label *structural*)
``observation``  the sensor record only; the digester is untouched (truth label
                 *sensor*)
``workflow``     neither truth nor observation: the tool registry or the
                 operator's notes (Level 8; no truth label)
===============  ===========================================================

A structural fault carries no magnitude semantics of its own for
``omitted_sao``/``omitted_precipitation``: those name an extension the **fitted** model
must not have, and the truth model keeps it on. ``imperfect_mixing`` is the exception —
its magnitude sizes the non-ideality of the truth reactor (:mod:`sim.plants.mixing`).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scenarios.schema import FaultType

__all__ = [
    "FAULT_SEMANTICS",
    "FaultLayer",
    "FaultSemantics",
    "benchmark_card_rows",
    "semantics_for",
]

FaultLayer = Literal["influent", "parameter", "state", "structure", "observation", "workflow"]


class FaultSemantics(BaseModel):
    """The meaning of one fault type's magnitude, and where it is applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fault: FaultType
    layer: FaultLayer = Field(description="Simulator layer that applies the fault")
    magnitude_unit: str = Field(description="Unit of Fault.magnitude for this fault type")
    magnitude_min: float | None = Field(
        default=None, description="Smallest admissible magnitude (inclusive), same unit"
    )
    magnitude_max: float | None = Field(
        default=None, description="Largest admissible magnitude (inclusive), same unit"
    )
    target: str = Field(
        default="",
        description="What the magnitude acts on: a sensor id, a parameter name, a feed id",
    )
    description: str = Field(description="One sentence for the benchmark card")

    def validate_magnitude(self, magnitude: float) -> None:
        """Raise if a scenario's magnitude is outside the admissible range.

        Raises:
            ValueError: If the magnitude is out of range for this fault type.
        """
        if self.magnitude_min is not None and magnitude < self.magnitude_min:
            raise ValueError(
                f"{self.fault.value}: magnitude {magnitude} is below the minimum "
                f"{self.magnitude_min} {self.magnitude_unit}"
            )
        if self.magnitude_max is not None and magnitude > self.magnitude_max:
            raise ValueError(
                f"{self.fault.value}: magnitude {magnitude} is above the maximum "
                f"{self.magnitude_max} {self.magnitude_unit}"
            )


def _s(
    fault: FaultType,
    layer: FaultLayer,
    unit: str,
    description: str,
    *,
    lo: float | None = None,
    hi: float | None = None,
    target: str = "",
) -> tuple[FaultType, FaultSemantics]:
    return fault, FaultSemantics(
        fault=fault,
        layer=layer,
        magnitude_unit=unit,
        magnitude_min=lo,
        magnitude_max=hi,
        target=target,
        description=description,
    )


#: The authoritative magnitude mapping, one entry per fault type (closed set).
FAULT_SEMANTICS: dict[FaultType, FaultSemantics] = dict(
    [
        # ---------------------------------------------------------- Level 1
        _s(
            FaultType.SENSOR_NOISE,
            "observation",
            "- (multiplier on every sensor's noise cv and sd_abs)",
            "Scales the declared measurement noise of every sensor in the tier; 1.0 is the "
            "declared instrumentation, 2.0 a plant whose instruments are twice as noisy.",
            lo=0.0,
        ),
        _s(
            FaultType.RANDOM_GAPS,
            "observation",
            "- (multiplier on every sensor's base missing rate)",
            "Scales the unconditional missing rate of every sensor; the conditional "
            "(foaming/overload) multipliers are untouched, so this adds gaps that carry no "
            "information about the state.",
            lo=0.0,
        ),
        # ---------------------------------------------------------- Level 2
        _s(
            FaultType.PH_ELECTRODE_DRIFT,
            "observation",
            "pH units per day (signed; negative = reads low)",
            "Adds a deterministic ramp to the pH sensor from the onset day, on top of the "
            "electrode's own random-walk drift. The sensor's recalibration interval still "
            "applies, which produces the drift-then-step signature of the Level-2 row.",
            lo=-0.05,
            hi=0.05,
            target="ph",
        ),
        _s(
            FaultType.GAS_METER_SCALE,
            "observation",
            "- (multiplicative scale factor)",
            "Multiplies the gas-flow sensor's reading from the onset day; 1.08 is the +8 % "
            "scale error of the Appendix-B example. The digester is untouched, so the "
            "correct conclusion is to estimate the factor, never to move a yield parameter.",
            lo=0.5,
            hi=2.0,
            target="gas_flow",
        ),
        _s(
            FaultType.CH4_ANALYSER_FLATLINE,
            "observation",
            "- (ignored; the episode length is the fault's duration_days)",
            "The methane analyser holds its last value for the whole fault window. The "
            "magnitude is not used: the episode is defined by onset_day and duration_days.",
            target="ch4_fraction",
        ),
        # ---------------------------------------------------------- Level 3
        _s(
            FaultType.FEED_MISLABELLED,
            "influent",
            "- (Dirichlet concentration of the mislabelled batch's true fractionation)",
            "One feed's true COD fractionation departs from its catalogue entry for the "
            "fault window: the true fractionation is redrawn with the given concentration "
            "(smaller = further from the catalogue), while the operator's log and the "
            "catalogue still say the entry. Revising the mapping is the correct action; "
            "hydrolysis is not at fault.",
            lo=1.0,
            hi=1000.0,
        ),
        _s(
            FaultType.UNRECORDED_DELIVERY,
            "influent",
            "- (multiple of the feed's median delivery that arrives unlogged)",
            "An extra delivery of the given size arrives on the onset day and never enters "
            "the feed log, so the COD balance closes only if the analyst notices.",
            lo=0.0,
            hi=10.0,
        ),
        _s(
            FaultType.MOISTURE_DRIFT,
            "influent",
            "- (relative change in the feed's total solids over the fault window)",
            "The feed's total solids ramp by the given fraction across the window (negative "
            "= wetter), lowering the VS delivered per tonne. The trend is in the influent, "
            "not the kinetics.",
            lo=-0.9,
            hi=2.0,
        ),
        # ---------------------------------------------------------- Level 4
        _s(
            FaultType.BIOMASS_MISINITIALISED,
            "state",
            "- (multiplier on every biomass state at t = 0)",
            "Every biomass state starts at the given multiple of the nominal initial value, "
            "so state estimation must converge before any parameter can be identified.",
            lo=0.01,
            hi=100.0,
        ),
        _s(
            FaultType.INFORMATIVE_MISSINGNESS,
            "observation",
            "- (multiplier on the conditional missing multipliers)",
            "Scales the foaming and overload multipliers of every sensor, so instruments "
            "fail *during* the transients that identify the process and naive "
            "interpolation destroys information.",
            lo=0.0,
        ),
        # ---------------------------------------------------------- Level 5
        _s(
            FaultType.AMMONIA_INHIBITION_SHIFT,
            "parameter",
            "- (multiplier on K_I_nh3 from the onset day)",
            "The free-ammonia inhibition constant of the acetoclastic methanogens changes "
            "at the onset day, as an adapted community would; the run is integrated in two "
            "segments. A bounded update of that parameter is the correct action.",
            lo=0.1,
            hi=10.0,
            target="K_I_nh3",
        ),
        _s(
            FaultType.HYDROLYSIS_REGIME_CHANGE,
            "parameter",
            "- (multiplier on k_hyd_ch, k_hyd_pr and k_hyd_li from the onset day)",
            "All three hydrolysis constants change at the onset day, as a change in feed "
            "particle size would do. Only hydrolysis may be updated in response.",
            lo=0.1,
            hi=10.0,
            target="k_hyd_ch,k_hyd_pr,k_hyd_li",
        ),
        # ---------------------------------------------------------- Level 6
        _s(
            FaultType.OMITTED_SAO,
            "structure",
            "- (ignored; the truth keeps the extension, the fitted model must not have it)",
            "The truth model runs with syntrophic acetate oxidation on and the fitted model "
            "without it. No magnitude: the fault is the omission itself.",
            target="sao",
        ),
        _s(
            FaultType.OMITTED_PRECIPITATION,
            "structure",
            "- (ignored; as omitted_sao, for the calcite sink)",
            "The truth model runs with the precipitation extension on and the fitted model "
            "without it; the residual appears in alkalinity and pH.",
            target="precipitation",
        ),
        _s(
            FaultType.IMPERFECT_MIXING,
            "structure",
            "- (stagnant volume fraction; the bypass is a fifth of it)",
            "The truth reactor is the two-zone structure of sim.plants.mixing with the given "
            "stagnant fraction, a bypass of one fifth of it, and the configured exchange "
            "rate; the fitted model still assumes an ideal CSTR. 0 reduces to the CSTR "
            "exactly.",
            lo=0.0,
            hi=0.5,
        ),
        # ---------------------------------------------------------- Level 8
        _s(
            FaultType.TOOL_FAILURE,
            "workflow",
            "- (probability that the named tool returns a non-converged result)",
            "The tool registry makes a tool fail with the given probability; the simulator "
            "and the observation record are untouched. Applied by the run harness.",
            lo=0.0,
            hi=1.0,
            target="bayes_mcmc",
        ),
        _s(
            FaultType.ADVERSARIAL_LOG_NOTE,
            "workflow",
            "- (ignored; the note text is scenario content)",
            "An operator note asserting a false cause is placed in the run's log. Neither "
            "truth nor observation changes; applied by the run harness.",
        ),
    ]
)

FAULT_SEMANTICS = MappingProxyType(FAULT_SEMANTICS)  # type: ignore[assignment]


def semantics_for(fault: FaultType) -> FaultSemantics:
    """The magnitude semantics of one fault type.

    Raises:
        KeyError: If the fault type has no entry (the set is closed, so this is a bug).
    """
    if fault not in FAULT_SEMANTICS:
        raise KeyError(f"no magnitude semantics declared for {fault}")
    return FAULT_SEMANTICS[fault]


def benchmark_card_rows() -> list[tuple[str, str, str, str]]:
    """The magnitude table for the benchmark card: ``(fault, layer, unit, description)``."""
    return [
        (f.value, s.layer, s.magnitude_unit, s.description)
        for f, s in sorted(FAULT_SEMANTICS.items(), key=lambda kv: kv[0].value)
    ]
