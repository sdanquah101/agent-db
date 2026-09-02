"""Fault injection (proposal §6.1): a scenario YAML becomes per-layer directives.

* :mod:`sim.faults.schema` — the authoritative meaning of every ``Fault.magnitude``
  (unit, admissible range, the layer that applies it) and the benchmark-card table.
* :mod:`sim.faults.plan` — :func:`build_plan`, the typed directives, and the appliers
  (parameter segmentation, initial-state corruption, the truth reactor's mixing
  structure, the fitted model's extension list).

The influent directives are consumed by :func:`sim.influent.generate_influent` and the
observation directives by :func:`sim.observation.observe`, so each layer applies only its
own. Nothing here writes files (CLAUDE.md rule 1).
"""

from sim.faults.defaults import CONFIG_DIR, INJECTION, load_fault_config
from sim.faults.plan import (
    FaultPlan,
    InfluentFaults,
    MislabelledFeed,
    MoistureRamp,
    ObservationFaults,
    ParameterFaults,
    StateFaults,
    StructureFaults,
    UnrecordedDelivery,
    WorkflowFaults,
    apply_state_faults,
    build_plan,
    declared_faults,
    fitted_extensions,
    parameter_segments,
    truth_mixing,
)
from sim.faults.schema import (
    FAULT_SEMANTICS,
    FaultInjectionConfig,
    FaultLayer,
    FaultSemantics,
    ImperfectMixingConfig,
    benchmark_card_rows,
    semantics_for,
)

__all__ = [
    "CONFIG_DIR",
    "FAULT_SEMANTICS",
    "INJECTION",
    "FaultInjectionConfig",
    "FaultLayer",
    "FaultPlan",
    "FaultSemantics",
    "ImperfectMixingConfig",
    "InfluentFaults",
    "MislabelledFeed",
    "MoistureRamp",
    "ObservationFaults",
    "ParameterFaults",
    "StateFaults",
    "StructureFaults",
    "UnrecordedDelivery",
    "WorkflowFaults",
    "apply_state_faults",
    "benchmark_card_rows",
    "build_plan",
    "declared_faults",
    "fitted_extensions",
    "load_fault_config",
    "parameter_segments",
    "semantics_for",
    "truth_mixing",
]
