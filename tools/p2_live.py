"""P2's live decider, privileged side (deliverable 3; ``docs/p2_design.md`` §9, §14).

Nothing here runs in the jail. The workflow asks a decision through ``tools.llm``; the
registry server hands the request to :class:`P2Gateway`, which:

- accepts only a request the frozen decision layer could have produced: the system
  prompt is one of the twelve frozen templates, the one tool is that decision's frozen
  tool, and the content is one user message (the declared inputs, as JSON);
- projects the request's cost **before** sending it (its input at the declared characters
  per token, plus the full ``max_tokens`` of output) and refuses it when the run would
  pass any cap: requests, tokens or USD. The workflow then abstains (``model_cap``);
- logs every attempt to ``llm_calls.jsonl`` through P1's gateway, with the point and
  role named by the template the request matched (never by the jail).

:func:`check_p2_frozen` is the template freeze: every template's text, every decision's
output schema and tool, and the model settings, against ``p2.yaml``'s ``frozen`` record.
The runner calls it before every P2 run, offline included, and refuses a run on any
difference.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from tools.llm import (
    GatewayRefusal,
    ModelError,
    ModelGateway,
    OpenAIResponsesClient,
    check_agent_request,
    system_digest,
    tools_digest,
)
from tools.workflow_config import DECISION_POINTS, P2Config, P2Frozen, load_p2_templates

__all__ = [
    "P2Gateway",
    "check_p2_frozen",
    "frozen_digests",
    "p2_live_client",
    "p2_provenance",
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frozen_digests(config: P2Config) -> dict[str, dict[str, str]]:
    """What the freeze records, recomputed from the files on disk and the workflow's code.

    ``templates`` (each template's text), ``schemas`` (each decision's output schema) and
    ``tools`` (the one tool each decision's request offers), by decision point.
    """
    from workflows.p2_multi_agent import workflow as wf

    templates = load_p2_templates(config)
    return {
        "templates": {p: templates[p]["sha256"] for p in DECISION_POINTS},
        "schemas": {p: wf.schema_sha256(wf.DECISIONS[p]["model"]) for p in DECISION_POINTS},
        "tools": {p: tools_digest([wf.decision_tool(p)]) for p in DECISION_POINTS},
    }


def check_p2_frozen(config: P2Config) -> P2Frozen:
    """Refuse a P2 run whose decision layer is not the frozen one.

    Returns:
        The freeze record, when everything matches.

    Raises:
        ValueError: There is no freeze record, or a template, an output schema, a tool
            or a model setting differs from it (naming the first difference).
    """
    frozen = config.frozen
    if frozen is None:
        raise ValueError("p2.yaml has no frozen record: P2's decision layer is not frozen")
    now = frozen_digests(config)
    for kind, recorded in (
        ("templates", frozen.templates_sha256),
        ("schemas", frozen.schemas_sha256),
        ("tools", frozen.tools_sha256),
    ):
        if set(recorded) != set(DECISION_POINTS):
            raise ValueError(f"the frozen {kind} must name exactly the twelve decision points")
        for point in DECISION_POINTS:
            if now[kind][point] != recorded[point]:
                raise ValueError(
                    f"the {kind[:-1]} of {point!r} is not the frozen one "
                    f"({now[kind][point][:12]}… vs {recorded[point][:12]}…): refused"
                )
    m = config.model
    for name, have, want in (
        ("model_id", m.model_id, frozen.model_id),
        ("effort", m.effort, frozen.effort),
        ("max_tokens", m.max_tokens, frozen.max_tokens),
        ("retry", m.retry, frozen.retry),
    ):
        if have != want:
            raise ValueError(f"the model's {name} ({have!r}) is not the frozen {want!r}")
    return frozen


def p2_provenance(config: P2Config) -> dict[str, str]:
    """What every ``llm_calls.jsonl`` line and the summary carry; refuses an unfrozen run."""
    from tools.runner import git_commit

    check_p2_frozen(config)
    now = frozen_digests(config)
    return {
        "templates_sha256": _sha(json.dumps(now["templates"], sort_keys=True)),
        "schemas_sha256": _sha(json.dumps(now["schemas"], sort_keys=True)),
        "tools_sha256": _sha(json.dumps(now["tools"], sort_keys=True)),
        "model_id": config.model.model_id,
        "git_commit": git_commit(),
    }


def p2_live_client(config: P2Config) -> OpenAIResponsesClient:
    """The live client: OpenAI's Responses API at P1's frozen settings (decision d)."""
    if config.model.provider != "openai":
        raise ValueError("P2's live decider is the frozen P1's OpenAI model")
    return OpenAIResponsesClient(config.model)


@dataclass
class P2Gateway(ModelGateway):
    """P1's gateway, with P2's request check and caps projected before each request.

    ``max_turns`` and ``max_total_tokens`` are P2's ``caps``; ``max_usd`` and
    ``input_chars_per_token`` too. ``allowed`` maps a frozen template's system digest to
    its ``(point, role, tools digest)``.
    """

    max_usd: float = 0.0
    input_chars_per_token: float = 2.0
    allowed: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    base_provenance: dict[str, str] = field(default_factory=dict)
    by_role: dict[str, dict[str, int]] = field(default_factory=dict)

    @classmethod
    def for_config(cls, config: P2Config, client: Any, log_dir: Any) -> P2Gateway:
        """The gateway of one P2 run, built from the frozen record (refuses an unfrozen run)."""
        from workflows.p2_multi_agent import workflow as wf

        frozen = check_p2_frozen(config)
        templates = load_p2_templates(config)
        allowed = {
            system_digest(templates[p]["text"]): (
                p,
                str(wf.DECISIONS[p]["role"]),
                frozen.tools_sha256[p],
            )
            for p in DECISION_POINTS
        }
        provenance = p2_provenance(config)
        return cls(
            settings=config.model,
            client=client,
            log_dir=log_dir,
            max_turns=config.caps.max_requests,
            max_total_tokens=config.caps.max_total_tokens,
            provenance=dict(provenance),
            max_usd=float(config.caps.max_usd),
            input_chars_per_token=float(config.caps.input_chars_per_token),
            allowed=allowed,
            base_provenance=dict(provenance),
        )

    def decision_of(self, request: dict[str, Any]) -> tuple[str, str]:
        """The ``(point, role)`` a request is for, or a refusal.

        Raises:
            ModelError: The request is not one the frozen decision layer produces.
        """
        check_agent_request(request, None, None)
        entry = self.allowed.get(system_digest(request.get("system", "")))
        if entry is None:
            raise ModelError("the system prompt is not one of P2's frozen templates")
        point, role, tools_sha = entry
        if tools_digest(request.get("tools") or []) != tools_sha:
            raise ModelError(f"{point}: the tool is not the decision's frozen tool")
        messages = request.get("messages") or []
        if (
            len(messages) != 1
            or messages[0]["role"] != "user"
            or not isinstance(messages[0]["content"], str)
        ):
            raise ModelError(f"{point}: a decision request is one user message of text")
        return point, role

    def projected(self, request: dict[str, Any]) -> tuple[int, float | None]:
        """The request's worst-case tokens and USD, before it is sent."""
        text = json.dumps(request, sort_keys=True, default=str)
        tokens_in = math.ceil(len(text) / self.input_chars_per_token)
        tokens_out = int(self.settings.max_tokens)
        p = self.settings.pricing_usd_per_mtok
        usd = None if p is None else (tokens_in * p.input + tokens_out * p.output) / 1e6
        return tokens_in + tokens_out, usd

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        """One decision request: checked, projected against every cap, then sent.

        Raises:
            GatewayRefusal: The request would take the run past a cap; nothing was sent.
            ModelError: The request is not a frozen decision's, or the call failed.
        """
        point, role = self.decision_of(request)
        tokens, usd = self.projected(request)
        if self.meter.requests + 1 > self.max_turns:
            raise GatewayRefusal(f"{point}: the run's {self.max_turns} requests are spent")
        if self.meter.total + tokens > self.max_total_tokens:
            raise GatewayRefusal(
                f"{point}: {self.meter.total} + {tokens} tokens would pass the run's "
                f"{self.max_total_tokens}"
            )
        spent = self.cost_usd()
        if usd is None or spent is None:
            raise GatewayRefusal(f"{point}: no declared price, so the USD cap cannot hold")
        if spent + usd > self.max_usd:
            raise GatewayRefusal(
                f"{point}: USD {spent:.4f} + {usd:.4f} would pass the run's {self.max_usd}"
            )
        self.provenance = {**self.base_provenance, "point": point, "role": role}
        before = self.meter.total
        out = super().complete(request)
        used = self.by_role.setdefault(role, {"tokens": 0, "requests": 0})
        used["tokens"] += self.meter.total - before
        used["requests"] += 1
        return out
