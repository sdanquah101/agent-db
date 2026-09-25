"""Scripted model policies for P1's tests: the deterministic test double's brains.

A policy is a pure function of the request the gateway would send (``tools.llm``): it
reads its own earlier tool results out of the history and returns the next response in
the Messages API's shape. Nothing here calls a network or needs a key.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

Policy = Callable[[dict[str, Any]], dict[str, Any]]


def tool_use(turn: int, k: int, name: str, inp: dict[str, Any]) -> dict[str, Any]:
    """A tool_use block with a deterministic id."""
    return {"type": "tool_use", "id": f"tu_{turn}_{k}", "name": name, "input": inp}


def reply(*blocks: dict[str, Any], text: str = "") -> dict[str, Any]:
    """A response whose content is an optional text block then the tool uses."""
    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.extend(blocks)
    stop = "tool_use" if any(b.get("type") == "tool_use" for b in blocks) else "end_turn"
    return {"content": content, "stop_reason": stop}


def results(params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every tool result so far, by tool_use id, parsed; ``is_error`` kept."""
    out: dict[str, dict[str, Any]] = {}
    for message in params["messages"]:
        if message["role"] != "user" or isinstance(message["content"], str):
            continue
        for block in message["content"]:
            if block.get("type") == "tool_result":
                payload = json.loads(block["content"])
                payload["_is_error"] = bool(block.get("is_error"))
                out[block["tool_use_id"]] = payload
    return out


def turn_of(params: dict[str, Any]) -> int:
    """How many assistant turns the history already holds."""
    return sum(1 for m in params["messages"] if m["role"] == "assistant")


def clean_policy(params: dict[str, Any]) -> dict[str, Any]:
    """A short, disciplined run on a clean cell, with one refused action on the way.

    Turn 0 checks quality and balances (two tool uses in one turn), turn 1 simulates at
    the defaults, turn 2 examines two residuals, turn 3 validates on the hold-out, turn 4
    records the evidence, turn 5 concludes with an abstention outside the vocabulary (the
    harness refuses it), turn 6 concludes correctly.
    """
    turn = turn_of(params)
    got = results(params)
    if turn == 0:
        return reply(
            tool_use(0, 0, "data_qc", {}),
            tool_use(0, 1, "mass_balance", {}),
            text="Quality and balances first.",
        )
    if turn == 1:
        return reply(tool_use(1, 0, "simulate", {}))
    sim = got["tu_1_0"]["call_index"]
    if turn == 2:
        return reply(
            tool_use(2, 0, "residual_diag", {"sensor": "gas_flow", "prediction": sim}),
            tool_use(2, 1, "residual_diag", {"sensor": "ph", "prediction": sim}),
        )
    if turn == 3:
        return reply(tool_use(3, 0, "validate", {"prediction": sim}))
    rd = got["tu_2_0"]
    if turn == 4:
        z = rd["result"]["standardised"]
        return reply(
            tool_use(
                4,
                0,
                "record_evidence",
                {
                    "label": "none",
                    "statement": "gas flow residual shows no step",
                    "values": {"sensor": "gas_flow", "bias_z": z["bias_z"], "rmse_z": z["rmse_z"]},
                    "calls": [sim, rd["call_index"]],
                },
            )
        )
    conclusion = {
        "label": "none",
        "secondary_labels": [],
        "confidence": 0.6,
        "kinetic_update": False,
        "parameters": {"k_m_ac": {"estimate": 1.0, "lower": None, "upper": None, "method": "none"}},
        "interval_method": "none",
        "abstentions": [],
        "summary": "No fault is supported.",
    }
    if turn == 5:
        return reply(tool_use(5, 0, "conclude", {**conclusion, "abstentions": ["everything"]}))
    return reply(tool_use(turn, 0, "conclude", conclusion))


def dawdling_policy(params: dict[str, Any]) -> dict[str, Any]:
    """Never concludes: inspects the record every turn (the run must stop unconcluded)."""
    turn = turn_of(params)
    return reply(tool_use(turn, 0, "inspect_record", {"what": "sensor", "name": "ph"}))
