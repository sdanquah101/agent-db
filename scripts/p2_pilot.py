"""P2's live pilot (deliverable 3; ``docs/p2_design.md`` §11): PREPARED, NOT RUN.

The pilot is the three-role minimum (data quality, calibration, verification;
coordination is code) with the live decider, on three development cells x two seeds
(replicates 0 and 1), about USD 0.3 in all:

| cell | truth | why |
|---|---|---|
| S0-01 B/B | ``none`` | the go/no-go cell (decisions b, c of 2026-10-07) |
| S2-01 B/B | ``sensor`` (pH drift) | data quality's S1 path |
| S8-01 B/B | ``sensor`` (gas scale), injected sampler failure | calibration's Level-8 path |

**No live call is made until the lead approves the pilot**, after the coordinator's review
of deliverable 3. The gate is not here: it is the runner's. ``run_workflow(live=True)``
refuses without the lead's committed approval record
(``configs/workflows/p2_live_approval.yaml``, checked by digest on a clean tree, naming
this exact run list and the caps; :func:`tools.p2_live.require_live_approval`). The
record is committed only on the lead's word, and one that no longer matches the
configuration refuses. ``run`` checks it first, before any client is built.

Usage::

    python -m scripts.p2_pilot plan                       # no call: cells, caps, layout
    python -m scripts.p2_pilot offline --store DIR        # the same six runs, OFFLINE
    python -m scripts.p2_pilot run --store DIR --live     # refused without the record
    python -m scripts.p2_pilot report --store DIR --attempt attempt2  # reports/p2_pilot/<attempt>/

``offline`` runs the six pilot runs with the offline decider at the same commit and the
same configuration (the review of PR #33, B-2): the baseline a live-versus-offline
difference is measured against. It writes ``DIR/results_offline.jsonl`` and
``reports/p2_pilot/offline.json`` and ``offline.md``.

**The record layout.** ``DIR`` lies outside the repository:

- ``DIR/config/``: the pilot's configuration, which is ``p2.yaml`` with the three-role
  ablation (influent, identifiability and design off), beside ``p0.yaml`` and the
  templates. The runner checks it against the same freeze.
- ``DIR/runs/<id>/workflows/p2/``: the run's record (``state.json``, ``report.json``,
  ``messages.jsonl``, ``decisions.jsonl``), the gateway's ``llm_calls.jsonl`` and the
  runner's ``summary.json`` with ``by_role``.
- ``DIR/results.jsonl``: one line per finished cell (summary and outcome).
- ``reports/p2_pilot/<attempt>/cells.json`` and ``summary.md``: each cell and seed's
  outcome (keyed on the verdict, never the label alone), the go/no-go check on S0-01 B/B,
  and the cost: USD, requests and the wall clock. The run's own visible records are copied
  beside them, under ``<attempt>/<run id>/``: ``llm_calls.jsonl``, ``decisions.jsonl``
  and the registry's ``calls.jsonl`` (the review of ``7ef1238``, nit 3).

**The wall clock is a cost for P2, never a compliance figure.** P2 runs have no
wall-clock limit (the lead's ruling of 2026-10-13), so the tables report the runner's
``wall_s`` as what the run cost. The evaluator's ``wall_clock_fraction`` (``eval/``,
frozen) divides by the cell's nominal allowance: for P2 it is a ratio against an
allowance that was never enforced, not a measure of staying inside it.

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
"""The pilot's total. A run is launched only if the running total plus one run's whole
cap (``caps.max_usd``) stays within it (N-new-5), so the worst case is this figure."""

KEY_VARIABLE = "OPENAI_API_KEY"


def plan() -> dict[str, Any]:
    """What the pilot would run, at what caps; makes no call of any kind."""
    from tools.workflow_config import load_p2

    config = load_p2()
    return {
        "approved": approved(),
        "cells": [f"{s} {p}/{t}" for s, p, t in CELLS],
        "replicates": list(REPLICATES),
        "runs": len(CELLS) * len(REPLICATES),
        "roles_off": sorted(THREE_ROLES),
        "model": config.model.model_id,
        "effort": config.model.effort,
        "caps_per_run": config.caps.model_dump(),
        "pilot_max_usd": PILOT_MAX_USD,
        "config_sha256": pilot_config_digest(),
        "expected_usd": 0.3,
        "command": "python -m scripts.p2_pilot run --store <DIR outside the repo> --live",
    }


def approval_draft(store: Path) -> dict[str, Any]:
    """Every field an approval record for this pilot must carry, but the ruling's text.

    The record is written and committed only on the coordinator's relay; this prints
    what it must hold for a store, so nothing is retyped by hand.
    """
    from tools.p2_live import config_digest, frozen_record_sha256
    from tools.workflow_config import load_p2

    store = Path(store).resolve()
    config = load_p2(write_config(store))
    return {
        "runs": approval_runs(),
        "caps": config.caps.model_dump(mode="json"),
        "frozen_sha256": frozen_record_sha256(),
        "config_sha256": config_digest(config),
        "runs_root": str(store / "runs"),
    }


def approval_runs() -> list[dict[str, Any]]:
    """The run list an approval record must name for this pilot, in order."""
    return [
        {"scenario": s, "plant": p, "tier": t, "replicate": r}
        for s, p, t in CELLS
        for r in REPLICATES
    ]


def pilot_config_digest() -> str:
    """The digest an approval record must name for the pilot's configuration (N-B3c)."""
    import tempfile

    from tools.p2_live import config_digest
    from tools.workflow_config import load_p2

    with tempfile.TemporaryDirectory() as tmp:
        return config_digest(load_p2(write_config(Path(tmp))))


def approved() -> bool:
    """Whether an approval record exists (no call is made).

    Whether it is valid for a store (pushed, this configuration, this run store) is
    checked by ``run`` and by the runner for every run.
    """
    from tools.p2_live import APPROVAL_FILE

    return APPROVAL_FILE.is_file()


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
    """Run the pilot live: refused without ``--live``, the approval record or the key.

    Raises:
        SystemExit: Not ``--live``, no approval, no key, or a store inside the repository.
    """
    if not live:
        raise SystemExit("the pilot is live: pass --live (or run `offline`)")
    from tools.p2_live import require_live_approval
    from tools.workflow_config import load_p2

    store = store.resolve()
    # a stopped pilot's run is recorded unfinished before any check that could refuse this
    # start (the review of 0b9f210, SF-1): a file write, no call
    record_stopped_live(store)
    try:
        # against the configuration the pilot actually runs (the three-role copy) and
        # its run store: the very checks the runner repeats for every run
        require_live_approval(load_p2(write_config(store)), runs_root=store / "runs")
    except ValueError as exc:
        raise SystemExit(f"the pilot is not approved: {exc}") from exc
    if not os.environ.get(KEY_VARIABLE):
        raise SystemExit(f"{KEY_VARIABLE} is not set")
    _runs(store, live=True)


def offline(store: Path, part: str = "0/1") -> None:
    """The six pilot runs with the offline decider: no model, no approval needed (B-2).

    ``part`` ``i/n`` runs every n-th run from the i-th, so two processes can share them.
    """
    _runs(store, live=False, part=part)


def _runs(store: Path, *, live: bool, part: str = "0/1") -> None:
    store = store.resolve()
    if store == REPO or REPO in store.parents:
        raise SystemExit("the store must be outside the repository")
    from scenarios.schema import load_scenario
    from scripts.p2_rerun import InFlight, append_synced, run_counted, set_aside
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from sim.run.matrix import at_plant_horizon
    from tools.runner import run_workflow

    config_path = write_config(store)
    i_part, n_part = (int(x) for x in part.split("/"))
    results = store / ("results.jsonl" if live else f"results_offline.{i_part}.jsonl")
    # unfinished runs are never results (the lead's rulings of 2026-10-19): they are kept
    # apart, reported, and never pooled, scored or counted as abstentions
    unfinished = store / ("unfinished.jsonl" if live else f"unfinished_offline.{i_part}.jsonl")
    if live and record_stopped_live(store):
        return
    # every part's files, so a resume under another part count still sees each cell's
    # result, unfinished record and stopped attempt (the review of 0b9f210, SF-2)
    done = settled(store, live=live)
    journal = InFlight(store / ("in_flight.jsonl" if live else f"in_flight_offline.{i_part}.jsonl"),
                       journals(store, live=live))  # fmt: skip
    # a stopped driver's attempt (journalled, no result, no record) is an unfinished one
    # (the review of b837c64, S-2): offline it counts, so at most one rerun follows
    orphans = journal.orphans(done)
    if not live and InFlight.TORN in orphans:
        print("STOP: an in-flight journal line is torn and names no cell; one attempt's "
              "cell is unknown, so no cell is run. Report it to the coordinator.",
              flush=True)  # fmt: skip
        return
    if live and unfinished.is_file() and unfinished.read_text().strip():
        # a live rerun is a new live call: only the lead's approval, relayed, starts one
        print(f"STOP: {unfinished.name} records an unfinished live run; a rerun or any "
              "further live run needs the lead's approval relayed by the coordinator")  # fmt: skip
        return
    from tools.workflow_config import load_p2

    per_run = float(load_p2(config_path).caps.max_usd)
    # the running total lives in the store, so a resumed pilot does not restart at 0
    ledger = store / ("spent_usd.json" if live else "spent_usd_offline.json")
    spent = float(json.loads(ledger.read_text())["usd"]) if ledger.is_file() else 0.0
    order = [(c, r) for c in CELLS for r in REPLICATES]
    for k, ((sid, plant_id, tier), rep) in enumerate(order):
        if k % n_part != i_part:
            continue
        cell = f"{sid} {plant_id}/{tier}"
        if (cell, rep) in done:
            continue
        if live and spent + per_run > PILOT_MAX_USD:
            print(f"STOP: USD {spent:.3f} spent; one more run could pass {PILOT_MAX_USD}")
            return
        plant = load_plant_config(plant_id)
        scenario = at_plant_horizon(load_scenario(REPO / "scenarios" / f"{sid}.yaml"), plant)
        prior = orphans.get((cell, rep), [])
        run_ids: list[str] = [str(p["run_id"]) for p in prior]

        def attempt(
            n: int,
            scenario: Any = scenario,
            plant: Any = plant,
            tier: str = tier,
            rep: int = rep,
            cell: str = cell,
            run_ids: list[str] = run_ids,
        ) -> dict:
            nonlocal spent
            if n > 1:  # the same cell and seed, regenerated; the failed attempt kept aside
                set_aside(store / "runs" / run_ids[-1], n - 1)
            art = generate_run(scenario, tier, plant=plant, replicate=rep,
                               runs_root=store / "runs")  # fmt: skip
            run_ids.append(art.run_id)
            journal.start(cell, rep, n, art.run_id)
            result = run_workflow(
                art.run_id,
                "p2",
                runs_root=store / "runs",
                scenario=scenario,
                config_path=config_path,
                live=live,
            )
            journal.finish(cell, rep, n, art.run_id, result.as_dict())
            spent += float(result.llm_cost_usd or 0.0)
            ledger.write_text(json.dumps({"usd": spent}), encoding="utf-8")
            out = store / "runs" / art.run_id / "workflows" / "p2"
            # a run that died wrote no report, or a partial or unreadable one: it is
            # unfinished (N-11f, N-11f')
            report = read_report(out / "report.json")
            return {
                "cell": cell,
                "replicate": rep,
                "run_id": art.run_id,
                "attempt": n,
                "truth": list(scenario.truth_label),
                "summary": result.as_dict(),
                "outcome": report.get("outcome", "pending"),
                "label": report.get("label"),
                "rule": report.get("rule"),
                "null_table": report.get("null_table"),
                "verdict": report.get("verdict"),
            }

        done_cell = run_counted(attempt, live=live, prior=prior)
        if done_cell.record is None:
            if not live and run_ids:  # nothing unfinished stays at workflows/p2 (N-7)
                set_aside(store / "runs" / run_ids[-1], len(done_cell.attempts))
            failure = {"cell": cell, "replicate": rep, **done_cell.failure()}
            append_synced(unfinished, json.dumps(failure, sort_keys=True, default=str) + "\n")
            print(f"STOP: {cell} r{rep} is unfinished ({done_cell.status}); nothing is "
                  f"scored for it. Report it to the coordinator: {failure['attempts']}",
                  flush=True)  # fmt: skip
            return
        line = done_cell.record
        append_synced(results, json.dumps(line, sort_keys=True, default=str) + "\n")
        rerun = " (after one rerun)" if line["attempt"] > 1 else ""
        print(f"{cell} r{rep}: {outcome_of(line)}{rerun} (USD {spent:.3f} so far)", flush=True)


def _cells_in(paths: list[Path]) -> set[tuple[str, int]]:
    return {
        (x["cell"], int(x["replicate"]))
        for path in paths
        if path.is_file()
        for x in map(json.loads, filter(str.strip, path.read_text(encoding="utf-8").splitlines()))
    }


def settled(store: Path, *, live: bool) -> set[tuple[str, int]]:
    """The cells with a result or an unfinished record, read from every part's files."""
    if live:
        return _cells_in([store / "results.jsonl", store / "unfinished.jsonl"])
    return _cells_in(sorted(store.glob("results_offline.*.jsonl"))
                     + sorted(store.glob("unfinished_offline.*.jsonl")))  # fmt: skip


def journals(store: Path, *, live: bool) -> list[Path]:
    """Every in-flight journal of the live pilot, or of every offline part."""
    return [store / "in_flight.jsonl"] if live else sorted(store.glob("in_flight_offline.*.jsonl"))


def record_stopped_live(store: Path) -> bool:
    """Record a stopped live pilot's runs unfinished; whether any was found.

    Called first by ``run``, before the approval and key checks, and by the driver: a live
    run left by a stopped pilot is recorded unfinished (``driver_stopped``) and never
    rerun without the lead's approval. A file write, no call.
    """
    from scripts.p2_rerun import InFlight, append_synced

    if not (store / "in_flight.jsonl").is_file():
        return False
    orphans = InFlight(store / "in_flight.jsonl").orphans(settled(store, live=True))
    # written only when there is something to record: a refused start with nothing
    # stopped leaves no empty unfinished.jsonl behind (B4, N-e)
    for (cell, rep), prior in orphans.items():
        failure = {"cell": cell, "replicate": rep, "status": "unfinished_live",
                   "attempts": [{"run_id": p["run_id"], "completed": False,
                                 "error": p["summary"]["error"],
                                 "failure_reason": p["summary"]["failure_reason"],
                                 "rule": None} for p in prior]}  # fmt: skip
        append_synced(store / "unfinished.jsonl", json.dumps(failure, sort_keys=True) + "\n")
        print(f"STOP: {cell} r{rep} was left unfinished by a stopped pilot; it is "
              "recorded unfinished and not rerun: a live rerun needs the lead's "
              "approval relayed by the coordinator", flush=True)  # fmt: skip
    return bool(orphans)


def read_report(path: Path) -> dict[str, Any]:
    """A run's ``report.json``, or ``{}`` when it is missing, truncated or unreadable."""
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def outcome_of(line: dict[str, Any]) -> str:
    """The runner's completion first, then the report's outcome (the review's N-4)."""
    if not (line.get("summary") or {}).get("completed"):
        return "pending"
    return str(line.get("outcome") or "pending")


RUN_RECORDS = (
    ("workflows/p2/llm_calls.jsonl", "llm_calls.jsonl"),
    ("workflows/p2/decisions.jsonl", "decisions.jsonl"),
    ("calls.jsonl", "calls.jsonl"),
)
"""Each run's visible records the report copies: the gateway's, the decisions', the registry's."""


def report(store: Path, attempt: str = "attempt2") -> dict[str, Any]:
    """``reports/p2_pilot/<attempt>/``: outcomes keyed on the verdict, the go/no-go, the cost.

    The cost is USD, requests and the wall clock (``wall_s``, a cost for P2, never a
    compliance figure); each run's visible records are copied beside the tables.
    """
    from scripts.p2_rerun import read_unfinished

    lines = read_unfinished([p for p in [store / "results.jsonl"] if p.is_file()])
    rows = [
        {
            "cell": x["cell"],
            "replicate": x["replicate"],
            "truth": x["truth"],
            "outcome": outcome_of(x),
            "usd": (x["summary"] or {}).get("llm_cost_usd"),
            "requests": (x["summary"] or {}).get("llm_turns"),
            "wall_min": round(float((x["summary"] or {}).get("wall_s") or 0.0) / 60.0, 1),
        }
        for x in lines
    ]
    # a stopped pilot's run is listed even before any driver has started since (the
    # review of 0b9f210, SF-1)
    unfinished = read_unfinished(list(store.glob("unfinished.jsonl"))) + stopped_in(
        store, live=True
    )
    out_dir = REPORT_DIR / attempt
    out_dir.mkdir(parents=True, exist_ok=True)
    for x in lines:
        run_id = str(x.get("run_id") or "")
        for src, name in RUN_RECORDS if run_id else ():
            path = store / "runs" / run_id / src
            if path.is_file():
                (out_dir / run_id).mkdir(exist_ok=True)
                shutil.copy2(path, out_dir / run_id / name)
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
        # what was spent in all (N-4): the ledger, and the unfinished runs' own metered cost
        "usd_ledger": _ledger(store / "spent_usd.json"),
        "usd_unfinished": unfinished_cost(store, unfinished),
        # unfinished runs are reported, never scored (the lead's rulings of 2026-10-19)
        "unfinished": unfinished,
    }
    (out_dir / "cells.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    md = [f"# P2 live pilot ({attempt})", "",
          "| cell | seed | truth | outcome | USD | requests | wall min |",
          "|---|---|---|---|---|---|---|"]  # fmt: skip
    md += [
        f"| {r['cell']} | {r['replicate']} | {','.join(r['truth'])} | {r['outcome']} "
        f"| {r['usd']} | {r['requests']} | {r['wall_min']} |"
        for r in rows
    ]
    md += unfinished_lines(unfinished) + rerun_lines(lines)
    md += ["", f"Go/no-go: stop = {out['go_no_go']['stop']}; USD {out['usd_total']} on the "
           f"finished runs; USD {out['usd_ledger']} spent in all (the pilot's ledger), of "
           f"which USD {out['usd_unfinished']} metered on unfinished runs.", "",
           "Wall min is the runner's `wall_s`: a cost (P2 has no wall-clock limit, the "
           "ruling of 2026-10-13), not compliance with the cell's allowance."]  # fmt: skip
    (out_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


def report_offline(store: Path) -> dict[str, Any]:
    """``reports/p2_pilot/offline.{json,md}``: the six runs offline (B-2).

    Where a cell is also a power-run cell (replicate 0 of S2-01 B/B and S8-01 B/B), the
    power run's outcome is shown beside it. That run had **every** role on and predates
    F-B, so a difference is the configuration's and F-B's together.
    """
    lines = [
        json.loads(x)
        for f in sorted(store.glob("results_offline.*.jsonl"))
        for x in f.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    order = {(f"{s} {p}/{t}", r): k for k, ((s, p, t), r) in enumerate(
        (c, r) for c in CELLS for r in REPLICATES)}  # fmt: skip
    lines.sort(key=lambda x: order.get((x["cell"], x["replicate"]), 99))
    power = json.loads((REPO / "reports" / "p2_power" / "cells.json").read_text())
    before = {c["cell"]: c.get("outcome", c["label"]) for c in power["cells"]}
    rows = []
    for x in lines:
        t = x.get("null_table") or {}
        full = read_report(
            store / "runs" / str(x.get("run_id")) / "workflows" / "p2" / "report.json"
        )
        sensor = (full.get("signatures") or {}).get("sensor") or {}
        s1 = sensor.get("s1") or {}
        rows.append({
            "s1": {"channel": sensor.get("channel"), "coupled_present": s1.get("coupled_present"),
                   "coupled_inside": s1.get("coupled_inside"), "reading": sensor.get("reading")},
            "cell": x["cell"], "replicate": x["replicate"], "truth": x["truth"],
            "outcome": outcome_of(x), "rule": x.get("rule"),
            "null": {k: t.get(k) for k in ("NB", "NM", "NS", "null_partial", "null_rejected")},
            "failed_channels": t.get("failed_channels"),
            "admitted": (x.get("verdict") or {}).get("admitted"),
            "power_run_outcome": before.get(x["cell"]) if x["replicate"] == 0 else None,
            "evaluations": (x["summary"] or {}).get("simulator_evals_used"),
            "wall_min": round(float((x["summary"] or {}).get("wall_s") or 0.0) / 60.0, 1),
            "commit": (x["summary"] or {}).get("git_commit"),
        })  # fmt: skip
    from scripts.p2_rerun import read_unfinished

    # unfinished cells are reported, never scored (the review of b837c64, S-1), and so is a
    # stopped driver's cell, before any resume (the review of 0b9f210, SF-1)
    unfinished = read_unfinished(list(store.glob("unfinished_offline.*.jsonl"))) + stopped_in(
        store, live=False
    )
    gate = [r["outcome"] for r in rows if r["cell"] == "S0-01 B/B"]
    out = {
        "what": "the six pilot runs, offline (no model), three-role minimum, at one commit",
        "rows": rows,
        "go_no_go_offline": {"S0-01 B/B": gate},
        "unfinished": unfinished,
        "reruns": [
            {"cell": x["cell"], "replicate": x["replicate"], "run_id": x.get("run_id")}
            for x in lines
            if int(x.get("attempt", 1)) > 1
        ],
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "offline.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    md = [
        "# P2 pilot runs, offline (B-2)",
        "",
        "The six pilot runs with the offline decider: three-role minimum, every decision at",
        "its code fallback, no model. The power-run column (replicate 0 only) is the",
        "full-role run of `reports/p2_power/` before F-B, shown where the cell overlaps.",
        "",
        "| cell | seed | truth | offline outcome | rule | failed channels | power run |",
        "|---|---|---|---|---|---|---|",
    ]
    md += [
        f"| {r['cell']} | {r['replicate']} | {','.join(r['truth'])} | {r['outcome']} | "
        f"{r['rule']} | {r['failed_channels']} | {r['power_run_outcome'] or '—'} |"
        for r in rows
    ]
    md += unfinished_lines(unfinished) + rerun_lines(lines)
    md += reading(rows)
    (REPORT_DIR / "offline.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


def stopped_in(store: Path, *, live: bool) -> list[dict[str, Any]]:
    """The journal's stopped (or still running) cells: neither a result nor a record yet."""
    from scripts.p2_rerun import InFlight, stopped

    paths = journals(store, live=live)
    if not paths:
        return []
    return stopped(InFlight(paths[0], paths).orphans(settled(store, live=live)))


def _ledger(path: Path) -> float | None:
    return round(float(json.loads(path.read_text())["usd"]), 6) if path.is_file() else None


def unfinished_cost(store: Path, unfinished: list[dict[str, Any]]) -> float | None:
    """The unfinished runs' metered cost, from each one's ``llm_calls.jsonl`` (N-4).

    Each response's usage at the pilot configuration's prices: what the gateway metered.
    A failed request's worst case, which the gateway books but never logs as usage, is in
    the ledger only. ``None`` with no declared price.
    """
    from tools.llm import TokenMeter
    from tools.workflow_config import load_p2

    config = store / "config" / "p2.yaml"
    price = load_p2(config).model.pricing_usd_per_mtok if config.is_file() else None
    if price is None:
        return None
    meter = TokenMeter()
    run_ids = {a.get("run_id") for u in unfinished for a in u.get("attempts", [])}
    for run_id in sorted(r for r in run_ids if r):
        for log in sorted((store / "runs" / run_id / "workflows").glob("p2*/llm_calls.jsonl")):
            for raw in log.read_text(encoding="utf-8").splitlines():
                if raw.strip():
                    meter.add(dict(json.loads(raw).get("usage") or {}))
    usd = (
        meter.input * price.input
        + meter.output * price.output
        + meter.cache_write * price.cache_write
        + meter.cache_read * price.cache_read
    ) / 1e6
    return round(usd, 6)  # fmt: skip


def unfinished_lines(unfinished: list[dict[str, Any]]) -> list[str]:
    """The report's lines for unfinished cells: listed, never scored (a blank line first)."""
    if not unfinished:
        return []
    return [""] + [
        f"Unfinished (not scored, reported to the coordinator): {u['cell']} "
        f"r{u.get('replicate', 0)}, {u['status']}"
        f"{' (' + u['note'] + ')' if u.get('note') else ''}: {u['attempts']}"
        for u in unfinished
    ]


def rerun_lines(lines: list[dict[str, Any]]) -> list[str]:
    """The report's lines for cells counted after one rerun (the review's N-5)."""
    reruns = [x for x in lines if int(x.get("attempt", 1)) > 1]
    if not reruns:
        return []
    return [""] + [
        f"Rerun once, completed: {x['cell']} r{x.get('replicate', 0)} ({x.get('run_id')})"
        for x in reruns
    ]


def reading(rows: list[dict[str, Any]]) -> list[str]:
    """What a live ``dq.coupled`` reading could change, generated from the rows (N-B2b).

    A run can gain ``sensor`` only where NS failed on one channel and the S1 table holds
    (every coupled channel's after-fit mean inside); then only the offline reading
    (``insufficient``) blocks it.
    """
    md = [
        "",
        "## What a live decider can change here (generated from the rows above)",
        "",
        "`sensor` can be admitted only where NS failed and the S1 table holds; there the",
        "offline `dq.coupled` reading (`insufficient`) is all that blocks it.",
        "",
        "| run | NB | NS | NS channel | coupled channels | S1 table holds | offline reading "
        "| live `coupled_inside` would give |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        n, s1 = r["null"], r["s1"]
        open_ = bool(n.get("NS")) and s1.get("coupled_inside") is True
        verdict = "—"
        if open_:
            verdict = "`sensor`: **correct**" if "sensor" in r["truth"] else "`sensor`: **wrong**"
        md.append(
            f"| {r['cell']} r{r['replicate']} | {n.get('NB')} | {n.get('NS')} | "
            f"{s1.get('channel') or '—'} | {', '.join(s1.get('coupled_present') or []) or '—'} | "
            f"{s1.get('coupled_inside') if s1.get('channel') else '—'} | "
            f"{s1.get('reading') or '—'} | {verdict} |"
        )
    gate = [r for r in rows if r["cell"] == "S0-01 B/B"]
    stands = [r["replicate"] for r in gate if not r["null"].get("null_rejected")]
    md += [
        "",
        "A run whose null stands is `none` whatever a decision says. "
        + (
            f"S0-01 B/B r{', r'.join(map(str, stands))}: the null stands, so at most "
            f"{len(gate) - len(stands)} seed(s) of the go/no-go cell can be labelled."
            if stands
            else "Both seeds of S0-01 B/B reject the null."
        ),
    ]
    return md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "action", choices=["plan", "offline", "run", "report", "report-offline"], nargs="?",
        default="plan",
    )  # fmt: skip
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--part", default="0/1", help="offline only: i/n of the runs")
    parser.add_argument("--attempt", default="attempt2", help="report only: its directory")
    args = parser.parse_args(argv)
    if args.action == "plan":
        print(json.dumps(plan(), indent=1))
        return 0
    if args.store is None:
        parser.error("--store is required")
    if args.action == "run":
        run(args.store, live=args.live)
    elif args.action == "offline":
        offline(args.store, args.part)
    elif args.action == "report-offline":
        report_offline(args.store)
    else:
        report(args.store, args.attempt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
