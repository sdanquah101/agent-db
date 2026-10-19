"""The lead's rulings of 2026-10-19: an unfinished run is not a result; it is rerun.

"A run that crashes or is stopped should not be recorded as no fault. It must be rerun."

1. The backstop label (L-1 a). An unfinished run's state (a checkpoint written with
   ``completed`` false, and ``main()``'s unexpected-exception path) carries ``abstain``,
   never ``none``, and the frozen evaluator (unchanged) scores it not correct on a clean
   cell without crashing. Negative control: a finished run whose null stands writes
   ``none``, scored correct. Mutation: the ``none`` default restored writes ``none``.
2. The rerun rule (L-1 b-d, ``scripts/p2_rerun.py``), in both drivers:
   - offline, unfinished then finished: rerun once with the same cell and seed, and only
     the finished result is counted;
   - offline, unfinished twice: the driver stops, nothing is scored for that cell, and the
     unfinished attempts are reported;
   - live, unfinished: no automatic rerun; the driver stops and reports, and refuses to
     start again until the lead approves a rerun.
   Negative control: a finished run is not rerun. Mutation: the completed check dropped
   lets an unfinished run be counted.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from eval.config import load_eval_config
from eval.records import load_records
from eval.score import Scorer
from scripts import p2_rerun
from state.task_state import ABSTAIN, TaskState
from tests.eval_support import DEFAULT_TRUTH, build_run
from tests.p2_support import FakeTools
from tools.config import load_fitted_model
from tools.workflow_config import load_p2, sandbox_config
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg() -> dict[str, Any]:
    return json.loads(json.dumps(sandbox_config(load_p2())))


class Crashes(FakeTools):
    """A registry whose reference fit dies with an error no step handles (a crash)."""

    def _fit_lsq(self, parameters: Any, max_nfev_per_start: int = 40, **kw: Any) -> Any:
        raise RuntimeError("the simulator process died")


# ------------------------------------------------------------------ 1. the backstop label


def _crashed_state(module: Any, monkeypatch: pytest.MonkeyPatch, cfg: dict) -> dict[str, Any]:
    fake = Crashes()
    monkeypatch.setattr(module, "tools", fake)
    run = module.Workflow(json.loads(json.dumps(cfg)), module.offline_responder)
    with pytest.raises(RuntimeError, match="died"):
        run.run()
    # the last checkpoint's state, written with completed false
    return json.loads(fake.run.outputs[module.STATE_FILE])


def test_an_unfinished_runs_state_carries_abstain(monkeypatch, cfg, tmp_path):
    doc = _crashed_state(wf, monkeypatch, cfg)
    TaskState.model_validate(doc)
    assert doc["final"]["completed"] is False and doc["classification"]["rule"] == "pending"
    assert doc["final"]["label"] == doc["classification"]["label"] == ABSTAIN
    # main()'s unexpected-exception path writes the same, and still raises
    (tmp_path / wf.CONFIG_FILE).write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    fake = Crashes()
    monkeypatch.setattr(wf, "tools", fake)
    with pytest.raises(RuntimeError, match="died"):
        wf.main()
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    TaskState.model_validate(doc)
    assert doc["final"]["completed"] is False and doc["final"]["label"] == ABSTAIN
    assert any(a.startswith("stopped: RuntimeError") for a in doc["annotations"])
    assert json.loads(fake.run.outputs[wf.REPORT_FILE])["outcome"] == "pending"
    # the negative control: a finished run whose null stands writes none
    monkeypatch.setattr(wf, "tools", (fake := FakeTools()))
    wf.Workflow(json.loads(json.dumps(cfg)), wf.offline_responder).run()
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    assert doc["final"]["completed"] and doc["final"]["label"] == "none"


def test_the_frozen_eval_scores_an_unfinished_state_not_correct(monkeypatch, cfg, tmp_path):
    scorer = Scorer(config=load_eval_config(), model=load_fitted_model(),
                    defaults=dict(DEFAULT_TRUTH))  # fmt: skip
    doc = _crashed_state(wf, monkeypatch, cfg)
    doc["run_id"] = "run_000000000001"
    build_run(tmp_path / "pending", truth_label=("none",), level=0, state=doc)
    records = load_records("run_000000000001", "p0", runs_root=tmp_path / "pending" / "runs",
                           truth_store=tmp_path / "pending" / "truth_store")  # fmt: skip
    assert records.state is not None  # valid, so the backstop is what is scored
    row = scorer.score(records)
    assert row["final_label"] == ABSTAIN
    assert row["attribution_exact"] is False and row["primary_in_truth"] is False
    # the same state with the pre-ruling none on this clean cell: scored correct, which
    # is what the backstop prevents
    doc["final"]["label"] = doc["classification"]["label"] = "none"
    build_run(tmp_path / "none", truth_label=("none",), level=0, state=doc)
    row = scorer.score(load_records("run_000000000001", "p0",
                                    runs_root=tmp_path / "none" / "runs",
                                    truth_store=tmp_path / "none" / "truth_store"))  # fmt: skip
    assert row["attribution_exact"] is True


def test_restoring_the_none_default_writes_none(monkeypatch, cfg, tmp_path):
    """The mutation: ``build_state``'s default back to the null label."""
    source = (REPO / "workflows" / "p2_multi_agent" / "workflow.py").read_text(encoding="utf-8")
    mutated = source.replace('"label": ABSTAIN_LABEL, "secondary_labels": []',
                             '"label": self.lab["none"], "secondary_labels": []')  # fmt: skip
    assert mutated != source
    path = tmp_path / "workflow_mutated_l1.py"
    path.write_text(mutated, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("workflow_mutated_l1", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "workflow_mutated_l1", module)
    spec.loader.exec_module(module)
    assert _crashed_state(module, monkeypatch, cfg)["final"]["label"] == "none"


# ------------------------------------------------------------------ 2. the rule itself


def _record(completed: bool, n: int = 1) -> dict[str, Any]:
    return {"run_id": f"run_{n}", "attempt": n, "summary": {"completed": completed,
            "error": "" if completed else "the workflow exited with status 1"},
            "outcome": "none" if completed else "pending",
            "rule": "null_stands" if completed else "pending"}  # fmt: skip


def test_the_rule_reruns_an_unfinished_offline_run_once_and_never_a_live_one():
    calls: list[int] = []

    def script(*finished: bool) -> Any:
        def attempt(n: int) -> dict[str, Any]:
            calls.append(n)
            return _record(finished[n - 1], n)

        return attempt

    # offline, unfinished then finished: one rerun, the finished record counted
    calls.clear()
    out = p2_rerun.run_counted(script(False, True), live=False)
    assert out.status == "counted" and calls == [1, 2] and out.record["attempt"] == 2
    # the negative control: a finished run is not rerun
    calls.clear()
    out = p2_rerun.run_counted(script(True), live=False)
    assert out.status == "counted" and calls == [1]
    # offline, unfinished twice: nothing counted, both attempts reported
    calls.clear()
    out = p2_rerun.run_counted(script(False, False), live=False)
    assert out.status == "unfinished_twice" and calls == [1, 2] and out.record is None
    assert [a["completed"] for a in out.failure()["attempts"]] == [False, False]
    # live, unfinished: no automatic rerun
    calls.clear()
    out = p2_rerun.run_counted(script(False, True), live=True)
    assert out.status == "unfinished_live" and calls == [1] and out.record is None
    # a report says pending, or the rule does, even if the runner saw completion
    assert not p2_rerun.finished({"summary": {"completed": True}, "outcome": "pending"})
    assert not p2_rerun.finished({"completed": True, "outcome": "none", "rule": "pending"})
    assert not p2_rerun.finished({"summary": {"completed": True}})  # no report at all
    # the mutation: without the completed check an unfinished run is counted
    calls.clear()
    out = p2_rerun.run_counted(script(False), live=False, is_finished=lambda r: True)
    assert out.status == "counted" and out.record["summary"]["completed"] is False


# ------------------------------------------------------------------ 2. the drivers


class FakeDriver:
    """``generate_run`` and ``run_workflow`` for a driver, with scripted completions."""

    def __init__(self, fail: dict[str, int]) -> None:
        """``fail`` maps a run id to how many of its attempts do not finish."""
        self.fail = dict(fail)
        self.launched: list[str] = []

    def generate(self, scenario: Any, tier: Any, *, plant: Any = None, replicate: int = 0,
                 runs_root: Path, **kw: Any) -> Any:  # fmt: skip
        rid = f"run_{scenario.id}_{replicate}"
        (runs_root / rid).mkdir(parents=True, exist_ok=True)
        (runs_root / rid / "calls.jsonl").write_text('{"seq": 0}\n')
        return types.SimpleNamespace(run_id=rid)

    def run_workflow(self, run_id: str, *a: Any, runs_root: Path, **kw: Any) -> Any:
        self.launched.append(run_id)
        out = runs_root / run_id / "workflows" / "p2"
        out.mkdir(parents=True, exist_ok=True)
        done = self.fail.get(run_id, 0) <= 0
        self.fail[run_id] = self.fail.get(run_id, 0) - 1
        report = {
            "outcome": "none",
            "rule": "null_stands",
            "label": "none",
            "verdict": {},
            "null_table": {},
            "signatures": {},
            "by_role": {},
        }
        if done:
            (out / "report.json").write_text(json.dumps(report))
            (out / "state.json").write_text(json.dumps({"abstentions": [], "annotations": []}))
        summary = {"completed": done, "error": "" if done else "the workflow exited with "
                   "status 1", "failure_reason": "" if done else "other"}  # fmt: skip
        return types.SimpleNamespace(
            llm_cost_usd=0.0,
            as_dict=lambda: summary,
            completed=done,
            error=summary["error"],
            simulator_evals_used=0,
            simulator_evals_total=1,
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sim.run.harness.generate_run", self.generate)
        monkeypatch.setattr("tools.runner.run_workflow", self.run_workflow)


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines()] if path.is_file() else []


def test_the_pilot_reruns_an_unfinished_offline_run_and_counts_only_finished_ones(
    tmp_path, monkeypatch
):
    from scripts import p2_pilot

    first = "run_S0-01_0"
    # unfinished once: rerun once with the same cell and seed, the finished one counted
    driver = FakeDriver({first: 1})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "once", live=False)
    rows = _lines(tmp_path / "once" / "results_offline.0.jsonl")
    assert len(rows) == 6 and rows[0]["run_id"] == first and rows[0]["attempt"] == 2
    assert all(r["summary"]["completed"] for r in rows)
    assert driver.launched.count(first) == 2 and len(driver.launched) == 7
    kept = tmp_path / "once" / "runs" / first / "workflows" / "p2.unfinished-1"
    assert kept.is_dir() and (kept / "calls.jsonl").is_file()  # the failed attempt, kept
    assert not _lines(tmp_path / "once" / "unfinished_offline.0.jsonl")
    # the negative control: finished runs are not rerun
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "clean", live=False)
    assert len(driver.launched) == 6 and all(
        r["attempt"] == 1 for r in _lines(tmp_path / "clean" / "results_offline.0.jsonl")
    )
    # unfinished twice: the driver stops, nothing scored for the cell, the failure reported
    driver = FakeDriver({first: 2})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "twice", live=False)
    assert driver.launched == [first, first]
    assert not _lines(tmp_path / "twice" / "results_offline.0.jsonl")
    (failure,) = _lines(tmp_path / "twice" / "unfinished_offline.0.jsonl")
    assert failure["status"] == "unfinished_twice" and len(failure["attempts"]) == 2
    assert all(a["error"] for a in failure["attempts"])
    # the mutation: without the completed check, the unfinished run is counted
    driver = FakeDriver({first: 1})
    driver.install(monkeypatch)
    monkeypatch.setattr(p2_rerun, "finished", lambda record: True)
    monkeypatch.setattr(p2_rerun.run_counted, "__kwdefaults__", {"is_finished": lambda r: True})
    p2_pilot._runs(tmp_path / "mutant", live=False)
    rows = _lines(tmp_path / "mutant" / "results_offline.0.jsonl")
    assert rows[0]["summary"]["completed"] is False  # counted: what the check prevents


def test_a_live_unfinished_run_is_not_rerun_and_stops_the_pilot(tmp_path, monkeypatch):
    from scripts import p2_pilot

    first = "run_S0-01_0"
    driver = FakeDriver({first: 1})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path, live=True)
    assert driver.launched == [first]  # no automatic rerun
    assert not _lines(tmp_path / "results.jsonl")  # nothing scored
    (failure,) = _lines(tmp_path / "unfinished.jsonl")
    assert failure["status"] == "unfinished_live" and failure["attempts"][0]["run_id"] == first
    # and the pilot refuses to start again: a rerun needs the lead's approval
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path, live=True)
    assert driver.launched == []
    # the report lists it, unscored
    monkeypatch.setattr(p2_pilot, "REPORT_DIR", tmp_path / "reports")
    (tmp_path / "results.jsonl").write_text("")
    out = p2_pilot.report(tmp_path, "attempt_x")
    assert out["rows"] == [] and out["unfinished"][0]["cell"] == "S0-01 B/B"
    assert (
        "Unfinished (not scored" in (tmp_path / "reports" / "attempt_x" / "summary.md").read_text()
    )
    # the negative control: finished live runs are all counted, none rerun
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "clean", live=True)
    assert len(driver.launched) == 6 and len(_lines(tmp_path / "clean" / "results.jsonl")) == 6


def test_the_power_run_reruns_once_and_never_scores_an_unfinished_cell(tmp_path, monkeypatch):
    from scripts import p2_power

    first = "run_S2-01_0"
    driver = FakeDriver({first: 1})
    driver.install(monkeypatch)
    p2_power.run(tmp_path / "once")
    results = sorted((tmp_path / "once" / "results").glob("*.json"))
    assert len(results) == len(p2_power.CELLS)
    record = json.loads((tmp_path / "once" / "results" / "S2-01-B-B.json").read_text())
    assert record["attempt"] == 2 and record["completed"] is True
    assert driver.launched.count(first) == 2
    # unfinished twice: stopped, not scored, reported
    driver = FakeDriver({first: 2})
    driver.install(monkeypatch)
    p2_power.run(tmp_path / "twice")
    assert driver.launched == [first, first]
    assert not list((tmp_path / "twice" / "results").glob("*.json"))
    failure = json.loads((tmp_path / "twice" / "unfinished" / "S2-01-B-B.json").read_text())
    assert failure["status"] == "unfinished_twice" and len(failure["attempts"]) == 2
    # and a resumed run does not silently retry it
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_power.run(tmp_path / "twice")
    assert first not in driver.launched
    # the negative control: finished cells run once each
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_power.run(tmp_path / "clean")
    assert len(driver.launched) == len(p2_power.CELLS)
