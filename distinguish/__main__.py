"""Run the distinguishability analysis over a store's Level 0-5 cells.

    python -m distinguish --level0-only --part 0/1   # the Level-0 cells (run first)
    python -m distinguish --part 0/3                 # every third remaining pair
    python -m distinguish --table reports/p0_distinguishability.csv   # collect

Writes ``truth_store/<id>/admissible.json`` beside each run's answer key (a workflow can
never read it) and, with ``--table``, the per-cell table. The Level-0 cells run first:
their calibrated baselines give each plant and tier its overdispersion, which every other
cell of that plant and tier uses (method version 3). A plant with no Level-0 cell (Plant
A) falls back to each cell's own calibrated baseline, and the table flags it. A pair
whose every run already has an ``admissible.json`` of the current method version is
skipped.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from distinguish.analysis import LABELS, METHOD_VERSION, analyse_pair, overdispersion_of

REPO = Path(__file__).resolve().parents[1]


def _pairs(truth_store: Path, levels: range) -> list[tuple[tuple[str, str], list[dict]]]:
    rows = [
        json.loads(line)
        for line in (truth_store / "index.jsonl").read_text().splitlines()
        if line.strip()
    ]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if int(r["level"]) in levels and int(r["replicate"]) == 0:
            groups[(r["scenario_id"], r["plant"])].append(r)
    return sorted(groups.items())


def _doc(truth_store: Path, run_id: str) -> dict | None:
    path = truth_store / run_id / "admissible.json"
    if not path.is_file():
        return None
    doc = json.loads(path.read_text())
    return doc if doc.get("method_version") == METHOD_VERSION else None


def _level0_overdispersion(truth_store: Path) -> dict[str, dict[str, dict[str, float]]]:
    """Plant -> tier -> sensor -> dispersion, from the analysed Level-0 cells."""
    out: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for (_sid, plant), members in _pairs(truth_store, range(0, 1)):
        for r in members:
            doc = _doc(truth_store, r["run_id"])
            if doc is not None:
                out[plant][r["tier"]] = overdispersion_of(doc)
    return out


def collect(truth_store: Path, levels: range, dest: Path) -> None:
    """The per-cell table of every analysed run, with each class's convergence."""
    rows = []
    for (_sid, _plant), members in _pairs(truth_store, levels):
        for r in sorted(members, key=lambda m: m["tier"]):
            doc = _doc(truth_store, r["run_id"])
            if doc is None:
                continue
            row = {
                "run_id": doc["run_id"], "scenario_id": doc["scenario_id"],
                "level": doc.get("level"), "plant": doc["plant"], "tier": doc["tier"],
                "truth_label": "+".join(doc["truth_label"]),
                "admissible_set": "+".join(doc["admissible_set"]),
                "admissible_set_sensitivity": "+".join(
                    doc["admissible"][f"{doc['sensitivity_margin']:g}"]
                ),
                "n_admissible": doc["n_admissible"], "chance_rate": doc["chance_rate"],
                "none_admissible": doc["none_admissible"],
                "truth_admissible": doc["truth_admissible"],
                "truth_representable": doc["truth_representable"],
                "truth_class_limited": "; ".join(doc["truth_class_limited"]),
                "best_label": doc["best_label"], "n_samples": doc["n_samples"],
                "simulations": doc["simulations"], "wall_s": doc["wall_s"],
                "overdispersion_source": doc["overdispersion_source"],
            }  # fmt: skip
            for lab in LABELS:
                c = doc["classes"].get(lab, {})
                row[f"score_{lab}"] = c.get("score")
                row[f"converged_{lab}"] = c.get("converged")
            rows.append(row)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["run_id"])
        w.writeheader()
        w.writerows(rows)
    dest.with_suffix(".json").write_text(json.dumps(rows, indent=1) + "\n")
    print(f"{len(rows)} cells -> {dest}")


def main(argv: list[str] | None = None) -> int:
    """Command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs-root", type=Path, default=REPO / "runs")
    parser.add_argument("--part", default="0/1", help="i/k: every k-th pair from the i-th")
    parser.add_argument("--table", type=Path, default=None, help="collect into this CSV")
    parser.add_argument("--scenario", action="append", default=None)
    parser.add_argument("--level0-only", action="store_true", help="only the Level-0 cells")
    args = parser.parse_args(argv)
    truth_store = args.runs_root.parent / "truth_store"
    if args.table is not None:
        collect(truth_store, range(0, 6), args.table)
        return 0
    levels = range(0, 1) if args.level0_only else range(1, 6)
    phi = {} if args.level0_only else _level0_overdispersion(truth_store)
    level0_plants = {plant for (_sid, plant), _ in _pairs(truth_store, range(0, 1))}
    i, k = (int(x) for x in args.part.split("/"))
    for n, ((sid, plant), members) in enumerate(_pairs(truth_store, levels)):
        if n % k != i or (args.scenario and sid not in args.scenario):
            continue
        if all(_doc(truth_store, r["run_id"]) is not None for r in members):
            print(f"SKIP {sid} {plant}", flush=True)
            continue
        waiting = not all(r["tier"] in phi.get(plant, {}) for r in members)
        if not args.level0_only and plant in level0_plants and waiting:
            print(f"WAIT {sid} {plant}: run the Level-0 cells first", flush=True)
            continue
        runs = [
            (r["run_id"], args.runs_root / r["run_id"], truth_store / r["run_id"])
            for r in sorted(members, key=lambda m: m["tier"])
        ]
        docs = analyse_pair(
            runs,
            # a plant with no Level-0 cell (Plant A) falls back to each cell's own baseline
            overdispersion=phi.get(plant) if plant in level0_plants else None,
            log=lambda m: print(m, flush=True),
        )
        for run_id, doc in docs.items():
            (truth_store / run_id / "admissible.json").write_text(json.dumps(doc, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
