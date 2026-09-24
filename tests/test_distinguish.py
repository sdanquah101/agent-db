"""The distinguishability analysis (docs/distinguishability.md) and its second score.

- The admissibility rule, on constructed class fits: AIC with the look-elsewhere
  penalty, not χ², and a margin read from ``configs/eval.yaml``.
- The look-elsewhere calibration (review of PR #25, item 1): on pure white noise around
  the defaults, the sensor class's best-of-N search pushes ``none`` out of the admissible
  set no more often than the declared rate allows. Without the penalty it does so most
  of the time, which reproduces the reviewer's finding.
- The sensor class's closed form recovers a planted scale step.
- The hold-out is never read.
- The truth's own form: the change-point model with nothing changed equals the plain
  fitted model, and an unrepresentable truth gets a null admissible score.
- The evaluator's second score only ever adds credit. It is judged against A plus the truth,
  sits beside ``attribution_exact`` (true, false and absent cases), and moves no other
  column.
- No workflow may import the package, by import or by string (the rule-1 checker, with
  negative controls).
- One short cell end to end.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from distinguish.analysis import (
    ClassFit,
    Series,
    _fit_sensor,
    _sensor_candidates,
    admissible,
    analyse_pair,
    calibration_end,
    class_limited,
    load_series,
    truth_representable,
)
from eval.config import load_eval_config
from eval.records import load_records
from eval.score import score_records
from tests.eval_support import build_run, minimal_state
from tests.test_truth_isolation import find_truth_references

CFG = load_eval_config().distinguishability


def _fits(**chi2_k: tuple[float, int]) -> dict[str, ClassFit]:
    return {lab: ClassFit(lab, c, k) for lab, (c, k) in chi2_k.items()}


def test_admissibility_is_an_aic_margin():
    fits = _fits(none=(100.0, 0), sensor=(97.0, 2), state=(101.5, 1), parameter=(90.0, 6))
    # AIC: none 100, sensor 101, state 103.5, parameter 102
    assert admissible(fits, 2.0) == ["none", "sensor", "parameter"]
    assert admissible(fits, 10.0) == ["none", "sensor", "state", "parameter"]
    # more knobs do not buy admission: a lower χ² with a larger k can still be out
    assert admissible(_fits(none=(50.0, 0), parameter=(47.0, 6)), 2.0) == ["none"]
    # a failed class is never admissible, and all-failed admits nothing
    assert admissible(_fits(none=(float("inf"), 0), state=(10.0, 1)), 2.0) == ["state"]
    assert admissible(_fits(none=(float("inf"), 0)), 2.0) == []


def test_a_search_pays_two_ln_n():
    searched = ClassFit("sensor", 90.0, 2, n_candidates=300)
    assert searched.search_penalty == pytest.approx(2.0 * np.log(300))
    assert searched.aic == pytest.approx(90.0 + 4.0 + 2.0 * np.log(300))
    # a 10-unit χ² gain found among 300 candidates does not beat the defaults
    fits = {"none": ClassFit("none", 100.0, 0), "sensor": searched}
    assert admissible(fits, 2.0) == ["none"]


def test_the_margins_come_from_the_configuration():
    assert CFG.margin == 2.0 and CFG.sensitivity_margin == 10.0 and CFG.look_elsewhere


def _white_noise(rng: np.random.Generator) -> tuple[list[Series], dict, float]:
    """Nine sensors, daily or weekly, pure noise around a flat default prediction."""
    t_daily, t_weekly = np.arange(0.0, 150.0), np.arange(0.0, 150.0, 7.0)
    series, base, chi2 = [], {"t": np.arange(0.0, 200.0)}, 0.0
    for i in range(9):
        t = t_daily if i < 4 else t_weekly
        level = 10.0 + i
        sd = np.full(t.size, 0.1 * level)
        z = rng.standard_normal(t.size)
        series.append(Series(f"s{i}", f"c{i}", t, level + sd * z, sd))
        base[f"c{i}"] = np.full(base["t"].size, level)
        chi2 += float(z @ z)
    return series, base, chi2


def test_on_white_noise_none_stays_admissible_at_the_declared_rate():
    """Review of PR #25, item 1: the look-elsewhere effect, measured and corrected."""
    from distinguish import analysis

    rng = np.random.default_rng(20260924)
    trials = [_white_noise(rng) for _ in range(300)]

    def rate(look_elsewhere: bool) -> float:
        analysis._LOOK_ELSEWHERE[0] = look_elsewhere
        kept = 0
        for series, base, chi2 in trials:
            fits = {
                "none": ClassFit("none", chi2, 0),
                "sensor": _fit_sensor(series, base, CFG.sensor_onset_every_d),
            }
            kept += "none" in admissible(fits, CFG.margin)
        return kept / len(trials)

    try:
        without, with_penalty = rate(False), rate(True)
    finally:
        analysis._LOOK_ELSEWHERE[0] = True
    assert without < 0.5  # the reviewer's finding reproduces: the search wins on noise
    assert with_penalty >= CFG.none_admissible_rate_min


def test_class_limits_are_declared_per_fault_type():
    assert truth_representable([{"type": "hydrolysis_regime_change"}]) == (True, [])
    assert truth_representable([{"type": "moisture_drift"}]) == (
        False,
        ["a per-day solids change"],
    )
    assert class_limited([{"type": "unrecorded_delivery"}, {"type": "ph_electrode_drift"}]) == []


def test_the_sensor_class_recovers_a_planted_scale_step():
    t = np.arange(0.0, 100.0)
    p = np.full(t.size, 10.0)
    y = p.copy()
    y[t >= 40.0] *= 1.3
    s = Series("gas_flow", "q_gas_stp_dry", t, y, np.full(t.size, 0.1))
    chi2, knobs = min(_sensor_candidates(s, p, 10.0), key=lambda c: c[0])
    assert knobs["kind"] == "scale_step" and knobs["onset_d"] == 40.0
    assert abs(knobs["a"] - 0.3) < 1e-9 and chi2 < 1e-12


def test_the_holdout_is_never_read(tiny_cell):
    run, scenario = tiny_cell
    end = calibration_end(scenario.duration_days)
    assert end == pytest.approx(0.75 * scenario.duration_days)
    series = load_series(run.paths.root / "observations" / "sensors.json", end)
    assert series and all(float(s.t.max()) <= end for s in series)
    everything = load_series(run.paths.root / "observations" / "sensors.json", 1e9)
    assert max(float(s.t.max()) for s in everything) > end


def test_the_change_point_model_with_nothing_changed_is_the_fitted_model(tiny_cell):
    from distinguish.analysis import Simulator
    from sim.run.artifacts import read_feed_log

    run, scenario = tiny_cell
    params = json.loads((run.paths.truth / "parameters.json").read_text())
    simr = Simulator(
        "C",
        read_feed_log(run.paths.root / "observations" / "feed_log.csv"),
        params["fitted_extensions"],
        scenario.duration_days,
    )
    plain = simr.run(("plain",), simr.model)
    split = simr.run(("split",), lambda: simr.model(onset_d=scenario.duration_days / 2))
    assert plain is not None and split is not None
    for name in ("q_gas_stp_dry", "pH", "ch4_fraction"):
        np.testing.assert_allclose(split[name], plain[name], rtol=2e-3, atol=1e-6)


def _score(tmp_path: Path, admissible_doc: dict | None, label: str) -> dict:
    state = minimal_state("run_000000000001")
    state["final"]["label"] = label
    runs, store = build_run(tmp_path, truth_label=("sensor",), state=state)
    if admissible_doc is not None:
        (store / "run_000000000001" / "admissible.json").write_text(json.dumps(admissible_doc))
    return score_records(load_records("run_000000000001", "p0", runs_root=runs, truth_store=store))


def _others(row: dict) -> dict:
    return {k: v for k, v in row.items() if "admissible" not in k and "representable" not in k}


def test_the_second_score_only_adds_credit(tmp_path: Path):
    doc = {"admissible_set": ["none", "state"], "truth_admissible": False,
           "truth_representable": True}  # fmt: skip
    # the truth itself is never marked wrong, even when the record does not admit it
    truth = _score(tmp_path / "a", doc, "sensor")
    assert truth["attribution_exact"] is True and truth["attribution_admissible"] is True
    # an admissible non-truth answer earns the second score, not the first
    other = _score(tmp_path / "b", doc, "none")
    assert other["attribution_exact"] is False and other["attribution_admissible"] is True
    assert other["n_admissible"] == 2 and other["admissible_chance_rate"] == 0.5
    wrong = _score(tmp_path / "c", doc, "parameter")
    assert wrong["attribution_admissible"] is False
    # an unrepresentable truth gives a null score, never a credit
    limited = _score(tmp_path / "d", {**doc, "truth_representable": False}, "none")
    assert limited["attribution_admissible"] is None and limited["truth_representable"] is False
    # without the analysis the columns are None, and nothing else moves
    absent = _score(tmp_path / "e", None, "none")
    assert absent["attribution_admissible"] is None and absent["admissible_set"] is None
    assert _others(other) == _others(absent)


def test_no_workflow_may_import_the_analysis(tmp_path: Path):
    for text in (
        "import distinguish\n",
        "from distinguish.analysis import admissible\n",
        "import importlib\nm = importlib.import_module('distinguish.analysis')\n",
    ):
        bad = tmp_path / "wf.py"
        bad.write_text(text)
        assert find_truth_references(bad), text  # negative control: it is caught
    for module in (Path(__file__).resolve().parents[1] / "workflows").rglob("*.py"):
        assert find_truth_references(module) == [], module


def test_one_short_cell_end_to_end(store, tiny_cell):
    run, scenario = tiny_cell
    docs = analyse_pair(
        [(run.run_id, run.paths.root, run.paths.truth)], classes=("none", "sensor"), log=str
    )
    doc = docs[run.run_id]
    assert doc["truth_label"] == ["none"] and doc["tier"] == "B"
    assert doc["calibration_end_d"] == pytest.approx(0.75 * scenario.duration_days)
    assert set(doc["classes"]) == {"none", "sensor"}
    assert doc["simulations"] == 1  # the sensor class reuses the default prediction
    assert doc["admissible_set"] and set(doc["admissible_set"]) <= {"none", "sensor"}
    assert doc["n_admissible"] == len(doc["admissible_set"]) and doc["truth_representable"]
    assert doc["classes"]["sensor"]["n_candidates"] > 1
    assert doc["classes"]["none"]["chi2"] is not None and doc["n_samples"] > 0
