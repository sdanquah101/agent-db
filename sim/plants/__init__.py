"""Virtual plants A, B and C: declared configuration and hidden realisations.

:func:`load_plant_config` reads ``configs/plants/plant_<id>.yaml`` (the only file I/O
here). :func:`sample_hidden_geometry` draws the hidden active-volume realisation for a
run from an explicit seed (CLAUDE.md rule 4); the run layer writes it to
``runs/<id>/truth/``. :func:`declared_geometry` and :func:`true_geometry` produce the
:class:`~sim.adm1.schema.PlantGeometry` the ADM1 model takes, from the declared and the
true active volume respectively.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from sim.adm1.schema import PlantGeometry
from sim.plants.schema import Anchoring, PlantConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "plants"
PLANT_IDS = ("A", "B", "C")

__all__ = [
    "CONFIG_DIR",
    "PLANT_IDS",
    "Anchoring",
    "HiddenGeometry",
    "PlantConfig",
    "declared_geometry",
    "load_all_plants",
    "load_plant_config",
    "sample_hidden_geometry",
    "true_geometry",
]


def load_plant_config(plant_id: str, config_dir: Path = CONFIG_DIR) -> PlantConfig:
    """Parse and validate ``plant_<id>.yaml``."""
    path = config_dir / f"plant_{plant_id}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    cfg = PlantConfig.model_validate(raw)
    if cfg.id != plant_id:
        raise ValueError(f"{path}: file is for plant {plant_id!r} but declares id {cfg.id!r}")
    return cfg


def load_all_plants(config_dir: Path = CONFIG_DIR) -> dict[str, PlantConfig]:
    """All three plants, keyed by id."""
    return {pid: load_plant_config(pid, config_dir) for pid in PLANT_IDS}


@dataclass(frozen=True)
class HiddenGeometry:
    """The per-run realisation of what the operator does not know. Hidden truth."""

    plant_id: str
    seed: int
    error_fraction: float
    """Signed relative error of the true active volume, (V_true - V_declared) / V_declared."""
    V_liq_true: float
    """True active liquid volume, m3."""


def sample_hidden_geometry(cfg: PlantConfig, seed: int) -> HiddenGeometry:
    """Draw the hidden active-volume error for one run.

    ``|error| ~ Uniform(error_min, error_max)``; the sign is drawn with probability 1/2
    each way when the config says ``random``. Deterministic in ``seed``.
    """
    rng = np.random.default_rng(seed)
    hav = cfg.hidden_active_volume
    magnitude = float(rng.uniform(hav.error_min, hav.error_max))
    if hav.sign == "random":
        sign = -1.0 if rng.uniform() < 0.5 else 1.0
    else:
        sign = -1.0 if hav.sign == "negative" else 1.0
    error = sign * magnitude
    return HiddenGeometry(
        plant_id=cfg.id,
        seed=seed,
        error_fraction=error,
        V_liq_true=cfg.geometry.V_liq_declared * (1.0 + error),
    )


def declared_geometry(cfg: PlantConfig) -> PlantGeometry:
    """The geometry a workflow is told (declared volume, set-point temperature)."""
    return PlantGeometry(
        V_liq=cfg.geometry.V_liq_declared,
        V_gas=cfg.geometry.V_gas,
        T_op=cfg.temperature.setpoint_K,
    )


def true_geometry(cfg: PlantConfig, hidden: HiddenGeometry) -> PlantGeometry:
    """The geometry the truth model integrates with (true active volume)."""
    if hidden.plant_id != cfg.id:
        raise ValueError(f"hidden geometry is for plant {hidden.plant_id!r}, config is {cfg.id!r}")
    return PlantGeometry(
        V_liq=hidden.V_liq_true,
        V_gas=cfg.geometry.V_gas,
        T_op=cfg.temperature.setpoint_K,
    )
