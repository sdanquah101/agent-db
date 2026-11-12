"""The agent arm's live pilot on the H4 cells (the lead's "approve the pilot", 2026-11-11).

Eight runs, S7-01 at B/A, B/B, B/C and S7-02 at A/C at replicates 0 and 1, of the agent
arm (``configs/workflows/p2_agents.yaml`` as committed) with the live decider, in the fresh
store the lead's approval record names, descriptive only (``docs/p2_agents_design.md``
§7). **Every run is gated three times before a model client exists:** the lead's committed
approval (:func:`tools.p2_live.require_live_approval`: the record as pushed on a clean
tree, its digest, the freeze, the configuration, the caps, this very run and this store),
the agent freeze (:func:`tools.p2_live.check_p2_frozen`, through
:func:`scripts.p2_power.h4_frozen`), and the store (fresh: a run the store already holds
is refused). The runner repeats the approval and freeze checks for each run and builds the
one live client; every model call goes through the agent gateway
(:class:`tools.p2_live.P2AgentGateway`) under the configured caps, the proposers' and the
verifier's, and is logged to ``llm_calls.jsonl`` beside the registry's ``calls.jsonl``.

Each run's record (``results.jsonl``) carries the label, the secondary labels and the
confidence the arm wrote; eval's two scores, ``primary_in_truth`` and ``attribution_exact``,
computed here from the scenario file's truth label (never the truth store); the spend
(USD, requests, attempts, tokens) in total and per role; every cap refusal the gateway
logged and whether the arm abstained on a cap; and whether the run finished. A live run is
never rerun (the lead's rulings of 2026-10-19): an unfinished one is recorded and stops the
pilot, and a rerun needs the lead's approval relayed by the coordinator.

**The lead's "B" (12 Nov 2026)** adds two rules and one bound:

- **An unreachable model is unfinished, never scored.** A run whose own ``llm_calls.jsonl``
  shows a credit, auth, quota or permission error on any attempt, or every attempt failing,
  is recorded in ``unfinished.jsonl`` with the error quoted, prints STOP and stops the pilot
  (:func:`model_unreachable`). The first live start's runs abstained on scripted fallbacks
  because every call failed with "no credits remaining"; such a run is not a result.
- **A run cut off by a restart is redone once.** A live run in the in-flight journal with
  no result and no unfinished record, and only that one attempt, has its run directory
  set aside under ``set_aside/`` (never deleted), is recorded in ``restarts.jsonl``, and is
  run again **once** in the same store through every gate. A second interruption of the same
  run is unfinished and stops the pilot (:func:`restart_eligible`).
- **The ledger counts a set-aside run** at the whole per-run cap (its meter died with it),
  so a redo never resets the USD ceiling.

``python -m scripts.p2_agents_pilot run --live`` runs the pilot in the approved store
(``OPENAI_API_KEY`` in the environment, never logged); ``run --dry-run --store DIR`` goes
through every check and every run with the offline scripted model in a scratch store and
builds no client; ``report`` writes ``reports/p2_agents_pilot/``. **No command here makes
a live call without ``--live``**, and ``--live`` makes none before the approval passes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.p2_power import (
    H4_CELLS,
    H4_REPLICATES,
    calls_digest,
    h4_frozen,
    key,
    observations_digest,
)

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "reports" / "p2_agents_pilot"
ARM = "agents"
"""The arm this pilot runs: ``H4_ARMS['agents']``, the committed ``p2_agents.yaml``."""
CELLS = H4_CELLS
REPLICATES = H4_REPLICATES
KEY_VARIABLE = "OPENAI_API_KEY"
"""The variable the live client reads its key from; never printed, logged or recorded."""

RUN_RECORDS = (
    ("workflows/p2/llm_calls.jsonl", "llm_calls.jsonl"),
    ("workflows/p2/decisions.jsonl", "decisions.jsonl"),
    ("workflows/p2/messages.jsonl", "messages.jsonl"),
    ("workflows/p2/report.json", "report.json"),
    ("workflows/p2/state.json", "state.json"),
    ("workflows/p2/summary.json", "summary.json"),
    ("workflows/p2/spend.json", "spend.json"),
    ("calls.jsonl", "calls.jsonl"),
)
"""Each run's visible records the report copies beside its tables."""

RESTART_RULING = "the lead's B of 12 Nov"
"""The word a restart's redo is made on, written into every restart record."""
UNREACHABLE = re.compile(
    r"AuthenticationError|PermissionDeniedError|Error code: (?:401|402|403)\b"
    r"|invalid_api_key|insufficient_quota|no credits|credit balance|quota|billing",
    re.IGNORECASE,
)
"""A provider error that means the model cannot be reached: credit, auth, quota, permission.

A transient error (a rate limit, a timeout, a dropped connection) does not match: a run with
one is scored unless every attempt failed.
"""


def config_path() -> Path:
    """The committed agent configuration the pilot runs, and the approval names."""
    from tools.p2_live import COMMITTED_P2_AGENTS

    return COMMITTED_P2_AGENTS


def load_config() -> Any:
    from tools.workflow_config import load_p2

    return load_p2(config_path())


def approval_runs() -> list[dict[str, Any]]:
    """The run list the approval record must name for this pilot, in order."""
    return [
        {"scenario": s, "plant": p, "tier": t, "replicate": r}
        for s, p, t in CELLS
        for r in REPLICATES
    ]


def approved_store() -> Path:
    """The store the lead's record names: ``runs_root``'s parent. Read, never checked here."""
    import yaml

    from tools.p2_live import APPROVAL_FILE

    if not APPROVAL_FILE.is_file():
        raise SystemExit(f"no approval record ({APPROVAL_FILE.name}): no live run")
    record = yaml.safe_load(APPROVAL_FILE.read_text(encoding="utf-8")) or {}
    root = record.get("runs_root")
    if not root:
        raise SystemExit("the approval record names no run store")
    return Path(str(root)).resolve().parent


def max_total_usd() -> float:
    """The pilot's worst case: every run at its whole cap (``run_caps``), nothing more."""
    from tools.p2_live import run_caps

    return float(run_caps(load_config()).max_usd) * len(approval_runs())


def plan() -> dict[str, Any]:
    """What the pilot would run, at what caps; makes no call and reads no store."""
    from tools.p2_live import frozen_record_sha256, run_caps

    config = load_config()
    return {
        "arm": ARM,
        "config": str(config_path().relative_to(REPO)),
        "model": config.model.model_id,
        "runs": approval_runs(),
        "caps_per_run": run_caps(config).model_dump(mode="json"),
        "proposer_caps": config.agents.caps.model_dump(mode="json"),
        "verifier_caps": config.agents.verifier_caps.model_dump(mode="json"),
        "max_total_usd": max_total_usd(),
        "frozen_sha256": frozen_record_sha256(config),
    }


def scenario_for(sid: str, plant: Any) -> Any:
    """The cell's scenario at the plant's horizon (tests shorten it here)."""
    from scenarios.schema import load_scenario
    from sim.run.matrix import at_plant_horizon

    return at_plant_horizon(load_scenario(REPO / "scenarios" / f"{sid}.yaml"), plant)


# ------------------------------------------------------------------ the gates


def check_run_approved(cell: dict[str, Any], runs_root: Path | None) -> dict[str, Any]:
    """The lead's approval of this very run, checked before any client exists.

    With ``runs_root`` (live) the record must name that store too; the dry run passes
    none, since it must not touch the approved store and runs in a scratch one.
    """
    from tools.p2_live import require_live_approval

    return require_live_approval(load_config(), cell, runs_root=runs_root)


def check_store_fresh(run_dir: Path) -> None:
    """Refuse a run the store already holds: its outputs, or a model log, exist.

    Raises:
        ValueError: The run directory already carries workflow outputs.
    """
    out = run_dir / "workflows" / "p2"
    if out.exists():
        what = "a model log" if (out / "llm_calls.jsonl").is_file() else "outputs"
        raise ValueError(f"the store already holds {run_dir.name} ({what}): not a fresh store")


# ------------------------------------------------------------------ the record


def _json_or_empty(path: Path) -> dict[str, Any]:
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def cap_refusals(run_dir: Path) -> list[dict[str, Any]]:
    """Every attempt the gateway refused on a cap, from the run's own ``llm_calls.jsonl``."""
    path = run_dir / "workflows" / "p2" / "llm_calls.jsonl"
    if not path.is_file():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if line.get("refused"):
            prov = line.get("provenance") or {}
            out.append({
                "role": prov.get("role") or line.get("role"),
                "point": prov.get("point"),
                "error": line.get("error"),
            })  # fmt: skip
    return out


def _model_calls(run_dir: Path) -> list[dict[str, Any]]:
    """The run's model attempts from its own ``llm_calls.jsonl``, cap refusals left out."""
    path = run_dir / "workflows" / "p2" / "llm_calls.jsonl"
    if not path.is_file():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and not line.get("refused"):
            out.append(line)
    return out


def model_unreachable(run_dir: Path) -> str | None:
    """Why the provider could not be reached in this run, quoted; ``None`` if it could.

    Read from the run's own ``llm_calls.jsonl`` (the lead's "B", 12 Nov): a credit, auth,
    quota or permission error on any attempt (:data:`UNREACHABLE`), or every attempt
    failing. A gateway cap refusal is not an attempt and counts neither way; a run with no
    attempt at all (the offline model) is not unreachable.
    """
    calls = _model_calls(run_dir)
    errors = [str(x["error"]) for x in calls if x.get("error")]
    for error in errors:
        if UNREACHABLE.search(error):
            return error
    if calls and len(errors) == len(calls):
        return f"every attempt failed ({len(calls)} of {len(calls)}); the last: {errors[-1]}"
    return None


def scores(label: Any, secondary: list[str], outcome: str, truth: list[str]) -> dict[str, Any]:
    """Eval's two attribution scores (``eval/attribution.py``), from the scenario's truth.

    On the outcome: an abstaining or unfinished run scores neither (``EXCLUDED``).
    """
    from scripts.p2_power import EXCLUDED

    if outcome in EXCLUDED or label is None:
        return {"label_set": [], "primary_in_truth": False, "attribution_exact": False}
    label_set = sorted({str(label), *secondary})
    return {
        "label_set": label_set,
        "primary_in_truth": str(label) in truth,
        "attribution_exact": set(label_set) == set(truth),
    }


def run_record(
    cell: tuple[str, str, str],
    replicate: int,
    truth: list[str],
    run_dir: Path,
    result: Any,
    wall_s: float,
    frozen: dict[str, str],
    *,
    live: bool,
) -> dict[str, Any]:
    """One run's record, read from its own directory and the runner's result; no truth store."""
    out = run_dir / "workflows" / "p2"
    report = _json_or_empty(out / "report.json")
    state = _json_or_empty(out / "state.json")
    summary = result.as_dict()
    cls = state.get("classification") or {}
    secondary = [
        str(x) for x in (cls.get("secondary_labels") or report.get("secondary_labels") or [])
    ]
    outcome = str(report.get("outcome", "pending")) if summary.get("completed") else "pending"
    label = report.get("label")
    refusals = cap_refusals(run_dir)
    verdict = report.get("verdict") or {}
    digest, n_lines = (
        calls_digest(run_dir / "calls.jsonl") if (run_dir / "calls.jsonl").is_file() else ("", 0)
    )
    by_role = summary.get("by_role") or {}
    return {
        "cell": key(cell),
        "replicate": replicate,
        "arm": ARM,
        "live": live,
        "truth": truth,  # the scenario file's label, never the truth store
        "run_id": run_dir.name,
        "wall_s": round(wall_s, 1),
        "completed": bool(summary.get("completed")),
        "finished": bool(summary.get("completed")) and outcome != "pending",
        "error": summary.get("error"),
        "failure_reason": summary.get("failure_reason") or "",
        "label": label,
        "secondary_labels": secondary,
        "confidence": cls.get("confidence", report.get("confidence")),
        "outcome": outcome,
        "rule": report.get("rule"),
        **scores(label, secondary, outcome, truth),
        "verdict": verdict,
        "null_table": report.get("null_table"),
        "routing": [x.get("to") for x in (report.get("routing") or [])],
        "spend": {
            "usd": summary.get("llm_cost_usd"),
            "requests": summary.get("llm_turns"),
            "attempts": summary.get("llm_attempts"),
            "tokens": summary.get("tokens_used"),
            "tokens_input": summary.get("tokens_input"),
            "tokens_output": summary.get("tokens_output"),
            "tokens_cache_read": summary.get("tokens_cache_read"),
            "by_role": {
                role: {
                    k: row.get(k)
                    for k in (
                        "requests",
                        "tokens",
                        "reserved_tokens",
                        "calls",
                        "evaluations",
                        "assay_units",
                    )
                }
                for role, row in sorted(by_role.items())
            },
            "evaluations": f"{summary.get('simulator_evals_used')}/"
            f"{summary.get('simulator_evals_total')}",
        },
        "cap": {
            "hit": bool(refusals) or verdict.get("reason") == "model_cap",
            "abstained_on_cap": verdict.get("reason") == "model_cap"
            or str(report.get("rule", "")).endswith("model_cap"),
            "refusals": refusals,
        },
        "decider": summary.get("decider"),
        "model_id": summary.get("model_id"),
        "provider": summary.get("provider"),
        "llm_calls_jsonl": (out / "llm_calls.jsonl").is_file(),
        "frozen": frozen,
        "provenance": {
            k: summary.get(k)
            for k in (
                "templates_sha256",
                "schemas_sha256",
                "tools_sha256",
                "git_commit",
            )
        },
        "observations_sha256": observations_digest(run_dir)
        if (run_dir / "observations").is_dir()
        else None,
        "calls_sha256": digest,
        "calls_lines": n_lines,
    }


# ------------------------------------------------------------------ the driver


def run(*, live: bool, store: Path | None = None, part: str = "0/1") -> None:
    """Run the pilot: live in the approved store, or a dry run in a scratch store.

    Raises:
        SystemExit: Live without the lead's approval, the key or the approved store; a
            dry run without a scratch store, or in the repository or the approved store.
    """
    from tools.p2_live import require_live_approval

    if live:
        if store is not None:
            raise SystemExit("a live run uses the store the approval names; pass no --store")
        store = approved_store()
        # a stopped pilot's run is recorded unfinished before any check that could refuse
        # this start: a file write, no call
        record_stopped_live(store)
        try:
            # the record as a whole, against the configuration the pilot runs and its
            # store: the very checks the runner repeats for every run
            require_live_approval(load_config(), runs_root=store / "runs")
        except ValueError as exc:
            raise SystemExit(f"the pilot is not approved: {exc}") from exc
        if not os.environ.get(KEY_VARIABLE):
            raise SystemExit(f"{KEY_VARIABLE} is not set")
    else:
        if store is None:
            raise SystemExit("a dry run needs a scratch store: pass --store DIR")
        store = store.resolve()
        approved = approved_store()
        if store == approved or approved in store.parents or store in approved.parents:
            raise SystemExit("a dry run never touches the approved store")
        try:
            # every check but the store binding, which the dry run must not satisfy
            require_live_approval(load_config())
        except ValueError as exc:
            raise SystemExit(f"the pilot is not approved: {exc}") from exc
    _runs(store, live=live, part=part)


def _runs(store: Path, *, live: bool, part: str = "0/1") -> None:
    store = store.resolve()
    if store == REPO or REPO in store.parents:
        raise SystemExit("the store must be outside the repository")
    from scripts.p2_rerun import InFlight, append_synced, run_counted, set_aside
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from tools.runner import run_workflow

    i_part, n_part = (int(x) for x in part.split("/"))
    suffix = "" if live else f"_dry.{i_part}"
    results = store / f"results{suffix}.jsonl"
    unfinished = store / f"unfinished{suffix}.jsonl"
    if live and record_stopped_live(store):
        return
    done = settled(store, live=live)
    journal = InFlight(store / f"in_flight{suffix}.jsonl", journals(store, live=live))
    orphans = journal.orphans(done)
    if not live and InFlight.TORN in orphans:
        print("STOP: an in-flight journal line is torn and names no cell; no cell is run.",
              flush=True)  # fmt: skip
        return
    if live and unfinished.is_file() and unfinished.read_text().strip():
        print(f"STOP: {unfinished.name} records an unfinished live run; a rerun or any "
              "further live run needs the lead's approval relayed by the coordinator",
              flush=True)  # fmt: skip
        return
    per_run = float(plan()["caps_per_run"]["max_usd"])
    limit = max_total_usd()
    ledger = store / f"spent_usd{suffix}.json"
    spent = float(json.loads(ledger.read_text())["usd"]) if ledger.is_file() else 0.0
    order = [(c, r) for c in CELLS for r in REPLICATES]
    for k, ((sid, plant_id, tier), rep) in enumerate(order):
        if k % n_part != i_part:
            continue
        cell = (sid, plant_id, tier)
        name = key(cell)
        if (name, rep) in done:
            continue
        approved_cell = {"scenario": sid, "plant": plant_id, "tier": tier, "replicate": rep}
        # gate 1, the lead's approval of this run (and, live, of this store); gate 2, the
        # freeze; both before a redo is set aside, before anything is generated and before
        # any client could exist
        try:
            check_run_approved(approved_cell, (store / "runs") if live else None)
            frozen = h4_frozen(ARM)
        except ValueError as exc:
            print(f"STOP: {name} r{rep} refused before any run: {exc}", flush=True)
            return
        prior = orphans.get((name, rep), [])
        offset = 0  # the journal's attempt number of this run's first attempt, less one
        restart: dict[str, Any] | None = None
        if live and prior:
            # the lead's "B": a run cut off by a restart is set aside and redone once; any
            # other orphan was recorded unfinished by record_stopped_live and never gets here
            if not restart_eligible(store, name, rep, prior):
                print(f"STOP: {name} r{rep} was interrupted again; it is not redone twice",
                      flush=True)  # fmt: skip
                return
            restart = set_aside_restart(store, name, rep, prior[-1], usd=per_run)
            spent += per_run  # the set-aside run's meter died with it: its whole cap
            ledger.write_text(json.dumps({"usd": spent}), encoding="utf-8")
            print(f"RESTART {name} r{rep}: {restart['run_id']} set aside at "
                  f"{restart['set_aside']}; redone once ({RESTART_RULING})",
                  flush=True)  # fmt: skip
            offset, prior = len(prior), []
        if live and spent + per_run > limit:
            print(f"STOP: USD {spent:.3f} spent; one more run could pass {limit:.2f}", flush=True)
            return
        plant = load_plant_config(plant_id)
        scenario = scenario_for(sid, plant)
        run_ids: list[str] = [str(p["run_id"]) for p in prior]

        def attempt(
            n: int,
            cell: tuple[str, str, str] = cell,
            rep: int = rep,
            name: str = name,
            scenario: Any = scenario,
            plant: Any = plant,
            tier: str = tier,
            run_ids: list[str] = run_ids,
            frozen: dict[str, str] = frozen,
            restart: dict[str, Any] | None = restart,
        ) -> dict:
            nonlocal spent
            if n > 1 and not live:  # an offline rerun; a live redo was set aside whole
                set_aside(store / "runs" / run_ids[-1], n - 1)
            art = generate_run(scenario, tier, plant=plant, replicate=rep,
                               runs_root=store / "runs")  # fmt: skip
            run_ids.append(art.run_id)
            run_dir = store / "runs" / art.run_id
            check_store_fresh(run_dir)  # gate 3: a fresh store, before any client
            journal.start(name, rep, n, art.run_id)
            print(f"START {name} r{rep} ({art.run_id}, {'live' if live else 'dry run'})",
                  flush=True)  # fmt: skip
            started = time.perf_counter()
            result = run_workflow(
                art.run_id,
                "p2",
                runs_root=store / "runs",
                scenario=scenario,
                config_path=config_path(),
                live=live,
            )
            journal.finish(name, rep, n, art.run_id, result.as_dict())
            spent += float(result.llm_cost_usd or 0.0)
            ledger.write_text(json.dumps({"usd": spent}), encoding="utf-8")
            record = run_record(cell, rep, list(scenario.truth_label), run_dir, result,
                                time.perf_counter() - started, frozen, live=live)  # fmt: skip
            record["attempt"] = n
            record["restart"] = restart
            reason = model_unreachable(run_dir)
            if reason is not None:  # the lead's "B": never a result, whatever it concluded
                record.update({"unreachable": reason, "finished": False,
                               "error": f"the model could not be reached: {reason}",
                               "failure_reason": "model_unreachable"})  # fmt: skip
            return record

        try:
            done_cell = run_counted(
                lambda n, offset=offset: attempt(n + offset),
                live=live,
                prior=prior,
                is_finished=_finished,
            )
        except ValueError as exc:  # a store that already holds the run, or a refused run
            print(f"STOP: {name} r{rep}: {exc}", flush=True)
            return
        if done_cell.record is None:
            if not live and run_ids:
                set_aside(store / "runs" / run_ids[-1], len(done_cell.attempts))
            failure = {"cell": name, "replicate": rep, **done_cell.failure()}
            last = done_cell.attempts[-1] if done_cell.attempts else {}
            if last.get("unreachable"):
                failure.update({"status": "model_unreachable", "error": last["unreachable"]})
            if restart is not None:
                failure["restart"] = restart
            append_synced(unfinished, json.dumps(failure, sort_keys=True, default=str) + "\n")
            if last.get("unreachable"):
                print(f"STOP: {name} r{rep}: the model could not be reached: "
                      f"{last['unreachable']}; recorded unfinished, never scored",
                      flush=True)  # fmt: skip
            print(f"STOP: {name} r{rep} is unfinished ({failure['status']}); nothing is "
                  f"scored for it. Report it to the coordinator: {failure['attempts']}",
                  flush=True)  # fmt: skip
            return
        line = done_cell.record
        append_synced(results, json.dumps(line, sort_keys=True, default=str) + "\n")
        print(f"DONE {name} r{rep}: {line['outcome']} ({line['rule']}); labels "
              f"{line['label_set']}; USD {line['spend']['usd']} (USD {spent:.3f} so far)"
              + ("; CAP HIT" if line["cap"]["hit"] else ""), flush=True)  # fmt: skip


def _finished(record: dict[str, Any]) -> bool:
    """A run is a result: complete, not pending, the model reached (the lead's "B")."""
    return (
        bool(record.get("completed"))
        and record.get("outcome") != "pending"
        and not record.get("unreachable")
    )


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
    return _cells_in(sorted(store.glob("results_dry.*.jsonl"))
                     + sorted(store.glob("unfinished_dry.*.jsonl")))  # fmt: skip


def journals(store: Path, *, live: bool) -> list[Path]:
    return [store / "in_flight.jsonl"] if live else sorted(store.glob("in_flight_dry.*.jsonl"))


def record_stopped_live(store: Path) -> bool:
    """Record a stopped live pilot's runs unfinished; whether any was found. No call."""
    from scripts.p2_rerun import InFlight, append_synced

    if not (store / "in_flight.jsonl").is_file():
        return False
    orphans = InFlight(store / "in_flight.jsonl").orphans(settled(store, live=True))
    orphans = {
        k: v for k, v in orphans.items() if not restart_eligible(store, k[0], k[1], v)
    }  # a run cut off once by a restart is redone, not recorded (the lead's "B")
    for (cell, rep), prior in orphans.items():
        failure = {"cell": cell, "replicate": rep, "status": "unfinished_live",
                   "attempts": [{"run_id": p["run_id"], "completed": False,
                                 "error": (p.get("summary") or {}).get("error"),
                                 "failure_reason": (p.get("summary") or {}).get("failure_reason"),
                                 "rule": None} for p in prior]}  # fmt: skip
        append_synced(store / "unfinished.jsonl", json.dumps(failure, sort_keys=True) + "\n")
        print(f"STOP: {cell} r{rep} was left unfinished by a stopped pilot; it is recorded "
              "unfinished and not rerun: a live rerun needs the lead's approval relayed "
              "by the coordinator", flush=True)  # fmt: skip
    return bool(orphans)


def restarts(store: Path) -> list[dict[str, Any]]:
    """The restart records of a live store (``restarts.jsonl``), oldest first."""
    from scripts.p2_rerun import read_unfinished

    path = store / "restarts.jsonl"
    return read_unfinished([path]) if path.is_file() else []


def restart_eligible(store: Path, cell: str, rep: int, prior: list[dict[str, Any]]) -> bool:
    """Whether an orphaned live run is redone: cut off once, and never redone before.

    The limit of one (the lead's "B", 12 Nov) is held twice: the journal shows that one
    attempt only, and ``restarts.jsonl`` holds no restart of this run. A second
    interruption fails both; a torn line naming no cell is never redone.
    """
    from scripts.p2_rerun import InFlight

    if (cell, rep) == InFlight.TORN or len(prior) != 1:
        return False
    return not any((x["cell"], int(x["replicate"])) == (cell, rep) for x in restarts(store))


def set_aside_restart(
    store: Path, cell: str, rep: int, prior: dict[str, Any], *, usd: float
) -> dict[str, Any]:
    """Set an interrupted run's directory aside, whole, and record the restart. No call.

    Into ``set_aside/<run id>.restart-N`` (the next free ``N``; never deleted, never
    overwritten); recorded in ``restarts.jsonl`` with the time, the ruling and the USD the
    ledger charges for it.
    """
    from scripts.p2_rerun import append_synced

    run_id = str(prior.get("run_id"))
    src = store / "runs" / run_id
    dest: Path | None = None
    calls = _model_calls(src)
    if src.is_dir():
        (store / "set_aside").mkdir(exist_ok=True)
        n = 1
        while (store / "set_aside" / f"{run_id}.restart-{n}").exists():
            n += 1
        dest = store / "set_aside" / f"{run_id}.restart-{n}"
        shutil.move(str(src), str(dest))
    entry = {
        "cell": cell,
        "replicate": rep,
        "run_id": run_id,
        "attempt": prior.get("attempt"),
        "set_aside": str(dest) if dest else None,
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "ruling": RESTART_RULING,
        "usd_charged": usd,
        "model_calls": len(calls),
        "model_errors": sum(bool(x.get("error")) for x in calls),
    }
    append_synced(store / "restarts.jsonl", json.dumps(entry, sort_keys=True) + "\n")
    return entry


# ------------------------------------------------------------------ the report


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The pilot's table: the scores, the spend in total and per run, the caps hit."""
    scored = [x for x in rows if x["finished"] and x["outcome"] not in ("abstain", "pending")]
    usd = [float(x["spend"]["usd"] or 0.0) for x in rows]
    return {
        "what": "the agent arm live on the H4 cells (the lead's approval of 2026-11-11)",
        "descriptive_only": True,
        "runs": len(rows),
        "finished": sum(x["finished"] for x in rows),
        "abstained": sum(x["outcome"] == "abstain" for x in rows),
        "primary_in_truth": f"{sum(x['primary_in_truth'] for x in scored)} of {len(scored)} scored",
        "attribution_exact": f"{sum(x['attribution_exact'] for x in scored)} of {len(scored)} "
        "scored",
        "both_faults_named": sum(len(x["label_set"]) == 2 for x in rows),
        "cap_hits": [f"{x['cell']} r{x['replicate']}" for x in rows if x["cap"]["hit"]],
        "usd_total": round(sum(usd), 4),
        "usd_per_run": {f"{x['cell']} r{x['replicate']}": x["spend"]["usd"] for x in rows},
        "requests_total": sum(int(x["spend"]["requests"] or 0) for x in rows),
        "tokens_total": sum(int(x["spend"]["tokens"] or 0) for x in rows),
        "wall_min_total": round(sum(float(x["wall_s"]) for x in rows) / 60.0, 1),
    }


def report(store: Path | None = None, *, live: bool = True) -> dict[str, Any]:
    """``reports/p2_agents_pilot/``: ``cells.json``, ``summary.md`` and each run's records."""
    from scripts.p2_rerun import InFlight, read_unfinished, stopped

    store = (approved_store() if store is None else Path(store)).resolve()
    suffix = "" if live else "_dry.*"
    results = [store / "results.jsonl"] if live else sorted(store.glob("results_dry.*.jsonl"))
    rows = read_unfinished([p for p in results if p.is_file()])
    rows.sort(key=lambda x: (x["cell"], x["replicate"]))
    out = summarise(rows)
    out["cells"] = rows
    unfinished = (
        [store / "unfinished.jsonl"] if live else sorted(store.glob(f"unfinished{suffix}.jsonl"))
    )
    out["unfinished"] = read_unfinished([p for p in unfinished if p.is_file()])
    paths = journals(store, live=live)
    if any(p.is_file() for p in paths):
        out["unfinished"] += stopped(InFlight(paths[0], paths).orphans(settled(store, live=live)))
    out["restarts"] = restarts(store) if live else []
    dest = REPORT_DIR if live else REPORT_DIR / "dry_run"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "cells.json").write_text(
        json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8"
    )
    for x in rows:
        run_dir = store / "runs" / str(x["run_id"])
        target = (
            dest / "runs" / f"{x['cell'].replace(' ', '-').replace('/', '-')}-r{x['replicate']}"
        )
        target.mkdir(parents=True, exist_ok=True)
        for rel, name in RUN_RECORDS:
            src = run_dir / rel
            if src.is_file():
                shutil.copy2(src, target / name)
    lines = [
        "# The agent arm live on the H4 cells (the lead's approval of 2026-11-11)",
        "",
        "Descriptive only (design note §7). The scores are eval's: `primary in truth`, the",
        "label names one of the two faults; `exact`, the label set (the label and the",
        "secondary labels) equals the truth. An abstaining or unfinished run scores neither.",
        f"Runs {out['runs']}, finished {out['finished']}, abstained {out['abstained']}; primary in "
        f"truth {out['primary_in_truth']}; exact {out['attribution_exact']}; both faults named in "
        f"{out['both_faults_named']}; caps hit: {', '.join(out['cap_hits']) or 'none'}.",
        f"Spend: USD {out['usd_total']}, {out['requests_total']} requests, "
        f"{out['tokens_total']} tokens, {out['wall_min_total']} min in all.",
        *([""] if out["unfinished"] else []),
        *[f"Unfinished (not scored): {u.get('cell')} r{u.get('replicate', 0)}, {u.get('status')}: "
          f"{u.get('attempts')}" for u in out["unfinished"]],
        *[f"Restarted ({r['ruling']}): {r['cell']} r{r['replicate']}, {r['run_id']} set aside "
          f"at {r['set_aside']} on {r['time']}, USD {r['usd_charged']} charged"
          for r in out["restarts"]],
        "",
        "| cell | seed | truth | outcome | label set | confidence | primary in truth | exact "
        "| rule | USD | requests | tokens | cap hit | wall min |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for x in rows:
        s = x["spend"]
        lines.append(
            f"| {x['cell']} | {x['replicate']} | {','.join(x['truth'])} | {x['outcome']} | "
            f"{','.join(x['label_set']) or '-'} | {x['confidence']} | {x['primary_in_truth']} | "
            f"{x['attribution_exact']} | {x['rule']} | {s['usd']} | {s['requests']} | "
            f"{s['tokens']} | {x['cap']['hit']} | {round(float(x['wall_s']) / 60.0, 1)} |"
        )
    (dest / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p_plan = sub.add_parser("plan", help="what would run, at what caps; no call, no store")
    p_run = sub.add_parser("run", help="the pilot: --live in the approved store, or --dry-run")
    mode = p_run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="the live pilot, approved store only")
    mode.add_argument("--dry-run", action="store_true", help="every check, the offline model")
    p_run.add_argument("--store", type=Path, default=None, help="the dry run's scratch store")
    p_run.add_argument("--part", default="0/1", help="dry runs only: i/n")
    p_rep = sub.add_parser("report", help="write reports/p2_agents_pilot/")
    p_rep.add_argument("--store", type=Path, default=None)
    p_rep.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "plan":
        print(json.dumps(plan(), indent=1))
    elif args.action == "run":
        if args.live and args.part != "0/1":
            raise SystemExit("the live pilot runs whole: one process, no --part")
        run(live=bool(args.live), store=args.store, part=args.part)
    else:
        report(args.store, live=not args.dry_run)
    del p_plan
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
