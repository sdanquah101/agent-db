"""Fault-injection API (proposal §6.1, §6.3): a scenario YAML compiled to truth variants.

    "Any scenario is a declarative YAML file specifying plant, tier, duration, fault
    type(s), onset time, magnitude and the ground-truth label."

A scenario declares *what* is wrong; this package decides *where* that is applied, and
returns the variants as data for the run harness to use:

======================  ==================================================================
Layer                   What the compiler produces
======================  ==================================================================
sensor                  :class:`~sim.observe.schema.SensorFault` objects for
                        :func:`sim.observe.model.observe`
influent                :class:`~sim.influent.generator.FeedModifier` objects for
                        :func:`sim.influent.generator.generate_influent` — the generator's
                        *parameters* and the catalogue -> influent mapping, never a
                        post-hoc edit of what it produced
state                   multipliers on the truth run's initial state
parameter               a :class:`~sim.faults.compiler.ParameterSchedule`: bounded,
                        time-varying truth parameters
structural              a :class:`~sim.faults.compiler.StructuralVariant`: which
                        extensions the *fitted* model gets (the truth keeps its own), and
                        the two-zone mixing structure of ``sim/plants/mixing.py``
workflow                carried in the record for the tool registry to honour (§6.2)
======================  ==================================================================

:mod:`sim.faults.schema` holds the two authoritative tables — which layer each fault type
belongs to and what its magnitude means — and the typed configuration; all numbers are
DESIGN content in ``configs/faults/faults.yaml``.

Nothing here writes: the run harness owns ``runs/<id>/truth/`` (CLAUDE.md rule 1).
"""

from sim.faults.compiler import (
    CompiledFaults,
    ParameterSchedule,
    StateVariant,
    StructuralVariant,
    WorkflowFault,
    compile_faults,
    magnitude_table,
    mislabelled_fractionation,
)
from sim.faults.defaults import CONFIG_DIR, FAULTS_CONFIG, load_faults_config
from sim.faults.schema import (
    FAULT_LAYER,
    FAULT_MAGNITUDE,
    FaultLayer,
    FaultsConfig,
    MagnitudeBounds,
    MagnitudeSpec,
)

__all__ = [
    "CONFIG_DIR",
    "FAULTS_CONFIG",
    "FAULT_LAYER",
    "FAULT_MAGNITUDE",
    "CompiledFaults",
    "FaultLayer",
    "FaultsConfig",
    "MagnitudeBounds",
    "MagnitudeSpec",
    "ParameterSchedule",
    "StateVariant",
    "StructuralVariant",
    "WorkflowFault",
    "compile_faults",
    "load_faults_config",
    "magnitude_table",
    "mislabelled_fractionation",
]
