"""Loader for the observation configuration under ``configs/observation/``.

The only function in :mod:`sim.observation` that touches the filesystem.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sim.observation.schema import ObservationConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "observation"
SENSORS = CONFIG_DIR / "sensors.yaml"


def load_observation_config(path: Path = SENSORS) -> ObservationConfig:
    """Parse and validate the sensor specifications and tier masks."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return ObservationConfig.model_validate(raw)
