"""P2's live wiring (deliverable 3): no test here reaches a model or the network.

1. F-B: the signatures come from the reference fit on the raw record, never from a subset
   fit a decision chose (a scripted ``ident.subset``), with a negative control.
2. F-E, the model block: P1's frozen settings exactly; the caps are declared.
3. F-E, the gateway: only a frozen decision's request is sent; requests, tokens and USD
   are projected and refused before sending; every attempt is logged with its point and
   role; a cap stops the run, which abstains.
4. F-E, the template freeze: a changed template, schema or tool is refused, offline too.
5. F-E, live mode: OFF by default; the default reaches no model (no gateway, the offline
   decider), and only the explicit flag builds the gateway.
6. The pilot: prepared, refused until approved, before any client is built.
"""

from __future__ import annotations

import json
import shutil
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from state.task_state import TaskState
from tests.p2_support import FakeTools
from tools.llm import GatewayRefusal, ModelError, ScriptedClient
from tools.p2_live import P2Gateway, check_p2_frozen, frozen_digests
from tools.workflow_config import DECISION_POINTS, load_p1, load_p2, sandbox_config
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg() -> dict[str, Any]:
    """The sandbox document of an offline P2 run."""
    return json.loads(json.dumps(sandbox_config(load_p2())))


def run_fake(monkeypatch, cfg, fake=None, respond=wf.offline_responder):
    fake = fake or FakeTools()
    monkeypatch.setattr(wf, "tools", fake)
    run = wf.Workflow(json.loads(json.dumps(cfg)), respond)
    run.run()
    doc = json.loads(fake.run.outputs[wf.STATE_FILE])
    TaskState.model_validate(doc)
    return run, fake, doc


# ------------------------------------------------------------------ 1. F-B


class SubsetSensitive(FakeTools):
    """A fake whose prediction moves only when the subset fit's lone parameter is set."""

    marker: str = ""

    def _simulate(self, model: str, parameters: dict | None = None, **kw: Any) -> Any:
        out = super()._simulate(model, parameters, **kw)
        if self.marker and set(parameters or {}) == {self.marker}:
            out.outputs = {k: v + 50.0 * abs(v) for k, v in out.outputs.items()}
        return out


def test_the_signatures_come_from_the_reference_fit_not_a_chosen_subset(monkeypatch, cfg):
    """The review's F-B: a scripted ``ident.subset`` moves the prediction, not the signatures."""
    base, _fake, _doc = run_fake(monkeypatch, cfg)
    kept = base.screening["morris_kept"]
    marker = kept[-1]

    # a scripted ident.subset: two parameters the schema accepts, whose fit (below)
    # simulates with the marker alone, so the chosen subset's prediction moves
    def subset(point: str, template: str, inputs: dict[str, Any]) -> Any:
        if point == "ident.subset":
            return {"parameters": [marker, kept[-2]]}
        return None

    fake = SubsetSensitive()
    fake.marker = marker

    def fit(parameters: Any, max_nfev_per_start: int = 40, **kw: Any) -> Any:
        out = FakeTools._fit_lsq(fake, parameters, max_nfev_per_start, **kw)
        if list(parameters) == [marker, kept[-2]]:  # the chosen subset's fit, alone
            out.parameters, out.theta, out.sd = [marker], np.ones(1), np.full(1, 0.1)
        return out

    monkeypatch.setattr(fake, "_fit_lsq", fit)
    run, fake, _doc = run_fake(monkeypatch, cfg, fake, subset)
    # the chosen subset was fitted and accepted: the current prediction moved
    assert run.prediction is not run.reference_prediction
    gas = next(s for s in run.series.values() if s.name == "gas_flow")
    moved = np.asarray(run.prediction.outputs[gas.channel])
    ref = np.asarray(run.reference_prediction.outputs[gas.channel])
    assert not np.allclose(moved, ref)

    # every signature input is the reference fit's: the residuals, the early/late test,
    # the change point, R3, the feed covariate and the hold-out bit equal the base run's
    def summaries(r: wf.Workflow) -> dict[str, Any]:
        # every residual statistic; the call index differs (the subset fit adds calls)
        return {
            n: {k: v for k, v in x.items() if k != "call_index"} for n, x in r.residuals.items()
        }

    assert summaries(run) == summaries(base)
    for key in ("early_late", "change_point", "change_point_tied", "r3", "r3_channels",
                "feed_covariate", "biomass_improves", "holdout_failed"):  # fmt: skip
        assert run.signatures.get(key) == base.signatures.get(key), key
    assert run.tables["holdout"]["rms_z"] == base.tables["holdout"]["rms_z"]
    # the biomass pair runs at the reference optimum, not the chosen subset's: drive the
    # state test with a channel that fires early and is clean late
    attr = cfg["p0"]["attribution"]
    run.residuals = {"gas_flow": {**run.residuals["gas_flow"],
                                  "early_bias_z": 2 * float(attr["state_bias_z"]),
                                  "late_bias_z": 0.0}}  # fmt: skip
    n = len(fake.calls)
    run.step_state_test()
    pair = [a for name, a in fake.calls[n:] if name == "simulate" and a.get("biomass_scale")]
    assert len(pair) == 2
    assert all(a["parameters"] == run.reference_optimum for a in pair)
    assert run.optimum != run.reference_optimum  # the subset's optimum is another vector
    # the negative control: the same residual arithmetic against the chosen subset's
    # prediction is far from the reference's (what F-B forbids reading)
    m = np.isfinite(gas.raw) & (gas.t >= run.cal[0]) & (gas.t <= run.cal[1])
    t_pred = np.asarray(run.prediction.t, dtype=float)
    off = gas.raw[m] - np.interp(gas.t[m], t_pred, moved)
    on = gas.raw[m] - np.interp(gas.t[m], t_pred, ref)
    assert abs(np.mean(off)) > 10 * abs(np.mean(on)) + 1.0


# ------------------------------------------------------------------ 2. the model block


def test_the_model_block_is_the_frozen_p1s_and_the_caps_are_declared():
    p1, p2 = load_p1(), load_p2()
    assert p2.model == p1.model
    assert p2.model.model_id == "gpt-5.6-luna" and p2.model.effort == "high"
    assert p2.model.temperature is None
    assert p2.caps.max_requests == p1.loop.max_turns
    assert p2.caps.max_total_tokens == p1.loop.max_total_tokens
    assert 0 < p2.caps.max_usd <= 0.5
    frozen = check_p2_frozen(p2)
    assert (frozen.model_id, frozen.effort, frozen.max_tokens) == (
        p1.frozen.model_id,
        p1.frozen.effort,
        p1.frozen.max_tokens,
    )
    assert frozen.retry == p1.frozen.retry


# ------------------------------------------------------------------ 3. the gateway


def _request(point: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the live responder sends for ``point``."""
    templates = sandbox_config(load_p2())["templates"]
    return {
        "system": templates[point]["text"],
        "messages": [{"role": "user", "content": json.dumps(inputs or {}, sort_keys=True)}],
        "tools": [wf.decision_tool(point)],
    }


def _answer(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "tool_use", "id": "t1", "name": name, "input": payload}],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 1000, "output_tokens": 500}}  # fmt: skip


def _gateway(tmp_path: Path, policy: Any, **caps: Any) -> P2Gateway:
    config = load_p2()
    if caps:
        config = config.model_copy(update={"caps": config.caps.model_copy(update=caps)})
    return P2Gateway.for_config(config, client=ScriptedClient(policy), log_dir=tmp_path)


def test_the_gateway_sends_only_a_frozen_decisions_request_and_logs_point_and_role(tmp_path):
    sent: list[dict[str, Any]] = []

    def policy(params: dict[str, Any]) -> dict[str, Any]:
        sent.append(params)
        return _answer("dq_coupled", {"sensor": "gas_flow", "code": "coupled_inside"})

    gw = _gateway(tmp_path, policy)
    out = gw.complete(_request("dq.coupled", {"s1_table": {}, "assays": []}))
    assert out["response"]["content"][0]["input"]["code"] == "coupled_inside"
    assert len(sent) == 1 and sent[0]["model"] == "gpt-5.6-luna"
    assert sent[0]["output_config"] == {"effort": "high"}
    line = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[0])
    assert line["provenance"]["point"] == "dq.coupled"
    assert line["provenance"]["role"] == "data_quality"
    assert gw.by_role["data_quality"] == {"tokens": 1500, "requests": 1}
    # refused before sending: another system prompt, another tool, two messages, a key
    bad = [
        {**_request("dq.coupled"), "system": "You are a helpful assistant."},
        {**_request("dq.coupled"), "tools": [wf.decision_tool("cal.bound")]},
        {
            **_request("dq.coupled"),
            "messages": [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
                {"role": "user", "content": "c"},
            ],
        },
        {**_request("dq.coupled"), "tool_choice": {"type": "any"}},
    ]
    for req in bad:
        with pytest.raises(ModelError):
            gw.complete(req)
    assert len(sent) == 1  # nothing else reached the client


@pytest.mark.parametrize("cap", ["requests", "tokens", "USD"])
def test_a_request_that_would_pass_a_cap_is_refused_before_it_is_sent(tmp_path, cap):
    sent: list[int] = []

    def policy(params: dict[str, Any]) -> dict[str, Any]:
        sent.append(1)
        return _answer("cal_bound", {"code": "identifiability_limit"})  # 1000 in, 500 out

    req = _request("cal.bound", {"parameter": "k", "bounds": [0, 1], "estimate": 1, "sd": 0.1})
    tokens, usd = _gateway(tmp_path / "probe", policy).projected(req)
    used_usd = (1000 * 0.20 + 500 * 1.20) / 1e6  # two answered requests cost twice this
    # caps at which two requests fit and the third's projection does not
    caps = {
        "requests": {"max_requests": 2},
        "tokens": {"max_total_tokens": 2 * 1500 + tokens - 1},
        "USD": {"max_usd": 2 * used_usd + usd - 1e-9},
    }[cap]
    sent.clear()
    gw = _gateway(tmp_path, policy, **caps)
    gw.complete(req)
    gw.complete(req)
    with pytest.raises(GatewayRefusal):
        gw.complete(req)
    assert len(sent) == 2  # the refused request was never sent
    lines = (tmp_path / "llm_calls.jsonl").read_text().splitlines()
    assert len(lines) == 2  # and never logged as an attempt
    # the projection is the worst case: the full max_tokens of output, every time
    assert tokens > 16000 and usd > 16000 * 1.20 / 1e6
    # the negative control: the same three requests under the declared caps all go
    sent.clear()
    gw = _gateway(tmp_path / "ok", policy)
    for _ in range(3):
        gw.complete(req)
    assert len(sent) == 3


class LiveFake(FakeTools):
    """The fake registry with ``tools.llm`` served by a real P2 gateway (no network)."""

    gateway: P2Gateway | None = None

    def llm(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.gateway.complete(request)
        except GatewayRefusal as exc:
            raise self.BudgetExceededError(str(exc)) from exc
        except ModelError as exc:
            raise self.ToolError(str(exc)) from exc


def test_a_live_run_records_every_attempt_and_a_cap_makes_it_abstain(monkeypatch, cfg, tmp_path):
    def policy(params: dict[str, Any]) -> dict[str, Any]:
        name = params["tools"][0]["name"]
        if name == "cal_bound":
            return _answer(name, {"code": "identifiability_limit"})
        return {"content": [{"type": "text", "text": "I think it is fine."}],
                "stop_reason": "end_turn"}  # fmt: skip

    live_cfg = json.loads(json.dumps(sandbox_config(load_p2(), live=True)))
    assert live_cfg["decider"] == "live"
    fake = LiveFake()
    fake.gateway = _gateway(tmp_path, policy)
    run, fake, doc = run_fake(monkeypatch, live_cfg, fake, wf.LiveResponder())
    records = [json.loads(x) for x in fake.run.outputs[wf.DECISIONS_FILE].splitlines()]
    asked = [r for r in records if r["point"] != "cal.bound"]
    assert asked and all(r["attempts"] == 2 and r["fallback_used"] for r in asked)
    assert all(r["failures"] == ["no decision call in the reply"] * 2 for r in asked)
    assert all(len(r["llm_call_ids"]) == 2 for r in records)
    n_log = len((tmp_path / "llm_calls.jsonl").read_text().splitlines())
    assert n_log == sum(len(r["llm_call_ids"]) for r in records)
    assert doc["final"]["completed"] and run.verdict["verdict"] != "abstain"
    # a cap reached mid-run: the run stops asking and abstains, and says so
    fake = LiveFake()
    fake.gateway = _gateway(tmp_path / "capped", policy, max_requests=3)
    run, fake, doc = run_fake(monkeypatch, live_cfg, fake, wf.LiveResponder())
    assert run.verdict["verdict"] == "abstain" and run.verdict["reason"] == "model_cap"
    assert doc["classification"]["rule"] == "abstain:model_cap"
    assert json.loads(fake.run.outputs[wf.REPORT_FILE])["outcome"] == "abstain"
    assert fake.gateway.meter.requests == 3


# ------------------------------------------------------------------ 4. the template freeze


def _copy_config(tmp_path: Path) -> Path:
    dest = tmp_path / "workflows"
    shutil.copytree(REPO / "configs" / "workflows", dest)
    return dest / "p2.yaml"


def test_a_changed_template_schema_or_tool_is_refused(tmp_path, monkeypatch):
    path = _copy_config(tmp_path)
    assert check_p2_frozen(load_p2(path)).date  # the negative control: unchanged passes
    template = path.parent / load_p2(path).templates["dq.coupled"]
    template.write_text(template.read_text() + "\nBe decisive.\n")
    with pytest.raises(ValueError, match=r"template of 'dq\.coupled'"):
        check_p2_frozen(load_p2(path))
    # and the runner refuses the run before anything is launched, offline included
    from tools import runner

    def never(*a: Any, **k: Any) -> Any:
        raise AssertionError("the registry was opened")

    monkeypatch.setattr(runner, "open_registry", never)
    with pytest.raises(ValueError, match="not the frozen one"):
        runner.run_workflow("run_x", "p2", config_path=path, runs_root=tmp_path / "runs")
    # a schema or a tool changed in the workflow's code is refused too
    monkeypatch.setitem(wf.DECISIONS["cal.bound"], "model", wf.CalAccept)
    with pytest.raises(ValueError, match=r"schema of 'cal\.bound'"):
        check_p2_frozen(load_p2())
    assert set(frozen_digests(load_p2())["tools"]) == set(DECISION_POINTS)


# ------------------------------------------------------------------ 5. live mode


def test_the_default_reaches_no_model(monkeypatch, cfg, tmp_path):
    """Offline is the default everywhere: the config, the jail document, the runner."""
    assert load_p2().decider == "offline"
    assert cfg["decider"] == "offline"
    assert not {"model", "caps", "frozen"} & set(cfg)  # privileged side only
    # the workflow's own choice: offline unless the jail document says live
    assert wf.responder_for(cfg) is wf.offline_responder
    assert isinstance(wf.responder_for({**cfg, "decider": "live"}), wf.LiveResponder)

    # an offline run never asks the model, even with a model behind tools.llm
    class Tripwire(FakeTools):
        def llm(self, request: dict[str, Any]) -> dict[str, Any]:
            raise AssertionError("the offline decider reached a model")

    run, _fake, _doc = run_fake(monkeypatch, cfg, Tripwire(), wf.responder_for(cfg))
    assert all(r["attempts"] == 0 for r in run.decider.records)
    # the runner: no gateway and an offline document unless live=True
    from tools import Budget, make_registry, runner

    seen: dict[str, Any] = {}

    def fake_launch(script: Any, registry: Any, **kw: Any) -> Any:
        seen["gateway"] = kw.get("model_gateway")
        box = kw["sandbox"]
        seen["config"] = json.loads((box / "cwd" / "p2_config.json").read_text())
        return types.SimpleNamespace(returncode=0, stderr="")

    def fake_registry(*a: Any, **k: Any) -> Any:
        return make_registry(budget=Budget(10, 5.0, 0), seed=1)

    monkeypatch.setattr(runner, "launch", fake_launch)
    monkeypatch.setattr(runner, "open_registry", fake_registry)
    monkeypatch.setattr(runner, "p2_live_client", None, raising=False)
    kw = {"runs_root": tmp_path / "runs", "sandbox_root": tmp_path / "boxes"}
    (tmp_path / "runs" / "run_x").mkdir(parents=True)
    runner.run_workflow("run_x", "p2", **kw)
    assert seen["gateway"] is None and seen["config"]["decider"] == "offline"
    # a model client without the flag is refused: offline reaches no model
    with pytest.raises(ValueError, match="without the live flag"):
        runner.run_workflow("run_x", "p2", model_client=ScriptedClient(lambda p: {}), **kw)
    # the flag is P2's alone
    with pytest.raises(ValueError, match="P2's"):
        runner.run_workflow("run_x", "p0", live=True, **kw)
    # only the explicit flag builds the gateway (a scripted client: still no network)
    summary = runner.run_workflow(
        "run_x", "p2", live=True, model_client=ScriptedClient(lambda p: {}), **kw
    )
    assert isinstance(seen["gateway"], P2Gateway) and seen["config"]["decider"] == "live"
    assert summary.decider == "live" and summary.templates_sha256


# ------------------------------------------------------------------ 6. the pilot


def test_the_pilot_is_prepared_and_refused_until_approved(tmp_path, monkeypatch):
    from scripts import p2_pilot

    plan = p2_pilot.plan()
    assert plan["approved"] is False and plan["runs"] == 6
    assert "S0-01 B/B" in plan["cells"] and plan["roles_off"] == [
        "design", "identifiability", "influent"
    ]  # fmt: skip
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-key")

    def never(*a: Any, **k: Any) -> Any:
        raise AssertionError("a run was attempted")

    monkeypatch.setattr("tools.runner.run_workflow", never)
    with pytest.raises(SystemExit, match="not approved"):
        p2_pilot.run(tmp_path, live=True)
    # the negative control: approval alone is not enough without --live
    monkeypatch.setattr(p2_pilot, "APPROVED", True)
    with pytest.raises(SystemExit, match="--live"):
        p2_pilot.run(tmp_path, live=False)
    # the pilot's configuration is the frozen one with the three-role ablation
    path = p2_pilot.write_config(tmp_path)
    pilot = load_p2(path)
    assert check_p2_frozen(pilot).date
    assert not any(pilot.ablation.roles.model_dump()[r] for r in p2_pilot.THREE_ROLES)
    assert pilot.ablation.roles.data_quality and pilot.ablation.roles.calibration
