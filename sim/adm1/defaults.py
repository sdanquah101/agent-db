"""Loaders for the frozen ADM1 configuration under ``configs/adm1/``.

These are the only functions in :mod:`sim.adm1` that touch the filesystem; the model
itself takes the loaded objects.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sim.adm1.petersen import PetersenMatrix, load_petersen
from sim.adm1.schema import ADM1Parameters, PlantGeometry, SolverConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "adm1"
PARAMS_BSM2 = CONFIG_DIR / "params_bsm2.yaml"
PLANT_BSM2 = CONFIG_DIR / "plant_bsm2.yaml"
SOLVER_DEFAULT = CONFIG_DIR / "solver.yaml"
PETERSEN_MATRIX = CONFIG_DIR / "petersen_matrix.yaml"


def _mapping(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return raw


def load_parameters(path: Path = PARAMS_BSM2) -> ADM1Parameters:
    """Parameter set from YAML (default: BSM2)."""
    return ADM1Parameters.model_validate(_mapping(path))


def load_plant(path: Path = PLANT_BSM2) -> PlantGeometry:
    """Plant geometry and temperature from YAML (default: BSM2 digester)."""
    return PlantGeometry.model_validate(_mapping(path))


def load_solver_config(path: Path = SOLVER_DEFAULT) -> SolverConfig:
    """Solver settings from YAML."""
    return SolverConfig.model_validate(_mapping(path))


def load_matrix(path: Path = PETERSEN_MATRIX) -> PetersenMatrix:
    """The standard-ADM1 Petersen matrix from YAML."""
    return load_petersen(path)
