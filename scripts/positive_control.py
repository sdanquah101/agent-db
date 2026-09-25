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
            kept = _kept_log(root, variant, new)
            if kept.is_file():
                obs_new["feed_log.csv"] = _sha(kept.read_bytes())
        same_obs = obs_base == obs_new
        same_truth = _truth_arrays(BASE_TRUTH / base) == _truth_arrays(truth / new)
        if not (same_obs and same_truth):
            raise RuntimeError(
                f"{cell}: the regenerated cell is not the baseline's ({same_obs=}, {same_truth=})"
            )
        if spec.get("exact_feed"):
            _write_exact_feed(runs / new, truth / new, _kept_log(root, variant, new))
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


def _kept_log(root: Path, variant: str, run_id: str) -> Path:
    """Where the generated feed log is kept: beside the store, never under ``runs/<id>/``."""
    return root / variant / "feed_logs" / f"{run_id}.generated.csv"


def _injected_kg(truth: Path, plant: str) -> dict[tuple[str, int], float]:
    """The scenario's injected unrecorded deliveries, (feed, day) -> kg wet.

    Recomputed as the generator adds them (``sim/influent/generator.py``: the feed's
    configured nonzero median delivery, in kg, times the fault's multiple), read-only.
    """
    from sim.influent.defaults import load_feed_fractionation, load_generator_config
    from sim.influent.generator import _amount_to_kg

    faults = json.loads((truth / "faults.json").read_text(encoding="utf-8"))
    gen = load_generator_config().plants[plant]
    catalogue = load_feed_fractionation()
    out: dict[tuple[str, int], float] = {}
    for extra in faults["influent"]["unrecorded"]:
        fid, day = str(extra["feed_id"]), int(extra["day"])
        amount = gen.feeds[fid].amount
        median = _amount_to_kg(amount.nonzero_median, amount.unit, catalogue.feeds[fid])
        out[(fid, day)] = out.get((fid, day), 0.0) + median * float(extra["multiple_of_median"])
    return out


def _write_exact_feed(run: Path, truth: Path, kept: Path) -> None:
    """R2 as amended (docs/positive_control.md §9): the feed log without its background noise.

    The log becomes the true delivered wet mass per day MINUS the scenario's injected
    unrecorded deliveries. The background mis-logs and background unrecorded deliveries
    are gone; the injected fault stays in the record exactly as the baseline has it.
    """
    log = run / "observations" / "feed_log.csv"
    if kept.is_file():
        return  # already rewritten
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(log.read_bytes())
    header = next(csv.reader(log.open(encoding="utf-8")))
    with np.load(truth / "influent.npz") as z:
        ids = [str(f) for f in z["feed_ids"]]
        delivered = np.array(z["delivered_kg_wet_per_d"], dtype=float)
    plant = json.loads((truth / "manifest.json").read_text(encoding="utf-8"))["plant"]
    for (fid, day), kg in _injected_kg(truth, plant).items():
        i = ids.index(fid)
        if not 0.0 <= kg <= delivered[i][day] * (1 + 1e-9):
            raise RuntimeError(
                f"{run.name}: injected {kg} kg of {fid} on day {day} exceeds the truth"
            )
        delivered[i][day] = max(delivered[i][day] - kg, 0.0)
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
            measures = _row_measures(variant, rec, base, row, runs, base_id)
            rows.append(
                {
                    **measures,
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


_WALL_CLOCK_MARKERS = ("at the measured rate", "refused for time")


def _wall_clock_steps(plan: dict[str, Any]) -> set[str]:
    """The steps a wall-clock guard refused: ``"<step>: bound N at the measured rate"``.

    Only these are time-dependent in the §5.2 sense (amendment §10). A fallback such as
    "N evaluations do not fit" can be the budget's doing, which is the lever R1 pulls, so
    it is not counted here.
    """
    entries = list(plan.get("guards_tripped") or []) + list(plan.get("fallbacks") or [])
    return {
        str(e).split(":", 1)[0].strip()
        for e in entries
        if any(marker in str(e) for marker in _WALL_CLOCK_MARKERS)
    }


def time_dependent_path(
    baseline_plan: dict[str, Any] | None, plan: dict[str, Any] | None, budget_x: float
) -> tuple[bool, str]:
    """§5.2 as amended in §10: (flag, reason).

    - a missing state is flagged (the conservative reading §9.2 promises);
    - a rung that changes the budget (R1) changes the wall-clock allowance by design, so
      its guard differences are the rung's effect, not timing noise, and are not flagged;
    - otherwise, the flag is set when the set of steps a wall-clock guard refused differs
      from the baseline run's.
    """
    if baseline_plan is None or plan is None:
        return True, "a state is missing: flagged"
    if float(budget_x) != 1.0:
        return False, "the rung changes the wall-clock allowance itself (R1)"
    a, b = _wall_clock_steps(baseline_plan), _wall_clock_steps(plan)
    if a == b:
        return False, ""
    return True, f"wall-clock guards differ: baseline {sorted(a)}, here {sorted(b)}"


def _row_measures(
    variant: str,
    rec: dict[str, Any],
    base: dict[str, Any],
    row: dict[str, Any],
    runs: Path,
    base_id: str,
) -> dict[str, Any]:
    """The pre-registered per-row measures (§5), computed before any verdict is read.

    ``moved_exact``: attribution_exact False at baseline, True here.
    ``time_dependent_path``: :func:`time_dependent_path` (§5.2 as amended in §10). For R3,
    the forced parameters' mechanical check and recovery against the last-segment truth,
    parsed from the evaluator's ``recovery_detail``: ``moved_recovery`` requires every
    forced parameter to be within 25 % of its truth OR inside a reported interval that
    covers it, the operational form of §5.1 (declared in §10).
    """
    out: dict[str, Any] = {
        "moved_exact": base.get("attribution_exact") == "False"
        and str(row.get("attribution_exact")) == "True",
    }
    mine = runs / row["run_id"] / "workflows" / "p0" / "state.json"
    theirs = BASE_RUNS / base_id / "workflows" / "p0" / "state.json"
    flag, reason = time_dependent_path(
        json.loads(theirs.read_text())["plan"] if theirs.is_file() else None,
        json.loads(mine.read_text())["plan"] if mine.is_file() else None,
        rec["budget_x"],
    )
    out["time_dependent_path"] = flag
    out["time_dependent_reason"] = reason
    if VARIANTS[variant].get("force"):
        forced = FORCED[rec["cell"][0]]
        state = json.loads(mine.read_text()) if mine.is_file() else {}
        approved = set((state.get("screening") or {}).get("approved", []))
        fitted = set((state.get("final") or {}).get("parameters") or {})
        detail = {}
        for item in str(row.get("recovery_detail") or "").split():
            name, _, rest = item.partition(":")
            parts = rest.split("/")
            if len(parts) == 3:
                detail[name] = (float(parts[0]), float(parts[1]), parts[2] == "in")
        within = [
            n in detail and abs(detail[n][0] - detail[n][1]) <= 0.25 * abs(detail[n][1])
            for n in forced
        ]
        covers = [n in detail and detail[n][2] for n in forced]
        out.update(
            forced="+".join(forced),
            forced_in_approved=all(n in approved for n in forced),
            forced_fitted=all(n in fitted for n in forced),
            forced_within_25pct=all(within),
            forced_interval_covers=all(covers),
            moved_recovery=all(w or c for w, c in zip(within, covers, strict=True)),
        )
    return out


def verdict(
    rows: list[dict[str, Any]] | None = None, dest: Path | bool | None = None
) -> dict[str, Any]:
    """The per-rung verdicts of §5, computed from the ladder table and nothing else.

    A move on a row whose ``time_dependent_path`` is True, or missing, is reported but not
    counted (§5.2 as amended in §9 and §10). A rung with cells still to run reads
    "incomplete".
    """
    if rows is None:
        rows = json.loads((REPO / "reports" / "p0_positive_control.json").read_text())

    def cells(variant: str, keys: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
        by_cell = {
            (r["scenario_id"], r["plant"], r["tier"]): r for r in rows if r["variant"] == variant
        }
        return [by_cell[k] for k in keys if k in by_cell]

    def moves(rs: list[dict[str, Any]], key: str = "moved_exact") -> tuple[int, int]:
        # a missing flag (None) counts as flagged: the conservative reading of §9.2
        counted = sum(1 for r in rs if r.get(key) and r.get("time_dependent_path") is False)
        timing = sum(1 for r in rs if r.get(key) and r.get("time_dependent_path") is not False)
        return counted, timing

    out: dict[str, Any] = {"method": "docs/positive_control.md §5 and §9", "rungs": {}}
    r1p, r1s = cells("r1x3", PARAMETER_CELLS), cells("r1x3", SENSOR_STATE_CELLS)
    if r1p or r1s:
        (mp, tp), (ms, ts) = moves(r1p), moves(r1s)
        complete = len(r1p) == len(PARAMETER_CELLS) and len(r1s) == len(SENSOR_STATE_CELLS)
        v = "pass" if mp >= 3 or ms >= 2 else "fail" if mp <= 1 and ms <= 1 else "inconclusive"
        out["rungs"]["R1x3"] = {
            "parameter_moves": mp, "sensor_state_moves": ms, "timing_moves_not_counted": tp + ts,
            "cells_run": [len(r1p), len(r1s)],
            "verdict": v if complete else f"incomplete ({v} so far)",
        }  # fmt: skip
    r10 = cells("r1x10", VARIANTS["r1x10"]["cells"])
    if r10:
        m, t = moves(r10)
        out["rungs"]["R1x10"] = {
            "moves": m, "timing_moves_not_counted": t, "cells_run": len(r10),
            "complete": len(r10) == len(VARIANTS["r1x10"]["cells"]),
        }  # fmt: skip
    r2, r2c = cells("r2", R2_CELLS), cells("r2", R2_CONTROLS)
    if r2 or r2c:
        (m, t), (mc, tc) = moves(r2), moves(r2c)
        # "fail" first: §5.1's "confounded" is control moves "as well" as S3-02 moves
        v = (
            "fail" if m == 0 else "confounded" if mc >= 2 else "pass" if m >= 2
            else "inconclusive"
        )  # fmt: skip
        complete = len(r2) == len(R2_CELLS) and len(r2c) == len(R2_CONTROLS)
        out["rungs"]["R2"] = {
            "s3_02_moves": m, "control_moves": mc, "timing_moves_not_counted": t + tc,
            "cells_run": [len(r2), len(r2c)],
            "verdict": v if complete else f"incomplete ({v} so far)",
        }  # fmt: skip
    r3 = cells("r3", PARAMETER_CELLS)
    if r3:
        mechanical = sum(1 for r in r3 if r.get("forced_in_approved") and r.get("forced_fitted"))
        exact, t_exact = moves(r3)
        recov, t_recov = moves(r3, "moved_recovery")
        either = sum(
            1 for r in r3
            if (r.get("moved_exact") or r.get("moved_recovery"))
            and r.get("time_dependent_path") is False
        )  # fmt: skip
        if len(r3) < len(PARAMETER_CELLS):
            v = f"incomplete ({len(r3)} of {len(PARAMETER_CELLS)} cells run)"
        elif mechanical < len(PARAMETER_CELLS):
            v = f"not run: forced parameters fitted on {mechanical} of {len(PARAMETER_CELLS)}"
        else:
            v = "pass" if either >= 3 else "fail" if either <= 1 else "inconclusive"
        out["rungs"]["R3"] = {
            "mechanical_check": f"{mechanical} of {len(r3)}", "moves": either,
            "moves_exact": exact, "moves_recovery": recov,
            "timing_moves_not_counted": max(t_exact, t_recov), "cells_run": len(r3), "verdict": v,
        }  # fmt: skip
    if dest is not False:
        path = dest or REPO / "reports" / "p0_positive_control_summary.json"
        path.write_text(json.dumps(out, indent=1) + "\n")
        print(json.dumps(out, indent=1))
    return out


def publish(root: Path) -> None:
    """Copy each variant's log (variants.jsonl) and the R3 configs next to the reports."""
    dest = REPO / "reports" / "positive_control"
    dest.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        src = root / variant / "variants.jsonl"
        if src.is_file():
            (dest / f"{variant}_variants.jsonl").write_bytes(src.read_bytes())
        for cfg in sorted((root / variant).glob("p0_S*.yaml")):
            (dest / f"{variant}_{cfg.name}").write_bytes(cfg.read_bytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "action", choices=["generate", "run", "score", "compare-hookoff", "verdict", "publish"]
    )
    parser.add_argument("--variant", default=None, choices=sorted(VARIANTS))
    parser.add_argument("--store", type=Path, required=True, help="root of the diagnostic stores")
    parser.add_argument("--part", default="0/1", help="i/k: run every k-th cell from the i-th")
    args = parser.parse_args(argv)
    if args.action == "verdict":
        verdict()
    elif args.action == "publish":
        publish(args.store)
    elif args.action == "score":
        score(args.store, [args.variant] if args.variant else list(VARIANTS))
        publish(args.store)
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
