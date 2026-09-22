"""Constructed truth/state pairs for the evaluation suite's tests.

A :func:`build_run` writes the two trees of one run the way the harness, the registry and
the runner would -- ``truth_store/<id>/`` with a manifest, the answer key, the parameters
and a truth-side log; ``runs/<id>/`` with the visible log and the workflow's ``state.json``
and ``summary.json`` -- from small dictionaries, so each metric can be scored on a positive
and a negative case without integrating anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from state.provenance import CallLog
from tools.server import OUTPUTS_DIR

DEFAULT_TRUTH = {"k_dis": 0.5, "k_m_ac": 8.0, "Y_ac": 0.05, "K_I_nh3": 0.0018}
"""Absolute defaults the constructed truth uses (BSM2 values of four parameters)."""


def truth_segment(multipliers: dict[str, float] | None = None) -> dict[str, Any]:
    """One integration segment with the given multipliers of :data:`DEFAULT_TRUTH`."""
    m = multipliers or {}
    return {
        "t_start_d": 0.0,
        "t_end_d": 200.0,
        "parameters": {
            "kinetics": {
                "k_dis": DEFAULT_TRUTH["k_dis"] * m.get("k_dis", 1.0),
                "k_m_ac": DEFAULT_TRUTH["k_m_ac"] * m.get("k_m_ac", 1.0),
                "K_I_nh3": DEFAULT_TRUTH["K_I_nh3"] * m.get("K_I_nh3", 1.0),
            },
            "stoichiometry": {"Y_ac": DEFAULT_TRUTH["Y_ac"] * m.get("Y_ac", 1.0)},
            "physchem": {},
        },
    }


def parameter(estimate: float, lower: float | None, upper: float | None, **kw: Any) -> dict:
    """A final parameter estimate."""
    return {
        "estimate": estimate,
        "lower": lower,
        "upper": upper,
        "method": kw.get("method", "fisher" if lower is not None else "none"),
        "at_bound": kw.get("at_bound", False),
        "unit": "",
    }


def action(step: str, name: str, seq: int, args_hash: str, call_index: int, **kw: Any) -> dict:
    """One action of the state, as the log names it."""
    return {
        "step": step,
        "name": name,
        "version": "1.0",
        "args_hash": args_hash,
        "seq": seq,
        "call_index": call_index,
        "outcome": kw.get("outcome", "ok"),
        "detail": kw.get("detail", ""),
    }


def evidence(rule: str, label: str, values: dict[str, Any], calls: list[int]) -> dict:
    """One evidence item of the classification."""
    return {"rule": rule, "label": label, "statement": rule, "values": values, "calls": calls}


def minimal_state(run_id: str, **overrides: Any) -> dict[str, Any]:
    """A valid ``TaskState`` document with the fields the tests override."""
    state: dict[str, Any] = {
        "schema_version": "1.0",
        "workflow": "p0",
        "workflow_version": "1.0",
        "run_id": run_id,
        "plant": "B",
        "tier": "B",
        "duration_days": 200.0,
        "calibration_window": [0.0, 150.0],
        "holdout_window": [150.0, 200.0],
        "candidate_model": "adm1_fitted",
        "model_parameters": ["k_dis", "k_m_ac", "Y_ac", "K_I_nh3"],
        "calibrated_outputs": ["q_gas_stp_dry", "pH"],
        "data_quality": {},
        "mass_balance": {},
        "classification": {
            "label": "none",
            "secondary_labels": [],
            "confidence": 0.6,
            "rule": "R6",
            "evidence": [],
            "flag_sensor": None,
            "scale_factor": {},
            "revise_influent_mapping": False,
            "recommend_structural_review": False,
            "kinetic_update": True,
        },
        "screening": {"declared": ["k_dis", "k_m_ac", "Y_ac", "K_I_nh3"], "approved": ["k_dis"]},
        "residuals": {},
        "actions": [],
        "tool_failures": [],
        "budget": {
            "simulator_evals": 0,
            "simulator_evals_total": 100,
            "simulator_evals_used": 100,
            "wall_clock_min": 10.0,
            "wall_clock_min_total": 60.0,
            "assay_units": 0,
            "assay_units_total": 2,
            "assay_units_used": 2,
            "n_calls": 0,
        },
        "validation": None,
        "assay_checks": [],
        "abstentions": [],
        "final": {
            "label": "none",
            "secondary_labels": [],
            "confidence": 0.6,
            "parameters": {},
            "interval_method": "fisher",
            "abstentions": [],
            "completed": True,
        },
        "plan": {},
        "notes_seen": [],
        "annotations": [],
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(state.get(key), dict):
            state[key] = {**state[key], **value}
        else:
            state[key] = value
    return state


def build_run(
    root: Path,
    run_id: str = "run_000000000001",
    *,
    workflow: str = "p0",
    level: int = 0,
    scenario_id: str = "S0-01",
    plant: str = "B",
    tier: str = "B",
    truth_label: tuple[str, ...] = ("none",),
    correct_conclusion: dict[str, Any] | None = None,
    segments: list[dict[str, Any]] | None = None,
    state: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    calls: list[dict[str, Any]] | None = None,
    duration_days: float = 200.0,
    write_state: bool = True,
    write_summary: bool = True,
    index: bool = True,
) -> tuple[Path, Path]:
    """Write one constructed run under ``root/runs`` and ``root/truth_store``.

    ``calls`` are the workflow's calls in order, each ``{"name", "args", "outcome",
    "n_evaluations", "assay_units", "detail"}``; they are logged to both logs after a
    ``registry.open`` record, exactly as the registry logs them.

    Returns:
        ``(runs_root, truth_store)``.
    """
    runs_root = root / "runs"
    store = root / "truth_store"
    run_dir = runs_root / run_id
    truth_dir = store / run_id
    (run_dir / "observations").mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    conclusion = {
        "flag_sensor": None,
        "estimate_scale_factor": False,
        "kinetic_update_allowed": "parameter" in truth_label or truth_label == ("none",),
        "abstain_on": [],
        "revise_influent_mapping": False,
        "recommend_structural_review": False,
    }
    conclusion.update(correct_conclusion or {})
    manifest = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "level": level,
        "plant": plant,
        "tier": tier,
        "duration_days": duration_days,
        "n_days": int(duration_days),
        "seeds": {"observation": 5},
    }
    (truth_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "manifest.json").write_text(
        json.dumps({k: manifest[k] for k in ("run_id", "plant", "tier", "duration_days")})
    )
    (truth_dir / "faults.json").write_text(
        json.dumps(
            {
                "scenario_id": scenario_id,
                "level": level,
                "truth_label": list(truth_label),
                "correct_conclusion": conclusion,
                "faults": [],
            }
        )
    )
    (truth_dir / "parameters.json").write_text(
        json.dumps(
            {
                "fitted_extensions": [],
                "segments": segments if segments is not None else [truth_segment()],
            }
        )
    )
    if index:
        with (store / "index.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "run_id": run_id,
                        "scenario_id": scenario_id,
                        "level": level,
                        "plant": plant,
                        "tier": tier,
                        "seed": 1,
                        "replicate": 0,
                    }
                )
                + "\n"
            )

    visible = CallLog(run_dir, fresh=True, projection=True)
    full = CallLog(truth_dir, fresh=True)
    # the harness's own record precedes the registry's
    full.append("sim.simulate_truth", "1.0", {"segment": 0}, 3.0, "ok")
    visible.append("sim.simulate_truth", "1.0", {"segment": 0}, 3.0, "ok")
    budget = {"simulator_evals": 100, "wall_clock_min": 60.0, "assay_units": 2}
    full.append("registry.open", "1.0", budget, 0.0, "ok", "clock start", n_evaluations=0)
    visible.append("registry.open", "1.0", budget, 0.0, "ok", "clock start")
    logged = []
    for call in calls or []:
        outcome = call.get("outcome", "ok")
        visible_outcome = "ok" if outcome == "injected_failure" else outcome
        full.append(
            call["name"],
            "1.0",
            call.get("args", {}),
            call.get("runtime_s", 1.0),
            outcome,
            call.get("detail", ""),
            n_evaluations=call.get("n_evaluations", 0),
            assay_units=call.get("assay_units", 0),
        )
        record = visible.append(
            call["name"],
            "1.0",
            call.get("args", {}),
            call.get("runtime_s", 1.0),
            visible_outcome,
            call.get("detail", ""),
        )
        logged.append(record)

    out_dir = run_dir / OUTPUTS_DIR / workflow
    if write_state or write_summary:
        out_dir.mkdir(parents=True, exist_ok=True)
    if write_state:
        doc = state if state is not None else minimal_state(run_id, plant=plant, tier=tier)
        (out_dir / "state.json").write_text(json.dumps(doc, indent=1))
    if write_summary:
        base = {
            "run_id": run_id,
            "workflow": workflow,
            "completed": write_state,
            "returncode": 0,
            "wall_s": 120.0,
            "simulator_evals_used": sum(int(c.get("n_evaluations", 0)) for c in calls or []),
            "simulator_evals_total": 100,
            "assay_units_used": sum(int(c.get("assay_units", 0)) for c in calls or []),
            "assay_units_total": 2,
            "wall_clock_min_total": 60.0,
            "n_calls": len(calls or []),
            "label": (state or {}).get("final", {}).get("label"),
            "cost_source": "registry_meter",
            "tokens_used": None,
            "error": "",
            "state_valid": write_state,
        }
        base.update(summary or {})
        (out_dir / "summary.json").write_text(json.dumps(base, indent=1))
    return runs_root, store


def actions_for(calls: list[dict[str, Any]], visible_log_dir: Path) -> list[dict[str, Any]]:
    """The state's ``actions`` naming each constructed call as the visible log does."""
    from state.provenance import read_calls

    lines = read_calls(visible_log_dir)
    opened = max(i for i, r in enumerate(lines) if r.name == "registry.open")
    out = []
    for index, call in enumerate(calls):
        line = lines[opened + 1 + index]
        out.append(
            action(
                call.get("step", call["name"]),
                call["name"],
                line.seq,
                line.args_hash,
                index,
                outcome="ok"
                if call.get("outcome", "ok") == "injected_failure"
                else call.get("outcome", "ok"),
            )
        )
    return out
