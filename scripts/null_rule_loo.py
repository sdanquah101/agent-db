"""Leave-one-out false-alarm rates of P2's null rule on the declared background's clean record.

``docs/p2_design.md`` §4 proposes the null rule P2's verifier applies with the declared
background (decision 1 of 2026-09-30; the band rule of the lead's ruling of 2026-09-30).
Its components are chosen by how often they fire on a **clean** run, measured here on the
committed record ``reports/background/runs.jsonl`` and nothing else: each clean run is
judged against the min-max envelope of the other runs of its (plant, tier), exactly as a
new clean run would be judged against the published one. No development cell, no
scenario and no run outside the clean record is read.

Run ``python -m scripts.null_rule_loo`` to regenerate
``reports/background/null_rule_loo.json``; a test regenerates it and compares.

A note on the rate. For **one** statistic, a run outside the envelope of N - 1
exchangeable others happens with probability 2 / N, against 2 / (N + 1) for the
published envelope of N. That bound is per statistic, not for the rule: a component with
an "every other channel inside" clause (NS) can fire more often on a wider envelope, so
these leave-one-out rates are estimates, not upper bounds. They are also a floor for any
cell that is not exchangeable with the clean background.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from scripts import declared_background as bg

OUT_FILE = bg.REPORT_DIR / "null_rule_loo.json"
BALANCE = ("cod_closure", "cod_closure_worst", "n_cod_inadmissible")
NEVER_IN_OBJECTIVE = ("temperature",)
"""A channel no calibratable parameter moves (P0's rule): read, never a null-case failure."""

Side = int  # -1 below the envelope, 0 inside, +1 above
Placement = dict[str, Side]


def statistics(record: dict[str, Any]) -> dict[str, float | None]:
    """The ruled statistics of one run record, by the placement's names."""
    b = record["balance"]
    out: dict[str, float | None] = {
        "cod_closure": b["cod_closure_mean"],
        "cod_closure_worst": bg.worst_window(record),
        "n_cod_inadmissible": b["n_cod_inadmissible"] if b["n_cod_evaluable"] else None,
    }
    for name, ch in record["channels"].items():
        for where in ("at_defaults", "after_fit"):
            for stat in ("mean_z", "rms_z"):
                out[f"{name}.{where}.{stat}"] = ch[where][stat]
    return out


def place(value: float, lo: float, hi: float) -> Side:
    """The min-max envelope exactly, no margin: -1 below, +1 above, 0 inside."""
    return -1 if value < lo else (1 if value > hi else 0)


def placement(record: dict[str, Any], others: Sequence[dict[str, Any]]) -> Placement:
    """Each statistic of ``record`` against the envelope of ``others``."""
    mine, theirs = statistics(record), [statistics(r) for r in others]
    out: Placement = {}
    for key, value in mine.items():
        seen = [t[key] for t in theirs if t.get(key) is not None]
        if value is None or not seen:
            continue
        out[key] = place(float(value), min(seen), max(seen))
    return out


def channels(p: Placement) -> list[str]:
    """The channels a placement judges, objective channels only."""
    names = {k.split(".", 1)[0] for k in p if "." in k}
    return sorted(n for n in names if n not in NEVER_IN_OBJECTIVE)


def channel_fails(p: Placement, name: str) -> bool:
    """One channel's null case failed.

    It is biased at the defaults and after the fit, on the same side, and more scattered
    after the fit than any clean run.

    A rise in scatter alone (``rms_z`` with the means inside) is not a failure: more noise
    or more gaps than declared is the ladder's Level 1, whose truth is ``none``.
    """
    after = p.get(f"{name}.after_fit.mean_z", 0)
    return (
        after != 0
        and after == p.get(f"{name}.at_defaults.mean_z", 0)
        and p.get(f"{name}.after_fit.rms_z", 0) == 1
    )


def n_bal(p: Placement) -> bool:
    """NB, the balance's null case failed.

    The mean closure and the worst window are outside on the same side, or there are more
    inadmissible windows than on any clean run.
    """
    mean = p.get("cod_closure", 0)
    return (mean != 0 and mean == p.get("cod_closure_worst", 0)) or p.get(
        "n_cod_inadmissible", 0
    ) == 1


def n_multi(p: Placement) -> bool:
    """NM: two or more channels' null cases failed."""
    return sum(channel_fails(p, c) for c in channels(p)) >= 2


def n_single(p: Placement) -> bool:
    """NS, one channel's null case failed alone.

    Exactly one channel failed, and every other channel's after-fit mean is inside.
    """
    failed = [c for c in channels(p) if channel_fails(p, c)]
    if len(failed) != 1:
        return False
    return all(p.get(f"{c}.after_fit.mean_z", 0) == 0 for c in channels(p) if c != failed[0])


RULES: dict[str, Callable[[Placement], bool]] = {
    "NB": n_bal,
    "NM": n_multi,
    "NS": n_single,
    "null_rejected": lambda p: n_bal(p) or n_multi(p) or n_single(p),
    # the rules the design rejects, measured for the record
    "any_statistic_outside": lambda p: any(v != 0 for v in p.values()),
    "any_channel_after_fit_mean_outside": lambda p: any(
        p.get(f"{c}.after_fit.mean_z", 0) != 0 for c in channels(p)
    ),
    "any_balance_statistic_outside": lambda p: any(p.get(k, 0) != 0 for k in BALANCE),
}


def leave_one_out(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Every rule's false-alarm count on the clean record, per (plant, tier) and overall."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in sorted(records, key=lambda r: r["key"]):
        groups[(r["plant"], r["tier"])].append(r)
    per: dict[str, dict[str, int]] = {name: {} for name in RULES}
    runs: dict[str, int] = {}
    stat_hits: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (plant, tier), rs in sorted(groups.items()):
        key = f"{plant}/{tier}"
        runs[key] = len(rs)
        for name in RULES:
            per[name][key] = 0
        for i, r in enumerate(rs):
            p = placement(r, rs[:i] + rs[i + 1 :])
            for name, rule in RULES.items():
                per[name][key] += int(rule(p))
            for stat, side in p.items():
                kind = stat if "." not in stat else stat.split(".", 1)[1]
                stat_hits[kind][0] += int(side != 0)
                stat_hits[kind][1] += 1
    total = sum(runs.values())
    return {
        "what": "leave-one-out false alarms of P2's null rule on the clean record "
        "(docs/p2_design.md §4); each clean run against the min-max envelope of the "
        "other runs of its plant and tier, no margin",
        "record": "reports/background/runs.jsonl",
        "n_runs": total,
        "runs": runs,
        "rules": {
            name: {
                "false_alarms": sum(counts.values()),
                "rate": round(sum(counts.values()) / total, 4),
                "per_plant_tier": counts,
            }
            for name, counts in per.items()
        },
        "per_statistic": {
            kind: {"outside": h, "n": n, "rate": round(h / n, 4)}
            for kind, (h, n) in sorted(stat_hits.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT_FILE)
    args = parser.parse_args(argv)
    result = leave_one_out(bg.read_record())
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    for name, r in result["rules"].items():
        print(f"{name:36s} {r['false_alarms']:3d}/{result['n_runs']} = {r['rate']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
