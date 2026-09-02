"""Scenario definitions: the Pydantic schema and the YAML scenario library (§6.3).

Each scenario carries a ground-truth uncertainty-class label and the conclusion a
workflow is expected to reach. Workflows never read these files; the evaluator does.
"""

from scenarios.schema import (
    Budget,
    CorrectConclusion,
    Fault,
    FaultType,
    Plant,
    Scenario,
    Tier,
    TruthLabel,
    load_scenario,
)

__all__ = [
    "Budget",
    "CorrectConclusion",
    "Fault",
    "FaultType",
    "Plant",
    "Scenario",
    "Tier",
    "TruthLabel",
    "load_scenario",
]
