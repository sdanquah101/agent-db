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
    FaultLayer,
    FaultSemantics,
    benchmark_card_rows,
    semantics_for,
)

__all__ = [
    "FAULT_SEMANTICS",
    "FaultLayer",
    "FaultPlan",
    "FaultSemantics",
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
    "parameter_segments",
    "semantics_for",
    "truth_mixing",
]
