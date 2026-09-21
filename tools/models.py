"""What a tool calls a "model", and the meter that charges every call to the budget.

A :class:`Model` is a callable ``theta -> {output: array on t}`` with declared parameter
names, defaults, bounds, units and a time grid. Tools never see the fitted ADM1 or a test
function directly: they see this interface, resolved by the registry from a name, and
wrapped in a :class:`MeteredModel` that counts every evaluation against the cell's
budget (CLAUDE.md rule 2; the evaluation-counting rule of
``docs/tool_registry_design.md``). A tool that would overrun is stopped **inside** the
model call by :class:`BudgetExhausted`, so no tool can spend past the limit however it
loops.

:class:`AnalyticModel` is the in-memory form used by tests (Ishigami, a linear-Gaussian
model with a non-identifiable direction) and by the filters' linear systems; it is
registered only through the registry's privileged side. :class:`StateSpaceModel` is the
interface the sequential estimators need: a one-step transition and an observation map.

Nothing here imports :mod:`sim`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

__all__ = [
    "AnalyticModel",
    "AnalyticStateSpaceModel",
    "BudgetExhausted",
    "EvaluationMeter",
    "MeteredModel",
    "Model",
    "StateSpaceModel",
    "summarise",
]


class BudgetExhausted(RuntimeError):
    """Raised inside a model call when the next evaluation would exceed the budget."""


@runtime_checkable
class Model(Protocol):
    """The interface every simulator-backed tool works against."""

    name: str
    parameter_names: tuple[str, ...]
    defaults: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    parameter_units: Mapping[str, str]
    output_names: tuple[str, ...]
    output_units: Mapping[str, str]
    t: np.ndarray
    description: str

    def evaluate(self, theta: np.ndarray, **options: object) -> dict[str, np.ndarray]:
        """Outputs on :attr:`t` for the full parameter vector ``theta``."""
        ...


@runtime_checkable
class StateSpaceModel(Protocol):
    """A discrete-time state-space model for the sequential estimators."""

    name: str
    state_names: tuple[str, ...]
    observation_names: tuple[str, ...]
    parameter_names: tuple[str, ...]
    defaults: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    n_steps: int
    t: np.ndarray

    def transition(self, x: np.ndarray, theta: np.ndarray, k: int) -> np.ndarray:
        """Propagate an ``(n_members, n_state)`` ensemble from step ``k`` to ``k + 1``."""
        ...

    def observe(self, x: np.ndarray, theta: np.ndarray, k: int) -> np.ndarray:
        """Observations ``(n_members, n_obs)`` of an ensemble at step ``k``."""
        ...


@dataclass
class AnalyticModel:
    """A model given as a Python function; the test double of the fitted ADM1.

    ``function(theta) -> {output: array on t}`` (a scalar function returns arrays of
    length one). Registered only by the privileged side.
    """

    name: str
    parameter_names: tuple[str, ...]
    defaults: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    function: Callable[[np.ndarray], Mapping[str, np.ndarray]]
    output_names: tuple[str, ...]
    t: np.ndarray = field(default_factory=lambda: np.array([0.0]))
    parameter_units: Mapping[str, str] = field(default_factory=dict)
    output_units: Mapping[str, str] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        """Normalise the arrays and fill units with ``"-"`` where none are given."""
        self.defaults = np.asarray(self.defaults, dtype=float)
        self.lower = np.asarray(self.lower, dtype=float)
        self.upper = np.asarray(self.upper, dtype=float)
        self.t = np.asarray(self.t, dtype=float)
        k = len(self.parameter_names)
        if self.defaults.shape != (k,) or self.lower.shape != (k,) or self.upper.shape != (k,):
            raise ValueError("defaults, lower and upper must have one entry per parameter")
        if np.any(self.lower > self.upper):
            raise ValueError("lower bounds must not exceed upper bounds")
        self.parameter_units = {n: self.parameter_units.get(n, "-") for n in self.parameter_names}
        self.output_units = {n: self.output_units.get(n, "-") for n in self.output_names}

    def evaluate(self, theta: np.ndarray, **options: object) -> dict[str, np.ndarray]:
        """Call the function; every declared output must come back on the grid."""
        out = self.function(np.asarray(theta, dtype=float))
        result = {}
        for name in self.output_names:
            values = np.atleast_1d(np.asarray(out[name], dtype=float))
            if values.shape != self.t.shape:
                raise ValueError(
                    f"{self.name}: output {name!r} has shape {values.shape}, grid {self.t.shape}"
                )
            result[name] = values
        return result


@dataclass
class AnalyticStateSpaceModel:
    """A state-space model given as Python functions (the filters' linear test system)."""

    name: str
    state_names: tuple[str, ...]
    observation_names: tuple[str, ...]
    transition_fn: Callable[[np.ndarray, np.ndarray, int], np.ndarray]
    observe_fn: Callable[[np.ndarray, np.ndarray, int], np.ndarray]
    n_steps: int
    parameter_names: tuple[str, ...] = ()
    defaults: np.ndarray = field(default_factory=lambda: np.zeros(0))
    lower: np.ndarray = field(default_factory=lambda: np.zeros(0))
    upper: np.ndarray = field(default_factory=lambda: np.zeros(0))
    t: np.ndarray | None = None

    def __post_init__(self) -> None:
        """Default the time axis to the step index."""
        self.defaults = np.asarray(self.defaults, dtype=float)
        self.lower = np.asarray(self.lower, dtype=float)
        self.upper = np.asarray(self.upper, dtype=float)
        if self.t is None:
            self.t = np.arange(self.n_steps, dtype=float)

    def transition(self, x: np.ndarray, theta: np.ndarray, k: int) -> np.ndarray:
        """Propagate the ensemble one step."""
        return np.asarray(self.transition_fn(x, theta, k), dtype=float)

    def observe(self, x: np.ndarray, theta: np.ndarray, k: int) -> np.ndarray:
        """Observe the ensemble."""
        return np.asarray(self.observe_fn(x, theta, k), dtype=float)


class EvaluationMeter:
    """Counts model evaluations against a limit; shared by every model of one registry."""

    def __init__(self, limit: int) -> None:
        """Start an empty meter with ``limit`` evaluations available in total."""
        self.limit = int(limit)
        self.used = 0

    @property
    def remaining(self) -> int:
        """Evaluations still available."""
        return max(self.limit - self.used, 0)

    def charge(self, n: int = 1) -> None:
        """Charge ``n`` evaluations, or raise :class:`BudgetExhausted` without charging."""
        if self.used + n > self.limit:
            raise BudgetExhausted(
                f"simulator budget exhausted: {self.used} of {self.limit} evaluations used, "
                f"{n} more requested"
            )
        self.used += n


class MeteredModel:
    """A :class:`Model` whose every evaluation is charged to a meter.

    Tools receive this and only this; they cannot reach the unmetered model. It also
    records how many evaluations the *current call* made, which the registry reports in
    every output's ``n_evaluations`` and charges to the budget.
    """

    def __init__(self, model: Model, meter: EvaluationMeter) -> None:
        """Wrap ``model`` so that its evaluations are charged to ``meter``."""
        self._model = model
        self._meter = meter
        self.calls = 0

    # -- the interface, delegated ------------------------------------------------
    @property
    def name(self) -> str:
        """The model's name."""
        return self._model.name

    @property
    def parameter_names(self) -> tuple[str, ...]:
        """Parameter names in vector order."""
        return tuple(self._model.parameter_names)

    @property
    def defaults(self) -> np.ndarray:
        """Default parameter vector."""
        return np.asarray(self._model.defaults, dtype=float)

    @property
    def lower(self) -> np.ndarray:
        """Lower bounds."""
        return np.asarray(self._model.lower, dtype=float)

    @property
    def upper(self) -> np.ndarray:
        """Upper bounds."""
        return np.asarray(self._model.upper, dtype=float)

    @property
    def parameter_units(self) -> Mapping[str, str]:
        """Parameter units."""
        return self._model.parameter_units

    @property
    def output_names(self) -> tuple[str, ...]:
        """Output names."""
        return tuple(self._model.output_names)

    @property
    def output_units(self) -> Mapping[str, str]:
        """Output units."""
        return self._model.output_units

    @property
    def t(self) -> np.ndarray:
        """Output time grid, d."""
        return np.asarray(self._model.t, dtype=float)

    @property
    def description(self) -> str:
        """The model in words."""
        return getattr(self._model, "description", "")

    def index(self, names: Sequence[str]) -> np.ndarray:
        """Vector positions of the named parameters.

        Raises:
            KeyError: If a name is not a parameter of the model.
        """
        positions = []
        for name in names:
            if name not in self.parameter_names:
                raise KeyError(f"{name!r} is not a parameter of model {self.name!r}")
            positions.append(self.parameter_names.index(name))
        return np.asarray(positions, dtype=int)

    def theta_from(self, values: Mapping[str, float]) -> np.ndarray:
        """The full parameter vector with the named entries overridden."""
        theta = self.defaults.copy()
        for name, value in values.items():
            theta[self.index([name])[0]] = float(value)
        return theta

    def evaluate(self, theta: np.ndarray, **options: object) -> dict[str, np.ndarray]:
        """One charged evaluation."""
        self._meter.charge(1)
        self.calls += 1
        return self._model.evaluate(np.asarray(theta, dtype=float), **options)


def summarise(
    series: np.ndarray, t: np.ndarray, summary: str, window: tuple[float, float] | None
) -> float:
    """One scalar of a series: its mean / final / max / min over a window."""
    mask = np.ones(t.shape, dtype=bool)
    if window is not None:
        mask = (t >= window[0]) & (t <= window[1])
        if not mask.any():
            raise ValueError(f"window {window} contains no output time")
    values = np.asarray(series, dtype=float)[mask]
    if summary == "mean":
        return float(np.mean(values))
    if summary == "final":
        return float(values[-1])
    if summary == "max":
        return float(np.max(values))
    if summary == "min":
        return float(np.min(values))
    raise ValueError(f"unknown summary {summary!r}")
