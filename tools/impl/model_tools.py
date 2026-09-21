"""The model-facing tools: describe_model, simulate, feed_loads, and request_assay."""

from __future__ import annotations

import numpy as np

from tools.registry import ToolArgumentError, ToolContext
from tools.schemas import (
    DescribeModelInput,
    DescribeModelOutput,
    FeedLoadsInput,
    FeedLoadsOutput,
    RequestAssayInput,
    RequestAssayOutput,
    SimulateInput,
    SimulateOutput,
)

__all__ = [
    "assay_cost",
    "assay_units",
    "describe_cost",
    "feed_loads_cost",
    "run_assay",
    "run_describe",
    "run_feed_loads",
    "run_simulate",
    "simulate_cost",
]


def describe_cost(inp: DescribeModelInput, ctx: ToolContext) -> int:
    """No evaluation."""
    return 0


def run_describe(inp: DescribeModelInput, ctx: ToolContext) -> DescribeModelOutput:
    """A model's interface."""
    model = ctx.model(inp.model)
    return DescribeModelOutput(
        model=model.name,
        parameter_names=model.parameter_names,
        defaults=model.defaults,
        lower=model.lower,
        upper=model.upper,
        parameter_units=dict(model.parameter_units),
        output_names=model.output_names,
        output_units=dict(model.output_units),
        t=model.t,
        description=model.description,
    )


def simulate_cost(inp: SimulateInput, ctx: ToolContext) -> int:
    """One evaluation."""
    return 1


def run_simulate(inp: SimulateInput, ctx: ToolContext) -> SimulateOutput:
    """One charged evaluation of a model."""
    model = ctx.model(inp.model)
    theta = model.theta_from(inp.parameters)
    if np.any(theta < model.lower) or np.any(theta > model.upper):
        raise ToolArgumentError("parameters lie outside the model's bounds")
    options: dict[str, object] = {}
    if inp.initial_state is not None:
        options["initial_state"] = dict(inp.initial_state)
    if inp.biomass_scale is not None:
        options["biomass_scale"] = float(inp.biomass_scale)
    if inp.t_end is not None:
        options["t_end"] = float(inp.t_end)
    outputs = model.evaluate(theta, **options)
    t = model.t
    if inp.t_end is not None:
        keep = t <= inp.t_end + 1e-9
        t = t[keep]
        outputs = {k: v[keep] for k, v in outputs.items()}
    info = getattr(model, "last_status", None)
    success, message = (True, "") if info is None else info()
    return SimulateOutput(
        model=model.name,
        t=t,
        outputs=outputs,
        units=dict(model.output_units),
        success=success,
        message=message,
        n_evaluations=model.calls,
    )


def feed_loads_cost(inp: FeedLoadsInput, ctx: ToolContext) -> int:
    """No evaluation: the catalogue is arithmetic."""
    return 0


def run_feed_loads(inp: FeedLoadsInput, ctx: ToolContext) -> FeedLoadsOutput:
    """The declared loads of the operator's feed log (fitted ADM1 only)."""
    if inp.model not in ctx.models:
        raise ToolArgumentError(f"unknown model {inp.model!r}")
    model = ctx.models[inp.model]
    loads = getattr(model, "feed_loads", None)
    if loads is None:
        raise ToolArgumentError(f"model {inp.model!r} has no feed log to compute loads from")
    return loads()


def assay_cost(inp: RequestAssayInput, ctx: ToolContext) -> int:
    """No simulator evaluation."""
    return 0


def assay_units(inp: RequestAssayInput, ctx: ToolContext) -> int:
    """The assay's price in units."""
    catalogue = ctx.configs.assays
    if inp.assay not in catalogue.assays:
        raise ToolArgumentError(
            f"unknown assay {inp.assay!r}; the catalogue has {sorted(catalogue.assays)}"
        )
    return catalogue.assays[inp.assay].unit_cost


def run_assay(inp: RequestAssayInput, ctx: ToolContext) -> RequestAssayOutput:
    """Serve one requested assay through the privileged channel."""
    if ctx.assay_server is None:
        raise ToolArgumentError("this registry serves no run, so no assay can be requested")
    return ctx.assay_server.serve(inp.assay, float(inp.day))
