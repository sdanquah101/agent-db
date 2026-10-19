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
    # a live unfinished run is not set aside: it stays where it ran (the review of 0b9f210, N-3)
    assert (tmp_path / "runs" / first / "workflows" / "p2").is_dir()
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


# ------------------------------------------------------------------ the review of b837c64


class StopsDriver(FakeDriver):
    """A driver whose ``run_workflow`` is interrupted (a stopped driver) on given run ids."""

    def __init__(self, stop: dict[str, int], fail: dict[str, int] | None = None) -> None:
        """``stop`` maps a run id to how many of its launches raise ``KeyboardInterrupt``."""
        super().__init__(fail or {})
        self.stop = dict(stop)

    def run_workflow(self, run_id: str, *a: Any, runs_root: Path, **kw: Any) -> Any:
        if self.stop.get(run_id, 0) > 0:
            self.stop[run_id] -= 1
            self.launched.append(run_id)
            raise KeyboardInterrupt
        return super().run_workflow(run_id, *a, runs_root=runs_root, **kw)


def test_finished_needs_both_the_runners_completion_and_a_non_pending_report():
    """N-1: each half of the check pinned on its own."""
    done = {"summary": {"completed": True}, "outcome": "none", "rule": "null_stands"}
    assert p2_rerun.finished(done)  # the negative control
    assert not p2_rerun.finished({**done, "summary": {"completed": False}})  # the runner half
    assert not p2_rerun.finished({**done, "outcome": "pending"})  # the report half
    assert not p2_rerun.finished({**done, "rule": "pending"})


def test_a_set_aside_never_overwrites_an_earlier_one(tmp_path):
    run = tmp_path / "run_x"
    (run / "workflows" / "p2.unfinished-1").mkdir(parents=True)
    (run / "workflows" / "p2.unfinished-1" / "keep").write_text("first")
    (run / "workflows" / "p2").mkdir()
    (run / "workflows" / "p2" / "state.json").write_text("{}")
    dest = p2_rerun.set_aside(run, 1)
    assert dest == run / "workflows" / "p2.unfinished-2"
    assert (run / "workflows" / "p2.unfinished-1" / "keep").read_text() == "first"
    assert (dest / "state.json").is_file() and not (run / "workflows" / "p2").exists()


def test_a_stopped_live_pilot_is_recorded_unfinished_and_never_relaunched(tmp_path, monkeypatch):
    """S-2 (d): the stop leaves an in-flight line; the resume records it and stops."""
    from scripts import p2_pilot

    first = "run_S0-01_0"
    driver = StopsDriver({first: 1})
    driver.install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(tmp_path, live=True)
    assert driver.launched == [first] and not _lines(tmp_path / "unfinished.jsonl")
    (journal,) = _lines(tmp_path / "in_flight.jsonl")
    assert journal["run_id"] == first and journal["attempt"] == 1
    # the resume: no launch at all, the run recorded unfinished, reported
    driver = StopsDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path, live=True)
    assert driver.launched == []
    (failure,) = _lines(tmp_path / "unfinished.jsonl")
    assert failure["status"] == "unfinished_live"
    assert failure["attempts"][0]["failure_reason"] == "driver_stopped"
    # and every later resume refuses too
    p2_pilot._runs(tmp_path, live=True)
    assert driver.launched == []
    # the mutation: a driver that ignores the journal relaunches the live run unapproved
    store = tmp_path / "mutant"
    driver = StopsDriver({first: 1})
    driver.install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(store, live=True)
    monkeypatch.setattr(p2_rerun.InFlight, "orphans", lambda self, settled: {})
    driver = StopsDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(store, live=True)
    assert first in driver.launched  # what the journal prevents


def test_a_stopped_offline_attempt_counts_so_only_one_rerun_follows(tmp_path, monkeypatch):
    """S-2 (c): the stop is attempt 1; the resume runs attempt 2 only, then counts it."""
    from scripts import p2_pilot

    first = "run_S0-01_0"
    driver = StopsDriver({first: 1})
    driver.install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(tmp_path / "once", live=False)
    driver = StopsDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "once", live=False)
    assert driver.launched.count(first) == 1  # the rerun only, not two more attempts
    rows = _lines(tmp_path / "once" / "results_offline.0.jsonl")
    assert rows[0]["run_id"] == first and rows[0]["attempt"] == 2 and len(rows) == 6
    # stopped, then the rerun unfinished too: stop and report, no third attempt
    driver = StopsDriver({first: 1})
    driver.install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(tmp_path / "twice", live=False)
    driver = StopsDriver({}, fail={first: 1})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "twice", live=False)
    assert driver.launched == [first]
    (failure,) = _lines(tmp_path / "twice" / "unfinished_offline.0.jsonl")
    assert failure["status"] == "unfinished_twice"
    assert failure["attempts"][0]["failure_reason"] == "driver_stopped"
    assert not (tmp_path / "twice" / "runs" / first / "workflows" / "p2").exists()  # N-7
    # N-2: a resumed pilot skips the twice-failed cell; the other five run once each
    driver = StopsDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "twice", live=False)
    assert first not in driver.launched and len(driver.launched) == 5
    # the negative control: a completed cell is not rerun on resume
    driver = StopsDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "twice", live=False)
    assert driver.launched == []
    # the mutation: ignoring the journal gives the stopped cell two more attempts
    store = tmp_path / "mutant"
    driver = StopsDriver({first: 1})
    driver.install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(store, live=False)
    monkeypatch.setattr(p2_rerun.InFlight, "orphans", lambda self, settled: {})
    driver = StopsDriver({}, fail={first: 1})
    driver.install(monkeypatch)
    p2_pilot._runs(store, live=False)
    assert driver.launched.count(first) == 2  # what the journal prevents


def test_a_stopped_power_run_counts_the_stopped_attempt(tmp_path, monkeypatch):
    from scripts import p2_power

    first = "run_S2-01_0"
    driver = StopsDriver({first: 1})
    driver.install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_power.run(tmp_path)
    driver = StopsDriver({}, fail={first: 1})
    driver.install(monkeypatch)
    p2_power.run(tmp_path)
    assert driver.launched == [first]  # one rerun only, then stop
    failure = json.loads((tmp_path / "unfinished" / "S2-01-B-B.json").read_text())
    assert failure["status"] == "unfinished_twice"
    assert failure["attempts"][0]["failure_reason"] == "driver_stopped"
    assert failure["attempts"][1]["failure_reason"] == "run_failed"  # N-4
    # nothing unfinished stays at workflows/p2 (N-7; the review of 0b9f210, N-3)
    assert not (tmp_path / "runs" / first / "workflows" / "p2").exists()


def test_the_power_report_lists_unfinished_cells_and_reruns_and_scores_neither(
    tmp_path, monkeypatch
):
    """S-1 for the power run, and N-5: reported, kept out of the cells and the counts."""
    from scripts import p2_power

    store = tmp_path / "store"
    driver = FakeDriver({"run_S2-01_0": 2, "run_S3-01_0": 1})
    driver.install(monkeypatch)
    for _ in range(3):  # S2-01 stops the driver; each resume gets further
        p2_power.run(store)
    assert (store / "unfinished" / "S2-01-B-B.json").is_file()
    monkeypatch.setattr(p2_power, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(p2_power, "steps_of", lambda store, record: None)
    monkeypatch.setattr(p2_power, "summarise", lambda records: {
        "cells": [{"cell": r["cell"], "truth": r["truth"], "outcome": r["outcome"],
                   "excluded": False, "null": {}, "failed_channels": [], "admitted": []}
                  for r in records], "hits_faulted": f"{len(records)}",
        "excluded_faulted": {}, "null_rejected_faulted": 0})  # fmt: skip
    out = p2_power.report(store)
    assert [u["cell"] for u in out["unfinished"]] == ["S2-01 B/B"]
    assert "S2-01 B/B" not in [c["cell"] for c in out["cells"]]
    assert [x["cell"] for x in out["reruns"]] == ["S3-01 C/B"]
    text = (tmp_path / "reports" / "summary.md").read_text()
    assert "Unfinished (not scored, reported to the coordinator): S2-01 B/B" in text
    assert "Rerun once, completed: S3-01 C/B" in text
    # a blank line before each group (the review of 0b9f210, N-5)
    lines = text.splitlines()
    for start in ("Unfinished", "Rerun once"):
        i = next(k for k, x in enumerate(lines) if x.startswith(start))
        assert lines[i - 1] == "", start
    # the mutation: a report that does not read the unfinished records drops the cell
    monkeypatch.setattr(p2_rerun, "read_unfinished", lambda paths: [])
    out = p2_power.report(store)
    assert (
        out["unfinished"] == []
        and "Unfinished" not in (tmp_path / "reports" / "summary.md").read_text()
    )


def test_the_offline_pilot_report_lists_unfinished_cells_and_reruns(tmp_path, monkeypatch):
    """S-1 for the pilot's offline report, and N-5."""
    from scripts import p2_pilot

    store = tmp_path / "store"
    driver = FakeDriver({"run_S0-01_0": 2, "run_S2-01_1": 1})
    driver.install(monkeypatch)
    for _ in range(2):
        p2_pilot._runs(store, live=False)
    monkeypatch.setattr(p2_pilot, "REPORT_DIR", tmp_path / "reports")
    out = p2_pilot.report_offline(store)
    assert [(u["cell"], u["replicate"]) for u in out["unfinished"]] == [("S0-01 B/B", 0)]
    assert ("S0-01 B/B", 0) not in [(r["cell"], r["replicate"]) for r in out["rows"]]
    assert [(x["cell"], x["replicate"]) for x in out["reruns"]] == [("S2-01 B/B", 1)]
    text = (tmp_path / "reports" / "offline.md").read_text()
    assert "Unfinished (not scored, reported to the coordinator): S0-01 B/B r0" in text
    assert "Rerun once, completed: S2-01 B/B r1" in text
    # the mutation: without the read, the cell vanishes from the report
    monkeypatch.setattr(p2_rerun, "read_unfinished", lambda paths: [])
    assert p2_pilot.report_offline(store)["unfinished"] == []


def test_the_live_reports_unfinished_lines_are_not_table_rows(tmp_path, monkeypatch):
    """N-3: a blank line between the table and the unfinished lines."""
    from scripts import p2_pilot

    driver = FakeDriver({"run_S0-01_0": 1})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path, live=True)
    (tmp_path / "results.jsonl").write_text("")
    monkeypatch.setattr(p2_pilot, "REPORT_DIR", tmp_path / "reports")
    p2_pilot.report(tmp_path, "a")
    lines = (tmp_path / "reports" / "a" / "summary.md").read_text().splitlines()
    i = next(k for k, x in enumerate(lines) if x.startswith("Unfinished"))
    assert lines[i - 1] == "" and lines[i - 2].startswith("|")


# ------------------------------------------------------------------ the review of 0b9f210


def _stub_summarise(monkeypatch: pytest.MonkeyPatch, p2_power: Any) -> None:
    monkeypatch.setattr(p2_power, "steps_of", lambda store, record: None)
    monkeypatch.setattr(p2_power, "summarise", lambda records: {
        "cells": [{"cell": r["cell"], "truth": r["truth"], "outcome": r["outcome"],
                   "excluded": False, "null": {}, "failed_channels": [], "admitted": []}
                  for r in records], "hits_faulted": f"{len(records)}",
        "excluded_faulted": {}, "null_rejected_faulted": 0})  # fmt: skip


def _stop_every_driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A live pilot, an offline pilot and a power run, each stopped on its first run."""
    from scripts import p2_pilot, p2_power

    stores = {k: tmp_path / k for k in ("live", "offline", "power")}
    for name, go, first in (
        ("live", lambda st: p2_pilot._runs(st, live=True), "run_S0-01_0"),
        ("offline", lambda st: p2_pilot._runs(st, live=False), "run_S0-01_0"),
        ("power", lambda st: p2_power.run(st), "run_S2-01_0"),
    ):
        StopsDriver({first: 1}).install(monkeypatch)
        with pytest.raises(KeyboardInterrupt):
            go(stores[name])
    return stores


def _reports(stores: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Each report's unfinished cells, with no driver started since the stop."""
    from scripts import p2_pilot, p2_power

    monkeypatch.setattr(p2_pilot, "REPORT_DIR", tmp_path / "reports_pilot")
    monkeypatch.setattr(p2_power, "REPORT_DIR", tmp_path / "reports_power")
    _stub_summarise(monkeypatch, p2_power)
    return {
        "live": p2_pilot.report(stores["live"], "a")["unfinished"],
        "offline": p2_pilot.report_offline(stores["offline"])["unfinished"],
        "power": p2_power.report(stores["power"])["unfinished"],
    }


def test_every_report_lists_a_stopped_cell_with_no_resume(tmp_path, monkeypatch):
    """SF-1: the journal is read by each report, not only by a later driver start."""
    stores = _stop_every_driver(tmp_path, monkeypatch)
    out = _reports(stores, tmp_path, monkeypatch)
    for name, cell in (("live", "S0-01 B/B"), ("offline", "S0-01 B/B"), ("power", "S2-01 B/B")):
        (u,) = out[name]
        assert (u["cell"], u["replicate"], u["status"]) == (cell, 0, "driver_stopped"), name
        assert u["note"] == "stopped or still running"
        assert u["attempts"][0]["failure_reason"] == "driver_stopped"
    for md in (tmp_path / "reports_pilot" / "a" / "summary.md",
               tmp_path / "reports_pilot" / "offline.md",
               tmp_path / "reports_power" / "summary.md"):  # fmt: skip
        assert "driver_stopped (stopped or still running)" in md.read_text(), md
    # nothing was recorded by the reports: the stores hold no unfinished record yet
    assert not (stores["live"] / "unfinished.jsonl").exists()
    # the mutation: a report that does not read the journal lists nothing
    monkeypatch.setattr(p2_rerun.InFlight, "orphans", lambda self, settled: {})
    assert _reports(stores, tmp_path, monkeypatch) == {"live": [], "offline": [], "power": []}


def test_a_refused_live_start_still_records_the_stopped_run(tmp_path, monkeypatch):
    """SF-1: ``run`` records a stopped pilot's run before the approval and key checks."""
    from scripts import p2_pilot

    StopsDriver({"run_S0-01_0": 1}).install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(tmp_path / "store", live=True)

    def refuse(*a: Any, **kw: Any) -> None:
        raise ValueError("no approval for this store")

    monkeypatch.setattr("tools.p2_live.require_live_approval", refuse)
    monkeypatch.delenv(p2_pilot.KEY_VARIABLE, raising=False)
    with pytest.raises(SystemExit, match="not approved"):
        p2_pilot.run(tmp_path / "store", live=True)
    (failure,) = _lines(tmp_path / "store" / "unfinished.jsonl")
    assert failure["cell"] == "S0-01 B/B" and failure["status"] == "unfinished_live"
    assert failure["attempts"][0]["failure_reason"] == "driver_stopped"
    # and once recorded, a second refused start does not record it again
    with pytest.raises(SystemExit):
        p2_pilot.run(tmp_path / "store", live=True)
    assert len(_lines(tmp_path / "store" / "unfinished.jsonl")) == 1
    # the mutation: recording only inside the driver, after the checks, records nothing
    StopsDriver({"run_S0-01_0": 1}).install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(tmp_path / "mutant", live=True)
    monkeypatch.setattr(p2_pilot, "record_stopped_live", lambda store: False)
    with pytest.raises(SystemExit):
        p2_pilot.run(tmp_path / "mutant", live=True)
    assert not (tmp_path / "mutant" / "unfinished.jsonl").exists()


def _only_own_journal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mutation for SF-2: each part reads its own journal only, as before."""
    init = p2_rerun.InFlight.__init__
    monkeypatch.setattr(p2_rerun.InFlight, "__init__",
                        lambda self, path, others=(): init(self, path))  # fmt: skip


def test_a_resume_under_another_part_count_gets_exactly_one_more_launch(tmp_path, monkeypatch):
    """SF-2: stopped under 1/2, resumed under 0/1: the stopped attempt still counts."""
    from scripts import p2_pilot, p2_power

    def stop_then_resume(store: Path, go: Any, stopped: str, mutant: bool = False) -> list:
        StopsDriver({stopped: 1}).install(monkeypatch)
        with pytest.raises(KeyboardInterrupt):
            go(store, "1/2")
        if mutant:
            _only_own_journal(monkeypatch)
        driver = StopsDriver({}, fail={stopped: 1})  # the rerun does not finish either
        driver.install(monkeypatch)
        go(store, "0/1")
        return driver.launched

    pilot = lambda store, part: p2_pilot._runs(store, live=False, part=part)  # noqa: E731
    power = lambda store, part: p2_power.run(store, part)  # noqa: E731
    # the pilot: part 1/2's first run is S0-01 r1; the power run's is S3-01
    launched = stop_then_resume(tmp_path / "pilot", pilot, "run_S0-01_1")
    assert launched == ["run_S0-01_0", "run_S0-01_1"]  # one more launch, then stop
    (failure,) = _lines(tmp_path / "pilot" / "unfinished_offline.0.jsonl")
    assert failure["status"] == "unfinished_twice" and failure["replicate"] == 1
    assert [a["failure_reason"] for a in failure["attempts"]] == ["driver_stopped", "other"]
    launched = stop_then_resume(tmp_path / "power", power, "run_S3-01_0")
    assert launched == ["run_S2-01_0", "run_S3-01_0"]
    failure = json.loads((tmp_path / "power" / "unfinished" / "S3-01-C-B.json").read_text())
    assert [a["failure_reason"] for a in failure["attempts"]] == ["driver_stopped", "run_failed"]
    # the mutation: a part that reads only its own journal gives the cell a third attempt
    launched = stop_then_resume(tmp_path / "pilot_mutant", pilot, "run_S0-01_1", mutant=True)
    assert launched.count("run_S0-01_1") == 2
    launched = stop_then_resume(tmp_path / "power_mutant", power, "run_S3-01_0", mutant=True)
    assert launched.count("run_S3-01_0") == 2


class FailsThenStops(FakeDriver):
    """A driver whose first launch of a run fails and whose second is stopped."""

    def run_workflow(self, run_id: str, *a: Any, runs_root: Path, **kw: Any) -> Any:
        if run_id in self.launched:
            self.launched.append(run_id)
            raise KeyboardInterrupt
        self.fail[run_id] = 1
        return super().run_workflow(run_id, *a, runs_root=runs_root, **kw)


def test_an_earlier_attempts_real_error_survives_a_later_stop(tmp_path, monkeypatch):
    """N-1: attempt 1 fails, attempt 2 is stopped; the resume keeps attempt 1's error."""
    from scripts import p2_pilot

    def go(store: Path) -> dict[str, Any]:
        FailsThenStops({}).install(monkeypatch)
        with pytest.raises(KeyboardInterrupt):
            p2_pilot._runs(store, live=False)
        driver = StopsDriver({})
        driver.install(monkeypatch)
        p2_pilot._runs(store, live=False)
        assert "run_S0-01_0" not in driver.launched  # two attempts made: no third
        return _lines(store / "unfinished_offline.0.jsonl")[0]

    failure = go(tmp_path / "store")
    assert failure["status"] == "unfinished_twice"
    first, second = failure["attempts"]
    assert first["error"] == "the workflow exited with status 1"
    assert first["failure_reason"] == "other"
    assert second["failure_reason"] == "driver_stopped"
    # the mutation: no line when an attempt returns, so attempt 1 reads as stopped
    monkeypatch.setattr(p2_rerun.InFlight, "finish", lambda self, *a, **kw: None)
    first, _ = go(tmp_path / "mutant")["attempts"]
    assert first["failure_reason"] == "driver_stopped"


def test_the_journal_is_synced_and_a_torn_line_is_an_in_flight_attempt(tmp_path, monkeypatch):
    """N-2: ``start`` flushes and syncs; a torn last line is never skipped."""
    from scripts import p2_pilot

    synced: list[int] = []
    monkeypatch.setattr(p2_rerun.os, "fsync", lambda fd: synced.append(fd))
    journal = p2_rerun.InFlight(tmp_path / "j.jsonl")
    journal.start("S0-01 B/B", 0, 1, "run_a")
    assert len(synced) == 1
    # a torn line naming its cell is that cell's in-flight attempt
    with journal.path.open("a") as fh:
        fh.write('{"cell": "S2-01 B/B", "replicate": 1, "att')
    orphans = journal.orphans(set())
    assert orphans[("S2-01 B/B", 1)][0]["summary"]["failure_reason"] == "driver_stopped"
    assert orphans[("S0-01 B/B", 0)][0]["run_id"] == "run_a"
    # one naming nothing is an attempt of an unknown cell
    torn = tmp_path / "torn.jsonl"
    torn.write_text('{"ce')
    assert p2_rerun.InFlight.TORN in p2_rerun.InFlight(torn).orphans(set())
    # offline, an unknown cell's attempt stops the driver: no cell is run
    store = tmp_path / "offline"
    store.mkdir()
    (store / "in_flight_offline.0.jsonl").write_text('{"ce')
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(store, live=False)
    assert driver.launched == []
    # live, a torn line on a live cell is recorded unfinished and the pilot stops
    store = tmp_path / "live"
    store.mkdir()
    (store / "in_flight.jsonl").write_text('{"cell": "S0-01 B/B", "replicate": 0, "attempt"')
    p2_pilot._runs(store, live=True)
    assert driver.launched == []
    (failure,) = _lines(store / "unfinished.jsonl")
    assert (failure["cell"], failure["replicate"]) == ("S0-01 B/B", 0)
    # the mutation: a torn line skipped (or the pre-review crash on it) relaunches the run
    store = tmp_path / "mutant"
    store.mkdir()
    (store / "in_flight.jsonl").write_text('{"cell": "S0-01 B/B", "replicate": 0, "attempt"')
    monkeypatch.setattr(p2_rerun.InFlight, "_torn", staticmethod(
        lambda raw: {"cell": "<skipped>", "replicate": -2, "event": "returned"}))  # fmt: skip
    p2_pilot._runs(store, live=True)
    assert "run_S0-01_0" in driver.launched


def test_the_live_report_gives_the_ledger_and_the_unfinished_runs_cost(tmp_path, monkeypatch):
    """N-4: the finished rows' USD, the ledger's total and the unfinished runs' own cost."""
    from scripts import p2_pilot

    FakeDriver({"run_S0-01_0": 1}).install(monkeypatch)
    p2_pilot._runs(tmp_path, live=True)
    log = tmp_path / "runs" / "run_S0-01_0" / "workflows" / "p2" / "llm_calls.jsonl"
    log.write_text(json.dumps({"usage": {"input_tokens": 1_000_000, "output_tokens": 100_000,
                                         "cache_read_input_tokens": 0}}) + "\n")  # fmt: skip
    (tmp_path / "spent_usd.json").write_text(json.dumps({"usd": 0.4}))
    monkeypatch.setattr(p2_pilot, "REPORT_DIR", tmp_path / "reports")
    out = p2_pilot.report(tmp_path, "a")
    price = load_p2(tmp_path / "config" / "p2.yaml").model.pricing_usd_per_mtok
    assert out["usd_total"] == 0.0  # no finished row
    assert out["usd_ledger"] == 0.4
    assert out["usd_unfinished"] == pytest.approx(price.input + 0.1 * price.output)
    text = (tmp_path / "reports" / "a" / "summary.md").read_text()
    assert "USD 0.4 spent in all" in text


class StopsInGenerate(FakeDriver):
    """A driver stopped inside ``generate_run``, before the run's journal line."""

    def __init__(self, journal_first: Path | None = None) -> None:
        """With ``journal_first``, the mutation: a journal line written before the stop."""
        super().__init__({})
        self.journal_first = journal_first

    def generate(self, scenario: Any, tier: Any, *, replicate: int = 0, runs_root: Path,
                 **kw: Any) -> Any:  # fmt: skip
        if self.journal_first is not None:
            p2_rerun.InFlight(self.journal_first).start(
                "S0-01 B/B", replicate, 1, f"run_{scenario.id}_{replicate}"
            )
        raise KeyboardInterrupt


def test_a_live_stop_before_the_journal_line_is_no_run_and_one_after_it_is(tmp_path, monkeypatch):
    """The lead's ruling of 2026-10-19, "Yes, keep both", pinned on each side."""
    from scripts import p2_pilot

    # (1) stopped inside generate_run: no journal line, nothing recorded; a resume runs it
    StopsInGenerate().install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(tmp_path / "one", live=True)
    assert not _lines(tmp_path / "one" / "in_flight.jsonl")
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "one", live=True)
    assert driver.launched[0] == "run_S0-01_0" and len(driver.launched) == 6
    assert not _lines(tmp_path / "one" / "unfinished.jsonl")
    # its mutation: a journal line written before generate_run makes that stop a run,
    # recorded unfinished, and the resume launches nothing
    store = tmp_path / "one_mutant"
    store.mkdir()
    StopsInGenerate(journal_first=store / "in_flight.jsonl").install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(store, live=True)
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(store, live=True)
    assert driver.launched == [] and _lines(store / "unfinished.jsonl")

    # (2) stopped after the journal line, before any model request (nothing spent):
    # recorded unfinished, and no resume launches it without approval
    def stop_after_journal(store: Path) -> None:
        StopsDriver({"run_S0-01_0": 1}).install(monkeypatch)
        with pytest.raises(KeyboardInterrupt):
            p2_pilot._runs(store, live=True)
        assert not (store / "runs" / "run_S0-01_0" / "workflows" / "p2" / "llm_calls.jsonl"
                    ).exists()  # fmt: skip

    stop_after_journal(tmp_path / "two")
    driver = StopsDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "two", live=True)
    assert driver.launched == []
    (failure,) = _lines(tmp_path / "two" / "unfinished.jsonl")
    assert failure["attempts"][0]["failure_reason"] == "driver_stopped"
    # its mutation: exempting a stop with no model request relaunches the run unapproved
    stop_after_journal(tmp_path / "two_mutant")
    orphans = p2_rerun.InFlight.orphans

    def spent_only(self: Any, settled: Any) -> dict:
        return {k: v for k, v in orphans(self, settled).items()
                if any((self.path.parent / "runs" / str(a["run_id"]) / "workflows" / "p2"
                        / "llm_calls.jsonl").is_file() for a in v)}  # fmt: skip

    monkeypatch.setattr(p2_rerun.InFlight, "orphans", spent_only)
    driver = StopsDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path / "two_mutant", live=True)
    assert "run_S0-01_0" in driver.launched


# ------------------------------------------------------------------ the review of 024da41


def _tear(journal: Path) -> None:
    """Cut the journal's last line short, after its cell and seed (a write torn by a crash)."""
    lines = journal.read_text().splitlines()
    last = lines[-1]
    journal.write_text("\n".join([*lines[:-1], last[: last.index('"attempt"') + 5]]))


def _unguarded_write(self: Any, line: dict[str, Any]) -> None:
    """The mutation: the journal writer as at 024da41, appending onto a torn line."""
    with self.path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, default=str) + "\n")


def test_a_line_after_a_torn_one_is_never_glued_onto_it(tmp_path, monkeypatch):
    """SF-1: torn line, resume (attempt 2 stopped), resume: no launch, ``unfinished_twice``."""
    from scripts import p2_pilot, p2_power

    def torn_then_twice(store: Path, go: Any, first: str, journal: str) -> list[str]:
        for _ in range(2):  # attempt 1 stopped, torn; attempt 2 stopped
            StopsDriver({first: 1}).install(monkeypatch)
            with pytest.raises(KeyboardInterrupt):
                go(store)
            if _ == 0:
                _tear(store / journal)
        driver = StopsDriver({})
        driver.install(monkeypatch)
        go(store)
        return driver.launched

    pilot = lambda store: p2_pilot._runs(store, live=False)  # noqa: E731
    launched = torn_then_twice(tmp_path / "pilot", pilot, "run_S0-01_0",
                               "in_flight_offline.0.jsonl")  # fmt: skip
    assert "run_S0-01_0" not in launched
    (failure,) = _lines(tmp_path / "pilot" / "unfinished_offline.0.jsonl")
    assert failure["status"] == "unfinished_twice" and failure["cell"] == "S0-01 B/B"
    rows = _lines(tmp_path / "pilot" / "results_offline.0.jsonl")
    assert ("S0-01 B/B", 0) not in [(r["cell"], r["replicate"]) for r in rows]  # not scored
    launched = torn_then_twice(tmp_path / "power", p2_power.run, "run_S2-01_0", "in_flight.0.jsonl")
    assert "run_S2-01_0" not in launched
    failure = json.loads((tmp_path / "power" / "unfinished" / "S2-01-B-B.json").read_text())
    assert failure["status"] == "unfinished_twice"
    assert not (tmp_path / "power" / "results" / "S2-01-B-B.json").exists()

    # across a part change: S4-01 torn under 0/2; S3-01's start, under 0/1, must not glue
    store = tmp_path / "parts"

    def parts(mutant: bool = False) -> FakeDriver:
        StopsDriver({"run_S4-01_0": 1}).install(monkeypatch)
        with pytest.raises(KeyboardInterrupt):
            p2_power.run(store, "0/2")  # S2-01 finishes, S4-01 is stopped
        _tear(store / "in_flight.0.jsonl")
        if mutant:
            monkeypatch.setattr(p2_rerun.InFlight, "_write", _unguarded_write)
        StopsDriver({"run_S3-01_0": 1}).install(monkeypatch)
        with pytest.raises(KeyboardInterrupt):
            p2_power.run(store, "0/1")  # S3-01, attempt 1, is stopped
        driver = StopsDriver({})
        driver.install(monkeypatch)
        p2_power.run(store, "0/1")
        return driver

    driver = parts()
    assert driver.launched.count("run_S3-01_0") == 1  # its rerun only
    assert driver.launched.count("run_S4-01_0") == 1
    for name in ("S3-01-C-B.json", "S4-01-B-B.json"):
        assert json.loads((store / "results" / name).read_text())["attempt"] == 2, name

    # the mutation: the unguarded writer glues S3-01's line onto S4-01's fragment, so S3-01
    # is relaunched as attempt 1, its stopped attempt lost
    store = tmp_path / "parts_mutant"
    parts(mutant=True)
    assert json.loads((store / "results" / "S3-01-C-B.json").read_text())["attempt"] == 1
    store = tmp_path / "pilot_mutant"
    launched = torn_then_twice(store, pilot, "run_S0-01_0", "in_flight_offline.0.jsonl")
    assert "run_S0-01_0" in launched  # a third attempt: what the guard prevents


def test_the_pilot_reads_every_parts_results(tmp_path, monkeypatch):
    """Nit: runs finished under 0/2 and 1/2 are not run again under 0/1."""
    from scripts import p2_pilot

    for part in ("0/2", "1/2"):
        FakeDriver({}).install(monkeypatch)
        p2_pilot._runs(tmp_path, live=False, part=part)
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(tmp_path, live=False, part="0/1")
    assert driver.launched == []
    # the mutation: reading only the part's own files reruns part 1/2's three runs
    monkeypatch.setattr(p2_pilot, "settled", lambda store, live: p2_pilot._cells_in(
        [store / "results_offline.0.jsonl", store / "unfinished_offline.0.jsonl"]))  # fmt: skip
    p2_pilot._runs(tmp_path, live=False, part="0/1")
    assert len(driver.launched) == 3


def test_the_power_run_stops_on_a_torn_line_that_names_no_cell(tmp_path, monkeypatch):
    """Nit: an unknown cell's in-flight attempt stops the power run; no cell is run."""
    from scripts import p2_power

    tmp_path.joinpath("in_flight.1.jsonl").write_text('{"ce')
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_power.run(tmp_path)
    assert driver.launched == []
    # the mutation: a torn line read as some other, named cell lets the run go ahead
    elsewhere = {"cell": "<elsewhere>", "replicate": 0, "attempt": 1, "run_id": None}
    monkeypatch.setattr(p2_rerun.InFlight, "_torn", staticmethod(lambda raw: dict(elsewhere)))
    p2_power.run(tmp_path)
    assert len(driver.launched) == len(p2_power.CELLS)


# ------------------------------------------------------------------ B4 (2026-10-19)


def test_a_torn_return_line_is_not_an_extra_attempt(tmp_path, monkeypatch):
    """N-b: attempt 1 failed and its return line is torn; the cell still gets its rerun."""
    from scripts import p2_pilot

    first = "run_S0-01_0"
    store = tmp_path / "store"

    def torn_return(store: Path) -> None:
        FailsThenStops({}).install(monkeypatch)  # attempt 1 fails, attempt 2 is stopped
        with pytest.raises(KeyboardInterrupt):
            p2_pilot._runs(store, live=False)
        journal = store / "in_flight_offline.0.jsonl"
        lines = [x for x in journal.read_text().splitlines() if '"run_S0-01_0"' in x
                 or '"S0-01 B/B", "replicate": 0' in x]  # fmt: skip
        start1, returned1 = lines[0], lines[1]
        assert '"event": "returned"' in returned1
        # the journal as a crash inside attempt 1's return line leaves it, torn before its
        # attempt number: one start, the fragment, and nothing of attempt 2
        journal.write_text(start1 + "\n" + returned1[: returned1.index('"event"') + 5])

    torn_return(store)
    orphans = p2_rerun.InFlight(store / "in_flight_offline.0.jsonl").orphans(set())
    assert [a["attempt"] for a in orphans[("S0-01 B/B", 0)]] == [1]  # one attempt, not two
    driver = StopsDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(store, live=False)
    assert driver.launched.count(first) == 1  # its one rerun
    rows = _lines(store / "results_offline.0.jsonl")
    assert [r["attempt"] for r in rows if r["run_id"] == first] == [2]
    # the control (fail-safe kept): a torn line after a RETURNED attempt is a new attempt
    # in flight, so an offline cell with it gets no further launch
    journal = tmp_path / "j.jsonl"
    j = p2_rerun.InFlight(journal)
    j.start("S0-01 B/B", 0, 1, first)
    j.finish("S0-01 B/B", 0, 1, first, {"completed": False, "error": "e", "failure_reason": "x"})
    with journal.open("a") as fh:
        fh.write('{"cell": "S0-01 B/B", "replicate": 0, "ev')
    assert [a["attempt"] for a in j.orphans(set())[("S0-01 B/B", 0)]] == [1, 2]
    # and live is unchanged: any journalled attempt is recorded and the pilot stops
    live = tmp_path / "live"
    live.mkdir()
    (live / "in_flight.jsonl").write_text(
        '{"cell": "S0-01 B/B", "replicate": 0, "event": "start", "attempt": 1, '
        '"run_id": "run_S0-01_0"}\n{"cell": "S0-01 B/B", "replicate": 0, "ev'
    )
    driver = FakeDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(live, live=True)
    assert driver.launched == [] and _lines(live / "unfinished.jsonl")
    # the mutation: the pre-B4 reading counts the torn return line as attempt 2, and the
    # cell loses its rerun
    original = p2_rerun.InFlight.orphans

    def counts_every_torn_line(self: Any, settled: Any) -> Any:
        out = original(self, settled)
        for path in self.paths:
            text = path.read_text() if path.is_file() else ""
            if text and not text.endswith("\n"):
                for k, v in out.items():
                    if k[0] in text.rsplit("\n", 1)[-1]:
                        v.append({**v[-1], "attempt": v[-1]["attempt"] + 1})
        return out

    store = tmp_path / "mutant"
    torn_return(store)
    monkeypatch.setattr(p2_rerun.InFlight, "orphans", counts_every_torn_line)
    driver = StopsDriver({})
    driver.install(monkeypatch)
    p2_pilot._runs(store, live=False)
    assert first not in driver.launched  # no rerun: what B4 fixes


def test_a_refused_live_start_leaves_no_empty_unfinished_file(tmp_path, monkeypatch):
    """N-e: nothing stopped, nothing written."""
    from scripts import p2_pilot

    def refuse(*a: Any, **kw: Any) -> None:
        raise ValueError("no approval for this store")

    monkeypatch.setattr("tools.p2_live.require_live_approval", refuse)
    for store, journal in ((tmp_path / "fresh", None),
                           (tmp_path / "settled", "a finished cell's journal")):  # fmt: skip
        store.mkdir()
        if journal:
            j = p2_rerun.InFlight(store / "in_flight.jsonl")
            j.start("S0-01 B/B", 0, 1, "run_S0-01_0")
            (store / "results.jsonl").write_text(
                json.dumps({"cell": "S0-01 B/B", "replicate": 0}) + "\n"
            )
        with pytest.raises(SystemExit, match="not approved"):
            p2_pilot.run(store, live=True)
        assert not (store / "unfinished.jsonl").exists(), store.name
    # the control: a stopped run is still recorded (SF-1 of the review of 0b9f210)
    StopsDriver({"run_S0-01_0": 1}).install(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        p2_pilot._runs(tmp_path / "stopped", live=True)
    with pytest.raises(SystemExit):
        p2_pilot.run(tmp_path / "stopped", live=True)
    assert len(_lines(tmp_path / "stopped" / "unfinished.jsonl")) == 1


def test_results_and_unfinished_records_are_synced_like_the_journal(tmp_path, monkeypatch):
    """B4: every result and unfinished record is flushed and synced as it is written."""
    from scripts import p2_pilot, p2_power

    synced: list[int] = []
    real = p2_rerun.os.fsync
    real_append = p2_rerun.append_synced
    monkeypatch.setattr(p2_rerun.os, "fsync", lambda fd: (synced.append(fd), real(fd)))
    FakeDriver({"run_S0-01_0": 2}).install(monkeypatch)
    p2_pilot._runs(tmp_path / "pilot", live=False)  # stops after S0-01 r0 fails twice
    journal = len((tmp_path / "pilot" / "in_flight_offline.0.jsonl").read_text().splitlines())
    assert len(synced) == journal + 1  # the journal's lines and the one unfinished record
    synced.clear()
    FakeDriver({}).install(monkeypatch)
    p2_pilot._runs(tmp_path / "pilot", live=False)  # the other five, each a result
    assert len(synced) == 5 * 2 + 5  # a start and a return line, and a result, each
    synced.clear()
    FakeDriver({}).install(monkeypatch)
    p2_power.run(tmp_path / "power")
    assert len(synced) == 3 * len(p2_power.CELLS)
    assert not list((tmp_path / "power" / "results").glob("*.tmp"))
    # the mutation: the drivers' records appended plainly, as before B4; only the
    # journal's lines are synced then

    def plain(path: Path, text: str) -> None:
        with Path(path).open("a", encoding="utf-8") as fh:
            fh.write(text)

    monkeypatch.setattr(p2_rerun, "append_synced", plain)

    def journal_synced(self: Any, line: dict[str, Any]) -> None:
        real_append(self.path, json.dumps(line) + "\n")

    monkeypatch.setattr(p2_rerun.InFlight, "_write", journal_synced)
    synced.clear()
    FakeDriver({}).install(monkeypatch)
    p2_pilot._runs(tmp_path / "mutant", live=False)
    assert len(synced) == 6 * 2  # the six results were not synced
