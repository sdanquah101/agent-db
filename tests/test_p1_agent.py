"""P1, the single constrained agent (``docs/p1_design.md``), without a network or a key.

1. Static: the agent passes the rule-1 checker; the committed prompts name no scenario id
   and no P0 rule id (the P1 prompt rule of 2026-09-24); what the runner hands the jail
   carries nothing of a run and no model setting; P1's evidence keys are the evaluator's
   registered claim sources and its hold-out is the evaluator's.
2. The model gateway (``tools.llm``): the frozen settings are what is sent, the agent
   cannot add any; retries follow the policy and every attempt is logged; the turn and
   token budgets refuse; the log reassembles every request verbatim; the recorded client
   replays a run and refuses a different one; the workflow cannot write the log.
3. The harness's own pieces: the input checker, the array summary, the assistant blocks.
4. End to end through the jail on a short clean cell, with the scripted double: the run
   concludes; the state validates; every action names its log line; the refused action
   is recorded; the evaluator scores the run with no unsupported claim; the runner's
   token count is the gateway's; nothing written carries a truth-side token; a replay of
   the transcript gives the same state (rule 4). A policy that never concludes stops at
   the declared limits with ``completed`` false.
"""

from __future__ import annotations

import itertools
import json
import re

import pytest
import yaml

from eval.config import load_eval_config
from eval.records import load_records
from eval.score import Scorer
from state.provenance import read_calls
from state.task_state import TaskState
from tests.conftest import _short
from tests.p1_support import adversarial_policy, clean_policy, dawdling_policy, slow
from tests.test_truth_isolation import find_truth_references
from tools.llm import (
    LLM_LOG_FILE,
    GatewayRefusal,
    ModelError,
    ModelGateway,
    RecordedClient,
    RetryableModelError,
    ScriptedClient,
    check_agent_request,
    from_responses_output,
    read_transcript,
    rebuild_requests,
    replay_digest,
    request_digest,
    system_digest,
    to_responses_request,
)
from tools.runner import WORKFLOWS, run_workflow
from tools.server import OUTPUTS_DIR, OutputSink
from tools.workflow_config import (
    WORKFLOW_CONFIG_DIR,
    load_p1,
    load_prompts,
    sandbox_config,
)
from workflows.p1_single_agent import agent

AGENT = WORKFLOWS["p1"]
PROMPT_DIR = WORKFLOW_CONFIG_DIR / "p1_prompts"


# ------------------------------------------------------------------ 1. static


def test_the_agent_passes_the_rule_one_checker():
    assert AGENT.is_file()
    assert find_truth_references(AGENT) == []


_FORBIDDEN_IN_PROMPTS = (re.compile(r"S\d-\d\d"), re.compile(r"R[1-6]"))


def prompt_violations(texts: dict[str, str]) -> list[tuple[str, str]]:
    """(where, match) for every scenario id or P0 rule id in the texts the model reads."""
    return [
        (where, m.group(0))
        for where, text in texts.items()
        for pattern in _FORBIDDEN_IN_PROMPTS
        for m in pattern.finditer(text)
    ]


def model_facing_texts(prompt_dir=PROMPT_DIR) -> dict[str, str]:
    """Every committed text the model reads, but the filled template (checked end to end).

    The prompt files; every tool name, description and schema the agent sends; and the
    harness's own source, which holds every notice and error message it writes.
    """
    texts = {str(p): p.read_text(encoding="utf-8") for p in sorted(prompt_dir.glob("*"))}
    texts["tool specifications"] = json.dumps(agent.tool_specs())
    texts[str(AGENT)] = AGENT.read_text(encoding="utf-8")
    return texts


def test_no_committed_prompt_names_a_scenario_or_a_p0_rule():
    texts = model_facing_texts()
    assert {str(PROMPT_DIR / "system.md"), str(PROMPT_DIR / "task.md")} <= set(texts)
    assert prompt_violations(texts) == []
    # the configuration names exactly these prompt files, and they load
    assert set(load_prompts(load_p1()).values()) == {
        (PROMPT_DIR / "system.md").read_text(encoding="utf-8"),
        (PROMPT_DIR / "task.md").read_text(encoding="utf-8"),
    }


# Examples that track the scenario library and its correct-action column: the lead's
# ruling of 2026-09-25 made the prompt's examples generic, and none may come back. The
# published abstention vocabulary (in the filled task prompt) is not scanned here.
_LIBRARY_EXAMPLES = re.compile(
    r"gas[- ]meter|scale error|estimate the factor|holds one value|never (been )?logged"
    r"|unrecorded deliver|unlogged|wetter|drier|acclimat|particle size|that parameter only"
    r"|mislabel|electrode|mis-?initiali[sz]ed|syntrophic|precipitat|imperfect mixing"
    r"|inhibition shift|overload|foaming",
    re.IGNORECASE,
)


def library_examples(texts: dict[str, str]) -> list[tuple[str, str]]:
    """(where, match) for every library-shaped example in the committed prompt surfaces."""
    return [(w, m.group(0)) for w, t in texts.items() for m in _LIBRARY_EXAMPLES.finditer(t)]


def test_no_prompt_surface_reintroduces_the_librarys_examples(tmp_path):
    assert library_examples(model_facing_texts()) == []
    # negative control: the pre-ruling wording is caught
    (tmp_path / "old.md").write_text(
        "Examples are a gas meter with a scale error, or feed that has become wetter.\n"
    )
    found = {m.lower() for _, m in library_examples({"old.md": (tmp_path / "old.md").read_text()})}
    assert found == {"gas meter", "scale error", "wetter"}


def test_the_prompt_check_fails_on_a_planted_file(tmp_path):
    # negative control: the same scan, over a prompt directory with one planted file
    for f in PROMPT_DIR.glob("*"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    assert prompt_violations(model_facing_texts(tmp_path)) == []
    (tmp_path / "extra.md").write_text("Behave as on S2-03, where rule R4 fires.\n")
    found = prompt_violations(model_facing_texts(tmp_path))
    assert sorted(m for _, m in found) == ["R4", "S2-03"]
    assert {w for w, _ in found} == {str(tmp_path / "extra.md")}


def test_what_the_runner_hands_the_jail_carries_nothing_of_a_run_and_no_model_setting():
    config = load_p1()
    payload = sandbox_config(config)
    assert "model" not in payload
    assert set(payload) == (set(config.model_dump()) - {"model"}) | {
        "sensor_noise",
        "plant_geometry",
        "abstentions",
        "prompts",
        "assay_catalogue",
    }
    text = json.dumps(payload)
    for token in ("run_", "truth", "scenario_id", "S0-01", "S8-01", "seed:", "baseline"):
        assert token not in text, token
    assert config.model.model_id not in text
    assert payload["assay_catalogue"]["alkalinity"]["unit_cost"] >= 1


def test_the_frozen_settings_are_the_contract_of_the_pr():
    config = load_p1()
    # the lead's choice in the session of 2026-09-25: OpenAI, gpt-5.6-luna
    assert config.model.provider == "openai" and config.model.model_id == "gpt-5.6-luna"
    assert config.model.temperature is None  # reasoning models take no sampling parameters
    assert config.model.pricing_usd_per_mtok is not None
    assert config.model.retry.max_attempts >= 1 and config.loop.max_tool_calls > 0
    assert config.loop.max_turns > 0 and config.loop.max_total_tokens > 0


def test_evidence_keys_are_the_evaluators_registered_claim_sources():
    config = load_p1()
    sources = load_eval_config().attribution.claim_sources.by_value_key
    assert {k: tuple(v) for k, v in config.evidence_keys.items()} == {
        k: tuple(v) for k, v in sources.items()
    }


def test_the_hold_out_is_the_evaluators():
    assert load_p1().windows.holdout_fraction == load_eval_config().windows.holdout_fraction


def test_the_task_template_fills_every_field():
    template = load_prompts(load_p1())["task"]
    fields = {m.group(1) for m in re.finditer(r"\$(\w+)", template)}
    # every placeholder the agent fills; a missing one raises KeyError at run time
    assert fields == {
        "plant", "tier", "duration_days", "volume_m3", "t_op_k", "calibration_window",
        "holdout_window", "sensors", "feeds", "feed_assays", "notes", "model", "budget",
        "max_turns", "max_tool_calls", "labels", "abstentions", "evidence_keys",
    }  # fmt: skip


# ------------------------------------------------------------------ 2. the gateway


def _gateway(tmp_path, client, **kw: object) -> ModelGateway:
    config = load_p1()
    return ModelGateway(
        settings=config.model,
        client=client,
        log_dir=tmp_path,
        max_turns=kw.get("max_turns", 5),
        max_total_tokens=kw.get("max_total_tokens", 10**9),
        sleep=kw.get("sleep", lambda s: None),
    )


def _echo(params):
    return {"content": [{"type": "text", "text": f"turn {len(params['messages'])}"}]}


def test_the_gateway_sends_the_frozen_settings_and_nothing_the_agent_chose(tmp_path):
    seen = []
    gw = _gateway(tmp_path, ScriptedClient(lambda p: seen.append(p) or _echo(p)))
    gw.complete({"system": "s", "messages": [{"role": "user", "content": "hi"}], "tools": []})
    sent = seen[0]
    assert sent["model"] == "gpt-5.6-luna" and sent["max_tokens"] == 16000
    assert "temperature" not in sent  # null in the configuration: never sent
    assert sent["output_config"] == {"effort": "high"}
    assert sent["cache_control"] == {"type": "ephemeral"}
    with pytest.raises(ModelError, match="only system, messages and tools"):
        gw.complete({"system": "s", "messages": [], "model": "another"})


def test_retries_follow_the_policy_and_every_attempt_is_logged(tmp_path):
    calls, sleeps = [], []

    def flaky(params):
        calls.append(1)
        if len(calls) < 3:
            raise RetryableModelError("overloaded")
        return _echo(params)

    class Flaky:
        name = "flaky"

        def create(self, params):
            return flaky(params)

    gw = _gateway(tmp_path, Flaky(), sleep=sleeps.append)
    out = gw.complete({"system": "s", "messages": [{"role": "user", "content": "hi"}]})
    assert out["response"]["content"][0]["text"] == "turn 1"
    assert sleeps == [2.0, 4.0] and gw.meter.attempts == 3 and gw.meter.requests == 1
    lines = read_transcript(tmp_path / LLM_LOG_FILE)
    assert [(ln["attempt"], bool(ln["error"])) for ln in lines] == [(0, 1), (1, 1), (2, 0)]

    class Broken:
        name = "broken"

        def create(self, params):
            raise ModelError("400 bad request")

    gw2 = _gateway(tmp_path / "b", Broken())
    with pytest.raises(ModelError, match="400"):
        gw2.complete({"system": "s", "messages": [{"role": "user", "content": "hi"}]})
    assert gw2.meter.attempts == 1  # not retried

    class Down:
        name = "down"

        def create(self, params):
            raise RetryableModelError("503")

    gw3 = _gateway(tmp_path / "c", Down())
    with pytest.raises(ModelError, match="4 attempts failed"):
        gw3.complete({"system": "s", "messages": [{"role": "user", "content": "hi"}]})


def test_the_turn_and_token_budgets_refuse_before_sending(tmp_path):
    gw = _gateway(tmp_path, ScriptedClient(_echo), max_turns=2)
    msg = {"system": "s", "messages": [{"role": "user", "content": "hi"}]}
    gw.complete(msg)
    gw.complete(msg)
    with pytest.raises(GatewayRefusal, match="2 model turns"):
        gw.complete(msg)
    assert gw.meter.requests == 2
    usage = {"input_tokens": 600, "output_tokens": 500}
    gw2 = _gateway(
        tmp_path / "t",
        ScriptedClient(lambda p: {**_echo(p), "usage": usage}),
        max_total_tokens=1000,
    )
    gw2.complete(msg)
    with pytest.raises(GatewayRefusal, match="1000 tokens"):
        gw2.complete(msg)
    assert gw2.status()["tokens_left"] == 0
    assert gw2.cost_usd() == pytest.approx((600 * 0.20 + 500 * 1.20) / 1e6)


def test_the_log_reassembles_every_request_verbatim(tmp_path):
    sent = []
    gw = _gateway(
        tmp_path, ScriptedClient(lambda p: sent.append(json.loads(json.dumps(p))) or _echo(p))
    )
    history = [{"role": "user", "content": "one"}]
    for k in range(3):
        out = gw.complete({"system": "s", "messages": list(history), "tools": [_GOOD_TOOL]})
        history += [
            {"role": "assistant", "content": out["response"]["content"]},
            {"role": "user", "content": f"next {k}"},
        ]
    lines = read_transcript(tmp_path / LLM_LOG_FILE)
    assert [ln["messages_from"] for ln in lines] == [0, 1, 3]
    assert "request_fixed" in lines[0] and "request_fixed" not in lines[1]
    rebuilt = rebuild_requests(lines)
    assert rebuilt == sent
    assert [ln["request_sha256"] for ln in lines] == [request_digest(p) for p in sent]


def test_the_recorded_client_replays_and_refuses_a_different_request(tmp_path):
    gw = _gateway(tmp_path, ScriptedClient(_echo))
    msg = {"system": "s", "messages": [{"role": "user", "content": "hi"}]}
    first = gw.complete(msg)["response"]
    replay = _gateway(tmp_path / "r", RecordedClient(tmp_path / LLM_LOG_FILE))
    assert replay.complete(msg)["response"] == first
    other = _gateway(tmp_path / "o", RecordedClient(tmp_path / LLM_LOG_FILE))
    with pytest.raises(ModelError, match="differs from the recorded"):
        other.complete({"system": "changed", "messages": msg["messages"]})


_GOOD_TOOL = {"name": "simulate", "description": "d", "input_schema": {"type": "object"}}


@pytest.mark.parametrize(
    ("request_", "match"),
    [
        ({"system": "s", "messages": [], "model": "x"}, "only system, messages and tools"),
        (
            {"system": "s", "messages": [], "tools": [
                {"type": "code_execution_20260521", "name": "code_execution"}]},
            "only custom tools",
        ),
        (
            {"system": "s", "messages": [], "tools": [
                {"type": "web_fetch_20260209", "name": "web_fetch"}]},
            "only custom tools",
        ),
        ({"system": "s", "messages": [], "tools": [{"name": "x"}]}, "name and an input_schema"),
        ({"system": "s", "messages": [], "tools": [_GOOD_TOOL, _GOOD_TOOL]}, "once"),
        ({"system": "not the prompt", "messages": []}, "not the committed prompt"),
        ({"system": "s", "messages": [{"role": "system", "content": "x"}]}, "role"),
        (
            {"system": "s", "messages": [{"role": "user", "content": [
                {"type": "document", "source": {}}]}]},
            "block type",
        ),
        (
            {"system": "s", "messages": [{"role": "user", "content": [
                {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}]}]},
            "carries exactly",
        ),
        (
            {"system": "s", "messages": [{"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": [{"type": "image"}]}]}]},
            "content is text",
        ),
    ],
)  # fmt: skip
def test_the_gateway_refuses_every_form_an_agent_may_not_send(tmp_path, request_, match):
    sent = []
    gw = _gateway(tmp_path, ScriptedClient(lambda p: sent.append(p) or _echo(p)))
    gw.system_sha256 = system_digest("s")
    with pytest.raises(ModelError, match=match):
        gw.complete(request_)
    assert sent == []  # nothing reached the client
    # negative control: the well-formed request passes
    ok = {
        "system": "s",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        "tools": [_GOOD_TOOL],
    }
    gw.complete(ok)
    assert len(sent) == 1


def test_the_replay_digest_masks_the_wall_clock_and_nothing_else():
    def request(clock: float, extra: str = "") -> dict:
        body = json.dumps({"budget": {"wall_clock_min_left": clock}, "x": 1})
        note = f"HARNESS: wall_clock_min_left={clock}{extra}"
        return {"messages": [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t", "content": body},
            {"type": "text", "text": note}]}]}  # fmt: skip

    assert request_digest(request(19.9)) != request_digest(request(12.3))
    assert replay_digest(request(19.9)) == replay_digest(request(12.3))
    assert replay_digest(request(19.9)) != replay_digest(request(19.9, " more"))


def test_the_openai_translation_carries_every_block_both_ways():
    reasoning = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "enc"}
    params = {
        "model": "gpt-5.6-luna",
        "max_tokens": 16000,
        "system": "the prompt",
        "cache_control": {"type": "ephemeral"},
        "output_config": {"effort": "high"},
        "tools": [_GOOD_TOOL],
        "messages": [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "", "signature": json.dumps(reasoning)},
                {"type": "text", "text": "checking"},
                {"type": "tool_use", "id": "call_1", "name": "simulate", "input": {"a": 1}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "{}", "is_error": True},
                {"type": "text", "text": "HARNESS: note"},
            ]},
        ],
    }  # fmt: skip
    kw = to_responses_request(params)
    assert kw["instructions"] == "the prompt" and kw["reasoning"] == {"effort": "high"}
    assert kw["max_output_tokens"] == 16000 and kw["store"] is False
    assert "cache_control" not in kw and "temperature" not in kw
    assert kw["tools"] == [{"type": "function", "name": "simulate", "description": "d",
                            "parameters": {"type": "object"}}]  # fmt: skip
    assert kw["input"] == [
        {"role": "user", "content": "task"},
        reasoning,  # handed back unchanged
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "checking"}]},
        {"type": "function_call", "call_id": "call_1", "name": "simulate", "arguments": '{"a": 1}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "ERROR: {}"},
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "HARNESS: note"}]},
    ]  # fmt: skip
    raw = {
        "model": "gpt-5.6-luna",
        "output": [
            reasoning,
            {"type": "message", "content": [{"type": "output_text", "text": "next"}]},
            {"type": "function_call", "call_id": "call_2", "name": "fisher_info",
             "arguments": '{"parameters": ["k_m_ac"]}'},
        ],
        "usage": {"input_tokens": 1000, "output_tokens": 50,
                  "input_tokens_details": {"cached_tokens": 800, "cache_write_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 30}},
    }  # fmt: skip
    out = from_responses_output(raw, kw)
    assert out["stop_reason"] == "tool_use"
    assert out["content"] == [
        {"type": "thinking", "thinking": "", "signature": json.dumps(reasoning)},
        {"type": "text", "text": "next"},
        {"type": "tool_use", "id": "call_2", "name": "fisher_info",
         "input": {"parameters": ["k_m_ac"]}},
    ]  # fmt: skip
    assert out["usage"]["input_tokens"] == 200 and out["usage"]["cache_read_input_tokens"] == 800
    assert out["provider"]["response"] == raw and "input" not in out["provider"]["request"]
    # the blocks go back into the next request unchanged, and the gateway accepts them
    check_agent_request(
        {"system": "s", "messages": [{"role": "assistant", "content": out["content"]}]}, None
    )
    # a truncated reply and a refusal map to the stop reasons the agent reads
    assert (
        from_responses_output(
            {"output": [], "incomplete_details": {"reason": "max_output_tokens"}}, kw
        )["stop_reason"]
        == "max_tokens"
    )
    refusal = {"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}
    assert from_responses_output(refusal, kw)["stop_reason"] == "refusal"


def test_the_workflow_cannot_write_the_gateways_log(tmp_path):
    from state.run_view import TruthAccessError

    sink = OutputSink(tmp_path, "p1", reserved=(LLM_LOG_FILE,))
    with pytest.raises(TruthAccessError, match="privileged side"):
        sink.write(LLM_LOG_FILE, "forged")
    assert sink.write("state.json", "{}")["bytes"] == 2  # negative control


# ------------------------------------------------------------------ 3. harness pieces


def test_the_input_checker_refuses_what_the_schema_refuses():
    specs = {s["name"]: s["input_schema"] for s in agent.tool_specs()}
    agent.check({"sensor": "ph", "prediction": 3}, specs["residual_diag"])
    for bad, msg in (
        ({"sensor": "ph"}, "missing required field 'prediction'"),
        ({"sensor": "ph", "prediction": "3"}, "expected integer"),
        ({"sensor": "ph", "prediction": 3, "extra": 1}, "unknown field"),
        ({"sensor": "ph", "prediction": True}, "expected integer"),
    ):
        with pytest.raises(agent.ActionError, match=msg):
            agent.check(bad, specs["residual_diag"])
    with pytest.raises(agent.ActionError, match="not one of"):
        agent.check({"what": "truth"}, specs["inspect_record"])
    with pytest.raises(agent.ActionError, match="at least 1"):
        agent.check({"label": "none", "statement": "x", "values": {}, "calls": []},
                    specs["record_evidence"])  # fmt: skip


def test_every_tool_the_agent_names_is_a_registry_tool_or_a_workspace_action():
    from tools.schemas import TOOL_INPUTS

    workspace = {"inspect_record", "set_sensor_status", "record_evidence", "conclude"}
    names = {s["name"] for s in agent.tool_specs()}
    assert names - workspace <= set(TOOL_INPUTS)
    # the two state-space filters need a state-space model, and a run registers none;
    # `validate` is the harness's, once, after the conclusion (the review of PR #26, 1)
    assert set(TOOL_INPUTS) - names == {"filter_enkf", "filter_mhe", "validate"}


def test_long_arrays_are_summarised_and_short_ones_kept():
    out = agent.compact({"a": list(range(100)), "b": [1.0, 2.0], "c": 1.23456789}, 12)
    assert out["a"]["n"] == 100 and out["a"]["first"] == [0, 1, 2, 3, 4, 5]
    assert out["b"] == [1.0, 2.0] and out["c"] == 1.2346


def test_assistant_blocks_keep_the_fields_the_api_reads_unchanged():
    content = [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "hi", "citations": None},
        {"type": "tool_use", "id": "t1", "name": "simulate", "input": {}, "caller": None},
    ]
    assert agent._assistant_blocks(content) == [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "hi"},
        {"type": "tool_use", "id": "t1", "name": "simulate", "input": {}},
    ]


# ------------------------------------------------------------------ 4. end to end


@pytest.fixture(scope="module")
def p1_cell(tmp_path_factory):
    """The short clean cell in its own store (P0's cell keeps its own clock record)."""
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run

    store = tmp_path_factory.mktemp("p1store")
    scenario = _short("S0-01", evals=40, wall_min=20.0, assays=2)
    run = generate_run(scenario, "B", plant=load_plant_config("C"), runs_root=store / "runs")
    return run, scenario


@pytest.fixture(scope="module")
def p1_result(p1_cell):
    run, scenario = p1_cell
    result = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        model_client=ScriptedClient(clean_policy),
    )
    out_dir = run.paths.root / OUTPUTS_DIR / "p1"
    snapshot = {p.name: p.read_text(encoding="utf-8") for p in out_dir.iterdir()}
    return run, scenario, result, snapshot


def test_the_agent_concludes_and_keeps_the_contract(p1_result):
    run, _, result, snap = p1_result
    assert result.error == "", result.stderr_tail
    assert result.completed and result.state_valid and result.returncode == 0
    assert set(snap) == {"state.json", "report.json", "summary.json", LLM_LOG_FILE}
    state = TaskState.model_validate_json(snap["state.json"])
    assert state.workflow == "p1" and state.final.completed and state.final.label == "none"
    assert state.holdout_window == (22.5, 30.0)
    # every action names its log line, and the line agrees
    visible = read_calls(run.paths.root)
    assert state.actions
    for action in state.actions:
        line = visible[action.seq]
        assert (line.name, line.args_hash, line.outcome) == (
            action.name,
            action.args_hash,
            action.outcome,
        )
    # the refused abstention is recorded, the second conclusion held
    refused = [f for f in state.tool_failures if f.name == "p1.conclude"]
    assert len(refused) == 1 and "everything" in refused[0].message
    assert state.plan.sizes["refused_actions"] == 1
    # the validation block names its call and the frozen window; the harness made that
    # call once, after the conclusion, and the model never saw it (the review of #26, 1)
    assert state.validation is not None and state.validation.holdout == (22.5, 30.0)
    validates = [a for a in state.actions if a.name == "validate"]
    assert len(validates) == 1 and state.actions[-1].name == "validate"
    assert state.validation.calls == (validates[0].call_index,)
    for metric in ("coverage_90", "interval_score", "crps", "nrmse"):
        assert metric not in snap[LLM_LOG_FILE], metric
    assert state.residuals and "q_gas_stp_dry" in state.residuals


def test_the_filled_task_prompt_names_no_scenario_or_p0_rule(p1_result):
    _, _, _, snap = p1_result
    first = rebuild_requests([json.loads(x) for x in snap[LLM_LOG_FILE].splitlines()])[0]
    texts = {
        "system (as sent)": first["system"],
        "task (as filled)": first["messages"][0]["content"],
    }
    assert "$" not in texts["task (as filled)"].split("## The fitted model")[0]
    assert prompt_violations(texts) == []


def test_the_evaluator_scores_the_run_with_every_claim_supported(p1_result):
    run, _, result, _ = p1_result
    records = load_records(run.run_id, "p1", runs_root=run.paths.root.parent)
    assert records.problems == ()
    row = Scorer().score(records)
    assert row["completed"] is True and row["attribution_exact"] is True
    assert row["claims"] == 1 and row["claims_unsupported"] == 0
    assert row["invalid_actions"] == 0 and row["tool_errors"] == 0
    assert row["forecast_reason"] == "" and row["meter_agrees_with_summary"] is True
    assert row["tokens"] == result.tokens_used > 0


def test_the_runner_counts_tokens_from_the_gateway_and_the_log_is_verbatim(p1_result):
    _, _, result, snap = p1_result
    lines = [json.loads(x) for x in snap[LLM_LOG_FILE].splitlines()]
    assert result.llm_turns == len(lines) == 6 and result.model_client == "scripted"
    assert result.tokens_used == sum(
        ln["usage"]["input_tokens"] + ln["usage"]["output_tokens"] for ln in lines
    )
    requests = rebuild_requests(lines)
    assert [request_digest(r) for r in requests] == [ln["request_sha256"] for ln in lines]
    assert requests[0]["model"] == "gpt-5.6-luna"
    # each request extends the last one: history is append-only
    for a, b in itertools.pairwise(requests):
        assert b["messages"][: len(a["messages"])] == a["messages"]
    summary = json.loads(snap["summary.json"])
    assert summary["tokens_used"] == result.tokens_used and summary["llm_cost_usd"] > 0


def test_nothing_p1_wrote_carries_a_truth_side_token(p1_result):
    run, scenario, _, snap = p1_result
    salt = (run.paths.truth.parent / "salt").read_bytes().hex()
    for name in ("state.json", "report.json", LLM_LOG_FILE):
        text = snap[name]
        for token in (
            scenario.id,
            "truth_store",
            "scenario_id",
            "fault_layers",
            "correct_conclusion",
            salt,
        ):
            assert token not in text, (name, token)


@pytest.fixture(scope="module")
def slow_run(p1_cell):
    """A live-like run: the double pauses 13 s before turn 2.

    The clock readings the agent is shown then differ from any replay's (they are rounded
    to 0.1 min, and 13 s always moves them).
    """
    run, scenario = p1_cell
    result = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        model_client=ScriptedClient(slow(clean_policy, 2, 13.0)),
        output_name="p1_slow",
    )
    log = run.paths.root / OUTPUTS_DIR / "p1_slow" / LLM_LOG_FILE
    return run, scenario, result, log, log.read_bytes()


def test_a_replay_reproduces_a_run_whose_clock_moved_and_keeps_its_source(slow_run):
    run, scenario, result, log, recorded = slow_run
    assert result.completed, result.stderr_tail
    # replaying into the source's own directory would erase it: refused before anything runs
    with pytest.raises(ValueError, match="would erase it"):
        run_workflow(
            run.run_id,
            "p1",
            runs_root=run.paths.root.parent,
            scenario=scenario,
            model_client=RecordedClient(log),
            output_name="p1_slow",
        )
    assert log.read_bytes() == recorded
    again = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        model_client=RecordedClient(log),
        output_name="p1_replay",
    )
    assert again.completed, again.stderr_tail
    assert log.read_bytes() == recorded  # the source transcript is untouched
    out = run.paths.root / OUTPUTS_DIR
    first_lines = read_transcript(log)
    replay_lines = read_transcript(out / "p1_replay" / LLM_LOG_FILE)
    # the clock readings differ, so the verbatim requests differ; the replay digests agree
    assert [x["request_sha256"] for x in first_lines] != [x["request_sha256"] for x in replay_lines]
    assert [x["replay_sha256"] for x in first_lines] == [x["replay_sha256"] for x in replay_lines]
    first = json.loads((out / "p1_slow" / "state.json").read_text(encoding="utf-8"))
    second = json.loads((out / "p1_replay" / "state.json").read_text(encoding="utf-8"))
    # the wall clock left is the one field a replay cannot reproduce; the log sequence
    # numbers continue on the same run's log (the replay's actions name the new lines)
    assert [a["seq"] for a in second["actions"]] != [a["seq"] for a in first["actions"]]
    for state in (first, second):
        state["budget"].pop("wall_clock_min")
        for a in state["actions"]:
            a.pop("seq")
    assert first == second


def test_every_refused_form_is_refused_and_recorded(p1_cell):
    run, scenario = p1_cell
    result = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        model_client=ScriptedClient(adversarial_policy),
        output_name="p1_adversarial",
    )
    assert result.completed, result.stderr_tail
    state = TaskState.model_validate_json(
        (run.paths.root / OUTPUTS_DIR / "p1_adversarial" / "state.json").read_text("utf-8")
    )
    messages = [f.message for f in state.tool_failures if f.name.startswith("p1.")]
    expected = [
        "`bias_z` = 42.0 is not what the cited calls produced",  # fabricated number
        "`bias_z` is a number; got 'huge'",  # a word for a number
        "no tool 'validate'",  # the hold-out is not the agent's to read
        "reaches into the hold-out window",  # nor its to edit
        "k_m_ac: no successful call of this run produced a fisher interval",
        "k_dis: no successful call of this run produced a profile interval",
        "`none` never stands beside another label",
        "the run is concluded; nothing runs after it",  # a use after conclude, same turn
    ]
    for text in expected:
        assert any(text in m for m in messages), (text, messages)
    assert state.plan.sizes["refused_actions"] == 7  # the two intervals are one refusal
    # the refused quarantine applied none of its windows
    assert state.data_quality["gas_flow"].quarantined_windows == ()
    assert state.classification.evidence == ()  # neither fabricated item was kept
    assert state.final.label == "none" and state.final.secondary_labels == ()
    # the simulate after the conclusion never reached the registry
    assert [a.name for a in state.actions].count("simulate") == 1


def test_a_run_that_never_concludes_stops_at_the_limits_and_is_not_completed(p1_cell, tmp_path):
    run, scenario = p1_cell
    raw = yaml.safe_load((WORKFLOW_CONFIG_DIR / "p1.yaml").read_text(encoding="utf-8"))
    raw["loop"]["max_turns"] = 6
    raw["loop"]["conclude_grace_turns"] = 2
    raw["prompts"] = {k: str(WORKFLOW_CONFIG_DIR / v) for k, v in raw["prompts"].items()}
    config = tmp_path / "p1_small.yaml"
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    result = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        config_path=config,
        model_client=ScriptedClient(dawdling_policy),
    )
    assert result.returncode == 0 and result.state_valid and not result.completed
    state = json.loads(
        (run.paths.root / OUTPUTS_DIR / "p1" / "state.json").read_text(encoding="utf-8")
    )
    assert state["final"]["completed"] is False and state["classification"]["rule"] == "unconcluded"
    assert state["plan"]["guards_tripped"] and result.llm_turns <= 6
    assert any("run ended" in a for a in state["annotations"])
