"""The lead's ruling of 2026-10-13: P2 runs have no wall-clock limit; a budget refusal abstains.

1. The registry never refuses a P2 run on the wall clock, whatever has elapsed; the
   negative control is the same registry with the clock enforced, as P0 and P1 have it.
2. The runner opens P2 with the wall clock unenforced and gives the jail no timeout; P0
   and P1 keep the cell's allowance and a timeout (the negative control).
3. P2's evaluation and assay budgets are unchanged and still refuse.
4. A budget refusal at ``step_null`` (the pilot's crash) and at another step ends the run
   as a recorded abstention (``abstain:budget``), never a crash or ``pending``; the
   negative control is the same run without a refusal. A mutation removing the catch
   makes the same run crash.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from state.provenance import read_calls
from state.task_state import TaskState
from tests.p2_support import FakeTools
from tools import AnalyticModel, Budget, BudgetExceededError, make_registry
from tools.llm import ScriptedClient
from tools.workflow_config import load_p0, load_p1, load_p2, sandbox_config
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]
T = np.linspace(0.0, 10.0, 11)


class Clock:
    """A clock the tests advance by hand, seconds."""

    def __init__(self) -> None:
        """Start at an arbitrary instant."""
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _registry(tmp_path: Path, budget: Budget, clock: Clock) -> tuple[Any, Path]:
    model = AnalyticModel(
        name="linear", parameter_names=("a", "b"), defaults=np.array([1.0, 0.0]),
        lower=np.array([-5.0, -5.0]), upper=np.array([5.0, 5.0]),
        function=lambda th: {"y": th[0] * T + th[1]}, output_names=("y",), t=T,
        parameter_units={"a": "1/d", "b": "-"}, output_units={"y": "-"},
    )  # fmt: skip
    run_dir = tmp_path / "runs" / "run_x"
    reg = make_registry(budget=budget, seed=7, run_dir=run_dir,
                        truth_log_dir=tmp_path / "truth_store" / "run_x",
                        models={"linear": model}, clock=clock)  # fmt: skip
    return reg, run_dir


# ------------------------------------------------------------------ 1. the registry


def test_the_registry_never_refuses_p2_on_the_wall_clock(tmp_path):
    clock = Clock()
    reg, run_dir = _registry(tmp_path, Budget(100, 2.0, 0, wall_clock_enforced=False), clock)
    reg.call("simulate", model="linear")
    clock.now += 10 * 3600.0  # ten hours past a two-minute allowance
    reg.call("simulate", model="linear")  # not refused
    left = reg.remaining()
    # nothing of the allowance is consumed, so a time-based guard never shrinks a step
    assert left.wall_clock_min == left.wall_clock_min_total == pytest.approx(2.0)
    calls = read_calls(run_dir)
    assert [c.outcome for c in calls] == ["ok", "ok", "ok"]
    assert "no wall-clock limit" in calls[0].detail  # the open record says so

    # the negative control: the same calls with the clock enforced (P0, P1) are refused
    clock = Clock()
    reg, run_dir = _registry(tmp_path / "enforced", Budget(100, 2.0, 0), clock)
    reg.call("simulate", model="linear")
    clock.now += 10 * 3600.0
    with pytest.raises(BudgetExceededError, match="wall-clock"):
        reg.call("simulate", model="linear")
    assert reg.remaining().wall_clock_min == 0.0
    assert "allowance runs from this record" in read_calls(run_dir)[0].detail


# ------------------------------------------------------------------ 3. the other budgets


def test_p2s_evaluation_and_assay_budgets_still_refuse(tmp_path):
    unlimited = {"wall_clock_enforced": False}
    reg, run_dir = _registry(tmp_path, Budget(2, 60.0, 1, **unlimited), Clock())
    reg.call("simulate", model="linear")
    reg.call("simulate", model="linear")
    with pytest.raises(BudgetExceededError, match="simulator evaluations"):
        reg.call("simulate", model="linear")
    # cod_total costs 2 units; 1 is available
    with pytest.raises(BudgetExceededError, match="assay"):
        reg.call("request_assay", assay="cod_total", day=10.0)
    assert [c.outcome for c in read_calls(run_dir)][-2:] == ["budget_exceeded"] * 2
    # the negative control: inside both budgets the same calls are served
    reg, _ = _registry(tmp_path / "inside", Budget(3, 60.0, 1, **unlimited), Clock())
    for _ in range(3):
        reg.call("simulate", model="linear")
    assert reg.remaining().simulator_evals == 0


# ------------------------------------------------------------------ 2. the runner


def test_the_runner_opens_p2_without_a_wall_clock_and_p0_p1_with_one(tmp_path, monkeypatch):
    from tools import runner

    assert load_p2().runner.wall_clock_limit is False
    seen: dict[str, Any] = {}

    def fake_launch(script: Any, registry: Any, **kw: Any) -> Any:
        seen["timeout_s"] = kw["timeout_s"]
        return types.SimpleNamespace(returncode=0, stderr="")

    def fake_registry(*a: Any, **k: Any) -> Any:
        seen["enforced"] = k.get("wall_clock_enforced", True)
        return make_registry(budget=Budget(10, 90.0, 0, **{
            "wall_clock_enforced": seen["enforced"]}), seed=1)  # fmt: skip

    monkeypatch.setattr(runner, "launch", fake_launch)
    monkeypatch.setattr(runner, "open_registry", fake_registry)
    kw = {"runs_root": tmp_path / "runs", "sandbox_root": tmp_path / "boxes"}
    (tmp_path / "runs" / "run_x").mkdir(parents=True)

    runner.run_workflow("run_x", "p2", **kw)
    assert seen == {"enforced": False, "timeout_s": None}
    # the negative controls: P0 and P1 keep the cell's allowance and the jail's timeout
    runner.run_workflow("run_x", "p0", **kw)
    assert seen["enforced"] is True
    assert seen["timeout_s"] == pytest.approx((90.0 + load_p0().runner.timeout_margin_min) * 60)
    runner.run_workflow("run_x", "p1", model_client=ScriptedClient(lambda p: {}), **kw)
    assert seen["enforced"] is True
    assert seen["timeout_s"] == pytest.approx((90.0 + load_p1().runner.timeout_margin_min) * 60)
    # a caller may still bound a P2 run explicitly (tests); the default is no timeout
    runner.run_workflow("run_x", "p2", timeout_s=30.0, **kw)
    assert seen == {"enforced": False, "timeout_s": 30.0}


def test_p2s_configuration_accepts_no_wall_clock_limit(tmp_path):
    import yaml
    from pydantic import ValidationError

    from tools.workflow_config import P2Config

    raw = yaml.safe_load((REPO / "configs" / "workflows" / "p2.yaml").read_text())
    P2Config.model_validate(raw)  # the committed file: no limit
    for runner_block in ({"wall_clock_limit": True}, {"timeout_margin_min": 15.0}):
        with pytest.raises(ValidationError):
            P2Config.model_validate({**raw, "runner": runner_block})


# ------------------------------------------------------------------ 4. the crash fix


@pytest.fixture(scope="module")
def cfg() -> dict[str, Any]:
    """The sandbox document of an offline P2 run."""
    return json.loads(json.dumps(sandbox_config(load_p2())))


class Refuses(FakeTools):
    """A fake registry that refuses the ``nth`` call of ``tool`` for lack of budget."""

    def __init__(self, tool: str, nth: int = 1) -> None:
        """Refuse ``tool`` on its ``nth`` call."""
        super().__init__()
        self.tool, self.nth, self.seen = tool, nth, 0

    def call(self, name: str, **args: Any) -> Any:
        if name == self.tool:
            self.seen += 1
            if self.seen == self.nth:
                self.calls.append((name, args))
                self.used["calls"] += 1
                self._last = {"seq": self.used["calls"] - 1, "args_hash": "h",
                              "version": "1.0", "outcome": "budget_exceeded"}  # fmt: skip
                raise self.BudgetExceededError(f"{name}: 0 of 450 simulator evaluations remain")
        return super().call(name, **args)


def _run(module: Any, monkeypatch: pytest.MonkeyPatch, cfg: dict, fake: FakeTools) -> Any:
    monkeypatch.setattr(module, "tools", fake)
    run = module.Workflow(json.loads(json.dumps(cfg)), module.offline_responder)
    run.run()
    return run


@pytest.mark.parametrize(
    ("tool", "nth", "step"),
    [
        ("declared_background", 2, "step_null"),  # the pilot's crash (workflow.py, step_null)
        ("simulate", 1, "step_read"),  # the default prediction, the run's first evaluation
    ],
)
def test_a_budget_refusal_at_any_step_abstains(monkeypatch, cfg, tool, nth, step):
    fake = Refuses(tool, nth)
    run = _run(wf, monkeypatch, cfg, fake)
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    TaskState.model_validate(doc)
    report = json.loads(fake.run.outputs[wf.REPORT_FILE])
    assert run.completed and doc["final"]["completed"]
    assert report["outcome"] == "abstain" and doc["classification"]["rule"] == "abstain:budget"
    assert doc["final"]["label"] == doc["classification"]["label"] == "abstain"  # N-2b
    assert run.verdict["reason"] == "budget" and "budget" in doc["plan"]["fallbacks"]
    assert any(a.startswith("budget refused after") for a in doc["annotations"])
    refused = [a for a in doc["actions"] if a["outcome"] == "budget_exceeded"]
    assert [a["name"] for a in refused] == [tool]
    # the refusal came where the case says: the step's predecessor finished, it did not
    finished = {"step_null": "reference", "step_read": None}[step]
    assert finished is None or finished in doc["plan"]["steps_completed"]
    # the negative control: the same run without a refusal does not abstain on budget
    clean = FakeTools()
    run = _run(wf, monkeypatch, cfg, clean)
    report = json.loads(clean.run.outputs[wf.REPORT_FILE])
    assert report["outcome"] == "none" and run.verdict.get("reason") is None


def test_removing_the_catch_makes_the_pilots_refusal_crash(monkeypatch, cfg, tmp_path):
    """The mutation: the workflow without its ``BudgetExceededError`` clause crashes."""
    import importlib.util

    source = (REPO / "workflows" / "p2_multi_agent" / "workflow.py").read_text(encoding="utf-8")
    clause = re.compile(
        r"\n        except tools\.BudgetExceededError as exc:\n"
        r"            self\.codes\.append\(\"budget\"\)\n.*?\n            \}\n",
        re.S,
    )
    mutated, n = clause.subn("\n", source, count=1)
    assert n == 1, "the catch was not found where the mutation expects it"
    path = tmp_path / "workflow_mutated.py"
    path.write_text(mutated, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("workflow_mutated", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "workflow_mutated", module)  # pydantic resolves by it
    spec.loader.exec_module(module)
    with pytest.raises(FakeTools.BudgetExceededError):
        _run(module, monkeypatch, cfg, Refuses("declared_background", 2))
    # the unmutated module, on the same refusal, abstains
    assert _run(wf, monkeypatch, cfg, Refuses("declared_background", 2)).verdict["reason"] == (
        "budget"
    )


# ------------------------------------------------------------------ S-1: the real wiring


@pytest.fixture(scope="module")
def short_run(tmp_path_factory):
    """A short generated S0-01 run (plant C, tier B) and its store."""
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run

    s = load_scenario(REPO / "scenarios" / "S0-01.yaml").model_copy(update={"duration_days": 20.0})
    root = tmp_path_factory.mktemp("store") / "runs"
    run = generate_run(s, "B", plant=load_plant_config("C"), runs_root=root)
    return run, s, root


def test_the_real_open_registry_carries_the_ruling(short_run, monkeypatch, tmp_path):
    """The review of ``7ef1238``, S-1: ``tools.privileged.open_registry`` itself, no fake."""
    from tools import runner
    from tools.privileged import open_registry

    run, scenario, root = short_run
    past = (scenario.budget.wall_clock_min + 60.0) * 60.0  # an hour past the allowance
    clock = Clock()
    reg = open_registry(run.run_id, runs_root=root, scenario=scenario, clock=clock,
                        wall_clock_enforced=False)  # fmt: skip
    assert reg.budget.wall_clock_enforced is False
    clock.now += past
    reg.call("describe_model", model="adm1_fitted")  # served
    # the negative control: the same run, enforced, is refused
    clock = Clock()
    reg = open_registry(run.run_id, runs_root=root, scenario=scenario, clock=clock)
    assert reg.budget.wall_clock_enforced is True
    clock.now += past
    with pytest.raises(BudgetExceededError, match="wall-clock"):
        reg.call("describe_model", model="adm1_fitted")

    # and through the runner: the real open_registry, only its clock injected
    outcome: dict[str, str] = {}

    def opened(*a: Any, **k: Any) -> Any:
        outcome["clock"] = clock = Clock()  # type: ignore[assignment]
        return open_registry(*a, clock=clock, **k)

    def fake_launch(script: Any, registry: Any, **kw: Any) -> Any:
        outcome["clock"].now += past  # type: ignore[attr-defined]
        try:
            registry.call("describe_model", model="adm1_fitted")
            outcome["call"] = "served"
        except BudgetExceededError:
            outcome["call"] = "refused"
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(runner, "open_registry", opened)
    monkeypatch.setattr(runner, "launch", fake_launch)
    kw = {"runs_root": root, "scenario": scenario, "sandbox_root": tmp_path / "boxes"}
    runner.run_workflow(run.run_id, "p2", **kw)
    assert outcome["call"] == "served"
    runner.run_workflow(run.run_id, "p0", output_name="p0_control", **kw)  # the control
    assert outcome["call"] == "refused"


# ------------------------------------------------------------------ nits of 7ef1238


def test_p2s_own_record_does_not_report_a_wall_clock_it_cannot_measure(monkeypatch, cfg):
    """Nit 1: no 0 s per role and no unexplained 90 min left; the control is a limited run."""
    fake = FakeTools()
    _run(wf, monkeypatch, cfg, fake)
    report = json.loads(fake.run.outputs[wf.REPORT_FILE])
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    assert report["by_role"] and all(u["wall_clock_s"] is None for u in report["by_role"].values())
    assert report["wall_clock"] == wf.UNLIMITED_NOTE and wf.UNLIMITED_NOTE in doc["annotations"]
    limited = json.loads(json.dumps(cfg))
    limited["runner"] = {"wall_clock_limit": True}
    fake = FakeTools()
    _run(wf, monkeypatch, limited, fake)
    report = json.loads(fake.run.outputs[wf.REPORT_FILE])
    assert all(isinstance(u["wall_clock_s"], float) for u in report["by_role"].values())
    assert wf.UNLIMITED_NOTE not in json.loads(fake.run.outputs[wf.STATE_FILE])["annotations"]


def test_the_pilot_report_copies_each_runs_records_and_reports_wall_s(tmp_path, monkeypatch):
    """Nits 2 and 3: wall_s is the cost column; llm_calls, decisions and calls are copied."""
    from scripts import p2_pilot

    monkeypatch.setattr(p2_pilot, "REPORT_DIR", tmp_path / "reports")
    store = tmp_path / "store"
    out = store / "runs" / "run_a" / "workflows" / "p2"
    out.mkdir(parents=True)
    for name in ("llm_calls.jsonl", "decisions.jsonl"):
        (out / name).write_text(f'{{"file": "{name}"}}\n')
    (store / "runs" / "run_a" / "calls.jsonl").write_text('{"seq": 0}\n')
    row = {"run_id": "run_a", "cell": "S0-01 B/B", "replicate": 0, "truth": ["none"],
           "outcome": "none", "label": "none", "rule": "null_stands",
           "summary": {"completed": True, "llm_cost_usd": 0.002, "llm_turns": 7,
                       "wall_s": 5400.0}}  # fmt: skip
    (store / "results.jsonl").write_text(json.dumps(row) + "\n")
    got = p2_pilot.report(store, "attempt2")
    assert got["rows"][0]["wall_min"] == 90.0
    dest = tmp_path / "reports" / "attempt2"
    assert sorted(p.name for p in (dest / "run_a").iterdir()) == [
        "calls.jsonl", "decisions.jsonl", "llm_calls.jsonl"]  # fmt: skip
    assert "a cost" in (dest / "summary.md").read_text()
    # the control: a run whose records are absent copies nothing and still reports
    row["run_id"] = "run_b"
    (store / "results.jsonl").write_text(json.dumps(row) + "\n")
    p2_pilot.report(store, "attempt3")
    assert not (tmp_path / "reports" / "attempt3" / "run_b").exists()
