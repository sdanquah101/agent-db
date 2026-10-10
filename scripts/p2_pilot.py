"""P2's live pilot (deliverable 3; ``docs/p2_design.md`` §11): PREPARED, NOT RUN.

The pilot is the three-role minimum (data quality, calibration, verification;
coordination is code) with the live decider, on three development cells x two seeds
(replicates 0 and 1), about USD 0.3 in all:

| cell | truth | why |
|---|---|---|
| S0-01 B/B | ``none`` | the go/no-go cell (decisions b, c of 2026-10-07) |
| S2-01 B/B | ``sensor`` (pH drift) | data quality's S1 path |
| S8-01 B/B | ``sensor`` (gas scale), injected sampler failure | calibration's Level-8 path |

**No live call is made from this file until the lead approves the pilot**, after the
coordinator's review of deliverable 3. :data:`APPROVED` is ``False``; ``run`` refuses
while it is, whatever the flags, and before any client is built. Approving it is a
reviewed one-line commit that names the lead's word.

Usage::

    python -m scripts.p2_pilot plan                       # no call: cells, caps, layout
    python -m scripts.p2_pilot run --store DIR --live     # refused until APPROVED
    python -m scripts.p2_pilot report --store DIR         # reports/p2_pilot/

**The record layout.** ``DIR`` lies outside the repository:

- ``DIR/config/``: the pilot's configuration, which is ``p2.yaml`` with the three-role
  ablation (influent, identifiability and design off), beside ``p0.yaml`` and the
  templates. The runner checks it against the same freeze.
- ``DIR/runs/<id>/workflows/p2/``: the run's record (``state.json``, ``report.json``,
  ``messages.jsonl``, ``decisions.jsonl``), the gateway's ``llm_calls.jsonl`` and the
  runner's ``summary.json`` with ``by_role``.
- ``DIR/results.jsonl``: one line per finished cell (summary and outcome).
- ``reports/p2_pilot/cells.json`` and ``summary.md``: each cell and seed's outcome (keyed on
  the verdict, never the label alone), the go/no-go check on S0-01 B/B, and the cost.

**Caps.** Each run has the gateway's caps (``p2.yaml`` ``caps``: 60 requests, 6 M tokens,
USD 0.25). The pilot stops launching cells once :data:`PILOT_MAX_USD` is spent. The key
is ``OPENAI_API_KEY`` in the environment; it is checked for presence only and never
written. Nothing else runs on the container beside the pilot (the P1 pilot's rule).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "reports" / "p2_pilot"

APPROVED = False
"""The lead's approval of the pilot. False until a reviewed commit names the lead's word."""

CELLS: tuple[tuple[str, str, str], ...] = (
    ("S0-01", "B", "B"),
    ("S2-01", "B", "B"),
    ("S8-01", "B", "B"),
)
REPLICATES = (0, 1)
"""Two seeds per cell: the cell's own seed (replicate 0) and its first replicate."""

THREE_ROLES = {"influent": False, "identifiability": False, "design": False}
"""The three-role minimum: data quality, calibration and verification stay on."""

PILOT_MAX_USD = 0.6
"""No further cell is launched once the pilot has spent this much (about twice the plan)."""

KEY_VARIABLE = "OPENAI_API_KEY"


def plan() -> dict[str, Any]:
    """What the pilot would run, at what caps; makes no call of any kind."""
    from tools.workflow_config import load_p2

    config = load_p2()
    return {
        "approved": APPROVED,
        "cells": [f"{s} {p}/{t}" for s, p, t in CELLS],
        "replicates": list(REPLICATES),
        "runs": len(CELLS) * len(REPLICATES),
        "roles_off": sorted(THREE_ROLES),
        "model": config.model.model_id,
        "effort": config.model.effort,
        "caps_per_run": config.caps.model_dump(),
        "pilot_max_usd": PILOT_MAX_USD,
        "expected_usd": 0.3,
        "command": "python -m scripts.p2_pilot run --store <DIR outside the repo> --live",
    }


def write_config(store: Path) -> Path:
    """The pilot's configuration: ``p2.yaml`` with the three-role ablation, its files beside."""
    src = REPO / "configs" / "workflows"
    dest = store / "config"
    dest.mkdir(parents=True, exist_ok=True)
    raw = yaml.safe_load((src / "p2.yaml").read_text(encoding="utf-8"))
    raw["ablation"]["roles"].update(THREE_ROLES)
    (dest / "p2.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    shutil.copy2(src / raw["p0_config"], dest / raw["p0_config"])
    shutil.copytree(src / "p2_prompts", dest / "p2_prompts", dirs_exist_ok=True)
    return dest / "p2.yaml"


def run(store: Path, *, live: bool) -> None:
    """Run the pilot: refused unless approved, live and keyed; caps enforced throughout.

    Raises:
        SystemExit: Not approved, not ``--live``, no key, or a store inside the repository.
    """
    if not APPROVED:
        raise SystemExit("the pilot is not approved: no live call before the lead's word")
    if not live:
        raise SystemExit("the pilot is live: pass --live")
    if not os.environ.get(KEY_VARIABLE):
        raise SystemExit(f"{KEY_VARIABLE} is not set")
    store = store.resolve()
    if store == REPO or REPO in store.parents:
        raise SystemExit("the store must be outside the repository")
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from sim.run.matrix import at_plant_horizon
    from tools.runner import run_workflow

    config_path = write_config(store)
    results = store / "results.jsonl"
    spent = 0.0
    for sid, plant_id, tier in CELLS:
        for rep in REPLICATES:
            if spent >= PILOT_MAX_USD:
                print(f"STOP: USD {spent:.3f} spent, the pilot's cap is {PILOT_MAX_USD}")
                return
            plant = load_plant_config(plant_id)
            scenario = at_plant_horizon(load_scenario(REPO / "scenarios" / f"{sid}.yaml"), plant)
            art = generate_run(scenario, tier, plant=plant, replicate=rep, runs_root=store / "runs")
            result = run_workflow(
                art.run_id,
                "p2",
                runs_root=store / "runs",
                scenario=scenario,
                config_path=config_path,
                live=True,
            )
            spent += float(result.llm_cost_usd or 0.0)
            out = store / "runs" / art.run_id / "workflows" / "p2"
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            line = {
                "cell": f"{sid} {plant_id}/{tier}",
                "replicate": rep,
                "truth": list(scenario.truth_label),
                "summary": result.as_dict(),
                "outcome": report.get("outcome"),
                "label": report.get("label"),
                "rule": report.get("rule"),
            }
            with results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, sort_keys=True) + "\n")
            print(f"{line['cell']} r{rep}: {line['outcome']} (USD {spent:.3f} so far)")


def outcome_of(line: dict[str, Any]) -> str:
    """The runner's completion first, then the report's outcome (the review's N-4)."""
    if not (line.get("summary") or {}).get("completed"):
        return "pending"
    return str(line.get("outcome") or "pending")


def report(store: Path) -> dict[str, Any]:
    """``reports/p2_pilot/``: outcomes keyed on the verdict, the go/no-go, the cost."""
    lines = [
        json.loads(x)
        for x in (store / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    rows = [
        {
            "cell": x["cell"],
            "replicate": x["replicate"],
            "truth": x["truth"],
            "outcome": outcome_of(x),
            "usd": (x["summary"] or {}).get("llm_cost_usd"),
            "requests": (x["summary"] or {}).get("llm_turns"),
        }
        for x in lines
    ]
    gate = [r["outcome"] for r in rows if r["cell"] == "S0-01 B/B"]
    scored = [o for o in gate if o not in ("abstain", "pending")]
    out = {
        "rows": rows,
        "go_no_go": {
            "S0-01 B/B": gate,
            "stop": len(scored) == len(REPLICATES) and all(o != "none" for o in scored),
            "rule": "stop only if both seeds of S0-01 B/B label something other than none; "
            "an abstaining or unfinished seed is excluded, never counted as none",
        },
        "usd_total": round(sum(float(r["usd"] or 0.0) for r in rows), 6),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "cells.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    md = ["# P2 live pilot", "", "| cell | seed | truth | outcome | USD |", "|---|---|---|---|---|"]
    md += [
        f"| {r['cell']} | {r['replicate']} | {','.join(r['truth'])} | {r['outcome']} | {r['usd']} |"
        for r in rows
    ]
    md += ["", f"Go/no-go: stop = {out['go_no_go']['stop']}; USD {out['usd_total']}."]
    (REPORT_DIR / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["plan", "run", "report"], nargs="?", default="plan")
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "plan":
        print(json.dumps(plan(), indent=1))
        return 0
    if args.store is None:
        parser.error("--store is required")
    if args.action == "run":
        run(args.store, live=args.live)
    else:
        report(args.store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
