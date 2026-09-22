"""The registry: one interface through which every workflow calls every tool (rule 2).

``Registry.call(name, **args)`` does, in order (``docs/tool_registry_design.md`` §1):

1. **validates** the arguments against the tool's Pydantic input (rule 6: units on every
   field), logging a failure as ``error``;
2. **checks the budget**: the tool's declared evaluation bound against what is left, the
   wall clock since the registry was opened against the cell's allowance, and an assay
   request's price against the assay units left -- a call that would exceed any of them is
   refused with outcome ``budget_exceeded`` and nothing runs;
3. **applies the Level-8 directive**: a tool the run's ``WorkflowFaults.tool_failure``
   names returns its realistic failure payload, with the row's probability from a keyed
   stream, and the outcome is ``injected_failure``. The workflow is *not* told; the log is;
4. **runs** the tool against models wrapped in a :class:`~tools.models.MeteredModel`, so
   every simulator evaluation is counted inside the tool and a tool that would overrun is
   stopped mid-way (outcome ``budget_exceeded``, partial result discarded, evaluations made
   so far charged);
5. **logs** one :class:`~state.provenance.CallRecord` to the run's visible
   ``calls.jsonl`` (projection: no timestamp, no runtime) and one, with both, to the
   truth-side log (rule 3), continuing the harness's sequence;
6. **returns** the Pydantic output.

Nothing in this module imports :mod:`sim`. The fitted ADM1 (:mod:`tools.fitted`) and the
assay server (:mod:`tools.assays`) do, and are attached by the privileged side
(:func:`tools.open_registry`); a registry built without them serves the pure tools only.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError

from state.provenance import CallLog, Outcome, args_hash
from tools import config as cfg
from tools.models import (
    BudgetExhausted,
    EvaluationMeter,
    MeteredModel,
    Model,
    StateSpaceModel,
)
from tools.schemas import RemainingBudget, ToolInput, ToolOutput

__all__ = [
    "Budget",
    "BudgetExceededError",
    "CallOutcome",
    "Registry",
    "ToolArgumentError",
    "ToolContext",
    "ToolError",
    "ToolFailure",
    "ToolSpec",
    "UnknownToolError",
    "stream_key",
]


class ToolError(Exception):
    """A call failed; the failure is in the log as ``error``."""


class ToolArgumentError(ToolError):
    """The arguments did not validate against the tool's input schema."""


class BudgetExceededError(ToolError):
    """The call was refused because it would exceed the cell's budget."""


class UnknownToolError(ToolError):
    """No tool of that name is registered."""


_STREAM_DOMAIN = "ad-agentbench/tools"


def stream_key(*parts: str) -> int:
    """A stable 64-bit identity for a named stream (as the observation model keys sensors)."""
    digest = hashlib.sha256("|".join((_STREAM_DOMAIN, *parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True)
class Budget:
    """The cell's envelope (scenario ``budget`` block, §7): identical across workflows."""

    simulator_evals: int
    wall_clock_min: float
    assay_units: int

    @classmethod
    def of(cls, budget: Any) -> Budget:
        """From anything with the three attributes (``scenarios.schema.Budget`` included)."""
        return cls(
            simulator_evals=int(budget.simulator_evals),
            wall_clock_min=float(budget.wall_clock_min),
            assay_units=int(budget.assay_units),
        )


@dataclass(frozen=True)
class ToolFailure:
    """One Level-8 directive: the named tool fails with this probability per call."""

    tool: str
    probability: float


class ToolConfigs:
    """Every ``configs/tools/*.yaml``, loaded once per registry."""

    @cached_property
    def registry(self) -> cfg.RegistryConfig:
        """``registry.yaml``."""
        return cfg.load_registry()

    @cached_property
    def model(self) -> cfg.FittedModelConfig:
        """``model.yaml``."""
        return cfg.load_fitted_model()

    @cached_property
    def assays(self) -> cfg.AssayCatalogue:
        """``assays.yaml``."""
        return cfg.load_assays()

    @cached_property
    def data_qc(self) -> cfg.DataQCConfig:
        """``data_qc.yaml``."""
        return cfg.load_data_qc()

    @cached_property
    def mass_balance(self) -> cfg.MassBalanceConfig:
        """``mass_balance.yaml``."""
        return cfg.load_mass_balance()

    @cached_property
    def gsa(self) -> cfg.GSAConfig:
        """``gsa.yaml``."""
        return cfg.load_gsa()

    @cached_property
    def identifiability(self) -> cfg.IdentifiabilityConfig:
        """``identifiability.yaml``."""
        return cfg.load_identifiability()

    @cached_property
    def fitters(self) -> cfg.FittersConfig:
        """``fitters.yaml``."""
        return cfg.load_fitters()

    @cached_property
    def mcmc(self) -> cfg.MCMCConfig:
        """``mcmc.yaml``."""
        return cfg.load_mcmc()

    @cached_property
    def validate(self) -> cfg.ValidateConfig:
        """``validate.yaml``."""
        return cfg.load_validate()

    @cached_property
    def residual_diag(self) -> cfg.ResidualDiagConfig:
        """``residual_diag.yaml``."""
        return cfg.load_residual_diag()

    @cached_property
    def filters(self) -> cfg.FiltersConfig:
        """``filters.yaml``."""
        return cfg.load_filters()

    @cached_property
    def voi(self) -> cfg.VOIConfig:
        """``voi.yaml``."""
        return cfg.load_voi()


@dataclass
class ToolContext:
    """What a tool implementation is handed: metered models, configs, the assay channel."""

    configs: ToolConfigs
    meter: EvaluationMeter
    models: Mapping[str, Model]
    state_space_models: Mapping[str, StateSpaceModel]
    assay_server: Any | None
    """The privileged assay channel (:class:`tools.assays.AssayServer`), or ``None``."""
    seed_domain: int
    """The registry's seed, for streams a tool derives beyond its own ``seed`` argument."""
    _metered: list[MeteredModel] = field(default_factory=list)

    def model(self, name: str) -> MeteredModel:
        """The named model, metered.

        Raises:
            ToolArgumentError: If no model of that name is registered.
        """
        if name not in self.models:
            raise ToolArgumentError(
                f"unknown model {name!r}; registered models are {sorted(self.models)}"
            )
        metered = MeteredModel(self.models[name], self.meter)
        self._metered.append(metered)
        return metered

    def state_space(self, name: str) -> StateSpaceModel:
        """The named state-space model (its transitions are charged by the tool).

        Raises:
            ToolArgumentError: If no model of that name is registered.
        """
        if name not in self.state_space_models:
            raise ToolArgumentError(
                f"unknown state-space model {name!r}; registered are "
                f"{sorted(self.state_space_models)}"
            )
        return self.state_space_models[name]

    @property
    def evaluations_used(self) -> int:
        """Model evaluations made through this context so far."""
        return sum(m.calls for m in self._metered)


@dataclass(frozen=True)
class ToolSpec:
    """One tool: its schemas, its implementation and its cost bound."""

    name: str
    input_model: type[ToolInput]
    output_model: type[ToolOutput]
    run: Callable[[Any, ToolContext], ToolOutput]
    cost: Callable[[Any, ToolContext], int]
    """Upper bound on the simulator evaluations a call will make."""
    failure: Callable[[Any, ToolContext, np.random.Generator], ToolOutput] | None = None
    """The Level-8 payload builder, for a tool the fault catalogue can name."""
    assay_cost: Callable[[Any, ToolContext], int] | None = None
    """Assay units a call spends, for the assay tool."""


@dataclass(frozen=True)
class CallOutcome:
    """What the registry recorded about the last call (for the transport and tests).

    ``seq`` and ``args_hash`` are the visible log line's (``runs/<id>/calls.jsonl``), so a
    workflow's own action record (§6.6) can name the call the way the log does; ``seq`` is
    ``None`` for a registry that logs nothing visible. Added for the task state (the P0
    session, 2026-09-21).
    """

    name: str
    outcome: Outcome
    """The truth-side outcome (``injected_failure`` included)."""
    detail: str
    n_evaluations: int
    seq: int | None = None
    args_hash: str = ""
    version: str = ""
    visible_outcome: Outcome = "ok"
    """The outcome the visible log carries (an injected failure reads ``ok``)."""

    def as_record(self) -> dict[str, Any]:
        """The JSON-safe reference a call envelope carries: nothing the visible log lacks."""
        return {
            "seq": self.seq,
            "args_hash": self.args_hash,
            "version": self.version,
            "outcome": self.visible_outcome,
        }


class Registry:
    """The tool registry of one run (§6.2)."""

    def __init__(
        self,
        *,
        specs: Mapping[str, ToolSpec],
        budget: Budget,
        seed: int,
        run_dir: str | Path | None = None,
        truth_log_dir: str | Path | None = None,
        tool_failures: Sequence[ToolFailure | tuple[str, float]] = (),
        models: Mapping[str, Model] | None = None,
        state_space_models: Mapping[str, StateSpaceModel] | None = None,
        assay_server: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        configs: ToolConfigs | None = None,
    ) -> None:
        """Open the registry of a run.

        Args:
            specs: The tools, by name (:data:`tools.impl.SPECS` for the full table).
            budget: The cell's envelope.
            seed: The registry's own seed: keys the Level-8 stream and the assay noise.
                The privileged side derives it from the run's observation seed.
            run_dir: ``runs/<id>/``; its ``calls.jsonl`` receives the visible projection.
                ``None`` logs nothing visible (in-memory tests only).
            truth_log_dir: ``truth_store/<id>/``; its ``calls.jsonl`` receives the full
                record with timestamps and runtimes.
            tool_failures: The run's ``WorkflowFaults.tool_failure`` directives, in memory.
            models: Simulator models by name (``adm1_fitted`` from the privileged side).
            state_space_models: State-space models for the filters.
            assay_server: The privileged assay channel, or ``None``.
            clock: A monotonic clock in seconds (injectable for the wall-clock tests).
            configs: Loaded tool configs (default: load from ``configs/tools/``).
        """
        self._specs = dict(specs)
        self.budget = budget
        self.seed = int(seed)
        self._clock = clock
        self._opened = clock()
        self._visible = CallLog(run_dir, projection=True) if run_dir is not None else None
        self._full = CallLog(truth_log_dir) if truth_log_dir is not None else None
        self._meter = EvaluationMeter(budget.simulator_evals)
        self._assay_units_used = 0
        self._n_calls = 0
        self._models: dict[str, Model] = dict(models or {})
        self._state_space: dict[str, StateSpaceModel] = dict(state_space_models or {})
        self._assay_server = assay_server
        self.configs = configs or ToolConfigs()
        self._failures: dict[str, tuple[float, np.random.Generator]] = {}
        for item in tool_failures:
            directive = item if isinstance(item, ToolFailure) else ToolFailure(*item)
            self._failures[directive.tool] = (
                float(directive.probability),
                np.random.default_rng(
                    np.random.SeedSequence([self.seed, stream_key("tool_failure", directive.tool)])
                ),
            )
        self.last: CallOutcome | None = None
        # the clock start is a record (the coordinator's condition on wall clock as time
        # since opening, 2026-09-21): the truth-side copy carries the timestamp the
        # evaluator reconstructs the allowance from; the projection carries the fact that
        # the registry opened and the budget it opened with, which the workflow can read
        # from `remaining()` anyway
        self._log(
            "registry.open",
            self.configs.registry.registry_version,
            {
                "simulator_evals": budget.simulator_evals,
                "wall_clock_min": budget.wall_clock_min,
                "assay_units": budget.assay_units,
            },
            self._opened,
            "ok",
            "clock start: the wall-clock allowance runs from this record",
            0,
        )
        self._n_calls = 0

    # -- privileged side ---------------------------------------------------------
    def register_model(self, name: str, model: Model) -> None:
        """Register a simulator model (privileged side only; never over the wire)."""
        self._models[name] = model

    def register_state_space_model(self, name: str, model: StateSpaceModel) -> None:
        """Register a state-space model (privileged side only)."""
        self._state_space[name] = model

    # -- the public surface ------------------------------------------------------
    @property
    def tools(self) -> tuple[str, ...]:
        """Every registered tool name, sorted."""
        return tuple(sorted(self._specs))

    def version_of(self, name: str) -> str:
        """The version string logged with a tool's calls."""
        return self.configs.registry.tool_versions.get(name, self.configs.registry.registry_version)

    def describe(self, name: str) -> dict[str, Any]:
        """A tool's version and its input / output JSON schemas.

        Raises:
            UnknownToolError: If the tool is not registered.
        """
        spec = self._spec(name)
        return {
            "name": name,
            "version": self.version_of(name),
            "input_schema": spec.input_model.model_json_schema(),
            "output_schema": spec.output_model.model_json_schema(),
        }

    @property
    def evaluations_used(self) -> int:
        """Simulator evaluations the meter has charged so far (privileged side)."""
        return int(self._meter.used)

    @property
    def assay_units_used(self) -> int:
        """Assay units charged so far (privileged side)."""
        return int(self._assay_units_used)

    def remaining(self) -> RemainingBudget:
        """The budget left, for the task state (§6.6)."""
        return RemainingBudget(
            simulator_evals=self._meter.remaining,
            simulator_evals_total=self.budget.simulator_evals,
            wall_clock_min=max(self.budget.wall_clock_min - self._elapsed_min(), 0.0),
            wall_clock_min_total=self.budget.wall_clock_min,
            assay_units=max(self.budget.assay_units - self._assay_units_used, 0),
            assay_units_total=self.budget.assay_units,
            n_calls=self._n_calls,
        )

    def call(self, name: str, **args: Any) -> ToolOutput:
        """Call one tool (see the module docstring for the sequence).

        Returns:
            The tool's output. An injected failure is returned like any other result.

        Raises:
            UnknownToolError: No such tool.
            ToolArgumentError: The arguments do not validate, or name an unknown model.
            BudgetExceededError: The call would exceed, or exceeded, the budget.
            ToolError: The tool raised; the message is in the log.
        """
        spec = self._spec(name)
        version = self.version_of(name)
        started = self._clock()
        context = self._context()
        # what THIS call charges the meter, on every path: the meter's count before and
        # after, never the metered models' own tally, which misses a tool that charges the
        # meter directly (the filters charge per ensemble transition; the coordinator's
        # review of PR #19, blocker B1, 2026-09-22)
        before = self._meter.used

        def charged() -> int:
            return int(self._meter.used - before)

        try:
            inp = spec.input_model.model_validate(args)
        except ValidationError as exc:
            self._log(name, version, args, started, "error", f"ValidationError: {exc}", charged())
            raise ToolArgumentError(f"{name}: {exc}") from exc
        hashed = inp.model_dump()

        try:
            refusal = self._refusal(spec, inp, context)
        except ToolError as exc:
            self._log(
                name, version, hashed, started, "error", f"{type(exc).__name__}: {exc}", charged()
            )
            raise
        if refusal is not None:
            self._log(name, version, hashed, started, "budget_exceeded", refusal, charged())
            raise BudgetExceededError(f"{name}: {refusal}")

        if self._injected(name):
            rng = np.random.default_rng(
                np.random.SeedSequence(
                    [self.seed, stream_key("failure_payload", name), self._n_calls]
                )
            )
            assert spec.failure is not None  # _injected checks it
            try:
                output = spec.failure(inp, context, rng)
            except Exception as exc:
                self._log(
                    name,
                    version,
                    hashed,
                    started,
                    "error",
                    f"{type(exc).__name__}: {exc}",
                    charged(),
                )
                raise ToolError(f"{name}: {exc}") from exc
            self._log(name, version, hashed, started, "injected_failure", "", charged())
            return output

        try:
            output = spec.run(inp, context)
        except BudgetExhausted as exc:
            self._log(name, version, hashed, started, "budget_exceeded", str(exc), charged())
            raise BudgetExceededError(f"{name}: {exc}") from exc
        except ToolError as exc:
            self._log(
                name, version, hashed, started, "error", f"{type(exc).__name__}: {exc}", charged()
            )
            raise
        except Exception as exc:
            self._log(
                name, version, hashed, started, "error", f"{type(exc).__name__}: {exc}", charged()
            )
            raise ToolError(f"{name}: {type(exc).__name__}: {exc}") from exc

        units = 0
        if spec.assay_cost is not None:
            units = int(spec.assay_cost(inp, context))
            self._assay_units_used += units
        self._log(name, version, hashed, started, "ok", "", charged(), units)
        return output

    def call_json(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        """The transport's form of :meth:`call`: never raises, returns a JSON-safe envelope.

        ``{"outcome": "ok", "output": {...}}`` on success (an injected failure looks the
        same to the caller), ``{"outcome": "budget_exceeded" | "error", "error": msg}``
        otherwise. Every envelope carries ``"record"``: the visible log line's ``seq`` and
        ``args_hash`` and the tool's version (:meth:`CallOutcome.as_record`), so a workflow
        can name the call in its task state exactly as ``calls.jsonl`` does.
        """
        before = self.last
        try:
            output = self.call(name, **dict(args))
        except BudgetExceededError as exc:
            return {"outcome": "budget_exceeded", "error": str(exc), "record": self._record(before)}
        except ToolError as exc:
            return {
                "outcome": "error",
                "error": str(exc),
                "kind": type(exc).__name__,
                "record": self._record(before),
            }
        return {
            "outcome": "ok",
            "output": output.model_dump(mode="json"),
            "record": self._record(before),
        }

    def _record(self, before: CallOutcome | None) -> dict[str, Any] | None:
        """The record of the call just made, or ``None`` if nothing was logged."""
        return None if self.last is None or self.last is before else self.last.as_record()

    # -- internals ---------------------------------------------------------------
    def _spec(self, name: str) -> ToolSpec:
        if name not in self._specs:
            raise UnknownToolError(f"unknown tool {name!r}; the registry has {self.tools}")
        return self._specs[name]

    def _context(self) -> ToolContext:
        return ToolContext(
            configs=self.configs,
            meter=self._meter,
            models=self._models,
            state_space_models=self._state_space,
            assay_server=self._assay_server,
            seed_domain=self.seed,
        )

    def _elapsed_min(self) -> float:
        return (self._clock() - self._opened) / 60.0

    def _refusal(self, spec: ToolSpec, inp: ToolInput, context: ToolContext) -> str | None:
        """Why the call would exceed the budget, or ``None`` if it may run."""
        elapsed = self._elapsed_min()
        if elapsed >= self.budget.wall_clock_min:
            return (
                f"wall-clock allowance of {self.budget.wall_clock_min:g} min spent "
                f"({elapsed:.2f} min elapsed)"
            )
        bound = int(spec.cost(inp, context))
        if bound > self._meter.remaining:
            return (
                f"call would make up to {bound} simulator evaluations, "
                f"{self._meter.remaining} of {self.budget.simulator_evals} remain"
            )
        if spec.assay_cost is not None:
            price = int(spec.assay_cost(inp, context))
            left = self.budget.assay_units - self._assay_units_used
            if price > left:
                return f"assay costs {price} units, {left} of {self.budget.assay_units} remain"
        return None

    def _injected(self, name: str) -> bool:
        """Whether the Level-8 directive fires on this call."""
        if name not in self._failures or self._specs[name].failure is None:
            return False
        probability, rng = self._failures[name]
        return bool(rng.uniform() < probability)

    def _log(
        self,
        name: str,
        version: str,
        args: Mapping[str, Any],
        started: float,
        outcome: Outcome,
        detail: str,
        n_evaluations: int,
        assay_units: int = 0,
    ) -> None:
        runtime = self._clock() - started
        self._n_calls += 1
        # the workflow experiences an injected failure as a tool that returned a bad
        # result, so its projection says `ok`: a visible `injected_failure` would be
        # the answer to the Level-8 row. The truth-side record below keeps it, which is
        # what lets §6.7 D tell a real tool error from the injected one. The same record
        # carries what the meter charged the call (evaluations, assay units): the
        # evaluator's cost counters of §6.7 C read it, never the workflow's self-report
        # (the evaluation session, 2026-09-22).
        visible_outcome: Outcome = "ok" if outcome == "injected_failure" else outcome
        if self._full is not None:
            self._full.append(
                name,
                version,
                args,
                runtime,
                outcome,
                detail,
                n_evaluations=int(n_evaluations),
                assay_units=int(assay_units),
            )
        seq: int | None = None
        if self._visible is not None:
            record = self._visible.append(name, version, args, runtime, visible_outcome, detail)
            seq, hashed = record.seq, record.args_hash
        else:
            hashed = args_hash(args)
        self.last = CallOutcome(
            name=name,
            outcome=outcome,
            detail=detail,
            n_evaluations=n_evaluations,
            seq=seq,
            args_hash=hashed,
            version=version,
            visible_outcome=visible_outcome,
        )
