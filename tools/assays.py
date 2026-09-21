"""Requested assays (§6.4): the privileged channel from the truth store to a workflow.

``request_assay(assay, day)`` is the one tool that reads hidden truth, and it does so on
the registry's privileged side only: :class:`AssayServer` holds the run's truth channels
(``truth_store/<id>/channels.npz``), samples the requested channel on the requested day,
applies the **same noise model** the observation layer gives the corresponding lab
sensor (``configs/observation/sensors.yaml``: ``value (1 + cv z1) + sd_abs z2``, two
independent draws, as :func:`sim.observation.model._sensor_series`), and reports the
value on ``day + turnaround``. The draw is keyed ``SeedSequence([seed, assay, channel,
day])``, so asking twice for the same day returns the same number: a workflow cannot
average the noise away by repeating a request, and the record is deterministic (rule 4).

Prices and turnarounds are ``configs/tools/assays.yaml``; the registry charges the price
from the ``assay_units`` budget before the call runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np

from sim.observation import CHANNEL_UNITS, ObservationConfig, load_observation_config
from tools.config import AssayCatalogue, load_assays
from tools.registry import ToolArgumentError, stream_key
from tools.schemas import AssayResult, RequestAssayOutput

__all__ = ["AssayServer"]


class AssayServer:
    """Serves requested assays from a run's truth channels with the observation noise."""

    def __init__(
        self,
        *,
        t: np.ndarray,
        channels: Mapping[str, np.ndarray],
        seed: int,
        catalogue: AssayCatalogue | None = None,
        sensors: ObservationConfig | None = None,
    ) -> None:
        """Hold the truth channels of one run.

        Args:
            t: Channel times, d.
            channels: Channel name -> values on ``t`` (the truth).
            seed: The registry's seed; every assay draw is a keyed child of it.
            catalogue: ``configs/tools/assays.yaml`` (default: loaded).
            sensors: ``configs/observation/sensors.yaml`` (default: loaded).
        """
        self.t = np.asarray(t, dtype=float)
        self._channels = {k: np.asarray(v, dtype=float) for k, v in channels.items()}
        self.seed = int(seed)
        self.catalogue = catalogue or load_assays()
        self.sensors = sensors or load_observation_config()

    @classmethod
    def from_truth_store(
        cls,
        truth_dir: str | Path,
        seed: int,
        catalogue: AssayCatalogue | None = None,
        sensors: ObservationConfig | None = None,
    ) -> AssayServer:
        """Load the channels of ``truth_store/<id>/channels.npz``."""
        with np.load(Path(truth_dir) / "channels.npz") as data:
            names = [str(n) for n in data["channel_names"]]
            channels = {name: np.array(data[f"channel_{name}"]) for name in names}
            t = np.array(data["t_d"])
        return cls(t=t, channels=channels, seed=seed, catalogue=catalogue, sensors=sensors)

    def noise_models(self) -> dict[str, tuple[float, float]]:
        """``sensor -> (cv, sd_abs)`` for every lab sensor the catalogue names."""
        out = {}
        for spec in self.catalogue.assays.values():
            for sensor in (spec.sensor, *spec.companions.values()):
                s = self.sensors.sensors[sensor]
                out[sensor] = (float(s.noise.cv), float(s.noise.sd_abs))
        return out

    def _draw(self, assay: str, channel: str, sensor: str, day: float) -> AssayResult:
        if channel not in self._channels:
            raise ToolArgumentError(
                f"assay {assay!r} samples {channel!r}, which this run did not compute"
            )
        truth = float(np.interp(day, self.t, self._channels[channel]))
        cv, sd_abs = self.noise_models()[sensor]
        key = stream_key("assay", assay, channel)
        rng = np.random.default_rng(np.random.SeedSequence([self.seed, key, round(day * 1000)]))
        z1, z2 = rng.standard_normal(2)
        value = truth * (1.0 + cv * z1) + sd_abs * z2
        sd = float(np.sqrt((cv * truth) ** 2 + sd_abs**2))
        return AssayResult(channel=channel, value=float(value), unit=CHANNEL_UNITS[channel], sd=sd)

    def serve(self, assay: str, day: float) -> RequestAssayOutput:
        """One assay on one day, at the declared turnaround.

        Raises:
            ToolArgumentError: For an unknown assay, a day outside the record, or a
                channel this run does not carry.
        """
        if assay not in self.catalogue.assays:
            raise ToolArgumentError(
                f"unknown assay {assay!r}; the catalogue has {sorted(self.catalogue.assays)}"
            )
        spec = self.catalogue.assays[assay]
        if day < self.t[0] - 1e-9 or day > self.t[-1] + 1e-9:
            raise ToolArgumentError(
                f"day {day} is outside the record [{self.t[0]:g}, {self.t[-1]:g}] d"
            )
        results = [self._draw(assay, spec.channel, spec.sensor, day)]
        for channel, sensor in spec.companions.items():
            results.append(self._draw(assay, channel, sensor, day))
        return RequestAssayOutput(
            assay=assay,
            sample_day=float(day),
            report_day=float(day + spec.turnaround_d),
            results=tuple(results),
            unit_cost=spec.unit_cost,
        )
