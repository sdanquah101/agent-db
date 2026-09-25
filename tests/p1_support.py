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
    the defaults, turn 2 examines two residuals, turn 3 records the evidence (its numbers
    copied from the residual call's result), turn 4 concludes with an abstention outside
    the vocabulary (the harness refuses it), turn 5 concludes correctly, naming the
    simulate call as the final prediction the harness validates.
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
    rd = got["tu_2_0"]
    if turn == 3:
        z = rd["result"]["standardised"]
        return reply(
            tool_use(
                3,
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
    conclusion = conclusion_for(sim)
    if turn == 4:
        return reply(tool_use(4, 0, "conclude", {**conclusion, "abstentions": ["everything"]}))
    return reply(tool_use(turn, 0, "conclude", conclusion))


def conclusion_for(sim: int) -> dict[str, Any]:
    """A valid conclusion on a clean cell, naming ``sim`` as the final prediction."""
    return {
        "label": "none",
        "secondary_labels": [],
        "confidence": 0.6,
        "kinetic_update": False,
        "parameters": {},
        "interval_method": "none",
        "abstentions": [],
        "prediction": sim,
        "summary": "No fault is supported.",
    }


def slow(policy: Policy, turn: int, seconds: float) -> Policy:
    """``policy`` with a pause before answering ``turn``: the registry's clock moves on."""
    import time

    def wrapped(params: dict[str, Any]) -> dict[str, Any]:
        if turn_of(params) == turn:
            time.sleep(seconds)
        return policy(params)

    return wrapped


def adversarial_policy(params: dict[str, Any]) -> dict[str, Any]:
    """Every refused form of the review of PR #26, then a valid conclusion.

    Turn 1 examines the gas-flow residual and calls Fisher on one parameter. Turn 2
    fabricates a residual z-score, gives a word for a number, cites the gas-flow value
    under the pH sensor's tag, asks for the hold-out validation, and quarantines a window
    of the hold-out (with one of the calibration window in the same call, which must not
    be applied either). Turn 3 claims a Fisher interval that is not the Fisher call's (the
    re-review's [0.999, 1.001]) and a profile interval with no profile. Turn 4 puts `none`
    beside a real label. Turn 5 concludes validly, reporting the Fisher call's own interval
    where it is finite, and in the same turn asks for one more simulate.
    """
    turn = turn_of(params)
    got = results(params)
    if turn == 0:
        return reply(tool_use(0, 0, "simulate", {}))
    sim = got["tu_0_0"]["call_index"]
    if turn == 1:
        return reply(
            tool_use(1, 0, "residual_diag", {"sensor": "gas_flow", "prediction": sim}),
            tool_use(1, 1, "fisher_info", {"parameters": ["k_m_ac"], "sensors": ["gas_flow"]}),
        )
    rd = got["tu_1_0"]["call_index"]
    real_z = got["tu_1_0"]["result"]["standardised"]["bias_z"]
    if turn == 2:
        ev = {"label": "sensor", "statement": "a large bias", "calls": [sim, rd]}
        return reply(
            tool_use(2, 0, "record_evidence", {**ev, "values": {"bias_z": 42.0}}),
            tool_use(2, 1, "record_evidence", {**ev, "values": {"bias_z": "huge"}}),
            tool_use(2, 4, "record_evidence", {**ev, "values": {"sensor": "ph", "bias_z": real_z}}),
            tool_use(2, 2, "validate", {"prediction": sim}),
            tool_use(
                2,
                3,
                "set_sensor_status",
                {
                    "sensor": "gas_flow",
                    "status": "quarantined",
                    "in_objective": True,
                    "quarantine": [[10, 12], [25, 26]],
                    "reason": "a spike in the hold-out",
                },
            ),
        )
    base = conclusion_for(sim)
    if turn == 3:
        return reply(
            tool_use(
                3,
                0,
                "conclude",
                {
                    **base,
                    "parameters": {
                        "k_m_ac": {
                            "estimate": 1.0,
                            "lower": 0.999,
                            "upper": 1.001,
                            "method": "fisher",
                        },
                        "k_dis": {"estimate": 1.0, "lower": 0.9, "upper": 1.1, "method": "profile"},
                    },
                    "interval_method": "fisher",
                },
            )
        )
    if turn == 4:
        return reply(
            tool_use(4, 0, "conclude", {**base, "label": "sensor", "secondary_labels": ["none"]})
        )
    return reply(
        tool_use(turn, 0, "conclude", base),
        tool_use(turn, 1, "simulate", {"parameters": {"k_m_ac": 1.5}}),
    )


def dawdling_policy(params: dict[str, Any]) -> dict[str, Any]:
    """Never concludes: inspects the record every turn (the run must stop unconcluded)."""
    turn = turn_of(params)
    return reply(tool_use(turn, 0, "inspect_record", {"what": "sensor", "name": "ph"}))


def peeking_policy(params: dict[str, Any]) -> dict[str, Any]:
    """Tries to read the hold-out through every tool that takes the record, then concludes.

    The re-review of e4fc44a, item 1: data_qc, mass_balance at one-day windows, and record
    inspection of hold-out days, each of which must return nothing from the hold-out.
    """
    turn = turn_of(params)
    if turn == 0:
        return reply(
            tool_use(0, 0, "data_qc", {}),
            tool_use(0, 1, "mass_balance", {"window_d": 1}),
            tool_use(0, 2, "inspect_record",
                     {"what": "sensor", "name": "gas_flow", "start_d": 23, "end_d": 30}),
            tool_use(0, 3, "inspect_record", {"what": "feed_log", "start_d": 23, "end_d": 30}),
            tool_use(0, 4, "inspect_record",
                     {"what": "feed_assays", "start_d": 23, "end_d": 30}),
        )  # fmt: skip
    final = {k: v for k, v in conclusion_for(0).items() if k != "prediction"}
    return reply(tool_use(turn, 0, "conclude", final))


def chosen_point_policy(params: dict[str, Any]) -> dict[str, Any]:
    """Tries every way to pass a chosen point off as an estimate, then reports a real one.

    The re-reviews of e4fc44a (2) and 1624e4d (2). Turn 0 simulates at a chosen k_m_ac of
    1.37, calls Fisher there, and runs a fit that starts at 1.37 with one evaluation (it
    does not converge and returns its start). Turn 1 offers 1.37 with the Fisher call's
    interval; turn 2 offers 1.37 with method none. Both are refused. Turn 3 fits properly.
    Turn 4 calls Fisher at the optimum twice: once with a second parameter at a chosen
    value, once at the optimum alone. Turn 5 offers the first call's interval (refused
    unless it is also the fit's own interval); turn 6 the second's (accepted), or the
    optimum with method none if the Fisher bound is not finite. A fit that did not
    converge ends the run with no estimate.
    """
    turn = turn_of(params)
    got = results(params)
    if turn == 0:
        return reply(
            tool_use(0, 0, "simulate", {"parameters": {"k_m_ac": 1.37}}),
            tool_use(0, 1, "fisher_info",
                     {"parameters": ["k_m_ac"], "sensors": ["gas_flow"], "at": {"k_m_ac": 1.37}}),
            tool_use(0, 2, "fit_lsq",
                     {"parameters": ["k_m_ac"], "sensors": ["gas_flow"], "start": {"k_m_ac": 1.37},
                      "n_starts": 1, "max_nfev_per_start": 1}),
        )  # fmt: skip
    sim = got["tu_0_0"]["call_index"]
    base = conclusion_for(sim)
    if turn == 1:
        iv = got["tu_0_1"]["result"]["interval_90_at_point"]["k_m_ac"] or [0.33, 3.0]
        chosen = {"estimate": 1.37, "lower": iv[0], "upper": iv[1], "method": "fisher"}
        return reply(
            tool_use(1, 0, "conclude", {**base, "parameters": {"k_m_ac": chosen},
                                        "interval_method": "fisher"})
        )  # fmt: skip
    if turn == 2:
        chosen = {"estimate": 1.37, "lower": None, "upper": None, "method": "none"}
        return reply(tool_use(2, 0, "conclude", {**base, "parameters": {"k_m_ac": chosen}}))
    if turn == 3:
        return reply(
            tool_use(3, 0, "fit_lsq", {"parameters": ["k_m_ac"], "sensors": ["gas_flow"],
                                       "n_starts": 1, "max_nfev_per_start": 20})
        )  # fmt: skip
    fit = got["tu_3_0"]["result"]
    theta = fit["theta"]["k_m_ac"]
    if not fit["converged"]:
        return reply(tool_use(turn, 0, "conclude", base))
    if turn == 4:
        return reply(
            tool_use(4, 0, "fisher_info",
                     {"parameters": ["k_m_ac", "k_dis"], "sensors": ["gas_flow"],
                      "at": {"k_m_ac": theta, "k_dis": 1.37}}),
            tool_use(4, 1, "fisher_info",
                     {"parameters": ["k_m_ac"], "sensors": ["gas_flow"], "at": {"k_m_ac": theta}}),
        )  # fmt: skip
    mixed = got["tu_4_0"]["result"]["interval_90_at_point"]["k_m_ac"]
    alone = got["tu_4_1"]["result"]["interval_90_at_point"]["k_m_ac"]
    if turn == 5 and mixed is not None:
        est = {"estimate": theta, "lower": mixed[0], "upper": mixed[1], "method": "fisher"}
        return reply(
            tool_use(5, 0, "conclude", {**base, "parameters": {"k_m_ac": est},
                                        "interval_method": "fisher"})
        )  # fmt: skip
    if alone is not None and alone != mixed:
        est = {"estimate": theta, "lower": alone[0], "upper": alone[1], "method": "fisher"}
        final = {**base, "parameters": {"k_m_ac": est}, "interval_method": "fisher"}
    else:
        est = {"estimate": theta, "lower": None, "upper": None, "method": "none"}
        final = {**base, "parameters": {"k_m_ac": est}}
    return reply(tool_use(turn, 0, "conclude", final))


def probe_policy(params: dict[str, Any]) -> dict[str, Any]:
    """Uses every tool that reads the record, for the two-copy hold-out test.

    The re-review of 1624e4d, item 1: run on two copies of a cell that differ only in
    hold-out values, every request this policy's run sends must be the same.
    """
    turn = turn_of(params)
    got = results(params)
    if turn == 0:
        return reply(
            tool_use(0, 0, "data_qc", {}),
            tool_use(0, 1, "mass_balance", {"window_d": 5}),
            tool_use(0, 2, "inspect_record", {"what": "sensor", "name": "gas_flow"}),
            tool_use(0, 3, "inspect_record", {"what": "feed_assays"}),
            tool_use(0, 4, "simulate", {}),
            tool_use(0, 5, "feed_loads", {}),
        )
    sim = got["tu_0_4"]["call_index"]
    if turn == 1:
        return reply(
            tool_use(1, 0, "residual_diag", {"sensor": "gas_flow", "prediction": sim}),
            tool_use(1, 1, "residual_diag", {"sensor": "ph", "prediction": sim}),
            tool_use(1, 2, "fisher_info", {"parameters": ["k_m_ac"]}),
            tool_use(1, 3, "fit_lsq",
                     {"parameters": ["k_m_ac"], "n_starts": 1, "max_nfev_per_start": 3}),
            tool_use(1, 4, "request_assay", {"assay": "tan", "day": 10, "prediction": sim}),
        )  # fmt: skip
    return reply(tool_use(turn, 0, "conclude", conclusion_for(sim)))
