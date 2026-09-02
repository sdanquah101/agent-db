"""Typed contract of the observation model (proposal §6.1, §6.4).

One **catalogue** of channels (:class:`ChannelSpec`) covers every quantity the benchmark
can report; the three instrumentation tiers are *masks* over it
(:meth:`ObservationConfig.channels_for_tier`), not three catalogues. A channel names the
**instrument** (:class:`InstrumentModel`) that measures it — sampling noise, quantisation,
bounded drift, fouling episodes, flatlining, saturation and missingness — so plants that
share an instrument share its statistics, and a plant that differs overrides only what
differs.

Every value carries its unit in the field description (CLAUDE.md rule 6); gas volumes and
fractions carry :class:`StandardConditions`, solids a wet/dry :class:`Basis`. Nothing in
this module reads or writes files (the loader is :mod:`sim.observe.defaults`).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

_Frac = Annotated[float, Field(ge=0.0, le=1.0)]
_Pos = Annotated[float, Field(gt=0.0)]
_NonNeg = Annotated[float, Field(ge=0.0)]

TierName = Literal["A", "B", "C"]
PlantId = Literal["A", "B", "C"]

TIER_ORDER: tuple[TierName, ...] = ("A", "B", "C")
"""Tiers in increasing richness; a tier shows every channel of the tiers below it."""


class Basis(StrEnum):
    """Solids basis of a reported value (CLAUDE.md rule 6)."""

    WET = "wet"
    """Per unit of wet (as-delivered, as-sampled) material."""
    DRY = "dry"
    """Per unit of dry matter."""
    NOT_APPLICABLE = "n/a"
    """The quantity has no solids basis (pH, temperature, a gas fraction)."""


class ChannelKind(StrEnum):
    """How a channel reaches the operator's record."""

    SENSOR = "sensor"
    """An instrument logged on a fixed interval."""
    ASSAY = "assay"
    """A laboratory measurement on a sampling schedule, reported after a turnaround."""
    LOG = "log"
    """An operator record produced elsewhere (the influent generator's feed log)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StandardConditions(_Frozen):
    """Reference conditions a gas quantity is reported at (CLAUDE.md rule 6)."""

    name: str = Field(description="Short name used in reports, e.g. 'STP dry (0 C, 1.013 bar)'")
    temperature_K: _Pos = Field(description="Reference temperature, K")
    pressure_bar: _Pos = Field(description="Reference pressure, bar")
    moisture: Literal["dry", "wet"] = Field(
        description="'dry': water vapour removed before the volume is reported"
    )


class DriftModel(_Frozen):
    """Slow instrument drift as a **bounded** random walk (proposal §6.1).

    The walk is evaluated at the channel's own sample times: ``d_k = reflect(d_{k-1} +
    sd_per_sqrt_d * sqrt(dt) * z_k, bound)``, reflected at ``+-bound`` so the drift stays
    inside a stated interval instead of wandering off.
    """

    sd_per_sqrt_d: _NonNeg = Field(
        description="Random-walk step, in the channel's unit per sqrt(day) ('offset' mode) "
        "or as a relative gain per sqrt(day) ('gain' mode)"
    )
    bound: _NonNeg = Field(description="Reflecting bound on |drift|, same unit as sd_per_sqrt_d")
    mode: Literal["offset", "gain"] = Field(
        description="'offset': value + d; 'gain': value * (1 + d)"
    )
    source: str = Field(default="", description="Where the numbers come from")


class FoulingModel(_Frozen):
    """Fouling episodes: a gain and offset error while the instrument is dirty."""

    onset_per_d: _NonNeg = Field(description="Rate of new fouling episodes, 1/d")
    mean_duration_d: _NonNeg = Field(description="Length of an episode, d (fixed, not random)")
    gain: _Pos = Field(default=1.0, description="Multiplicative error during an episode, -")
    offset: float = Field(default=0.0, description="Additive error during an episode, channel unit")
    source: str = ""

    @model_validator(mode="after")
    def _episode_has_an_effect(self) -> FoulingModel:
        if self.onset_per_d > 0.0 and self.gain == 1.0 and self.offset == 0.0:
            raise ValueError("a fouling episode with no gain and no offset would be invisible")
        if self.onset_per_d > 0.0 and self.mean_duration_d <= 0.0:
            raise ValueError("a fouling episode needs a positive duration")
        return self


class FlatlineModel(_Frozen):
    """Flatlining: the instrument repeats its last reported value for a while."""

    onset_per_d: _NonNeg = Field(description="Rate of new flatline episodes, 1/d")
    mean_duration_d: _NonNeg = Field(description="Length of an episode, d (fixed, not random)")
    source: str = ""

    @model_validator(mode="after")
    def _episode_has_a_length(self) -> FlatlineModel:
        if self.onset_per_d > 0.0 and self.mean_duration_d <= 0.0:
            raise ValueError("a flatline episode needs a positive duration")
        return self


class SaturationModel(_Frozen):
    """The instrument's range: readings outside it are clipped and flagged."""

    minimum: float | None = Field(default=None, description="Lower limit, channel unit")
    maximum: float | None = Field(default=None, description="Upper limit, channel unit")
    source: str = ""

    @model_validator(mode="after")
    def _ordered(self) -> SaturationModel:
        if self.minimum is not None and self.maximum is not None and self.minimum >= self.maximum:
            raise ValueError("saturation minimum must be below the maximum")
        return self


class MissingnessModel(_Frozen):
    """Missingness of one channel: a base rate and its dependence on process stress.

    The dependence is the point of proposal §6.1 ("instruments are more likely to fail
    during foaming and overload, so that naive interpolation destroys information"). The
    per-sample probability is

    ``p = min(p_max, base_probability * exp(stress_sensitivity * stress(t)))``

    with ``stress(t)`` built from truth-state excursions by :class:`StressCoupling`. A
    channel with ``stress_sensitivity = 0`` is missing at random.
    """

    base_probability: _Frac = Field(description="Probability that a scheduled sample is lost, -")
    stress_sensitivity: _NonNeg = Field(
        description="Multiplier on the process-stress term of the log hazard, - "
        "(0 = missing at random; 1 = the coupling declared in `stress`)"
    )
    source: str = ""


class InstrumentModel(_Frozen):
    """Everything about how one instrument measures: noise, drift, failure, missingness."""

    noise_cv: _NonNeg = Field(description="Relative measurement noise, - (sd / value)")
    noise_sd_abs: _NonNeg = Field(
        default=0.0, description="Absolute measurement noise, in the channel's unit"
    )
    resolution: _NonNeg = Field(
        default=0.0,
        description="Recorded quantisation of the channel, its unit (0 = not quantised)",
    )
    drift: DriftModel
    fouling: FoulingModel
    flatline: FlatlineModel
    saturation: SaturationModel
    missingness: MissingnessModel
    source: str = Field(default="", description="Where the numbers come from")

    @property
    def assumed(self) -> bool:
        """True when every source of this instrument's numbers says ASSUMED."""
        sources = [
            self.source,
            self.drift.source,
            self.fouling.source,
            self.flatline.source,
            self.saturation.source,
            self.missingness.source,
        ]
        return all("ASSUMED" in s for s in sources if s)


class ChannelSpec(_Frozen):
    """One entry of the observation catalogue: what is reported, from where, how often."""

    name: str = Field(description="Channel id; equals the catalogue key")
    kind: ChannelKind
    tier: TierName = Field(description="Lowest tier at which the channel is observed (§6.4)")
    unit: str = Field(description="Unit of the reported value")
    basis: Basis = Field(description="Wet/dry basis of the reported value")
    instrument: str = Field(description="Key of the instrument that measures it")
    truth_quantity: str | None = Field(
        description="Key of the truth series this channel observes; None = not derivable "
        "from the truth model (then `unavailable_reason` says why)"
    )
    unavailable_reason: str = Field(
        default="",
        description="Why the channel cannot be produced; empty when truth_quantity is set",
    )
    interval_d: _Pos = Field(description="Sampling interval, d")
    weekdays_only: bool = Field(
        default=False, description="Samples are only taken Monday-Friday (lab not staffed)"
    )
    lag_d: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Turnaround: report day - sample day, d"
    )
    standard_conditions: StandardConditions | None = Field(
        default=None, description="Reference conditions of a gas quantity; None if not a gas"
    )
    description: str = ""
    source: str = ""

    @model_validator(mode="after")
    def _availability(self) -> ChannelSpec:
        if self.weekdays_only and self.interval_d != int(self.interval_d):
            raise ValueError(f"{self.name}: a weekdays-only schedule needs a whole-day interval")
        if self.truth_quantity is None and not self.unavailable_reason:
            raise ValueError(f"{self.name}: an unavailable channel must say why")
        if self.truth_quantity is not None and self.unavailable_reason:
            raise ValueError(f"{self.name}: has a truth quantity and an unavailable_reason")
        # a same-day assay is allowed, but it must be a stated choice
        same_day = "same day" in self.source or "same-day" in self.source
        if self.kind is ChannelKind.ASSAY and self.lag_d == 0 and not same_day:
            raise ValueError(f"{self.name}: a zero-lag assay must say so in `source`")
        return self

    @property
    def available(self) -> bool:
        """True when the channel can be produced from the truth model."""
        return self.truth_quantity is not None


class SensorEffect(StrEnum):
    """What a compiled sensor fault does to a channel (:mod:`sim.faults` builds these)."""

    SCALE = "scale"
    """Multiply the reading by the magnitude while the fault is active."""
    DRIFT = "drift"
    """Add ``magnitude x (t - onset)`` to the reading; the offset disappears when the
    episode ends, which is the step recalibration of the Level-2 scenario."""
    OFFSET = "offset"
    """Add a constant to the reading while the fault is active."""
    FLATLINE = "flatline"
    """Hold ``magnitude x`` the last reported value for the fault's duration."""
    NOISE = "noise"
    """Multiply the instrument's noise scale by the magnitude."""
    GAP = "gap"
    """Add the magnitude to the per-sample missing probability."""
    STRESS_COUPLING = "stress_coupling"
    """Multiply the channel's stress sensitivity by the magnitude, so missingness becomes
    more strongly informative (the Level-4 scenario)."""


class SensorFault(_Frozen):
    """One compiled sensor-layer fault, as the observation model consumes it.

    Produced by :mod:`sim.faults` from a scenario's :class:`~scenarios.schema.Fault`;
    ``label`` keeps the originating :class:`~scenarios.schema.FaultType` so the hidden
    observation record can be scored against the scenario's answer key.
    """

    channel: str | None = Field(
        description="Channel the fault acts on; None = every channel of the tier"
    )
    effect: SensorEffect
    onset_d: _NonNeg = Field(description="Day the fault becomes active, d")
    magnitude: float = Field(description="Fault size; its meaning is fixed by `effect`")
    duration_d: _Pos | None = Field(
        default=None, description="Length of the episode, d; None = to the end of the run"
    )
    label: str = Field(default="", description="Scenario fault type this came from")

    def active(self, t: np.ndarray) -> np.ndarray:
        """Boolean mask of the times at which this fault is in force."""
        after = np.asarray(t, dtype=float) >= self.onset_d
        if self.duration_d is None:
            return after
        return after & (np.asarray(t, dtype=float) < self.onset_d + self.duration_d)


class StressCoupling(_Frozen):
    """How truth-state excursions raise the missing-sample hazard (§6.1, Level-4 scenario).

    ``stress(t) = vfa_coupling * max(0, log2(VFA(t) / median VFA))
                + gas_coupling * |log2(q_gas(t) / median q_gas)|``

    Both terms are in *doublings* away from the run's own median, so no plant-specific
    threshold is needed and the indicator is scale-free. The VFA term is one-sided (only
    an accumulation is stress); the gas term is two-sided (a foaming episode both spikes
    and chokes the meter).
    """

    vfa_coupling: _NonNeg = Field(
        description="Log-hazard per doubling of total VFA above the run median, -"
    )
    gas_coupling: _NonNeg = Field(
        description="Log-hazard per doubling of |gas-rate deviation| from the run median, -"
    )
    max_probability: _Frac = Field(
        description="Cap on the per-sample missing probability whatever the stress, -"
    )
    vfa_quantity: str = Field(default="vfa_total", description="Truth series used for the VFA term")
    gas_quantity: str = Field(
        default="biogas_volume", description="Truth series used for the gas term"
    )
    source: str = ""


class SolidsConvention(_Frozen):
    """How reactor COD becomes total and volatile solids (:mod:`sim.observe.truth`).

    ADM1 has no solids state: VS is the organic COD converted at per-class COD
    equivalents, and TS is VS plus the inorganic solids (the conservative ash the feed
    carries, plus any calcite the precipitation extension has formed). Both the
    equivalents and the treatment of VFA are declared here rather than assumed in code
    (CLAUDE.md rule 6).
    """

    cod_per_vs: dict[
        Literal["carbohydrate", "protein", "lipid", "inert", "biomass", "composite"], _Pos
    ] = Field(description="COD equivalent of each class, kg COD/kg VS")
    include_vfa_in_vs: bool = Field(
        description="Whether volatile fatty acids count towards VS (they largely "
        "volatilise during drying at 105 degC, so the usual answer is false)"
    )
    source: str = ""


class PlantObservation(_Frozen):
    """Per-plant instrument overrides (a plant with different instruments says so here)."""

    plant_id: PlantId
    note: str = ""
    instruments: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Instrument key -> partial override, merged into the shared instrument "
        "(nested blocks merge key by key; unknown fields are rejected on merge)",
    )


def _merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge an override mapping into a base mapping."""
    out = dict(base)
    for key, value in override.items():
        current = out.get(key)
        if isinstance(value, Mapping) and isinstance(current, Mapping):
            out[key] = _merge(current, value)
        else:
            out[key] = value
    return out


class ObservationConfig(_Frozen):
    """``configs/observe/observation.yaml``: the catalogue, the instruments, the tiers."""

    version: int
    standard_conditions: dict[str, StandardConditions] = Field(
        description="Named reference conditions channels refer to"
    )
    solids: SolidsConvention
    stress: StressCoupling
    instruments: dict[str, InstrumentModel]
    channels: dict[str, ChannelSpec]
    plants: dict[PlantId, PlantObservation]

    @model_validator(mode="after")
    def _consistent(self) -> ObservationConfig:
        for key, channel in self.channels.items():
            if channel.name != key:
                raise ValueError(f"channel key {key!r} != name {channel.name!r}")
            if channel.instrument not in self.instruments:
                raise ValueError(f"{key}: unknown instrument {channel.instrument!r}")
        for pid, plant in self.plants.items():
            if plant.plant_id != pid:
                raise ValueError(f"plants[{pid!r}] declares plant_id {plant.plant_id!r}")
            unknown = set(plant.instruments) - set(self.instruments)
            if unknown:
                raise ValueError(f"plant {pid}: overrides unknown instruments {sorted(unknown)}")
            for key in plant.instruments:
                self.instrument_for(pid, key)  # validates the merge
        for name in (self.stress.vfa_quantity, self.stress.gas_quantity):
            if not any(c.truth_quantity == name for c in self.channels.values()):
                raise ValueError(f"stress refers to {name!r}, which no channel observes")
        return self

    def instrument_for(self, plant_id: str, instrument: str) -> InstrumentModel:
        """The instrument model for a plant, with that plant's overrides applied.

        Raises:
            KeyError: If the instrument is not in the catalogue.
            pydantic.ValidationError: If an override is not a valid instrument field.
        """
        base = self.instruments[instrument]
        override = (
            self.plants[plant_id].instruments.get(instrument) if plant_id in self.plants else None
        )
        if not override:
            return base
        return InstrumentModel.model_validate(_merge(base.model_dump(), override))

    def channels_for_tier(
        self, tier: str, *, available_only: bool = True
    ) -> tuple[ChannelSpec, ...]:
        """Channels visible at a tier: the mask of §6.4, in sorted channel order.

        Args:
            tier: ``A``, ``B`` or ``C``. A tier shows its own channels and every channel
                of the tiers below it.
            available_only: Skip channels the truth model cannot produce (their
                ``unavailable_reason`` says why).
        """
        if tier not in TIER_ORDER:
            raise ValueError(f"unknown tier {tier!r}")
        limit = TIER_ORDER.index(tier)
        return tuple(
            channel
            for _, channel in sorted(self.channels.items())
            if TIER_ORDER.index(channel.tier) <= limit and (channel.available or not available_only)
        )
