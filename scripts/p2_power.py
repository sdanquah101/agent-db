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

**The H4 development cells (Q6; ``docs/p2_agents_design.md`` §7):** S7-01 at B/A, B/B and
B/C and S7-02 at A/C, two seeds each (replicates 0 and 1), each run offline by both arms:
the procedural P2 (``p2.yaml``, the code-only floor any agent result is read against) and
the agent arm (``p2_agents.yaml`` as committed, its frozen record checked before every
run, its roles at their scripted offline plans). ``h4-run`` and ``h4-report`` write
``reports/p2_power/h4_cells.json`` and ``h4_summary.md``; ``cells.json`` and
``summary.md`` are left as they are. No model is reachable in either arm.
"""

from __future__ import annotations

import argparse
import hashlib
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

    The runner's ``completed`` is read **first** (the review's N-4): a run the runner did
    not see complete is ``pending`` whatever its report says. Then the workflow's own
    ``outcome``, if the record carries it; an older record (written before the field
    existed) is derived the same way: the rule ``pending`` is ``pending``, an abstaining
    verdict is ``abstain``.
    """
    if not record.get("completed") or record.get("rule") == "pending":
        return "pending"
    if record.get("outcome"):
        return str(record["outcome"])
    verdict = record.get("verdict") or {}
    if verdict.get("verdict") == "abstain" or str(record.get("rule", "")).startswith("abstain"):
        return "abstain"
    return str(record["label"])


H4_CELLS: tuple[tuple[str, str, str], ...] = (
    ("S7-01", "B", "A"),
    ("S7-01", "B", "B"),
    ("S7-01", "B", "C"),
    ("S7-02", "A", "C"),
)
"""The Q6 cells: S7-01 at B/A, B/B, B/C and S7-02 at A/C, its defined tier (decided
2026-10-25, the lead's "Yes to both"; ``docs/p2_agents_design.md`` §7 and Q6)."""

H4_REPLICATES: tuple[int, ...] = (0, 1)
"""Two seeds per cell: the cell's own seed (replicate 0) and its first replicate, as the
pilot's (``scripts/p2_pilot.py``)."""

H4_ARMS: dict[str, Path | None] = {
    "procedural": None,  # the runner's own p2.yaml
    "agents": REPO / "configs" / "workflows" / "p2_agents.yaml",
}
"""Each arm's configuration: ``None`` is the committed ``p2.yaml``."""

H4_DROPPED = ("runtime_s", "t_utc")
"""The fields of a ``calls.jsonl`` line that are the clock's, not the run's: left out of
the record's digest so two runs of one seed compare equal."""


def h4_jobs() -> list[tuple[tuple[str, str, str], int, str]]:
    """Every (cell, replicate, arm) of the H4 run, in a fixed order."""
    return [(c, r, a) for c in H4_CELLS for r in H4_REPLICATES for a in H4_ARMS]


def h4_name(cell: tuple[str, str, str], replicate: int, arm: str) -> str:
    """``S7-01-B-B-r0-agents.json``."""
    return f"{cell[0]}-{cell[1]}-{cell[2]}-r{replicate}-{arm}.json"


def calls_digest(path: Path) -> tuple[str, int]:
    """The digest of a run's ``calls.jsonl`` without its clock fields, and its line count."""
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            line = json.loads(raw)
            for k in H4_DROPPED:
                line.pop(k, None)
            lines.append(json.dumps(line, sort_keys=True))
    return hashlib.sha256("\n".join(lines).encode()).hexdigest(), len(lines)


def observations_digest(run_dir: Path) -> str:
    """The digest of every file under a run's ``observations/``, by relative path."""
    h = hashlib.sha256()
    base = run_dir / "observations"
    for f in sorted(p for p in base.rglob("*") if p.is_file()):
        h.update(f.relative_to(base).as_posix().encode() + b"\0")
        h.update(hashlib.sha256(f.read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def run(store: Path, part: str = "0/1") -> None:
    """Generate and run every cell of this part that has no result yet."""
    from scenarios.schema import load_scenario
    from scripts.p2_rerun import InFlight, run_counted, set_aside, write_synced
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from sim.run.matrix import at_plant_horizon
    from tools.runner import run_workflow

    i, n = (int(x) for x in part.split("/"))
    results = store / "results"
    results.mkdir(parents=True, exist_ok=True)
    # unfinished runs are never results (the lead's rulings of 2026-10-19): kept apart,
    # reported, never pooled or scored
    unfinished = store / "unfinished"
    unfinished.mkdir(parents=True, exist_ok=True)
    # a stopped driver's attempt counts as an unfinished one (the review of b837c64, S-2),
    # found in every part's journal, so a resume under another part count still counts it
    # (the review of 0b9f210, SF-2); a part consults only its own cells
    journal = InFlight(store / f"in_flight.{i}.jsonl", sorted(store.glob("in_flight.*.jsonl")))
    orphans = journal.orphans(settled(store))
    if InFlight.TORN in orphans:
        print("STOP: an in-flight journal line is torn and names no cell; one attempt's "
              "cell is unknown, so no cell is run. Report it to the coordinator.",
              flush=True)  # fmt: skip
        return
    for j, cell in enumerate(CELLS):
        if j % n != i:
            continue
        name = f"{cell[0]}-{cell[1]}-{cell[2]}.json"
        dest = results / name
        if dest.is_file() or (unfinished / name).is_file():
            continue
        sid, plant_id, tier = cell
        plant = load_plant_config(plant_id)
        scenario = at_plant_horizon(load_scenario(REPO / "scenarios" / f"{sid}.yaml"), plant)
        root = store / "runs"
        prior = orphans.get((key(cell), 0), [])
        run_ids: list[str] = [str(p["run_id"]) for p in prior]

        def attempt(
            k: int,
            cell: Any = cell,
            scenario: Any = scenario,
            plant: Any = plant,
            tier: str = tier,
            root: Path = root,
            run_ids: list[str] = run_ids,
        ) -> dict:
            if k > 1:  # the same cell and seed, regenerated; the failed attempt kept aside
                set_aside(root / run_ids[-1], k - 1)
            art = generate_run(scenario, tier, plant=plant, runs_root=root)
            run_ids.append(art.run_id)
            journal.start(key(cell), 0, k, art.run_id)
            print(f"START {key(cell)} ({art.run_id}, attempt {k})", flush=True)
            started = time.perf_counter()
            result = run_workflow(art.run_id, "p2", runs_root=root, scenario=scenario)
            journal.finish(key(cell), 0, k, art.run_id, {
                "completed": result.completed, "error": result.error,
                "failure_reason": getattr(result, "failure_reason", "")
                or ("" if result.completed else "run_failed")})  # fmt: skip
            out = root / art.run_id / "workflows" / "p2"
            report = _json_or_empty(out / "report.json")
            state = _json_or_empty(out / "state.json")
            return {
                "cell": key(cell),
                "truth": list(scenario.truth_label),
                "run_id": art.run_id,
                "attempt": k,
                "wall_s": round(time.perf_counter() - started, 1),
                "completed": bool(result.completed),
                "error": result.error,
                "failure_reason": getattr(result, "failure_reason", "")
                or ("" if result.completed else "run_failed"),
                "evaluations_used": result.simulator_evals_used,
                "evaluations_total": result.simulator_evals_total,
                "label": report.get("label"),
                "outcome": report.get("outcome", "pending"),
                "rule": report.get("rule"),
                "verdict": report.get("verdict"),
                "null_table": report.get("null_table"),
                "signatures": report.get("signatures"),
                "by_role": report.get("by_role"),
                "abstentions": state.get("abstentions"),
                "codes": state.get("annotations"),
            }

        done_cell = run_counted(attempt, live=False, prior=prior)
        if done_cell.record is None:
            if run_ids:  # nothing unfinished stays at workflows/p2 (N-7)
                set_aside(root / run_ids[-1], len(done_cell.attempts))
            failure = {"cell": key(cell), **done_cell.failure()}
            write_synced(unfinished / name, json.dumps(failure, indent=1, sort_keys=True) + "\n")
            print(f"STOP: {key(cell)} is unfinished after one rerun; nothing is scored "
                  f"for it. Report it to the coordinator: {failure['attempts']}",
                  flush=True)  # fmt: skip
            return
        record = done_cell.record
        write_synced(dest, json.dumps(record, indent=1, sort_keys=True) + "\n")
        print(f"DONE {key(cell)}: {record['label']} ({record['rule']}) in "
              f"{record['wall_s']:.0f} s", flush=True)  # fmt: skip


def h4_frozen(arm: str) -> dict[str, str]:
    """The digests of the arm's frozen record, after the check a run passes first.

    The runner calls :func:`tools.p2_live.check_p2_frozen` before every P2 run, offline
    included; this repeats it on the driver's side so the record names what it checked.
    """
    from tools.p2_live import (
        agent_frozen_record_sha256,
        check_p2_frozen,
        config_digest,
        frozen_record_sha256,
    )
    from tools.workflow_config import load_p2

    path = H4_ARMS[arm]
    config = load_p2() if path is None else load_p2(path)
    check_p2_frozen(config)
    out = {
        "frozen_record_sha256": frozen_record_sha256(config),
        "config_sha256": config_digest(config),
    }
    if config.agents is not None:
        out["agents_frozen_sha256"] = agent_frozen_record_sha256(config)
    return out


def h4_record(
    cell: tuple[str, str, str],
    replicate: int,
    arm: str,
    truth: list[str],
    run_dir: Path,
    result: Any,
    wall_s: float,
    frozen: dict[str, str],
) -> dict[str, Any]:
    """One H4 run's record, read from its own run directory (never the truth store)."""
    out = run_dir / "workflows" / "p2"
    report = _json_or_empty(out / "report.json")
    summary = _json_or_empty(out / "summary.json")
    digest, n_lines = calls_digest(run_dir / "calls.jsonl")
    return {
        "cell": key(cell),
        "replicate": replicate,
        "arm": arm,
        "truth": truth,  # the scenario file's label, never the truth store
        "run_id": run_dir.name,
        "wall_s": round(wall_s, 1),
        "completed": bool(result.completed),
        "error": result.error,
        "failure_reason": getattr(result, "failure_reason", "")
        or ("" if result.completed else "run_failed"),
        "evaluations_used": result.simulator_evals_used,
        "evaluations_total": result.simulator_evals_total,
        "label": report.get("label"),
        "outcome": report.get("outcome", "pending"),
        "rule": report.get("rule"),
        "verdict": report.get("verdict"),
        "null_table": report.get("null_table"),
        "signatures": report.get("signatures"),
        "routing": report.get("routing"),
        "workflow_version": report.get("workflow_version"),
        "decider": summary.get("decider"),
        "llm_turns": summary.get("llm_turns"),
        "model_id": summary.get("model_id"),
        "frozen": frozen,
        "provenance": {
            k: summary.get(k)
            for k in ("templates_sha256", "schemas_sha256", "tools_sha256", "git_commit")
        },
        "observations_sha256": observations_digest(run_dir),
        "calls_sha256": digest,
        "calls_lines": n_lines,
    }


def h4_run(store: Path, part: str = "0/1") -> None:
    """Generate and run every H4 job of this part that has no result yet (offline only)."""
    from scenarios.schema import load_scenario
    from scripts.p2_rerun import InFlight, run_counted, set_aside, write_synced
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from sim.run.matrix import at_plant_horizon
    from tools.runner import run_workflow

    i, n = (int(x) for x in part.split("/"))
    results, unfinished = store / "results", store / "unfinished"
    results.mkdir(parents=True, exist_ok=True)
    unfinished.mkdir(parents=True, exist_ok=True)
    journal = InFlight(store / f"in_flight.{i}.jsonl", sorted(store.glob("in_flight.*.jsonl")))
    orphans = journal.orphans(h4_settled(store))
    if InFlight.TORN in orphans:
        print("STOP: an in-flight journal line is torn; no job is run.", flush=True)
        return
    for j, (cell, rep, arm) in enumerate(h4_jobs()):
        if j % n != i:
            continue
        name = h4_name(cell, rep, arm)
        if (results / name).is_file() or (unfinished / name).is_file():
            continue
        sid, plant_id, tier = cell
        plant = load_plant_config(plant_id)
        scenario = at_plant_horizon(load_scenario(REPO / "scenarios" / f"{sid}.yaml"), plant)
        # each arm its own run store: a run's id is keyed on its cell and seed, so two arms
        # in one store would share a run directory and write over each other's outputs
        root = store / arm / "runs"
        job = f"{key(cell)} {arm}"
        prior = orphans.get((job, rep), [])
        run_ids: list[str] = [str(p["run_id"]) for p in prior]
        frozen = h4_frozen(arm)  # refuses before any run if the record moved

        def attempt(
            k: int,
            cell: Any = cell,
            rep: int = rep,
            arm: str = arm,
            job: str = job,
            scenario: Any = scenario,
            plant: Any = plant,
            tier: str = tier,
            root: Path = root,
            run_ids: list[str] = run_ids,
            frozen: dict[str, str] = frozen,
        ) -> dict:
            if k > 1:
                set_aside(root / run_ids[-1], k - 1)
            art = generate_run(scenario, tier, plant=plant, replicate=rep, runs_root=root)
            run_ids.append(art.run_id)
            journal.start(job, rep, k, art.run_id)
            print(f"START {job} r{rep} ({art.run_id}, attempt {k})", flush=True)
            started = time.perf_counter()
            path = H4_ARMS[arm]
            result = run_workflow(
                art.run_id, "p2", runs_root=root, scenario=scenario, config_path=path
            )
            journal.finish(job, rep, k, art.run_id, {
                "completed": result.completed, "error": result.error,
                "failure_reason": getattr(result, "failure_reason", "")
                or ("" if result.completed else "run_failed")})  # fmt: skip
            record = h4_record(
                cell, rep, arm, list(scenario.truth_label), root / art.run_id, result,
                time.perf_counter() - started, frozen,
            )  # fmt: skip
            record["attempt"] = k
            return record

        done = run_counted(attempt, live=False, prior=prior)
        if done.record is None:
            if run_ids:
                set_aside(root / run_ids[-1], len(done.attempts))
            failure = {"cell": job, "replicate": rep, **done.failure()}
            write_synced(unfinished / name, json.dumps(failure, indent=1, sort_keys=True) + "\n")
            print(f"STOP: {job} r{rep} is unfinished after one rerun; reported, never scored: "
                  f"{failure['attempts']}", flush=True)  # fmt: skip
            continue
        record = done.record
        write_synced(results / name, json.dumps(record, indent=1, sort_keys=True) + "\n")
        print(f"DONE {job} r{rep}: {record['outcome']} ({record['rule']}) in "
              f"{record['wall_s']:.0f} s", flush=True)  # fmt: skip


def h4_settled(store: Path) -> set[tuple[str, int]]:
    """The H4 jobs with a result or an unfinished record."""
    return {
        (f"{key(c)} {a}", r)
        for c, r, a in h4_jobs()
        if (store / "results" / h4_name(c, r, a)).is_file()
        or (store / "unfinished" / h4_name(c, r, a)).is_file()
    }


def settled(store: Path) -> set[tuple[str, int]]:
    """The cells with a result or an unfinished record (every part's: one directory each)."""
    return {
        (key(c), 0)
        for c in CELLS
        if (store / "results" / f"{c[0]}-{c[1]}-{c[2]}.json").is_file()
        or (store / "unfinished" / f"{c[0]}-{c[1]}-{c[2]}.json").is_file()
    }


def _json_or_empty(path: Path) -> dict[str, Any]:
    """A JSON object from ``path``, or ``{}`` when it is missing or unreadable."""
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def steps_of(store: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    """Each sensor's located change point (day, size) and the first-HRT boundary.

    Read from the run's own ``state.json`` in the store (its ``residuals``, keyed by model
    output, mapped back to sensor names through the band's channels), so the per-cell
    claims in ``docs/decisions.md`` can be checked from the repo without a re-run (the
    review's N-2). ``None`` when the store no longer holds the run.
    """
    from tools.config import load_background
    from tools.workflow_config import load_p2

    path = store / "runs" / str(record.get("run_id")) / "workflows" / "p2" / "state.json"
    if not path.is_file():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    name_of = {
        ch.channel: name
        for tiers in load_background().bands.values()
        for band in tiers.values()
        for name, ch in band.channels.items()
    }
    boundary = float(state["calibration_window"][0]) + float(load_p2().p0().attribution.transient_d)
    steps = {
        name_of.get(out, out): {"step_day": r.get("step_day"), "step_z": r.get("step_z")}
        for out, r in sorted(state["residuals"].items())
    }
    return {"first_hrt_end_d": boundary, "steps": steps}


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
                "change_point_untied": sig.get("change_point"),
                "change_point_tied": sig.get("change_point_tied"),
                "inhibited": (sig.get("inhibition") or {}).get("inhibited"),
                "r3": sig.get("r3"),
                "r3_channels": sig.get("r3_channels"),
                "r3_channels_all": sig.get("r3_channels_all"),
                "structural": sig.get("structural"),
            },
            "admitted": (r["verdict"] or {}).get("admitted"),
            "rejected": (r["verdict"] or {}).get("rejected"),
            "holdout_failed": (r["verdict"] or {}).get("holdout_failed"),
            "steps": r.get("steps"),
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


def report(store: Path, before: Path | None = None) -> dict[str, Any]:
    """Write ``reports/p2_power/cells.json`` and ``summary.md`` from the store's results.

    With ``before`` (an earlier ``cells.json``), each cell's earlier outcome is shown
    beside the new one.
    """
    from scripts.p2_rerun import InFlight, read_unfinished, stopped

    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((store / "results").glob("*.json"))]  # fmt: skip
    for r in records:
        r["steps"] = steps_of(store, r)
    out = summarise(records)
    # unfinished cells are reported, never scored or counted (the review of b837c64, S-1)
    out["unfinished"] = read_unfinished(list((store / "unfinished").glob("*.json")))
    # and a stopped driver's cell, before any resume (the review of 0b9f210, SF-1)
    paths = sorted(store.glob("in_flight.*.jsonl"))
    if paths:
        out["unfinished"] += stopped(InFlight(paths[0], paths).orphans(settled(store)))
    out["reruns"] = [{"cell": r["cell"], "run_id": r.get("run_id")}
                     for r in records if int(r.get("attempt", 1)) > 1]  # fmt: skip
    if before is not None:
        earlier = json.loads(before.read_text(encoding="utf-8"))
        was = {c["cell"]: c.get("outcome", c["label"]) for c in earlier["cells"]}
        out["before"] = {"file": before.name, "hits_faulted": earlier["hits_faulted"]}
        for x in out["cells"]:
            x["outcome_before"] = was.get(x["cell"])
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
        # a blank line before each group, so neither runs into the sentence above (N-5)
        *([""] if out["unfinished"] else []),
        *[
            f"Unfinished (not scored, reported to the coordinator): {u['cell']}, "
            f"{u['status']}{' (' + u['note'] + ')' if u.get('note') else ''}: {u['attempts']}"
            for u in out["unfinished"]
        ],
        *([""] if out["reruns"] else []),
        *[f"Rerun once, completed: {x['cell']} ({x['run_id']})" for x in out["reruns"]],
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
    if "before" in out:
        lines += [
            "",
            f"Before (`{out['before']['file']}`): faulted cells hit "
            f"{out['before']['hits_faulted']}.",
            "",
            "| cell | truth | before | after |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {x['cell']} | {','.join(x['truth'])} | {x['outcome_before']} | {x['outcome']} |"
            for x in out["cells"]
        ]
    (REPORT_DIR / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return out


def h4_summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Each H4 run's row, the paired seed checks, and the counts per arm (descriptive only)."""
    rows = []
    for r in records:
        t = r.get("null_table") or {}
        out = outcome_of(r)
        admitted = (r.get("verdict") or {}).get("admitted") or []
        rows.append({
            "cell": r["cell"],
            "replicate": r["replicate"],
            "arm": r["arm"],
            "truth": r["truth"],
            "label": r["label"],
            "outcome": out,
            "rule": r.get("rule"),
            "excluded": out in EXCLUDED,
            # a run writes one label: a hit names one of the two faults, never both
            "hit": out not in EXCLUDED and out in r["truth"],
            "admitted": admitted,
            "truth_admitted": sorted(set(admitted) & set(r["truth"])),
            "null": {k: t.get(k) for k in ("NB", "NM", "NS", "null_partial", "null_rejected")},
            "failed_channels": t.get("failed_channels"),
            "routing": [x.get("to") for x in (r.get("routing") or [])],
            "evaluations": f"{r['evaluations_used']}/{r['evaluations_total']}",
            "wall_min": round(r["wall_s"] / 60.0, 1),
            "decider": r.get("decider"),
            "llm_turns": r.get("llm_turns"),
            "frozen": r.get("frozen"),
            "observations_sha256": r.get("observations_sha256"),
            "calls_sha256": r.get("calls_sha256"),
            "calls_lines": r.get("calls_lines"),
            "run_id": r.get("run_id"),
        })  # fmt: skip
    rows.sort(key=lambda x: (x["cell"], x["replicate"], x["arm"]))
    # one seed generates one cell: both arms see byte-identical observations; two seeds differ
    pairs: dict[str, dict[str, Any]] = {}
    for x in rows:
        pairs.setdefault(f"{x['cell']} r{x['replicate']}", {})[x["arm"]] = x["observations_sha256"]
    seeds = {
        k: {"arms_see_the_same_observations": len(set(v.values())) == 1, "arms": sorted(v)}
        for k, v in pairs.items()
    }
    by_cell: dict[str, set[str]] = {}
    for k, v in pairs.items():
        by_cell.setdefault(k.rsplit(" r", 1)[0], set()).update(v.values())
    arms = {}
    for arm in H4_ARMS:
        mine = [x for x in rows if x["arm"] == arm]
        scored = [x for x in mine if not x["excluded"]]
        arms[arm] = {
            "runs": len(mine),
            "hits": f"{sum(x['hit'] for x in scored)} of {len(scored)} scored",
            "excluded": {k: sum(1 for x in mine if x["outcome"] == k) for k in EXCLUDED},
            "both_faults_admitted": sum(len(x["truth_admitted"]) == 2 for x in mine),
        }
    return {
        "what": "the Q6 (H4) development cells offline: no model in either arm",
        "counting": "on the outcome (verdict and completion), never on the label alone",
        "descriptive_only": True,
        "cells": rows,
        "arms": arms,
        "seed_checks": seeds,
        "seeds_differ_within_a_cell": {k: len(v) == len(H4_REPLICATES) for k, v in by_cell.items()},
    }


def h4_report(store: Path) -> dict[str, Any]:
    """Write ``reports/p2_power/h4_cells.json`` and ``h4_summary.md`` from the store."""
    from scripts.p2_rerun import InFlight, read_unfinished, stopped

    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((store / "results").glob("*.json"))]  # fmt: skip
    out = h4_summarise(records)
    out["unfinished"] = read_unfinished(list((store / "unfinished").glob("*.json")))
    paths = sorted(store.glob("in_flight.*.jsonl"))
    if paths:
        out["unfinished"] += stopped(InFlight(paths[0], paths).orphans(h4_settled(store)))
    out["reruns"] = [{"cell": r["cell"], "replicate": r["replicate"], "arm": r["arm"],
                      "run_id": r.get("run_id")}
                     for r in records if int(r.get("attempt", 1)) > 1]  # fmt: skip
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "h4_cells.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    lines = [
        "# The Q6 (H4) development cells offline: no model call",
        "",
        "S7-01 at B/A, B/B, B/C and S7-02 at A/C, two seeds each (replicates 0 and 1), each",
        "run by both arms with every decision at its offline fallback: the procedural P2",
        "(`p2.yaml`, the code-only floor) and the agent arm (`p2_agents.yaml` as committed,",
        "its frozen record checked before every run, its roles at their scripted plans).",
        "Descriptive only (design note §7). A run writes one label, so a hit names one of",
        "the two faults; `truth admitted` shows which of them the admission let through.",
        "Every count keys on the outcome; an abstaining or unfinished run is excluded.",
        "",
        *[f"- {arm}: hits {v['hits']}; excluded "
          f"{', '.join(f'{k} {n}' for k, n in v['excluded'].items())}; both faults admitted "
          f"in {v['both_faults_admitted']} of {v['runs']} runs"
          for arm, v in out["arms"].items()],
        *([""] if out["unfinished"] else []),
        *[f"Unfinished (not scored): {u['cell']} r{u.get('replicate', 0)}, {u['status']}: "
          f"{u['attempts']}" for u in out["unfinished"]],
        *([""] if out["reruns"] else []),
        *[f"Rerun once, completed: {x['cell']} r{x['replicate']} {x['arm']} ({x['run_id']})"
          for x in out["reruns"]],
        "",
        "| cell | seed | arm | truth | outcome | rule | truth admitted | NB | NM | NS "
        "| failed channels | evaluations | wall min |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for x in out["cells"]:
        n = x["null"]
        lines.append(
            f"| {x['cell']} | {x['replicate']} | {x['arm']} | {','.join(x['truth'])} | "
            f"{x['outcome']} | {x['rule']} | {','.join(x['truth_admitted']) or '-'} | "
            f"{n.get('NB')} | {n.get('NM')} | {n.get('NS')} | {x['failed_channels']} | "
            f"{x['evaluations']} | {x['wall_min']} |"
        )
    same = all(v["arms_see_the_same_observations"] for v in out["seed_checks"].values())
    differ = all(out["seeds_differ_within_a_cell"].values())
    lines += [
        "",
        f"Seed checks: both arms of every cell and seed saw byte-identical observations: "
        f"{same}; the two seeds of every cell differ: {differ}.",
    ]
    (REPORT_DIR / "h4_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["run", "report", "h4-run", "h4-report"])
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--part", default="0/1")
    parser.add_argument("--before", type=Path, default=None)
    args = parser.parse_args(argv)
    store = args.store.resolve()
    if store == REPO or REPO in store.parents:
        raise SystemExit("the store must be outside the repository")
    if args.action == "run":
        run(store, args.part)
    elif args.action == "report":
        report(store, args.before)
    elif args.action == "h4-run":
        h4_run(store, args.part)
    else:
        h4_report(store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
