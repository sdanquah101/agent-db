"""The distinguishability analysis (docs/distinguishability.md) and its second score.

- The admissibility rule, on constructed class fits: AIC, not χ², and a margin.
- The sensor class's closed form recovers a planted scale step.
- The evaluator adds the admissible columns beside the exact ones: when the analysis ran
  (true and false cases) and ``None`` when it did not, with every other column unchanged.
- No workflow may import the package (the rule-1 checker, with a negative control).
- One short cell end to end, with the two classes that need no fit beyond one simulation.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from distinguish.analysis import (
    ClassFit,
    Series,
    _sensor_candidates,
    admissible,
    analyse_pair,
    class_limited,
)
from eval.records import load_records
from eval.score import score_records
from tests.eval_support import build_run, minimal_state
from tests.test_truth_isolation import find_truth_references


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


def test_class_limits_are_declared_per_fault_type():
    assert class_limited([{"type": "hydrolysis_regime_change"}]) == [
        "a mid-record parameter change"
    ]
    assert class_limited([{"type": "unrecorded_delivery"}, {"type": "sensor_drift"}]) == []


def test_the_sensor_class_recovers_a_planted_scale_step():
    t = np.arange(0.0, 100.0)
    p = np.full(t.size, 10.0)
    y = p.copy()
    y[t >= 40.0] *= 1.3
    s = Series("gas_flow", "q_gas_stp_dry", t, y, np.full(t.size, 0.1))
    chi2, knobs = min(_sensor_candidates(s, p), key=lambda c: c[0])
    assert knobs["kind"] == "scale_step" and knobs["onset_d"] == 40.0
    assert abs(knobs["a"] - 0.3) < 1e-9 and chi2 < 1e-12


def _score(tmp_path: Path, admissible_doc: dict | None, label: str) -> dict:
    state = minimal_state("run_000000000001")
    state["final"]["label"] = label
    runs, store = build_run(tmp_path, truth_label=("sensor",), state=state)
    if admissible_doc is not None:
        (store / "run_000000000001" / "admissible.json").write_text(json.dumps(admissible_doc))
    return score_records(load_records("run_000000000001", "p0", runs_root=runs, truth_store=store))


def test_the_evaluator_reports_the_second_score_beside_the_exact_one(tmp_path: Path):
    doc = {"admissible_set": ["none", "sensor"], "truth_admissible": True}
    right = _score(tmp_path / "a", doc, "none")
    assert right["attribution_exact"] is False  # the truth is `sensor`
    assert right["attribution_admissible"] is True  # but `none` is admissible
    assert right["admissible_set"] == "none+sensor" and right["truth_admissible"] is True
    wrong = _score(tmp_path / "b", doc, "parameter")
    assert wrong["attribution_admissible"] is False
    absent = _score(tmp_path / "c", None, "none")
    assert absent["attribution_admissible"] is None and absent["admissible_set"] is None
    # nothing else moves when the file is there
    keep = {k: v for k, v in right.items() if "admissible" not in k}
    assert keep == {k: v for k, v in absent.items() if "admissible" not in k}


def test_no_workflow_may_import_the_analysis(tmp_path: Path):
    for text in ("import distinguish\n", "from distinguish.analysis import admissible\n"):
        bad = tmp_path / "wf.py"
        bad.write_text(text)
        assert find_truth_references(bad), text  # negative control: it is caught
    for module in (Path(__file__).resolve().parents[1] / "workflows").rglob("*.py"):
        assert find_truth_references(module) == [], module


def test_one_short_cell_end_to_end(store, tiny_cell):
    run, _ = tiny_cell
    docs = analyse_pair(
        [(run.run_id, run.paths.root, run.paths.truth)], classes=("none", "sensor"), log=str
    )
    doc = docs[run.run_id]
    assert doc["truth_label"] == ["none"] and doc["tier"] == "B"
    assert set(doc["classes"]) == {"none", "sensor"}
    assert doc["simulations"] == 1  # the sensor class reuses the default prediction
    assert doc["admissible_set"] and set(doc["admissible_set"]) <= {"none", "sensor"}
    assert doc["classes"]["none"]["chi2"] is not None and doc["n_samples"] > 0
