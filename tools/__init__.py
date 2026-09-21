"""Frozen tool registry (§6.2): pure, versioned, schema-typed numerical functions.

Every workflow reaches numerical code only through this package. Budgets (simulator
evaluations, wall-clock, assay units) and call logging are enforced here, not in
workflows.

Two sides, one interface (``docs/tool_registry_design.md``):

* the **privileged side** -- :func:`open_registry` builds the :class:`Registry` of a
  generated run: the fitted ADM1 (:mod:`tools.fitted`, which imports :mod:`sim`), the
  assay channel into the truth store (:mod:`tools.assays`), the budget from the scenario,
  the Level-8 directive in memory, and the logs. :mod:`tools.server` serves it on a
  socket and :mod:`tools.sandbox` launches a workflow in a process where ``sim``,
  ``scenarios`` and ``truth_store`` do not resolve;
* the **workflow side** -- :mod:`tools.client`, staged as ``tools`` in that process:
  ``tools.call(name, **args)``, ``tools.remaining()``, ``tools.describe(name)`` and
  ``tools.run`` (the observations), all over the wire.

Importing this package does not import :mod:`sim`; :func:`open_registry` does, lazily.
"""

from __future__ import annotations

from tools.models import (
    AnalyticModel,
    AnalyticStateSpaceModel,
    BudgetExhausted,
    Model,
    StateSpaceModel,
)
from tools.registry import (
    Budget,
    BudgetExceededError,
    Registry,
    ToolArgumentError,
    ToolError,
    ToolFailure,
    ToolSpec,
    UnknownToolError,
)

__all__ = [
    "AnalyticModel",
    "AnalyticStateSpaceModel",
    "Budget",
    "BudgetExceededError",
    "BudgetExhausted",
    "Model",
    "Registry",
    "StateSpaceModel",
    "ToolArgumentError",
    "ToolError",
    "ToolFailure",
    "ToolSpec",
    "UnknownToolError",
    "make_registry",
    "open_registry",
]


def make_registry(**kwargs: object) -> Registry:
    """A registry over the full tool table with no run attached (tests, pure tools).

    Keyword arguments go to :class:`Registry`; ``specs`` defaults to every tool.
    """
    from tools.impl import SPECS

    kwargs.setdefault("specs", SPECS)
    return Registry(**kwargs)  # type: ignore[arg-type]


def open_registry(*args: object, **kwargs: object) -> Registry:
    """The registry of a generated run (privileged side; :mod:`tools.privileged`)."""
    from tools.privileged import open_registry as _open

    return _open(*args, **kwargs)  # type: ignore[arg-type]
