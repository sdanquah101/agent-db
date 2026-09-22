"""The registry's meter is the source of a run's cost (follow-up (d) of milestone 5).

1. The truth-side log carries what the meter charged each call (evaluations, assay
   units); the visible projection carries neither.
2. ``summary.json``'s cost fields come from the meter on the privileged side: a task
   state that misreports its budget does not change them, and the misreport is kept
   beside them.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from sim.run.layout import RunPaths
from state.provenance import read_calls
from tests.eval_support import minimal_state
from tests.test_tool_registry import linear_data, linear_model
from tools import Budget, BudgetExceededError, make_registry
from tools.runner import _summarise
from tools.server import OUTPUTS_DIR


def _registry(tmp_path):
    run_dir = tmp_path / "runs" / "run_meter"
    truth_dir = tmp_path / "truth_store" / "run_meter"
    reg = make_registry(
        budget=Budget(50, 60.0, 4),
        seed=7,
        run_dir=run_dir,
        truth_log_dir=truth_dir,
        models={"linear": linear_model()},
    )
    return reg, run_dir, truth_dir


def test_the_truth_side_log_carries_the_meter_and_the_projection_does_not(tmp_path):
    reg, run_dir, truth_dir = _registry(tmp_path)
    reg.call("simulate", model="linear", parameters={"a": 2.0})
    reg.call(
        "fit_lsq", model="linear", data=[linear_data()], parameters=["a", "b"], n_starts=1,
        max_nfev_per_start=20, seed=1,
    )  # fmt: skip
    with pytest.raises(BudgetExceededError):  # bound 100 x 3 > 50: refused, nothing runs
        reg.call(
            "gsa_morris", model="linear", parameters=["a", "b"], outputs=["y"],
            n_trajectories=100, seed=2,
        )  # fmt: skip
    full = read_calls(truth_dir)
    visible = read_calls(run_dir)
    assert [r.name for r in full] == ["registry.open", "simulate", "fit_lsq", "gsa_morris"]
    assert full[0].n_evaluations == 0 and full[1].n_evaluations == 1
    assert full[2].n_evaluations is not None and full[2].n_evaluations >= 1
    assert full[3].outcome == "budget_exceeded" and full[3].n_evaluations == 0
    assert all(r.assay_units == 0 for r in full)
    assert sum(r.n_evaluations or 0 for r in full) == reg.evaluations_used
    assert reg.evaluations_used == 50 - reg.remaining().simulator_evals
    for record in visible:
        assert record.n_evaluations is None and record.assay_units is None
        assert "n_evaluations" not in record.to_json()
    assert all("n_evaluations" in json.loads(r.to_json()) for r in full)


def test_summary_cost_fields_come_from_the_meter_not_the_state(tmp_path):
    reg, run_dir, _ = _registry(tmp_path)
    for a in (1.0, 2.0, 3.0):
        reg.call("simulate", model="linear", parameters={"a": a})
    charged = reg.evaluations_used
    assert charged == 3
    paths = RunPaths.for_run("run_meter", tmp_path / "runs", tmp_path / "truth_store")
    out_dir = run_dir / OUTPUTS_DIR / "p0"
    out_dir.mkdir(parents=True)
    lying = minimal_state(
        "run_meter",
        budget={
            "simulator_evals": 49, "simulator_evals_total": 50, "simulator_evals_used": 1,
            "assay_units": 4, "assay_units_total": 4, "assay_units_used": 0, "n_calls": 1,
        },
    )  # fmt: skip
    (out_dir / "state.json").write_text(json.dumps(lying))
    summary = _summarise(paths, "p0", 12.5, 0, "", "", registry=reg)
    assert summary.state_valid and summary.completed
    assert summary.cost_source == "registry_meter"
    assert summary.simulator_evals_used == 3 and summary.simulator_evals_total == 50
    assert summary.n_calls == 3 and summary.assay_units_used == 0
    assert summary.self_reported_simulator_evals_used == 1
    assert summary.self_reported_n_calls == 1
    assert summary.tokens_used is None
    # the same meter, the state gone entirely: the cost is still the meter's
    (out_dir / "state.json").unlink()
    absent = _summarise(paths, "p0", 12.5, 0, "", "", registry=reg)
    assert not absent.state_valid and absent.simulator_evals_used == 3
    assert absent.error == "the workflow wrote no state"
    assert np.isclose(absent.wall_s, 12.5)
