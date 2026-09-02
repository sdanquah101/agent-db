"""The fault-injection API: a scenario YAML becomes typed, per-layer directives (§6.1).

"Any scenario is a declarative YAML file specifying plant, tier, duration, fault type(s),
onset time, magnitude and the ground-truth label. The simulator logs hidden truth
alongside observations, in a separate file never exposed to workflows."

:func:`build_plan` reads a :class:`~scenarios.schema.Scenario`, validates every magnitude
against :mod:`sim.faults.schema`, and returns a :class:`FaultPlan` — one directive object
per layer, each consumed by the layer that owns it:

===============  ==========================================================
:class:`InfluentFaults`      :func:`sim.influent.generate_influent`
:class:`ParameterFaults`     :func:`parameter_segments`, then a segmented run
:class:`StateFaults`         :func:`apply_state_faults` on the initial state
:class:`StructureFaults`     :func:`truth_mixing`, :func:`fitted_extensions`
:class:`ObservationFaults`   :func:`sim.observation.observe`
:class:`WorkflowFaults`      the run harness and the tool registry
===============  ==========================================================

**Its own random stream.** Faults that need randomness (only the mislabelled-feed redraw)
draw from ``default_rng(fault_seed)``, a stream separate from the influent generator's and
the observation model's. Injecting a fault therefore cannot shift the baseline run's
draws: the same scenario seed with and without a fault gives two runs that differ *only*
by the fault, which is what makes a paired comparison meaningful (tested).

Nothing here writes files or reads ``runs/<id>/truth/`` (CLAUDE.md rule 1).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np

from scenarios.schema import Fault, FaultType, Scenario
from sim.adm1.schema import ADM1Parameters
from sim.faults.schema import FAULT_SEMANTICS, semantics_for
from sim.plants.mixing import MixingStructure

__all__ = [
    "FaultPlan",
    "InfluentFaults",
    "MislabelledFeed",
    "ObservationFaults",
    "ParameterFaults",
    "StateFaults",
    "StructureFaults",
    "UnrecordedDelivery",
    "WorkflowFaults",
    "apply_state_faults",
    "build_plan",
    "fitted_extensions",
    "parameter_segments",
    "truth_mixing",
]

#: Exchange coefficient of the stagnant zone when imperfect mixing is injected, 1/d.
#: PR #7's prior band was 0.2-2 d^-1; the mid-point is used and the scenario sizes the
#: fault through the stagnant fraction alone (decisions log).
MIXING_EXCHANGE_PER_D = 1.0

#: Bypass as a fraction of the stagnant fraction (a fifth), so one magnitude sizes both.
MIXING_BYPASS_OF_STAGNANT = 0.2


def _window(fault: Fault, duration_days: float) -> tuple[float, float]:
    """``(onset, end)`` of a fault in days, clipped to the run."""
    end = duration_days if fault.duration_days is None else fault.onset_day + fault.duration_days
    return float(fault.onset_day), float(min(end, duration_days))


@dataclass(frozen=True)
class MislabelledFeed:
    """One feed whose true fractionation departs from the catalogue for a window."""

    feed_id: str
    onset_d: float
    end_d: float
    concentration: float
    """Dirichlet concentration of the redraw; smaller = further from the catalogue."""


@dataclass(frozen=True)
class UnrecordedDelivery:
    """An extra delivery that never enters the operator's log."""

    feed_id: str
    day: int
    multiple_of_median: float


@dataclass(frozen=True)
class MoistureRamp:
    """A relative ramp on one feed's total solids across a window."""

    feed_id: str
    onset_d: float
    end_d: float
    relative_change: float
    """Total relative change at the end of the window; negative = wetter."""


@dataclass(frozen=True)
class InfluentFaults:
    """Directives for the influent generator (truth label *influent*)."""

    mislabelled: tuple[MislabelledFeed, ...] = ()
    unrecorded: tuple[UnrecordedDelivery, ...] = ()
    moisture: tuple[MoistureRamp, ...] = ()
    seed: int = 0
    """Seed of the fault layer's own stream (used by the mislabelled redraw)."""

    def __bool__(self) -> bool:
        """Whether any influent fault is present."""
        return bool(self.mislabelled or self.unrecorded or self.moisture)


@dataclass(frozen=True)
class ParameterFaults:
    """Truth-model parameter changes at an onset day (truth label *parameter*)."""

    multipliers: tuple[tuple[float, str, float], ...] = ()
    """``(onset_day, parameter_name, multiplier)``, sorted by onset."""

    def __bool__(self) -> bool:
        """Whether any parameter change is present."""
        return bool(self.multipliers)


@dataclass(frozen=True)
class StateFaults:
    """Initial-state corruption (truth label *state*)."""

    biomass_multiplier: float = 1.0

    def __bool__(self) -> bool:
        """Whether the initial state is corrupted."""
        return self.biomass_multiplier != 1.0


@dataclass(frozen=True)
class StructureFaults:
    """Structural mismatch: a mechanism the truth has and the fitted model must not.

    Truth label *structural* (§6.3, Level 6).
    """

    omit_from_fitted: tuple[str, ...] = ()
    """Extension names the fitted model must not carry (the truth keeps them)."""
    stagnant_fraction: float = 0.0
    """Stagnant volume fraction of the truth reactor; 0 = ideal CSTR."""

    def __bool__(self) -> bool:
        """Whether any structural fault is present."""
        return bool(self.omit_from_fitted) or self.stagnant_fraction > 0.0


@dataclass(frozen=True)
class ObservationFaults:
    """Directives for the observation model (truth label *sensor*, or Level-1 noise).

    ``noise_scale`` and ``missing_scale`` act on every sensor; ``stress_scale`` acts on the
    conditional multipliers only. ``ramps``, ``scales`` and ``flatlines`` are per sensor.
    """

    noise_scale: float = 1.0
    missing_scale: float = 1.0
    stress_scale: float = 1.0
    ramps: dict[str, tuple[float, float]] = field(default_factory=dict)
    """sensor -> (onset day, rate in the sensor's unit per day)."""
    scales: dict[str, tuple[float, float]] = field(default_factory=dict)
    """sensor -> (onset day, multiplicative factor from that day)."""
    flatlines: dict[str, tuple[float, float]] = field(default_factory=dict)
    """sensor -> (onset day, end day) of a forced flatline episode."""

    def __bool__(self) -> bool:
        """Whether any observation fault is present."""
        return bool(
            self.noise_scale != 1.0
            or self.missing_scale != 1.0
            or self.stress_scale != 1.0
            or self.ramps
            or self.scales
            or self.flatlines
        )


@dataclass(frozen=True)
class WorkflowFaults:
    """Level-8 faults the run harness applies: neither truth nor observation changes."""

    tool_failure: tuple[tuple[str, float], ...] = ()
    """``(tool name, failure probability)``."""
    adversarial_log_note: bool = False

    def __bool__(self) -> bool:
        """Whether any workflow fault is present."""
        return bool(self.tool_failure or self.adversarial_log_note)


@dataclass(frozen=True)
class FaultPlan:
    """Every fault of a scenario, routed to the layer that applies it."""

    scenario_id: str
    duration_days: float
    influent: InfluentFaults
    parameter: ParameterFaults
    state: StateFaults
    structure: StructureFaults
    observation: ObservationFaults
    workflow: WorkflowFaults

    @property
    def layers(self) -> tuple[str, ...]:
        """Layers this plan touches, sorted."""
        present = {
            "influent": bool(self.influent),
            "parameter": bool(self.parameter),
            "state": bool(self.state),
            "structure": bool(self.structure),
            "observation": bool(self.observation),
            "workflow": bool(self.workflow),
        }
        return tuple(sorted(name for name, on in present.items() if on))


def build_plan(
    scenario: Scenario, feed_ids: Sequence[str], fault_seed: int | None = None
) -> FaultPlan:
    """Route a scenario's faults into per-layer directives.

    Args:
        scenario: The validated scenario.
        feed_ids: The plant's feed ids, in the plant's own order. An influent fault with
            no explicit target acts on the **last** id, which is the co-substrate for
            every frozen plant (Plant A silage, Plant B FOG); a scenario that means
            another feed says so in its notes and the run layer overrides.
        fault_seed: Seed of the fault layer's own stream; defaults to the scenario seed
            plus one, or 0 when the scenario carries no seed.

    Returns:
        The plan.

    Raises:
        ValueError: If a magnitude is outside the admissible range of its fault type, or
            the scenario has no feeds to act on for an influent fault.
    """
    mislabelled: list[MislabelledFeed] = []
    unrecorded: list[UnrecordedDelivery] = []
    moisture: list[MoistureRamp] = []
    multipliers: list[tuple[float, str, float]] = []
    biomass = 1.0
    omit: list[str] = []
    stagnant = 0.0
    noise_scale = missing_scale = stress_scale = 1.0
    ramps: dict[str, tuple[float, float]] = {}
    scales: dict[str, tuple[float, float]] = {}
    flatlines: dict[str, tuple[float, float]] = {}
    tools: list[tuple[str, float]] = []
    note = False

    target_feed = feed_ids[-1] if feed_ids else None

    for fault in scenario.faults:
        spec = semantics_for(fault.type)
        spec.validate_magnitude(fault.magnitude)
        onset, end = _window(fault, scenario.duration_days)

        if spec.layer == "influent" and target_feed is None:
            raise ValueError(f"{fault.type.value} needs a feed, but the plant declares none")

        match fault.type:
            case FaultType.SENSOR_NOISE:
                noise_scale *= fault.magnitude
            case FaultType.RANDOM_GAPS:
                missing_scale *= fault.magnitude
            case FaultType.INFORMATIVE_MISSINGNESS:
                stress_scale *= fault.magnitude
            case FaultType.PH_ELECTRODE_DRIFT:
                ramps[spec.target] = (onset, fault.magnitude)
            case FaultType.GAS_METER_SCALE:
                scales[spec.target] = (onset, fault.magnitude)
            case FaultType.CH4_ANALYSER_FLATLINE:
                flatlines[spec.target] = (onset, end)
            case FaultType.FEED_MISLABELLED:
                mislabelled.append(
                    MislabelledFeed(
                        feed_id=str(target_feed),
                        onset_d=onset,
                        end_d=end,
                        concentration=fault.magnitude,
                    )
                )
            case FaultType.UNRECORDED_DELIVERY:
                unrecorded.append(
                    UnrecordedDelivery(
                        feed_id=str(target_feed),
                        day=int(onset),
                        multiple_of_median=fault.magnitude,
                    )
                )
            case FaultType.MOISTURE_DRIFT:
                moisture.append(
                    MoistureRamp(
                        feed_id=str(target_feed),
                        onset_d=onset,
                        end_d=end,
                        relative_change=fault.magnitude,
                    )
                )
            case FaultType.BIOMASS_MISINITIALISED:
                biomass *= fault.magnitude
            case FaultType.AMMONIA_INHIBITION_SHIFT | FaultType.HYDROLYSIS_REGIME_CHANGE:
                for name in spec.target.split(","):
                    multipliers.append((onset, name, fault.magnitude))
            case FaultType.OMITTED_SAO | FaultType.OMITTED_PRECIPITATION:
                omit.append(spec.target)
            case FaultType.IMPERFECT_MIXING:
                stagnant = max(stagnant, fault.magnitude)
            case FaultType.TOOL_FAILURE:
                tools.append((spec.target, fault.magnitude))
            case FaultType.ADVERSARIAL_LOG_NOTE:
                note = True

    seed = fault_seed
    if seed is None:
        seed = 0 if scenario.seed is None else scenario.seed + 1

    return FaultPlan(
        scenario_id=scenario.id,
        duration_days=scenario.duration_days,
        influent=InfluentFaults(
            mislabelled=tuple(mislabelled),
            unrecorded=tuple(unrecorded),
            moisture=tuple(moisture),
            seed=int(seed),
        ),
        parameter=ParameterFaults(multipliers=tuple(sorted(multipliers))),
        state=StateFaults(biomass_multiplier=biomass),
        structure=StructureFaults(
            omit_from_fitted=tuple(sorted(set(omit))), stagnant_fraction=stagnant
        ),
        observation=ObservationFaults(
            noise_scale=noise_scale,
            missing_scale=missing_scale,
            stress_scale=stress_scale,
            ramps=ramps,
            scales=scales,
            flatlines=flatlines,
        ),
        workflow=WorkflowFaults(tool_failure=tuple(sorted(tools)), adversarial_log_note=note),
    )


# ------------------------------------------------------------------ appliers


def parameter_segments(
    plan: FaultPlan, params: ADM1Parameters
) -> list[tuple[float, float, ADM1Parameters]]:
    """Integration segments and the parameters that hold in each.

    A parameter fault changes the truth model at its onset day, so the run is integrated
    in segments and the state is carried across. With no parameter fault this is one
    segment over the whole run.

    Returns:
        ``[(t_start, t_end, params), ...]`` covering ``[0, duration_days]``.

    Raises:
        ValueError: If a multiplier names a parameter that is not in the kinetics group.
    """
    onsets = sorted({onset for onset, _, _ in plan.parameter.multipliers})
    boundaries = [0.0, *[o for o in onsets if 0.0 < o < plan.duration_days], plan.duration_days]
    segments = []
    for start, end in pairwise(boundaries):
        updates: dict[str, float] = {}
        for onset, name, multiplier in plan.parameter.multipliers:
            if onset <= start:
                if not hasattr(params.kinetics, name):
                    raise ValueError(f"{name!r} is not a kinetic parameter")
                base = getattr(params.kinetics, name)
                updates[name] = updates.get(name, base) * multiplier
        kinetics = params.kinetics.model_copy(update=updates) if updates else params.kinetics
        segments.append((start, end, params.model_copy(update={"kinetics": kinetics})))
    return segments


def apply_state_faults(y0: np.ndarray, plan: FaultPlan, state_names: Sequence[str]) -> np.ndarray:
    """The initial state with the plan's state faults applied.

    Every biomass state (``X_su`` … ``X_h2`` and the SAO biomass when present) is scaled
    by ``biomass_multiplier``; the array is copied, never modified in place.
    """
    y = np.array(y0, dtype=float, copy=True)
    if not plan.state:
        return y
    biomass = [
        i
        for i, name in enumerate(state_names)
        if name in {"X_su", "X_aa", "X_fa", "X_c4", "X_pro", "X_ac", "X_h2", "X_sao"}
    ]
    y[biomass] *= plan.state.biomass_multiplier
    return y


def truth_mixing(plan: FaultPlan) -> MixingStructure:
    """The truth reactor's mixing structure for this plan.

    An ``imperfect_mixing`` fault sizes the stagnant zone; the bypass is
    :data:`MIXING_BYPASS_OF_STAGNANT` of it and the exchange is
    :data:`MIXING_EXCHANGE_PER_D`, so one magnitude sizes the whole non-ideality. With no
    such fault this is the ideal CSTR the plant contract declares.
    """
    phi = plan.structure.stagnant_fraction
    if phi <= 0.0:
        return MixingStructure.cstr()
    return MixingStructure(
        bypass_fraction=phi * MIXING_BYPASS_OF_STAGNANT,
        stagnant_fraction=phi,
        exchange_rate=MIXING_EXCHANGE_PER_D,
    )


def fitted_extensions(plan: FaultPlan, truth_extensions: Sequence[str]) -> tuple[str, ...]:
    """Extensions the *fitted* model may use: the truth's, less the omitted ones.

    The truth model always keeps every extension its plant declares; a structural
    scenario removes it from the fitted model only (§6.3, Level 6).
    """
    omitted = set(plan.structure.omit_from_fitted)
    return tuple(name for name in truth_extensions if name not in omitted)


def declared_faults(scenario: Scenario) -> dict[str, list[str]]:
    """Fault ids grouped by layer, for a run manifest or a scenario report."""
    out: dict[str, list[str]] = {}
    for fault in scenario.faults:
        out.setdefault(FAULT_SEMANTICS[fault.type].layer, []).append(fault.type.value)
    return {layer: sorted(names) for layer, names in sorted(out.items())}
