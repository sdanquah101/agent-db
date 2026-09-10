"""Typed contract for the observation model (proposal §6.1, §6.4).

"Every sensor has a declared model: sampling interval, noise, drift (random walk with
bounds), fouling episodes, flatlining, saturation, and a wet/dry and standard-conditions
convention. Lab assays have method noise, turnaround delay and schedule. Missingness is
generated *conditionally* — instruments are more likely to fail during foaming and
overload — so that naive interpolation destroys information."

A :class:`SensorSpec` is the declared model of one instrument; a :class:`TierSpec` is the
**observation mask** of an instrumentation tier (§6.4: tiers are masks on identical
underlying truth, never different truth). The specs live in
``configs/observation/sensors.yaml``; the noise and flatline statistics of the two
continuous Muscatine channels are re-derived from the 1-minute SCADA file by
``tests/test_observation.py``, and everything else is marked ``ASSUMED`` with its reason.

Every numeric field carries its unit, and every measured quantity carries its
**convention** — gas at standard conditions or at operating conditions, wet or dry basis,
solids wet or dry (CLAUDE.md rule 6). All models are frozen and reject unknown fields.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_Frac = Annotated[float, Field(ge=0.0, le=1.0)]
_Pos = Annotated[float, Field(gt=0.0)]
_NonNeg = Annotated[float, Field(ge=0.0)]

#: Measurement conventions a channel may declare (CLAUDE.md rule 6: no silent choice).
GasConvention = Literal["stp_dry", "stp_wet", "operating_wet", "none"]
"""``stp_dry``: 0 degC, 1 atm, water vapour removed. ``stp_wet``: standard conditions,
water vapour retained. ``operating_wet``: at T_op and P_atm as the plant meter reads it
(the BSM2 convention). ``none``: not a gas quantity."""

SolidsBasis = Literal["wet", "dry", "none"]
"""``wet``: per kg or m3 of wet sample. ``dry``: per kg of total solids. ``none``: not a
solids quantity."""

#: Condition flags the missingness model reacts to (proposal §6.1: foaming and overload).
ConditionFlag = Literal["overload", "foaming"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NoiseModel(_Frozen):
    """Additive measurement noise of one instrument."""

    cv: _NonNeg = Field(description="Relative standard deviation, - (fraction of the value)")
    sd_abs: _NonNeg = Field(
        default=0.0, description="Absolute standard deviation, in the channel's own unit"
    )
    source: str = Field(default="", description="Where the numbers come from")

    @model_validator(mode="after")
    def _some_noise(self) -> NoiseModel:
        if self.cv == 0.0 and self.sd_abs == 0.0:
            raise ValueError("a noise model must declare a non-zero cv or sd_abs")
        return self


class DriftModel(_Frozen):
    """Slow zero drift as a bounded random walk (proposal §6.1).

    The drift is an additive offset in the channel's own unit, updated once per sample:
    ``d(t+1) = clip(d(t) + sd_per_sqrt_d sqrt(dt) z, -bound, +bound)``. A recalibration
    resets it to zero, which is what makes the Level-2 "drift then step-recalibration"
    signature (§6.3). *How often* an instrument is recalibrated is a property of the
    plant, not of the instrument, so the cadence is the tier's
    (:attr:`TierSpec.recalibration_interval_d`) and the sensor only declares whether it is
    recalibrated at all (lead's decision 2026-09-02: monthly at Tiers B and C, quarterly
    at Tier A).
    """

    sd_per_sqrt_d: _NonNeg = Field(
        description="Random-walk scale, channel unit per sqrt(day); 0 = no drift"
    )
    bound: _NonNeg = Field(description="Absolute bound on the accumulated offset, channel unit")
    recalibrated: bool = Field(
        default=False,
        description="Whether the instrument is recalibrated on the tier's cadence, - (else never)",
    )
    source: str = ""


class EpisodeModel(_Frozen):
    """A Bernoulli-onset, **fixed-duration** episode (fouling or flatlining).

    On each sample an episode starts with probability ``hazard_per_d * dt`` and lasts
    exactly ``max(1, round(mean_duration_d / dt))`` samples — a deterministic length, not a
    geometric draw: the documented random-stream order allocates one uniform per sample for
    onsets and none for durations, and adding a draw would move every later sensor's block
    (:mod:`sim.observation.model`).

    Realised occupancy is therefore ``hazard_per_d * dt * max(1, round(...))``, which
    equals the intended ``hazard_per_d * mean_duration_d`` **only when the episode lasts at
    least one sample**. A duration below the sampling interval is rounded up to one sample
    and inflates the occupancy, so :meth:`_observable` rejects it: an episode shorter than
    the schedule is not observable on that schedule, and declaring one silently changes the
    anchored flatline rates it claims to reproduce.
    """

    hazard_per_d: _Frac = Field(
        description="Probability per day that an episode starts, 1/d (<= 1: it is a probability)"
    )
    mean_duration_d: _Pos = Field(description="Episode length, d (rounded to whole samples)")
    source: str = ""


class FoulingModel(EpisodeModel):
    """A fouling episode: the reading degrades multiplicatively and/or additively.

    During an episode the true value is transformed to
    ``gain * value + offset`` before noise, with the deviation ramping linearly from zero
    at onset to its full size at the end of the episode (fouling accumulates; it does not
    switch on).
    """

    gain: _Pos = Field(description="Multiplicative factor at full fouling, - (1 = no gain error)")
    offset: float = Field(default=0.0, description="Additive offset at full fouling, channel unit")


class SaturationModel(_Frozen):
    """Readable range of the instrument; values outside it are clipped and flagged."""

    low: float | None = Field(default=None, description="Lowest readable value, channel unit")
    high: float | None = Field(default=None, description="Highest readable value, channel unit")

    @model_validator(mode="after")
    def _ordered(self) -> SaturationModel:
        if self.low is not None and self.high is not None and self.low >= self.high:
            raise ValueError("saturation low must be below high")
        return self


class MissingnessModel(_Frozen):
    """Conditional missingness (proposal §6.1).

    A sample is missing with probability ``base_rate`` in normal operation, and with
    ``base_rate * multiplier[flag]`` while a condition flag is raised — instruments are
    more likely to fail during foaming and overload, so gaps coincide with exactly the
    transients that identify the process. Naive interpolation across such a gap therefore
    destroys information rather than merely losing precision.
    """

    base_rate: _Frac = Field(description="Probability that a scheduled sample is missing, -")
    stress_multipliers: dict[ConditionFlag, _Pos] = Field(
        default_factory=dict,
        description="Multiplier applied to base_rate while each condition flag is raised, -",
    )
    source: str = ""

    def rate(self, flags: frozenset[str]) -> float:
        """Missing probability under the raised flags (multipliers compound, capped at 1)."""
        p = self.base_rate
        for flag, multiplier in sorted(self.stress_multipliers.items()):
            if flag in flags:
                p *= multiplier
        return min(p, 1.0)


class MissingnessPolicy(_Frozen):
    """How missingness is declared: a base rate per **tier**, multipliers per instrument **kind**.

    Lead's decision of 2026-09-02. A tier is a plant's monitoring capability, so how often
    a scheduled sample is simply lost belongs to the tier (a constrained Tier-A plant
    loses more), while how much worse it gets under stress belongs to the kind of
    instrument (an online probe in a foaming digester fails far more often than a grab
    sample sent to a laboratory).

    Every rate here is ASSUMED and per-sensor **independent**. The one *measured* dropout
    the anchor carries is not one of these: it is a plant-level, correlated process and
    lives in :class:`HistorianDropout` (lead's ruling of 2026-09-03). Keeping the two apart
    is the point — a rate that is measured on a correlated process and then applied as an
    independent per-sensor rate imports the number and discards the structure.
    """

    base_rate_by_tier: dict[Literal["A", "B", "C"], _Frac] = Field(
        description="Probability that a scheduled sample is lost, by tier, -"
    )
    stress_multipliers_by_kind: dict[Literal["online", "lab"], dict[ConditionFlag, _Pos]] = Field(
        description="Multiplier on the base rate while each flag is raised, by instrument kind, -"
    )
    source: str = ""

    @model_validator(mode="after")
    def _complete(self) -> MissingnessPolicy:
        if set(self.base_rate_by_tier) != {"A", "B", "C"}:
            raise ValueError("base_rate_by_tier must cover tiers A, B and C")
        if set(self.stress_multipliers_by_kind) != {"online", "lab"}:
            raise ValueError("stress_multipliers_by_kind must cover 'online' and 'lab'")
        return self

    def model_for(self, tier: str, kind: str) -> MissingnessModel:
        """The resolved missingness model of one sensor kind at one tier."""
        return MissingnessModel(
            base_rate=self.base_rate_by_tier[tier],  # type: ignore[index]
            stress_multipliers=dict(self.stress_multipliers_by_kind[kind]),  # type: ignore[index]
        )


class HistorianDropout(_Frozen):
    """A **plant-level** logging outage: every online instrument loses the same samples.

    Lead's ruling of 2026-09-03, on the finding that the measured SCADA dropout is a
    correlated process and had been applied as an independent per-sensor rate.

    **What the anchor actually shows.** The Muscatine 1-minute file is 100 % finite in its
    *cells* — which is why the dropout was first recorded as unanchorable — but whole
    **rows** are absent: 19 gaps over 347.8 d, 484 minutes missing, **0.0966 %** of the
    record, lengths 1 to 421 min (median 2, p90 9.8). Because whole rows go, every online
    channel loses exactly the same minutes together. Modelled as an independent per-sensor
    rate ``p``, two online sensors would lose the same sample with probability ``p^2``
    (9.3e-7 at this rate); in the record it is 1. That is a difference of six orders of
    magnitude in exactly the structure §6.1 is about, so the process is modelled as what it
    is: one outage series per tier, applied to every online sensor.

    **The analogue at Tiers A and B.** Those plants have no SCADA historian — their online
    readings are logged by hand — so the shared failure is "nobody wrote the readings down
    that day", coarser and rarer than a per-instrument fault. Same structure, ASSUMED rates.

    **This is additive to, not a replacement for, per-sensor missingness**
    (:class:`MissingnessPolicy`), which stays exactly as the lead froze it: an instrument
    can fail on its own while the historian is up, and the historian can fall over while
    every instrument is healthy.

    Laboratory assays are untouched: a grab sample does not go through the historian.
    """

    rate_by_tier: dict[Literal["A", "B", "C"], _Frac] = Field(
        description="Fraction of scheduled online samples lost to a shared outage, by tier, -"
    )
    gap_lengths_min: tuple[_Pos, ...] = Field(
        description=(
            "Empirical outage lengths in minutes, the distribution an outage is drawn from; "
            "the anchor's 19 observed gaps for the measured tier"
        )
    )
    measured_tiers: tuple[Literal["A", "B", "C"], ...] = Field(
        default=(),
        description="Tiers whose rate is measured rather than assumed (CLAUDE.md rule 6)",
    )
    source: str = ""

    @model_validator(mode="after")
    def _complete(self) -> HistorianDropout:
        if set(self.rate_by_tier) != {"A", "B", "C"}:
            raise ValueError("rate_by_tier must cover tiers A, B and C")
        if not self.gap_lengths_min:
            raise ValueError("gap_lengths_min must carry at least one observed outage length")
        unknown = set(self.measured_tiers) - set(self.rate_by_tier)
        if unknown:
            raise ValueError(f"measured_tiers names unknown tiers {sorted(unknown)}")
        return self

    @property
    def mean_gap_min(self) -> float:
        """Mean outage length, min."""
        return float(sum(self.gap_lengths_min) / len(self.gap_lengths_min))

    def spans_multiple_samples(self, sampling_interval_d: float) -> bool:
        """Whether the longest observed outage can cover more than one scheduled sample."""
        return max(self.gap_lengths_min) / 1440.0 >= sampling_interval_d


class SensorSpec(_Frozen):
    """The declared model of one instrument or lab assay.

    ``channel`` names the truth quantity it measures
    (:data:`sim.observation.channels.CHANNEL_UNITS`); the spec fixes how that quantity is
    turned into a record: schedule, conventions, noise, drift, fouling, flatline,
    saturation, turnaround and missingness.
    """

    name: str = Field(description="Sensor id, e.g. 'gas_flow'; unique in the configuration")
    channel: str = Field(description="Truth channel measured (sim.observation.channels)")
    kind: Literal["online", "lab"] = Field(
        description="'online': an instrument sampled on an interval; 'lab': a scheduled assay"
    )
    unit: str = Field(description="Unit of the reported value")
    gas_convention: GasConvention = Field(
        default="none", description="Standard-conditions convention of a gas quantity"
    )
    solids_basis: SolidsBasis = Field(
        default="none", description="Wet or dry basis of a solids quantity"
    )
    sampling_interval_d: _Pos = Field(description="Days between samples, d")
    noise: NoiseModel
    drift: DriftModel | None = Field(default=None, description="Zero drift, if any")
    fouling: FoulingModel | None = Field(default=None, description="Fouling episodes, if any")
    flatline: EpisodeModel | None = Field(
        default=None, description="Flatline episodes (the reading holds its last value), if any"
    )
    saturation: SaturationModel | None = Field(default=None, description="Readable range, if any")
    source: str = Field(default="", description="Where the numbers come from")

    @model_validator(mode="after")
    def _conventions_declared(self) -> SensorSpec:
        gas = self.channel.startswith(("q_gas", "ch4_", "co2_", "h2_"))
        if gas and self.gas_convention == "none":
            raise ValueError(f"{self.name}: a gas channel must declare a gas_convention")
        if self.channel in ("ts", "vs") and self.solids_basis == "none":
            raise ValueError(f"{self.name}: a solids channel must declare a solids_basis")
        return self

    @model_validator(mode="after")
    def _episodes_are_observable(self) -> SensorSpec:
        """An episode shorter than the sampling interval is rounded up and inflates occupancy.

        The mask lasts ``max(1, round(mean_duration_d / dt))`` samples, so a declared 0.4 d
        episode on a daily sensor really lasts a full day and the realised occupancy is
        2.5x what ``hazard_per_d * mean_duration_d`` says — silently breaking an anchored
        flatline rate. Declare the duration in whole samples instead.
        """
        for field, model in (("fouling", self.fouling), ("flatline", self.flatline)):
            if model is not None and model.mean_duration_d < self.sampling_interval_d:
                raise ValueError(
                    f"{self.name}: {field} mean_duration_d {model.mean_duration_d} d is below "
                    f"the sampling interval {self.sampling_interval_d} d, so the episode would "
                    "be rounded up to one sample and its occupancy inflated"
                )
        return self


class TierSpec(_Frozen):
    """One instrumentation tier: which sensors are readable (§6.4).

    A tier is an **observation mask**: the underlying truth is identical across tiers, and
    a higher tier only adds channels. That containment is validated here and tested.

    The tier also carries the plant's **monitoring capability**, which the lead's decision
    of 2026-09-02 makes a tier property rather than a per-sensor one: how quickly the
    laboratory returns a result, how often instruments are recalibrated, and (through
    :class:`MissingnessPolicy`) how often a scheduled sample is simply lost. The truth is
    still identical across tiers; only the quality of the window onto it differs.
    """

    tier: Literal["A", "B", "C"]
    sensors: tuple[str, ...] = Field(description="Sensor ids readable at this tier")
    feed_assays: tuple[str, ...] = Field(
        description="Influent-generator assay names visible at this tier (sim.influent.generator)"
    )
    lab_turnaround_d: _NonNeg = Field(
        description="Days from sample to result for a lab assay at this tier, d (online = 0)"
    )
    recalibration_interval_d: _Pos = Field(
        description="Days between instrument recalibrations at this tier, d"
    )
    note: str = ""

    @model_validator(mode="after")
    def _unique(self) -> TierSpec:
        for field in ("sensors", "feed_assays"):
            values = getattr(self, field)
            if len(set(values)) != len(values):
                raise ValueError(f"{self.tier}: duplicate entries in {field}")
        return self


class ConditionThresholds(_Frozen):
    """When the condition flags that drive missingness are raised.

    Both triggers fire on the **hidden process state**, never on a reading. ``overload``:
    true VFA above ``vfa_surge_ratio`` times its trailing median over
    ``vfa_median_window_d`` days (lead's ruling B, 2026-09-09). ``foaming``: the gas rate
    above ``gas_surge_ratio`` times its trailing median over ``gas_median_window_d`` days
    **and** true VFA above ``foaming_vfa_ratio`` times the same trailing median the
    overload trigger uses (lead's ruling B3, 2026-09-10) — a foaming digester is one that
    is both gassing hard and acidifying. Every trailing median is over the samples
    *before* the current one, current excluded.

    ``fos_tac_overload`` and ``fos_tac_foaming`` are still here and are **not triggers**:
    they are the operator-visible thresholds on the titrimetric FOS/TAC, which a workflow
    can compute from the record it is given. Trigger and threshold are deliberately
    separate (ruling C): one is what the plant *is*, the other is what an operator would
    *say*. The foaming threshold in particular is structurally dead as a trigger — the
    titrimetric ratio has a bicarbonate floor near 0.13-0.14 and sits at 0.14-0.18 in
    every sound run — which is a measurement-model finding, recorded in the report and the
    card, not a reason to lower the number.
    """

    vfa_surge_ratio: _Pos = Field(
        description="True VFA over its trailing median needed for the overload flag, -"
    )
    vfa_median_window_d: _Pos = Field(
        description="Trailing window of the true-VFA median, d (excludes the current day)"
    )
    fos_tac_overload: _Pos = Field(
        description=(
            "OPERATOR-VISIBLE overload threshold on the titrimetric FOS/TAC, - "
            "(kg FOS as acetic acid per kg CaCO3). Reported, not a missingness trigger."
        )
    )
    fos_tac_foaming: _Pos = Field(
        description=(
            "OPERATOR-VISIBLE foaming threshold on the titrimetric FOS/TAC, -. Reported, "
            "not a missingness trigger, and never wired to one (ruling B3, 2026-09-10)."
        )
    )
    gas_surge_ratio: _Pos = Field(
        description="Gas rate over its trailing median needed for the foaming flag, -"
    )
    gas_median_window_d: _Pos = Field(
        description="Trailing window of the gas median, d (excludes the current day)"
    )
    foaming_vfa_ratio: _Pos = Field(
        description=(
            "True VFA over its trailing median (the overload trigger's own reference) "
            "also needed for the foaming flag, -"
        )
    )
    source: str = ""

    @model_validator(mode="after")
    def _ordered(self) -> ConditionThresholds:
        if self.gas_surge_ratio <= 1.0:
            raise ValueError("gas_surge_ratio must exceed 1 (a surge is above the median)")
        if self.vfa_surge_ratio <= 1.0:
            raise ValueError("vfa_surge_ratio must exceed 1 (a surge is above the median)")
        if self.foaming_vfa_ratio < 1.0:
            raise ValueError(
                "foaming_vfa_ratio must be at least 1 (foaming needs VFA ABOVE its median)"
            )
        return self


class ObservationConfig(_Frozen):
    """``configs/observation/sensors.yaml``: every sensor, the tiers and the flag rule."""

    version: int
    conditions: ConditionThresholds
    missingness: MissingnessPolicy
    historian: HistorianDropout
    sensors: dict[str, SensorSpec]
    tiers: dict[Literal["A", "B", "C"], TierSpec]

    @model_validator(mode="after")
    def _consistent(self) -> ObservationConfig:
        for key, spec in self.sensors.items():
            if spec.name != key:
                raise ValueError(f"sensor key {key!r} != name {spec.name!r}")
        for tier_id, tier in self.tiers.items():
            if tier.tier != tier_id:
                raise ValueError(f"tier key {tier_id!r} != declared tier {tier.tier!r}")
            unknown = set(tier.sensors) - set(self.sensors)
            if unknown:
                raise ValueError(f"tier {tier_id}: unknown sensors {sorted(unknown)}")
        # §6.4: tiers are nested masks - B adds to A, C adds to B
        for lower, upper in (("A", "B"), ("B", "C")):
            if lower in self.tiers and upper in self.tiers:
                missing = set(self.tiers[lower].sensors) - set(self.tiers[upper].sensors)
                if missing:
                    raise ValueError(
                        f"tier {upper} must contain every sensor of tier {lower}; "
                        f"missing {sorted(missing)}"
                    )
                missing = set(self.tiers[lower].feed_assays) - set(self.tiers[upper].feed_assays)
                if missing:
                    raise ValueError(
                        f"tier {upper} must contain every feed assay of tier {lower}; "
                        f"missing {sorted(missing)}"
                    )
        return self
