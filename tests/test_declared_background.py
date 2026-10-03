"""The declared background (decision 1 of 2026-09-30): a registry tool beside the frozen table.

What this file checks, each against something other than the code that makes the claim:

1. **Registered, versioned, logged like every tool.** ``declared_background`` is in the
   registry's table with a version from ``registry.yaml``, costs no evaluation (it is
   served on a spent evaluation budget), and every call writes one visible and one
   truth-side log line; the transport envelope validates as its output model, which is
   what the workflow-side stub does.
2. **Per plant and tier only (rule 1), with a negative control.** Two registries of
   different runs -- different seeds, budgets, a Level-8 directive -- answer identically
   for the same ``(plant, tier)``; the control is that two different ``(plant, tier)``
   answer differently, so equality is not vacuous. A ``(plant, tier)`` without a band is
   refused; Plant A's two declared community states pool into one band, and no
   ``baseline`` key exists under the bands.
3. **The committed band is what the committed record says**: ``configs/background.yaml``
   regenerates from ``reports/background/runs.jsonl`` with the driver's own aggregation,
   its procedure block is the frozen P0/P1 settings, the benchmark card's section is the
   rendered one, and the record's call logs show the declared sequence and nothing else
   (no assay, no injected failure). The band carries no run id, no library seed and no
   scenario but the clean row it is generated from.
4. **No existing tool changed.** The frozen table (``tools.impl.SPECS``) still has its
   nineteen tools with their pinned input and output fields and versions
   (``tests/tool_contracts_v1.json``, written from ``origin/main``); P0's pipeline and the
   frozen P1's committed tool list never name the new tool, and P1's tool digest is the
   one every frozen summary carries. The two-head P0 freeze test is the runtime half.
5. **The arithmetic.** The driver's per-run summary is P1's ``sim_summary`` (P0's
   declared-noise weights) and its aggregation is the plain sample statistics.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest
from pydantic import ValidationError

from scripts import declared_background as bg
from state.provenance import read_calls
from tests.test_tool_registry import linear_model
from tools import Budget, ToolArgumentError, ToolFailure, make_registry
from tools.background import TOOL_NAME, full_specs
from tools.config import BackgroundConfig, load_background, load_registry
from tools.registry import ToolConfigs
from tools.schemas import TOOL_INPUTS, TOOL_OUTPUTS, DeclaredBackgroundOutput
from tools.schemas.background import BackgroundProcedure

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "tests" / "tool_contracts_v1.json"
FROZEN_TOOLS = (
    "describe_model", "simulate", "feed_loads", "data_qc", "mass_balance", "gsa_morris",
    "gsa_sobol", "profile_likelihood", "fisher_info", "fit_lsq", "fit_de", "fit_cmaes",
    "bayes_mcmc", "filter_enkf", "filter_mhe", "residual_diag", "voi_assay", "validate",
    "request_assay",
)  # fmt: skip
SEQUENCE = (
    "registry.open", "describe_model", "feed_loads", "simulate", "mass_balance",
    "gsa_morris", "fisher_info", "fit_lsq", "simulate",
)  # fmt: skip


# ------------------------------------------------------------------ a synthetic record


def _record(
    plant: str,
    tier: str,
    seed: int,
    *,
    baseline: str | None = None,
    shift: float = 0.0,
    horizon: float = 200.0,
) -> dict[str, Any]:
    """One per-run record in the driver's shape, with numbers that depend on ``shift``."""
    sensors = {
        "A": ["gas_flow", "ph", "temperature"],
        "B": ["gas_flow", "ph", "tan", "temperature"],
        "C": ["gas_flow", "ph", "tan", "temperature", "vfa_ac"],
    }[tier]
    channels = {}
    for i, name in enumerate(sensors):
        channels[name] = {
            "channel": {"ph": "pH", "gas_flow": "q_gas_stp_dry"}.get(name, name),
            "unit": "-",
            "in_objective": name != "temperature",
            "n": 100 + i,
            "at_defaults": {"mean_z": 4.0 + shift + i, "rms_z": 7.0 + shift},
            "after_fit": {"mean_z": 1.0 + shift - i, "rms_z": 3.0 + shift},
        }
    cod = tier != "A"
    stage = plant if baseline is None else f"{plant}.{baseline}"
    return {
        "key": f"{stage}-{tier}-{seed}",
        "plant": plant,
        "baseline": baseline,
        "tier": tier,
        "seed": seed,
        "run_id": f"run_{seed:012x}",
        "horizon_d": horizon,
        "calibration_window": [0.0, 0.75 * horizon],
        "balance_window_d": 30.0,
        "sensors": sorted(sensors),
        "objective": [s for s in sensors if s != "temperature"],
        "balance": {
            "n_windows": 5,
            "n_cod_evaluable": 5 if cod else 0,
            "n_cod_inadmissible": 2 if cod else 0,
            "cod_closure_windows": [-0.1 + shift, -0.2 + shift, -0.15, -0.12, -0.13] if cod else [],
            "cod_closure_mean": -0.14 + shift if cod else None,
            "n_closure_mean": 0.3 if cod else None,
            "charge_drift": 0.1 + shift if cod else None,
            "charge_consistent": (shift == 0.0) if cod else None,
            "admissible": False,
        },
        "screening": {"morris_kept": ["Y_ac", "k_dec_X_ac"], "approved": ["Y_ac"]},
        "fit": {
            "parameters": ["Y_ac", "k_dec_X_ac"] if shift == 0.0 else ["Y_ac"],
            "optimum": {"Y_ac": 0.9},
            "chi2": 1.0e4,
            "n_data": 300,
            "at_bound": [] if shift == 0.0 else ["Y_ac"],
            "converged": True,
            "message": "",
            "n_evaluations": 30,
        },
        "channels": channels,
        "evaluations_used": 72,
        "n_calls": 8,
        "wall_s": 1.0,
        "git_commit": "test",
    }


SYNTHETIC = [
    _record("B", "B", 1),
    _record("B", "B", 2, shift=0.5),
    _record("B", "A", 1),
    _record("B", "A", 2, shift=0.5),
    _record("C", "B", 1, shift=-1.0),
    _record("C", "B", 2, shift=-1.5),
    _record("A", "A", 1, baseline="adapted", horizon=365.0),
    _record("A", "A", 2, baseline="unadapted", shift=2.0, horizon=365.0),
]


@pytest.fixture(scope="module")
def synthetic_config(tmp_path_factory) -> BackgroundConfig:
    """A configuration rendered and re-read the way ``publish`` writes it."""
    bands = bg.aggregate(SYNTHETIC)
    text = bg.render_config(
        bands,
        {
            "git_commit": "test",
            "computed": "2026-09-30",
            "record": "synthetic",
            "n_runs": len(SYNTHETIC),
            "evaluations": 8 * 72,
            "status": "PROVISIONAL",
            "seeds": [1, 2],
        },
    )
    path = tmp_path_factory.mktemp("bg") / "background.yaml"
    path.write_text(text, encoding="utf-8")
    return load_background(path)


def _registry(tmp_path, config: BackgroundConfig, *, seed=7, budget=None, failures=()):
    configs = ToolConfigs()
    configs.background = config  # the cached property, set for the test
    run_dir = tmp_path / "runs" / f"run_{seed}"
    truth_dir = tmp_path / "truth_store" / f"run_{seed}"
    reg = make_registry(
        budget=budget or Budget(1000, 60.0, 4),
        seed=seed,
        run_dir=run_dir,
        truth_log_dir=truth_dir,
        tool_failures=failures,
        models={"linear": linear_model()},
        configs=configs,
    )
    return reg, run_dir, truth_dir


# ------------------------------------------------------------------ 1. registered and logged


def test_the_tool_is_registered_beside_the_frozen_table_versioned_and_costs_nothing(
    tmp_path, synthetic_config
):
    from tools.impl import SPECS

    assert TOOL_NAME not in SPECS and set(SPECS) == set(FROZEN_TOOLS)
    table = full_specs()
    assert set(table) == set(FROZEN_TOOLS) | {TOOL_NAME}
    assert TOOL_NAME in TOOL_INPUTS and TOOL_OUTPUTS[TOOL_NAME] is DeclaredBackgroundOutput
    assert load_registry().tool_versions[TOOL_NAME] == "1.0"
    with pytest.raises(ValueError, match="already"):
        full_specs(table)

    # served on a spent evaluation budget: the tool costs no evaluation
    reg, run_dir, truth_dir = _registry(tmp_path, synthetic_config, budget=Budget(1, 60.0, 0))
    reg.call("simulate", model="linear")
    assert reg.remaining().simulator_evals == 0
    out = reg.call(TOOL_NAME, plant="B", tier="B")
    assert isinstance(out, DeclaredBackgroundOutput)
    assert out.plant == "B" and out.tier == "B" and out.n_runs == 2
    assert reg.describe(TOOL_NAME)["version"] == "1.0"
    assert "plant" in reg.describe(TOOL_NAME)["input_schema"]["properties"]

    # logged like every tool: one visible line (no runtime) and one truth-side line
    visible, full = read_calls(run_dir)[-1], read_calls(truth_dir)[-1]
    assert visible.name == TOOL_NAME and visible.version == "1.0" and visible.outcome == "ok"
    assert visible.runtime_s is None and visible.t_utc is None
    assert full.name == TOOL_NAME and full.n_evaluations == 0 and full.runtime_s is not None
    assert reg.last is not None and reg.last.n_evaluations == 0

    # the transport envelope is what the stub validates
    envelope = reg.call_json(TOOL_NAME, {"plant": "B", "tier": "A"})
    assert envelope["outcome"] == "ok"
    again = DeclaredBackgroundOutput.model_validate(envelope["output"])
    assert again.tier == "A" and again.cod_closure is None  # tier A has no COD balance
    assert again.units["mean_z"].startswith("-")


# ------------------------------------------------------------------ 2. per plant and tier only


def test_the_band_is_a_pure_function_of_plant_and_tier_with_a_negative_control(
    tmp_path, synthetic_config
):
    reg1, _, _ = _registry(tmp_path / "one", synthetic_config, seed=1)
    reg2, _, _ = _registry(
        tmp_path / "two",
        synthetic_config,
        seed=99,
        budget=Budget(5, 1.0, 0),
        failures=[ToolFailure("bayes_mcmc", 1.0)],
    )
    same = [r.call(TOOL_NAME, plant="B", tier="B").model_dump(mode="json") for r in (reg1, reg2)]
    assert same[0] == same[1]
    # the negative control: the band can tell plants and tiers apart
    other_tier = reg1.call(TOOL_NAME, plant="B", tier="A").model_dump(mode="json")
    other_plant = reg1.call(TOOL_NAME, plant="C", tier="B").model_dump(mode="json")
    assert other_tier != same[0] and other_plant != same[0]
    assert other_plant["channels"]["gas_flow"] != same[0]["channels"]["gas_flow"]
    # nothing but plant and tier chooses the answer: a run of another cell is the same call
    assert same[0]["procedure"]["seeds"] == list(bg.SEEDS)
    # a (plant, tier) without a band is refused, and a plant that does not exist too
    with pytest.raises(ToolArgumentError, match="no declared background"):
        reg1.call(TOOL_NAME, plant="C", tier="C")
    with pytest.raises(ToolArgumentError):
        reg1.call(TOOL_NAME, plant="D", tier="A")


def test_plant_a_pools_its_two_declared_states_into_one_band_without_naming_them():
    bands = bg.aggregate(SYNTHETIC)
    band = bands["A"]["A"]
    assert band["n_runs"] == 2 and band["horizon_d"] == 365.0
    gas = band["channels"]["gas_flow"]["at_defaults"]["mean_z"]
    assert gas["min"] == 4.0 and gas["max"] == 6.0 and gas["mean"] == 5.0
    text = bg.render_config(
        bands,
        {
            "git_commit": "t",
            "computed": "2026-09-30",
            "record": "s",
            "n_runs": 8,
            "evaluations": 1,
            "status": "PROVISIONAL",
            "seeds": [1, 2],
        },
    )
    body = text.split("bands:", 1)[1]
    assert "baseline" not in body and "adapted" not in body
    assert "seed" not in body and "run_" not in body
    # the keys under bands are plants and tiers, and nothing else is accepted
    with pytest.raises(ValidationError, match="plant id"):
        BackgroundConfig.model_validate(
            {
                "version": 1,
                "procedure": bg.procedure_settings(),
                "provenance": {
                    "git_commit": "t",
                    "computed": "d",
                    "record": "r",
                    "n_runs": 1,
                    "evaluations": 0,
                    "status": "PROVISIONAL",
                    "seeds": [1],
                },
                "bands": {"S0-01": {"A": bands["A"]["A"]}},
            }
        )


# ------------------------------------------------------------------ 5. the arithmetic


def test_the_aggregation_is_the_plain_sample_statistics_and_refuses_a_mixed_record():
    bands = bg.aggregate(SYNTHETIC)
    bb = bands["B"]["B"]
    assert bb["n_runs"] == 2
    closure = bb["cod_closure"]
    assert closure["n"] == 2 and closure["min"] == -0.14 and closure["max"] == 0.36
    assert closure["mean"] == pytest.approx(0.11, rel=1e-5)
    assert closure["sd"] == pytest.approx(np.std([-0.14, 0.36], ddof=1), rel=1e-5)
    assert bb["cod_closure_windows"]["n"] == 10
    # the worst window keeps its sign and is the largest |closure| of each run
    assert bb["cod_closure_worst"]["min"] == -0.2 and bb["cod_closure_worst"]["max"] == 0.4
    assert bg.worst_window({"balance": {"cod_closure_windows": [0.1, -0.3, 0.25]}}) == -0.3
    assert bg.worst_window({"balance": {"cod_closure_windows": []}}) is None
    assert bands["B"]["A"]["cod_closure_worst"] is None
    assert bb["n_cod_inadmissible"] == {"n": 2, "mean": 2.0, "min": 2, "max": 2}
    assert bb["charge_consistent_fraction"] == 0.5
    assert bb["fitted_parameters"] == {"Y_ac": 2, "k_dec_X_ac": 1}
    assert bb["n_fitted"] == {"n": 2, "mean": 1.5, "min": 1, "max": 2}
    assert bb["fit_at_bound_fraction"] == 0.5
    ph = bb["channels"]["ph"]
    assert ph["after_fit"]["rms_z"] == {
        "n": 2,
        "mean": 3.25,
        "sd": pytest.approx(0.353553, rel=1e-5),
        "min": 3.0,
        "max": 3.5,
    }
    assert ph["n_samples"] == {"n": 2, "mean": 101.0, "min": 101, "max": 101}
    assert ph["in_objective"] and not bb["channels"]["temperature"]["in_objective"]
    # a tier with no COD balance reports None, not a zero
    ba = bands["B"]["A"]
    assert ba["cod_closure"] is None and ba["n_cod_inadmissible"] is None
    assert ba["charge_consistent_fraction"] is None and ba["n_closure"] is None
    # one run below two: no sd
    single = bg.aggregate([_record("C", "A", 1)])["C"]["A"]
    assert single["channels"]["gas_flow"]["at_defaults"]["mean_z"]["sd"] is None
    # the runs of a (plant, tier) must be one record: horizons or sensors that differ refuse
    with pytest.raises(ValueError, match="horizon"):
        bg.aggregate([_record("B", "B", 1), _record("B", "B", 2, horizon=210.0)])
    mixed = _record("B", "B", 2)
    mixed["sensors"] = sorted([*mixed["sensors"], "cod_total"])
    with pytest.raises(ValueError, match="sensor set"):
        bg.aggregate([_record("B", "B", 1), mixed])
    assert bg._stat([]) is None and bg._stat([None, float("nan")]) is None


def test_the_per_run_summary_is_p1s_arithmetic_on_p0s_declared_noise_weights():
    t = np.arange(0.0, 10.0)
    value = np.array([10.0, 11.0, np.nan, 12.0, 9.0, 10.5, 30.0, 10.0, 10.0, 10.0])
    raw = {
        "channel": "y",
        "unit": "u",
        "sample_t_d": t,
        "value": [None if np.isnan(v) else v for v in value],
    }
    s = bg._Series(
        "y_sensor", raw, cv=0.05, sd_abs=0.2, cal={"min_relative_sd": 0.02, "sd_floor_abs": 1e-6}
    )
    finite = value[np.isfinite(value)]
    floor = 0.02 * float(np.median(np.abs(finite)))
    expected_sd = np.maximum(np.sqrt((0.05 * np.abs(np.nan_to_num(value))) ** 2 + 0.2**2), floor)
    np.testing.assert_allclose(s.sd, expected_sd)

    class Sim:
        t = np.arange(0.0, 10.0)
        outputs: ClassVar[dict] = {"y": np.full(10, 10.0)}

    out = s.summary(Sim(), (0.0, 5.0))
    m = np.isfinite(value) & (t <= 5.0)
    z = (value[m] - 10.0) / expected_sd[m]
    assert out["n"] == int(m.sum()) == 5
    assert out["mean_z"] == pytest.approx(float(z.mean()), rel=1e-5)
    assert out["rms_z"] == pytest.approx(float(np.sqrt(np.mean(z**2))), rel=1e-5)
    assert s.summary(Sim(), (100.0, 200.0)) is None  # no sample in the window

    class Other:
        t = np.arange(0.0, 10.0)
        outputs: ClassVar[dict] = {"z": np.zeros(10)}

    assert s.summary(Other(), (0.0, 5.0)) is None  # the model does not output the channel


def test_the_background_seeds_are_the_benchmarks_own_and_the_runs_are_ordered_dev_first():
    from sim.run.matrix import load_library

    library_seeds = {s.seed for s in load_library().values()}
    assert not set(bg.SEEDS) & library_seeds
    runs = bg.all_runs()
    # ten seeds per truth group, fixed by the lead's ruling of 2026-09-30
    assert tuple(range(900001, 900011)) == bg.SEEDS
    assert len(runs) == 120 and len({r.key for r in runs}) == 120
    # the first three seeds of every truth group run first, the development combinations
    # first among them
    head = runs[:36]
    assert {r.seed for r in head} == set(bg.SEEDS[: bg.FIRST_SEEDS])
    first = [(r.plant, r.baseline, r.tier) for r in head[: len(bg.DEV_FIRST) * bg.FIRST_SEEDS]]
    assert set(first) == set(bg.DEV_FIRST)
    assert bg.PLANT_BASELINES["A"] == ("adapted", "unadapted")
    settings = BackgroundProcedure.model_validate(bg.procedure_settings())
    assert settings.subset_max == 4 and settings.subset_min == 2 and settings.lsq_starts == 1
    assert settings.morris_trajectories == 4 and settings.morris_seed == 101


# ------------------------------------------------------------------ 4. nothing existing changed


def test_no_existing_tool_changed_and_neither_p0_nor_the_frozen_p1_calls_the_new_one():
    from tools.impl import SPECS
    from tools.llm import tools_digest
    from workflows.p1_single_agent.agent import tool_specs

    pinned = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    versions = load_registry().tool_versions
    assert set(pinned) == set(FROZEN_TOOLS) == set(SPECS)
    for name, contract in pinned.items():
        spec = SPECS[name]
        assert versions[name] == contract["version"], name
        assert sorted(spec.input_model.model_fields) == contract["input"], name
        assert sorted(spec.output_model.model_fields) == contract["output"], name
        assert (spec.failure is not None) == contract["has_failure_payload"], name
        assert (spec.assay_cost is not None) == contract["has_assay_cost"], name
    # P0's pipeline and P1's committed tool list never name it
    for path in (
        REPO / "workflows" / "p0_scripted" / "pipeline.py",
        REPO / "workflows" / "p1_single_agent" / "agent.py",
        REPO / "configs" / "workflows" / "p0.yaml",
    ):
        assert TOOL_NAME not in path.read_text(encoding="utf-8"), path
    names = {s["name"] for s in tool_specs()}
    assert TOOL_NAME not in names
    # the frozen P1's tool digest is the one every frozen-arm summary carries
    digest = tools_digest(tool_specs())
    summaries = sorted((REPO / "reports" / "p1_pilot" / "summaries").glob("*.json"))
    carried = {json.loads(p.read_text(encoding="utf-8")).get("tools_sha256") for p in summaries} - {
        None
    }
    assert carried == {digest}, (carried, digest)


# ------------------------------------------------------------------ 3. the committed band


def _committed():
    if not bg.CONFIG_FILE.is_file() or not bg.RECORD_FILE.is_file():
        pytest.fail("configs/background.yaml and reports/background/runs.jsonl must be committed")
    return load_background(), bg.read_record()


def test_the_committed_band_regenerates_from_the_committed_record():
    config, records = _committed()
    expected = BackgroundConfig.model_validate(
        {
            "version": config.version,
            "procedure": bg.procedure_settings(),
            "provenance": config.provenance.model_dump(),
            "bands": bg.aggregate(records),
        }
    )
    assert config.bands == expected.bands
    assert config.procedure == expected.procedure
    assert config.provenance.n_runs == len(records)
    assert config.provenance.evaluations == sum(int(r["evaluations_used"]) for r in records)
    assert config.provenance.record == "reports/background/runs.jsonl"
    # every run of every published seed, once; only complete seeds are published
    seeds = list(config.provenance.seeds)
    assert seeds == bg.complete_seeds(records) and seeds == list(bg.SEEDS[: len(seeds)])
    keys = {r["key"] for r in records}
    assert keys == {r.key for r in bg.all_runs() if r.seed in seeds}
    # FINAL exactly when all ten declared seeds are in
    assert (config.provenance.status == "FINAL") == (seeds == list(bg.SEEDS))
    # the csv beside it lists the same runs
    csv_keys = {
        line.split(",")[0]
        for line in (bg.REPORT_DIR / "runs.csv").read_text(encoding="utf-8").splitlines()[1:]
    }
    assert csv_keys == keys


def test_the_committed_band_is_per_plant_and_tier_and_carries_nothing_per_cell():
    from sim.observation import load_observation_config
    from sim.run.matrix import load_library

    config, _records = _committed()
    text = bg.CONFIG_FILE.read_text(encoding="utf-8")
    assert set(config.bands) == {"A", "B", "C"}
    for plant, tiers in config.bands.items():
        assert set(tiers) == {"A", "B", "C"}, plant
        n = {b.n_runs for b in tiers.values()}
        assert len(n) == 1, (plant, n)  # every tier of a plant shares its truth groups
        expected = len(config.provenance.seeds) * len(bg.PLANT_BASELINES[plant])
        assert n == {expected}, (plant, n)
    assert not re.findall(r"run_[0-9a-f]{12}", text)
    assert set(re.findall(r"S\d-\d\d", text)) == {bg.SCENARIO_ID}
    assert "truth" not in text and "baseline:" not in text.split("bands:", 1)[1]
    body = text.split("bands:", 1)[1]
    for seed in {s.seed for s in load_library().values()}:
        # as a whole number, not a digit run inside a decimal (0.231031 is not seed 1031)
        assert not re.search(rf"(?<![\d.]){seed}(?![\d])", body), seed

    def keys_of(node: Any):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys_of(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys_of(v)

    band_keys = set(
        keys_of({p: {t: b.model_dump() for t, b in ts.items()} for p, ts in config.bands.items()})
    )
    assert not band_keys & {"baseline", "seed", "run_id", "scenario_id", "scenario", "key"}
    # every band describes exactly the tier's declared sensors
    tiers = load_observation_config().tiers
    for plant, per_tier in config.bands.items():
        for tier, band in per_tier.items():
            assert set(band.channels) == set(tiers[tier].sensors), (plant, tier)
            for name, ch in band.channels.items():
                assert ch.in_objective == (
                    name != "temperature" and name in config.procedure.objective_channels
                )
                assert ch.at_defaults.rms_z.n == band.n_runs == ch.after_fit.rms_z.n
    # the record itself names only visible quantities and the driver's own keys
    record_text = bg.RECORD_FILE.read_text(encoding="utf-8")
    for token in ("truth", "faults", "salt", "K_I_nh3_true", "correct_conclusion"):
        # as a whole word: "faults" inside "at_defaults" is not a fault plan
        assert not re.search(rf"(?<![A-Za-z_]){token}(?![A-Za-z_])", record_text), token


def test_the_committed_record_shows_the_declared_call_sequence_and_nothing_else():
    _, records = _committed()
    calls_dir = bg.REPORT_DIR / "calls"
    for rec in records:
        lines = [
            json.loads(x)
            for x in (calls_dir / f"{rec['key']}.calls.jsonl").read_text("utf-8").splitlines()
            if x.strip()
        ]
        names = tuple(x["name"] for x in lines)
        # the harness's generation calls come first; each registry.open starts one attempt.
        # The log is append-only, so attempts that were cut off (a container restart) or
        # discarded (the first, Fisher-only procedure) stay in it; the record is the LAST
        # attempt, which must be the declared sequence, every call ok
        opens = [i for i, n in enumerate(names) if n == "registry.open"]
        assert opens, rec["key"]
        start = opens[-1]
        assert names[start:] == SEQUENCE, rec["key"]
        assert all(x["outcome"] == "ok" for x in lines[start:]), rec["key"]
        assert all(n != "request_assay" for n in names), rec["key"]  # no assay, any attempt
        assert all("t_utc" not in x and "runtime_s" not in x for x in lines), rec["key"]
        assert rec["n_calls"] == len(SEQUENCE) - 1
        assert rec["evaluations_used"] <= bg.BUDGET["simulator_evals"]
        assert rec["fit"]["parameters"] == rec["screening"]["approved"]
        assert set(rec["screening"]["approved"]) <= set(rec["screening"]["morris_kept"])
        assert len(rec["screening"]["morris_kept"]) <= 4
        assert 2 <= len(rec["fit"]["parameters"]) <= 4
        assert rec["balance"]["n_windows"] == int(
            rec["calibration_window"][1] // rec["balance_window_d"]
        )


def test_the_benchmark_cards_section_is_the_rendered_one():
    config, _ = _committed()
    text = bg.CARD_FILE.read_text(encoding="utf-8")
    assert bg.CARD_BEGIN in text and bg.CARD_END in text
    section = text.split(bg.CARD_BEGIN, 1)[1].split(bg.CARD_END, 1)[0].strip("\n")
    assert section == bg.render_card_section(config)


def test_each_plant_a_state_has_its_own_store_and_a_shared_run_id_is_refused(tmp_path):
    """Plant A's two states never share a run directory (the bug found 2026-10-02).

    A run id is not keyed by the declared state, so the two states shared one run directory
    in one store and the second generation overwrote the first.
    """
    runs = {r.key: r for r in bg.all_runs()}
    adapted, unadapted = runs["A.adapted-B-900001"], runs["A.unadapted-B-900001"]
    plant_b, plant_c = runs["B-B-900001"], runs["C-B-900001"]
    roots = {bg.runs_root(tmp_path, r) for r in (adapted, unadapted, plant_b)}
    assert len(roots) == 3  # one store per Plant A state; B and C share theirs
    assert bg.runs_root(tmp_path, plant_b) == bg.runs_root(tmp_path, plant_c)
    # the truth store is the run store's sibling, so separate stores mean separate truth
    from sim.run.layout import truth_store_for

    assert truth_store_for(bg.runs_root(tmp_path, adapted)) != truth_store_for(
        bg.runs_root(tmp_path, unadapted)
    )
    # the guard: two runs of one stage may not share an id; two stages may
    with pytest.raises(RuntimeError, match="share run id"):
        bg.check_index({adapted.key: "run_x", runs["A.adapted-C-900001"].key: "run_x"})
    bg.check_index({adapted.key: "run_x", unadapted.key: "run_x"})
    assert bg.default_baseline("A") == "adapted" and bg.default_baseline("B") is None


def test_placement_is_the_published_envelope_with_no_margin(synthetic_config):
    band = synthetic_config.band("B", "B")
    inside = _record("B", "B", 9)  # the first synthetic run: on the envelope's edge
    rows = {r["statistic"]: r for r in bg.placement(inside, band)}
    assert rows["cod_closure"]["inside"] is True
    assert rows["gas_flow.after_fit.rms_z"]["inside"] is True
    # just past the envelope is outside: no margin of any size is added
    outside = _record("B", "B", 9, shift=0.5000001)
    rows = {r["statistic"]: r for r in bg.placement(outside, band)}
    assert rows["cod_closure"]["inside"] is False
    assert rows["cod_closure"]["band_max"] == band.cod_closure.max
    # a channel the band does not carry is reported, not judged
    extra = _record("B", "B", 9)
    extra["channels"]["h2_offgas"] = extra["channels"]["ph"]
    rows = {r["statistic"]: r for r in bg.placement(extra, band)}
    assert rows["h2_offgas.after_fit.mean_z"]["inside"] is None
    # a tier with no COD balance reports no closure judgement
    rows = {
        r["statistic"]: r
        for r in bg.placement(_record("B", "A", 9), synthetic_config.band("B", "A"))
    }
    assert rows["cod_closure"]["inside"] is None and "n_cod_inadmissible" not in rows
    assert set(bg.DEV_CELLS) == {("S0-01", "B", "A"), ("S0-01", "B", "B"),
                                 ("S0-01", "B", "C"), ("S1-01", "B", "B")}  # fmt: skip


def test_the_committed_placement_is_against_the_committed_band():
    config, _ = _committed()
    if not bg.DEV_FILE.is_file():
        # the cells are placed when the band is final (the lead's ruling); not before
        assert config.provenance.status == "PROVISIONAL"
        return
    placed = json.loads(bg.DEV_FILE.read_text(encoding="utf-8"))
    assert {c["cell"] for c in placed["cells"]} == {f"{s} {p}/{t}" for s, p, t in bg.DEV_CELLS}
    for cell in placed["cells"]:
        assert cell["band_seeds"] == list(config.provenance.seeds)
        assert cell["band_status"] == config.provenance.status
        plant, tier = cell["cell"].split()[1].split("/")
        band = config.band(plant, tier)
        for r in cell["rows"]:
            if r["inside"] is None:
                continue
            assert r["inside"] == (r["band_min"] <= r["value"] <= r["band_max"])
        assert cell["n_outside"] == sum(1 for r in cell["rows"] if r["inside"] is False)
        assert band is not None
