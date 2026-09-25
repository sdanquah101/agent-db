"""Pure-noise records for the joint calibration of the admissibility rule (method version 4).

A record is drawn by the observation model itself (``sim.observation.model._sensor_series``)
around a known smooth truth: white noise, the sensor's recalibrated drift walk, pH fouling,
flatline episodes and missingness, exactly as a run's record is drawn. Optionally the white
noise is replaced by an AR(1) process of the same marginal sd (correlation the observation
model does not have), to measure the method's limit.

On each record every class competes with ``none`` at once:
- the sensor class runs its real closed form and flatline search over the real grids;
- each simulated class is the linear-Gaussian surrogate of its search: one fitted knob per
  candidate group gains an independent chi2(1) (the exact gain of a one-knob GLS fit
  under the right covariance, and the worst case of independent directions), best of the
  class's group count; an extension left out is given the same gain at k = 0, the worst
  case of an alternative that happens to point along the noise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from distinguish.analysis import (
    Candidate,
    admissible,
    flag_deviance,
    gaussian_terms,
    load_record,
    prepare,
    sensor_candidates,
)

TIER = "B"
HORIZON_D = 200.0
T_END = 150.0
# the group counts of the simulated classes on a 200-d cell (the grids of configs/eval.yaml)
GROUPS = {"influent": 24, "state": 1, "parameter": 8}
# four extensions, though three are offered (precipitation cannot be switched off): conservative
N_EXTENSIONS = 4


class _Channels:
    """A smooth truth for every channel the tier's calibrated sensors read."""

    def __init__(self, levels: dict[str, float]) -> None:
        self.t = np.arange(0.0, HORIZON_D + 1e-9, 0.25)
        self._v = {
            c: lv * (1.0 + 0.1 * np.sin(2 * np.pi * self.t / 90.0)) for c, lv in levels.items()
        }

    def __getitem__(self, name: str) -> np.ndarray:
        return self._v[name]


class _AR1Stream:
    """A block stream whose normal draws are AR(1) with unit marginal variance."""

    def __init__(self, rng: np.random.Generator, rho: float) -> None:
        self.rng, self.rho = rng, rho

    def uniform(self, size: int) -> np.ndarray:
        return self.rng.uniform(size=size)

    def standard_normal(self, size: int) -> np.ndarray:
        e = self.rng.standard_normal(size)
        z = np.empty(size)
        z[0] = e[0]
        for i in range(1, size):
            z[i] = self.rho * z[i - 1] + np.sqrt(1.0 - self.rho**2) * e[i]
        return z


LEVELS = {
    "q_gas_stp_dry": 3000.0,
    "ch4_fraction": 0.62,
    "pH": 7.2,
    "alkalinity_total": 12.0,
    "vfa_titrimetric": 0.4,
    "tan": 1.1,
    "cod_total": 30.0,
}


def noise_record(seed: int, directory: Path, rho: float = 0.0) -> tuple[list[Any], dict]:
    """One pure-noise record, written as ``sensors.json`` and read back by ``load_record``."""
    from sim.faults.plan import ObservationFaults
    from sim.observation import load_observation_config
    from sim.observation.model import _sensor_series

    obs = load_observation_config()
    spec_tier = obs.tiers[TIER]
    channels = _Channels(LEVELS)
    flags = np.zeros(channels.t.size, dtype=bool)
    sensors = {}
    for i, name in enumerate(("gas_flow", "ch4_fraction", "ph", "alkalinity", "vfa_total", "tan",
                              "cod_total")):  # fmt: skip
        spec = obs.sensors[name]

        def stream(block: int, _i: int = i) -> Any:
            rng = np.random.default_rng([seed, _i, block])
            return _AR1Stream(rng, rho) if rho and block in (3, 4) else rng

        series = _sensor_series(
            spec, channels, HORIZON_D, flags, flags, stream, ObservationFaults(),
            obs.missingness.model_for(TIER, spec.kind), 0.0,
            spec_tier.recalibration_interval_d,
        )  # fmt: skip
        sensors[name] = {
            "channel": spec.channel,
            "sample_t_d": series.sample_t.tolist(),
            "value": [None if not np.isfinite(v) else float(v) for v in series.value],
            "missing": series.missing.tolist(),
            "flatlined": series.flatlined.tolist(),
            "saturated": series.saturated.tolist(),
            "fouled": series.fouled.tolist(),
        }
    path = directory / f"sensors_{seed}.json"
    path.write_text(json.dumps({"sensors": sensors}))
    record = load_record(path, TIER, T_END)
    t_ch = channels.t
    mu = {s.sensor: np.interp(s.t, t_ch, channels[s.channel]) for s in record}
    path.unlink()
    return record, mu


def noise_trial(seed: int, directory: Path, cfg: Any, rho: float = 0.0) -> dict[str, Candidate]:
    """Every class on one pure-noise record."""
    record, mu = noise_record(seed, directory, rho)
    prepare(record, mu)
    flags = {s.sensor: flag_deviance(s) for s in record}
    g0 = gaussian_terms(record, mu)
    none = sum(g0.values()) + sum(flags.values())
    onsets = [float(x) for x in np.arange(0.0, T_END - 1e-9, cfg.sensor_onset_every_d)]
    windows = [(o, o + d) for o in onsets for d in cfg.flatline_durations_d]
    rng = np.random.default_rng([seed, 99])
    fits = {
        "none": Candidate("none", none, 0),
        "sensor": sensor_candidates(record, mu, flags, onsets, windows),
    }
    for label, n in GROUPS.items():
        gain = float(rng.chisquare(1, size=n).max())
        fits[label] = Candidate(label, none - gain, 1, n_candidates=n)
    gain = float(rng.chisquare(1, size=N_EXTENSIONS).max())
    fits["structural"] = Candidate("structural", none - gain, 0, n_candidates=N_EXTENSIONS)
    return fits


def none_admissible_rate(
    n: int, directory: Path, cfg: Any, rho: float = 0.0, seed0: int = 0
) -> float:
    """The fraction of ``n`` pure-noise records on which ``none`` is admissible."""
    kept = [
        "none" in admissible(noise_trial(seed0 + i, directory, cfg, rho), cfg.margin)
        for i in range(n)
    ]
    return float(np.mean(kept))
