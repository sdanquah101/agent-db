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
from tools import p2_live
from tools.llm import GatewayRefusal, ModelError, ScriptedClient
from tools.p2_live import P2Gateway, check_p2_frozen, frozen_digests, frozen_record_sha256
from tools.workflow_config import DECISION_POINTS, load_p1, load_p2, sandbox_config
from workflows.p2_multi_agent import workflow as wf

REPO = Path(__file__).resolve().parents[1]
COMMITTED_FROZEN_SHA256 = "b2fad49a246c6782a6b4e983c0dc3fb97efd573b4c4209b925619c4deddf7468"
"""The digest of the committed ``p2.yaml`` ``frozen`` record (B-4): a new freeze edits it."""


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
    assert frozen.model == p1.model and frozen.caps == p2.caps
    assert (frozen.model.model_id, frozen.model.effort, frozen.model.max_tokens) == (
        p1.frozen.model_id,
        p1.frozen.effort,
        p1.frozen.max_tokens,
    )
    assert frozen.model.retry == p1.frozen.retry
    # the committed record itself is pinned (B-4): its digest is this one
    assert frozen_record_sha256() == COMMITTED_FROZEN_SHA256


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


def _gateway(tmp_path: Path, policy: Any, client: Any = None, **caps: Any) -> P2Gateway:
    """The gateway of the committed configuration; ``caps`` tightened on it afterwards.

    (A configuration with other caps is refused by the freeze, B-4: the test sets the
    tighter caps on the built gateway, as only a test may.)
    """
    gw = P2Gateway.for_config(load_p2(), client=client or ScriptedClient(policy), log_dir=tmp_path)
    names = {"max_requests": "max_turns", "max_total_tokens": "max_total_tokens",
             "max_usd": "max_usd"}  # fmt: skip
    for key, value in caps.items():
        setattr(gw, names[key], value)
    return gw


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
    with pytest.raises(GatewayRefusal, match=r"\[llm_lines=2\]"):
        gw.complete(req)
    assert len(sent) == 2  # the refused request was never sent
    lines = [json.loads(x) for x in (tmp_path / "llm_calls.jsonl").read_text().splitlines()]
    # and it is auditable from the log, as a refusal, not an attempt (N-2c)
    assert len(lines) == 3 and lines[2]["refused"] is True and lines[2]["response"] is None
    assert lines[2]["error"].startswith("refused: cap:")
    assert lines[2]["provenance"]["point"] == "cal.bound"
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
    cited = sorted(i for r in records for i in r["llm_call_ids"])
    assert cited == list(range(n_log))  # every logged attempt, cited exactly once
    assert doc["final"]["completed"] and run.verdict["verdict"] != "abstain"
    # a cap reached mid-run: the run stops asking and abstains, and says so
    fake = LiveFake()
    fake.gateway = _gateway(tmp_path / "capped", policy, max_requests=3)
    run, fake, doc = run_fake(monkeypatch, live_cfg, fake, wf.LiveResponder())
    assert run.verdict["verdict"] == "abstain" and run.verdict["reason"] == "model_cap"
    assert doc["classification"]["rule"] == "abstain:model_cap"
    assert json.loads(fake.run.outputs[wf.REPORT_FILE])["outcome"] == "abstain"
    assert fake.gateway.attempts_sent == 3
    # an abstaining run claims no kinetic update (N-2b)
    assert doc["classification"]["kinetic_update"] is False
    # the interrupted decision is recorded too, and every logged line (the refusal
    # included) is cited by some decision record (N-2a, N-2c)
    records = [json.loads(x) for x in fake.run.outputs[wf.DECISIONS_FILE].splitlines()]
    assert records[-1]["failures"][-1] == "model_cap" and records[-1]["fallback_used"]
    n_log = len((tmp_path / "capped" / "llm_calls.jsonl").read_text().splitlines())
    assert sorted(i for r in records for i in r["llm_call_ids"]) == list(range(n_log))


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

    def no_client(*a: Any, **k: Any) -> Any:
        raise AssertionError("the live client was built")

    monkeypatch.setattr(runner, "launch", fake_launch)
    monkeypatch.setattr(runner, "open_registry", fake_registry)
    monkeypatch.setattr(p2_live, "p2_live_client", no_client)  # a tripwire (N-1a)
    kw = {"runs_root": tmp_path / "runs", "sandbox_root": tmp_path / "boxes"}
    (tmp_path / "runs" / "run_x").mkdir(parents=True)
    offline = runner.run_workflow("run_x", "p2", **kw)
    assert seen["gateway"] is None and seen["config"]["decider"] == "offline"
    assert offline.model_id is None and offline.decider == "offline"  # N-10b
    # a model client without the flag is refused: offline reaches no model
    with pytest.raises(ValueError, match="without the live flag"):
        runner.run_workflow("run_x", "p2", model_client=ScriptedClient(lambda p: {}), **kw)
    # the flag is P2's alone
    with pytest.raises(ValueError, match="P2's"):
        runner.run_workflow("run_x", "p0", live=True, **kw)
    # the flag alone is refused: there is no approval record (B-3)
    with pytest.raises(ValueError, match="no approval record"):
        runner.run_workflow(
            "run_x", "p2", live=True, model_client=ScriptedClient(lambda p: {}), **kw
        )
    # with an approval (stubbed here) the explicit flag builds the gateway; a scripted
    # client, so still no network
    monkeypatch.setattr(p2_live, "require_live_approval", lambda config, cell=None: {})
    monkeypatch.setattr(p2_live, "cell_of", lambda path: {})
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
    with pytest.raises(SystemExit, match="not approved: no approval record"):
        p2_pilot.run(tmp_path, live=True)
    # the negative control: without --live it is refused before the approval is read
    with pytest.raises(SystemExit, match="--live"):
        p2_pilot.run(tmp_path, live=False)
    assert p2_pilot.approval_runs()[0] == {
        "scenario": "S0-01", "plant": "B", "tier": "B", "replicate": 0
    }  # fmt: skip
    # the pilot's configuration is the frozen one with the three-role ablation
    path = p2_pilot.write_config(tmp_path)
    pilot = load_p2(path)
    assert check_p2_frozen(pilot).date
    assert not any(pilot.ablation.roles.model_dump()[r] for r in p2_pilot.THREE_ROLES)
    assert pilot.ablation.roles.data_quality and pilot.ablation.roles.calibration


# ------------------------------------------------------------------ B-1: caps per attempt


def _cal_bound_request() -> dict[str, Any]:
    return _request("cal.bound", {"parameter": "k", "bounds": [0, 1], "estimate": 1, "sd": 0.1})


class Flaky:
    """A client that fails every attempt: retryably, or with a reply it cannot read."""

    name = "flaky"

    def __init__(self, retryable: bool) -> None:
        """Fail every attempt, retryably or not."""
        self.retryable, self.calls = retryable, 0

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        from tools.llm import RetryableModelError

        self.calls += 1
        if self.retryable:
            raise RetryableModelError("429: rate limited")
        raise ModelError("the reply arrived but could not be read (billed)")


def test_every_retry_counts_against_the_request_cap(tmp_path):
    """Retries are attempts (B-1): the request cap holds inside P1's retry loop."""
    client = Flaky(retryable=True)
    gw = _gateway(tmp_path, None, client=client, max_requests=2)
    gw.sleep = lambda s: None
    with pytest.raises(GatewayRefusal):
        gw.complete(_cal_bound_request())
    assert client.calls == 2  # not P1's four attempts: the third was refused unsent
    tokens, usd = gw.projected(_cal_bound_request())
    assert gw.reserved_tokens == 2 * tokens and gw.cost_usd() == pytest.approx(2 * usd)
    lines = [json.loads(x) for x in (tmp_path / "llm_calls.jsonl").read_text().splitlines()]
    assert [bool(x.get("refused")) for x in lines] == [False, False, True]


def test_a_billed_unreadable_reply_is_booked_against_the_usd_and_token_caps(tmp_path):
    """A reply that arrived but could not be read may have been billed (B-1)."""
    req = _cal_bound_request()
    client = Flaky(retryable=False)
    probe = _gateway(tmp_path / "probe", None, client=client)
    tokens, usd = probe.projected(req)
    gw = _gateway(tmp_path, None, client=client, max_usd=1.5 * usd)
    with pytest.raises(ModelError):
        gw.complete(req)
    assert client.calls == 1 and gw.cost_usd() == pytest.approx(usd)  # booked, not 0.0
    with pytest.raises(GatewayRefusal, match="USD"):
        gw.complete(req)  # the booked worst case leaves no room for another
    assert client.calls == 1
    gw = _gateway(tmp_path / "tok", None, client=client, max_total_tokens=int(1.5 * tokens))
    with pytest.raises(ModelError):
        gw.complete(req)
    with pytest.raises(GatewayRefusal, match="tokens"):
        gw.complete(req)
    # the negative control: with room for both, both attempts go
    gw = _gateway(tmp_path / "room", None, client=client)
    for _ in range(2):
        with pytest.raises(ModelError):
            gw.complete(req)
    assert client.calls == 4


# ------------------------------------------------------------------ B-3: the approval


def _record(caps: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    rec = {"ruling_date": "2026-10-12", "word": "test only", "runs": runs, "caps": caps,
           "frozen_sha256": frozen_record_sha256()}  # fmt: skip
    rec["digest"] = p2_live.approval_digest(rec)
    return rec


def test_live_needs_the_leads_committed_approval_on_every_path(tmp_path, monkeypatch):
    import yaml

    from scripts import p2_pilot
    from tools import runner

    config = load_p2()
    assert not p2_live.APPROVAL_FILE.exists()  # not created before the lead's word
    with pytest.raises(ValueError, match="no approval record"):
        p2_live.require_live_approval(config)
    # the command line refuses before any cell is selected
    with pytest.raises(ValueError, match="no approval record"):
        runner.main(["--workflow", "p2", "--live", "--run", "run_x"])
    # a record (in a temporary place, as if committed): the negative control passes
    cell = {"scenario": "S0-01", "plant": "B", "tier": "B", "replicate": 0}
    path = tmp_path / "p2_live_approval.yaml"
    record = _record(config.caps.model_dump(mode="json"), p2_pilot.approval_runs())
    path.write_text(yaml.safe_dump(record))
    monkeypatch.setattr(p2_live, "APPROVAL_FILE", path)
    monkeypatch.setattr(p2_live, "_git_clean", lambda p: (True, ""))
    assert p2_live.require_live_approval(config, cell)["digest"] == record["digest"]
    # a run it does not list
    with pytest.raises(ValueError, match="does not list this run"):
        p2_live.require_live_approval(config, {**cell, "replicate": 2})
    # an uncommitted record or a dirty tree
    monkeypatch.setattr(p2_live, "_git_clean", lambda p: (False, "uncommitted changes"))
    with pytest.raises(ValueError, match="uncommitted"):
        p2_live.require_live_approval(config, cell)
    monkeypatch.setattr(p2_live, "_git_clean", lambda p: (True, ""))
    # a record edited after its digest, other caps, or another freeze
    for edit, why in (
        ({"runs": [*record["runs"], {**cell, "replicate": 9}]}, "digest"),
        ({"caps": {**record["caps"], "max_usd": 5.0}}, "caps"),
        ({"frozen_sha256": "0" * 64}, "freeze"),
    ):
        bad = {**record, **edit}
        if why != "digest":
            bad["digest"] = p2_live.approval_digest(bad)
        path.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValueError, match=why):
            p2_live.require_live_approval(config, cell)
    # the real check reads git: this repository has no record committed
    monkeypatch.undo()
    assert p2_live._git_clean(tmp_path / "nowhere.yaml")[0] is False


# ------------------------------------------------------------------ B-4: the whole freeze


def _edit_yaml(path: Path, fn: Any) -> None:
    import yaml

    raw = yaml.safe_load(path.read_text())
    fn(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


def test_the_whole_model_block_and_the_caps_are_frozen(tmp_path, monkeypatch):
    for name, fn, why in (
        ("price", lambda r: r["model"]["pricing_usd_per_mtok"].update(output=0.6), "model block"),
        ("cap", lambda r: r["caps"].update(max_usd=1.0), "caps block"),
        ("timeout", lambda r: r["model"].update(request_timeout_s=60), "model block"),
        ("chars", lambda r: r["caps"].update(input_chars_per_token=8.0), "caps block"),
    ):
        path = _copy_config(tmp_path / name)
        _edit_yaml(path, fn)
        with pytest.raises(ValueError, match=why):
            check_p2_frozen(load_p2(path))
        # the same edit made in the copy's own frozen record too: not the committed one
        _edit_yaml(path, lambda r, fn=fn: fn(r["frozen"]))
        with pytest.raises(ValueError, match="not the committed one"):
            check_p2_frozen(load_p2(path))
    # an edited template with its hash edited to match (the pilot writes its own copy)
    path = _copy_config(tmp_path / "template")
    template = path.parent / load_p2(path).templates["dq.coupled"]
    template.write_text(template.read_text() + "\nBe decisive.\n")
    fresh = frozen_digests(load_p2(path))["templates"]["dq.coupled"]
    _edit_yaml(path, lambda r: r["frozen"]["templates_sha256"].update({"dq.coupled": fresh}))
    with pytest.raises(ValueError, match="not the committed one"):
        check_p2_frozen(load_p2(path))
    # the P1-equality check runs on the configuration the run uses
    p1 = load_p1()
    other = p1.model_copy(update={"model": p1.model.model_copy(update={"effort": "low"})})
    monkeypatch.setattr("tools.workflow_config.load_p1", lambda *a, **k: other)
    with pytest.raises(ValueError, match="frozen P1's"):
        check_p2_frozen(load_p2())


def test_a_tool_changed_apart_from_its_schema_is_refused(monkeypatch):
    """The freeze covers each decision's tool itself (N-4a): name and description."""
    original = wf.decision_tool
    assert check_p2_frozen(load_p2()).date  # the negative control
    for change in ({"description": "Decide."}, {"name": "dq_coupled_v2"}):

        def changed(point: str, change: dict = change) -> dict[str, Any]:
            tool = original(point)
            return {**tool, **change} if point == "dq.coupled" else tool

        monkeypatch.setattr(wf, "decision_tool", changed)
        with pytest.raises(ValueError, match=r"tool of 'dq\.coupled'"):
            check_p2_frozen(load_p2())


# ------------------------------------------------------------------ F-B, the gaps (N-5a)


class LateSpike(FakeTools):
    """QC flags a spike on day 120 too (after the first HRT, before the hold-out)."""

    def _data_qc(self, series: Any, event_windows: Any, **kw: Any) -> Any:
        out = super()._data_qc(series, event_windows, **kw)
        for r in out.results:
            r.spikes = [5.0, 120.0]
        return out


def test_a_quarantine_a_decision_chose_does_not_reach_the_signatures(monkeypatch, cfg):
    """A scripted ``dq.trust`` quarantine changes the working record, not the signatures."""
    base, _fake, _doc = run_fake(monkeypatch, cfg)

    def quarantine(point: str, template: str, inputs: dict[str, Any]) -> Any:
        if point == "dq.trust":
            return {"sensor": inputs["sensor"], "quarantine": [[120.0, 120.0]],
                    "reason": "spike_run"}  # fmt: skip
        return None

    run, _fake, _doc = run_fake(monkeypatch, cfg, LateSpike(), quarantine)
    gas = run.series["gas_flow"]
    day = int(np.flatnonzero(gas.t == 120.0)[0])
    assert np.isnan(gas.value[day]) and np.isfinite(gas.raw[day])  # it was quarantined
    assert run.decider.records[0]["point"] == "dq.trust"
    assert not run.decider.records[0]["fallback_used"]  # the scripted choice was taken
    assert {n: s.in_objective for n, s in run.series.items()} == {
        n: s.in_objective for n, s in base.series.items()
    }  # N-5b
    for name, r in run.residuals.items():
        assert r["n"] == base.residuals[name]["n"]
        assert r["bias_z"] == pytest.approx(base.residuals[name]["bias_z"])


def test_the_signatures_use_the_served_weights(monkeypatch, cfg):
    """The residuals are standardised by the served floors' weights, not P0's (N-5a)."""
    fake = FakeTools()
    served = fake._declared_background

    def floors_changed(plant: str, tier: str) -> Any:
        out = served(plant, tier)
        proc = out.procedure.model_copy(update={"min_relative_sd": 0.5})
        return out.model_copy(update={"procedure": proc})

    monkeypatch.setattr(fake, "_declared_background", floors_changed)
    run, _fake, _doc = run_fake(monkeypatch, cfg, fake)
    gas = run.series["gas_flow"]
    assert not np.allclose(run.reference_sd["gas_flow"], gas.sd)  # they differ here
    pred = run.reference_prediction
    m = np.isfinite(gas.raw) & (gas.t >= run.cal[0]) & (gas.t <= run.cal[1])
    r = gas.raw[m] - np.interp(gas.t[m], np.asarray(pred.t), np.asarray(pred.outputs[gas.channel]))
    served_rms = float(np.sqrt(np.mean((r / run.reference_sd["gas_flow"][m]) ** 2)))
    p0_rms = float(np.sqrt(np.mean((r / gas.sd[m]) ** 2)))
    assert run.residuals["gas_flow"]["rmse_z"] == pytest.approx(served_rms)
    assert abs(served_rms - p0_rms) > 0.1 * served_rms  # the negative control


def test_r3_reads_the_reference_fits_bounds_not_a_chosen_subsets(monkeypatch, cfg):
    """``at_bound`` differs between the two fits; R3 reads the reference's (N-5a)."""
    run, _fake, _doc = run_fake(monkeypatch, cfg)
    assert list(run.reference_fit.at_bound) == []
    # a subset fit that hit a bound
    run.fit = types.SimpleNamespace(**{**vars(run.reference_fit), "at_bound": ["k_dis"]})
    failed = ["ph", "tan"]
    run.placement = {}
    for ch in ("gas_flow", "ph", "tan", "cod_total"):
        side = 1 if ch in failed else 0
        run.placement.update({f"{ch}.at_defaults.mean_z": side, f"{ch}.after_fit.mean_z": side,
                              f"{ch}.after_fit.rms_z": side})  # fmt: skip
    run.table = wf.null_table(run.placement)
    attr = cfg["p0"]["attribution"]
    rmse = 2 * float(attr["structural_rmse_z_min"])
    run.residuals = {ch: {"channel": ch, "rmse_z": rmse, "serially_structured": True,
                          "most_explanatory": None, "step_z": None, "step_day": None}
                     for ch in failed}  # fmt: skip
    run.step_profile()
    # structured, but not by load or time, and the reference fit hit no bound: no R3
    assert run.signatures["r3"] is False
    # the negative control: the reference fit at a bound gives R3 on the failed channels
    run.reference_fit = run.fit
    run.step_profile()
    assert run.signatures["r3"] is True


class FlatPh(FakeTools):
    """QC finds pH flat across the calibration window: its quarantine covers it all."""

    def _data_qc(self, series: Any, event_windows: Any, **kw: Any) -> Any:
        from tests.p2_support import ns

        out = super()._data_qc(series, event_windows, **kw)
        for r in out.results:
            if r.name == "ph":
                r.flatlines = [ns(start=0.0, end=149.0)]
        return out


def test_a_quarantine_cannot_drop_a_sensor_from_the_objective(monkeypatch, cfg):
    """The minimum-samples check counts the raw record (N-5b)."""
    base, _fake, _doc = run_fake(monkeypatch, cfg)
    run, _fake, _doc = run_fake(monkeypatch, cfg, FlatPh())
    ph = run.series["ph"]
    assert ph.count(run.cal) < int(cfg["p0"]["qc"]["min_samples"])  # quarantined away
    assert ph.count(run.cal, raw=True) >= int(cfg["p0"]["qc"]["min_samples"])
    assert ph.in_objective is base.series["ph"].in_objective is True
    assert set(run.residuals) == set(base.residuals)  # the signatures see the same channels
