"""The three virtual plants (proposal §6.1): declared vs. hidden configuration.

:class:`PlantDeclared` is what an operator or workflow may see; :class:`PlantTruth` is
the hidden configuration drawn by :func:`sample_truth`; :mod:`sim.plants.reactor` runs
the extended ADM1 truth model under the hidden mixing structure. This package never
writes the truth anywhere.
"""

from sim.plants.defaults import load_plant_a_statistics, load_plant_declared
from sim.plants.feed import (
    cod_loading_rate,
    constant_influent,
    extension_influent,
    implied_tkn,
    mix_feeds,
    organic_loading_rate,
    tkn_consistent,
)
from sim.plants.reactor import (
    ReactorModel,
    ReactorResult,
    apply_parameter_overrides,
    compile_reactor,
    initial_state,
    rhs_reactor,
    simulate_reactor,
)
from sim.plants.sampling import sample_truth
from sim.plants.schema import (
    CODFractionation,
    FeedstockSpec,
    FeedstockTruth,
    MixingPrior,
    MixingTruth,
    PlantDeclared,
    PlantTruth,
)

__all__ = [
    "CODFractionation",
    "FeedstockSpec",
    "FeedstockTruth",
    "MixingPrior",
    "MixingTruth",
    "PlantDeclared",
    "PlantTruth",
    "ReactorModel",
    "ReactorResult",
    "apply_parameter_overrides",
    "cod_loading_rate",
    "compile_reactor",
    "constant_influent",
    "extension_influent",
    "implied_tkn",
    "initial_state",
    "load_plant_a_statistics",
    "load_plant_declared",
    "mix_feeds",
    "organic_loading_rate",
    "rhs_reactor",
    "sample_truth",
    "simulate_reactor",
    "tkn_consistent",
]
