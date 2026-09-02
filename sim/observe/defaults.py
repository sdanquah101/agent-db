"""Loader for the observation-model configuration under ``configs/observe/``.

The only function in :mod:`sim.observe` that touches the filesystem, and it only reads
(CLAUDE.md rule 1: nothing under ``sim/`` writes).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sim.observe.schema import ObservationConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "observe"
OBSERVATION_CONFIG = CONFIG_DIR / "observation.yaml"


def load_observation_config(path: Path = OBSERVATION_CONFIG) -> ObservationConfig:
    """Parse and validate the observation catalogue, instruments and tiers.

    Args:
        path: Location of ``observation.yaml``.

    Returns:
        The validated configuration.

    Raises:
        ValueError: If the file does not contain a YAML mapping.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return ObservationConfig.model_validate(raw)
