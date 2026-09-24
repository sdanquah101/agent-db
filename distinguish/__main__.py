"""Run the distinguishability analysis over a store's Level 0-5 cells.

    python -m distinguish --part 0/3            # every third (scenario, plant) pair
    python -m distinguish --table reports/p0_distinguishability.csv   # collect

Writes ``truth_store/<id>/admissible.json`` beside each run's answer key (a workflow can
never read it) and, with ``--table``, the per-cell table. A pair whose every run already
has an ``admissible.json`` of the current method version is skipped.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from distinguish.analysis import LABELS, METHOD_VERSION, analyse_pair

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


def _done(truth_store: Path, run_id: str) -> bool:
    path = truth_store / run_id / "admissible.json"
    if not path.is_file():
        return False
    return json.loads(path.read_text()).get("method_version") == METHOD_VERSION


def collect(truth_store: Path, levels: range, dest: Path) -> None:
    """The per-cell table of every analysed run."""
    rows = []
    for (_sid, _plant), members in _pairs(truth_store, levels):
        for r in sorted(members, key=lambda m: m["tier"]):
            path = truth_store / r["run_id"] / "admissible.json"
            if not path.is_file():
                continue
            doc = json.loads(path.read_text())
            row = {
                "run_id": doc["run_id"], "scenario_id": doc["scenario_id"], "plant": doc["plant"],
                "tier": doc["tier"], "truth_label": "+".join(doc["truth_label"]),
                "admissible_set": "+".join(doc["admissible_set"]),
                "admissible_set_margin10": "+".join(doc["admissible"]["10"]),
                "n_admissible": len(doc["admissible_set"]),
                "truth_admissible": doc["truth_admissible"],
                "truth_class_limited": "; ".join(doc["truth_class_limited"]),
                "best_label": doc["best_label"], "n_samples": doc["n_samples"],
                "simulations": doc["simulations"],
            }  # fmt: skip
            for lab in LABELS:
                c = doc["classes"].get(lab, {})
                row[f"aic_{lab}"] = c.get("aic")
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
    args = parser.parse_args(argv)
    truth_store = args.runs_root.parent / "truth_store"
    levels = range(0, 6)
    if args.table is not None:
        collect(truth_store, levels, args.table)
        return 0
    i, k = (int(x) for x in args.part.split("/"))
    pairs = _pairs(truth_store, levels)
    for n, ((sid, plant), members) in enumerate(pairs):
        if n % k != i or (args.scenario and sid not in args.scenario):
            continue
        if all(_done(truth_store, r["run_id"]) for r in members):
            print(f"SKIP {sid} {plant}", flush=True)
            continue
        runs = [
            (r["run_id"], args.runs_root / r["run_id"], truth_store / r["run_id"])
            for r in sorted(members, key=lambda m: m["tier"])
        ]
        docs = analyse_pair(runs, log=lambda m: print(m, flush=True))
        for run_id, doc in docs.items():
            (truth_store / run_id / "admissible.json").write_text(json.dumps(doc, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
