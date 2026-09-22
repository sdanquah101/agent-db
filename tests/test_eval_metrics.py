"""Every metric of §6.7 A-D on constructed truth/state pairs: a positive and a negative case each.

The pairs are written by ``tests/eval_support.py`` exactly as the harness, the registry
and the runner write them, so the scorer reads records here the way it reads a real run.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from eval.aggregate import aggregate, bootstrap_mean_interval
from eval.attribution import prior_interval
from eval.config import load_eval_config
from eval.records import load_records, selected_runs
from eval.score import Scorer
from eval.tables import write_tables
from tests.conftest import REPO_ROOT
from tests.eval_support import (
    DEFAULT_TRUTH,
    actions_for,
    build_run,
    evidence,
    minimal_state,
    parameter,
    truth_segment,
)
from tools.config import load_fitted_model

CFG = load_eval_config()
MODEL = load_fitted_model()


@pytest.fixture(scope="module")
def scorer() -> Scorer:
    return Scorer(config=CFG, model=MODEL, defaults=dict(DEFAULT_TRUTH))


def _score(scorer: Scorer, root: Path, run_id: str = "run_000000000001", workflow: str = "p0"):
    records = load_records(
        run_id, workflow, runs_root=root / "runs", truth_store=root / "truth_store"
    )
    return scorer.score(records), records


def _state_with_calls(root: Path, run_id: str, calls: list[dict], **overrides: object):
    """Build the run twice: first for the log, then with actions naming the log's lines."""
    build_run(root, run_id, calls=calls, index=False)
    actions = actions_for(calls, root / "runs" / run_id)
    return minimal_state(run_id, actions=actions, **overrides)


# ------------------------------------------------------------------ the configuration


def test_the_configuration_declares_the_frozen_window_p0_declares():
    p0 = yaml.safe_load((REPO_ROOT / "configs" / "workflows" / "p0.yaml").read_text())
    assert CFG.windows.holdout_fraction == p0["windows"]["holdout_fraction"]
    assert CFG.prediction.recovery_levels == (0, 1, 2, 3, 4, 5)
    assert 6 not in CFG.prediction.recovery_levels
    assert CFG.attribution.prior_interval_mass == 0.9
    assert CFG.prediction.interval_score_alpha == 0.1
    assert isinstance(CFG.aggregate.bootstrap.seed, int)


def test_the_prior_interval_is_the_central_mass_of_the_declared_box():
    lo, hi = prior_interval(0.25, 4.0, 0.9)
    assert lo == pytest.approx(0.25 + 0.05 * 3.75) and hi == pytest.approx(4.0 - 0.05 * 3.75)
    assert MODEL.parameters["k_dis"].group == "kinetics"
    assert MODEL.parameters["Y_ac"].group == "stoichiometry"


# ------------------------------------------------------------------ family B


def test_attribution_exact_and_partial(scorer, tmp_path):
    root = tmp_path / "hit"
    build_run(root, truth_label=("sensor",), level=2, state=minimal_state(
        "run_000000000001",
        final={"label": "sensor", "secondary_labels": []},
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["attribution_exact"] is True and row["attribution_partial"] == 1.0
    assert row["primary_in_truth"] is True and row["truth_label"] == "sensor"

    root = tmp_path / "miss"
    build_run(root, truth_label=("sensor",), level=2, state=minimal_state(
        "run_000000000001", final={"label": "none", "secondary_labels": []}
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["attribution_exact"] is False and row["attribution_partial"] == 0.0

    root = tmp_path / "partial"  # a compound truth, half named
    build_run(root, truth_label=("sensor", "influent"), level=7, state=minimal_state(
        "run_000000000001", final={"label": "sensor", "secondary_labels": []}
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["attribution_exact"] is False and row["attribution_partial"] == 0.5
    assert row["primary_in_truth"] is True

    root = tmp_path / "compound"  # both named, in either order, is exact
    build_run(root, truth_label=("sensor", "influent"), level=7, state=minimal_state(
        "run_000000000001", final={"label": "influent", "secondary_labels": ["sensor"]}
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["attribution_exact"] is True and row["final_label_set"] == "influent+sensor"

    root = tmp_path / "nostate"  # a launched run with no state: a MISS, in the denominator
    build_run(root, truth_label=("sensor",), level=2, write_state=False)
    row, _ = _score(scorer, root)
    assert row["completed"] is False and row["launched"] is True
    assert row["attribution_exact"] is False and row["attribution_partial"] == 0.0
    assert row["primary_in_truth"] is False
    assert row["false_kinetic_drift"] is None and row["abstention_correct"] is None

    root = tmp_path / "unlaunched"  # never launched: no verdict at all
    build_run(root, truth_label=("sensor",), level=2, write_state=False, write_summary=False)
    row, _ = _score(scorer, root)
    assert row["launched"] is False and row["attribution_exact"] is None


def test_false_kinetic_drift_reads_the_declared_prior_interval(scorer, tmp_path):
    _, k_hi = prior_interval(MODEL.parameters["k_dis"].lower, MODEL.parameters["k_dis"].upper, 0.9)
    # positive: a sensor truth, k_dis pushed past the prior's 90 % interval
    root = tmp_path / "drift"
    build_run(root, truth_label=("sensor",), level=2, state=minimal_state(
        "run_000000000001",
        final={"parameters": {"k_dis": parameter(k_hi + 0.01, k_hi - 0.5, 4.0)}},
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["drift_applicable"] is True and row["false_kinetic_drift"] is True
    assert row["kinetic_parameters_outside_prior"] == "k_dis"

    # negative: the same truth, the estimate inside the interval
    root = tmp_path / "inside"
    build_run(root, truth_label=("sensor",), level=2, state=minimal_state(
        "run_000000000001",
        final={"parameters": {"k_dis": parameter(1.0, 0.8, 1.2)}},
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["false_kinetic_drift"] is False and row["kinetic_parameters_reported"] == 1

    # a stoichiometric parameter at its bound is not a kinetic drift
    root = tmp_path / "yield"
    build_run(root, truth_label=("sensor",), level=2, state=minimal_state(
        "run_000000000001",
        final={"parameters": {"Y_ac": parameter(1.5, 1.0, 1.5, at_bound=True)}},
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["false_kinetic_drift"] is False and row["kinetic_parameters_reported"] == 0

    # not applicable on a parameter truth: the metric abstains
    root = tmp_path / "parameter"
    build_run(root, truth_label=("parameter",), level=5, state=minimal_state(
        "run_000000000001",
        final={"parameters": {"k_dis": parameter(k_hi + 0.01, None, None)}},
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["drift_applicable"] is False and row["false_kinetic_drift"] is None
    assert row["kinetic_parameters_outside_prior"] == "k_dis"


def test_false_kinetic_update_reads_the_answer_key(scorer, tmp_path):
    root = tmp_path / "offered"
    build_run(root, truth_label=("structural",), level=6, state=minimal_state(
        "run_000000000001", classification={"kinetic_update": True}
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["false_kinetic_update"] is True
    root = tmp_path / "allowed"
    build_run(root, truth_label=("parameter",), level=5, state=minimal_state(
        "run_000000000001", classification={"kinetic_update": True}
    ))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["false_kinetic_update"] is None and row["kinetic_update_offered"] is True


def test_correct_abstention_is_binary_and_from_the_structured_state(scorer, tmp_path):
    key = {"abstain_on": ["alkalinity_budget", "inorganic_carbon_balance"]}
    root = tmp_path / "abstains"
    state = minimal_state(
        "run_000000000001",
        abstentions=["alkalinity_budget", "inorganic_carbon_balance", "posterior_intervals"],
        final={"abstentions": ["alkalinity_budget", "inorganic_carbon_balance"]},
        annotations=["free text saying nothing is abstained"],
    )
    build_run(root, truth_label=("structural",), level=6, correct_conclusion=key, state=state)
    row, _ = _score(scorer, root)
    assert row["abstention_applicable"] is True and row["abstention_correct"] is True
    assert row["abstention_fraction"] == 1.0

    root = tmp_path / "half"  # one of two declined: not correct, half credit shown
    state = minimal_state(
        "run_000000000001",
        abstentions=["alkalinity_budget"],
        final={"abstentions": ["alkalinity_budget"]},
        annotations=["abstains on the inorganic carbon balance"],  # prose does not count
    )
    build_run(root, truth_label=("structural",), level=6, correct_conclusion=key, state=state)
    row, _ = _score(scorer, root)
    assert row["abstention_correct"] is False and row["abstention_fraction"] == 0.5

    root = tmp_path / "none"  # a clean scenario declares nothing: not applicable
    build_run(root, truth_label=("none",), level=0)
    row, _ = _score(scorer, root)
    assert row["abstention_applicable"] is False and row["abstention_correct"] is None

    root = tmp_path / "level8"  # abstain_on outside a structural/compound truth: scored, flagged
    state = minimal_state("run_000000000001", final={"abstentions": ["posterior_intervals"]})
    key8 = {"abstain_on": ["posterior_intervals"]}
    build_run(root, truth_label=("sensor",), level=8, correct_conclusion=key8, state=state)
    row, _ = _score(scorer, root)
    assert row["abstention_applicable"] is False and row["abstention_correct"] is True


def test_unsupported_claims_follow_the_trail_to_the_log(scorer, tmp_path):
    calls = [
        {"name": "simulate", "args": {"p": 1}, "n_evaluations": 1},
        {"name": "residual_diag", "args": {"o": "pH"}},
        {"name": "mass_balance", "args": {"w": 30.0}},
        {"name": "feed_loads", "args": {}},
    ]
    root = tmp_path / "trail"
    good = evidence("R1b", "sensor", {"bias_z": 5.0}, [1])  # residual_diag returns bias_z
    empty = evidence("R4", "parameter", {"pH": 60.0}, [])  # names no call
    wrong = evidence("R1b", "sensor", {"bias_z": 5.0}, [3])  # feed_loads returns no bias
    balance = evidence("R2", "influent", {"n_inadmissible": 3}, [2])
    dangling = evidence("R2", "influent", {"n_inadmissible": 3}, [7])  # no such action
    state = _state_with_calls(root, "run_000000000001", calls, classification={
        "evidence": [good, empty, wrong, balance, dangling]
    })  # fmt: skip
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["claims"] == 5 and row["claims_unsupported"] == 3
    assert row["unsupported_claim_rate"] == pytest.approx(0.6)

    # a state whose action misnames the log line (hash tampered) is unsupported too
    tampered = json.loads(json.dumps(state))
    tampered["actions"][1]["args_hash"] = "0" * 16
    root2 = tmp_path / "tampered"
    build_run(root2, state=tampered, calls=calls)
    row, _ = _score(scorer, root2)
    assert row["claims_unsupported"] == 4

    # a claim whose rule and value keys are all unregistered in claim_sources cannot be
    # checked against "returned the claimed quantity": unsupported by the declared policy
    # (blocker B2 of the PR #19 review), even though it cites a logged ok call
    root4 = tmp_path / "unmapped"
    unmapped = evidence("R9", "sensor", {"made_up": 1.0}, [3])
    state4 = _state_with_calls(
        root4, "run_000000000001", calls, classification={"evidence": [unmapped, good]}
    )
    build_run(root4, state=state4, calls=calls)
    row, _ = _score(scorer, root4)
    assert row["claims"] == 2 and row["claims_unsupported"] == 1
    assert CFG.attribution.unmapped_claim == "unsupported"
    lenient_attribution = CFG.attribution.model_copy(update={"unmapped_claim": "supported"})
    lenient = Scorer(
        config=CFG.model_copy(update={"attribution": lenient_attribution}),
        model=MODEL,
        defaults=dict(DEFAULT_TRUTH),
    )
    row, _ = _score(lenient, root4)
    assert row["claims_unsupported"] == 0  # the other policy, declared, not the default

    # no evidence at all: the rate abstains rather than reading as perfect
    root3 = tmp_path / "silent"
    build_run(root3)
    row, _ = _score(scorer, root3)
    assert row["claims"] == 0 and row["unsupported_claim_rate"] is None


# ------------------------------------------------------------------ family A


def _validation(window, calls, metrics=None, ensemble=True):
    return {
        "holdout": list(window),
        "ensemble": ensemble,
        "ensemble_size": 8 if ensemble else 0,
        "metrics": metrics
        or {
            "q_gas_stp_dry": {
                "n": 10.0,
                "mae": 1.0,
                "rmse": 1.5,
                "nrmse": 0.3,
                "bias": -0.5,
                "coverage_50": 0.4,
                "coverage_90": 0.8,
                "interval_score_90": 12.0,
                "crps": 0.7,
            },
            "pH": {
                "n": 10.0,
                "mae": 0.1,
                "rmse": 0.12,
                "nrmse": 1.1,
                "bias": 0.05,
                "coverage_50": None,
                "coverage_90": None,
                "interval_score_90": None,
                "crps": None,
            },
        },
        "constraint_violations": 0,
        "calls": list(calls),
    }


def test_forecast_metrics_need_a_logged_validate_call_on_the_frozen_window(scorer, tmp_path):
    calls = [{"name": "simulate", "args": {}, "n_evaluations": 1}, {"name": "validate", "args": {}}]
    root = tmp_path / "verified"
    state = _state_with_calls(root, "run_000000000001", calls,
                              validation=_validation((150.0, 200.0), [1]))  # fmt: skip
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["forecast_verified"] is True and row["forecast_reason"] == ""
    assert row["q_gas_stp_dry_mae"] == 1.0 and row["q_gas_stp_dry_bias"] == -0.5
    assert (
        row["q_gas_stp_dry_coverage_90"] == 0.8 and row["q_gas_stp_dry_interval_score_90"] == 12.0
    )
    assert row["q_gas_stp_dry_crps"] == 0.7 and row["q_gas_stp_dry_crps_posterior"] is None
    assert row["pH_mae"] == 0.1 and row["pH_coverage_50"] is None
    assert row["tan_mae"] is None  # not observed at this tier: abstained, not zero
    assert row["interval_source"] == "fisher" and row["ensemble"] is True

    root = tmp_path / "posterior"  # a posterior predictive fills the posterior column
    state = _state_with_calls(root, "run_000000000001", calls,
                              validation=_validation((150.0, 200.0), [1]),
                              final={"interval_method": "posterior"})  # fmt: skip
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["q_gas_stp_dry_crps_posterior"] == 0.7

    root = tmp_path / "window"  # the wrong window: not the frozen forecast
    state = _state_with_calls(root, "run_000000000001", calls,
                              validation=_validation((100.0, 200.0), [1]))  # fmt: skip
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["forecast_verified"] is False and "frozen" in row["forecast_reason"]
    assert row["q_gas_stp_dry_mae"] is None

    root = tmp_path / "wrongtool"  # the call named is a simulate, not a validate
    state = _state_with_calls(root, "run_000000000001", calls,
                              validation=_validation((150.0, 200.0), [0]))  # fmt: skip
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["forecast_verified"] is False and "validate" in row["forecast_reason"]

    root = tmp_path / "point"  # a point prediction: errors yes, intervals abstained
    point = _validation((150.0, 200.0), [1], ensemble=False)
    state = _state_with_calls(root, "run_000000000001", calls, validation=point)
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["forecast_verified"] is True and row["q_gas_stp_dry_rmse"] == 1.5
    assert row["q_gas_stp_dry_coverage_90"] is None and row["q_gas_stp_dry_crps"] is None


def test_balance_error_needs_a_logged_mass_balance_call(scorer, tmp_path):
    calls = [{"name": "mass_balance", "args": {"w": 30.0}}]
    balance = {"cod_closure_mean": -0.08, "n_cod_inadmissible": 2, "charge_drift": 0.31,
               "charge_consistent": False, "admissible": True}  # fmt: skip
    root = tmp_path / "balanced"
    state = _state_with_calls(root, "run_000000000001", calls, mass_balance=balance)
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["balance_verified"] is True and row["cod_balance_error"] == pytest.approx(0.08)
    assert row["n_cod_inadmissible"] == 2 and row["charge_consistent"] is False

    root = tmp_path / "unlogged"
    build_run(root, state=minimal_state("run_000000000001", mass_balance=balance))
    row, _ = _score(scorer, root)
    assert row["balance_verified"] is False and row["cod_balance_error"] is None


def test_parameter_recovery_is_scored_on_levels_zero_to_five_only(scorer, tmp_path):
    estimates = {
        "k_dis": parameter(1.2, 0.9, 1.5),  # truth 1.0: covered
        "k_m_ac": parameter(0.5, 0.4, 0.6),  # truth 1.0: not covered
    }
    root = tmp_path / "level0"
    build_run(
        root, level=0, state=minimal_state("run_000000000001", final={"parameters": estimates})
    )
    row, _ = _score(scorer, root)
    assert row["recovery_scored"] is True and row["recovery_n"] == 2
    assert row["recovery_mean_abs_error"] == pytest.approx(0.35)
    assert row["recovery_mean_rel_error"] == pytest.approx(0.35)
    assert row["recovery_coverage"] == 0.5 and row["recovery_at_bound"] == 0.0
    assert "k_dis:1.200/1.000/in" in row["recovery_detail"]

    # a Level-5 truth is scored against its last segment (the regime the record ends in)
    root = tmp_path / "level5"
    build_run(root, level=5, truth_label=("parameter",),
              segments=[truth_segment(), truth_segment({"k_dis": 1.2})],
              state=minimal_state("run_000000000001", final={"parameters": estimates}))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["recovery_scored"] is True
    assert "k_dis:1.200/1.200/in" in row["recovery_detail"]

    # the negative control: the SAME estimates on a Level-6 structural cell are not scored
    root = tmp_path / "level6"
    same = minimal_state("run_000000000001", final={"parameters": estimates})
    build_run(root, level=6, truth_label=("structural",), state=same)
    row, _ = _score(scorer, root)
    assert row["recovery_scored"] is False
    assert all(
        row[k] is None
        for k in ("recovery_n", "recovery_mean_abs_error", "recovery_coverage", "recovery_detail")
    )
    for level in (7, 8):
        root = tmp_path / f"level{level}"
        build_run(root, level=level, truth_label=("sensor",), state=same)
        assert _score(scorer, root)[0]["recovery_scored"] is False


# ------------------------------------------------------------------ family C


def test_cost_is_read_from_the_meter_not_the_self_report(scorer, tmp_path):
    calls = [
        {"name": "simulate", "args": {"a": 1}, "n_evaluations": 1, "runtime_s": 12.0},
        {"name": "gsa_morris", "args": {"r": 4}, "n_evaluations": 84, "runtime_s": 900.0},
        {"name": "request_assay", "args": {"assay": "tan", "day": 10.0}, "assay_units": 1},
        {"name": "request_assay", "args": {"assay": "alkalinity", "day": 10.0}, "assay_units": 1},
    ]
    root = tmp_path / "honest"
    state = _state_with_calls(root, "run_000000000001", calls, budget={
        "simulator_evals_used": 85, "assay_units_used": 2,
    })  # fmt: skip
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["simulator_evals"] == 85 and row["assay_units"] == 2 and row["n_calls"] == 4
    assert row["tool_runtime_s"] == pytest.approx(914.0)
    assert row["self_report_mismatch"] is False and row["meter_agrees_with_summary"] is True
    assert row["simulator_evals_fraction"] == pytest.approx(0.85)
    assert row["wall_clock_fraction"] == pytest.approx(120.0 / 3600.0)
    assert row["cost_source"] == "registry_meter" and row["tokens"] is None

    # the workflow under-reports: the scored cost does not move, the mismatch is flagged
    root = tmp_path / "liar"
    state = _state_with_calls(root, "run_000000000001", calls, budget={
        "simulator_evals_used": 5, "assay_units_used": 0,
    })  # fmt: skip
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["simulator_evals"] == 85 and row["assay_units"] == 2
    assert row["self_report_mismatch"] is True

    # a summary whose call count disagrees with the log is flagged too
    root = tmp_path / "calls"
    state = _state_with_calls(
        root, "run_000000000001", calls, budget={"simulator_evals_used": 85, "assay_units_used": 2}
    )
    build_run(root, state=state, calls=calls, summary={"n_calls": 3})
    row, _ = _score(scorer, root)
    assert row["meter_agrees_with_summary"] is False and row["n_calls"] == 4


def test_uncertainty_reduction_per_assay_unit(scorer, tmp_path):
    k_lo, k_hi = prior_interval(
        MODEL.parameters["k_dis"].lower, MODEL.parameters["k_dis"].upper, 0.9
    )
    half = (k_hi - k_lo) / 2.0
    calls = [{"name": "request_assay", "args": {"assay": "tan", "day": 1.0}, "assay_units": 2}]
    root = tmp_path / "halved"
    state = _state_with_calls(root, "run_000000000001", calls, final={
        "parameters": {"k_dis": parameter(1.0, 1.0 - half / 2, 1.0 + half / 2)}
    })  # fmt: skip
    build_run(root, state=state, calls=calls)
    row, _ = _score(scorer, root)
    assert row["uncertainty_reduction"] == pytest.approx(0.5)
    assert row["uncertainty_reduction_per_assay_unit"] == pytest.approx(0.25)

    root = tmp_path / "noassay"  # no unit spent: the per-unit figure abstains
    build_run(root, state=minimal_state("run_000000000001", final={
        "parameters": {"k_dis": parameter(1.0, 0.5, 1.5)}
    }))  # fmt: skip
    row, _ = _score(scorer, root)
    assert row["uncertainty_reduction"] is not None
    assert row["uncertainty_reduction_per_assay_unit"] is None


# ------------------------------------------------------------------ family D


def test_reliability_counts_come_from_the_truth_side_log(scorer, tmp_path):
    calls = [
        {"name": "simulate", "args": {"a": 1}, "n_evaluations": 1},
        {"name": "simulate", "args": {"a": 1}, "n_evaluations": 1},  # a retry
        {"name": "simulate", "args": {"a": 2}, "outcome": "error",
         "detail": "ValidationError: 1 validation error"},  # invalid action
        {"name": "gsa_sobol", "args": {"n": 8}, "outcome": "budget_exceeded",
         "detail": "call would make up to 80 simulator evaluations"},  # invalid action
        {"name": "fit_lsq", "args": {}, "outcome": "error", "detail": "ToolError: singular"},
        {"name": "bayes_mcmc", "args": {}, "outcome": "injected_failure"},
        {"name": "verifier.reject", "args": {"reason": "x"}},
    ]  # fmt: skip
    root = tmp_path / "counts"
    build_run(root, calls=calls)
    row, _ = _score(scorer, root)
    assert row["completed"] is True and row["launched"] is True
    assert row["retries"] == 1
    assert row["invalid_actions"] == 2 and row["budget_refusals"] == 1
    assert row["tool_errors"] == 1
    assert row["injected_failures"] == 1
    assert row["verifier_rejections"] == 1
    assert row["n_calls"] == 7

    root = tmp_path / "clean"
    build_run(root, calls=[{"name": "simulate", "args": {"a": 1}, "n_evaluations": 1}])
    row, _ = _score(scorer, root)
    assert (
        row["retries"],
        row["invalid_actions"],
        row["tool_errors"],
        row["injected_failures"],
    ) == (0, 0, 0, 0)


def test_a_failed_run_stays_in_the_denominator(scorer, tmp_path):
    root = tmp_path / "killed"  # launched, killed: a summary with an error, no state
    killed = {
        "completed": False,
        "returncode": None,
        "error": "the workflow was killed after 5700 s",
    }
    build_run(root, write_state=False, summary=killed)
    row, _ = _score(scorer, root)
    assert row["launched"] is True and row["completed"] is False and row["state_valid"] is False
    assert "killed" in row["runner_error"] and "state.json missing" in row["problems"]
    assert row["attribution_exact"] is False and row["recovery_scored"] is False

    root = tmp_path / "never"  # never launched: no summary, no state
    build_run(root, write_state=False, write_summary=False)
    row, _ = _score(scorer, root)
    assert row["launched"] is False and row["completed"] is False
    assert row["runner_error"] == "not launched"

    root = tmp_path / "invalid"  # a state that does not validate is no state
    build_run(root, state={"schema_version": "1.0", "garbage": True})
    row, _ = _score(scorer, root)
    assert row["state_valid"] is False and row["completed"] is True  # the runner's verdict stands
    assert "invalid" in row["problems"]

    # the aggregate keeps every row: n_runs counts the failed ones
    rows = [_score(scorer, tmp_path / name)[0] for name in ("killed", "never", "invalid")]
    agg = aggregate(rows, CFG.aggregate)
    assert len(agg) == 1 and agg[0]["n_runs"] == 3 and agg[0]["n_completed"] == 1
    assert agg[0]["completed_mean"] == pytest.approx(1 / 3)
    # the two launched runs are attribution misses; the never-launched one is no datum,
    # and `_n` beside the rate says how many runs the rate is over
    assert agg[0]["attribution_exact_n"] == 2 and agg[0]["attribution_exact_mean"] == 0.0

    # an unreadable answer key is the one thing the loader refuses, and it says which file
    from eval.records import load_records

    root = tmp_path / "broken"
    build_run(root)
    (root / "truth_store" / "run_000000000001" / "faults.json").write_text("not json")
    with pytest.raises(FileNotFoundError, match=r"faults\.json is not a JSON object"):
        load_records(
            "run_000000000001", "p0", runs_root=root / "runs", truth_store=root / "truth_store"
        )


# ------------------------------------------------------------------ the aggregate


def test_the_aggregate_bootstraps_with_the_declared_seed():
    rows = [
        {"scenario_id": "S0-01", "plant": "B", "tier": "A", "workflow": "p0", "seed": s,
         "completed": True, "attribution_exact": s % 2 == 0, "pH_mae": 0.1 * (s + 1),
         "final_label": "none", "recovery_n": None}
        for s in range(4)
    ]  # fmt: skip
    agg = aggregate(rows, CFG.aggregate)
    assert len(agg) == 1
    a = agg[0]
    assert a["n_runs"] == 4 and a["pH_mae_n"] == 4
    assert a["pH_mae_mean"] == pytest.approx(0.25)
    assert a["pH_mae_sd"] == pytest.approx(np.std([0.1, 0.2, 0.3, 0.4], ddof=1))
    assert a["pH_mae_lo"] <= a["pH_mae_mean"] <= a["pH_mae_hi"]
    assert a["attribution_exact_mean"] == 0.5 and "attribution_exact_lo" in a
    assert "final_label_mean" not in a and "recovery_n_mean" not in a
    again = aggregate(rows, CFG.aggregate)
    assert again == agg  # the same seed, the same interval (rule 4)
    values = np.random.default_rng(3).standard_normal(30)
    lo1, hi1 = bootstrap_mean_interval(values, n_resamples=500, interval=0.9, seed=1)
    lo2, hi2 = bootstrap_mean_interval(values, n_resamples=500, interval=0.9, seed=1)
    lo3, _ = bootstrap_mean_interval(values, n_resamples=500, interval=0.9, seed=2)
    assert (lo1, hi1) == (lo2, hi2) and lo3 != lo1

    single = aggregate(rows[:1], CFG.aggregate)[0]
    assert single["pH_mae_n"] == 1 and "pH_mae_lo" not in single and "pH_mae_sd" not in single

    two_cells = aggregate([*rows, {**rows[0], "tier": "B"}], CFG.aggregate)
    assert [(a["tier"], a["n_runs"]) for a in two_cells] == [("A", 4), ("B", 1)]


# ------------------------------------------------------------------ the command line


def test_the_command_line_scores_a_store_and_writes_four_tables(tmp_path, capsys):
    from eval.__main__ import main

    root = tmp_path / "store"
    build_run(root, "run_000000000001", level=0)
    build_run(root, "run_000000000002", level=2, truth_label=("sensor",), scenario_id="S2-01")
    build_run(
        root,
        "run_000000000003",
        level=2,
        truth_label=("sensor",),
        scenario_id="S2-01",
        write_state=False,
        write_summary=False,
    )  # generated, never run: not selected
    out = tmp_path / "tables" / "scored.csv"
    assert main(["--runs-root", str(root / "runs"), "--all", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "2 runs scored" in printed
    assert out.is_file() and out.with_suffix(".json").is_file()
    agg = out.with_name("scored_aggregate.csv")
    assert agg.is_file() and agg.with_suffix(".json").is_file()
    header = out.read_text().splitlines()[0].split(",")
    assert header[:4] == ["run_id", "workflow", "scenario_id", "level"]
    assert {"attribution_exact", "false_kinetic_drift", "simulator_evals", "completed"} <= set(
        header
    )
    rows = json.loads(out.with_suffix(".json").read_text())
    assert [r["run_id"] for r in rows] == ["run_000000000001", "run_000000000002"]
    # the scorer wrote nothing under the run store or the truth store
    assert sorted(p.name for p in (root / "runs" / "run_000000000001").iterdir()) == [
        "calls.jsonl", "manifest.json", "observations", "workflows"
    ]  # fmt: skip
    assert not any(p.suffix == ".csv" for p in (root / "truth_store").rglob("*"))

    # an explicit run id scores a never-launched run as not completed
    selected = selected_runs(root / "truth_store", runs_root=root / "runs", workflow="p0",
                             run_ids=["run_000000000003"])  # fmt: skip
    assert selected == ["run_000000000003"]
    assert main(["--runs-root", str(root / "runs"), "--run", "run_000000000003",
                 "--out", str(tmp_path / "one.csv")]) == 0  # fmt: skip
    one = json.loads((tmp_path / "one.json").read_text())
    assert one[0]["completed"] is False and one[0]["launched"] is False

    with pytest.raises(SystemExit):
        main(["--runs-root", str(root / "runs"), "--out", str(tmp_path / "x.csv")])

    path = write_tables([{"a": 1.23456789, "b": None, "c": "x"}], tmp_path / "t.csv")
    assert (tmp_path / "t.csv").read_text().splitlines() == ["a,b,c", "1.23457,,x"]
    assert path.name == "t.json"
