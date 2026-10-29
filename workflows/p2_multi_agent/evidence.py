"""The evidence module (``docs/p2_agents_design.md`` §2): null rule, signatures, admission.

Shared by both arms. Staged into the jail with its package (``tools/sandbox.py``, the
lead's option A of 2026-10-26): the entry ``workflow.py`` imports it by the same dotted
name as the host, ``workflows.p2_multi_agent.evidence``. Three things live here, each
moved from ``workflow.py`` as a unit with no logic change:

* **the null rule** (§4 of ``docs/p2_design.md``, frozen 2026-10-07): the placement
  helpers, NB / NM / NS, the failed channels, :func:`null_table`. Written in code rather
  than imported from ``scripts/null_rule_loo.py`` because the jail cannot reach
  ``scripts/``; ``tests/test_p2_workflow.py`` pins every count of
  ``reports/background/null_rule_loo.json`` and the four §4.5 outcomes to these functions;
* **the signatures** (the design note §2: the S1 table, the onset test, the feed covariate,
  early/late, the change points, R3, inhibition): numbers with their thresholds, never
  verdicts;
* **the admission**: :func:`admit`, the procedural arm's rule, frozen on 2026-10-07
  (``docs/p2_design.md`` §4.4) and moved here **verbatim** (a test pins its source to the
  frozen digest); :func:`admit_agent`, the agent arm's, which equals :func:`admit` on every
  label but ``structural`` and carries the amended ``structural`` case (docs/decisions.md,
  2026-10-25, Q13 and Q14) through :func:`structural_case`; :func:`admissible_alternative`
  is the code check of a verdict's alternative.

Rule 1: nothing here reads the truth store, and nothing here imports beyond the standard
library (a test pins the imports).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

NEVER_IN_OBJECTIVE = ("temperature",)
"""A channel no calibratable parameter moves (P0's rule): placed and shown, never failed."""
BALANCE_STATS = ("cod_closure", "cod_closure_worst", "n_cod_inadmissible")


# ------------------------------------------------------------------ the null rule (§4)
# The frozen rule (docs/decisions.md, 2026-10-07), written again here because the jail
# cannot import scripts/null_rule_loo.py; tests/test_p2_workflow.py pins every count of
# reports/background/null_rule_loo.json and the four §4.5 outcomes to these functions.

Placement = dict[str, int]
"""Statistic -> -1 below the envelope, 0 inside, +1 above."""


def place(value: float, lo: float, hi: float) -> int:
    """The min-max envelope exactly, no margin."""
    return -1 if value < lo else (1 if value > hi else 0)


def worst_window(windows: Sequence[float | None]) -> float | None:
    """The closure of the window with the largest |closure|, sign kept."""
    cod = [float(c) for c in windows if c is not None]
    return max(cod, key=abs) if cod else None


def record_statistics(record: dict[str, Any]) -> dict[str, float | None]:
    """The ruled statistics of one reference-fit record, by the placement's names."""
    b = record["balance"]
    out: dict[str, float | None] = {
        "cod_closure": b["cod_closure_mean"],
        "cod_closure_worst": worst_window(b.get("cod_closure_windows", [])),
        "n_cod_inadmissible": b["n_cod_inadmissible"] if b["n_cod_evaluable"] else None,
    }
    for name, ch in record["channels"].items():
        for where in ("at_defaults", "after_fit"):
            for stat in ("mean_z", "rms_z"):
                out[f"{name}.{where}.{stat}"] = ch[where][stat]
    return out


def envelope_placement(record: dict[str, Any], others: Sequence[dict[str, Any]]) -> Placement:
    """Each statistic of ``record`` against the min-max envelope of ``others``."""
    mine = record_statistics(record)
    theirs = [record_statistics(r) for r in others]
    out: Placement = {}
    for key, value in mine.items():
        seen = [t[key] for t in theirs if t.get(key) is not None]
        if value is None or not seen:
            continue
        out[key] = place(float(value), min(seen), max(seen))
    return out


def band_envelopes(band: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """The published band (the tool's output, as JSON) as statistic -> (min, max)."""
    out: dict[str, tuple[float, float]] = {}
    for key in BALANCE_STATS:
        stat = band.get(key)
        if stat is not None:
            out[key] = (float(stat["min"]), float(stat["max"]))
    for name, ch in band.get("channels", {}).items():
        for where in ("at_defaults", "after_fit"):
            for stat in ("mean_z", "rms_z"):
                s = ch[where][stat]
                out[f"{name}.{where}.{stat}"] = (float(s["min"]), float(s["max"]))
    return out


def band_placement(stats: dict[str, float | None], band: dict[str, Any]) -> Placement:
    """Each statistic against the band exactly as published (the verifier's S7)."""
    env = band_envelopes(band)
    return {
        key: place(float(value), *env[key])
        for key, value in stats.items()
        if value is not None and key in env
    }


def channels_of(p: Placement) -> list[str]:
    """The channels a placement judges, objective channels only."""
    names = {k.split(".", 1)[0] for k in p if "." in k}
    return sorted(n for n in names if n not in NEVER_IN_OBJECTIVE)


def channel_fails(p: Placement, name: str) -> bool:
    """One channel's null case failed (§4.2).

    It is biased on the same side at the defaults and after the fit, and more scattered
    after the fit than any clean run.
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


def failed_channels(p: Placement) -> list[str]:
    """The channels whose null case failed."""
    return [c for c in channels_of(p) if channel_fails(p, c)]


def n_multi(p: Placement) -> bool:
    """NM: two or more channels' null cases failed."""
    return len(failed_channels(p)) >= 2


def n_single(p: Placement) -> bool:
    """NS: exactly one channel failed, every other channel's after-fit mean inside."""
    failed = failed_channels(p)
    if len(failed) != 1:
        return False
    return all(p.get(f"{c}.after_fit.mean_z", 0) == 0 for c in channels_of(p) if c != failed[0])


def null_partial(p: Placement) -> bool:
    """The channel-level gap read as ``none`` by design (§4.2; the review's R3).

    Exactly one channel failed and another channel's after-fit mean is outside without a
    full failure, so neither NS nor NM fires for the channels. It is a statement about
    the channels only: it can co-occur with NB, which is judged on its own.
    """
    failed = failed_channels(p)
    if len(failed) != 1:
        return False
    return any(p.get(f"{c}.after_fit.mean_z", 0) != 0 for c in channels_of(p) if c != failed[0])


def null_rejected(p: Placement) -> bool:
    """The null is rejected when NB, NM or NS fails."""
    return n_bal(p) or n_multi(p) or n_single(p)


def null_table(p: Placement) -> dict[str, Any]:
    """The verifier's null table: the components, the failed channels, the gap."""
    return {
        "placement": dict(sorted(p.items())),
        "n_statistics": len(p),
        "n_outside": sum(1 for v in p.values() if v != 0),
        "NB": n_bal(p),
        "NM": n_multi(p),
        "NS": n_single(p),
        "failed_channels": failed_channels(p),
        "null_partial": null_partial(p),
        "null_rejected": null_rejected(p),
    }


# ------------------------------------------------------------------ the signatures (code)


def nb_side(p: Placement) -> int:
    """The side NB failed on, which the onset test dates: +1 above, -1 below, 0 none.

    - NB not failed: 0 (there is nothing to date).
    - The mean closure and the worst window outside on one side: that side.
    - NB failed only on the inadmissible count: the worst window's side if it is outside,
      else the mean closure's if it is outside, else 0. An inadmissible window can lie on
      either side, so no side is assumed; with 0 the onset test cannot pass.
    """
    if not n_bal(p):
        return 0
    mean, worst = int(p.get("cod_closure", 0)), int(p.get("cod_closure_worst", 0))
    if mean != 0 and mean == worst:
        return mean
    return worst or mean


def onset_test(
    windows: Sequence[dict[str, Any]],
    envelope: tuple[float, float],
    side: int,
    onset_day: float | None,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """The dated-onset test (§2.3; the re-reviews' N1 and R1), on per-window closures.

    Passes only when, about ``onset_day``:
    - at least ``min_windows_before`` evaluable windows end on or before it, and every one
      of them is inside the band's per-window envelope; and
    - at least ``min_windows_after`` evaluable windows start on or after it, and (with
      ``every_window_after``) **every** one of them is outside on the side NB failed.

    A uniform offset (outside in every window) has no window inside before any day, so it
    never passes, and an onset at day 0 has no window before it.
    """
    out = {"onset_day": onset_day, "passes": False, "code": "no_onset"}
    if onset_day is None:
        return out
    if side not in (-1, 1):
        return {**out, "code": "no_side"}
    ev = [w for w in windows if w.get("closure") is not None]
    before = [w for w in ev if float(w["end"]) <= float(onset_day) + 1e-9]
    after = [w for w in ev if float(w["start"]) >= float(onset_day) - 1e-9]
    lo, hi = envelope
    if len(before) < int(cfg["min_windows_before"]):
        return {**out, "code": "too_few_windows_before"}
    if any(place(float(w["closure"]), lo, hi) != 0 for w in before):
        return {**out, "code": "outside_before"}
    sides = [place(float(w["closure"]), lo, hi) for w in after]
    hits = sum(1 for s in sides if s == side)
    if hits < int(cfg["min_windows_after"]):
        return {**out, "code": "too_few_outside_after"}
    if cfg["every_window_after"] and hits != len(sides):
        return {**out, "code": "inside_after"}
    return {**out, "passes": True, "code": "dated_onset"}


def candidate_onsets(
    windows: Sequence[dict[str, Any]],
    envelope: tuple[float, float],
    side: int,
    cfg: dict[str, Any],
) -> list[float]:
    """Every window boundary that would pass the onset test (the re-review's R1 report)."""
    days = sorted({float(w["start"]) for w in windows} | {float(w["end"]) for w in windows})
    return [d for d in days if onset_test(windows, envelope, side, d, cfg)["passes"]]


def feed_covariate(primary: dict[str, Any] | None, attr: dict[str, Any]) -> bool:
    """P0's R2 feed test: the primary residual explained most by a feed, η² ≥ the minimum."""
    if not primary:
        return False
    eta = [v for k, v in primary.get("covariate_eta2", {}).items() if k.startswith("feed")]
    return str(primary.get("most_explanatory") or "").startswith("feed") and max(
        eta or [0.0]
    ) >= float(attr["feed_eta2_min"])


def early_late(residuals: dict[str, dict[str, Any]], attr: dict[str, Any]) -> list[str]:
    """The S4 test in code (§2.4): channels biased early and clean after (P0's R5)."""
    out = []
    for ch, r in residuals.items():
        early, late = r.get("early_bias_z"), r.get("late_bias_z")
        if (
            early is not None
            and late is not None
            and abs(early) >= float(attr["state_bias_z"])
            and abs(late) <= float(attr["clean_bias_z"])
        ):
            out.append(ch)
    return sorted(out)


def common_change_point(
    residuals: dict[str, dict[str, Any]], attr: dict[str, Any]
) -> dict[str, Any]:
    """P0's R4 arithmetic: a step on enough channels within the day tolerance."""
    steps = [
        (ch, float(r["step_day"]))
        for ch, r in residuals.items()
        if r.get("step_z") is not None
        and r["step_z"] >= float(attr["parameter_step_z"])
        and r.get("step_day") is not None
    ]
    need, tol = int(attr["parameter_channels_min"]), float(attr["step_day_tolerance_d"])
    for _, day in sorted(steps, key=lambda s: s[1]):
        sharing = [ch for ch, d in steps if abs(d - day) <= tol]
        if len(sharing) >= need:
            return {"common": True, "day": day, "channels": sorted(sharing)}
    return {"common": False, "day": None, "channels": []}


def split_agrees(
    day: float | None,
    channels: Sequence[str],
    steps: dict[str, dict[str, Any]],
    attr: dict[str, Any],
) -> bool:
    """Whether ``cal.split``'s proposal is a valid common step by P0's R4 arithmetic.

    Accepted (the lead's ruling of 2026-10-14, defect c): no day with no channel; or at least
    ``parameter_channels_min`` named channels, each with its own step at or above
    ``parameter_step_z`` (a missing or NaN step refuses), whose step days all lie within
    ``step_day_tolerance_d`` of one of their own step days (R4's own form: ``sharing`` is every
    channel within the tolerance of a step day; not pairwise, which is stricter for three or
    more channels) and of the proposed day. Before the ruling only R4's earliest common day was
    accepted, so a later valid common step (attempt 1's ``tan`` and ``alkalinity`` at days 105
    and 112) was refused. A channel below the threshold (attempt 1's ``cod_total`` at z 1.43) is
    still refused.
    """
    if day is None:
        return not channels
    if len(channels) < int(attr["parameter_channels_min"]) or len(set(channels)) != len(channels):
        return False
    z_min, tol = float(attr["parameter_step_z"]), float(attr["step_day_tolerance_d"])
    days = []
    for ch in channels:
        r = steps.get(ch) or {}
        z, d = r.get("step_z"), r.get("step_day")
        if z is None or d is None or not (float(z) >= z_min):  # NaN is refused
            return False
        days.append(float(d))
    if not any(all(abs(d - anchor) <= tol for d in days) for anchor in days):
        return False
    return all(abs(d - float(day)) <= tol for d in days)


def tied_change_point(
    residuals: dict[str, dict[str, Any]],
    failed: Sequence[str],
    attr: dict[str, Any],
    transient_end: float,
) -> dict[str, Any]:
    """The change point that may admit ``parameter`` (the lead's rulings, 2026-10-08).

    P0's R4 arithmetic over the channels whose null case **failed** only, and only over
    change points **after** the first HRT (``transient_end``: the calibration start plus
    P0's ``transient_d``, the early/late test's own boundary). A channel's located change
    point that falls inside the first HRT does not count (it is not searched for again
    later); a step on a channel that did not fail does not count. ``common`` therefore
    needs ``parameter_channels_min`` failed channels sharing a step after the transient.
    """
    dated = {ch: float(r["step_day"]) for ch, r in residuals.items()
             if r.get("step_day") is not None}  # fmt: skip
    late = {ch: residuals[ch] for ch, day in dated.items() if day > transient_end}
    out = common_change_point({ch: r for ch, r in late.items() if ch in set(failed)}, attr)
    # only channels whose located step is inside the first HRT (the review's N-6)
    out["first_hrt_excluded"] = sorted(ch for ch, day in dated.items() if day <= transient_end)
    out["off_failed"] = sorted(ch for ch in late if ch not in set(failed))
    return out


def structured_channels(
    residuals: dict[str, dict[str, Any]], attr: dict[str, Any], at_bound: bool
) -> list[str]:
    """P0's R3 criterion: channels still structured by load or time after the fit."""
    return sorted(
        ch
        for ch, r in residuals.items()
        if (r.get("rmse_z") or 0.0) >= float(attr["structural_rmse_z_min"])
        and r.get("serially_structured")
        and (r.get("most_explanatory") in ("load", "time") or at_bound)
    )


def inhibition(p: Placement) -> dict[str, Any]:
    """The inhibited-steady-state check (§2.5): TAN and VFA high after the fit, pH not."""
    if "tan.after_fit.mean_z" not in p or "vfa_total.after_fit.mean_z" not in p:
        return {"available": False, "inhibited": False}
    tan, vfa = p["tan.after_fit.mean_z"], p["vfa_total.after_fit.mean_z"]
    ph = p.get("ph.after_fit.mean_z", 0)
    return {
        "available": True,
        "tan_side": tan,
        "vfa_side": vfa,
        "ph_side": ph,
        "inhibited": tan == 1 and vfa == 1 and ph != 1,
    }


def s1_table(channel: str, p: Placement, coupled: dict[str, Sequence[str]]) -> dict[str, Any]:
    """The S1 table (§2.2): the candidate beside its coupled channels, from the placement."""
    rows = {}
    for name in [channel, *coupled.get(channel, ())]:
        rows[name] = {
            "after_fit_mean": p.get(f"{name}.after_fit.mean_z"),
            "after_fit_rms": p.get(f"{name}.after_fit.rms_z"),
        }
    present = [c for c in coupled.get(channel, ()) if f"{c}.after_fit.mean_z" in p]
    return {
        "channel": channel,
        "rows": rows,
        "coupled_present": present,
        "coupled_inside": all(p[f"{c}.after_fit.mean_z"] == 0 for c in present),
    }


# ------------------------------------------------------------------ the admission (§4.4)


def admit(
    lab: dict[str, str],
    table: dict[str, Any] | None,
    signatures: dict[str, Any],
) -> dict[str, Any]:
    """Admission (§4.4): a label only over a failed null case that matches it.

    ``signatures`` holds the code results: ``sensor`` (the channel that failed alone, and
    whether its S1 reading holds), ``influent`` (onset or feed covariate), ``initial_state``
    (early/late on a failed channel and the biomass pair improving), ``parameter`` (a
    common step or inhibition, no feed covariate), ``structural`` (R3 and a failed
    hold-out). With no table (the verifier off), no null case is checked.
    """
    admitted: list[str] = []
    rejected: list[dict[str, str]] = []

    def judge(key: str, null_ok: bool, signature_ok: bool, code: str = "signature_absent") -> None:
        if not signature_ok:
            if signatures.get(f"{key}_proposed"):
                rejected.append({"label": lab[key], "code": code})
            return
        if table is not None and not null_ok:
            rejected.append({"label": lab[key], "code": "null_not_failed"})
            return
        admitted.append(lab[key])

    t = table or {}
    sensor = signatures.get("sensor") or {}
    judge(
        "sensor",
        bool(t.get("NS")) and sensor.get("channel") in t.get("failed_channels", []),
        bool(sensor.get("channel")) and bool(sensor.get("s1_holds")),
        # coupled_outside only when the S1 table itself shows the coupled channels moved;
        # a table that holds with no reading for it (the offline fallback) is absent
        "coupled_outside"
        if sensor.get("channel") and not (sensor.get("s1") or {}).get("coupled_inside", False)
        else "signature_absent",
    )
    judge("influent", bool(t.get("NB")), bool(signatures.get("influent")))
    judge(
        "initial_state",
        bool(t.get("NS")) or bool(t.get("NM")),
        bool(signatures.get("initial_state")),
    )
    judge(
        "parameter",
        bool(t.get("NM")) and not bool(t.get("NB")),
        bool(signatures.get("parameter")),
        str(signatures.get("parameter_code", "signature_absent")),
    )
    judge(
        "structural",
        bool(t.get("NM")),
        bool(signatures.get("structural")),
        str(signatures.get("structural_code", "signature_absent"))
        if not signatures.get("r3")
        else ("holdout_unavailable" if signatures.get("holdout_failed") is None
              and "holdout_failed" in signatures else "holdout_passed"),
    )  # fmt: skip
    return {"admitted": admitted, "rejected": rejected}


# ------------------------------------------------------------------ the agent arm
# (docs/p2_agents_design.md §2; the procedural arm, Q12, the "decision points only" arm,
# keeps `admit` as frozen.)


def structural_case(table: dict[str, Any] | None, signatures: dict[str, Any]) -> tuple[bool, str]:
    """The amended admitting case for ``structural`` (docs/decisions.md, 2026-10-25, Q13 and Q14).

    Two branches, both needing a failed hold-out:

    1. **NM failed** (the rule frozen on 2026-10-07 (a)): P0's R3 criterion on two or more
       **failed** channels (``signatures["r3"]``, the 2026-10-08 ruling) and a failed hold-out.
    2. **NM stands** (the lead's "Yes to both" and "Yes" of 2026-10-25): a failed hold-out
       **and** R3 counted over **all** channels, two independent pieces of evidence. This
       amends the 2026-10-08 ruling for this case only. R3 over all channels is read as the
       pipeline's own count, ``signatures["structural_proposed"]``
       (``len(r3_channels_all) >= structural_channels_min``, written by ``step_profile``
       at the configured minimum): no caller passes a minimum of its own, so none can pass
       a literal, a stricter one (which would return the pipeline's code for another case)
       or a looser one (which would admit what the pipeline never proposed). A test pins
       every key this function reads to one the pipeline writes.

    One reading differs from the frozen :func:`admit`: a hold-out that was never checked
    (``holdout_failed`` absent, as well as ``None``) is ``holdout_unavailable`` here, where
    :func:`admit` reads an absent key as ``holdout_passed``. The pipeline always writes the
    key before admission, so the two agree on every pipeline input.

    Returns:
        ``(admitted, code)``: the code is the design's rejection code when not admitted
        (``holdout_unavailable`` when the hold-out was not checked, ``holdout_passed`` when it
        passed, else ``signature_absent`` / the finer R3 code).
    """
    t = table or {}
    nm = bool(t.get("NM"))
    r3 = bool(signatures.get("r3")) if nm else bool(signatures.get("structural_proposed"))
    holdout = signatures.get("holdout_failed")
    if not r3:
        return False, str(signatures.get("structural_code", "signature_absent"))
    if holdout is None:
        return False, "holdout_unavailable"
    if not holdout:
        return False, "holdout_passed"
    return True, "admitted"


def admit_agent(
    lab: dict[str, str],
    table: dict[str, Any] | None,
    signatures: dict[str, Any],
) -> dict[str, Any]:
    """Admission for the agent arm: :func:`admit` with the amended ``structural`` case.

    ``sensor``, ``influent``, ``state`` and ``parameter`` are judged exactly as :func:`admit`
    does (a test pins the two equal on every input). ``structural`` follows
    :func:`structural_case`: when NM stands it needs a failed hold-out and R3 over all
    channels (docs/decisions.md, 2026-10-25, Q13 and Q14; ``docs/p2_design.md`` §4.4 is
    superseded on this point for this arm only). With no table (the verifier off) no null
    case is checked, as in :func:`admit`.

    One record differs from :func:`admit`, deliberately: when some channel is structured
    (``r3_channels_all`` non-empty) but too few for a proposal, the agent arm records a
    ``structural`` rejection with its code, where the frozen rule records nothing (it writes
    a rejection only for a proposed label). The agent arm's verifier reads the rejections,
    so a structured channel that fell short is on the record for it.
    """
    base = admit(lab, table, signatures)
    structural = lab["structural"]
    admitted = [x for x in base["admitted"] if x != structural]
    rejected = [r for r in base["rejected"] if r["label"] != structural]
    if table is None:
        ok, code = (
            bool(signatures.get("structural")),
            str(signatures.get("structural_code", "signature_absent")),
        )
    else:
        ok, code = structural_case(table, signatures)
    if ok:
        admitted.append(structural)
    elif (
        signatures.get("structural_proposed")
        or signatures.get("r3")
        or signatures.get("r3_channels_all")
    ):
        rejected.append({"label": structural, "code": code})
    return {"admitted": admitted, "rejected": rejected}


def admissible_alternative(
    alternative: str,
    lab: dict[str, str],
    table: dict[str, Any] | None,
    signatures: dict[str, Any],
) -> bool:
    """Whether a verifier's alternative may be named: ``none``, or a label the amended rule admits.

    The code check of the ``Verdict`` (design note §3.3): the verifier cannot name a cause
    the evidence does not admit. The harness calls it with the pipeline's own signatures.
    """
    if alternative == lab["none"]:
        return True
    return alternative in admit_agent(lab, table, signatures)["admitted"]
