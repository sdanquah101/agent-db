"""P0, the scripted pipeline (milestone 5; ``docs/p0_design.md``), end to end through the jail.

1. The pipeline module passes the rule-1 checker (allow-listed imports only, no dynamic
   import, no truth token), and what the runner hands the jail carries nothing of a run.
2. On a short S0-01 cell of Plant C with a tiny budget, P0 completes through the declared
   fallbacks: its ``state.json`` validates against the shared schema, the output directory
   holds exactly the contract, evaluations used never exceed the budget, every action's
   sequence number and argument hash match the visible call log line for line, the
   fallbacks are recorded, and no truth-side token (scenario id, seeds, fault types, the
   salt, the truth path, a timestamp) appears in anything P0 wrote.
3. The same cell twice gives the same ``state.json`` (rule 4), the wall-clock fields aside.
4. On a short S8-01 cell (the Level-8 directive on ``bayes_mcmc``) with a small test
   configuration, P0 calls the sampler once, does not report the posterior, records the
   failure and abstains on ``posterior_intervals``; the truth-side log says
   ``injected_failure`` while the visible one says ``ok``.
5. The attribution rule on constructed evidence: each rule fires on the evidence designed
   for it and not on clean evidence; the compound case reports one primary label and the
   secondary ones.
6. The runner's batch selection over the truth-side index and its table.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from scenarios.schema import load_scenario
from sim.plants import load_plant_config
from sim.run.harness import generate_run
from state.provenance import read_calls
from state.task_state import LABELS, TaskState
from tests.conftest import REPO_ROOT
from tests.test_truth_isolation import find_truth_references
from tools.config import load_fitted_model
from tools.runner import WORKFLOWS, main, run_workflow, select_cells, write_table
from tools.server import OUTPUTS_DIR
from tools.workflow_config import load_p0, sandbox_config
from workflows.p0_scripted import pipeline

SHORT_DAYS = 30.0
PIPELINE = WORKFLOWS["p0"]


def _short(scenario_id: str, *, evals: int, wall_min: float, assays: int):
    scenario = load_scenario(REPO_ROOT / "scenarios" / f"{scenario_id}.yaml")
    faults = tuple(
        f.model_copy(update={"onset_day": min(f.onset_day, SHORT_DAYS / 2)})
        for f in scenario.faults
    )
    budget = scenario.budget.model_copy(
        update={"simulator_evals": evals, "wall_clock_min": wall_min, "assay_units": assays}
    )
    return scenario.model_copy(
        update={"duration_days": SHORT_DAYS, "faults": faults, "budget": budget}
    )


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    return tmp_path_factory.mktemp("store")


@pytest.fixture(scope="module")
def tiny_cell(store):
    """S0-01 on Plant C at Tier B, 30 d, 40 evaluations: every expensive step falls back."""
    scenario = _short("S0-01", evals=40, wall_min=20.0, assays=2)
    run = generate_run(scenario, "B", plant=load_plant_config("C"), runs_root=store / "runs")
    return run, scenario


@pytest.fixture(scope="module")
def tiny_result(tiny_cell, tmp_path_factory):
    run, scenario = tiny_cell
    result = run_workflow(
        run.run_id,
        "p0",
        runs_root=run.paths.root.parent,
        scenario=scenario,
    )
    return run, scenario, result


def _state(run) -> dict:
    return json.loads((run.paths.root / OUTPUTS_DIR / "p0" / "state.json").read_text())


# ------------------------------------------------------------------ 1. static


def test_the_pipeline_passes_the_rule_one_checker():
    assert PIPELINE.is_file()
    assert find_truth_references(PIPELINE) == []
    for module in (REPO_ROOT / "workflows").rglob("*.py"):
        assert find_truth_references(module) == [], module


def test_what_the_runner_hands_the_jail_carries_nothing_of_a_run():
    config = load_p0()
    payload = sandbox_config(config)
    assert set(payload) == set(config.model_dump()) | {"sensor_noise", "plant_geometry"}
    assert set(payload["plant_geometry"]) == {"A", "B", "C"}
    assert payload["plant_geometry"]["B"]["V_liq_m3"] == 1836.0
    assert set(payload["sensor_noise"]["ph"]) == {
        "cv",
        "sd_abs",
        "drift_bound",
        "drift_sd_per_sqrt_d",
    }
    text = json.dumps(payload)
    for token in ("run_", "truth", "scenario_id", "S0-01", "S8-01", "seed:", "baseline"):
        assert token not in text, token
    # every stochastic step has a declared seed, and the labels are the six classes
    assert set(config.seeds.model_dump()) == {
        "morris", "sobol", "profile", "lsq", "de", "mcmc", "ensemble"
    }  # fmt: skip
    assert set(config.labels.model_dump().values()) == set(LABELS)


# ------------------------------------------------------------------ 2. end to end


def test_p0_completes_a_tiny_cell_through_the_fallbacks_and_keeps_the_contract(tiny_result):
    run, _, result = tiny_result
    assert result.error == "", result.stderr_tail
    assert result.completed and result.state_valid and result.returncode == 0
    out_dir = run.paths.root / OUTPUTS_DIR / "p0"
    assert {p.name for p in out_dir.iterdir()} == {"state.json", "report.json", "summary.json"}
    assert {p.name for p in run.paths.root.iterdir()} == {
        "observations", "manifest.json", "calls.jsonl", OUTPUTS_DIR
    }  # fmt: skip
    state = TaskState.model_validate_json((out_dir / "state.json").read_text())
    assert state.workflow == "p0" and state.run_id == run.run_id
    assert state.plant == "C" and state.tier == "B" and state.duration_days == SHORT_DAYS
    assert state.holdout_window == (SHORT_DAYS * 0.75, SHORT_DAYS)
    assert state.final.completed and state.final.label in LABELS
    assert state.classification.label == state.final.label
    # the budget: never over, and the registry's own count agrees with the log
    assert state.budget.simulator_evals_total == 40
    assert 0 < state.budget.simulator_evals_used <= 40
    assert state.budget.simulator_evals == 40 - state.budget.simulator_evals_used
    visible = read_calls(run.paths.root)
    opened = [i for i, r in enumerate(visible) if r.name == "registry.open"]
    assert len(opened) == 1
    assert state.budget.n_calls == len(visible) - opened[0] - 1
    # every action names its log line, and the line agrees
    assert state.actions and all(a.seq is not None for a in state.actions)
    for action in state.actions:
        line = visible[action.seq]
        assert (line.name, line.args_hash, line.outcome) == (
            action.name, action.args_hash, action.outcome
        ), action  # fmt: skip
        assert line.version == action.version
    assert [a.name for a in state.actions[:3]] == ["describe_model", "feed_loads", "simulate"]
    # the fallbacks fired and were recorded; nothing expensive ran
    names = [a.name for a in state.actions]
    assert "gsa_morris" not in names and "gsa_sobol" not in names and "bayes_mcmc" not in names
    assert state.plan.fallbacks and any("morris" in f for f in state.plan.fallbacks)
    assert "posterior_intervals" in state.abstentions
    assert state.final.interval_method in ("none", "fisher")  # DE alone may fit the budget
    bounds = load_fitted_model().parameters
    for name, est in state.final.parameters.items():
        assert est.method in ("none", "fisher")
        if est.lower is not None:  # the interval is clipped to the admissible range
            assert est.lower <= est.estimate <= est.upper
            assert bounds[name].lower <= est.lower and est.upper <= bounds[name].upper
    assert "mcmc" in state.plan.steps_skipped
    assert state.plan.eval_seconds_assumed == load_p0().plan.eval_seconds_assumed
    assert "attribute" in state.plan.steps_completed
    # QC ran on every sensor of the tier; temperature is never in the objective
    assert set(state.data_quality) == {
        "temperature", "ph", "gas_flow", "ch4_fraction", "alkalinity", "vfa_total", "tan",
        "cod_total",
    }  # fmt: skip
    assert not state.data_quality["temperature"].in_objective
    assert "gas_flow" in state.calibrated_outputs or "q_gas_stp_dry" in state.calibrated_outputs
    # the notes are data: day and author, never the text
    assert all(set(n) == {"day", "author", "length"} for n in state.notes_seen)
    # the summary the runner wrote beside it
    summary = json.loads((out_dir / "summary.json").read_text())
    assert summary["run_id"] == run.run_id and summary["completed"] is True
    assert summary["simulator_evals_used"] == state.budget.simulator_evals_used
    assert summary["label"] == state.final.label and summary["wall_s"] > 0


def test_nothing_p0_wrote_carries_a_truth_side_token(tiny_result):
    run, scenario, _ = tiny_result
    out_dir = run.paths.root / OUTPUTS_DIR / "p0"
    complete = json.loads(run.paths.truth_manifest.read_text())
    salt = (run.paths.truth.parent / "salt").read_bytes().hex()
    tokens = [
        scenario.id,
        "S0-01",
        str(run.paths.truth),
        "truth_store",
        salt,
        "t_utc",
        "created_utc",
        "injected",
        "baseline",
    ]
    seeds = {str(v) for v in complete["seeds"].values() if isinstance(v, int) and v > 99}
    assert len(seeds) >= 5
    for path in out_dir.iterdir():
        text = path.read_text()
        for token in tokens:
            assert token not in text, (path.name, token)
        for seed in seeds:
            assert re.search(rf"(?<![\d.]){re.escape(seed)}(?![\d.])", text) is None, (
                path.name,
                seed,
            )
        # no timestamp of any kind
        assert re.search(r"20\d\d-\d\d-\d\dT", text) is None, path.name
    # and the truth-side tokens really are on disk, out here
    assert scenario.id in run.paths.truth_manifest.read_text()


def test_the_same_cell_twice_gives_the_same_state(tiny_result):
    run, scenario, _ = tiny_result
    before = _state(run)
    again = run_workflow(run.run_id, "p0", runs_root=run.paths.root.parent, scenario=scenario)
    assert again.completed and again.error == ""
    after = _state(run)

    def normalise(state: dict) -> dict:
        state = json.loads(json.dumps(state))
        state["budget"].pop("wall_clock_min")
        state["plan"].pop("guards_tripped")
        # the second run's calls continue the log: sequence numbers and indices shift by a
        # constant, so compare the actions without them
        for action in state["actions"]:
            action.pop("seq")
            action.pop("call_index")
        state["budget"].pop("n_calls")
        for item in state["classification"]["evidence"]:
            item.pop("calls")
        if state.get("validation"):
            state["validation"].pop("calls")
        return state

    assert normalise(before) == normalise(after)
    assert before["plan"]["guards_tripped"] == [] == after["plan"]["guards_tripped"]


# ------------------------------------------------------------------ 4. the Level-8 row


@pytest.fixture(scope="module")
def small_config(tmp_path_factory) -> Path:
    """The frozen configuration with sizes a 30-day cell can afford in a test."""
    raw = yaml.safe_load((REPO_ROOT / "configs" / "workflows" / "p0.yaml").read_text())
    raw["gsa"]["morris_trajectories"] = 1
    raw["plan"]["morris_min_trajectories"] = 1
    raw["screening"]["morris_keep"] = 2
    raw["gsa"]["sobol_samples"] = 8
    raw["fit"]["lsq_starts"] = 1
    raw["fit"]["lsq_max_nfev_per_start"] = 5
    raw["fit"]["de_generations"] = 1  # below the minimum: DE is skipped by the ladder
    raw["mcmc"]["walkers"] = 4
    raw["mcmc"]["steps"] = 2
    raw["plan"]["mcmc_min_steps"] = 2
    raw["validation"]["ensemble_size"] = 2
    raw["fit"]["second_pass"] = False
    path = tmp_path_factory.mktemp("cfg") / "p0_small.yaml"
    path.write_text(yaml.safe_dump(raw))
    assert load_p0(path).mcmc.steps == 2
    return path


def test_the_level_eight_fallback_records_the_failure_and_reports_no_posterior(store, small_config):
    scenario = _short("S8-01", evals=400, wall_min=30.0, assays=6)
    run = generate_run(scenario, "B", plant=load_plant_config("C"), runs_root=store / "runs")
    result = run_workflow(
        run.run_id, "p0", runs_root=store / "runs", scenario=scenario, config_path=small_config
    )
    assert result.error == "", result.stderr_tail
    assert result.completed
    state = TaskState.model_validate_json(
        (run.paths.root / OUTPUTS_DIR / "p0" / "state.json").read_text()
    )
    names = [a.name for a in state.actions]
    assert names.count("bayes_mcmc") == 1, names  # called once, never retried
    assert "gsa_morris" in names and "fit_lsq" in names and "validate" in names
    failures = [f for f in state.tool_failures if f.name == "bayes_mcmc"]
    assert len(failures) == 1 and failures[0].kind == "not_converged"
    assert "R-hat" in failures[0].message and "not reported" in failures[0].fallback
    assert "posterior_intervals" in state.abstentions
    assert state.final.interval_method in ("fisher", "profile", "none")
    assert all(p.method != "posterior" for p in state.final.parameters.values())
    assert state.final.parameters, "the screened fit produced estimates"
    # the failure is injected: the truth-side log knows, the visible one does not
    truth_log = [r for r in read_calls(run.paths.truth) if r.name == "bayes_mcmc"]
    visible_log = [r for r in read_calls(run.paths.root) if r.name == "bayes_mcmc"]
    assert [r.outcome for r in truth_log] == ["injected_failure"]
    assert [r.outcome for r in visible_log] == ["ok"]
    mcmc_action = next(a for a in state.actions if a.name == "bayes_mcmc")
    assert mcmc_action.outcome == "ok" and mcmc_action.seq == visible_log[0].seq
    # the assay rule spent its units
    assert state.budget.assay_units_used >= 1 and state.assay_checks
    assert state.validation is not None and state.validation.ensemble


# ------------------------------------------------------------------ 5. the rule


def _cfg() -> dict:
    return sandbox_config(load_p0())


def _residual(**kw: object) -> dict:
    base = {
        "n": 100, "bias_z": 0.2, "rmse_z": 1.0, "serially_structured": False,
        "lag1_autocorrelation": 0.05, "trend_slope_per_d": 0.0, "most_explanatory": None,
        "covariate_eta2": {}, "step_z": 1.0, "step_day": 60.0, "early_bias_z": 0.3,
        "late_bias_z": 0.1,
    }  # fmt: skip
    base.update(kw)
    return base


CHANNELS = {"gas_flow": "q_gas_stp_dry", "ph": "pH", "ch4_fraction": "ch4_fraction", "tan": "tan"}
CLEAN_BALANCE = {"admissible": True, "n_cod_inadmissible": 0, "charge_consistent": True}


def _classify(residuals, balance=None, flagged=(), abstentions=(), at_bound=False):
    cfg = _cfg()
    return pipeline.classify(
        cfg, cfg["labels"], residuals=residuals, balance=balance or CLEAN_BALANCE,
        flagged=list(flagged), channel_of=CHANNELS, primary_channel="q_gas_stp_dry",
        abstentions=list(abstentions), at_bound=at_bound,
    )  # fmt: skip


def test_clean_evidence_is_none_and_every_rule_fires_on_its_own_evidence():
    clean = {ch: _residual() for ch in CHANNELS.values()}
    verdict = _classify(clean)
    assert (
        verdict["classification"]["label"] == "none" and verdict["classification"]["rule"] == "R6"
    )
    assert verdict["classification"]["kinetic_update"] and verdict["abstentions"] == []
    assert verdict["classification"]["confidence"] == 0.6

    # R1a: QC flagged a sensor
    v = _classify(clean, flagged=["ph"])
    assert (v["classification"]["label"], v["classification"]["rule"]) == ("sensor", "R1")
    assert v["classification"]["flag_sensor"] == "ph"
    assert "kinetic_attribution" in v["abstentions"] and not v["classification"]["kinetic_update"]

    # R1b: one channel off, the rest clean
    off = dict(clean, q_gas_stp_dry=_residual(bias_z=5.0, step_z=6.0, step_day=60.0))
    v = _classify(off)
    assert (
        v["classification"]["label"] == "sensor"
        and v["classification"]["flag_sensor"] == "gas_flow"
    )
    assert any(e["rule"] == "R1b" for e in v["evidence"])
    # ... but not when a second channel is off too
    two = dict(off, pH=_residual(bias_z=4.0))
    assert _classify(two)["classification"]["label"] != "sensor"

    # R1c: the charge balance disagrees with a structured pH
    v = _classify(
        dict(clean, pH=_residual(serially_structured=True)),
        balance={**CLEAN_BALANCE, "charge_consistent": False, "charge_drift": 0.4},
    )
    assert v["classification"]["label"] == "sensor" and v["classification"]["flag_sensor"] == "ph"

    # R2: the COD balance does not close, or the feed batch explains the residual
    v = _classify(clean, balance={**CLEAN_BALANCE, "admissible": False, "n_cod_inadmissible": 3})
    assert (v["classification"]["label"], v["classification"]["rule"]) == ("influent", "R2")
    assert v["classification"]["revise_influent_mapping"]
    feed = dict(
        clean,
        q_gas_stp_dry=_residual(most_explanatory="feed_fog", covariate_eta2={"feed_fog": 0.3}),
    )
    assert _classify(feed)["classification"]["label"] == "influent"

    # R5: the initial transient only
    early = dict(clean, q_gas_stp_dry=_residual(early_bias_z=5.0, late_bias_z=0.5))
    v = _classify(early)
    assert (v["classification"]["label"], v["classification"]["rule"]) == ("state", "R5")
    # ... and informative missingness found by QC
    assert _classify(clean, abstentions=["missing_transient"])["classification"]["label"] == "state"

    # R4: a common change point in two channels
    shift = dict(
        clean,
        q_gas_stp_dry=_residual(step_z=4.0, step_day=100.0),
        ch4_fraction=_residual(step_z=3.5, step_day=110.0),
    )
    v = _classify(shift)
    assert (v["classification"]["label"], v["classification"]["rule"]) == ("parameter", "R4")
    assert v["classification"]["kinetic_update"]
    # ... two change points far apart are not common
    apart = dict(shift, ch4_fraction=_residual(step_z=3.5, step_day=10.0))
    assert _classify(apart)["classification"]["label"] != "parameter"

    # R3: persistent structure by load in two channels
    structural = dict(
        clean,
        pH=_residual(rmse_z=3.0, serially_structured=True, most_explanatory="load"),
        tan=_residual(rmse_z=2.5, serially_structured=True, most_explanatory="time"),
    )
    v = _classify(structural)
    assert (v["classification"]["label"], v["classification"]["rule"]) == ("structural", "R3")
    assert v["classification"]["recommend_structural_review"]
    assert {"parameter_values", "kinetic_attribution", "pH_budget", "tan_budget"} <= set(
        v["abstentions"]
    )
    # a parameter at a bound counts as the structural signature too
    bound = dict(
        clean,
        pH=_residual(rmse_z=3.0, serially_structured=True),
        tan=_residual(rmse_z=2.5, serially_structured=True),
    )
    assert _classify(bound)["classification"]["label"] == "none"
    assert _classify(bound, at_bound=True)["classification"]["label"] == "structural"


def test_a_compound_case_reports_one_primary_label_and_the_rest_as_secondary():
    residuals = {ch: _residual() for ch in CHANNELS.values()}
    residuals["q_gas_stp_dry"] = _residual(
        most_explanatory="feed_fog", covariate_eta2={"feed_fog": 0.3}
    )
    v = _classify(residuals, flagged=["ph"])
    assert v["classification"]["label"] == "sensor"
    assert v["classification"]["secondary_labels"] == ["influent"]
    assert v["classification"]["confidence"] == 0.5
    assert v["classification"]["revise_influent_mapping"]
    assert v["rules"] == ["R1", "R2"]


def test_the_single_offender_needs_every_other_channel_clean():
    cfg = _cfg()
    residuals = {"a": _residual(bias_z=5.0), "b": _residual(), "c": _residual()}
    assert pipeline.single_offender(cfg, residuals, True) == "a"
    assert pipeline.single_offender(cfg, residuals, False) is None
    residuals["b"] = _residual(serially_structured=True)
    assert pipeline.single_offender(cfg, residuals, True) is None


# ------------------------------------------------------------------ 6. the runner


def test_the_runner_selects_cells_from_the_index_and_writes_the_table(
    tiny_result, tmp_path, capsys
):
    run, _, result = tiny_result
    root = run.paths.root.parent
    store = run.paths.truth.parent
    cells = select_cells(store)
    assert {c["run_id"] for c in cells} >= {run.run_id}
    assert select_cells(store, levels="0") and not select_cells(store, levels="3-5")
    assert select_cells(store, plants=["C"], tiers=["B"], scenarios=["S0-01"])
    assert main(["--dry-run", "--all", "--runs-root", str(root)]) == 0
    printed = capsys.readouterr().out
    assert run.run_id in printed and "cells" in printed
    table = tmp_path / "pilot.csv"
    row = {"run_id": run.run_id, "scenario_id": "S0-01", "final_label": result.label}
    write_table([row], table)
    write_table([{**row, "final_label": "sensor"}], table)
    lines = table.read_text().splitlines()
    assert len(lines) == 2 and lines[1].split(",")[0] == run.run_id and ",sensor," in lines[1]
