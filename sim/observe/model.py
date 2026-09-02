"""The observation model of proposal §6.1: truth in, an operator's record out.

    "Every sensor has a declared model: sampling interval, noise, drift (random walk
    with bounds), fouling episodes, flatlining, saturation, and a wet/dry and
    standard-conditions convention. Lab assays have method noise, turnaround delay and
    schedule. Missingness is generated *conditionally* — instruments are more likely to
    fail during foaming and overload — so that naive interpolation destroys information."

:func:`observe` takes the truth series (:mod:`sim.observe.truth`), the catalogue and the
instrument statistics (``configs/observe/observation.yaml``), a tier and a seed, and
returns what the operator sees (:class:`ObservedRun`) beside the hidden record of what
the instruments actually did (:class:`ObservationTruth`). It writes nothing: the run
layer owns ``runs/<id>/truth/`` (CLAUDE.md rule 1).

**Tiers are masks, not catalogues** (§6.4). One catalogue holds every channel; Tier A
sees the channels declared at Tier A, Tier B those plus its own, Tier C everything. The
underlying truth is identical.

**The chain applied to one sample**, in this order (each step is a declared model, and
the hidden record keeps the intermediate flags):

1. the true value, linearly interpolated onto the sample time;
2. *fouling* — ``gain x value + offset`` while the instrument is dirty;
3. *drift* — a bounded random walk, added (``offset`` mode) or applied as a gain;
4. *injected sensor faults* — the scale, offset, drift and noise effects of the scenario
   (:class:`~sim.observe.schema.SensorFault`), in that fixed order;
5. *measurement noise* — ``value x (1 + cv z) + sd_abs z`` on one standard normal draw;
6. *saturation* — clipped to the instrument's range, and flagged;
7. *resolution* — rounded to the recorded quantisation;
8. *flatline* — last, because a flat-lined instrument repeats the value it last
   *reported*: inside an episode (spontaneous or injected) the sample takes the previous
   sample's reported value, and everything above it is discarded.

Then the sample is dropped with the conditional missing probability of
:class:`~sim.observe.schema.MissingnessModel`: ``p = min(p_max, p_base exp(sensitivity x
stress(t)))`` where ``stress`` counts doublings of total VFA above, and of the gas rate
away from, the run's own median. A dropped sensor sample is ``NaN`` in the series; a
dropped assay produces no record at all.

**Randomness** (CLAUDE.md rule 4). One ``numpy.random.SeedSequence(seed)`` per run, with
one child stream per **catalogue** channel, keyed by the channel's index in the sorted
catalogue (``spawn_key=(i,)``). Within a channel the stream is consumed in a fixed order:
a block of ``n_samples`` draws for each of noise, drift, fouling onset, flatline onset and
missingness — *always consumed*, whatever the instrument's models say, so that turning a
model on cannot shift the rest of that channel.

Keying the child stream on the *catalogue* rather than on the tier is what makes a tier a
true mask: the pH series of a Tier-A run is bit for bit the pH series of the Tier-C run
with the same seed, and a channel's realisation does not move when another channel is
added, removed or reconfigured (all tested).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from sim.observe.schema import (
    ChannelKind,
    ChannelSpec,
    InstrumentModel,
    ObservationConfig,
    SensorEffect,
    SensorFault,
    StressCoupling,
)
from sim.observe.truth import TruthChannels

__all__ = [
    "AssayResult",
    "Episode",
    "Observation",
    "ObservationTruth",
    "ObservedRun",
    "SensorSeries",
    "observe",
    "sample_times",
    "stress_indicator",
]

_DRAW_BLOCKS: tuple[str, ...] = ("noise", "drift", "fouling", "flatline", "missing")
"""The per-channel random blocks, in the order they are drawn."""


@dataclass(frozen=True)
class SensorSeries:
    """One observed sensor channel as the operator's historian holds it."""

    channel: str
    unit: str
    basis: str
    t: np.ndarray
    """Sample times, d."""
    value: np.ndarray
    """Reported values in ``unit``; ``NaN`` where the sample is missing."""
    missing: np.ndarray
    """Boolean: the sample was lost."""
    standard_conditions: str | None = None
    """Name of the reference conditions of a gas quantity (CLAUDE.md rule 6)."""

    @property
    def observed_fraction(self) -> float:
        """Fraction of scheduled samples that carry a value, -."""
        return float(np.mean(~self.missing)) if self.missing.size else 0.0


@dataclass(frozen=True)
class AssayResult:
    """One laboratory result as the operator receives it (method noise and lag applied)."""

    channel: str
    sample_day: int
    report_day: int
    value: float
    unit: str
    basis: str


@dataclass(frozen=True)
class Episode:
    """A window in which an instrument misbehaved. Hidden truth."""

    channel: str
    kind: str
    """``fouling``, ``flatline`` or the label of an injected fault."""
    start_d: float
    end_d: float


@dataclass(frozen=True)
class ObservedRun:
    """What a workflow may see at this tier."""

    plant_id: str
    tier: str
    sensors: dict[str, SensorSeries]
    assays: tuple[AssayResult, ...]
    """Ordered by report day, then channel."""
    feed_log_kg_wet_d: dict[str, np.ndarray] = field(default_factory=dict)
    """The influent generator's operator feed log, passed through at Tier A and above."""


@dataclass(frozen=True)
class ObservationTruth:
    """What the instruments actually did. Hidden truth; the run layer writes it."""

    plant_id: str
    tier: str
    seed: int
    drift: dict[str, np.ndarray]
    """Realised drift of each channel at its sample times, in the channel's unit."""
    missing_probability: dict[str, np.ndarray]
    """The conditional probability each sample was dropped with, -."""
    stress: np.ndarray
    """The process-stress indicator on the truth grid, - (doublings; see §6.1)."""
    stress_t: np.ndarray
    """Times of :attr:`stress`, d."""
    episodes: tuple[Episode, ...]
    """Fouling, flatline and injected-fault windows."""
    saturated: dict[str, np.ndarray]
    """Boolean per sample: the reading hit an instrument limit."""
    faults: tuple[SensorFault, ...]
    """The sensor faults that were applied."""


@dataclass(frozen=True)
class Observation:
    """Truth and observation of one run, side by side; the run layer separates them."""

    truth: ObservationTruth
    observed: ObservedRun


def sample_times(spec: ChannelSpec, horizon_d: float, start_weekday: int = 0) -> np.ndarray:
    """Times at which a channel is sampled, d.

    Samples run from the first eligible day at the channel's interval. A weekdays-only
    schedule is anchored to the first weekday of the horizon (a run starting on a
    Saturday still gets its weekly samples) and keeps only the samples that fall on a
    weekday — the same rule the influent generator uses for its feed assays.
    """
    if horizon_d <= 0.0:
        return np.zeros(0)
    if not spec.weekdays_only:
        return np.arange(0.0, horizon_d, spec.interval_d)
    first = next((d for d in range(7) if (start_weekday + d) % 7 < 5), 0)
    days = np.arange(first, math.ceil(horizon_d), int(spec.interval_d), dtype=float)
    weekday = (start_weekday + days.astype(int)) % 7
    return days[weekday < 5]


def stress_indicator(truth: TruthChannels, coupling: StressCoupling) -> np.ndarray:
    """The process-stress indicator of §6.1, on the truth grid.

    Doublings of total VFA above the run's median (one-sided: only an accumulation is
    stress) plus doublings of the gas rate away from it (two-sided: a foaming or
    overload episode both spikes and chokes the meter), each weighted by its coupling.
    Scale-free, so no plant-specific threshold is needed.
    """
    stress = np.zeros_like(truth.t)
    for quantity, weight, one_sided in (
        (coupling.vfa_quantity, coupling.vfa_coupling, True),
        (coupling.gas_quantity, coupling.gas_coupling, False),
    ):
        if weight == 0.0:
            continue
        series = np.asarray(truth.values[quantity], dtype=float)
        reference = float(np.median(series[series > 0.0])) if np.any(series > 0.0) else 0.0
        if reference <= 0.0:
            continue
        with np.errstate(divide="ignore", invalid="ignore"):
            doublings = np.log2(np.maximum(series, 1e-12) / reference)
        term = np.maximum(doublings, 0.0) if one_sided else np.abs(doublings)
        stress = stress + weight * term
    return stress


def _reflect(x: float, bound: float) -> float:
    """Fold a value into ``[-bound, bound]`` by reflection at both ends."""
    if bound <= 0.0:
        return 0.0
    period = 4.0 * bound
    y = math.fmod(x + bound, period)
    if y < 0.0:
        y += period
    return abs(y - 2.0 * bound) - bound


def _bounded_walk(z: np.ndarray, dt: np.ndarray, sd_per_sqrt_d: float, bound: float) -> np.ndarray:
    """A reflected random walk sampled at the channel's own times."""
    out = np.zeros(z.size)
    current = 0.0
    for k in range(z.size):
        current = _reflect(current + sd_per_sqrt_d * math.sqrt(dt[k]) * z[k], bound)
        out[k] = current
    return out


def _episodes(u: np.ndarray, t: np.ndarray, onset_per_d: float, duration_d: float) -> np.ndarray:
    """Boolean mask of the samples inside an episode, from one uniform draw per sample.

    An episode starts at a sample with probability ``onset_per_d x interval`` and lasts
    ``duration_d`` (a fixed length; a scenario that wants another length declares it).
    """
    active = np.zeros(t.size, dtype=bool)
    if onset_per_d <= 0.0 or duration_d <= 0.0:
        return active
    interval = np.diff(t, prepend=t[0] - (t[1] - t[0] if t.size > 1 else 1.0))
    end = -np.inf
    for k in range(t.size):
        if t[k] < end:
            active[k] = True
            continue
        if u[k] < min(1.0, onset_per_d * interval[k]):
            active[k] = True
            end = t[k] + duration_d
    return active


def _mask_to_episodes(channel: str, kind: str, mask: np.ndarray, t: np.ndarray) -> list[Episode]:
    """Contiguous ``True`` runs of a per-sample mask as :class:`Episode` windows."""
    out: list[Episode] = []
    start: float | None = None
    for k, flag in enumerate(mask):
        if flag and start is None:
            start = float(t[k])
        elif not flag and start is not None:
            out.append(Episode(channel=channel, kind=kind, start_d=start, end_d=float(t[k])))
            start = None
    if start is not None:
        out.append(Episode(channel=channel, kind=kind, start_d=start, end_d=float(t[-1])))
    return out


def _faults_for(channel: str, faults: Sequence[SensorFault]) -> list[SensorFault]:
    """The faults that act on a channel (a fault with ``channel=None`` acts on all)."""
    return [f for f in faults if f.channel in (None, channel)]


def _apply_faults(
    values: np.ndarray,
    t: np.ndarray,
    faults: Sequence[SensorFault],
) -> tuple[np.ndarray, np.ndarray, float]:
    """Apply the value-changing sensor faults; return values, the flatline mask and noise gain."""
    out = np.array(values, dtype=float, copy=True)
    flatline = np.zeros(t.size, dtype=bool)
    noise_gain = 1.0
    for fault in faults:
        mask = fault.active(t)
        if fault.effect is SensorEffect.SCALE:
            out = np.where(mask, out * fault.magnitude, out)
        elif fault.effect is SensorEffect.OFFSET:
            out = np.where(mask, out + fault.magnitude, out)
        elif fault.effect is SensorEffect.DRIFT:
            out = np.where(mask, out + fault.magnitude * (t - fault.onset_d), out)
        elif fault.effect is SensorEffect.FLATLINE:
            flatline |= mask
            out = np.where(mask, out * fault.magnitude, out)
        elif fault.effect is SensorEffect.NOISE and mask.any():
            noise_gain *= fault.magnitude
    return out, flatline, noise_gain


def _missing_probability(
    instrument: InstrumentModel,
    stress: np.ndarray,
    coupling: StressCoupling,
    faults: Sequence[SensorFault],
    t: np.ndarray,
) -> np.ndarray:
    """The conditional per-sample missing probability of one channel."""
    sensitivity = instrument.missingness.stress_sensitivity
    base = instrument.missingness.base_probability
    for fault in faults:
        mask = fault.active(t)
        if not mask.any():
            continue
        if fault.effect is SensorEffect.STRESS_COUPLING:
            sensitivity = sensitivity * fault.magnitude
    p = base * np.exp(sensitivity * stress)
    for fault in faults:
        if fault.effect is SensorEffect.GAP:
            p = p + np.where(fault.active(t), fault.magnitude, 0.0)
    return np.clip(p, 0.0, coupling.max_probability)


def observe(
    truth: TruthChannels,
    config: ObservationConfig,
    plant_id: str,
    tier: str,
    seed: int,
    *,
    horizon_d: float | None = None,
    faults: Sequence[SensorFault] = (),
    feed_log_kg_wet_d: Mapping[str, np.ndarray] | None = None,
    start_weekday: int = 0,
) -> Observation:
    """Observe a truth trajectory at one instrumentation tier.

    Args:
        truth: The measurable truth series (:func:`sim.observe.truth.truth_channels`).
        config: The catalogue, instruments and stress coupling.
        plant_id: Which plant's instruments to use (``A``, ``B`` or ``C``).
        tier: Instrumentation tier ``A``, ``B`` or ``C`` (a mask over the catalogue).
        seed: Seed of the run's ``SeedSequence``; each catalogue channel draws from its
            own child stream of it (CLAUDE.md rule 4).
        horizon_d: Length of the observation window, d; defaults to the truth horizon.
        faults: Compiled sensor faults (:mod:`sim.faults`).
        feed_log_kg_wet_d: The influent generator's operator feed log, passed through.
        start_weekday: Weekday of day 0 (0 = Monday), for weekdays-only schedules.

    Returns:
        The observed record and the hidden record of what the instruments did.

    Raises:
        KeyError: If the catalogue names a truth quantity the truth series lacks.
        ValueError: If the tier or the plant is unknown.
    """
    if plant_id not in config.plants:
        raise ValueError(f"unknown plant {plant_id!r}")
    horizon = float(truth.t[-1] - truth.t[0]) if horizon_d is None else float(horizon_d)
    catalogue_index = {name: i for i, name in enumerate(sorted(config.channels))}
    stress = stress_indicator(truth, config.stress)

    sensors: dict[str, SensorSeries] = {}
    assays: list[AssayResult] = []
    drifts: dict[str, np.ndarray] = {}
    probabilities: dict[str, np.ndarray] = {}
    saturations: dict[str, np.ndarray] = {}
    episodes: list[Episode] = []
    applied: list[SensorFault] = []

    for spec in config.channels_for_tier(tier):
        if spec.kind is ChannelKind.LOG:
            continue
        instrument = config.instrument_for(plant_id, spec.instrument)
        t = sample_times(spec, horizon, start_weekday)
        rng = np.random.default_rng(
            np.random.SeedSequence(seed, spawn_key=(catalogue_index[spec.name],))
        )
        draws = {block: rng.standard_normal(t.size) for block in _DRAW_BLOCKS[:2]}
        draws.update({block: rng.uniform(size=t.size) for block in _DRAW_BLOCKS[2:]})
        if t.size == 0:
            continue

        assert spec.truth_quantity is not None  # channels_for_tier drops the unavailable
        values = truth.at(spec.truth_quantity, t)
        channel_faults = _faults_for(spec.name, faults)
        applied.extend(channel_faults)

        fouled = _episodes(
            draws["fouling"], t, instrument.fouling.onset_per_d, instrument.fouling.mean_duration_d
        )
        values = np.where(
            fouled, values * instrument.fouling.gain + instrument.fouling.offset, values
        )

        dt = np.diff(t, prepend=t[0] - (t[1] - t[0] if t.size > 1 else 1.0))
        drift = _bounded_walk(
            draws["drift"], dt, instrument.drift.sd_per_sqrt_d, instrument.drift.bound
        )
        values = values + drift if instrument.drift.mode == "offset" else values * (1.0 + drift)

        values, fault_flatline, noise_gain = _apply_faults(values, t, channel_faults)
        values = values * (1.0 + noise_gain * instrument.noise_cv * draws["noise"])
        values = values + noise_gain * instrument.noise_sd_abs * draws["noise"]

        low, high = instrument.saturation.minimum, instrument.saturation.maximum
        saturated = np.zeros(t.size, dtype=bool)
        if low is not None:
            saturated |= values <= low
            values = np.maximum(values, low)
        if high is not None:
            saturated |= values >= high
            values = np.minimum(values, high)
        if instrument.resolution > 0.0:
            values = np.round(values / instrument.resolution) * instrument.resolution

        flatlined = (
            _episodes(
                draws["flatline"],
                t,
                instrument.flatline.onset_per_d,
                instrument.flatline.mean_duration_d,
            )
            | fault_flatline
        )
        values = _hold(values, flatlined)

        p_missing = _missing_probability(
            instrument, np.interp(t, truth.t, stress), config.stress, channel_faults, t
        )
        missing = draws["missing"] < p_missing

        drifts[spec.name] = drift
        probabilities[spec.name] = p_missing
        saturations[spec.name] = saturated
        episodes.extend(_mask_to_episodes(spec.name, "fouling", fouled, t))
        episodes.extend(_mask_to_episodes(spec.name, "flatline", flatlined, t))

        if spec.kind is ChannelKind.SENSOR:
            reported = np.where(missing, np.nan, values)
            sensors[spec.name] = SensorSeries(
                channel=spec.name,
                unit=spec.unit,
                basis=str(spec.basis),
                t=t,
                value=reported,
                missing=missing,
                standard_conditions=(
                    spec.standard_conditions.name if spec.standard_conditions else None
                ),
            )
        else:
            for k in np.flatnonzero(~missing):
                assays.append(
                    AssayResult(
                        channel=spec.name,
                        sample_day=int(t[k]),
                        report_day=int(t[k]) + spec.lag_d,
                        value=float(values[k]),
                        unit=spec.unit,
                        basis=str(spec.basis),
                    )
                )

    assays.sort(key=lambda r: (r.report_day, r.channel))
    observed = ObservedRun(
        plant_id=plant_id,
        tier=tier,
        sensors=sensors,
        assays=tuple(assays),
        feed_log_kg_wet_d=dict(feed_log_kg_wet_d or {}),
    )
    hidden = ObservationTruth(
        plant_id=plant_id,
        tier=tier,
        seed=int(seed),
        drift=drifts,
        missing_probability=probabilities,
        stress=stress,
        stress_t=truth.t,
        episodes=tuple(episodes),
        saturated=saturations,
        faults=tuple(applied),
    )
    return Observation(truth=hidden, observed=observed)


def _hold(values: np.ndarray, flatlined: np.ndarray) -> np.ndarray:
    """Replace flat-lined samples by the last value the instrument reported."""
    out = np.array(values, dtype=float, copy=True)
    for k in np.flatnonzero(flatlined):
        if k > 0:
            out[k] = out[k - 1]
    return out
