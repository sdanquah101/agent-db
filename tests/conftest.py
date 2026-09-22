"""Shared fixtures: the ADM1 configuration, the R&J 2006 state, the probe harness.

And the one short P0 cell the pipeline and the evaluation tests both score.
"""

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


# ------------------------------------------------------------------ the short P0 cell
# A 30-day S0-01 cell of Plant C at Tier B with a 40-evaluation budget, generated once and
# run through the jail once per session: ``tests/test_p0_pipeline.py`` checks P0's output
# contract on it and ``tests/test_eval_end_to_end.py`` scores it (milestone 6).

SHORT_DAYS = 30.0


def _short(scenario_id: str, *, evals: int, wall_min: float, assays: int):
    """A scenario shortened to :data:`SHORT_DAYS` with a small budget (tests only)."""
    from scenarios.schema import load_scenario

    scenario = load_scenario(REPO_ROOT / "scenarios" / f"{scenario_id}.yaml")
    faults = tuple(
        f.model_copy(update={"onset_day": min(f.onset_day, SHORT_DAYS / 2)})
        for f in scenario.faults
    )
    budget = scenario.budget.model_copy(
        update={"simulator_evals": evals, "wall_clock_min": wall_min, "assay_units": assays}
    )
    return scenario.model_copy(
        update={"duration_days": SHORT_DAYS, "faults": faults, "budget": budget}
    )


@pytest.fixture(scope="session")
def store(tmp_path_factory):
    """A run store (with its sibling truth store) shared by the short-cell tests."""
    return tmp_path_factory.mktemp("store")


@pytest.fixture(scope="session")
def tiny_cell(store):
    """S0-01 on Plant C at Tier B, 30 d, 40 evaluations: every expensive step falls back."""
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run

    scenario = _short("S0-01", evals=40, wall_min=20.0, assays=2)
    run = generate_run(scenario, "B", plant=load_plant_config("C"), runs_root=store / "runs")
    return run, scenario


@pytest.fixture(scope="session")
def tiny_result(tiny_cell):
    """The tiny cell run through the jail by the runner: ``(run, scenario, result)``."""
    from tools.runner import run_workflow

    run, scenario = tiny_cell
    result = run_workflow(run.run_id, "p0", runs_root=run.paths.root.parent, scenario=scenario)
    return run, scenario, result
