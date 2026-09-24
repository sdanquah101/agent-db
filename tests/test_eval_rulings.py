"""The lead's evaluator rulings of 2026-09-24 (PR D).

- D1 over-abstention: ``abstention_extra`` and ``abstention_precision`` sit beside an
  unchanged ``abstention_correct``. The negative control is a run that declines every
  vocabulary term: correct, but with precision near 0.
- D2 earned abstention: S8-01's ``posterior_intervals`` counts only when the logs show
  the last ``bayes_mcmc`` call that ran failed (not converged, injected failure, error).
  P0's plan-level skip earns nothing; the workflow's own failure record is never evidence.
- D3 is documentation (``claim_sources`` means the call the number rests on). The test
  checks the definition is written where the ruling put it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from eval.config import load_eval_config
from eval.records import load_records
from eval.score import Scorer
from state.abstentions import abstention_vocabulary
from tests.conftest import REPO_ROOT
from tests.eval_support import actions_for, build_run, minimal_state

SCORER = Scorer()
RUN = "run_000000000001"


def _score(root: Path) -> dict:
    records = load_records(RUN, "p0", runs_root=root / "runs", truth_store=root / "truth_store")
    return SCORER.score(records)


def _run(
    root: Path,
    *,
    abstain_on: tuple[str, ...],
    declared: list[str],
    calls: list[dict] | None = None,
    failures: list[dict] | None = None,
    truth_label: tuple[str, ...] = ("sensor",),
) -> dict:
    """A constructed run with the given answer key, abstentions and sampler calls."""
    conclusion = {"kinetic_update_allowed": False, "abstain_on": list(abstain_on)}
    calls = calls or []
    build_run(root, RUN, calls=calls, index=False)
    actions = actions_for(calls, root / "runs" / RUN) if calls else []
    state = minimal_state(
        RUN,
        actions=actions,
        tool_failures=failures or [],
        abstentions=declared,
        final={"abstentions": declared},
    )
    build_run(
        root,
        RUN,
        state=state,
        calls=calls,
        truth_label=truth_label,
        correct_conclusion=conclusion,
        level=8 if "posterior_intervals" in abstain_on else 0,
        scenario_id="S8-01" if "posterior_intervals" in abstain_on else "S0-01",
    )
    return _score(root)


MCMC = {"name": "bayes_mcmc", "args": {"walkers": 4}, "n_evaluations": 8}


def _failure(kind: str) -> dict:
    return {
        "step": "mcmc",
        "name": "bayes_mcmc",
        "call_index": 0,
        "kind": kind,
        "message": "R-hat 1.4",
        "fallback": "Fisher intervals stand",
    }


# ------------------------------------------------------------------ D1 over-abstention


def test_declining_everything_is_correct_but_imprecise(tmp_path: Path):
    """Negative control: all 47 terms declined, S2-02's two among them."""
    everything = sorted(abstention_vocabulary())
    assert len(everything) == 47
    row = _run(tmp_path, abstain_on=("ch4_fraction_claims", "ch4_yield"), declared=everything)
    assert row["abstention_correct"] is True  # the ruling keeps this exactly as defined
    assert row["abstention_fraction"] == 1.0
    assert row["abstention_extra"] == 45
    assert row["abstention_precision"] == 2 / 47


def test_declining_exactly_the_key_is_precise(tmp_path: Path):
    row = _run(
        tmp_path,
        abstain_on=("ch4_fraction_claims", "ch4_yield"),
        declared=["ch4_fraction_claims", "ch4_yield"],
    )
    assert row["abstention_correct"] is True
    assert row["abstention_extra"] == 0 and row["abstention_precision"] == 1.0


def test_precision_is_null_when_nothing_is_declared_and_counted_on_every_run(tmp_path: Path):
    silent = _run(tmp_path / "a", abstain_on=(), declared=[])
    assert silent["abstention_precision"] is None and silent["abstention_extra"] == 0
    assert silent["abstention_correct"] is None  # no answer-key terms: not scored, as before
    # a run declining something on a cell whose key asks for nothing: precision 0
    noisy = _run(tmp_path / "b", abstain_on=(), declared=["missing_transient"])
    assert noisy["abstention_extra"] == 1 and noisy["abstention_precision"] == 0.0


def test_the_new_columns_are_declared_and_aggregated(tmp_path: Path):
    from eval.aggregate import aggregate

    raw = (REPO_ROOT / "configs" / "eval.yaml").read_text(encoding="utf-8")
    assert "abstention_extra" in raw and "abstention_precision" in raw
    design = (REPO_ROOT / "docs" / "eval_design.md").read_text(encoding="utf-8")
    assert "abstention_extra" in design and "abstention_precision" in design
    row = _run(tmp_path, abstain_on=("ch4_yield",), declared=["ch4_yield", "ph_claims"])
    groups = aggregate([row], load_eval_config().aggregate)
    assert groups[0]["abstention_precision_mean"] == 0.5
    assert groups[0]["abstention_extra_mean"] == 1.0


# ------------------------------------------------------------------ D2 earned abstention


def test_a_plan_level_skip_earns_no_credit(tmp_path: Path):
    """P0 on a slow machine: no sampler call, `posterior_intervals` declined anyway."""
    row = _run(
        tmp_path,
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        truth_label=("sensor",),
    )
    assert row["abstention_correct"] is False
    assert row["abstention_fraction"] == 0.0
    assert row["abstention_precision"] == 0.0  # declared, but not credited
    assert row["abstention_extra"] == 0  # it is the key's own term, just unearned


def test_a_logged_non_converged_call_earns_it(tmp_path: Path):
    """The registry notes `not_converged` on the ok line of a sampler that did not converge."""
    row = _run(
        tmp_path,
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[{**MCMC, "detail": "not_converged"}],
    )
    assert row["abstention_correct"] is True and row["abstention_precision"] == 1.0


def test_an_injected_failure_or_a_logged_error_earns_it(tmp_path: Path):
    injected = _run(
        tmp_path / "a",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[{**MCMC, "outcome": "injected_failure"}],
    )
    assert injected["abstention_correct"] is True
    errored = _run(
        tmp_path / "b",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[{**MCMC, "outcome": "error", "detail": "RuntimeError: diverged"}],
    )
    assert errored["abstention_correct"] is True


def test_the_workflows_own_failure_record_is_never_evidence(tmp_path: Path):
    """Review of PR #24, item 2: a converged ok call plus a self-declared record earns nothing."""
    row = _run(
        tmp_path,
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[MCMC],
        failures=[_failure("not_converged")],
    )
    assert row["abstention_correct"] is False
    # nor does a record naming no logged sampler call at all
    unanchored = _run(
        tmp_path / "b",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        failures=[_failure("not_converged")],
    )
    assert unanchored["abstention_correct"] is False


def test_the_evidence_is_the_log_whatever_the_actions_list(tmp_path: Path):
    """Review item 1: the log decides, not the actions or the failure records.

    Calls [residual_diag, bayes_mcmc] with a failed sampler earn the credit, and a
    failure record whose index lands on the residual_diag call earns nothing.
    """
    calls = [{"name": "residual_diag", "args": {"o": "pH"}}, {**MCMC, "detail": "not_converged"}]
    missed_before = _run(
        tmp_path / "a",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=calls,
    )
    assert missed_before["abstention_correct"] is True
    false_before = _run(
        tmp_path / "b",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[{"name": "residual_diag", "args": {"o": "pH"}}, MCMC],
        failures=[_failure("not_converged")],  # call_index 0: the residual_diag call
    )
    assert false_before["abstention_correct"] is False


def test_the_last_sampler_call_decides(tmp_path: Path):
    """Review item 3: an error followed by a converged call is a posterior that exists."""
    recovered = _run(
        tmp_path / "a",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[
            {**MCMC, "outcome": "error", "detail": "RuntimeError: x"},
            {**MCMC, "args": {"walkers": 8}},
        ],
    )
    assert recovered["abstention_correct"] is False
    failed_last = _run(
        tmp_path / "b",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[MCMC, {**MCMC, "args": {"walkers": 8}, "detail": "not_converged"}],
    )
    assert failed_last["abstention_correct"] is True


def test_a_converged_call_or_a_refusal_earns_nothing(tmp_path: Path):
    converged = _run(
        tmp_path / "a",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[MCMC],
    )
    assert converged["abstention_correct"] is False
    refused = _run(
        tmp_path / "b",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[{**MCMC, "outcome": "budget_exceeded", "n_evaluations": 0}],
    )
    assert refused["abstention_correct"] is False
    # a refusal after a failed run does not hide the failure: refusals run nothing
    failed_then_refused = _run(
        tmp_path / "c",
        abstain_on=("posterior_intervals",),
        declared=["posterior_intervals"],
        calls=[{**MCMC, "detail": "not_converged"}, {**MCMC, "outcome": "budget_exceeded"}],
    )
    assert failed_then_refused["abstention_correct"] is True


def test_other_terms_need_no_call(tmp_path: Path):
    row = _run(tmp_path, abstain_on=("ch4_yield",), declared=["ch4_yield"])
    assert row["abstention_correct"] is True


# ------------------------------------------------------------------ D3 the definition


def test_claim_sources_are_defined_as_the_call_the_number_rests_on():
    raw = (REPO_ROOT / "configs" / "eval.yaml").read_text(encoding="utf-8")
    design = (REPO_ROOT / "docs" / "eval_design.md").read_text(encoding="utf-8")
    assert "RESTS ON" in raw and "ruling D3" in raw
    assert "the call the number rests on" in design and "ruling\n  D3" in design
    # the meaning is documented, not changed: the mapping is what it was
    sources = yaml.safe_load(raw)["attribution"]["claim_sources"]["by_value_key"]
    assert sources["bias_z"] == ["residual_diag"]
