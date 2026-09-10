"""The observation model: truth channels to sensor records through a tier mask (§6.1, §6.4).

One :func:`observe` call turns a run's :class:`~sim.observation.channels.TruthChannels`
into the :class:`ObservationRecord` a workflow may read. Per sensor, in this order:

1. **Schedule** — samples at ``0, interval, 2 interval, ...`` within the horizon; the
   true value is linearly interpolated from the truth channel at the sample time.
2. **Fouling** — inside an episode the reading is ``gain x value + offset`` with the
   deviation ramping linearly from zero at onset to full size at the end of the episode.
3. **Drift** — a bounded random walk added as an offset, reset at each recalibration.
4. **Noise** — ``value (1 + cv z1) + sd_abs z2`` with ``z1`` and ``z2`` independent, so a
   sensor declaring both a relative and an absolute term has total standard deviation
   ``sqrt((value cv)^2 + sd_abs^2)`` rather than the two perfectly correlated.
5. **Saturation** — clipped to the readable range; clipped samples are flagged.
6. **Flatline** — inside an episode the sensor repeats its last reported value.
7. **Missingness** — two processes compose. The sample is dropped with a per-sensor,
   **independent** probability that depends on the tier and on the condition flags raised
   at that time (:class:`~sim.observation.schema.MissingnessPolicy`); and, for an online
   sensor, it is also dropped if a **plant-level logging outage** covers it
   (:class:`~sim.observation.schema.HistorianDropout`), which every online sensor at the
   tier loses together.
8. **Lag** — the record's ``report_t`` is the sample time plus the tier's laboratory
   turnaround (online instruments report immediately).

The **tier** supplies the missing rate, the laboratory turnaround and the recalibration
cadence; the **sensor** supplies everything intrinsic to the instrument (lead's decision
of 2026-09-02).

**Randomness.** **One stream per sensor**, derived from ``(observation seed, sensor
name)`` by :func:`sensor_rng` (CLAUDE.md rule 4), consumed within a sensor in a fixed
order: ``n`` uniforms for flatline onsets, ``n`` uniforms for fouling onsets, ``n``
normals for the drift walk, ``n`` normals for the relative noise, ``n`` normals for the
absolute noise, ``n`` uniforms for missingness — every block drawn whether or not the
sensor declares that effect, so adding a drift model to one sensor cannot change that
sensor's own noise (tested).

It was one serial stream per *run*, consumed in sorted sensor-name order, and that made
§6.4's central claim false: tiers carry different sensor sets, so a sensor's position in
the order changed with the tier and every shared sensor got a different realisation. At
one observation seed, tier A's ``gas_flow`` began 3212.4, nan, 5413.4 while tier C's began
3065.9, 5927.2, 5515.3 — the *same instrument on the same digester*, with tier A losing a
sample tier C kept. A tier is supposed to be a mask on identical truth, so a tier
comparison must not also be a re-roll. Deriving each stream from the sensor's own identity
makes a sensor's draws independent of which other sensors the tier happens to contain, and
of whether a subset was requested (both tested).

The **historian** stays plant-level, because that is what it models: one logging outage
that every online sensor at the tier loses together.

The historian is a separate stochastic component and takes its own stream, derived from
the run seed by :data:`HISTORIAN_STREAM_OFFSET` and drawn once per run: one block of ``n``
uniforms for outage onsets and one of ``n`` integers for outage lengths, at the finest
online schedule of the tier. Every stream here is independent of the influent generator's:
a run gives the observation model its own seed.

Nothing here writes files; :class:`ObservationRecord` goes to the run layer, which owns
``runs/<id>/`` (CLAUDE.md rule 1).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from sim.faults.plan import ObservationFaults
from sim.observation.channels import TruthChannels, condition_flags, flags_at
from sim.observation.schema import (
    EpisodeModel,
    HistorianDropout,
    MissingnessModel,
    ObservationConfig,
    SensorSpec,
    TierSpec,
)

__all__ = [
    "HISTORIAN_STREAM_OFFSET",
    "ObservationRecord",
    "SensorSeries",
    "episode_mask",
    "historian_outages",
    "observe",
    "sample_times",
    "sensor_rng",
    "sensor_stream_key",
]

_SENSOR_STREAM_DOMAIN = "ad-agentbench/observation/sensor"
"""Domain string mixed into :func:`sensor_stream_key`, so the sensor identities of this
model cannot collide with any other component that hashes names into a seed sequence."""


def sensor_stream_key(name: str) -> int:
    """A stable 64-bit identity for a sensor name.

    ``hash()`` is salted per interpreter run, so it cannot be used: a seed derived from it
    would change between processes and break CLAUDE.md rule 4. This is SHA-256 of the
    domain-separated name, which is stable across platforms, Python versions and numpy
    versions.

    Args:
        name: The sensor's name.

    Returns:
        A non-negative integer, for :class:`numpy.random.SeedSequence`.
    """
    digest = hashlib.sha256(f"{_SENSOR_STREAM_DOMAIN}|{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def sensor_rng(seed: int, name: str) -> np.random.Generator:
    """The stream of one sensor in one run: a function of the run seed and the name alone.

    Args:
        seed: The run's observation seed.
        name: The sensor's name.

    Returns:
        That sensor's generator.
    """
    return np.random.default_rng(np.random.SeedSequence([int(seed), sensor_stream_key(name)]))


HISTORIAN_STREAM_OFFSET = 1_000_003
"""Offset from the run seed to the plant-level historian stream (a prime, for tidiness).

The historian is a *separate stochastic component* and takes its own stream (CLAUDE.md
rule 4). Deriving it by an offset rather than by splitting the run seed keeps every
sensor's own draws bit-identical to what they were before the historian existed, so the
component can be added without silently re-rolling every archived run.
"""


def historian_outages(
    dropout: HistorianDropout,
    tier: str,
    t: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Which of the sample times ``t`` fall inside a shared logging outage.

    One outage series for the whole plant: the same mask is applied to **every** online
    sensor at the tier, which is what makes the losses correlated rather than independent
    (:class:`~sim.observation.schema.HistorianDropout`).

    An outage starts at a sample with probability ``rate`` and lasts a length drawn from
    the empirical distribution ``gap_lengths_min``; a sample is lost if an outage covers it.
    With daily sampling every observed outage (longest 421 min) is shorter than one
    interval, so it costs exactly the sample it lands on and the realised loss fraction is
    the declared rate — the length distribution only starts to matter for a schedule finer
    than the longest outage, which is why it is carried rather than collapsed to a mean.

    Args:
        dropout: The declared outage process.
        tier: Instrumentation tier.
        t: Sample times, d.
        rng: The historian's own stream.

    Returns:
        Boolean mask over ``t``: True where the sample is lost to a shared outage.
    """
    rate = dropout.rate_by_tier[tier]  # type: ignore[index]
    lost = np.zeros(t.size, dtype=bool)
    # both blocks are drawn whatever the rate, so a tier's mask does not depend on how
    # many outages another tier happened to have
    starts = rng.uniform(size=t.size) < rate
    lengths_d = np.asarray(dropout.gap_lengths_min, dtype=float) / 1440.0
    draws = rng.integers(0, lengths_d.size, size=t.size)
    if rate <= 0.0:
        return lost
    for i in np.flatnonzero(starts):
        lost |= (t >= t[i]) & (t < t[i] + max(lengths_d[draws[i]], np.finfo(float).tiny))
        lost[i] = True  # the sample the outage starts on is always lost
    return lost


@dataclass(frozen=True)
class SensorSeries:
    """What one instrument reported over a run — the workflow-visible record."""

    name: str
    channel: str
    unit: str
    gas_convention: str
    solids_basis: str
    sample_t: np.ndarray
    """Time the sample was taken, d."""
    report_t: np.ndarray
    """Time the result became available, d (``sample_t + lag_d``)."""
    value: np.ndarray
    """Reported value, NaN where the sample is missing."""
    missing: np.ndarray
    """True where the sample was lost (the value is NaN)."""
    saturated: np.ndarray
    """True where the reading hit the instrument's readable range."""
    flatlined: np.ndarray
    """True where the sensor was repeating its last value."""
    fouled: np.ndarray
    """True where a fouling episode was in progress."""

    @property
    def observed(self) -> np.ndarray:
        """Indices of the samples that were actually reported."""
        return np.flatnonzero(~self.missing)

    def as_pairs(self) -> list[tuple[float, float]]:
        """``(report_t, value)`` of the reported samples only."""
        return [(float(self.report_t[i]), float(self.value[i])) for i in self.observed]


@dataclass(frozen=True)
class ObservationRecord:
    """Everything a workflow may read from one run's instrumentation.

    ``truth_flags`` is **not** part of it: the condition flags that drove missingness are
    hidden truth and stay with the run's truth record.
    """

    tier: str
    seed: int
    horizon_d: float
    sensors: dict[str, SensorSeries]

    def __getitem__(self, name: str) -> SensorSeries:
        """One sensor's series."""
        if name not in self.sensors:
            raise KeyError(f"sensor {name!r} is not readable at tier {self.tier}")
        return self.sensors[name]

    @property
    def names(self) -> tuple[str, ...]:
        """Sensors readable at this tier, sorted."""
        return tuple(sorted(self.sensors))

    @property
    def units(self) -> Mapping[str, str]:
        """Unit of every reported sensor (CLAUDE.md rule 6)."""
        return {name: series.unit for name, series in sorted(self.sensors.items())}


def sample_times(interval_d: float, horizon_d: float) -> np.ndarray:
    """Sample times ``0, interval, ...`` up to and including the horizon, d."""
    if interval_d <= 0.0:
        raise ValueError("sampling interval must be positive")
    # the tolerance is not cosmetic: 0.3 / 0.1 == 2.9999999999999996 in binary floating
    # point, which would silently drop the sample at the horizon
    n = int(np.floor(horizon_d / interval_d + 1e-9)) + 1
    return np.arange(n, dtype=float) * interval_d


def episode_mask(
    model: EpisodeModel | None, u: np.ndarray, dt: float
) -> tuple[np.ndarray, np.ndarray]:
    """Episode occupancy and progress from one uniform per sample.

    An episode starts at a sample with probability ``hazard_per_d * dt`` and lasts
    ``max(1, round(mean_duration_d / dt))`` samples. Returns ``(active, progress)`` where
    ``progress`` runs from ``1/length`` to 1 across an episode and is 0 outside — the
    ramp a fouling deviation follows.
    """
    n = u.size
    active = np.zeros(n, dtype=bool)
    progress = np.zeros(n)
    if model is None or model.hazard_per_d <= 0.0:
        return active, progress
    length = max(1, round(model.mean_duration_d / dt))
    p = min(model.hazard_per_d * dt, 1.0)
    i = 0
    while i < n:
        if u[i] < p:
            end = min(i + length, n)
            active[i:end] = True
            progress[i:end] = np.arange(1, end - i + 1) / length
            i = end
        else:
            i += 1
    return active, progress


def _outages_at(
    historian_t: np.ndarray, lost: np.ndarray, interval_d: float, horizon_d: float
) -> np.ndarray:
    """The shared outage mask resampled onto one sensor's own schedule.

    The outage series is drawn once on the tier's finest online schedule; a sensor sampling
    less often reads the same series at its own times. Sample-and-hold, not interpolation:
    an outage either covers a sample instant or it does not.
    """
    t = sample_times(interval_d, horizon_d)
    if t.size == historian_t.size and np.array_equal(t, historian_t):
        return lost
    idx = np.clip(np.searchsorted(historian_t, t, side="right") - 1, 0, historian_t.size - 1)
    return lost[idx]


def _sensor_series(
    spec: SensorSpec,
    channels: TruthChannels,
    horizon_d: float,
    overload: np.ndarray,
    foaming: np.ndarray,
    rng: np.random.Generator,
    faults: ObservationFaults,
    missingness: MissingnessModel,
    lag_d: float,
    recalibration_interval_d: float,
    historian_lost: np.ndarray | None = None,
) -> SensorSeries:
    """One sensor's record; consumes this sensor's block of the run's stream.

    ``missingness``, ``lag_d`` and ``recalibration_interval_d`` are the **tier's**
    (:class:`~sim.observation.schema.TierSpec`), not the sensor's.
    """
    t = sample_times(spec.sampling_interval_d, horizon_d)
    n = t.size
    dt = spec.sampling_interval_d

    # the stream blocks, always drawn in this order and always this size
    u_flat = rng.uniform(size=n)
    u_foul = rng.uniform(size=n)
    z_drift = rng.standard_normal(size=n)
    z_noise = rng.standard_normal(size=n)
    z_noise_abs = rng.standard_normal(size=n)
    u_missing = rng.uniform(size=n)

    truth = np.interp(t, channels.t, channels[spec.channel])
    value = truth.copy()

    fouled, ramp = episode_mask(spec.fouling, u_foul, dt)
    if spec.fouling is not None:
        gain = 1.0 + (spec.fouling.gain - 1.0) * ramp
        offset = spec.fouling.offset * ramp
        value = value * gain + offset

    if spec.drift is not None and spec.drift.sd_per_sqrt_d > 0.0:
        step = spec.drift.sd_per_sqrt_d * np.sqrt(dt)
        offset = 0.0
        drift = np.empty(n)
        for i in range(n):
            if (
                spec.drift.recalibrated
                and i > 0
                and int(t[i] // recalibration_interval_d)
                != int(t[i - 1] // recalibration_interval_d)
            ):
                offset = 0.0
            offset = float(np.clip(offset + step * z_drift[i], -spec.drift.bound, spec.drift.bound))
            drift[i] = offset
        value = value + drift

    # injected sensor faults act on the calibration, before the instrument's own noise
    if spec.name in faults.ramps:
        onset, rate = faults.ramps[spec.name]
        elapsed = np.maximum(t - onset, 0.0)
        if spec.drift is not None and spec.drift.recalibrated:
            # a calibration fault is removed by a calibration: the ramp accumulates only
            # since the last recalibration after its onset, which is what produces the
            # sawtooth "drift then step" of the Level-2 row (§6.3). Without this the ramp
            # runs to the end of the horizon and there is no step anywhere.
            since_recal = t - np.floor(t / recalibration_interval_d) * recalibration_interval_d
            elapsed = np.where(t >= onset, np.minimum(elapsed, since_recal), 0.0)
        value = value + rate * elapsed
    if spec.name in faults.scales:
        onset, factor = faults.scales[spec.name]
        value = np.where(t >= onset, value * factor, value)

    # the relative and absolute noise terms are INDEPENDENT draws: a sensor that declares
    # both (the H2 cell) has total sd sqrt((v cv)^2 + sd_abs^2), not (v cv + sd_abs)
    cv = spec.noise.cv * faults.noise_scale
    sd_abs = spec.noise.sd_abs * faults.noise_scale
    value = value * (1.0 + cv * z_noise) + sd_abs * z_noise_abs

    saturated = np.zeros(n, dtype=bool)
    if spec.saturation is not None:
        if spec.saturation.low is not None:
            saturated |= value < spec.saturation.low
            value = np.maximum(value, spec.saturation.low)
        if spec.saturation.high is not None:
            saturated |= value > spec.saturation.high
            value = np.minimum(value, spec.saturation.high)

    flatlined, _ = episode_mask(spec.flatline, u_flat, dt)
    if spec.name in faults.flatlines:
        onset, end = faults.flatlines[spec.name]
        flatlined = flatlined | ((t >= onset) & (t < end))
    for i in range(1, n):
        if flatlined[i]:
            # a stuck sensor repeats the previous *reading*, so the saturation flag is the
            # previous reading's too: a flag that contradicted its own value would tell a
            # workflow the instrument hit its range when the reported number is inside it
            value[i] = value[i - 1]
            saturated[i] = saturated[i - 1]

    idx = np.clip(np.searchsorted(channels.t, t, side="right") - 1, 0, channels.t.size - 1)
    missing = np.zeros(n, dtype=bool)
    # `random_gaps` must add gaps that carry NO information about the state, so it is an
    # additive unconditional term rather than a factor on the base rate: scaling the base
    # rate scales the stressed rate by the same factor, so every added gap would be as
    # informative as the originals and the Level-1 nuisance would not be MCAR. The
    # conditional multipliers are `informative_missingness`'s to scale (fault semantics).
    extra = missingness.base_rate * (faults.missing_scale - 1.0)
    scaled = MissingnessModel(
        base_rate=missingness.base_rate,
        stress_multipliers={
            flag: m * faults.stress_scale for flag, m in missingness.stress_multipliers.items()
        },
    )
    for i in range(n):
        rate = min(scaled.rate(flags_at(overload, foaming, int(idx[i]))) + extra, 1.0)
        missing[i] = u_missing[i] < rate
    if historian_lost is not None:
        # the plant-level outage is drawn once for the tier and applied to every online
        # sensor, so these losses are perfectly correlated across instruments; the
        # per-sensor draw above is unchanged and independent, and the two compose
        missing = missing | historian_lost
    value = np.where(missing, np.nan, value)

    return SensorSeries(
        name=spec.name,
        channel=spec.channel,
        unit=spec.unit,
        gas_convention=spec.gas_convention,
        solids_basis=spec.solids_basis,
        sample_t=t,
        report_t=t + lag_d,
        value=value,
        missing=missing,
        saturated=saturated & ~missing,
        flatlined=flatlined & ~missing,
        fouled=fouled & ~missing,
    )


def observe(
    channels: TruthChannels,
    config: ObservationConfig,
    tier: str,
    seed: int,
    horizon_d: float | None = None,
    sensors: Sequence[str] | None = None,
    faults: ObservationFaults | None = None,
) -> ObservationRecord:
    """Observe a run at one instrumentation tier.

    Args:
        channels: The run's truth channels.
        config: Sensor specifications and tier masks.
        tier: ``"A"``, ``"B"`` or ``"C"`` (§6.4).
        seed: Seed of the run's observation stream.
        horizon_d: Horizon, d (default: the last channel time).
        sensors: Subset of the tier's sensors to report (default: all of them). A subset
            never changes another sensor's values, because each sensor's stream is derived
            from its own name (:func:`sensor_rng`) and not from a position in a queue.
        faults: Observation-layer fault directives (:mod:`sim.faults`). They change the
            record only: the digester is untouched, and the stream is consumed
            identically, so a faulted record differs from its clean twin only by the
            fault (tested).

    Returns:
        The workflow-visible record.

    Raises:
        KeyError: If the tier is unknown.
        ValueError: If a tier sensor measures a channel this run did not compute, or a
            requested sensor is not in the tier.
    """
    if tier not in config.tiers:
        raise KeyError(f"unknown tier {tier!r}; known tiers are {sorted(config.tiers)}")
    spec_tier: TierSpec = config.tiers[tier]
    horizon = float(channels.t[-1]) if horizon_d is None else float(horizon_d)
    if horizon > float(channels.t[-1]) + 1e-9:
        # np.interp clamps beyond the last channel time, so a longer horizon would
        # silently fabricate constant readings for a run that never happened
        raise ValueError(
            f"horizon {horizon} d is beyond the run's last channel time "
            f"{float(channels.t[-1])} d; there is no truth to observe there"
        )
    requested = set(spec_tier.sensors if sensors is None else sensors)
    unknown = requested - set(spec_tier.sensors)
    if unknown:
        raise ValueError(f"sensors {sorted(unknown)} are not readable at tier {tier}")

    missing_channels = [
        config.sensors[name].channel
        for name in spec_tier.sensors
        if config.sensors[name].channel not in channels
    ]
    if missing_channels:
        raise ValueError(
            f"tier {tier} needs channels {sorted(set(missing_channels))}, which this run did "
            "not compute (solids channels need the influent's inert equivalent and ash)"
        )

    overload, foaming = condition_flags(
        channels,
        vfa_surge_ratio=config.conditions.vfa_surge_ratio,
        vfa_median_window_d=config.conditions.vfa_median_window_d,
        gas_surge_ratio=config.conditions.gas_surge_ratio,
        gas_median_window_d=config.conditions.gas_median_window_d,
        foaming_vfa_ratio=config.conditions.foaming_vfa_ratio,
    )

    # the plant-level outage series: ONE draw for the tier, on the finest online schedule,
    # shared by every online sensor. Its own stream (rule 4).
    online = [n for n in spec_tier.sensors if config.sensors[n].kind == "online"]
    historian_t = sample_times(
        min((config.sensors[n].sampling_interval_d for n in online), default=1.0), horizon
    )
    historian_lost = historian_outages(
        config.historian,
        tier,
        historian_t,
        np.random.default_rng(int(seed) + HISTORIAN_STREAM_OFFSET),
    )
    # `or` would replace an empty-but-configured directive object, because
    # ObservationFaults defines __bool__; only None means "no faults"
    applied = ObservationFaults() if faults is None else faults
    unknown_targets = (set(applied.ramps) | set(applied.scales) | set(applied.flatlines)) - set(
        config.sensors
    )
    if unknown_targets:
        raise ValueError(f"observation faults name unknown sensors {sorted(unknown_targets)}")
    out: dict[str, SensorSeries] = {}
    for name in sorted(requested):
        sensor = config.sensors[name]
        # this sensor's own stream: a function of (run seed, sensor name) and of nothing
        # else, so which other sensors the tier carries cannot move it
        series = _sensor_series(
            sensor,
            channels,
            horizon,
            overload,
            foaming,
            sensor_rng(seed, name),
            applied,
            config.missingness.model_for(tier, sensor.kind),
            spec_tier.lab_turnaround_d if sensor.kind == "lab" else 0.0,
            spec_tier.recalibration_interval_d,
            # a grab sample does not pass through the historian, so lab assays are untouched
            _outages_at(historian_t, historian_lost, sensor.sampling_interval_d, horizon)
            if sensor.kind == "online"
            else None,
        )
        out[name] = series
    return ObservationRecord(tier=tier, seed=int(seed), horizon_d=horizon, sensors=out)
