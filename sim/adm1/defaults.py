"""Loaders for the frozen ADM1 configuration under ``configs/adm1/``.

These are the only functions in :mod:`sim.adm1` that touch the filesystem; the model
itself takes the loaded objects.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml

from sim.adm1.extensions import ExtensionsConfig
from sim.adm1.model import state_vector
from sim.adm1.petersen import PetersenMatrix, load_petersen
from sim.adm1.schema import ADM1Parameters, PlantGeometry, SolverConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "adm1"
PARAMS_BSM2 = CONFIG_DIR / "params_bsm2.yaml"
PLANT_BSM2 = CONFIG_DIR / "plant_bsm2.yaml"
SOLVER_DEFAULT = CONFIG_DIR / "solver.yaml"
PETERSEN_MATRIX = CONFIG_DIR / "petersen_matrix.yaml"
EXTENSIONS_YAML = CONFIG_DIR / "extensions.yaml"
INITIAL_STATE_RJ2006 = CONFIG_DIR / "initial_state_rj2006.yaml"


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


def load_extensions(path: Path = EXTENSIONS_YAML) -> ExtensionsConfig:
    """The truth-model extension declarations (``extensions.yaml``)."""
    return ExtensionsConfig.model_validate(_mapping(path))


def load_initial_state(path: Path = INITIAL_STATE_RJ2006) -> np.ndarray:
    """The published Rosen & Jeppsson (2006) steady state as a 29-vector.

    Only the run harness's burn-in starts here (``sim.run.harness``); no scenario does.
    The values are the same ones ``scripts/adm1_candidates/common.py`` carries for the
    ring test, moved into ``configs/`` because ``sim/`` may not import disposable probe
    code (decision 2026-09-02).

    Raises:
        ValueError: If the file is not a mapping with ``liquid`` and ``gas`` blocks.
    """
    raw = _mapping(path)
    for block in ("liquid", "gas"):
        if not isinstance(raw.get(block), dict):
            raise ValueError(f"{path}: missing the {block!r} mapping")
    return state_vector(raw["liquid"], raw["gas"])
