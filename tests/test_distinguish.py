"""The distinguishability analysis (docs/distinguishability.md) and its second score.

- The admissibility rule, on constructed class fits: a score of χ² plus a penalty (the
  likelihood-ratio critical value at alpha / alternatives, plus 2 ln N for a search),
  and a margin read from ``configs/eval.yaml`` (method version 3).
- The joint noise calibration (re-review of PR #25, B): with every class competing at
  once on pure noise, ``none`` stays admissible at least the declared rate; with the
  version-2 penalty (2k + 2 ln N) it does not, which reproduces the reviewer's 0.873.
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
from scipy.stats import chi2 as chi2_dist

from distinguish.analysis import (
    ClassFit,
    Series,
    _fit_sensor,
    _sensor_candidates,
    admissible,
    analyse_pair,
    calibration_end,
    chance_rate,
    class_limited,
    class_penalty,
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


def test_admissibility_is_a_penalised_margin():
    p1, p2 = class_penalty(1, 1), class_penalty(2, 1)
    assert p1 == pytest.approx(chi2_dist.ppf(1 - 0.05 / 5, 1))  # 6.63
    fits = _fits(none=(100.0, 0), state=(100.0 - p1 + 2.5, 1), sensor=(100.0 - p2 - 1.0, 2))
    # scores: none 100, state 102.5, sensor 99
    assert admissible(fits, 2.0) == ["none", "sensor"]
    assert admissible(fits, 10.0) == ["none", "sensor", "state"]
    # a failed class is never admissible, and all-failed admits nothing
    assert admissible(_fits(none=(float("inf"), 0), state=(10.0, 1)), 2.0) == ["state"]
    assert admissible(_fits(none=(float("inf"), 0)), 2.0) == []


def test_a_search_pays_two_ln_n():
    searched = ClassFit("sensor", 90.0, 2, n_candidates=300)
    assert searched.penalty == pytest.approx(class_penalty(2, 1) + 2.0 * np.log(300))
    # a 10-unit χ² gain found among 300 candidates does not beat the baseline
    fits = {"none": ClassFit("none", 100.0, 0), "sensor": searched}
    assert admissible(fits, 2.0) == ["none"]


def test_the_rule_comes_from_the_configuration():
    assert CFG.method_version == 3 and CFG.margin == 2.0 and CFG.sensitivity_margin == 10.0
    assert CFG.lr_alpha == 0.05 and CFG.n_alternatives == 5 and CFG.look_elsewhere
    assert CFG.baseline_parameters == ("Y_ac", "k_m_ac", "k_m_h2", "Y_h2")


def test_the_chance_rate_counts_a_or_the_truth():
    """Re-review item 8: a uniform guess lands in A or the truth with |A or T| / 6."""
    assert chance_rate(["none", "sensor"], ["sensor"]) == pytest.approx(2 / 6)
    assert chance_rate(["none"], ["state", "sensor"]) == pytest.approx(3 / 6)


def _noise_trial(rng: np.random.Generator) -> dict[str, ClassFit]:
    """Every class on one pure-noise record, as each class's fit sees it.

    Nine sensors (daily and weekly) around a flat baseline. A class with k continuous
    knobs gains exactly the projection of the noise onto a k-dimensional subspace (the
    linear-Gaussian surrogate of a fit near the truth); the sensor class runs its real
    closed form; an extension left out changes the prediction deterministically, so it
    gains nothing on noise.
    """
    t_daily, t_weekly = np.arange(0.0, 150.0), np.arange(0.0, 150.0, 7.0)
    series, base, z_all = [], {"t": np.arange(0.0, 200.0)}, []
    for i in range(9):
        t = t_daily if i < 4 else t_weekly
        level = 10.0 + i
        sd = np.full(t.size, 0.1 * level)
        z = rng.standard_normal(t.size)
        series.append(Series(f"s{i}", f"c{i}", t, level + sd * z, sd))
        base[f"c{i}"] = np.full(base["t"].size, level)
        z_all.append(z)
    z = np.concatenate(z_all)
    none = float(z @ z)

    def gain(k: int) -> float:
        q, _ = np.linalg.qr(rng.standard_normal((z.size, k)))
        proj = q.T @ z
        return float(proj @ proj)

    influent = [ClassFit("influent", none - gain(4), 4), ClassFit("influent", none - gain(1), 1)]
    best_influent = min(influent, key=lambda c: c.score)
    best_influent.n_candidates = 2
    structural = [ClassFit("structural", none, 0) for _ in range(4)]
    structural.append(ClassFit("structural", none - gain(1), 1))
    best_structural = min(structural, key=lambda c: c.chi2 + class_penalty(c.k, 1))
    best_structural.n_candidates = 5
    return {
        "none": ClassFit("none", none, 0),
        "sensor": _fit_sensor(series, base, CFG.sensor_onset_every_d),
        "influent": best_influent,
        "state": ClassFit("state", none - gain(1), 1),
        "parameter": ClassFit("parameter", none - gain(2), 2),
        "structural": best_structural,
    }


def test_on_noise_with_every_class_competing_none_stays_admissible():
    """Re-review of PR #25, B: the joint calibration, and the version-2 rule's shortfall."""
    from distinguish import analysis

    rng = np.random.default_rng(20260924)
    trials = [_noise_trial(rng) for _ in range(400)]
    rate = np.mean(["none" in admissible(fits, CFG.margin) for fits in trials])
    assert rate >= CFG.none_admissible_rate_min, rate

    # the version-2 rule (2k + 2 ln N) on the same trials falls short, as the reviewer found
    def aic_v2(c: ClassFit) -> float:
        return c.chi2 + 2.0 * c.k + 2.0 * np.log(c.n_candidates)

    kept = 0
    for fits in trials:
        best = min(aic_v2(c) for c in fits.values())
        kept += aic_v2(fits["none"]) - best <= CFG.margin
    assert kept / len(trials) < CFG.none_admissible_rate_min
    assert analysis._PENALTY["alpha"] == CFG.lr_alpha


def test_the_least_squares_fit_moves_from_its_start():
    """The Level-0 check found every fit stopped at nfev 1 (a zero relative step at u = 0)."""
    from distinguish.analysis import _lsq

    t = np.arange(0.0, 50.0)
    truth = np.array([0.3, -0.2])  # log multipliers
    sd = np.full(t.size, 0.01)
    series = [
        Series("a", "ca", t, np.full(t.size, 5.0 * np.exp(truth[0])), sd),
        Series("b", "cb", t, np.full(t.size, 2.0 * np.exp(truth[1])), sd),
    ]

    def make(u: np.ndarray) -> dict:
        return {
            "t": t,
            "ca": np.full(t.size, 5.0 * np.exp(u[0])),
            "cb": np.full(t.size, 2.0 * np.exp(u[1])),
        }

    u, ok, status = _lsq(series, 2, np.array([0.5, 0.5]), np.array([2.0, 2.0]), make, 30)
    assert ok, status
    np.testing.assert_allclose(u, truth, atol=1e-4)


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
    doc = {"method_version": 3, "admissible_set": ["none", "state"], "truth_admissible": False,
           "truth_representable": True, "chance_rate": 3 / 6}  # fmt: skip
    # the truth itself is never marked wrong, even when the record does not admit it
    truth = _score(tmp_path / "a", doc, "sensor")
    assert truth["attribution_exact"] is True and truth["attribution_admissible"] is True
    # an admissible non-truth answer earns the second score, not the first
    other = _score(tmp_path / "b", doc, "none")
    assert other["attribution_exact"] is False and other["attribution_admissible"] is True
    assert other["n_admissible"] == 2 and other["admissible_chance_rate"] == 0.5
    # an analysis of another method version is not read
    stale = _score(tmp_path / "f", {**doc, "method_version": 2}, "none")
    assert stale["attribution_admissible"] is None and stale["admissible_set"] is None
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


def test_one_short_cell_end_to_end(store, tiny_cell, monkeypatch):
    """A clean 30-day cell: the null is the calibrated baseline, and it is admissible."""
    from distinguish import analysis

    small = CFG.model_copy(update={"lsq_max_nfev": 3, "scalar_max_iter": 3})
    monkeypatch.setattr(analysis, "_cfg", lambda: small)
    run, scenario = tiny_cell
    docs = analyse_pair(
        [(run.run_id, run.paths.root, run.paths.truth)], classes=("none", "sensor"), log=str
    )
    doc = docs[run.run_id]
    assert doc["method_version"] == 3
    assert doc["truth_label"] == ["none"] and doc["tier"] == "B"
    assert doc["calibration_end_d"] == pytest.approx(0.75 * scenario.duration_days)
    assert set(doc["classes"]) == {"none", "sensor"}
    assert doc["classes"]["none"]["knobs"]["form"] == "calibrated_baseline"
    assert set(doc["baseline"]) - {"form"} == set(CFG.baseline_parameters)
    # a clean cell with no Level-0 table given: its own baseline gives the dispersion
    assert "own calibrated baseline" in doc["overdispersion_source"]
    assert all(v >= 1.0 for v in doc["overdispersion"].values())
    assert doc["none_admissible"]  # the Level-0 requirement (re-review, blocker A)
    assert doc["n_admissible"] == len(doc["admissible_set"]) and doc["truth_representable"]
    assert doc["chance_rate"] == pytest.approx(len(set(doc["admissible_set"]) | {"none"}) / 6)
    assert doc["classes"]["sensor"]["n_candidates"] > 1
    assert doc["classes"]["none"]["converged"] in (True, False)
