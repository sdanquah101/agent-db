"""The P1 development-pilot report: per-cell rows, the CSVs and the markdown tables.

Usage::

    python -m scripts.p1_pilot_report <repo> <spec.json> [--csv-only]

``spec.json`` is ``{"versions": [{"label", "results", "store", "sha", "csv",
"summaries", "brief_sha"?}, ...]}``: for each arm, the driver's results file
(``scripts/p1_pilot.py``), its store, the prompt hash its rows must carry, the CSV they
go to and the directory their summaries are copied to. Versions naming one CSV share
it. Every row is checked against its version's prompt hash (and brief hash); a mismatch
stops the report.

Development diagnostics only: never a sweep score, never set beside P0. The columns
read from the run's own record, not from state self-reports (the coordinator's answers
of 2026-09-28): the harness refusals are counted in the gateway's verbatim log; the
evidence behind each label is the accepted ``record_evidence`` items and how many of
them cite a localised pattern. A failed run (``run_failed`` in the summary, with its
``failure_reason``; ``tools/runner.py::FAILURE_REASONS``) is a miss in every label
total and its credit columns are blank, so nobody credits the interim placeholder by
reading the raw columns (the coordinator's review of ``cc256fd``). Rows recorded before
the summary carried those fields are backfilled by the runner's own classifier from the
stored record.
"""

from __future__ import annotations

import csv
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.llm import read_transcript, rebuild_requests
from tools.runner import annotations_of, failure_reason, llm_log_of
from tools.server import OUTPUTS_DIR

FIELDS = [
    "prompt_version", "model", "prompt_sha256", "brief_sha256", "git_commit", "scenario_id",
    "plant", "tier", "run_id", "completed", "run_failed", "failure_reason", "label",
    "secondary_labels", "truth_label", "primary_matches_truth", "truth_among_labels",
    "attribution_exact", "claims", "claims_unsupported", "invalid_actions",
    "harness_refusals", "abstention_extra", "false_kinetic_update", "false_kinetic_drift",
    "evidence_by_label", "labels_without_localised_evidence", "simulator_evals_used",
    "simulator_evals_total", "wall_min", "wall_clock_min_total", "llm_turns", "tokens_used",
    "llm_cost_usd",
]  # fmt: skip

# keys that localise a pattern in time, or measure a quantity directly
LOCALISING_KEYS = {
    "step_z", "step_day", "early_bias_z", "late_bias_z", "start_d", "end_d",
    "slope_per_d", "event_missing_ratio", "assay", "disagreement_z",
}  # fmt: skip


def run_dir(store: Path, run_id: str, output_name: str = "p1") -> Path:
    """The workflow output directory of a run in ``store`` (the summary's ``output_name``)."""
    return store / "runs" / run_id / OUTPUTS_DIR / output_name


def refusals_received(out: Path) -> int:
    """Refusal results that reached the agent, from the last request in the verbatim log."""
    try:
        requests = rebuild_requests(read_transcript(out / "llm_calls.jsonl"))
    except OSError:
        return 0
    if not requests:
        return 0
    n = 0
    for message in requests[-1]["messages"]:
        if message["role"] != "user" or not isinstance(message["content"], list):
            continue
        for block in message["content"]:
            if block.get("type") != "tool_result" or not block.get("is_error"):
                continue
            try:
                payload = json.loads(block["content"])
            except (TypeError, ValueError):
                continue
            if str(payload.get("error", "")).startswith("refused:"):
                n += 1
    return n


def _localised(item: dict) -> bool:
    values = item.get("values") or {}
    return bool(LOCALISING_KEYS & set(values)) or "sensor" in values or "channel" in values


def _timed(item: dict) -> bool:
    return bool(LOCALISING_KEYS & set(item.get("values") or {}))


def evidence_by_label(out: Path) -> tuple[str, int]:
    """``label n (t a, c b)`` for each label given, and how many labels lack a localised item.

    n: accepted evidence items for the label; t: items citing a time-localising key or a
    direct measurement; c: the rest that are tagged to a sensor or channel (localised in
    channel only). A label with t + c = 0 rests on whole-record figures only.
    """
    try:
        state = json.loads((out / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", 0
    final = state.get("final") or {}
    labels = [x for x in [final.get("label"), *final.get("secondary_labels", [])] if x]
    items = state.get("evidence") or []
    if not items:  # older states keep the items under the classification
        items = (state.get("classification") or {}).get("evidence") or []
    parts, bare = [], 0
    for label in labels:
        mine = [i for i in items if i.get("label") == label]
        t = sum(_timed(i) for i in mine)
        c = sum(_localised(i) and not _timed(i) for i in mine)
        bare += t + c == 0
        parts.append(f"{label} {len(mine)} (t {t}, c {c})")
    return "; ".join(parts), bare


def failure_of(summary: dict, out: Path) -> tuple[bool, str]:
    """``(run_failed, failure_reason)`` from the summary; backfilled from the record if absent."""
    if "run_failed" in summary:
        return bool(summary["run_failed"]), str(summary.get("failure_reason") or "")
    failed = not summary.get("completed")
    if not failed:
        return False, ""
    return True, failure_reason(
        str(summary.get("error") or ""), annotations_of(out), llm_log_of(out)
    )


def row_of(version: dict, r: dict) -> dict:
    """One CSV row from a driver's results line (its summary and evaluator row)."""
    base = {
        "prompt_version": version["label"],
        "scenario_id": r["scenario_id"],
        "plant": r["plant"],
        "tier": r["tier"],
        "run_id": r.get("run_id"),
    }
    if "error" in r:
        return {**base, "completed": False, "label": "ERROR " + r["error"][:120]}
    s, c = r["summary"], r["score"]
    if s["prompt_sha256"] != version["sha"]:
        raise SystemExit(f"{version['label']}: {base} ran prompt {s['prompt_sha256']}")
    if (s.get("brief_sha256") or "") != version.get("brief_sha", ""):
        raise SystemExit(f"{version['label']}: {base} ran brief {s.get('brief_sha256')!r}")
    truth = c.get("truth_label")
    truth = list(truth) if isinstance(truth, list | tuple) else [str(truth)]
    labels = [s.get("label"), *s.get("secondary_labels", [])]
    out = run_dir(Path(version["store"]), r["run_id"], s.get("output_name") or "p1")
    failed, reason = failure_of(s, out)
    s["run_failed"], s["failure_reason"] = failed, reason  # the summary as copied carries them
    if failed:  # no conclusion: the state is the harness's interim placeholder
        ev, bare = "(no conclusion; the interim state's placeholder)", 0
    else:
        ev, bare = evidence_by_label(out)
    return {
        **base,
        "model": s.get("model_id") or "",
        "prompt_sha256": s["prompt_sha256"],
        "brief_sha256": s.get("brief_sha256") or "",
        "git_commit": s["git_commit"],
        "completed": s.get("completed"),
        "run_failed": failed,
        "failure_reason": reason,
        "label": s.get("label"),
        "secondary_labels": "+".join(s.get("secondary_labels", [])),
        "truth_label": "+".join(truth),
        # a failed run's credit columns are blank (the review of cc256fd)
        "primary_matches_truth": "" if failed else s.get("label") in truth,
        "truth_among_labels": "" if failed else all(t in labels for t in truth),
        "attribution_exact": "" if failed else bool(c.get("attribution_exact")),
        "claims": c.get("claims"),
        "claims_unsupported": c.get("claims_unsupported"),
        "invalid_actions": c.get("invalid_actions"),
        "harness_refusals": refusals_received(out),
        "abstention_extra": c.get("abstention_extra"),
        "false_kinetic_update": c.get("false_kinetic_update"),
        "false_kinetic_drift": c.get("false_kinetic_drift"),
        "evidence_by_label": ev,
        "labels_without_localised_evidence": bare,
        "simulator_evals_used": s.get("simulator_evals_used"),
        "simulator_evals_total": s.get("simulator_evals_total"),
        "wall_min": round((s.get("wall_s") or 0) / 60, 1),
        "wall_clock_min_total": s.get("wall_clock_min_total"),
        "llm_turns": s.get("llm_turns"),
        "tokens_used": s.get("tokens_used"),
        "llm_cost_usd": s.get("llm_cost_usd"),
    }


def rows_of(version: dict) -> list[dict]:
    """Every row of one arm, sorted by cell; its summaries copied where the spec says."""
    path = Path(version["results"])
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            rows.append(row_of(version, r))
            if version.get("summaries") and "summary" in r:
                d = Path(version["summaries"])
                d.mkdir(parents=True, exist_ok=True)
                name = f"{version['label']}_{r['scenario_id']}_{r['plant']}{r['tier']}.json"
                (d / name).write_text(
                    json.dumps(r["summary"], indent=1, sort_keys=True) + "\n", encoding="utf-8"
                )
    rows.sort(key=lambda x: (x["scenario_id"], x["plant"], x["tier"]))
    return rows


def totals(rows: list[dict]) -> dict:
    """The arm's totals; a failed run is a miss in every label row."""
    ok = [r for r in rows if "truth_label" in r]
    n = len(ok)
    done = [r for r in ok if not r["run_failed"]]
    return {
        "cells": n,
        "failed runs (no conclusion)": n - len(done),
        "  of which killed": sum(r["failure_reason"] == "killed" for r in ok),
        "  of which connection": sum(r["failure_reason"] == "connection" for r in ok),
        "  of which refusal": sum(r["failure_reason"] == "refusal" for r in ok),
        "exact attribution": sum(r["attribution_exact"] for r in done),
        "primary label = truth": sum(r["primary_matches_truth"] for r in done),
        "truth among the labels given": sum(r["truth_among_labels"] for r in done),
        "`none` reached on `none` cells": sum(
            r["label"] == "none" for r in done if r["truth_label"] == "none"
        ),
        "labels given": sum(
            1 + len([x for x in r["secondary_labels"].split("+") if x]) for r in done
        ),
        "labels without localised evidence": sum(
            r["labels_without_localised_evidence"] for r in ok
        ),
        "unsupported claims": sum(r["claims_unsupported"] or 0 for r in ok),
        "invalid actions (evaluator)": sum(r["invalid_actions"] or 0 for r in ok),
        "harness refusals (verbatim log)": sum(r["harness_refusals"] for r in ok),
        "extra abstentions": sum(r["abstention_extra"] or 0 for r in ok),
        "kinetic-update errors": sum(bool(r["false_kinetic_update"]) for r in ok),
        "kinetic drift (cells)": sum(bool(r["false_kinetic_drift"]) for r in ok),
        "simulator evaluations": sum(r["simulator_evals_used"] or 0 for r in ok),
        "wall clock, min": round(sum(r["wall_min"] for r in ok), 1),
        "turns": sum(r["llm_turns"] or 0 for r in ok),
        "tokens": sum(r["tokens_used"] or 0 for r in ok),
        "cost at the arm's declared rates, USD": round(sum(r["llm_cost_usd"] or 0 for r in ok), 3),
    }  # fmt: skip


COLS: list[tuple[str, Callable[[dict], Any]]] = [
    ("cell", lambda r: f"{r['scenario_id']} {r['plant']}/{r['tier']}"),
    ("labels (truth)", lambda r: (f"FAILED ({r['failure_reason']}), no conclusion; placeholder "
                                   if r["run_failed"] else "")
     + "+".join(x for x in [r["label"], r.get("secondary_labels")] if x)
     + f" ({r.get('truth_label')})"),
    ("evidence per label: n (t, c)", lambda r: r.get("evidence_by_label")),
    ("unsupp.", lambda r: f"{r.get('claims_unsupported')}/{r.get('claims')}"),
    ("invalid", lambda r: r.get("invalid_actions")),
    ("refused", lambda r: r.get("harness_refusals")),
    ("extra abst.", lambda r: r.get("abstention_extra")),
    ("kin. err.", lambda r: r.get("false_kinetic_update")),
    ("kin. drift", lambda r: r.get("false_kinetic_drift")),
    ("evals", lambda r: f"{r.get('simulator_evals_used')}/{r.get('simulator_evals_total')}"),
    ("wall min", lambda r: f"{r.get('wall_min')}/{r.get('wall_clock_min_total')}"),
    ("turns", lambda r: r.get("llm_turns")),
    ("tokens", lambda r: r.get("tokens_used")),
    ("USD", lambda r: r.get("llm_cost_usd")),
]  # fmt: skip


def markdown(rows: list[dict]) -> str:
    """The per-cell table of one arm."""
    lines = ["| " + " | ".join(c for c, _ in COLS) + " |", "|" + "---|" * len(COLS)]
    for r in rows:
        if "truth_label" not in r:
            lines.append(f"| {r['scenario_id']} {r['plant']}/{r['tier']} | {r['label']} |")
            continue
        lines.append("| " + " | ".join(str(f(r)) for _, f in COLS) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Write the CSVs; print the per-arm tables and the totals with every pairwise difference."""
    args = list(sys.argv[1:] if argv is None else argv)
    repo, spec = Path(args[0]), json.loads(Path(args[1]).read_text(encoding="utf-8"))
    all_rows: dict[str, list[dict]] = {}
    by_csv: dict[str, list[dict]] = {}
    for v in spec["versions"]:
        rows = rows_of(v)
        all_rows[v["label"]] = rows
        if v.get("csv"):
            by_csv.setdefault(v["csv"], []).extend(rows)
    for name, rows in by_csv.items():
        with open(repo / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    if "--csv-only" in args:
        return 0
    for v in spec["versions"]:
        rows = all_rows[v["label"]]
        commits = sorted({r["git_commit"][:7] for r in rows if r.get("git_commit")})
        print(f"**{v['label']}** (prompt `{v['sha'][:8]}…`, runs at {commits})\n")
        print(markdown(rows) + "\n")
    labels = [v["label"] for v in spec["versions"]]
    tots = {k: totals(all_rows[k]) for k in labels}
    pairs = [(b, a) for i, a in enumerate(labels) for b in labels[:i]]
    head = labels + [f"{a} - {b}" for b, a in pairs]
    print("| total | " + " | ".join(head) + " |\n|---|" + "---|" * len(head))
    for key in tots[labels[0]]:
        vals = [str(tots[k][key]) for k in labels]
        diffs = [f"{round(tots[a][key] - tots[b][key], 3):+}" for b, a in pairs]
        print(f"| {key} | " + " | ".join(vals + diffs) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
