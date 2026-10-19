"""The lead's rulings of 2026-10-15: D-1 (the hold-out bit) and N-2b (the abstain label).

D-1. ``verify.differential`` is shown the hold-out bit only when ``structural`` is admitted
(design §7 governs; §2.7 brought into line). Attempt 2's own inputs are the fixture: the
clean S0-01 r1, ``sensor`` admitted, was shown ``holdout_failed: false`` and the model set
``sensor`` aside as ``holdout_passed``. The negative control is an admitted ``structural``,
which keeps the bit; the mutation shows the bit again and fails.

N-2b. An abstaining run writes ``final.label`` ``abstain``, not ``none``, and the frozen
evaluator (``eval/``, unchanged) scores it as not correct without crashing, through the
record loader, the scorer, the aggregate and the tables. The negative control is a ``none``
run on a clean cell, scored correct; the mutation is the six-class label type, under which
the evaluator drops the state as invalid.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from eval.aggregate import aggregate
from eval.config import load_eval_config
from eval.records import load_records
from eval.score import Scorer
from eval.tables import write_tables
from state.task_state import ABSTAIN, FinalLabel, Label, TaskState
from tests.eval_support import DEFAULT_TRUTH, build_run, minimal_state
from tests.p2_support import FakeTools
from tools.config import load_fitted_model
from tools.workflow_config import load_p2, sandbox_config
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]
ATTEMPT2 = REPO / "reports" / "p2_pilot" / "attempt2"
LAB = {"sensor": "sensor", "influent": "influent", "initial_state": "state",
       "parameter": "parameter", "structural": "structural", "none": "none"}  # fmt: skip


@pytest.fixture(scope="module")
def cfg() -> dict[str, Any]:
    return json.loads(json.dumps(sandbox_config(load_p2())))


def _attempt2_differential(run_id: str) -> dict[str, Any]:
    """The inputs attempt 2's differential was shown on ``run_id`` (the JSON message)."""
    lines = [
        json.loads(x) for x in (ATTEMPT2 / run_id / "llm_calls.jsonl").read_text().splitlines()
    ]
    for line in lines:
        if line["provenance"]["point"] == "verify.differential" and line.get("messages"):
            return json.loads(line["messages"][-1]["content"])
    raise AssertionError(f"no differential in {run_id}")


class Capture:
    """A responder that records what ``verify.differential`` is shown and answers nothing."""

    def __init__(self) -> None:
        """Start with nothing seen."""
        self.seen: list[dict[str, Any]] = []

    def __call__(self, point: str, template: str, inputs: dict[str, Any]) -> Any:
        if point == "verify.differential":
            self.seen.append(json.loads(json.dumps(inputs, default=str)))
        return None


# ------------------------------------------------------------------ D-1


def test_the_hold_out_bit_is_shown_only_beside_an_admitted_structural():
    # attempt 2, the clean S0-01 r1: sensor admitted, the bit shown, set aside on it
    shown = _attempt2_differential("run_6ee91ae7e48e")
    assert shown["admitted"] == ["sensor"] and shown["holdout_failed"] is False
    table = {**shown["null_table"], "placement": {}}
    now = wf.differential_inputs(LAB, table, shown["admitted"], shown["tables"]["s1"], False)
    assert "holdout_failed" not in now  # D-1: not shown beside sensor
    assert now["allowed_labels"] == ["sensor", "none"] and "placement" not in now["null_table"]
    # the negative control: with structural admitted the bit is shown, as §7 allows
    with_structural = wf.differential_inputs(LAB, table, ["structural"], None, True)
    assert with_structural["holdout_failed"] is True
    both = wf.differential_inputs(LAB, table, ["sensor", "structural"], None, True)
    assert both["holdout_failed"] is True
    # and no admitted label at all: nothing to show it for
    assert "holdout_failed" not in wf.differential_inputs(LAB, table, [], None, False)
    # the template says so, and keeps holdout_passed for the structural candidate
    text = sandbox_config(load_p2())["templates"]["verify.differential"]["text"]
    assert "not shown otherwise" in text and "applies to the structural candidate only" in text


def test_a_run_shows_the_differential_no_hold_out_bit_and_the_mutation_does(monkeypatch, cfg):
    capture = Capture()
    monkeypatch.setattr(wf, "tools", FakeTools())
    run = wf.Workflow(json.loads(json.dumps(cfg)), capture)
    run.run()
    assert capture.seen and run.tables["holdout"]["holdout_failed"] is not None
    assert all("holdout_failed" not in s for s in capture.seen)  # computed, not shown
    assert run.verdict["holdout_failed"] is not None  # the verdict still records it

    # the reverting mutation, by monkeypatching: the pre-ruling inputs show the bit again
    def pre_ruling(lab: Any, table: Any, admitted: Any, s1: Any, holdout_failed: Any) -> Any:
        out = {"null_table": {k: v for k, v in table.items() if k != "placement"},
               "admitted": list(admitted), "tables": {"s1": s1},
               "holdout_failed": holdout_failed,
               "allowed_labels": [*admitted, lab["none"]]}  # fmt: skip
        return out

    monkeypatch.setattr(wf, "differential_inputs", pre_ruling)
    capture = Capture()
    monkeypatch.setattr(wf, "tools", FakeTools())
    wf.Workflow(json.loads(json.dumps(cfg)), capture).run()
    assert any("holdout_failed" in s for s in capture.seen)


# ------------------------------------------------------------------ N-2b


def test_an_abstaining_run_writes_abstain_and_a_finished_one_does_not(monkeypatch, cfg):
    monkeypatch.setattr(wf, "tools", (fake := FakeTools(evals=60)))
    run = wf.Workflow(json.loads(json.dumps(cfg)), wf.offline_responder)
    run.run()
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    TaskState.model_validate(doc)
    assert run.verdict["verdict"] == "abstain"
    assert doc["final"]["label"] == doc["classification"]["label"] == ABSTAIN == wf.ABSTAIN_LABEL
    assert doc["classification"]["rule"].startswith("abstain:")
    assert doc["classification"]["kinetic_update"] is False
    assert doc["classification"]["evidence"] == []  # an abstention claims nothing
    # the negative control: a run whose null stands still writes none
    monkeypatch.setattr(wf, "tools", (fake := FakeTools()))
    wf.Workflow(json.loads(json.dumps(cfg)), wf.offline_responder).run()
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    assert doc["final"]["label"] == "none" and doc["classification"]["rule"] == "null_stands"


@pytest.fixture(scope="module")
def scorer() -> Scorer:
    return Scorer(config=load_eval_config(), model=load_fitted_model(),
                  defaults=dict(DEFAULT_TRUTH))  # fmt: skip


def _abstaining_state(run_id: str) -> dict[str, Any]:
    return minimal_state(run_id, final={"label": ABSTAIN, "secondary_labels": []},
                         classification={"label": ABSTAIN, "rule": "abstain:no_null_table",
                                         "confidence": 0.0})  # fmt: skip


def test_the_frozen_eval_scores_abstain_as_not_correct_without_crashing(scorer, tmp_path):
    rows = []
    for name, truth, level in (("clean", ("none",), 0), ("faulted", ("sensor",), 2)):
        root = tmp_path / name
        build_run(root, truth_label=truth, level=level,
                  state=_abstaining_state("run_000000000001"))  # fmt: skip
        records = load_records("run_000000000001", "p0", runs_root=root / "runs",
                               truth_store=root / "truth_store")  # fmt: skip
        assert records.state is not None and not records.problems  # the state is valid
        row = scorer.score(records)
        assert row["final_label"] == ABSTAIN
        assert row["attribution_exact"] is False and row["attribution_partial"] == 0.0
        assert row["primary_in_truth"] is False  # never a correct none on the clean cell
        rows.append(row)
    # the rest of the frozen pipeline takes it: the aggregate and the tables
    assert aggregate(rows, load_eval_config().aggregate)
    assert write_tables(rows, tmp_path / "rows.csv").is_file()
    # the negative control: the same clean cell answered none is scored correct
    root = tmp_path / "none"
    build_run(root, truth_label=("none",), level=0, state=minimal_state(
        "run_000000000001", final={"label": "none", "secondary_labels": []}))  # fmt: skip
    row = scorer.score(load_records("run_000000000001", "p0", runs_root=root / "runs",
                                    truth_store=root / "truth_store"))  # fmt: skip
    assert row["attribution_exact"] is True and row["primary_in_truth"] is True


def test_the_six_class_label_type_would_drop_the_abstaining_state(scorer, tmp_path, monkeypatch):
    """The mutation: ``FinalResult`` typed with the six classes only, as before the ruling."""
    assert TypeAdapter(FinalLabel).validate_python(ABSTAIN) == ABSTAIN
    with pytest.raises(ValidationError):
        TypeAdapter(Label).validate_python(ABSTAIN)
    source = (REPO / "state" / "task_state.py").read_text(encoding="utf-8")
    mutated = source.replace("    label: FinalLabel", "    label: Label")
    assert mutated != source
    path = tmp_path / "task_state_mutated.py"
    path.write_text(mutated, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("task_state_mutated", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "task_state_mutated", module)
    spec.loader.exec_module(module)
    import eval.records as records_module

    monkeypatch.setattr(records_module, "TaskState", module.TaskState)
    root = tmp_path / "run"
    build_run(root, truth_label=("none",), level=0, state=_abstaining_state("run_000000000001"))
    records = load_records("run_000000000001", "p0", runs_root=root / "runs",
                           truth_store=root / "truth_store")  # fmt: skip
    assert records.state is None and any("state.json invalid" in p for p in records.problems)
