"""Compile a scenario's declared faults into truth variants, layer by layer.

:func:`compile_faults` turns the ``faults`` block of a scenario
(:class:`scenarios.schema.Scenario`, the Appendix-B contract) into a
:class:`CompiledFaults` record: the sensor faults the observation model consumes, the
per-feed modifiers the influent generator consumes, the initial-state multipliers, the
bounded time-varying truth parameters, the structural variant (which model the *fitted*
side gets, and the reactor's mixing structure) and the workflow faults that are carried
for the tool registry.

**Everything here is returned as data.** Nothing is written: the run harness owns
``runs/<id>/truth/`` (CLAUDE.md rule 1), and this package neither reads nor writes it.

**The truth's physics are never edited to inject a structural fault.** ``omitted_sao``
and ``omitted_precipitation`` leave the truth model exactly as the plant declares it and
remove the extension from :attr:`StructuralVariant.fitted_extensions` — the fitted model
is the one that is wrong, which is the whole point of proposal §6.1 ("the extension
exists so that the fitted model is structurally wrong by design"). ``imperfect_mixing`` is
the one structural fault that does change the truth's *reactor*, through the two-zone
variant that the frozen plant decision reserved for exactly this scenario
(``sim/plants/mixing.py``; decision 2026-09-02, answer 6).

Magnitudes are checked against the bounds declared in ``configs/faults/faults.yaml``
before anything is built, so a scenario cannot move a truth parameter arbitrarily far.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from scenarios.schema import Fault, FaultType, Scenario
from sim.adm1.schema import ADM1Parameters
from sim.faults.schema import (
    FAULT_LAYER,
    FAULT_MAGNITUDE,
    FaultLayer,
    FaultsConfig,
)
from sim.influent.generator import FeedModifier
from sim.influent.schema import FRACTION_NAMES, CODFractionation, FeedFractionationCatalogue
from sim.observe.schema import SensorEffect, SensorFault
from sim.plants.mixing import MixingStructure
from sim.plants.schema import PlantConfig

__all__ = [
    "CompiledFaults",
    "ParameterSchedule",
    "StateVariant",
    "StructuralVariant",
    "WorkflowFault",
    "compile_faults",
    "magnitude_table",
    "mislabelled_fractionation",
]


@dataclass(frozen=True)
class ParameterSchedule:
    """Bounded, time-varying truth parameters (the Level-5 faults).

    A parameter fault multiplies a group of parameters by a factor that is reached either
    as a step (a feed particle-size change) or linearly over an acclimation time (an
    ammonia-inhibition shift), and returns to one when the episode ends. The schedule is
    a *function of time*, and :meth:`breakpoints` gives the times at which the truth
    model must be restarted or re-compiled.
    """

    base: ADM1Parameters
    """The unfaulted truth parameters."""
    factors: tuple[tuple[str, tuple[str, ...], float, float, float, float], ...] = ()
    """``(group, parameter names, factor, onset_d, transition_d, end_d)`` per fault."""

    def factor_at(self, t: float) -> dict[tuple[str, str], float]:
        """The multiplier on every affected parameter at time ``t``, d."""
        out: dict[tuple[str, str], float] = {}
        for group, names, factor, onset, transition, end in self.factors:
            if t < onset or t >= end:
                continue
            ramp = min(1.0, (t - onset) / transition) if transition > 0.0 else 1.0
            value = 1.0 + ramp * (factor - 1.0)
            for name in names:
                out[(group, name)] = out.get((group, name), 1.0) * value
        return out

    def at(self, t: float) -> ADM1Parameters:
        """The truth parameters in force at time ``t``, d (a copy; ``base`` is untouched)."""
        factors = self.factor_at(t)
        if not factors:
            return self.base
        updates: dict[str, dict[str, float]] = {}
        for (group, name), factor in factors.items():
            current = getattr(getattr(self.base, group), name)
            updates.setdefault(group, {})[name] = current * factor
        groups = {
            group: getattr(self.base, group).model_copy(update=update)
            for group, update in updates.items()
        }
        return self.base.model_copy(update=groups)

    def breakpoints(
        self, t_span: tuple[float, float], ramp_step_d: float = 1.0
    ) -> tuple[float, ...]:
        """Times at which the parameters change, inside ``t_span``.

        Onsets and ends are exact; a ramp is discretised at ``ramp_step_d`` so the run
        harness can integrate a piecewise-constant parameter trajectory (the truth model
        takes one parameter set per segment).
        """
        t0, t1 = t_span
        times = {t0}
        for _, _, _, onset, transition, end in self.factors:
            for point in (onset, end):
                if t0 < point < t1:
                    times.add(point)
            if transition > 0.0:
                step = onset + ramp_step_d
                while step < min(onset + transition, t1):
                    if step > t0:
                        times.add(step)
                    step += ramp_step_d
        return tuple(sorted(times))

    @property
    def constant(self) -> bool:
        """True when no parameter fault is scheduled."""
        return not self.factors


@dataclass(frozen=True)
class StateVariant:
    """Multipliers applied to the truth run's initial state (the Level-4 state fault)."""

    multipliers: Mapping[str, float] = field(default_factory=dict)
    """State name -> factor; states not listed are unchanged."""

    def apply(self, y0: np.ndarray, state_names: Sequence[str]) -> np.ndarray:
        """A copy of ``y0`` with the multipliers applied.

        Raises:
            ValueError: If a multiplier names a state the model does not have, or the
                shapes disagree.
        """
        y0 = np.asarray(y0, dtype=float)
        if y0.shape != (len(state_names),):
            raise ValueError(f"y0 has shape {y0.shape}, expected ({len(state_names)},)")
        unknown = set(self.multipliers) - set(state_names)
        if unknown:
            raise ValueError(f"state fault names unknown states: {sorted(unknown)}")
        out = y0.copy()
        index = {name: i for i, name in enumerate(state_names)}
        for name, factor in self.multipliers.items():
            out[index[name]] *= factor
        return out


@dataclass(frozen=True)
class StructuralVariant:
    """Which model each side gets, and how the truth reactor mixes (the Level-6 faults)."""

    truth_extensions: tuple[str, ...]
    """Extensions the TRUTH runs — always the plant's own list, never reduced here."""
    fitted_extensions: tuple[str, ...]
    """Extensions the FITTED model is allowed; an omission fault removes one from here."""
    mixing: MixingStructure
    """The truth reactor's mixing structure; the ideal CSTR unless a mixing fault applies."""

    @property
    def omitted(self) -> tuple[str, ...]:
        """Extensions the truth has and the fitted model does not."""
        return tuple(e for e in self.truth_extensions if e not in self.fitted_extensions)


@dataclass(frozen=True)
class WorkflowFault:
    """A Level-8 fault carried for the tool registry and the run layer, not applied here."""

    type: FaultType
    onset_d: float
    magnitude: float
    duration_d: float | None
    target: str = ""
    """Tool the failure applies to (``tool_failure``)."""
    note: str = ""
    """The operator note to inject (``adversarial_log_note``)."""


@dataclass(frozen=True)
class CompiledFaults:
    """A scenario's faults, compiled to the layer each is applied at. Hidden truth."""

    declared: tuple[Fault, ...]
    """The scenario's own declaration, unchanged."""
    layers: Mapping[FaultType, FaultLayer]
    """Which layer each declared fault went to (the answer key's provenance)."""
    sensor: tuple[SensorFault, ...]
    """Passed to :func:`sim.observe.model.observe`."""
    influent: Mapping[str, FeedModifier]
    """Passed to :func:`sim.influent.generator.generate_influent` as ``modifiers``."""
    state: StateVariant
    """Applied to the truth run's initial state."""
    parameters: ParameterSchedule
    """The truth model's parameters as a function of time."""
    structural: StructuralVariant
    """Truth vs fitted model, and the truth reactor's mixing."""
    workflow: tuple[WorkflowFault, ...]
    """Carried for the registry; nothing in the simulator honours these."""

    @property
    def touches_truth(self) -> bool:
        """True when any layer other than the sensor and workflow layers is affected."""
        return bool(
            self.influent
            or self.state.multipliers
            or not self.parameters.constant
            or self.structural.omitted
            or not self.structural.mixing.ideal
        )


def mislabelled_fractionation(
    fractionation: CODFractionation, share: float, from_names: Sequence[str], to_name: str
) -> CODFractionation:
    """Move a COD share from the degradable classes into another class.

    The Level-3 "feed mislabelled" fault: the *true* fractionation of one feed differs
    from the catalogue an operator reads. ``share`` is taken from ``from_names`` in
    proportion to their current size (so a feed with no lipid does not acquire a negative
    one) and added to ``to_name``; the six fractions still sum to one.

    Raises:
        ValueError: If the share exceeds what the source classes carry, or a name is not
            a COD fraction.
    """
    unknown = (set(from_names) | {to_name}) - set(FRACTION_NAMES)
    if unknown:
        raise ValueError(f"not COD fractions: {sorted(unknown)}")
    values = {name: getattr(fractionation, name) for name in FRACTION_NAMES}
    available = sum(values[name] for name in from_names)
    if share > available:
        raise ValueError(
            f"cannot move {share} of COD out of {list(from_names)}, which carry {available}"
        )
    if available > 0.0:
        for name in from_names:
            values[name] -= share * values[name] / available
    values[to_name] += share
    return CODFractionation(**values)


def _sensor_faults(fault: Fault, config: FaultsConfig) -> list[SensorFault]:
    spec = config.sensor[fault.type]
    magnitude = spec.magnitude.check(fault.magnitude, fault.type.value)
    duration = fault.duration_days if fault.duration_days is not None else spec.default_duration_d
    return [
        SensorFault(
            channel=spec.channel,
            effect=SensorEffect(spec.effect),
            onset_d=fault.onset_day,
            magnitude=magnitude,
            duration_d=duration,
            label=fault.type.value,
        )
    ]


def _influent_modifier(fault: Fault, config: FaultsConfig, n_days: int) -> FeedModifier:
    spec = config.influent[fault.type]
    magnitude = spec.magnitude.check(fault.magnitude, fault.type.value)
    day = np.arange(n_days, dtype=float)
    end = n_days if fault.duration_days is None else fault.onset_day + fault.duration_days
    active = (day >= fault.onset_day) & (day < end)
    if spec.transition_d > 0.0:
        ramp = np.clip((day - fault.onset_day) / spec.transition_d, 0.0, 1.0)
    else:
        ramp = np.ones(n_days)
    ramp = np.where(active, ramp, 0.0)

    if fault.type is FaultType.MOISTURE_DRIFT:
        return FeedModifier(ts_factor=1.0 + ramp * (magnitude - 1.0))
    if fault.type is FaultType.UNRECORDED_DELIVERY:
        return FeedModifier(extra_unrecorded_probability=ramp * magnitude)
    if fault.type is FaultType.FEED_MISLABELLED:
        raise ValueError("feed mislabelling is compiled with the drawn true fractionation")
    raise ValueError(f"{fault.type.value} is not an influent fault")


def _affected_feed(plant: PlantConfig, catalogue: FeedFractionationCatalogue) -> str:
    """The feed an influent fault acts on: the plant's largest batch feed, else the first.

    A scenario names a plant and a fault, not a feed (Appendix B has no feed field), so
    the choice has to be a stated rule. A batch-delivered feed is the one a plant can
    plausibly mis-log or mis-characterise (a pumped, metered sludge line is not), and the
    largest such feed makes the fault detectable at all; with no batch feed the first feed
    in sorted order is used.
    """
    batch = sorted(
        (f for f in plant.feeds if f.delivery == "batch"),
        key=lambda f: (
            (f.volume_m3_d.median if f.volume_m3_d is not None else 0.0)
            * catalogue.feeds[f.name].density
            + (f.mass_t_fm_d.median * 1000.0 if f.mass_t_fm_d is not None else 0.0)
        ),
        reverse=True,
    )
    if batch:
        return batch[0].name
    return sorted(f.name for f in plant.feeds)[0]


def compile_faults(
    scenario: Scenario,
    config: FaultsConfig,
    plant: PlantConfig,
    catalogue: FeedFractionationCatalogue,
    params: ADM1Parameters,
    *,
    n_days: int | None = None,
    true_fractionations: Mapping[str, CODFractionation] | None = None,
) -> CompiledFaults:
    """Compile a scenario's faults into the variants each layer applies.

    Args:
        scenario: The validated scenario (its ``faults`` block is the declaration).
        config: ``configs/faults/faults.yaml``.
        plant: The plant the scenario runs on (its declared truth extensions are the
            truth's; a structural fault only removes one from the *fitted* side).
        catalogue: The feed catalogue (an influent fault needs the feed's fractionation).
        params: The truth parameters before any parameter fault.
        n_days: Horizon in whole days; defaults to ``ceil(scenario.duration_days)``.
        true_fractionations: The run's drawn true fractionations, needed to compile a
            ``feed_mislabelled`` fault (the mislabel is a shift *of that draw*). Without
            them, the catalogue fractionation is shifted instead and the run's own draw
            is discarded for that feed.

    Returns:
        The compiled faults, as data.

    Raises:
        ValueError: If a magnitude is outside its configured bounds, or a fault type is
            not handled at the layer :data:`~sim.faults.schema.FAULT_LAYER` assigns it.
    """
    horizon = int(np.ceil(scenario.duration_days)) if n_days is None else int(n_days)
    sensor: list[SensorFault] = []
    influent: dict[str, FeedModifier] = {}
    multipliers: dict[str, float] = {}
    factors: list[tuple[str, tuple[str, ...], float, float, float, float]] = []
    truth_extensions = tuple(plant.truth_model.extensions)
    fitted_extensions = list(truth_extensions)
    mixing = MixingStructure.cstr()
    workflow: list[WorkflowFault] = []
    layers: dict[FaultType, FaultLayer] = {}

    for fault in scenario.faults:
        layer = FAULT_LAYER[fault.type]
        layers[fault.type] = layer
        end = (
            float(scenario.duration_days)
            if fault.duration_days is None
            else fault.onset_day + fault.duration_days
        )
        if layer is FaultLayer.SENSOR:
            sensor.extend(_sensor_faults(fault, config))
        elif layer is FaultLayer.INFLUENT:
            feed_id = _affected_feed(plant, catalogue)
            spec = config.influent[fault.type]
            if fault.type is FaultType.FEED_MISLABELLED:
                share = spec.magnitude.check(fault.magnitude, fault.type.value)
                drawn = (true_fractionations or {}).get(
                    feed_id, catalogue.feeds[feed_id].fractionation
                )
                influent[feed_id] = FeedModifier(
                    fractionation=mislabelled_fractionation(
                        drawn, share, spec.shift_from, spec.shift_to
                    )
                )
            else:
                influent[feed_id] = _influent_modifier(fault, config, horizon)
        elif layer is FaultLayer.STATE:
            state_spec = config.state[fault.type]
            magnitude = state_spec.magnitude.check(fault.magnitude, fault.type.value)
            for name in state_spec.states:
                multipliers[name] = multipliers.get(name, 1.0) * magnitude
        elif layer is FaultLayer.PARAMETER:
            p_spec = config.parameter[fault.type]
            magnitude = p_spec.magnitude.check(fault.magnitude, fault.type.value)
            factors.append(
                (
                    p_spec.group,
                    p_spec.parameters,
                    magnitude,
                    fault.onset_day,
                    p_spec.transition_d,
                    end,
                )
            )
        elif layer is FaultLayer.STRUCTURAL:
            s_spec = config.structural[fault.type]
            if s_spec.omit_extension is not None:
                if s_spec.omit_extension not in truth_extensions:
                    raise ValueError(
                        f"{fault.type.value}: plant {plant.id} does not run the "
                        f"{s_spec.omit_extension!r} extension, so the fitted model cannot "
                        "omit it"
                    )
                if s_spec.omit_extension in fitted_extensions:
                    fitted_extensions.remove(s_spec.omit_extension)
            else:
                assert s_spec.magnitude is not None  # validated by the config schema
                stagnant = s_spec.magnitude.check(fault.magnitude, fault.type.value)
                mixing = MixingStructure(
                    bypass_fraction=s_spec.bypass_fraction or 0.0,
                    stagnant_fraction=stagnant,
                    exchange_rate=s_spec.exchange_rate or 0.0,
                )
        else:
            w_spec = config.workflow[fault.type]
            magnitude = w_spec.magnitude.check(fault.magnitude, fault.type.value)
            note = ""
            if w_spec.notes:
                note = w_spec.notes[int(magnitude) % len(w_spec.notes)]
            workflow.append(
                WorkflowFault(
                    type=fault.type,
                    onset_d=fault.onset_day,
                    magnitude=magnitude,
                    duration_d=fault.duration_days,
                    target=w_spec.target,
                    note=note,
                )
            )

    return CompiledFaults(
        declared=tuple(scenario.faults),
        layers=layers,
        sensor=tuple(sensor),
        influent=influent,
        state=StateVariant(multipliers=multipliers),
        parameters=ParameterSchedule(base=params, factors=tuple(factors)),
        structural=StructuralVariant(
            truth_extensions=truth_extensions,
            fitted_extensions=tuple(fitted_extensions),
            mixing=mixing,
        ),
        workflow=tuple(workflow),
    )


def magnitude_table() -> tuple[tuple[str, str, str, str], ...]:
    """The benchmark card's fault table: ``(fault, layer, magnitude unit, meaning)``."""
    return tuple(
        (
            fault.value,
            FAULT_LAYER[fault].value,
            FAULT_MAGNITUDE[fault].unit,
            FAULT_MAGNITUDE[fault].meaning,
        )
        for fault in FaultType
    )
