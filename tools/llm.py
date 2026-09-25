"""The model gateway: an LLM workflow's model calls, from the privileged side (P1, §6.5).

A jailed agent never holds an API key, never picks its model, and cannot hide a request.
It sends ``{"op": "llm", "request": {"system", "messages", "tools"}}`` over the registry
socket (:mod:`tools.server`), and :class:`ModelGateway` here, in the privileged process:

1. **refuses** the request when the run has used its turns or its tokens
   (``configs/workflows/p1.yaml`` ``loop``), as the registry refuses a tool call over budget;
2. **completes** it with the frozen settings of the ``model`` block (the model id, the
   response cap, the effort, prompt caching; no sampling parameter the model rejects) through
   a :class:`ModelClient`, retrying per the declared policy;
3. **logs every attempt verbatim** to ``runs/<id>/workflows/<wf>/llm_calls.jsonl``
   (proposal §13: "LLM outputs are logged verbatim"): the request as sent and the response
   as received, or the error. The history is append-only, so each line carries the
   request's messages from the first one the previous request did not already have
   (``messages_from``), and the whole request is recoverable by concatenation; the fixed
   parts (system, tools, settings) are logged on the first line and whenever they change;
4. **meters** the tokens every response reports; the runner reads the meter into
   ``summary.json`` (``tokens_used``), never the agent's self-report.

The file name is reserved: the workflow's own ``write_output`` cannot write it
(:class:`tools.server.OutputSink`).

**Clients.** :class:`AnthropicClient` calls the Messages API through the ``anthropic`` SDK
(imported only when it is constructed). Two deterministic test doubles let the whole loop
run in CI with no network and no key: :class:`ScriptedClient` answers with a policy, a
pure function of the request; :class:`RecordedClient` replays a logged transcript and
refuses a request that differs from the one recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tools.workflow_config import ModelSettings

__all__ = [
    "LLM_LOG_FILE",
    "AnthropicClient",
    "GatewayRefusal",
    "ModelClient",
    "ModelError",
    "ModelGateway",
    "OpenAIResponsesClient",
    "RecordedClient",
    "RetryableModelError",
    "ScriptedClient",
    "check_agent_request",
    "from_responses_output",
    "read_transcript",
    "rebuild_requests",
    "replay_digest",
    "request_digest",
    "system_digest",
    "to_responses_request",
]

LLM_LOG_FILE = "llm_calls.jsonl"
"""The gateway's log in the workflow's output directory; the workflow may not write it."""


class ModelError(Exception):
    """A model call failed and is not retried (a bad request, a refusal to authenticate)."""


class RetryableModelError(ModelError):
    """A model call failed in a way the retry policy retries (rate limit, overload, network)."""


class GatewayRefusal(Exception):
    """The run has used its turns or its tokens; nothing was sent."""


class ModelClient(Protocol):
    """One model call: a Messages API request in, the response as a plain dict out."""

    name: str

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send ``params`` and return the response (``content``, ``stop_reason``, ``usage``).

        Raises:
            RetryableModelError: A failure the retry policy retries.
            ModelError: Any other failure.
        """
        ...


def request_digest(params: dict[str, Any]) -> str:
    """A fingerprint of a whole request (sorted-key JSON, sha256)."""
    blob = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


WALL_CLOCK_KEY = "wall_clock_min_left"
"""The one tag under which the harness shows the agent a wall-clock reading. A reading is
the one part of a request a replay cannot reproduce, so :func:`replay_digest` masks it."""

_WALL_CLOCK = re.compile(WALL_CLOCK_KEY + r'([\\"]*\s*[:=]\s*)-?\d[0-9.eE+-]*')


def replay_digest(params: dict[str, Any]) -> str:
    """The fingerprint a replay compares: the request with its wall-clock readings masked.

    Everything else must be byte-identical; a request whose *text* differs because the
    clock crossed a threshold (a harness notice that appears in one run and not the other)
    still differs, and the replay is refused.
    """
    blob = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    blob = _WALL_CLOCK.sub(WALL_CLOCK_KEY + r"\1<masked>", blob)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def system_digest(system: str) -> str:
    """The sha256 of a system prompt's text (the committed prompt's fingerprint)."""
    return hashlib.sha256(system.encode("utf-8")).hexdigest()


_BLOCK_FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    # block type -> (required fields, allowed fields)
    "text": (frozenset({"type", "text"}), frozenset({"type", "text"})),
    "tool_use": (
        frozenset({"type", "id", "name", "input"}),
        frozenset({"type", "id", "name", "input"}),
    ),
    "tool_result": (
        frozenset({"type", "tool_use_id", "content"}),
        frozenset({"type", "tool_use_id", "content", "is_error"}),
    ),
    "thinking": (
        frozenset({"type", "thinking", "signature"}),
        frozenset({"type", "thinking", "signature"}),
    ),
    "redacted_thinking": (frozenset({"type", "data"}), frozenset({"type", "data"})),
}


def check_agent_request(request: dict[str, Any], system_sha256: str | None) -> None:
    """Refuse any request form an agent may not send (rule 2; the review of PR #26, 5).

    Only custom tools (a name, a description, an input schema: no ``type``, so no server
    tool that runs code or reaches the network); only user and assistant turns made of
    text, tool_use, tool_result and thinking blocks; and, when ``system_sha256`` is given,
    exactly the committed system prompt.

    Raises:
        ModelError: Naming the first form refused.
    """
    extra = set(request) - {"system", "messages", "tools"}
    if extra:
        raise ModelError(
            f"an agent request carries only system, messages and tools; got {sorted(extra)}"
        )
    system = request.get("system", "")
    if not isinstance(system, str):
        raise ModelError("the system prompt must be the committed text, as a string")
    if system_sha256 is not None and system_digest(system) != system_sha256:
        raise ModelError("the system prompt is not the committed prompt")
    names: set[str] = set()
    for tool in request.get("tools") or []:
        if not isinstance(tool, dict) or set(tool) - {"name", "description", "input_schema"}:
            raise ModelError(
                "only custom tools (name, description, input_schema) are accepted; got "
                f"{sorted(tool) if isinstance(tool, dict) else type(tool).__name__}"
            )
        schema = tool.get("input_schema")
        if not isinstance(tool.get("name"), str) or not isinstance(schema, dict):
            raise ModelError("a tool needs a name and an input_schema")
        if schema.get("type") != "object" or tool["name"] in names:
            raise ModelError(f"tool {tool['name']!r}: an object schema, once")
        names.add(tool["name"])
    for message in request.get("messages") or []:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise ModelError("a message is exactly {role, content}")
        if message["role"] not in ("user", "assistant"):
            raise ModelError(f"role {message['role']!r} is not accepted")
        content = message["content"]
        if isinstance(content, str):
            continue
        if not isinstance(content, list):
            raise ModelError("message content is a string or a list of blocks")
        for block in content:
            kind = block.get("type") if isinstance(block, dict) else None
            if kind not in _BLOCK_FIELDS:
                raise ModelError(f"block type {kind!r} is not accepted")
            required, allowed = _BLOCK_FIELDS[kind]
            if not required <= set(block) <= allowed:
                raise ModelError(f"a {kind} block carries exactly {sorted(allowed)}")
            if kind == "tool_result" and not isinstance(block["content"], str):
                raise ModelError("a tool_result's content is text")


# ------------------------------------------------------------------ clients


class AnthropicClient:
    """The Messages API through the ``anthropic`` SDK; the key comes from the environment.

    The SDK's own retries are off (``max_retries=0``) so that every attempt passes through
    the gateway's declared policy and its log.
    """

    def __init__(self, settings: ModelSettings) -> None:
        """Build the SDK client.

        Raises:
            ModelError: If the SDK is not installed.
        """
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ModelError("the anthropic SDK is not installed (pip install anthropic)") from exc
        self._sdk = anthropic
        self._client = anthropic.Anthropic(max_retries=0, timeout=settings.request_timeout_s)
        self.name = f"anthropic:{settings.model_id}"

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        """One Messages API call."""
        sdk = self._sdk
        try:
            message = self._client.messages.create(**params)
        except (sdk.RateLimitError, sdk.APIConnectionError) as exc:  # includes timeouts
            raise RetryableModelError(f"{type(exc).__name__}: {exc}") from exc
        except sdk.APIStatusError as exc:
            if exc.status_code >= 500:
                raise RetryableModelError(f"{type(exc).__name__}: {exc}") from exc
            raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        return message.to_dict()


class OpenAIResponsesClient:
    """OpenAI's Responses API through the ``openai`` SDK; the key comes from the environment.

    The agent and the gateway speak one request shape, the Messages API's (content blocks,
    ``tool_use`` / ``tool_result``), so the log and the replay are the same for every
    provider. This client translates that shape to the Responses API and the reply back
    (:func:`to_responses_request`, :func:`from_responses_output`). The reasoning items the
    model returns are carried across turns encrypted (``store=False`` with
    ``reasoning.encrypted_content``), inside the ``signature`` of a thinking block. The
    provider's raw response is kept verbatim under ``provider``. The GPT-5.6 models
    refuse function tools with reasoning on Chat Completions, so this uses the Responses
    API. The SDK's own retries are off, as for the Anthropic client.
    """

    def __init__(self, settings: ModelSettings) -> None:
        """Build the SDK client.

        Raises:
            ModelError: If the SDK is not installed.
        """
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ModelError("the openai SDK is not installed (pip install openai)") from exc
        self._sdk = openai
        self._client = openai.OpenAI(max_retries=0, timeout=settings.request_timeout_s)
        self.name = f"openai:{settings.model_id}"

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        """One Responses API call, translated both ways."""
        sdk = self._sdk
        kwargs = to_responses_request(params)
        try:
            response = self._client.responses.create(**kwargs)
        except (sdk.RateLimitError, sdk.APIConnectionError) as exc:  # includes timeouts
            raise RetryableModelError(f"{type(exc).__name__}: {exc}") from exc
        except sdk.APIStatusError as exc:
            if exc.status_code >= 500:
                raise RetryableModelError(f"{type(exc).__name__}: {exc}") from exc
            raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        return from_responses_output(response.to_dict(), kwargs)


def to_responses_request(params: dict[str, Any]) -> dict[str, Any]:
    """A Messages-API-shaped request as Responses API arguments.

    - the system prompt becomes ``instructions``;
    - a user turn's text becomes a user message, its ``tool_result`` blocks become
      ``function_call_output`` items (an error result says so in the output text);
    - an assistant turn's text becomes an assistant message, its ``tool_use`` blocks
      ``function_call`` items, and its thinking blocks the reasoning items their
      signatures carry;
    - tools become function tools; the effort becomes ``reasoning.effort``;
      ``max_tokens`` becomes ``max_output_tokens``;
    - ``cache_control`` is dropped: OpenAI caches prompt prefixes automatically.

    ``temperature`` is passed through only if the settings sent one.
    """
    items: list[dict[str, Any]] = []
    for message in params.get("messages") or []:
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            items.append({"role": role, "content": content})
            continue
        texts: list[str] = []

        def flush(role: str = role, texts: list[str] = texts) -> None:
            if texts:
                kind = "input_text" if role == "user" else "output_text"
                items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": [{"type": kind, "text": t} for t in texts],
                    }
                )
                texts.clear()

        for block in content:
            kind = block.get("type")
            if kind == "text":
                texts.append(str(block["text"]))
                continue
            flush()
            if kind == "tool_result":
                output = str(block["content"])
                if block.get("is_error"):
                    output = "ERROR: " + output
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block["tool_use_id"],
                        "output": output,
                    }
                )
            elif kind == "tool_use":
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block["id"],
                        "name": block["name"],
                        "arguments": json.dumps(block["input"], sort_keys=True),
                    }
                )
            elif kind == "thinking" and block.get("signature"):
                items.append(json.loads(block["signature"]))
        flush()
    kwargs: dict[str, Any] = {
        "model": params["model"],
        "instructions": params.get("system", ""),
        "input": items,
        "max_output_tokens": params["max_tokens"],
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    if params.get("tools"):
        kwargs["tools"] = [
            {
                "type": "function",
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            }
            for t in params["tools"]
        ]
    effort = (params.get("output_config") or {}).get("effort")
    if effort is not None:
        kwargs["reasoning"] = {"effort": effort}
    if params.get("temperature") is not None:
        kwargs["temperature"] = params["temperature"]
    return kwargs


def from_responses_output(raw: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """A Responses API response as a Messages-API-shaped response.

    Reasoning items become thinking blocks whose ``signature`` is the item itself (so the
    next turn hands it back unchanged), messages become text blocks, function calls
    ``tool_use`` blocks. ``usage`` is mapped so the meter counts the same way for every
    provider: ``input_tokens`` uncached, ``cache_read_input_tokens`` cached,
    ``cache_creation_input_tokens`` cache writes, ``output_tokens`` including reasoning.
    The raw response is kept under ``provider.response``; the request under
    ``provider.request`` without its ``input``, which :func:`to_responses_request`
    derives from the logged request, with its digest.
    """
    content: list[dict[str, Any]] = []
    for item in raw.get("output") or []:
        kind = item.get("type")
        if kind == "reasoning":
            summary = " ".join(
                str(part.get("text", "")) for part in item.get("summary") or []
            ).strip()
            content.append({"type": "thinking", "thinking": summary, "signature": json.dumps(item)})
        elif kind == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    content.append({"type": "text", "text": str(part.get("text", ""))})
                elif part.get("type") == "refusal":
                    content.append({"type": "text", "text": str(part.get("refusal", ""))})
        elif kind == "function_call":
            try:
                arguments = json.loads(item.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {"_unparseable_arguments": str(item.get("arguments"))}
            if not isinstance(arguments, dict):
                arguments = {"_unparseable_arguments": str(item.get("arguments"))}
            content.append(
                {
                    "type": "tool_use",
                    "id": item["call_id"],
                    "name": item["name"],
                    "input": arguments,
                }
            )
    refused = any(
        part.get("type") == "refusal"
        for item in raw.get("output") or []
        if item.get("type") == "message"
        for part in item.get("content") or []
    )
    incomplete = (raw.get("incomplete_details") or {}).get("reason")
    if any(b["type"] == "tool_use" for b in content):
        stop = "tool_use"
    elif refused or incomplete == "content_filter":
        stop = "refusal"
    elif incomplete == "max_output_tokens":
        stop = "max_tokens"
    else:
        stop = "end_turn"
    usage = raw.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    written = int(details.get("cache_write_tokens") or 0)
    request = {k: v for k, v in kwargs.items() if k != "input"}
    request["input_sha256"] = request_digest({"input": kwargs.get("input", [])})
    return {
        "type": "message",
        "role": "assistant",
        "model": raw.get("model", kwargs.get("model")),
        "content": content,
        "stop_reason": stop,
        "usage": {
            "input_tokens": max(int(usage.get("input_tokens") or 0) - cached - written, 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_read_input_tokens": cached,
            "cache_creation_input_tokens": written,
            "reasoning_tokens": int(
                (usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0
            ),
        },
        "provider": {"api": "openai.responses", "request": request, "response": raw},
    }


class ScriptedClient:
    """A deterministic test double: ``policy(request) -> response``.

    The policy sees exactly the request the gateway would send, so a scripted agent can
    read its own tool results from the history and decide its next tool use.
    """

    def __init__(self, policy: Callable[[dict[str, Any]], dict[str, Any]], name: str = "") -> None:
        """Wrap a policy."""
        self._policy = policy
        self.name = name or "scripted"

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        """Answer from the policy, with a usage block sized by the request if none is given."""
        response = dict(self._policy(params))
        response.setdefault("type", "message")
        response.setdefault("role", "assistant")
        response.setdefault("model", str(params.get("model", "")))
        response.setdefault("stop_reason", "end_turn")
        if "usage" not in response:
            size = len(json.dumps(params.get("messages", []), default=str))
            out = len(json.dumps(response.get("content", []), default=str))
            response["usage"] = {
                "input_tokens": size // 4,
                "output_tokens": out // 4,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            }
        return response


def read_transcript(path: Path) -> list[dict[str, Any]]:
    """Every line of a gateway log, in order."""
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class RecordedClient:
    """Replays the successful responses of a logged run, in order.

    A request whose fingerprint differs from the one recorded at that position raises
    :class:`ModelError`: the replay reproduces a run, it does not improvise one. The
    fingerprint is :func:`replay_digest`, which masks the wall-clock readings a replay
    cannot reproduce. The transcript is read once, here, and never written: ``source``
    names it so that the runner can refuse to log the replay over it.
    """

    def __init__(self, transcript: Path | list[dict[str, Any]], *, strict: bool = True) -> None:
        """Load the transcript's successful turns."""
        self.source: Path | None = Path(transcript) if isinstance(transcript, Path) else None
        lines = read_transcript(transcript) if isinstance(transcript, Path) else transcript
        self._turns = [line for line in lines if line.get("response") is not None]
        self._next = 0
        self._strict = strict
        self.name = "recorded"

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        """The next recorded response."""
        if self._next >= len(self._turns):
            raise ModelError("the recorded transcript has no further turn")
        line = self._turns[self._next]
        if self._strict and line.get("replay_sha256") != replay_digest(params):
            raise ModelError(
                f"turn {self._next}: the request differs from the recorded one; replay refused"
            )
        self._next += 1
        return dict(line["response"])


# ------------------------------------------------------------------ the gateway


@dataclass
class TokenMeter:
    """Tokens the responses reported, summed over the run."""

    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0
    requests: int = 0
    attempts: int = 0

    @property
    def total(self) -> int:
        """Every token billed: input, cache writes, cache reads and output."""
        return self.input + self.output + self.cache_write + self.cache_read

    def add(self, usage: dict[str, Any]) -> None:
        """Count one response's usage block."""
        self.input += int(usage.get("input_tokens") or 0)
        self.output += int(usage.get("output_tokens") or 0)
        self.cache_write += int(usage.get("cache_creation_input_tokens") or 0)
        self.cache_read += int(usage.get("cache_read_input_tokens") or 0)


@dataclass
class ModelGateway:
    """Budgets, settings, retries, log and meter of one run's model calls."""

    settings: ModelSettings
    client: ModelClient
    log_dir: Path
    max_turns: int
    max_total_tokens: int
    sleep: Callable[[float], None] = time.sleep
    system_sha256: str | None = None
    meter: TokenMeter = field(default_factory=TokenMeter)
    _previous: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _fixed_digest: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Start a fresh log (a re-run of the workflow on the run replaces the old one).

        Raises:
            ValueError: If the client replays the very file this log would overwrite.
        """
        self.log_dir = Path(self.log_dir)
        self.log_path = self.log_dir / LLM_LOG_FILE
        source = getattr(self.client, "source", None)
        if source is not None and Path(source).resolve() == self.log_path.resolve():
            raise ValueError(
                f"the replay's transcript is {self.log_path}; logging the replay there would "
                "erase it (write the replay to another output directory)"
            )
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")

    # -- what the runner reads -------------------------------------------------------
    def cost_usd(self) -> float | None:
        """The run's cost at the declared prices; None when no price is declared."""
        p = self.settings.pricing_usd_per_mtok
        if p is None:
            return None
        m = self.meter
        return (
            m.input * p.input
            + m.output * p.output
            + m.cache_write * p.cache_write
            + m.cache_read * p.cache_read
        ) / 1e6

    def status(self) -> dict[str, int]:
        """Turns and tokens used and left."""
        return {
            "turns_used": self.meter.requests,
            "turns_left": max(self.max_turns - self.meter.requests, 0),
            "tokens_used": self.meter.total,
            "tokens_left": max(self.max_total_tokens - self.meter.total, 0),
        }

    # -- one turn ----------------------------------------------------------------------
    def params(self, request: dict[str, Any]) -> dict[str, Any]:
        """The request as sent: the agent's content and the frozen settings.

        Raises:
            ModelError: If the request carries a form an agent may not send
                (:func:`check_agent_request`).
        """
        check_agent_request(request, self.system_sha256)
        s = self.settings
        params: dict[str, Any] = {
            "model": s.model_id,
            "max_tokens": s.max_tokens,
            "system": request.get("system", ""),
            "messages": list(request.get("messages") or []),
        }
        if request.get("tools"):
            params["tools"] = list(request["tools"])
        if s.temperature is not None:
            params["temperature"] = s.temperature
        if s.effort is not None:
            params["output_config"] = {"effort": s.effort}
        if s.prompt_caching:
            params["cache_control"] = {"type": "ephemeral"}
        return params

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        """One model turn for the agent.

        Returns:
            ``{"response": <the Messages API response>, "status": <turns and tokens>}``.

        Raises:
            GatewayRefusal: The run's turns or tokens are spent; nothing was sent.
            ModelError: The call failed after the declared retries, or cannot be retried.
        """
        if self.meter.requests >= self.max_turns:
            raise GatewayRefusal(f"the run has used its {self.max_turns} model turns")
        if self.meter.total >= self.max_total_tokens:
            raise GatewayRefusal(f"the run has used its {self.max_total_tokens} tokens")
        params = self.params(request)
        turn = self.meter.requests
        policy = self.settings.retry
        delay = policy.backoff_s
        last: ModelError | None = None
        for attempt in range(policy.max_attempts):
            self.meter.attempts += 1
            try:
                response = self.client.create(params)
            except RetryableModelError as exc:
                last = exc
                self._log(turn, attempt, params, None, str(exc))
                if attempt + 1 < policy.max_attempts:
                    self.sleep(min(delay, policy.max_backoff_s))
                    delay *= 2.0
                continue
            except ModelError as exc:
                self._log(turn, attempt, params, None, str(exc))
                raise
            self.meter.requests += 1
            self.meter.add(dict(response.get("usage") or {}))
            self._log(turn, attempt, params, response, "")
            self._previous = params
            return {"response": response, "status": self.status()}
        raise ModelError(
            f"turn {turn}: {policy.max_attempts} attempts failed; last: {last}"
        ) from last

    def _log(
        self,
        turn: int,
        attempt: int,
        params: dict[str, Any],
        response: dict[str, Any] | None,
        error: str,
    ) -> None:
        """Append one attempt, verbatim, to the log."""
        messages = params["messages"]
        start = 0
        prev = self._previous
        if prev is not None:
            old = prev["messages"]
            while start < min(len(old), len(messages)) and old[start] == messages[start]:
                start += 1
        fixed = {k: v for k, v in params.items() if k != "messages"}
        fixed_digest = request_digest(fixed)
        line: dict[str, Any] = {
            "turn": turn,
            "attempt": attempt,
            "client": self.client.name,
            "request_sha256": request_digest(params),
            "replay_sha256": replay_digest(params),
            "n_messages": len(messages),
            "messages_from": start,
            "messages": messages[start:],
        }
        if fixed_digest != self._fixed_digest:
            line["request_fixed"] = fixed
            self._fixed_digest = fixed_digest
        line["response"] = response
        line["error"] = error
        if response is not None:
            line["usage"] = response.get("usage")
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True, default=str) + "\n")


def rebuild_requests(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every request of a gateway log, reassembled from its lines (the log's own test).

    Each line's messages are the request's from ``messages_from`` on; the earlier ones are
    the previous *successful* request's, and the fixed parts are the last logged ones.
    """
    out: list[dict[str, Any]] = []
    fixed: dict[str, Any] = {}
    previous: list[Any] = []
    for line in lines:
        if "request_fixed" in line:
            fixed = dict(line["request_fixed"])
        messages = previous[: line["messages_from"]] + list(line["messages"])
        out.append({**fixed, "messages": messages})
        if line.get("response") is not None:
            previous = messages
    return out
