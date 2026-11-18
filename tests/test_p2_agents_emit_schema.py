"""The ``emit_finding`` schema as sent, and the refusal that names every error (2026-11-17).

The live pilot of 2026-11-13 gave no verdict: ``role_tool_specs`` nested the finding's
``$defs`` under ``properties.finding`` while Pydantic's references are root-relative
(``#/$defs/EvidenceRef``), and ``tools/llm.py`` sends ``input_schema`` itself as the
tool's ``parameters``. Every reference dangled, so no role saw the shape of an evidence
item, a hold-out or a separating test; ``check_finding`` named one error per refusal, and
the roles spent their turns finding the schema one field at a time. The lead's ruling:
"stop, and yes to the fix".

Offline, each with its control:

* for every role, every ``$ref`` in the ``emit_finding`` parameters **as built by the
  client's request path** resolves (the control: the old nesting dangles, under the same
  test);
* a finding valid against the sent schema (checked by a validator that refuses an
  unresolved reference and any keyword it does not know) passes the schema stage; one
  missing two nested fields is refused with both named, and more than the bound are
  counted;
* a scripted model that builds its finding from the sent schema alone (not from code, as
  ``OfflineModel`` does) gets it accepted through the role's own loop, for the verifier
  and every proposer that can act with no assay (the control: on the old nesting the same
  model cannot build one).
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from tests.p2_support import FakeTools
from tests.test_p2_agents_harness import AGENTS_YAML, _install
from tools.llm import to_responses_request
from tools.workflow_config import load_p2
from workflows.p2_multi_agent import agents, messages

ARM = load_p2(AGENTS_YAML)
ROLES = sorted(ARM.agents.roles)
ANNOTATIONS = {"title", "description", "default", "examples"}


class Dangling(Exception):
    """A ``$ref`` that does not resolve in the schema as sent."""


# ------------------------------------------------------------------ the schema as sent


def sent_parameters(specs: list[dict[str, Any]], name: str = "emit_finding") -> dict[str, Any]:
    """The ``parameters`` of tool ``name`` exactly as ``tools/llm.py`` builds the request."""
    request = to_responses_request(
        {
            "model": ARM.model.model_id,
            "max_tokens": ARM.model.max_tokens,
            "messages": [{"role": "user", "content": "{}"}],
            "tools": specs,
        }
    )
    (tool,) = [t for t in request["tools"] if t["name"] == name]
    return tool["parameters"]


def old_nesting(role: str) -> list[dict[str, Any]]:
    """The tool list as it was at 14c220f: the finding's ``$defs`` left under ``finding``."""
    specs = agents.role_tool_specs(role, list(ARM.agents.roles[role].tools))
    model = messages.FINDINGS[role]
    specs[-1] = {
        **specs[-1],
        "input_schema": {
            "type": "object",
            "description": model.__name__,
            "properties": {"finding": model.model_json_schema()},
            "required": ["finding"],
            "additionalProperties": False,
        },
    }
    return specs


def refs(node: Any) -> list[str]:
    """Every ``$ref`` string anywhere under ``node``."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                out.append(v)
            else:
                out.extend(refs(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(refs(v))
    return out


def resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    """The schema ``ref`` names, as a JSON pointer into ``root`` (the sent parameters)."""
    if not ref.startswith("#/"):
        raise Dangling(f"{ref}: not a local reference")
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise Dangling(f"{ref}: no {part!r} at the sent root")
        node = node[part]
    return node


def dangling(root: dict[str, Any]) -> list[str]:
    """The references under ``root`` that do not resolve against ``root``."""
    bad = []
    for ref in refs(root):
        try:
            resolve(ref, root)
        except Dangling:
            bad.append(ref)
    return bad


def _type_ok(value: Any, kind: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "null": value is None,
    }[kind]


def validate(value: Any, schema: dict[str, Any], root: dict[str, Any], at: str = "$") -> list[str]:
    """The JSON-schema errors of ``value`` (the subset Pydantic emits), resolving at ``root``.

    An unresolved reference raises :class:`Dangling`; a keyword this validator does not
    know raises ``ValueError``: a validator that skipped either would pass anything.
    """
    unknown = set(schema) - ANNOTATIONS - {
        "$ref", "$defs", "type", "enum", "const", "pattern", "required", "properties",
        "additionalProperties", "patternProperties", "items", "prefixItems", "minItems",
        "maxItems", "minimum", "maximum", "maxProperties", "anyOf",
    }  # fmt: skip
    if unknown:
        raise ValueError(f"{at}: keywords this validator does not know: {sorted(unknown)}")
    if "$ref" in schema:
        return validate(value, resolve(schema["$ref"], root), root, at)
    if "anyOf" in schema:
        branches = [validate(value, s, root, at) for s in schema["anyOf"]]
        return [] if any(not b for b in branches) else [f"{at}: matches no anyOf branch"]
    errors: list[str] = []
    if "type" in schema and not _type_ok(value, schema["type"]):
        return [f"{at}: not {schema['type']}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{at}: not in enum")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{at}: not the const")
    if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
        errors.append(f"{at}: does not match {schema['pattern']}")
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{at}: below the minimum")
    if "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{at}: above the maximum")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        pats = schema.get("patternProperties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{at}.{key}: required")
        if len(value) > schema.get("maxProperties", len(value)):
            errors.append(f"{at}: too many properties")
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], root, f"{at}.{key}")
                continue
            matched = [s for p, s in pats.items() if re.search(p, key)]
            for s in matched:
                errors += validate(item, s, root, f"{at}.{key}")
            extra = schema.get("additionalProperties", True)
            if not matched and extra is False:
                errors.append(f"{at}.{key}: not permitted")
            elif not matched and isinstance(extra, dict):
                errors += validate(item, extra, root, f"{at}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get(
            "maxItems", len(value)
        ):
            errors.append(f"{at}: wrong number of items")
        prefix = schema.get("prefixItems", [])
        for i, item in enumerate(value):
            sub = prefix[i] if i < len(prefix) else schema.get("items")
            if sub is not None:
                errors += validate(item, sub, root, f"{at}[{i}]")
    return errors


# ------------------------------------------------------------------ a schema-only model

PREFER = ("abstain", "no_claim", "none")
"""Where the schema offers a choice, the scripted model takes a modest one if offered."""


def build(schema: dict[str, Any], root: dict[str, Any], call: int) -> Any:
    """A value of ``schema`` built from the schema alone (resolving at ``root``).

    Required fields only, plus one item in every array whose items are a referenced
    message (so the evidence item's shape is exercised); a choice takes a :data:`PREFER`
    option where one is offered, else the first; every integer of a ``calls``-like list
    and every bare integer is ``call`` (the index the model was shown); a pattern string
    is the first alternative of an anchored ``^(a|b|...)$`` pattern.
    """
    if "$ref" in schema:
        return build(resolve(schema["$ref"], root), root, call)
    if "anyOf" in schema:
        options = [s for s in schema["anyOf"] if s.get("type") != "null"]
        return build(options[0], root, call)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return next((v for v in PREFER if v in schema["enum"]), schema["enum"][0])
    kind = schema.get("type")
    if kind == "object":
        props = schema.get("properties", {})
        out = {k: build(props[k], root, call) for k in schema.get("required", [])}
        for k, s in props.items():
            if k not in out and s.get("type") == "array" and "$ref" in s.get("items", {}):
                out[k] = [build(s["items"], root, call)]
        return out
    if kind == "array":
        n = schema.get("minItems", 0)
        prefix = schema.get("prefixItems", [])
        out = []
        for i in range(n):
            sub = prefix[i] if i < len(prefix) else schema["items"]
            value = build(sub, root, call)
            m = re.fullmatch(r"\^\(([A-Za-z0-9_|]+)\)\$", sub.get("pattern", ""))
            if value in out and m is not None:  # a tuple of choices: distinct ones
                value = next(v for v in m.group(1).split("|") if v not in out)
            out.append(value)
        return out
    if kind == "string":
        pattern = schema.get("pattern")
        if pattern is None:
            return "x"
        m = re.fullmatch(r"\^\(([A-Za-z0-9_|]+)\)\$", pattern)
        if m is not None:
            options = m.group(1).split("|")
            return next((v for v in PREFER if v in options), options[0])
        token = next((t for t in ("x", "-", "1") if re.search(pattern, t)), None)
        if token is None:
            raise ValueError(f"cannot build a string for pattern {pattern!r}")
        return token
    if kind == "integer":
        lo, hi = schema.get("minimum", call), schema.get("maximum", call)
        return call if lo <= call <= hi else int(lo)
    if kind == "number":
        return float(schema.get("minimum", 0.0))
    if kind == "boolean":
        return False
    raise ValueError(f"cannot build a value for {schema!r:.80}")


class SchemaOnlyModel:
    """A scripted role that reads the tool list the client would send, and nothing else.

    Turn 1: one call of ``first`` (no arguments). Turn 2: ``emit_finding``, its finding
    built by :func:`build` from the sent parameters, citing the call index turn 1 returned.
    """

    def __init__(self, first: str) -> None:
        """Set up with the role's first tool."""
        self.first = first
        self.turn = 0
        self.call = -1

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        """The next reply."""
        self.turn += 1
        last = request["messages"][-1]["content"]
        if isinstance(last, list):
            for block in last:
                if block.get("type") == "tool_result" and not block.get("is_error"):
                    self.call = int(json.loads(block["content"])["call_index"])
        if self.turn == 1:
            block = {"type": "tool_use", "id": "s-1", "name": self.first, "input": {}}
        else:
            params = sent_parameters(request["tools"])
            finding = build(params["properties"]["finding"], params, self.call)
            block = {
                "type": "tool_use",
                "id": f"s-{self.turn}",
                "name": "emit_finding",
                "input": {"finding": finding},
            }
        return {"response": {"content": [block], "stop_reason": "tool_use", "usage": {}}}


FIRST_TOOL = {  # a tool each role may call with no arguments; design needs an assay
    "data_quality": "data_qc",
    "influent": "mass_balance",
    "identifiability": "describe_model",
    "calibration": "simulate",
    "verification": "simulate",
}


# ------------------------------------------------------------------ (a) the references


@pytest.mark.parametrize("role", ROLES)
def test_every_emit_finding_reference_resolves_in_the_parameters_as_sent(role):
    params = sent_parameters(agents.role_tool_specs(role, list(ARM.agents.roles[role].tools)))
    found = refs(params)
    assert found, "no reference at all: the test would pass on anything"
    assert dangling(params) == []
    assert "$defs" not in params["properties"]["finding"]
    # the control: the old nesting, through the same request path, dangles
    old = sent_parameters(old_nesting(role))
    assert sorted(set(dangling(old))) == sorted(set(refs(old))) != []


def test_the_verifiers_three_messages_are_reachable_as_sent():
    params = sent_parameters(
        agents.role_tool_specs("verification", list(ARM.agents.roles["verification"].tools))
    )
    assert sorted(params["$defs"]) == ["EvidenceRef", "HoldoutResult", "SeparatingTest"]
    for name in params["$defs"]:
        assert resolve(f"#/$defs/{name}", params)["title"] == name


def test_the_validator_refuses_a_dangling_reference_and_an_unknown_keyword():
    """The checker's own controls: it can fail, so its passes mean something."""
    with pytest.raises(Dangling):
        validate({}, {"$ref": "#/$defs/Nowhere"}, {})
    with pytest.raises(ValueError, match="does not know"):
        validate({}, {"type": "object", "oneOf": []}, {})
    assert validate({"a": 1}, {"type": "object", "additionalProperties": False}, {}) == [
        "$.a: not permitted"
    ]


# ------------------------------------------------------------------ (b) the schema stage


@pytest.mark.parametrize("role", ROLES)
def test_a_finding_valid_against_the_sent_schema_passes_the_schema_stage(role):
    params = sent_parameters(agents.role_tool_specs(role, list(ARM.agents.roles[role].tools)))
    finding = build(params["properties"]["finding"], params, 3)
    assert validate({"finding": finding}, params, params) == []
    if "evidence" in finding:
        assert finding["evidence"] and set(finding["evidence"][0]) >= {"label", "rule", "calls"}
    parsed = agents.parse_finding(role, finding)
    assert isinstance(parsed, messages.FINDINGS[role])
    # the control: the same finding with a field the sent schema does not allow is refused
    # by both the sent schema and the schema stage
    bad = {**finding, "statement": "x"}
    assert validate({"finding": bad}, params, params) != []
    with pytest.raises(agents.ActionError, match="statement"):
        agents.parse_finding(role, bad)


def test_a_finding_missing_two_nested_fields_is_refused_with_both_named():
    item = {"calls": [3], "values": {}, "units": {}}  # no label, no rule
    finding = {"round": 1, "verdict": "abstain", "evidence": [item]}
    with pytest.raises(agents.ActionError) as exc:
        agents.parse_finding("verification", finding)
    text = str(exc.value)
    assert "2 error(s)" in text
    assert "evidence.0.label: Field required" in text
    assert "evidence.0.rule: Field required" in text
    # and through check_finding, the path the role's loop takes (the schema stage needs
    # no workspace: it refuses before any evidence is looked up)
    with pytest.raises(agents.ActionError) as exc2:
        agents.check_finding(None, "verification", finding, 1)
    assert str(exc2.value) == text
    # the control: with the two fields the item passes the schema stage
    agents.parse_finding(
        "verification", {**finding, "evidence": [{**item, "label": "none", "rule": "sensor"}]}
    )


def test_a_refusal_names_at_most_the_bound_and_counts_the_rest():
    n = agents.FINDING_ERRORS_SHOWN + 5
    items = [{"calls": [1]} for _ in range(n)]  # each misses label and rule
    with pytest.raises(agents.ActionError) as exc:
        agents.parse_finding("verification", {"round": 1, "verdict": "abstain", "evidence": items})
    text = str(exc.value)
    assert f"{2 * n} error(s)" in text
    assert text.count("Field required") == agents.FINDING_ERRORS_SHOWN
    assert text.endswith(f"; and {2 * n - agents.FINDING_ERRORS_SHOWN} more")


# ------------------------------------------------------------------ (c) a schema-only model


def _agent(monkeypatch, role: str, responder: Any) -> agents.RoleAgent:
    fake = FakeTools("B", "B", evals=5000, offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    from tests.test_p2_agents_harness import _cfg

    run = agents.AgentRun(_cfg())
    run.code_steps()
    return agents.RoleAgent(
        role, run.ws, responder, round_=1,
        grant={"evaluations": 10**4, "assays": 0}, brief={}, turns=4,
    )  # fmt: skip


@pytest.mark.parametrize("role", sorted(FIRST_TOOL))
def test_a_model_reading_only_the_sent_schema_gets_its_finding_accepted(monkeypatch, role):
    model = SchemaOnlyModel(FIRST_TOOL[role])
    agent = _agent(monkeypatch, role, model)
    finding = agent.run()
    assert finding is not None, agent.stop_reason
    assert agent.stop_reason == "finding emitted"
    assert agent.state["refused"] == 0 and agent.state["turns"] == 2
    assert finding.evidence and finding.evidence[0].calls == [model.call]


@pytest.mark.parametrize("role", ["verification", "data_quality"])
def test_on_the_old_nesting_the_same_model_cannot_build_a_finding(monkeypatch, role):
    """The control of the test above: the bug, reproduced through the same path."""
    agent = _agent(monkeypatch, role, SchemaOnlyModel(FIRST_TOOL[role]))
    agent.specs = old_nesting(role)
    with pytest.raises(Dangling):
        agent.run()
    assert agent.finding is None
