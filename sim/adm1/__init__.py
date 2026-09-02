"""Standard ADM1 (Batstone et al. 2002, BSM2 form of Rosen & Jeppsson 2006).

Petersen-matrix formulation: stoichiometry is data (``configs/adm1/petersen_matrix.yaml``),
rates and physico-chemistry are pure functions, and :func:`simulate` integrates the
29-state ODE (26 liquid states + 3 headspace states) with SciPy's implicit solvers.
"""

from sim.adm1.defaults import load_matrix, load_parameters, load_plant, load_solver_config
from sim.adm1.model import CompiledModel, compile_model, derived_quantities, rhs, simulate
from sim.adm1.petersen import PetersenMatrix, compile_stoichiometry, conservation_residuals
from sim.adm1.schema import (
    GAS_STATE_NAMES,
    LIQUID_STATE_NAMES,
    N_STATES,
    STATE_NAMES,
    ADM1Parameters,
    Influent,
    PlantGeometry,
    SimulationResult,
    SolverConfig,
    SolverStats,
)

__all__ = [
    "GAS_STATE_NAMES",
    "LIQUID_STATE_NAMES",
    "N_STATES",
    "STATE_NAMES",
    "ADM1Parameters",
    "CompiledModel",
    "Influent",
    "PetersenMatrix",
    "PlantGeometry",
    "SimulationResult",
    "SolverConfig",
    "SolverStats",
    "compile_model",
    "compile_stoichiometry",
    "conservation_residuals",
    "derived_quantities",
    "load_matrix",
    "load_parameters",
    "load_plant",
    "load_solver_config",
    "rhs",
    "simulate",
]
