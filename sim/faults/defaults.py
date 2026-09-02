"""Loader for the fault-injection configuration under ``configs/faults/``.

The only function in :mod:`sim.faults` that touches the filesystem, and it only reads
(CLAUDE.md rule 1: nothing under ``sim/`` writes).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sim.faults.schema import FaultsConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "faults"
FAULTS_CONFIG = CONFIG_DIR / "faults.yaml"


def load_faults_config(path: Path = FAULTS_CONFIG) -> FaultsConfig:
    """Parse and validate the fault-injection parameters.

    Args:
        path: Location of ``faults.yaml``.

    Returns:
        The validated configuration.

    Raises:
        ValueError: If the file does not contain a YAML mapping.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return FaultsConfig.model_validate(raw)
