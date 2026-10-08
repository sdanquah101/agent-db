"""P2's offline power run (``docs/p2_design.md`` §11; deliverable 2): no model is called.

Each development cell is generated as the matrix generates it (its own scenario, its
library seed, the plant's horizon and budget) into a store **outside** the repository,
and P2 runs on it through the runner, in the sandbox, with ``decider: offline``: every
decision point takes its declared code fallback. What the code alone achieves is then
read from each run's record:

- the null table (NB, NM, NS, the failed channels, ``null_partial``);
- every code signature (the S1 table, the onset test and, for every cell where NB fails,
  every candidate onset day that would pass (the review's R1), the feed covariate, the
  early/late test and the biomass pair, the change point, the inhibition check, R3);
- the admitted labels and the final label, against the cell's truth;
- the four §4.5 predictions, checked on S0-01 B/C and S1-01 B/B (B/A and B/B are not in
  this run: their predictions need no signature).

``python -m scripts.p2_power run --store DIR [--part i/n]`` runs the cells (finished ones
are skipped); ``python -m scripts.p2_power report --store DIR`` writes
``reports/p2_power/cells.json`` and ``reports/p2_power/summary.md``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "reports" / "p2_power"

CELLS: tuple[tuple[str, str, str], ...] = (
    ("S2-01", "B", "B"),
    ("S3-01", "C", "B"),
    ("S4-01", "B", "B"),
    ("S5-01", "A", "A"),
    ("S6-02", "B", "B"),
    ("S8-01", "B", "B"),
    ("S0-01", "B", "C"),
    ("S1-01", "B", "B"),
)
"""The faulted development cells of the design's power table, and two clean cells whose
§4.5 predictions need a signature check (the re-review's N6)."""

PREDICTIONS = {
    "S0-01 B/C": {"null": "NM", "failed": ["digestate_ts", "digestate_vs"], "label": "none"},
    "S1-01 B/B": {"null": "NB", "failed": ["gas_flow"], "label": "none"},
}
"""The pre-registered §4.5 predictions this run can check."""


def key(cell: tuple[str, str, str]) -> str:
    """``S2-01 B/B``."""
    return f"{cell[0]} {cell[1]}/{cell[2]}"


EXCLUDED = ("abstain", "pending")
"""Outcomes that are never a label: reported in their own column, never counted as
``none`` (the review's F-A, ruling (c))."""


def outcome_of(record: dict[str, Any]) -> str:
    """The outcome a count keys on: the verdict and completion first, the label last.

    A record that carries the workflow's ``outcome`` is read as written. An older record
    (written before the field existed) is derived the same way: not completed, or the
    rule ``pending``, is ``pending``; an abstaining verdict is ``abstain``.
    """
    if record.get("outcome"):
        return str(record["outcome"])
    verdict = record.get("verdict") or {}
    if not record.get("completed") or record.get("rule") == "pending":
        return "pending"
    if verdict.get("verdict") == "abstain" or str(record.get("rule", "")).startswith("abstain"):
        return "abstain"
    return str(record["label"])


def run(store: Path, part: str = "0/1") -> None:
    """Generate and run every cell of this part that has no result yet."""
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from sim.run.matrix import at_plant_horizon
    from tools.runner import run_workflow

    i, n = (int(x) for x in part.split("/"))
    results = store / "results"
    results.mkdir(parents=True, exist_ok=True)
    for j, cell in enumerate(CELLS):
        if j % n != i:
            continue
        dest = results / f"{cell[0]}-{cell[1]}-{cell[2]}.json"
        if dest.is_file():
            continue
        sid, plant_id, tier = cell
        plant = load_plant_config(plant_id)
        scenario = at_plant_horizon(load_scenario(REPO / "scenarios" / f"{sid}.yaml"), plant)
        root = store / "runs"
        art = generate_run(scenario, tier, plant=plant, runs_root=root)
        print(f"START {key(cell)} ({art.run_id})", flush=True)
        started = time.perf_counter()
        result = run_workflow(art.run_id, "p2", runs_root=root, scenario=scenario)
        out = root / art.run_id / "workflows" / "p2"
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        state = json.loads((out / "state.json").read_text(encoding="utf-8"))
        record = {
            "cell": key(cell),
            "truth": list(scenario.truth_label),
            "run_id": art.run_id,
            "wall_s": round(time.perf_counter() - started, 1),
            "completed": bool(result.completed),
            "error": result.error,
            "evaluations_used": result.simulator_evals_used,
            "evaluations_total": result.simulator_evals_total,
            "label": report["label"],
            "outcome": report.get("outcome"),
            "rule": report["rule"],
            "verdict": report["verdict"],
            "null_table": report["null_table"],
            "signatures": report["signatures"],
            "by_role": report["by_role"],
            "abstentions": state["abstentions"],
            "codes": state["annotations"],
        }
        dest.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"DONE {key(cell)}: {record['label']} ({record['rule']}) in "
              f"{record['wall_s']:.0f} s", flush=True)  # fmt: skip


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The hit counts and the prediction checks."""
    rows = []
    for r in records:
        t = r["null_table"] or {}
        sig = r["signatures"] or {}
        out = outcome_of(r)
        rows.append({
            "cell": r["cell"],
            "truth": r["truth"],
            "label": r["label"],
            "outcome": out,
            "excluded": out in EXCLUDED,
            "hit": out not in EXCLUDED and out in r["truth"],
            "null": {k: t.get(k) for k in ("NB", "NM", "NS", "null_partial", "null_rejected")},
            "failed_channels": t.get("failed_channels"),
            "n_outside": t.get("n_outside"),
            "n_statistics": t.get("n_statistics"),
            "signatures": {
                "sensor_s1_holds": (sig.get("sensor") or {}).get("s1_holds"),
                "sensor_channel": (sig.get("sensor") or {}).get("channel"),
                "influent": sig.get("influent"),
                "onset": (sig.get("onset") or {}).get("code"),
                "candidate_onsets": sig.get("candidate_onsets"),
                "feed_covariate": sig.get("feed_covariate"),
                "early_late": sig.get("early_late"),
                "biomass_improves": sig.get("biomass_improves"),
                "change_point": (sig.get("change_point") or {}).get("common"),
                "inhibited": (sig.get("inhibition") or {}).get("inhibited"),
                "r3": sig.get("r3"),
                "structural": sig.get("structural"),
            },
            "admitted": (r["verdict"] or {}).get("admitted"),
            "rejected": (r["verdict"] or {}).get("rejected"),
            "holdout_failed": (r["verdict"] or {}).get("holdout_failed"),
            "completed": r["completed"],
            "evaluations": f"{r['evaluations_used']}/{r['evaluations_total']}",
            "wall_min": round(r["wall_s"] / 60.0, 1),
        })  # fmt: skip
    checks = {}
    for cell, pred in PREDICTIONS.items():
        row = next((x for x in rows if x["cell"] == cell), None)
        if row is None:
            continue
        checks[cell] = {
            "predicted": pred,
            "null_component": bool(row["null"].get(pred["null"])),
            "failed_channels": row["failed_channels"] == pred["failed"],
            "label": row["outcome"] == pred["label"],
        }
    faulted = [x for x in rows if x["truth"] != ["none"]]
    scored = [x for x in faulted if not x["excluded"]]
    return {
        "what": "P2 offline (no model): every decision point at its code fallback",
        "counting": "on the outcome (verdict and completion), never on the label alone",
        "cells": rows,
        "hits_faulted": f"{sum(x['hit'] for x in scored)} of {len(scored)} scored",
        "excluded_faulted": {k: sum(1 for x in faulted if x["outcome"] == k) for k in EXCLUDED},
        "null_rejected_faulted": f"{sum(bool(x['null'].get('null_rejected')) for x in faulted)}"
        f" of {len(faulted)}",
        "prediction_checks": checks,
    }


def report(store: Path) -> dict[str, Any]:
    """Write ``reports/p2_power/cells.json`` and ``summary.md`` from the store's results."""
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((store / "results").glob("*.json"))]  # fmt: skip
    out = summarise(records)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "cells.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    lines = [
        "# P2 offline power run (deliverable 2): no model call",
        "",
        "Every decision point at its declared code fallback (`decider: offline`).",
        "Every count keys on the outcome (the verdict and completion), never the label alone:",
        "an abstaining or unfinished run is excluded, never read as `none`.",
        f"Faulted cells hit: {out['hits_faulted']}; excluded: "
        f"{', '.join(f'{k} {v}' for k, v in out['excluded_faulted'].items())}; null rejected "
        f"on faulted cells: {out['null_rejected_faulted']}.",
        "",
        "| cell | truth | outcome | excluded | NB | NM | NS | partial | failed channels "
        "| admitted |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for x in out["cells"]:
        n = x["null"]
        lines.append(
            f"| {x['cell']} | {','.join(x['truth'])} | {x['outcome']} | "
            f"{x['excluded']} | {n.get('NB')} | "
            f"{n.get('NM')} | {n.get('NS')} | {n.get('null_partial')} | "
            f"{x['failed_channels']} | {x['admitted']} |"
        )
    (REPORT_DIR / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["run", "report"])
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--part", default="0/1")
    args = parser.parse_args(argv)
    store = args.store.resolve()
    if store == REPO or REPO in store.parents:
        raise SystemExit("the store must be outside the repository")
    if args.action == "run":
        run(store, args.part)
    else:
        report(store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
