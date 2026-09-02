"""Shared fixtures: default ADM1 configuration, the R&J 2006 state, and the probe harness."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from sim.adm1 import load_matrix, load_parameters, load_plant, load_solver_config
from sim.adm1.model import state_vector

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_DIR = REPO_ROOT / "scripts" / "adm1_candidates"

#: Headspace part of the Rosen & Jeppsson (2006) steady state (Table 5), kg COD/m3 for
#: H2/CH4 and kmol C/m3 for CO2. The liquid part comes from the probe harness.
RJ2006_GAS_STATE = {"S_gas_h2": 1.1032e-5, "S_gas_ch4": 1.6535, "S_gas_co2": 0.0135}


@pytest.fixture(scope="session")
def probe_common() -> types.ModuleType:
    """`scripts/adm1_candidates/common.py`, the single definition of Probes 1 and 2."""
    spec = importlib.util.spec_from_file_location("adm1_probe_common", CANDIDATES_DIR / "common.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def adm1_params():
    return load_parameters()


@pytest.fixture(scope="session")
def adm1_plant():
    return load_plant()


@pytest.fixture(scope="session")
def adm1_solver():
    return load_solver_config()


@pytest.fixture(scope="session")
def adm1_matrix():
    return load_matrix()


@pytest.fixture(scope="session")
def rj2006_state(probe_common) -> np.ndarray:
    """The 29-state R&J 2006 steady state used to initialise every probe."""
    return state_vector(probe_common.STEADY_STATE_RJ2006, RJ2006_GAS_STATE)
