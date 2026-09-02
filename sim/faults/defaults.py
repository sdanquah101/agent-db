"""Loader for the fault-injection constants under ``configs/faults/``.

The only function in :mod:`sim.faults` that touches the filesystem.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sim.faults.schema import FaultInjectionConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "faults"
INJECTION = CONFIG_DIR / "injection.yaml"


def load_fault_config(path: Path = INJECTION) -> FaultInjectionConfig:
    """Parse and validate the fault-injection constants."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return FaultInjectionConfig.model_validate(raw)
