"""The Anthropic arm: the same P1, its model turns through Anthropic's Messages API.

The lead's ruling of 2026-09-29: a second model arm (revision 2 with ``claude-opus-5-5``)
beside revision 2 with ``gpt-5.6-luna``, one development run each. Everything but the
``model`` block is shared: the prompts, the tools, the budgets, the jail, the loop. These
tests run on a stand-in for the SDK client and need no key and no network.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
import yaml

from state.provenance import read_calls
from state.task_state import TaskState
from tests.p1_support import clean_policy, tool_use, turn_of
from tools.llm import (
    LLM_LOG_FILE,
    AnthropicClient,
    ModelError,
    ModelGateway,
    RecordedClient,
    RetryableModelError,
    ScriptedClient,
    check_messages_request,
    from_messages_output,
    read_transcript,
    system_digest,
    to_messages_request,
)
from tools.runner import p1_provenance, run_workflow
from tools.server import OUTPUTS_DIR
from tools.workflow_config import WORKFLOW_CONFIG_DIR, load_p1, load_prompts, model_system_text
from workflows.p1_single_agent import agent

ARM = WORKFLOW_CONFIG_DIR / "p1_anthropic.yaml"


@pytest.fixture(scope="module")
def p1_cell(tmp_path_factory):
    """The short clean cell in its own store (as tests/test_p1_agent.py's)."""
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from tests.conftest import _short

    store = tmp_path_factory.mktemp("p1armstore")
    scenario = _short("S0-01", evals=40, wall_min=20.0, assays=2)
    run = generate_run(scenario, "B", plant=load_plant_config("C"), runs_root=store / "runs")
    return run, scenario


# ------------------------------------------------------------------ the stand-in SDK


class _Stream:
    def __init__(self, message: Any) -> None:
        self._message = message

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get_final_message(self) -> Any:
        return self._message


class _Messages:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.sent: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> _Stream:
        self.sent.append(json.loads(json.dumps(kwargs)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Stream(reply)


class FakeAnthropic:
    """``client.messages.stream(**kwargs)`` answering from a script of raw responses."""

    def __init__(self, *replies: Any) -> None:
        """The raw responses (or exceptions) to answer with, in order."""
        self.messages = _Messages(list(replies))

    @property
    def sent(self) -> list[dict[str, Any]]:
        return self.messages.sent


def raw(content: list[dict[str, Any]], stop: str = "end_turn", **extra: Any) -> dict[str, Any]:
    """A Messages API response as the SDK's ``to_dict()`` gives it."""
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_creation_input_tokens": 30,
            "cache_read_input_tokens": 40,
        },
        **extra,
    }


def _gateway(tmp_path, client, **kw: object) -> ModelGateway:
    config = load_p1(ARM)
    return ModelGateway(
        settings=config.model,
        client=client,
        log_dir=tmp_path,
        max_turns=kw.get("max_turns", 5),
        max_total_tokens=kw.get("max_total_tokens", 10**9),
        sleep=kw.get("sleep", lambda s: None),
        system_sha256=kw.get("system_sha256"),
    )


# ------------------------------------------------------------------ the configuration


def test_the_anthropic_arm_differs_from_p1_only_in_the_model_block():
    plain = yaml.safe_load((WORKFLOW_CONFIG_DIR / "p1.yaml").read_text("utf-8"))
    arm = yaml.safe_load(ARM.read_text("utf-8"))
    model = arm.pop("model")
    plain_model = plain.pop("model")
    # the frozen P1 commits its hash and its record; the comparison arm carries neither
    assert plain.pop("frozen")["prompt_sha256"] == plain["prompt_sha256"] != ""
    assert arm["prompt_sha256"] == "" and "frozen" not in arm
    plain["prompt_sha256"] = ""
    assert arm == plain
    assert model["provider"] == "anthropic" and model["model_id"] == "claude-opus-5-5"
    assert model["temperature"] is None and model["effort"] == "high"
    assert model["max_tokens"] == plain_model["max_tokens"]
    assert model["prompt_caching"] is True and model["retry"] == plain_model["retry"]
    assert model["request_timeout_s"] == plain_model["request_timeout_s"]
    assert model["pricing_usd_per_mtok"] == {
        "input": 4.0,
        "output": 20.0,
        "cache_write": 5.0,
        "cache_read": 0.2,
    }
    config = load_p1(ARM)
    assert config.prompt_sha256 == "" and config.brief_sha256 == ""  # a comparison arm
    assert p1_provenance(config) == p1_provenance(load_p1())  # the same prompts and tools


def test_the_digests_of_both_configurations_are_the_ones_the_summaries_carry():
    # the coordinator's review of d5f6282 (flag 3): the literal values, so that a silent
    # edit of a prompt or a tool specification fails a test rather than moving a runtime
    # value. Since the freeze of 2026-09-30 the prompt and system digests are also the
    # frozen record's (tests/test_p1_agent.py); the comparison arm shares the prompts.
    pins = {
        "prompt_sha256": "c80a37521e81487012b7a7ebc13e179b616216060d93f1ae45aa8791daf661d1",
        "system_sha256": "ab2025e4d00db06eac2b146bb175ab5fd1cfb744c71af21b14d816608324c1eb",
        "tools_sha256": "11d8e352a76e776c2973a7b1d57f15d52a3529e96a743012bc59647d7a07fd6b",
    }
    for path in (ARM, WORKFLOW_CONFIG_DIR / "p1.yaml"):
        provenance = p1_provenance(load_p1(path))
        for key, value in pins.items():
            assert provenance[key] == value, (path.name, key)
        assert provenance["brief_sha256"] == ""
    # what the pins are: the joined system text's sha256 (the system prompt alone in
    # these two arms) and the sorted-key JSON of the system and task prompts
    prompts = load_prompts(load_p1(ARM))
    assert system_digest(model_system_text(prompts)) == pins["system_sha256"]
    assert system_digest(prompts["system"]) == pins["system_sha256"]


# ------------------------------------------------------------------ the request


def test_the_client_sends_the_committed_request_and_nothing_else(tmp_path):
    prompts = load_prompts(load_p1(ARM))
    system = model_system_text(prompts)
    specs = agent.tool_specs()
    fake = FakeAnthropic(
        raw(
            [
                {"type": "thinking", "thinking": "", "signature": "sig-1"},
                {"type": "tool_use", "id": "toolu_1", "name": "check_quality", "input": {}},
            ],
            "tool_use",
        )
    )
    client = AnthropicClient(
        load_p1(ARM).model, system_sha256=system_digest(system), transport=fake
    )
    assert client.name == "anthropic:claude-opus-5-5"
    gw = _gateway(tmp_path, client, system_sha256=system_digest(system))
    out = gw.complete(
        {"system": system, "messages": [{"role": "user", "content": "go"}], "tools": specs}
    )
    sent = fake.sent[0]
    assert set(sent) == {"model", "max_tokens", "system", "messages", "tools", "tool_choice",
                         "output_config"}  # fmt: skip
    assert sent["model"] == "claude-opus-5-5" and sent["max_tokens"] == 16000
    assert sent["output_config"] == {"effort": "high"}
    assert sent["tool_choice"] == {"type": "auto"}
    for absent in ("thinking", "temperature", "metadata", "fallbacks", "stop_sequences", "betas"):
        assert absent not in sent
    # the system text, one block, the cache breakpoint on it
    assert sent["system"] == [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
    ]
    # the tools are the committed specifications, unchanged: no strict, no cache_control
    assert sent["tools"] == json.loads(json.dumps(specs))
    assert all(set(t) == {"name", "description", "input_schema"} for t in sent["tools"])
    # the other breakpoint on the last block of the last message
    assert sent["messages"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "go", "cache_control": {"type": "ephemeral"}}],
        }
    ]
    # the reply is the gateway's shape; the raw response and the request as sent are kept
    response = out["response"]
    assert response["stop_reason"] == "tool_use"
    assert response["content"] == [
        {"type": "thinking", "thinking": "", "signature": "sig-1"},
        {"type": "tool_use", "id": "toolu_1", "name": "check_quality", "input": {}},
    ]
    assert response["provider"]["api"] == "anthropic.messages"
    assert response["provider"]["request"] == sent
    assert response["usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_creation_input_tokens": 30,
        "cache_read_input_tokens": 40,
    }
    assert gw.meter.input == 100 and gw.meter.cache_write == 30 and gw.meter.cache_read == 40
    assert gw.cost_usd() == pytest.approx((100 * 4 + 20 * 20 + 30 * 5 + 40 * 0.2) / 1e6)
    line = read_transcript(tmp_path / LLM_LOG_FILE)[0]
    assert line["client"] == "anthropic:claude-opus-5-5"
    assert line["response"]["provider"]["request"] == sent


def test_the_agents_history_is_not_edited_by_the_translation():
    params = {
        "model": "claude-opus-5-5",
        "max_tokens": 16000,
        "system": "s",
        "messages": [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": [tool_use(0, 0, "check_quality", {})]},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tu_0_0", "content": "{}"}],
            },
        ],
        "cache_control": {"type": "ephemeral"},
    }
    before = json.loads(json.dumps(params))
    kwargs = to_messages_request(params)
    assert params == before  # the gateway's request (what the log keeps) is untouched
    assert kwargs["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["messages"][:-1] == params["messages"][:-1]
    assert "tools" not in kwargs and "tool_choice" not in kwargs  # none given, none sent
    # without caching: no breakpoints at all
    plain = to_messages_request({k: v for k, v in params.items() if k != "cache_control"})
    assert plain["system"] == [{"type": "text", "text": "s"}]
    assert plain["messages"] == params["messages"]


def test_the_check_refuses_every_form_the_arm_may_not_send():
    settings = load_p1(ARM).model
    digest = system_digest("s")
    good = to_messages_request(
        {
            "model": "claude-opus-5-5",
            "max_tokens": 16000,
            "system": "s",
            "messages": [{"role": "user", "content": "go"}],
            "tools": [{"name": "t", "description": "d", "input_schema": {"type": "object"}}],
            "output_config": {"effort": "high"},
            "cache_control": {"type": "ephemeral"},
        }
    )
    check_messages_request(good, settings, digest)
    bad: list[tuple[dict[str, Any], str]] = [
        ({**good, "thinking": {"type": "adaptive"}}, "may not"),
        ({**good, "fallbacks": ["claude-sonnet-5-5"]}, "may not"),
        ({**good, "metadata": {"user_id": "x"}}, "may not"),
        ({**good, "stop_sequences": ["END"]}, "may not"),
        ({**good, "model": "claude-sonnet-5-5"}, "the model sent"),
        ({**good, "max_tokens": 4000}, "max_tokens"),
        ({**good, "output_config": {"effort": "medium"}}, "effort"),
        ({**good, "output_config": {"effort": "high", "format": {}}}, "effort"),
        ({**good, "temperature": 0.0}, "temperature"),
        ({**good, "system": "s"}, "list of text blocks"),
        ({**good, "system": [{"type": "text", "text": "s", "extra": 1}]}, "system block"),
        ({**good, "tools": [{**good["tools"][0], "strict": True}]}, "no strict"),
        ({**good, "tools": [{"type": "web_search_20260209", "name": "web_search"}]}, "custom"),
        ({**good, "tool_choice": {"type": "any"}}, "tool_choice"),
        ({k: v for k, v in good.items() if k != "tool_choice"}, "tool_choice"),
        ({**good, "messages": [{"role": "system", "content": "x"}]}, "role"),
        (
            {**good, "messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}]},
            "block type",
        ),
        (
            {
                **good,
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "x", "citations": []}]}
                ],
            },
            "carries exactly",
        ),
    ]
    for kwargs, match in bad:
        with pytest.raises(ModelError, match=match):
            check_messages_request(kwargs, settings, digest)
    # the system digest is checked on the joined text
    with pytest.raises(ModelError, match="not the committed system prompt"):
        check_messages_request(good, settings, system_digest("another"))
    # tools without tool_choice are fine when there are no tools
    none = {k: v for k, v in good.items() if k not in ("tools", "tool_choice")}
    check_messages_request(none, settings, digest)


# ------------------------------------------------------------------ the reply


def test_the_reply_translation_keeps_every_block_and_refuses_the_unknown():
    kw = {"model": "claude-opus-5-5"}
    out = from_messages_output(
        raw(
            [
                {"type": "thinking", "thinking": None, "signature": "sig"},
                {"type": "redacted_thinking", "data": "blob"},
                {"type": "text", "text": "then"},
                {"type": "tool_use", "id": "toolu_2", "name": "simulate", "input": '{"a": 1}'},
                {"type": "tool_use", "id": "toolu_3", "name": "simulate", "input": "{not json"},
                {"type": "tool_use", "id": "toolu_4", "name": "simulate", "input": [1, 2]},
            ],
            "tool_use",
        ),
        kw,
    )
    assert out["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    assert out["content"][1] == {"type": "redacted_thinking", "data": "blob"}
    assert out["content"][2] == {"type": "text", "text": "then"}
    assert out["content"][3]["input"] == {"a": 1}
    assert out["content"][4]["input"] == {"_unparseable_arguments": "{not json"}
    assert out["content"][5]["input"] == {"_unparseable_arguments": "[1, 2]"}
    assert out["stop_reason"] == "tool_use" and "stop_details" not in out
    for stop in ("end_turn", "max_tokens"):
        assert from_messages_output(raw([], stop), kw)["stop_reason"] == stop
    refusal = from_messages_output(
        raw([], "refusal", stop_details={"type": "refusal", "category": "x"}), kw
    )
    assert refusal["stop_reason"] == "refusal"
    assert refusal["stop_details"] == {"type": "refusal", "category": "x"}
    with pytest.raises(ModelError, match="unhandled content block"):
        from_messages_output(raw([{"type": "server_tool_use", "id": "s", "name": "n"}]), kw)
    with pytest.raises(ModelError, match="unhandled stop reason"):
        from_messages_output(raw([], "pause_turn"), kw)


def test_an_unhandled_reply_is_logged_with_the_raw_response(tmp_path):
    fake = FakeAnthropic(raw([{"type": "web_search_tool_result", "tool_use_id": "s"}]))
    client = AnthropicClient(load_p1(ARM).model, transport=fake)
    gw = _gateway(tmp_path, client)
    with pytest.raises(ModelError, match="unhandled content block"):
        gw.complete({"system": "s", "messages": [{"role": "user", "content": "go"}]})
    line = read_transcript(tmp_path / LLM_LOG_FILE)[0]
    assert line["response"] is None and line["provider_response"]["content"][0]["type"] == (
        "web_search_tool_result"
    )
    assert line["provider_request"] == fake.sent[0]


def test_sdk_errors_map_to_the_gateways_retry_policy(tmp_path):
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx2")  # the SDK's HTTP layer (anthropic 1.x)

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def status(code: int) -> Exception:
        return anthropic.APIStatusError(
            f"status {code}", response=httpx.Response(code, request=request), body=None
        )

    fake = FakeAnthropic(
        anthropic.RateLimitError(
            "slow down", response=httpx.Response(429, request=request), body=None
        ),
        anthropic.APIConnectionError(request=request),
        status(529),
        status(400),
    )
    client = AnthropicClient(load_p1(ARM).model, transport=fake)
    client._sdk = anthropic  # the stand-in transport, the SDK's exception classes
    params = {
        "model": "claude-opus-5-5",
        "max_tokens": 16000,
        "system": "s",
        "messages": [],
        "output_config": {"effort": "high"},
    }
    for _ in range(3):
        with pytest.raises(RetryableModelError):
            client.create(params)
    with pytest.raises(ModelError) as info:
        client.create(params)
    assert not isinstance(info.value, RetryableModelError)


# ------------------------------------------------------------------ the runner


def test_the_live_client_of_the_anthropic_arm_checks_the_text_the_gateway_sends(monkeypatch):
    pytest.importorskip("anthropic")
    from tools.runner import live_client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    config = load_p1(ARM)
    client = live_client(config)
    assert isinstance(client, AnthropicClient)
    assert client.system_sha256 == p1_provenance(config)["system_sha256"]
    assert client.name == "anthropic:claude-opus-5-5"


KEY_MARKER = "sk-ant-test-marker-never-a-key"


def test_a_run_of_the_arm_records_its_provider_and_replays(p1_cell, tmp_path, monkeypatch):
    run, scenario = p1_cell
    # the key is in the environment of the run (as the driver's shell puts it) and nowhere
    # the run writes: not the summary, the state, the logs or the provenance (the
    # coordinator's step 4 of 2026-09-29)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY_MARKER)
    # the clean policy's replies, sent back through the stand-in SDK as raw responses
    script: list[dict[str, Any]] = []

    class Through:
        """The stand-in SDK answering from the scripted policy on the request it is sent."""

        def __init__(self) -> None:
            self.messages = self

        def stream(self, **kwargs: Any) -> _Stream:
            system = "".join(b["text"] for b in kwargs["system"])
            messages = [
                {"role": m["role"], "content": m["content"] if isinstance(m["content"], str)
                 else [{k: v for k, v in b.items() if k != "cache_control"} for b in m["content"]]}
                for m in kwargs["messages"]
            ]  # fmt: skip
            reply = clean_policy({"system": system, "messages": messages})
            script.append(reply)
            return _Stream(raw(reply["content"], reply["stop_reason"]))

    client = AnthropicClient(
        load_p1(ARM).model,
        system_sha256=p1_provenance(load_p1(ARM))["system_sha256"],
        transport=Through(),
    )
    result = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        config_path=ARM,
        model_client=client,
        output_name="p1_anthropic",
    )
    assert result.error == "", result.stderr_tail
    assert result.completed and result.state_valid
    assert result.provider == "anthropic" and result.model_id == "claude-opus-5-5"
    assert result.run_failed is False and result.failure_reason == ""
    assert result.model_client == "anthropic:claude-opus-5-5"
    assert result.llm_cost_usd is not None and result.llm_cost_usd > 0
    out = run.paths.root / OUTPUTS_DIR / "p1_anthropic"
    summary = json.loads((out / "summary.json").read_text("utf-8"))
    assert summary["provider"] == "anthropic"
    state = TaskState.model_validate_json((out / "state.json").read_text("utf-8"))
    assert state.final.completed and state.final.label == "none"
    assert read_calls(run.paths.root)
    # every line of the log kept the request as sent and the raw reply; the replay holds
    lines = read_transcript(out / LLM_LOG_FILE)
    assert all(x["response"]["provider"]["api"] == "anthropic.messages" for x in lines)
    replay = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        config_path=ARM,
        model_client=RecordedClient(out / LLM_LOG_FILE),
        output_name="p1_anthropic_replay",
    )
    assert replay.error == "", replay.stderr_tail
    assert replay.completed and replay.label == result.label
    # nothing the run wrote carries the key or names its variable; the marker was in the
    # environment the whole time (the negative control: the scan does find it there)
    assert KEY_MARKER in json.dumps(dict(os.environ))
    written = [p for p in run.paths.root.rglob("*") if p.is_file()]
    assert written
    for path in written:
        text = path.read_bytes()
        assert b"sk-ant-" not in text and b"ANTHROPIC_API_KEY" not in text, path
    for blob in (result.as_dict(), p1_provenance(load_p1(ARM)), lines):
        dumped = json.dumps(blob, default=str)
        assert "sk-ant-" not in dumped and "ANTHROPIC_API_KEY" not in dumped


# ------------------------------------------------------------------ the loop


def _cut_then_clean(params: dict[str, Any]) -> dict[str, Any]:
    """Turn 0 is cut at the token limit (text only); then the clean run, offset by one."""
    if turn_of(params) == 0:
        return {
            "content": [{"type": "text", "text": "I will begin by"}],
            "stop_reason": "max_tokens",
        }
    messages = [params["messages"][0], *params["messages"][3:]]
    return clean_policy({**params, "messages": messages})


def test_a_reply_cut_at_the_token_limit_is_continued_once(p1_cell):
    run, scenario = p1_cell
    result = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        model_client=ScriptedClient(_cut_then_clean),
        output_name="p1_cut_once",
    )
    assert result.error == "", result.stderr_tail
    assert result.completed and result.state_valid
    out = run.paths.root / OUTPUTS_DIR / "p1_cut_once"
    state = json.loads((out / "state.json").read_text("utf-8"))
    assert "reply cut at the token limit at turn 1" in state["plan"]["guards_tripped"]
    lines = read_transcript(out / LLM_LOG_FILE)
    second = lines[1]["messages"]  # the messages the second request added
    assert second[0]["role"] == "assistant" and second[0]["content"][0]["text"] == "I will begin by"
    assert "cut at the token limit" in second[1]["content"][0]["text"]


def _cut_twice(params: dict[str, Any]) -> dict[str, Any]:
    """Two replies cut at the token limit, each with a tool use the harness must not run."""
    turn = turn_of(params)
    return {
        "content": [tool_use(turn, 0, "simulate", {"parameters": {}})],
        "stop_reason": "max_tokens",
    }


def test_a_second_cut_reply_ends_the_run_and_its_tool_uses_never_run(p1_cell):
    run, scenario = p1_cell
    result = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        model_client=ScriptedClient(_cut_twice),
        output_name="p1_cut_twice",
    )
    assert result.error == "", result.stderr_tail
    assert not result.completed and result.llm_turns == 2
    out = run.paths.root / OUTPUTS_DIR / "p1_cut_twice"
    state = TaskState.model_validate_json((out / "state.json").read_text("utf-8"))
    assert "run ended: the model's reply was cut at the token limit twice" in state.annotations
    assert result.run_failed is True and result.failure_reason == "cut_reply"
    assert state.plan.sizes["refused_actions"] == 1  # the first cut's tool use, refused
    assert [f.message for f in state.tool_failures] == [
        "the reply was cut at the token limit; the tool was not run"
    ]
    assert not any(
        c.name == "p1.simulate" and c.outcome == "ok" for c in read_calls(run.paths.root)
    )
    lines = read_transcript(out / LLM_LOG_FILE)
    answer = lines[1]["messages"][1]["content"]
    assert answer[0]["type"] == "tool_result" and answer[0].get("is_error") is True


def test_a_refusal_ends_the_run_with_its_category(p1_cell):
    run, scenario = p1_cell

    def policy(_params: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": [],
            "stop_reason": "refusal",
            "stop_details": {"type": "refusal", "category": "test"},
        }

    result = run_workflow(
        run.run_id,
        "p1",
        runs_root=run.paths.root.parent,
        scenario=scenario,
        model_client=ScriptedClient(policy),
        output_name="p1_refusal",
    )
    assert result.error == "", result.stderr_tail
    assert not result.completed and result.llm_turns == 1
    out = run.paths.root / OUTPUTS_DIR / "p1_refusal"
    state = TaskState.model_validate_json((out / "state.json").read_text("utf-8"))
    assert "run ended: the model refused (test)" in state.annotations
    # the summary says why (the coordinator's review of d5f6282, flag 2) ...
    assert result.run_failed is True and result.failure_reason == "refusal"
    summary = json.loads((out / "summary.json").read_text("utf-8"))
    assert summary["run_failed"] is True and summary["failure_reason"] == "refusal"
    # ... and the report's row reads it from the summary: a failed row, its credit
    # columns blank, the placeholder label named as such
    from scripts.p1_pilot_report import row_of, totals

    version = {
        "label": "t",
        "sha": summary["prompt_sha256"],
        "store": str(run.paths.root.parent.parent),
    }
    line = {
        "scenario_id": scenario.id,
        "plant": "C",
        "tier": "B",
        "run_id": run.run_id,
        "summary": summary,
        "score": {"truth_label": "none", "attribution_exact": True, "claims": 0},
    }
    row = row_of(version, line)
    assert row["run_failed"] is True and row["failure_reason"] == "refusal"
    assert row["primary_matches_truth"] == "" and row["attribution_exact"] == ""
    assert row["truth_among_labels"] == ""
    assert row["evidence_by_label"].startswith("(no conclusion")
    tot = totals([row])
    assert tot["failed runs (no conclusion)"] == 1 and tot["  of which refusal"] == 1
    assert tot["exact attribution"] == 0 and tot["labels given"] == 0
    # a summary recorded before the fields existed is backfilled from the record
    older = {k: v for k, v in summary.items() if k not in ("run_failed", "failure_reason")}
    row = row_of(version, {**line, "summary": older})
    assert row["run_failed"] is True and row["failure_reason"] == "refusal"
    assert older["run_failed"] is True  # and the copy the report keeps carries them


def test_a_gzipped_log_reads_as_the_plain_one(tmp_path):
    # the review of PR #29 (note 2): the two records over 5 MB are committed gzipped
    import gzip

    lines = [{"turn": 0, "response": {"content": []}}, {"turn": 1, "response": None}]
    text = "".join(json.dumps(x) + "\n" for x in lines)
    plain = tmp_path / "llm_calls.jsonl"
    plain.write_text(text, encoding="utf-8")
    assert read_transcript(plain) == lines
    packed = tmp_path / "packed" / "llm_calls.jsonl"
    packed.parent.mkdir()
    with gzip.open(packed.with_name("llm_calls.jsonl.gz"), "wt", encoding="utf-8") as fh:
        fh.write(text)
    assert read_transcript(packed) == lines  # the plain name, the packed file
    with pytest.raises(FileNotFoundError):  # neither: the error, not an empty log
        read_transcript(tmp_path / "missing" / "llm_calls.jsonl")
