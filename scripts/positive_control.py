"""The positive-control ladder's driver (docs/positive_control.md). Experimenter side.

This script is the *experimenter*, not a workflow. It reads the truth store to build
the declared variants of rungs R2 (the true feed) and R3 (the shifted parameters), and
it never runs inside a sandbox. P0 sees a variant only through the channels every run
uses:
- a run store's observations (R2);
- the configuration file handed to the jail (R3);
- the budget the registry enforces (R1).

Every variant's content and sha256 go into the ladder's table. Every ladder cell is
regenerated into a diagnostic store of its own, one per variant, so no baseline output
is ever overwritten. The driver checks that the regenerated cell's observations
(before any R2 rewrite) and truth arrays are byte-identical to the baseline cell's.

Run it from the repository root as a module, so the checkout's code is the code run:

    python -m scripts.positive_control generate --variant r3 --store <dir>
    python -m scripts.positive_control run --variant r3 --store <dir> --part 0/3
    python -m scripts.positive_control score --store <dir>

Ladder rows are diagnostics: never P0 entries and never rows of a baseline table.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
BASE_RUNS = REPO / "runs"
BASE_TRUTH = REPO / "truth_store"
FROZEN_P0 = REPO / "configs" / "workflows" / "p0.yaml"

PARAMETER_CELLS = [
    ("S5-01", "A", "A"), ("S5-01", "A", "B"), ("S5-01", "A", "C"),
    ("S5-02", "B", "A"), ("S5-02", "B", "B"), ("S5-02", "B", "C"),
    ("S5-02", "C", "A"), ("S5-02", "C", "B"), ("S5-02", "C", "C"),
    ("S5-02", "A", "A"),
]  # fmt: skip
SENSOR_STATE_CELLS = [
    ("S2-01", "B", "B"),
    ("S2-03", "C", "B"),
    ("S4-01", "B", "B"),
    ("S4-02", "C", "B"),
]
PILOT_CELLS = [
    ("S0-01", "B", "A"), ("S0-01", "B", "B"), ("S0-01", "B", "C"), ("S1-01", "B", "B"),
    ("S2-01", "B", "B"), ("S3-01", "C", "B"), ("S4-01", "B", "B"), ("S5-01", "A", "A"),
]  # fmt: skip
R2_CELLS = [("S3-02", p, t) for p in ("B", "C") for t in ("C", "B")]
R2_CONTROLS = [(s, p, "C") for s in ("S3-01", "S3-03") for p in ("B", "C")]

# the pre-registered variants (docs/positive_control.md §3, §5.3)
VARIANTS: dict[str, dict[str, Any]] = {
    "hookoff": {"rung": "hook_off_check", "cells": PILOT_CELLS, "budget_x": 1},
    "r3": {"rung": "R3", "cells": PARAMETER_CELLS, "budget_x": 1, "force": True},
    "r1x3": {"rung": "R1", "cells": PARAMETER_CELLS + SENSOR_STATE_CELLS, "budget_x": 3},
    "r2": {"rung": "R2", "cells": R2_CELLS + R2_CONTROLS, "budget_x": 1, "exact_feed": True},
    "r1x10": {"rung": "R1", "cells": [("S5-02", "B", "B"), ("S5-01", "A", "B")], "budget_x": 10},
}

# R3: the shifted parameters, from the fault declarations the scenarios carry
# (sim/faults/schema.py: ammonia_inhibition_shift, hydrolysis_regime_change)
FORCED = {"S5-01": ["K_I_nh3"], "S5-02": ["k_hyd_ch", "k_hyd_pr", "k_hyd_li"]}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _index(truth_store: Path) -> list[dict[str, Any]]:
    path = truth_store / "index.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _find(truth_store: Path, cell: tuple[str, str, str]) -> dict[str, Any]:
    sid, plant, tier = cell
    rows = [
        r
        for r in _index(truth_store)
        if (r["scenario_id"], r["plant"], r["tier"]) == (sid, plant, tier) and r["replicate"] == 0
    ]
    if len(rows) != 1:
        raise LookupError(f"{cell}: {len(rows)} index rows in {truth_store}")
    return rows[0]


def _store(root: Path, variant: str) -> tuple[Path, Path]:
    runs = root / variant / "runs"
    return runs, runs.parent / "truth_store"


def _tree(path: Path) -> dict[str, str]:
    return {
        str(p.relative_to(path)): _sha(p.read_bytes())
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def _truth_arrays(truth: Path) -> dict[str, str]:
    """Content hashes of the truth arrays (npz members, not the zip container's bytes)."""
    out = {"parameters.json": _sha((truth / "parameters.json").read_bytes())}
    for name in ("influent.npz", "states.npz"):
        with np.load(truth / name) as z:
            for key in sorted(z.files):
                out[f"{name}:{key}"] = _sha(np.ascontiguousarray(z[key]).tobytes())
    return out


def generate(variant: str, root: Path) -> None:
    """Regenerate the variant's cells into its own store and check they are the baseline's."""
    from sim.run.matrix import Cell, generate_matrix

    spec = VARIANTS[variant]
    runs, truth = _store(root, variant)
    runs.mkdir(parents=True, exist_ok=True)
    cells = []
    for cell in spec["cells"]:
        base = _find(BASE_TRUTH, cell)
        cells.append(Cell(cell[0], cell[1], cell[2], int(base["seed"]), 0))
    todo = [c for c in cells if not _has(truth, c)]
    for result in generate_matrix(todo, runs_root=runs):
        print(result, flush=True)
        if not result.ok:
            raise RuntimeError(f"{result.cell} did not generate: {result.detail}")
    checks = []
    for cell in spec["cells"]:
        base = _find(BASE_TRUTH, cell)["run_id"]
        new = _find(truth, cell)["run_id"]
        obs_base, obs_new = (
            _tree(BASE_RUNS / base / "observations"),
            _tree(runs / new / "observations"),
        )
        if spec.get("exact_feed"):
            # compare before the rewrite: the first generation's feed log is kept aside
            kept = runs / new / "feed_log.generated.csv"
            if kept.is_file():
                obs_new["feed_log.csv"] = _sha(kept.read_bytes())
        same_obs = obs_base == obs_new
        same_truth = _truth_arrays(BASE_TRUTH / base) == _truth_arrays(truth / new)
        if not (same_obs and same_truth):
            raise RuntimeError(
                f"{cell}: the regenerated cell is not the baseline's ({same_obs=}, {same_truth=})"
            )
        if spec.get("exact_feed"):
            _write_exact_feed(runs / new, truth / new)
        checks.append(
            {
                "cell": list(cell),
                "baseline_run_id": base,
                "run_id": new,
                "observations_identical": True,
                "truth_identical": True,
            }
        )
    (root / variant / "identity.json").write_text(json.dumps(checks, indent=1) + "\n")
    print(f"{variant}: {len(checks)} cells regenerated and identical to the baseline", flush=True)


def _has(truth: Path, cell: Any) -> bool:
    try:
        _find(truth, (cell.scenario_id, cell.plant, cell.tier))
    except LookupError:
        return False
    return True


def _write_exact_feed(run: Path, truth: Path) -> None:
    """R2: the feed log becomes the true delivered wet mass per day (kg wet/d)."""
    log = run / "observations" / "feed_log.csv"
    kept = run / "feed_log.generated.csv"
    if kept.is_file():
        return  # already rewritten
    kept.write_bytes(log.read_bytes())
    header = next(csv.reader(log.open(encoding="utf-8")))
    with np.load(truth / "influent.npz") as z:
        ids = [str(f) for f in z["feed_ids"]]
        delivered = np.asarray(z["delivered_kg_wet_per_d"])
    columns = [h.removesuffix("_kg_wet_per_d") for h in header[1:]]
    assert sorted(columns) == sorted(ids), (columns, ids)
    rows = sum(1 for _ in log.open(encoding="utf-8")) - 1
    with log.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for day in range(rows):
            writer.writerow([day, *[f"{float(delivered[ids.index(c)][day]):.6g}" for c in columns]])


def _config_for(variant: str, scenario_id: str, root: Path) -> tuple[Path | None, str, str]:
    """The configuration file of a (variant, scenario), its content and its sha256."""
    if not VARIANTS[variant].get("force"):
        return None, "frozen configs/workflows/p0.yaml", _sha(FROZEN_P0.read_bytes())
    raw = yaml.safe_load(FROZEN_P0.read_text(encoding="utf-8"))
    raw["screening"]["force_include"] = FORCED[scenario_id]
    text = yaml.safe_dump(raw, sort_keys=False)
    path = root / variant / f"p0_{scenario_id}.yaml"
    path.write_text(text, encoding="utf-8")
    return path, f"screening.force_include={FORCED[scenario_id]}", _sha(text.encode())


def run(variant: str, root: Path, part: str) -> None:
    """Run the variant's cells (every k-th of a part) through the unchanged runner."""
    from scenarios.schema import load_scenario
    from sim.run.layout import RunPaths
    from tools.runner import run_workflow, table_row, write_table

    spec = VARIANTS[variant]
    runs, truth = _store(root, variant)
    i, k = (int(x) for x in part.split("/"))
    for n, cell in enumerate(spec["cells"]):
        if n % k != i:
            continue
        row = _find(truth, cell)
        rid = row["run_id"]
        if (runs / rid / "workflows" / "p0" / "summary.json").is_file():
            print(f"SKIP {variant} {cell} {rid}", flush=True)
            continue
        # as the baseline's runner loaded it (tools.runner.select_cells): the YAML as is
        scenario = load_scenario(REPO / "scenarios" / f"{cell[0]}.yaml")
        x = int(spec["budget_x"])
        if x != 1:
            budget = scenario.budget.model_copy(
                update={
                    "simulator_evals": scenario.budget.simulator_evals * x,
                    "wall_clock_min": scenario.budget.wall_clock_min * x,
                }
            )
            scenario = scenario.model_copy(update={"budget": budget})
        config, content, sha = _config_for(variant, cell[0], root)
        record = {
            "variant": variant, "rung": spec["rung"], "run_id": rid, "cell": list(cell),
            "budget_x": x, "simulator_evals": scenario.budget.simulator_evals,
            "wall_clock_min": scenario.budget.wall_clock_min, "config": content,
            "config_sha256": sha,
            "exact_feed": bool(spec.get("exact_feed")),
        }  # fmt: skip
        with (root / variant / "variants.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"START {variant} {cell} {rid} x{x} {content}", flush=True)
        result = run_workflow(rid, "p0", runs_root=runs, scenario=scenario, config_path=config)
        cell_row = {**row, "scenario": scenario}
        write_table(
            [table_row(cell_row, RunPaths.for_run(rid, runs), result)],
            root / variant / f"runner_{i}.csv",
        )
        print(
            f"END {variant} {cell} {rid} completed={result.completed} error={result.error!r}",
            flush=True,
        )


def _normalise(state: dict[str, Any]) -> dict[str, Any]:
    """The same-cell-twice normalisation: no wall clock, no log positions, no call lists."""
    state = json.loads(json.dumps(state))
    state["budget"].pop("wall_clock_min", None)
    state["plan"].pop("guards_tripped", None)
    for action in state["actions"]:
        action.pop("seq", None)
        action.pop("call_index", None)
    state["budget"].pop("n_calls", None)
    for item in state["classification"]["evidence"]:
        item.pop("calls", None)
    if state.get("validation"):
        state["validation"].pop("calls", None)
    return state


def compare_hookoff(root: Path) -> dict[str, Any]:
    """§5.3 (b): each pilot cell's hook-off outputs against the baseline's, bytes first."""
    runs, truth = _store(root, "hookoff")
    rows = []
    for cell in PILOT_CELLS:
        base = _find(BASE_TRUTH, cell)["run_id"]
        new = _find(truth, cell)["run_id"]
        a, b = BASE_RUNS / base / "workflows" / "p0", runs / new / "workflows" / "p0"
        row: dict[str, Any] = {"cell": list(cell), "baseline_run_id": base, "run_id": new}
        for name in ("state.json", "summary.json", "report.md"):
            pa, pb = a / name, b / name
            row[f"{name}_bytes_equal"] = (
                pa.is_file() and pb.is_file() and pa.read_bytes() == pb.read_bytes()
            )
        sa = json.loads((a / "state.json").read_text())
        sb = json.loads((b / "state.json").read_text())
        na, nb = _normalise(sa), _normalise(sb)
        # the run id is store-specific: compare with it masked
        text_a = json.dumps(na, sort_keys=True).replace(base, "<run>")
        text_b = json.dumps(nb, sort_keys=True).replace(new, "<run>")
        row["normalised_state_equal"] = text_a == text_b
        if text_a != text_b:
            da, db = json.loads(text_a), json.loads(text_b)
            row["differing_keys"] = sorted(k for k in set(da) | set(db) if da.get(k) != db.get(k))
            row["plan_a"] = {
                k: sa["plan"].get(k) for k in ("guards_tripped", "fallbacks", "steps_skipped")
            }
            row["plan_b"] = {
                k: sb["plan"].get(k) for k in ("guards_tripped", "fallbacks", "steps_skipped")
            }
        rows.append(row)
    out = {"cells": rows, "all_normalised_equal": all(r["normalised_state_equal"] for r in rows)}
    (root / "hookoff" / "comparison.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return out


def score(root: Path, variants: list[str]) -> None:
    """Score every finished ladder run with the unchanged evaluator; write the ladder tables."""
    baseline = {
        r["run_id"]: r for r in csv.DictReader((REPO / "reports" / "p0_sweep_scored.csv").open())
    }
    rows: list[dict[str, Any]] = []
    for variant in variants:
        runs, truth = _store(root, variant)
        records = {}
        path = root / variant / "variants.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            records[rec["run_id"]] = rec  # the last launch of a run id is the one on disk
        done = [r for r in records if (runs / r / "workflows" / "p0" / "summary.json").is_file()]
        if not done:
            continue
        out = root / variant / "scored.csv"
        cmd = [sys.executable, "-m", "eval", "--workflow", "p0", "--runs-root", str(runs)]
        cmd += ["--truth-store", str(truth), "--out", str(out)]
        for r in done:
            cmd += ["--run", r]
        subprocess.run(cmd, cwd=REPO, check=True, stdout=subprocess.DEVNULL)
        for row in csv.DictReader(out.open()):
            rec = records[row["run_id"]]
            base_id = _find(BASE_TRUTH, tuple(rec["cell"]))["run_id"]
            base = baseline.get(base_id, {})
            rows.append(
                {
                    "rung": rec["rung"], "variant": variant, "diagnostic": True,
                    "variant_detail": rec["config"], "variant_sha256": rec["config_sha256"],
                    "budget_x": rec["budget_x"], "exact_feed": rec["exact_feed"],
                    "baseline_run_id": base_id,
                    "baseline_attribution_exact": base.get("attribution_exact"),
                    "baseline_final_label_set": base.get("final_label_set"),
                    **row,
                }
            )  # fmt: skip
    if not rows:
        print("nothing scored yet")
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    dest = REPO / "reports" / "p0_positive_control.csv"
    with dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    dest.with_suffix(".json").write_text(json.dumps(rows, indent=1) + "\n")
    print(f"{len(rows)} ladder rows -> {dest.relative_to(REPO)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["generate", "run", "score", "compare-hookoff"])
    parser.add_argument("--variant", default=None, choices=sorted(VARIANTS))
    parser.add_argument("--store", type=Path, required=True, help="root of the diagnostic stores")
    parser.add_argument("--part", default="0/1", help="i/k: run every k-th cell from the i-th")
    args = parser.parse_args(argv)
    if args.action == "score":
        score(args.store, [args.variant] if args.variant else list(VARIANTS))
    elif args.action == "compare-hookoff":
        compare_hookoff(args.store)
    elif args.variant is None:
        parser.error(f"{args.action} needs --variant")
    elif args.action == "generate":
        generate(args.variant, args.store)
    else:
        run(args.variant, args.store, args.part)
    return 0


if __name__ == "__main__":
    sys.exit(main())
