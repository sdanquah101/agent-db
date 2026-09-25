"""The admissible label set of one cell (docs/distinguishability.md, method version 4).

**Every class is the truth, less the injected fault, plus its own candidate.** For each
(scenario, plant), the truth simulation is rebuilt from the scenario, the plant and the
run's own seeds (true parameters, true influent, true initial state; checked to reproduce
the stored channels exactly). The reference for every class is that truth with the
injected fault removed; each class adds only its own candidate perturbation (a sensor
step, scale, drift or flatline; a delivery, fractionation or solids fault; an initial-state
offset; a parameter change point; one truth extension switched off) and is fitted by its
few fault knobs. This is an **upper bound** on distinguishability, optimistic by
construction: no workflow knows the truth's parameters, influent or state.

**The likelihood is the observation model's own.** Each calibrated sensor's residual is
compared with its declared noise: white noise ``sqrt((cv mu)^2 + sd_abs^2)`` plus the
sensor's random-walk drift, which is reset at the tier's recalibration (the covariance of
that walk is modelled, so its correlation is not mistaken for signal). There is no
dispersion rescaling. Flatlined samples stay visible: their values carry no information
(a stuck sensor repeats its last reading), but their flags enter through the flatline
episode model, so a flatline candidate is judged by the flags it explains.

**A class's score is -2 log-likelihood plus a penalty:** the likelihood-ratio critical
value of its k fitted knobs at alpha / (number of alternatives), plus 2 ln N for a
best-of-N search over its discrete candidates. A label is admissible when its score is
within a margin of the best.

The truth store is read for the seeds, the target feed and the answer key; the scenario
file for the faults. The data are the tier's visible record, cut at the end of P0's
calibration window.
"""

from __future__ import annotations

import hashlib
import json
import math
import pickle
import signal
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType
from typing import Any, NoReturn

import numpy as np
import yaml
from scipy.linalg import cho_factor, solve_triangular
from scipy.stats import chi2 as chi2_dist
from scipy.stats import norm

__all__ = [
    "LABELS",
    "METHOD_VERSION",
    "Candidate",
    "SensorData",
    "admissible",
    "analyse_pair",
    "calibration_end",
    "chance_rate",
    "class_limited",
    "class_penalty",
    "drift_covariance",
    "flag_deviance",
    "load_record",
    "sensor_candidates",
    "sensor_deviance",
    "truth_representable",
]

METHOD_VERSION = 4
LABELS = ("none", "sensor", "influent", "state", "parameter", "structural")
REPO = Path(__file__).resolve().parents[1]
P0_CONFIG = REPO / "configs" / "workflows" / "p0.yaml"

# the label each injected fault type carries; the Level-1 nuisances carry none and stay in
# every class, because they are part of the record's noise, not a fault to attribute
LABEL_OF = {
    "ph_electrode_drift": "sensor",
    "gas_meter_scale": "sensor",
    "ch4_analyser_flatline": "sensor",
    "feed_mislabelled": "influent",
    "unrecorded_delivery": "influent",
    "moisture_drift": "influent",
    "biomass_misinitialised": "state",
    "informative_missingness": "state",
    "ammonia_inhibition_shift": "parameter",
    "hydrolysis_regime_change": "parameter",
    "omitted_sao": "structural",
    "omitted_precipitation": "structural",
    "imperfect_mixing": "structural",
}
NUISANCE = ("sensor_noise", "random_gaps")
# fault types whose truth no class here can represent: null score, not credited
_UNREPRESENTABLE = {
    "informative_missingness": "a missingness pattern (the likelihood does not model "
    "which samples are missing)",
}
PARAMETER_GROUPS = {
    "ammonia_inhibition_shift": "K_I_nh3",
    "hydrolysis_regime_change": "k_hyd_ch,k_hyd_pr,k_hyd_li",
}
# truth extensions the harness cannot switch off without a change under sim/: the
# structural class does not offer them, and every document says so
STRUCTURAL_LIMITS = {
    "precipitation": "simulate_truth always feeds dissolved calcium (S_ca) to the reactor "
    "(sim/run/harness.py), so the truth cannot run without the precipitation extension "
    "unless sim/ changes",
}
FLAG_LEAK = 1e-9  # a flag the episode model cannot produce has this probability, not zero

# the penalty's settings, set from configs/eval.yaml at the start of an analysis
_PENALTY: dict[str, Any] = {"alpha": 0.05, "m": 5, "look_elsewhere": True}


def _cfg() -> Any:
    from eval.config import load_eval_config

    return load_eval_config().distinguishability


def _p0() -> dict[str, Any]:
    return yaml.safe_load(P0_CONFIG.read_text(encoding="utf-8"))


def class_penalty(k: int, n_candidates: int) -> float:
    """The critical value of an alternative with ``k`` fitted knobs, plus the search term.

    With k >= 1 it is the likelihood-ratio critical value, chi2(k) at 1 - alpha / m. A
    fixed alternative (k = 0: an extension left out, a flatline window) is a simple
    hypothesis: its deviance gain over the null is ``2 delta.w - |delta|^2`` for a fixed
    whitened shift ``delta``, which exceeds ``c`` with probability at most
    ``P(Z > sqrt(c))`` whatever ``|delta|`` is, so its critical value is
    ``Phi^-1(1 - alpha / m)^2``. The null itself pays nothing (``Candidate.penalty``).
    """
    q = 1.0 - _PENALTY["alpha"] / _PENALTY["m"]
    lr = float(chi2_dist.ppf(q, k)) if k > 0 else float(norm.ppf(q)) ** 2
    search = 2.0 * math.log(n_candidates) if _PENALTY["look_elsewhere"] else 0.0
    return lr + search


def calibration_end(duration_days: float) -> float:
    """The last day the analysis reads: P0's calibration window ends at the hold-out."""
    return float(duration_days) * (1.0 - float(_p0()["windows"]["holdout_fraction"]))


# ------------------------------------------------------------------ the record


@dataclass
class SensorData:
    """One calibrated sensor of the visible record, up to the end of the calibration window.

    ``keep`` marks the samples whose values enter the Gaussian term (not missing,
    saturated, flatlined or fouled). ``flag``/``flag_seen`` are the flatline flags and
    whether each was observable (a missing sample's flag is not).
    """

    sensor: str
    channel: str
    kind: str
    t: np.ndarray
    y: np.ndarray
    keep: np.ndarray
    flag: np.ndarray
    flag_seen: np.ndarray
    dt: float
    cv: float
    sd_abs: float
    drift_sd: float
    recalibrated: bool
    recal_d: float
    hazard_per_d: float
    episode_d: float
    chol: Any = None
    """Cholesky factor of the reference covariance of the kept samples (:func:`prepare`)."""
    drift_k: Any = None
    """The drift walk's covariance of the kept samples (:func:`prepare`)."""
    logdet_ref: float = 0.0
    white_floor: float = 0.0


def load_record(
    sensors_json: Path, tier: str, t_end: float, noise_scale: float = 1.0
) -> list[SensorData]:
    """The tier's calibrated sensors from ``observations/sensors.json``, up to ``t_end``.

    Only the sensors P0 calibrates are used (so temperature is left out); nothing after
    ``t_end`` is read. Every flag is kept: flatlined samples enter through their flags.
    """
    from sim.observation import load_observation_config

    obs = load_observation_config()
    recal = float(obs.tiers[tier].recalibration_interval_d)
    raw = json.loads(sensors_json.read_text(encoding="utf-8"))["sensors"]
    out = []
    for name in _p0()["calibration"]["channels"]:
        if name not in raw:
            continue
        s, spec = raw[name], obs.sensors[name]
        t = np.asarray(s["sample_t_d"], dtype=float)
        within = t <= t_end + 1e-9
        t = t[within]
        y = np.array([np.nan if v is None else float(v) for v in s["value"]])[within]

        def flag(key: str, _s: Mapping[str, Any] = s, _w: np.ndarray = within) -> np.ndarray:
            return np.asarray(_s.get(key, [False] * _w.size), dtype=bool)[_w]

        missing, flat = flag("missing") | ~np.isfinite(y), flag("flatlined")
        keep = ~missing & ~flat & ~flag("saturated") & ~flag("fouled")
        drift = spec.drift
        episode = spec.flatline
        out.append(
            SensorData(
                sensor=name,
                channel=str(s["channel"]),
                kind=str(spec.kind),
                t=t,
                y=y,
                keep=keep,
                flag=flat,
                flag_seen=~missing,
                dt=float(spec.sampling_interval_d),
                cv=float(spec.noise.cv) * noise_scale,
                sd_abs=float(spec.noise.sd_abs) * noise_scale,
                drift_sd=float(drift.sd_per_sqrt_d) if drift is not None else 0.0,
                recalibrated=bool(drift.recalibrated) if drift is not None else False,
                recal_d=recal,
                hazard_per_d=float(episode.hazard_per_d) if episode is not None else 0.0,
                episode_d=float(episode.mean_duration_d) if episode is not None else 1.0,
            )
        )
    return out


def drift_covariance(
    t: np.ndarray, dt: float, sd_per_sqrt_d: float, recal_d: float, recalibrated: bool
) -> np.ndarray:
    """Covariance of the observation model's random-walk drift at the sample times ``t``.

    The walk adds ``sd sqrt(dt) z`` at every sample of the sensor's grid, missing or not,
    and restarts from zero at the first sample of each recalibration interval
    (``sim/observation/model.py``). Two samples of one interval, ``i <= j`` on the grid,
    share ``i - start + 1`` steps; samples of different intervals share none. The bound
    on the walk is not modelled (it is several sd away at every declared setting).
    """
    if sd_per_sqrt_d <= 0.0:
        return np.zeros((t.size, t.size))
    idx = np.rint(t / dt).astype(int)
    grid = np.arange(int(idx.max()) + 1 if idx.size else 0) * dt
    seg_grid = (
        np.floor(grid / recal_d + 1e-12).astype(int) if recalibrated else np.zeros(grid.size, int)
    )
    # first grid index of each sample's interval
    starts = np.zeros(grid.size, dtype=int)
    for i in range(1, grid.size):
        starts[i] = i if seg_grid[i] != seg_grid[i - 1] else starts[i - 1]
    seg, start = seg_grid[idx], starts[idx]
    shared = np.minimum.outer(idx, idx) - start[:, None] + 1
    same = seg[:, None] == seg[None, :]
    return (sd_per_sqrt_d**2 * dt) * np.where(same, shared, 0).astype(float)


def _white(s: SensorData, mu: np.ndarray) -> np.ndarray:
    """The declared white-noise variance at the prediction ``mu`` (kept samples)."""
    return np.maximum((s.cv * np.abs(mu)) ** 2 + s.sd_abs**2, s.white_floor)


def prepare(record: Sequence[SensorData], mu_ref: Mapping[str, np.ndarray]) -> None:
    """Set each sensor's drift covariance and its reference factor.

    The reference factor (white noise at the reference prediction, plus the drift walk)
    whitens a design in the sensor class's closed-form fit and fixes the zero of the
    log-determinant; every class is then scored with its own covariance
    (:func:`sensor_deviance`).
    """
    for s in record:
        mu = mu_ref[s.sensor][s.keep]
        s.white_floor = 1e-24 + (1e-9 * max(float(np.median(np.abs(mu))) if mu.size else 0.0,
                                            1e-12)) ** 2  # fmt: skip
        s.drift_k = drift_covariance(s.t[s.keep], s.dt, s.drift_sd, s.recal_d, s.recalibrated)
        cov = np.diag(_white(s, mu)) + s.drift_k
        s.chol = cho_factor(cov, lower=True)[0] if cov.size else None
        s.logdet_ref = 2.0 * float(np.log(np.diag(s.chol)).sum()) if cov.size else 0.0


def sensor_deviance(s: SensorData, mu: np.ndarray) -> float:
    """-2 log-likelihood of one sensor's kept values under the prediction ``mu``.

    The covariance is the declared noise at ``mu``'s own level plus the drift walk, as
    the observation model draws it under that hypothesis; the log-determinant is taken
    relative to the reference's, so the reference prediction scores its whitened sum of
    squares.
    """
    if s.chol is None:
        return 0.0
    m = mu[s.keep]
    if not np.all(np.isfinite(m)):
        return float("inf")
    try:
        chol = cho_factor(np.diag(_white(s, m)) + s.drift_k, lower=True)[0]
    except np.linalg.LinAlgError:
        return float("inf")
    w = solve_triangular(chol, s.y[s.keep] - m, lower=True, check_finite=False)
    logdet = 2.0 * float(np.log(np.diag(chol)).sum())
    return float(w @ w) + logdet - s.logdet_ref


def whiten(s: SensorData, v: np.ndarray) -> np.ndarray:
    """``L^-1 v`` over the kept samples with the reference factor (``v`` on the full grid)."""
    if s.chol is None:
        return np.zeros(0)
    return solve_triangular(s.chol, v[s.keep], lower=True, check_finite=False)


def flag_deviance(s: SensorData, window: tuple[float, float] | None = None) -> float:
    """-2 log P(flatline flags) under the sensor's episode model.

    An optional injected flatline ``[onset, end)`` flags its samples whatever the episodes
    do.

    The episode model is ``sim.observation.model.episode_mask``: at a sample outside an
    episode, one starts with probability ``hazard dt`` and covers
    ``max(1, round(duration / dt))`` samples. A forward pass over the samples remaining
    in the current episode. A missing sample's flag is unobservable; a sample inside a
    candidate's injected window must be flagged, as ``observe`` flags every sample
    of an injected flatline. A flag the model cannot produce has probability
    ``FLAG_LEAK``.
    """
    n = s.t.size
    if n == 0:
        return 0.0
    length = max(1, round(s.episode_d / s.dt))
    p = min(s.hazard_per_d * s.dt, 1.0)
    forced = np.zeros(n, dtype=bool)
    if window is not None:
        forced = (s.t >= window[0]) & (s.t < window[1])
    seen = s.flag_seen
    alpha = np.zeros(length)
    alpha[0] = 1.0  # remaining episode samples after the previous one: none
    total = 0.0
    for i in range(n):
        if seen[i] and forced[i]:
            e_on = e_off = 1.0 if s.flag[i] else FLAG_LEAK
        elif seen[i]:
            e_on = 1.0 if s.flag[i] else FLAG_LEAK
            e_off = FLAG_LEAK if s.flag[i] else 1.0
        else:
            e_on = e_off = 1.0
        new = np.zeros(length)
        new[: length - 1] += alpha[1:] * e_on  # an episode running on
        new[length - 1] += alpha[0] * p * e_on  # one starting here
        new[0] += alpha[0] * (1.0 - p) * e_off  # none
        z = float(new.sum())
        if z <= 0.0:
            return float("inf")
        total += math.log(z)
        alpha = new / z
    return -2.0 * total


# ------------------------------------------------------------------ classes


@dataclass
class Candidate:
    """The best representative of one hypothesis class on one tier's record."""

    label: str
    deviance: float
    k: int
    n_candidates: int = 1
    knobs: dict[str, Any] = field(default_factory=dict)
    per_sensor: dict[str, float] = field(default_factory=dict)
    note: str = ""
    failed: int = 0

    @property
    def penalty(self) -> float:
        """The class's penalty (``class_penalty``); 0 for the null."""
        return 0.0 if self.label == "none" else class_penalty(self.k, self.n_candidates)

    @property
    def score(self) -> float:
        """-2 log-likelihood (up to a constant shared by every class) plus the penalty."""
        return self.deviance + self.penalty


def predict(channels: Any, record: Sequence[SensorData]) -> dict[str, np.ndarray]:
    """The noiseless observation of ``channels`` at every sensor's sample times."""
    t_ch = np.asarray(channels.t, dtype=float)
    return {s.sensor: np.interp(s.t, t_ch, np.asarray(channels[s.channel], float)) for s in record}


def gaussian_terms(record: Sequence[SensorData], mu: Mapping[str, np.ndarray]) -> dict[str, float]:
    """Each sensor's Gaussian deviance under ``mu`` (:func:`sensor_deviance`)."""
    return {s.sensor: sensor_deviance(s, mu[s.sensor]) for s in record}


def _ramp(s: SensorData, onset: float) -> np.ndarray:
    """A unit-rate calibration ramp from ``onset``.

    It is reset at recalibration, as ``observe`` resets an injected ``ph_electrode_drift``.
    """
    elapsed = np.maximum(s.t - onset, 0.0)
    if s.drift_sd > 0.0 and s.recalibrated:
        since = s.t - np.floor(s.t / s.recal_d) * s.recal_d
        elapsed = np.where(s.t >= onset, np.minimum(elapsed, since), 0.0)
    return elapsed


def sensor_candidates(
    record: Sequence[SensorData],
    mu: Mapping[str, np.ndarray],
    flags0: Mapping[str, float],
    onsets: Sequence[float],
    flatline_windows: Sequence[tuple[float, float]],
) -> Candidate:
    """The sensor class on top of the reference prediction ``mu``.

    On one sensor at a time: a scale step, an offset step or a calibration ramp from an
    onset (k = 1 each; the size is solved in closed form by generalised least squares
    with the reference covariance, and the candidate is then scored with its own), or a
    flatline window (k = 0: it changes only which flags are explained). The best
    candidate pays the search over all of them.
    """
    gauss0 = gaussian_terms(record, mu)
    base = sum(gauss0.values()) + sum(flags0.values())
    options: list[tuple[float, int, dict[str, Any]]] = []
    for s in record:
        if s.chol is None:
            continue
        w0 = whiten(s, s.y - mu[s.sensor])
        g0 = gauss0[s.sensor]
        for onset in onsets:
            step = (s.t >= onset).astype(float)
            for form, design in (
                ("scale", mu[s.sensor] * step),
                ("offset", step),
                ("ramp", _ramp(s, onset)),
            ):
                wd = whiten(s, design)
                dd = float(wd @ wd)
                if dd <= 0.0 or not np.isfinite(dd):
                    continue
                beta = float(wd @ w0) / dd
                dev = base - g0 + sensor_deviance(s, mu[s.sensor] + beta * design)
                knob = {"scale": 1.0 + beta, "offset": beta, "ramp": beta}[form]
                options.append(
                    (dev, 1, {"sensor": s.sensor, "form": form, "onset_d": onset, "value": knob})
                )
        if s.kind == "online" and s.hazard_per_d > 0.0:
            for window in flatline_windows:
                dev = base - flags0[s.sensor] + flag_deviance(s, window)
                options.append(
                    (dev, 0, {"sensor": s.sensor, "form": "flatline", "window_d": list(window)})
                )
    if not options:
        return Candidate("sensor", float("inf"), 0, note="no calibrated sensor")
    n = len(options)
    dev, k, knobs = min(options, key=lambda o: o[0] + class_penalty(o[1], n))
    return Candidate("sensor", dev, k, n_candidates=n, knobs=knobs)


# ------------------------------------------------------------------ the truth simulator


class _Timeout(Exception):
    pass


def _alarm(_signum: int, _frame: FrameType | None) -> NoReturn:
    raise _Timeout


def _fault_key(f: Any) -> tuple[str, float, float, float | None]:
    return (str(f.type), float(f.onset_day), float(f.magnitude), f.duration_days)


def _harness_for(extensions: Sequence[str]) -> Any:
    """The harness settings with only the enabled extensions' initial and feed states.

    The harness seeds every declared extension's state (``X_sao``, ``X_caco3``); with an
    extension switched off that state does not exist, and the simulator refuses it.
    """
    from sim.adm1.defaults import load_extensions
    from sim.run.harness import load_harness_config

    specs = load_extensions().extensions
    names = {c.name for e in extensions for c in specs[e].components}
    cfg = load_harness_config()
    return cfg.model_copy(
        update={
            "initial_extension_states": {
                k: v for k, v in cfg.initial_extension_states.items() if k in names
            },
            "influent_extension_states": {
                k: v for k, v in cfg.influent_extension_states.items() if k in names
            },
        }
    )


class TruthSimulator:
    """The truth of one (scenario, plant), with its faults replaced, cached by variant.

    The scenario is re-timed to the plant's horizon and integrated with the run's own
    seeds and target feed, as ``sim.run.matrix`` generated it.
    """

    def __init__(
        self,
        scenario: Any,
        plant: Any,
        seeds: Any,
        target_feed: str | None,
        timeout_s: float,
        cache_dir: Path | None = None,
    ) -> None:
        self.scenario, self.plant, self.seeds = scenario, plant, seeds
        self.target_feed, self.timeout_s = target_feed, timeout_s
        self.cache: dict[tuple, Any] = {}
        self.cache_dir = cache_dir
        self.from_disk = 0
        self.n_sims = 0
        self.failures: list[str] = []
        self.wall_s = 0.0

    def run(self, faults: Sequence[Any], extensions: Sequence[str] | None = None) -> Any:
        """The truth channels with ``faults`` in place of the scenario's, or None."""
        from sim.run.harness import simulate_truth

        exts = tuple(self.plant.truth_model.extensions if extensions is None else extensions)
        key = (tuple(sorted(_fault_key(f) for f in faults)), exts)
        if key in self.cache:
            return self.cache[key]
        disk = self._disk_path(key)
        refused = disk.with_suffix(".refused") if disk is not None else None
        if refused is not None and refused.is_file():
            self.failures.append(refused.read_text(encoding="utf-8"))
            self.cache[key] = None
            return None
        if disk is not None and disk.is_file():
            with disk.open("rb") as fh:
                self.cache[key] = pickle.load(fh)  # our own cache, on the truth side
            self.from_disk += 1
            return self.cache[key]
        scenario = self.scenario.model_copy(update={"faults": tuple(faults)})
        plant = self.plant
        if extensions is not None:
            model = plant.truth_model.model_copy(update={"extensions": exts})
            plant = plant.model_copy(update={"truth_model": model})
        harness = None if extensions is None else _harness_for(exts)
        started = time.perf_counter()
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, self.timeout_s)
        try:
            out = simulate_truth(
                scenario, plant, self.seeds, harness=harness, target_feed=self.target_feed
            )
            channels = out.channels
        except _Timeout:
            channels = None
            self.failures.append(f"{key}: timed out after {self.timeout_s:g} s")
        except Exception as exc:  # a candidate the simulator refuses is reported, not fatal
            channels = None
            self.failures.append(f"{key}: {type(exc).__name__}: {exc}")
            if refused is not None:  # a refusal is kept; a timeout is retried next time
                refused.parent.mkdir(parents=True, exist_ok=True)
                refused.write_text(self.failures[-1], encoding="utf-8")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
        self.n_sims += 1
        self.wall_s += time.perf_counter() - started
        self.cache[key] = channels
        if disk is not None and channels is not None:
            disk.parent.mkdir(parents=True, exist_ok=True)
            tmp = disk.with_suffix(".tmp")
            with tmp.open("wb") as fh:
                pickle.dump(channels, fh)
            tmp.replace(disk)
        return channels

    def _disk_path(self, key: tuple) -> Path | None:
        """Where a simulation is kept between analyses (a failed one never is)."""
        if self.cache_dir is None:
            return None
        ident = repr((self.scenario.id, self.scenario.duration_days, self.plant.id,
                      self.seeds.as_dict(), self.target_feed, key))  # fmt: skip
        digest = hashlib.sha256(ident.encode()).hexdigest()[:24]
        return self.cache_dir / f"{self.scenario.id}_{self.plant.id}" / f"{digest}.pkl"


# ------------------------------------------------------------------ candidates


def _grid(every: float, t_end: float, start: float = 0.0) -> list[float]:
    return [float(x) for x in np.arange(start, t_end - 1e-9, every)]


def _truth_faults(scenario: Any, label: str) -> list[Any]:
    return [f for f in scenario.faults if LABEL_OF.get(str(f.type)) == label]


def _nuisance(scenario: Any) -> list[Any]:
    return [f for f in scenario.faults if str(f.type) in NUISANCE]


def ode_candidates(scenario: Any, cfg: Any, t_end: float) -> dict[str, list[dict[str, Any]]]:
    """The candidate perturbations of every class that needs a simulation.

    Each candidate is ``{"form": ..., "faults": [Fault, ...], "k": ..., "group": ...}``;
    candidates sharing a ``group`` differ only in a knob fitted on its grid (their best
    pays k), and the groups are the discrete search (N). The truth's own faults are one
    more candidate of their class, in their own group (an optimistic upper bound).
    """
    from scenarios.schema import Fault, FaultType

    def fault(
        kind: FaultType, onset: float, magnitude: float, duration: float | None = None
    ) -> Fault:
        return Fault(type=kind, onset_day=onset, magnitude=magnitude, duration_days=duration)

    out: dict[str, list[dict[str, Any]]] = {"influent": [], "state": [], "parameter": []}
    for day in _grid(cfg.delivery_every_d, t_end):
        for m in cfg.delivery_multiples:
            out["influent"].append(
                {
                    "form": "unrecorded_delivery",
                    "group": ("delivery", day),
                    "k": 1,
                    "faults": [fault(FaultType.UNRECORDED_DELIVERY, day, m)],
                }
            )
    for onset in _grid(cfg.window_onset_every_d, t_end):
        for dur in cfg.mislabel_durations_d:
            for c in cfg.mislabel_concentrations:
                out["influent"].append(
                    {
                        "form": "feed_mislabelled",
                        "group": ("mislabel", onset, dur),
                        "k": 1,
                        "faults": [fault(FaultType.FEED_MISLABELLED, onset, c, dur)],
                    }
                )
        for dur in cfg.moisture_durations_d:
            for c in cfg.moisture_changes:
                out["influent"].append(
                    {
                        "form": "moisture_drift",
                        "group": ("moisture", onset, dur),
                        "k": 1,
                        "faults": [fault(FaultType.MOISTURE_DRIFT, onset, c, dur)],
                    }
                )
    for m in cfg.biomass_multipliers:
        out["state"].append(
            {
                "form": "biomass_misinitialised",
                "group": ("biomass",),
                "k": 1,
                "faults": [fault(FaultType.BIOMASS_MISINITIALISED, 0.0, m)],
            }
        )
    for kind in (FaultType.AMMONIA_INHIBITION_SHIFT, FaultType.HYDROLYSIS_REGIME_CHANGE):
        for onset in _grid(cfg.parameter_onset_every_d, t_end):
            for m in cfg.parameter_multipliers:
                out["parameter"].append(
                    {
                        "form": str(kind),
                        "group": (str(kind), onset),
                        "k": 1,
                        "faults": [fault(kind, onset, m)],
                    }
                )
    for label in out:
        own = _truth_faults(scenario, label)
        visible = [f for f in own if float(f.onset_day) < t_end]
        if visible:
            out[label].append(
                {"form": "truth's own", "group": ("truth",), "k": 1, "faults": list(visible)}
            )
    return out


def _flatline_windows(
    scenario: Any, cfg: Any, t_end: float
) -> tuple[list[float], list[tuple[float, float]]]:
    onsets = _grid(cfg.sensor_onset_every_d, t_end)
    windows = [(o, o + d) for o in onsets for d in cfg.flatline_durations_d]
    for f in _truth_faults(scenario, "sensor"):
        onset = float(f.onset_day)
        if onset < t_end and onset not in onsets:
            onsets.append(onset)
        if str(f.type) == "ch4_analyser_flatline":
            end = onset + (float(f.duration_days) if f.duration_days else t_end)
            if (onset, end) not in windows:
                windows.append((onset, end))
    return sorted(onsets), windows


# ------------------------------------------------------------------ the rule


def admissible(fits: Mapping[str, Candidate], margin: float) -> list[str]:
    """The labels whose score is within ``margin`` of the best class's, in label order."""
    finite = [c.score for c in fits.values() if np.isfinite(c.score)]
    if not finite:
        return []
    best = min(finite)
    return [lab for lab in LABELS if lab in fits and fits[lab].score - best <= margin]


def chance_rate(admissible_set: Sequence[str], truth: Sequence[str]) -> float:
    """What a uniform guess over the six labels scores: |A or truth| / 6 (re-review, item 8)."""
    return len(set(admissible_set) | set(truth)) / len(LABELS)


def truth_representable(faults: Sequence[Mapping[str, Any]]) -> tuple[bool, list[str]]:
    """Whether some class can represent the injected faults, and the limits that apply."""
    limits = sorted(
        {_UNREPRESENTABLE[f["type"]] for f in faults if f.get("type") in _UNREPRESENTABLE}
    )
    return not limits, limits


def class_limited(faults: Sequence[Mapping[str, Any]]) -> list[str]:
    """The declared limits that apply to a cell's injected faults."""
    return truth_representable(faults)[1]


def _best_ode(
    label: str,
    options: Sequence[dict[str, Any]],
    sim: TruthSimulator,
    record: Sequence[SensorData],
    flags0: float,
    extensions: Sequence[str] | None = None,
) -> Candidate:
    """The best candidate of a simulated class; N counts the class's groups."""
    groups = {tuple(o["group"]) for o in options}
    n = max(len(groups), 1)
    best: Candidate | None = None
    failed = 0
    for o in options:
        ch = sim.run([*o["base"], *o["faults"]], o.get("extensions", extensions))
        if ch is None:
            failed += 1
            continue
        per = gaussian_terms(record, predict(ch, record))
        dev = sum(per.values()) + flags0
        c = Candidate(
            label,
            dev,
            int(o["k"]),
            n_candidates=n,
            per_sensor=per,
            knobs={
                "form": o["form"],
                **(
                    {"faults": [f.model_dump(mode="json") for f in o["faults"]]}
                    if o["faults"]
                    else {}
                ),
                **({"extension_off": o["extension_off"]} if "extension_off" in o else {}),
            },
        )
        if best is None or c.score < best.score:
            best = c
    if best is None:
        return Candidate(label, float("inf"), 0, n_candidates=n, note="every candidate failed")
    best.failed = failed
    if failed:
        best.note = f"{failed} of {len(options)} candidate simulations failed"
    return best


def _finite(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


def _cell_setup(
    first_truth: Path, scenarios_dir: Path, scenario: Any = None
) -> tuple[Any, Any, Any, str | None]:
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.matrix import at_plant_horizon
    from sim.run.seeds import RunSeeds

    manifest = json.loads((first_truth / "manifest.json").read_text(encoding="utf-8"))
    plant = load_plant_config(str(manifest["plant"]))
    if scenario is None:
        scenario = at_plant_horizon(
            load_scenario(scenarios_dir / f"{manifest['scenario_id']}.yaml"), plant
        )
    s = manifest["seeds"]
    seeds = RunSeeds.derive(int(s["base"]), str(manifest["plant"]), int(s["replicate"]))
    if seeds.as_dict() != s:
        raise ValueError(f"{first_truth}: the derived seeds do not match the run's")
    return scenario, plant, seeds, manifest.get("target_feed")


def check_truth(sim: TruthSimulator, truth_dir: Path) -> float:
    """Max |difference| between the rebuilt truth's channels and the stored ones."""
    stored = np.load(truth_dir / "channels.npz")
    ch = sim.run(list(sim.scenario.faults))
    if ch is None:
        return float("inf")
    worst = float(np.max(np.abs(np.asarray(ch.t) - stored["t_d"])))
    for name in stored.files:
        if name.startswith("channel_") and name not in ("channel_names", "channel_units"):
            a, b = np.asarray(ch[name[len("channel_") :]], float), stored[name]
            worst = max(worst, float(np.nanmax(np.abs(a - b))) if a.size else 0.0)
    return worst


def analyse_pair(
    runs: Sequence[tuple[str, Path, Path]],
    *,
    scenarios_dir: Path = REPO / "scenarios",
    scenario: Any = None,
    cache_dir: Path | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, dict[str, Any]]:
    """Every tier of one (scenario, plant). ``runs`` is (run id, run dir, truth dir).

    The simulations are shared by the tiers; the fits are per tier. ``scenario`` replaces
    the scenario file re-timed to the plant's horizon (a test's short cell); either way
    the rebuilt truth must reproduce the stored channels exactly. ``cache_dir`` keeps the
    simulations between analyses (keyed by scenario, plant, seeds and candidate).
    """
    cfg = _cfg()
    _PENALTY.update(
        alpha=float(cfg.lr_alpha),
        m=int(cfg.n_alternatives),
        look_elsewhere=bool(cfg.look_elsewhere),
    )
    started_pair = time.perf_counter()
    scenario, plant, seeds, target = _cell_setup(runs[0][2], scenarios_dir, scenario)
    faults_doc = json.loads((runs[0][2] / "faults.json").read_text(encoding="utf-8"))
    declared = [str(f["type"]) for f in faults_doc.get("faults", [])]
    if declared != [str(f.type) for f in scenario.faults]:
        raise ValueError(f"{runs[0][2]}: the scenario file's faults are not the run's")
    sim = TruthSimulator(scenario, plant, seeds, target, float(cfg.sim_timeout_s), cache_dir)
    reproduced = check_truth(sim, runs[0][2])
    if reproduced != 0.0:
        raise ValueError(f"{runs[0][2]}: the rebuilt truth differs from the stored by {reproduced}")
    t_end = calibration_end(scenario.duration_days)
    base = _nuisance(scenario)
    none_ch = sim.run(base)
    if none_ch is None:
        raise RuntimeError(f"the truth less its fault failed to integrate: {sim.failures}")
    noise_scale = 1.0
    for f in base:
        if str(f.type) == "sensor_noise":
            noise_scale *= float(f.magnitude)

    ode = ode_candidates(scenario, cfg, t_end)
    for opts in ode.values():
        for o in opts:
            o["base"] = base
    exts = tuple(plant.truth_model.extensions)
    structural = [
        {
            "form": "extension off",
            "group": (name,),
            "k": 0,
            "faults": [],
            "base": base,
            "extensions": tuple(e for e in exts if e != name),
            "extension_off": name,
        }
        for name in exts
        if name not in STRUCTURAL_LIMITS
    ]
    onsets, windows = _flatline_windows(scenario, cfg, t_end)

    out = {}
    for run_id, run_dir, truth_dir in runs:
        started, n0 = time.perf_counter(), sim.n_sims
        tier = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["tier"]
        faults = json.loads((truth_dir / "faults.json").read_text(encoding="utf-8"))
        record = load_record(run_dir / "observations" / "sensors.json", tier, t_end, noise_scale)
        mu0 = predict(none_ch, record)
        prepare(record, mu0)
        flags = {s.sensor: flag_deviance(s) for s in record}
        flags0 = sum(flags.values())
        g0 = gaussian_terms(record, mu0)
        fits: dict[str, Candidate] = {
            "none": Candidate("none", sum(g0.values()) + flags0, 0, per_sensor=g0)
        }
        fits["sensor"] = sensor_candidates(record, mu0, flags, onsets, windows)
        for label in ("influent", "state", "parameter"):
            fits[label] = _best_ode(label, ode[label], sim, record, flags0)
        fits["structural"] = _best_ode("structural", structural, sim, record, flags0)

        # the truth class's own candidate, scored alone: the reproducibility check of the
        # upper bound (on a Level-0 cell it is `none`)
        truth_ch = sim.run(list(scenario.faults))
        truth_dev = None
        if truth_ch is not None:
            mu_t = predict(truth_ch, record)
            truth_window = None
            for f in scenario.faults:
                if str(f.type) == "ch4_analyser_flatline":
                    end = float(f.onset_day) + float(f.duration_days or t_end)
                    truth_window = (float(f.onset_day), end)
            obs = faults.get("observation", {})
            for s in record:
                if s.sensor in obs.get("scales", {}):
                    onset, factor = obs["scales"][s.sensor]
                    mu_t[s.sensor] = np.where(s.t >= onset, mu_t[s.sensor] * factor, mu_t[s.sensor])
                if s.sensor in obs.get("ramps", {}):
                    onset, rate = obs["ramps"][s.sensor]
                    mu_t[s.sensor] = mu_t[s.sensor] + rate * _ramp(s, onset)
            truth_dev = sum(gaussian_terms(record, mu_t).values()) + sum(
                flag_deviance(s, truth_window if s.sensor == "ch4_fraction" else None)
                for s in record
            )

        truth = [str(x) for x in faults["truth_label"]]
        sets = {
            f"{cfg.margin:g}": admissible(fits, cfg.margin),
            f"{cfg.sensitivity_margin:g}": admissible(fits, cfg.sensitivity_margin),
        }
        primary = sets[f"{cfg.margin:g}"]
        representable, limits = truth_representable(faults.get("faults", []))
        best = min(fits.values(), key=lambda c: c.score)
        doc = {
            "method_version": METHOD_VERSION,
            "run_id": run_id,
            "scenario_id": faults["scenario_id"],
            "level": faults.get("level"),
            "plant": plant.id,
            "tier": tier,
            "truth_label": truth,
            "calibration_end_d": t_end,
            "n_samples": int(sum(int(s.keep.sum()) for s in record)),
            "n_per_sensor": {s.sensor: int(s.keep.sum()) for s in record},
            "n_flags_per_sensor": {s.sensor: int((s.flag & s.flag_seen).sum()) for s in record},
            "sensors": [s.sensor for s in record],
            "noise_scale": noise_scale,
            "truth_reproduced_max_abs": reproduced,
            "truth_candidate_deviance": _finite(truth_dev) if truth_dev is not None else None,
            "margin": cfg.margin,
            "sensitivity_margin": cfg.sensitivity_margin,
            "penalty": {
                "lr_alpha": cfg.lr_alpha,
                "n_alternatives": cfg.n_alternatives,
                "look_elsewhere": bool(cfg.look_elsewhere),
            },
            "admissible": sets,
            "admissible_set": primary,
            "n_admissible": len(primary),
            "chance_rate": chance_rate(primary, truth),
            "none_admissible": "none" in primary,
            # a multi-label truth passes when any one of its labels is admissible
            "truth_admissible": any(t in primary for t in truth),
            "truth_representable": representable,
            "truth_class_limited": limits,
            "structural_not_offered": {k: v for k, v in STRUCTURAL_LIMITS.items() if k in exts},
            "best_label": best.label,
            "classes": {
                lab: {
                    "deviance": _finite(c.deviance),
                    "k": c.k,
                    "n_candidates": c.n_candidates,
                    "penalty": c.penalty,
                    "score": _finite(c.score),
                    "delta": _finite(c.score - best.score),
                    "knobs": c.knobs,
                    "deviance_per_sensor": c.per_sensor,
                    "failed_candidates": c.failed,
                    "note": c.note,
                }
                for lab, c in fits.items()
            },
            "flag_deviance_per_sensor": flags,
            "simulations_new": sim.n_sims - n0,
            "simulations_pair": sim.n_sims,
            "simulations_from_cache": sim.from_disk,
            "simulation_wall_s": round(sim.wall_s, 1),
            "simulation_failures": list(sim.failures),
            "wall_s": round(time.perf_counter() - started, 1),
            "pair_wall_s": round(time.perf_counter() - started_pair, 1),
        }
        out[run_id] = doc
        log(
            f"{faults['scenario_id']} {plant.id}/{tier} {run_id}: A={primary} "
            f"truth={truth} best={best.label} "
            + " ".join(f"{lab}={c.score - best.score:.1f}" for lab, c in fits.items())
            + f" sims={sim.n_sims} {doc['wall_s']} s"
        )
    return out
