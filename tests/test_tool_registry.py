"""The registry core (proposal §6.2; CLAUDE.md rules 2-4, 6): what every call must do.

Driven with analytic models registered on the privileged side, so nothing here integrates
ADM1; the fitted model has its own file. Each claim is checked against something other
than the code that makes it:

1. **One interface** validates the arguments (a bad argument is an ``error`` in the log and
   a ``ToolArgumentError`` to the caller) and returns a typed output with units.
2. **Logging** (rule 3): one record per call, in the run's visible ``calls.jsonl``, in
   projection form (no timestamp, no runtime), *continuing* the sequence the harness
   wrote; the truth-side log carries both.
3. **Budgets** (rule 2): a call whose declared bound exceeds the remaining evaluations is
   refused before running; a call that overruns mid-way is stopped inside the model with
   its evaluations charged; the wall clock is enforced against an injectable clock; assay
   units are enforced; ``remaining()`` reports all three.
4. **The Level-8 directive**: ``bayes_mcmc`` returns non-converged chains (R-hat > 1.1,
   low ESS, ``converged=False``) without raising, the truth-side log says
   ``injected_failure`` and the visible log says ``ok``; with probability 0 it never fires;
   with a directive for another tool ``bayes_mcmc`` is untouched.
5. **Determinism** (rule 4): the same seed gives bit-equal output; another seed does not.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from state.provenance import CallLog, read_calls
from tools import (
    AnalyticModel,
    Budget,
    BudgetExceededError,
    ToolArgumentError,
    ToolFailure,
    UnknownToolError,
    make_registry,
)
from tools.schemas import ObservedSeries

T = np.linspace(0.0, 10.0, 11)


def linear_model() -> AnalyticModel:
    """``y = a t + b`` on an 11-point grid: two identifiable parameters."""
    return AnalyticModel(
        name="linear",
        parameter_names=("a", "b"),
        defaults=np.array([1.0, 0.0]),
        lower=np.array([-5.0, -5.0]),
        upper=np.array([5.0, 5.0]),
        function=lambda th: {"y": th[0] * T + th[1]},
        output_names=("y",),
        t=T,
        parameter_units={"a": "1/d", "b": "-"},
        output_units={"y": "-"},
    )


def linear_data(a: float = 2.0, b: float = 1.0, seed: int = 0, sd: float = 0.1) -> ObservedSeries:
    rng = np.random.default_rng(seed)
    return ObservedSeries(
        output="y", t=T, value=a * T + b + sd * rng.standard_normal(T.size), sd=sd
    )


class Clock:
    """A clock the tests advance by hand, seconds."""

    def __init__(self) -> None:
        """Start at an arbitrary instant."""
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


DEFAULT_BUDGET = Budget(1000, 60.0, 4)


def registry(tmp_path, *, budget=DEFAULT_BUDGET, clock=None, failures=(), seed=7):
    run_dir = tmp_path / "runs" / "run_x"
    truth_dir = tmp_path / "truth_store" / "run_x"
    reg = make_registry(
        budget=budget,
        seed=seed,
        run_dir=run_dir,
        truth_log_dir=truth_dir,
        tool_failures=failures,
        models={"linear": linear_model()},
        clock=clock or Clock(),
    )
    return reg, run_dir, truth_dir


# ------------------------------------------------------------------ 1. one interface


def test_a_call_validates_returns_a_typed_output_with_units_and_is_logged(tmp_path):
    reg, run_dir, _ = registry(tmp_path)
    out = reg.call("simulate", model="linear", parameters={"a": 2.0})
    assert out.units == {"y": "-"}
    np.testing.assert_allclose(out.outputs["y"], 2.0 * T)
    assert out.n_evaluations == 1
    with pytest.raises(ToolArgumentError):
        reg.call("simulate", model="linear", parameters={"a": 2.0}, bogus=1)
    with pytest.raises(ToolArgumentError):
        reg.call("simulate", model="linear", parameters={"a": 99.0})  # outside the bounds
    with pytest.raises(ToolArgumentError):
        reg.call("simulate", model="no_such_model")
    with pytest.raises(UnknownToolError):
        reg.call("no_such_tool")
    visible = read_calls(run_dir)
    assert [r.outcome for r in visible] == ["ok", "ok", "error", "error", "error"]
    assert [r.name for r in visible] == ["registry.open", *["simulate"] * 4]
    assert reg.remaining().n_calls == 4


def test_every_tool_of_the_proposal_table_is_registered_with_a_version(tmp_path):
    reg, _, _ = registry(tmp_path)
    expected = {
        "data_qc", "mass_balance", "gsa_morris", "gsa_sobol", "profile_likelihood",
        "fisher_info", "fit_lsq", "fit_de", "fit_cmaes", "bayes_mcmc", "filter_enkf",
        "filter_mhe", "residual_diag", "voi_assay", "validate", "request_assay",
        "simulate", "describe_model", "feed_loads",
    }  # fmt: skip
    assert set(reg.tools) == expected
    for name in expected:
        desc = reg.describe(name)
        assert desc["version"] == "1.0"
        assert "properties" in desc["input_schema"]


# ------------------------------------------------------------------ 2. logging


def test_the_registry_continues_the_sequence_the_harness_wrote(tmp_path):
    run_dir = tmp_path / "runs" / "run_x"
    harness = CallLog(run_dir, fresh=True, projection=True)
    harness.append("sim.generate_influent", "1.0", {"plant": "C"}, 0.5, "ok")
    harness.append("sim.observe", "1.0", {"tier": "A"}, 0.1, "ok")
    reg, _, truth_dir = registry(tmp_path)
    reg.call("describe_model", model="linear")
    reg.call("simulate", model="linear")
    records = read_calls(run_dir)
    assert [r.seq for r in records] == [0, 1, 2, 3, 4]
    assert [r.name for r in records] == [
        "sim.generate_influent", "sim.observe", "registry.open", "describe_model", "simulate"
    ]  # fmt: skip
    for r in records:
        assert r.t_utc is None and r.runtime_s is None  # the projection (findings F1, F3)
        assert len(r.args_hash) == 16
    full = read_calls(truth_dir)
    assert [r.name for r in full] == ["registry.open", "describe_model", "simulate"]
    for r in full:
        assert r.t_utc is not None and r.runtime_s is not None and r.runtime_s >= 0.0
    # the clock start the evaluator reconstructs the wall-clock allowance from
    assert full[0].detail.startswith("clock start") and full[0].runtime_s == 0.0
    assert full[0].version == reg.configs.registry.registry_version
    # the raw lines of the projection carry no timestamp key at all
    for line in run_dir.joinpath("calls.jsonl").read_text().splitlines():
        assert "t_utc" not in json.loads(line)


# ------------------------------------------------------------------ 3. budgets


def test_a_call_that_would_exceed_the_evaluations_is_refused_before_running(tmp_path):
    reg, run_dir, _ = registry(tmp_path, budget=Budget(10, 60.0, 0))
    # Morris: r (k + 1) = 4 x 3 = 12 > 10
    with pytest.raises(BudgetExceededError):
        reg.call(
            "gsa_morris", model="linear", parameters=("a", "b"), outputs=("y",),
            n_trajectories=4, seed=1,
        )  # fmt: skip
    assert reg.remaining().simulator_evals == 10  # nothing was spent
    assert read_calls(run_dir)[-1].outcome == "budget_exceeded"
    # r = 3: 9 evaluations, fits
    out = reg.call(
        "gsa_morris", model="linear", parameters=("a", "b"), outputs=("y",),
        n_trajectories=3, seed=1,
    )  # fmt: skip
    assert out.n_evaluations == 9
    assert reg.remaining().simulator_evals == 1


def test_a_tool_that_overruns_is_stopped_inside_the_model_and_charged(tmp_path):
    """A model that lies about its cost cannot spend past the limit: the meter stops it."""
    reg, run_dir, truth_dir = registry(tmp_path, budget=Budget(5, 60.0, 0))
    from tools.registry import ToolSpec
    from tools.schemas import SimulateInput, SimulateOutput

    def greedy(inp, ctx):
        model = ctx.model(inp.model)
        for _ in range(100):
            model.evaluate(model.defaults)
        raise AssertionError("unreachable")

    reg._specs["greedy"] = ToolSpec(
        name="greedy", input_model=SimulateInput, output_model=SimulateOutput, run=greedy,
        cost=lambda inp, ctx: 1,
    )  # fmt: skip
    with pytest.raises(BudgetExceededError):
        reg.call("greedy", model="linear")
    assert reg.remaining().simulator_evals == 0
    assert read_calls(run_dir)[-1].outcome == "budget_exceeded"
    assert "5 of 5" in read_calls(truth_dir)[-1].detail


def test_the_wall_clock_is_enforced_since_the_registry_opened(tmp_path):
    clock = Clock()
    reg, run_dir, _ = registry(tmp_path, budget=Budget(100, 2.0, 0), clock=clock)
    reg.call("simulate", model="linear")
    assert reg.remaining().wall_clock_min == pytest.approx(2.0)
    clock.now += 90.0
    assert reg.remaining().wall_clock_min == pytest.approx(0.5)
    reg.call("simulate", model="linear")
    clock.now += 31.0
    with pytest.raises(BudgetExceededError, match="wall-clock"):
        reg.call("simulate", model="linear")
    assert reg.remaining().wall_clock_min == 0.0
    assert read_calls(run_dir)[-1].outcome == "budget_exceeded"


def test_assay_units_are_enforced_and_a_registry_without_a_run_serves_no_assay(tmp_path):
    reg, _, _ = registry(tmp_path, budget=Budget(100, 60.0, 1))
    # cod_total costs 2 units; only 1 is available: refused as budget_exceeded
    with pytest.raises(BudgetExceededError, match="assay"):
        reg.call("request_assay", assay="cod_total", day=10.0)
    # alkalinity costs 1 unit but this registry has no truth-side channel: an error
    with pytest.raises(ToolArgumentError):
        reg.call("request_assay", assay="alkalinity", day=10.0)
    assert reg.remaining().assay_units == 1
    with pytest.raises(ToolArgumentError, match="unknown assay"):
        reg.call("request_assay", assay="mass_spec", day=10.0)


# ------------------------------------------------------------------ 4. the Level-8 directive


def mcmc_args(**over: object):
    args = {
        "model": "linear", "data": (linear_data(),), "parameters": ("a", "b"),
        "start": {"a": 2.0, "b": 1.0}, "n_walkers": 8, "n_steps": 60, "seed": 3,
    }  # fmt: skip
    args.update(over)
    return args


def test_the_tool_failure_directive_returns_non_converged_chains_and_is_logged_truth_side_only(
    tmp_path,
):
    reg, run_dir, truth_dir = registry(tmp_path, failures=[ToolFailure("bayes_mcmc", 1.0)])
    out = reg.call("bayes_mcmc", **mcmc_args())
    assert not out.converged
    assert np.all(out.rhat > 1.1)
    assert np.all(out.ess < reg.configs.mcmc.ess_floor)
    assert "not converged" in out.warning
    assert out.n_evaluations == 0
    assert reg.remaining().simulator_evals == 1000  # a failed sampler spends nothing
    assert read_calls(truth_dir)[-1].outcome == "injected_failure"
    assert read_calls(run_dir)[-1].outcome == "ok"
    blob = run_dir.joinpath("calls.jsonl").read_text()
    assert "injected" not in blob
    # every call fails at probability 1.0
    again = reg.call("bayes_mcmc", **mcmc_args(seed=4))
    assert not again.converged


def test_a_zero_probability_directive_never_fires_and_another_tools_directive_is_ignored(tmp_path):
    reg, _, truth_dir = registry(
        tmp_path, budget=Budget(5000, 60.0, 0), failures=[("bayes_mcmc", 0.0), ("fit_lsq", 1.0)]
    )
    out = reg.call("bayes_mcmc", **mcmc_args())
    assert out.n_evaluations > 0
    assert read_calls(truth_dir)[-1].outcome == "ok"
    # fit_lsq has no failure payload in the catalogue, so a directive naming it is inert
    fit = reg.call(
        "fit_lsq", model="linear", data=(linear_data(),), parameters=("a", "b"), seed=1, n_starts=2
    )
    assert read_calls(truth_dir)[-1].outcome == "ok"
    assert fit.chi2 < 50.0


def test_a_fractional_directive_fires_at_its_rate_from_a_keyed_stream(tmp_path):
    reg, _, truth_dir = registry(tmp_path, failures=[("bayes_mcmc", 0.5)])
    outcomes = []
    for i in range(20):
        reg.call("bayes_mcmc", **mcmc_args(seed=i, n_steps=10))
        outcomes.append(read_calls(truth_dir)[-1].outcome)
    n_fail = outcomes.count("injected_failure")
    assert 4 <= n_fail <= 16
    # the same registry seed reproduces the same firing pattern
    reg2, _, truth2 = registry(tmp_path / "again", failures=[("bayes_mcmc", 0.5)])
    for i in range(20):
        reg2.call("bayes_mcmc", **mcmc_args(seed=i, n_steps=10))
    assert [r.outcome for r in read_calls(truth2) if r.name == "bayes_mcmc"] == outcomes


# ------------------------------------------------------------------ 5. determinism


@pytest.mark.parametrize(
    "tool, args",
    [
        ("gsa_morris", {"parameters": ("a", "b"), "outputs": ("y",), "n_trajectories": 3}),
        ("gsa_sobol", {"parameters": ("a", "b"), "outputs": ("y",), "n_samples": 8}),
        ("fit_lsq", {"data": (linear_data(),), "parameters": ("a", "b"), "n_starts": 3}),
        (
            "fit_de",
            {
                "data": (linear_data(),),
                "parameters": ("a", "b"),
                "popsize": 4,
                "max_generations": 5,
            },
        ),
        (
            "bayes_mcmc",
            {"data": (linear_data(),), "parameters": ("a", "b"), "n_walkers": 6, "n_steps": 20},
        ),
    ],
)  # fmt: skip
def test_the_same_seed_gives_bit_equal_output_and_another_seed_does_not(tmp_path, tool, args):
    reg, _, _ = registry(tmp_path, budget=Budget(100000, 60.0, 0))
    first = reg.call(tool, model="linear", seed=11, **args).model_dump(mode="json")
    second = reg.call(tool, model="linear", seed=11, **args).model_dump(mode="json")
    assert first == second
    third = reg.call(tool, model="linear", seed=12, **args).model_dump(mode="json")
    assert third != first


def test_a_seed_is_required_on_every_stochastic_tool(tmp_path):
    reg, _, _ = registry(tmp_path)
    with pytest.raises(ToolArgumentError, match="seed"):
        reg.call("gsa_morris", model="linear", parameters=("a",), outputs=("y",))


def test_a_workflow_may_ask_for_less_than_the_ceiling_but_never_more(tmp_path):
    reg, _, _ = registry(tmp_path, budget=Budget(10**7, 60.0, 0))
    ceiling = reg.configs.gsa.morris.n_trajectories
    with pytest.raises(ToolArgumentError, match="ceiling"):
        reg.call(
            "gsa_morris", model="linear", parameters=("a",), outputs=("y",),
            n_trajectories=ceiling + 1, seed=1,
        )  # fmt: skip


def test_call_json_is_the_transport_envelope(tmp_path):
    reg, _, _ = registry(tmp_path, budget=Budget(1, 60.0, 0))
    ok = reg.call_json("simulate", {"model": "linear", "parameters": {"a": 1.5}})
    assert ok["outcome"] == "ok"
    assert ok["output"]["outputs"]["y"][-1] == pytest.approx(15.0)
    refused = reg.call_json("simulate", {"model": "linear"})
    assert refused["outcome"] == "budget_exceeded"
    bad = reg.call_json("simulate", {"model": "linear", "nope": 1})
    assert bad["outcome"] == "error" and bad["kind"] == "ToolArgumentError"
