"""Loaders for the plant configurations under ``configs/plants/``.

The only functions in :mod:`sim.plants` that touch the filesystem.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sim.plants.schema import PlantDeclared

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "plants"
PLANT_FILES: dict[str, Path] = {
    "A": CONFIG_DIR / "plant_a.yaml",
    "B": CONFIG_DIR / "plant_b.yaml",
    "C": CONFIG_DIR / "plant_c.yaml",
}
PLANT_A_STATISTICS = CONFIG_DIR / "plant_a_statistics.yaml"


def _mapping(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return raw


def load_plant_declared(plant: str | Path) -> PlantDeclared:
    """The declared configuration of plant ``"A"``, ``"B"`` or ``"C"``, or of a YAML path."""
    path = PLANT_FILES[plant] if isinstance(plant, str) and plant in PLANT_FILES else Path(plant)
    return PlantDeclared.model_validate(_mapping(path))


def load_plant_a_statistics(path: Path = PLANT_A_STATISTICS) -> dict:
    """The Plant-A anchor statistics (Tisocco et al. envelopes) as a plain mapping."""
    return _mapping(path)
