"""P2: task-specialised procedures with model-backed decision points (``docs/p2_design.md``).

Runs **inside the jail** (``tools.sandbox.launch``), which copies this one file: the only
things that resolve here are ``tools`` (the client stub), numpy, scipy, pydantic and the
standard library. It reads its settings from ``p2_config.json`` (``configs/workflows/
p2.yaml`` with P0's ``p0.yaml`` beside it, the decision templates with their sha256, the
declared noise and geometry), the run from ``tools.run``, and calls every numerical
routine through ``tools.call``, each through the calling role's allow-listed view.

The design in one paragraph. Coordination is code: a fixed state machine (§5) over the
§6.6 task state. The roles are procedures. A model is consulted only at twelve declared
decision points (§2), each with a fixed output schema and a declared fallback. By
default the decider is **offline** (``decider: offline``): every decision point takes its
fallback and no model is called. Only the runner's explicit live flag hands the jail
``decider: live``, and then each decision is one request through the privileged
gateway (``tools.llm``), with its frozen template and its one tool (deliverable 3). Every
test that sets a label's evidence is code, in either mode. The
first calibration is the **reference fit**, the declared background's own procedure,
so its statistics are placed against the published band like for like (§3); the
**null rule** (§4, frozen 2026-10-07) reads the placement, and a label is admitted only
over a null case that failed (§4.4). The verifier alone reads the hold-out.

Rule 1: nothing here reads the truth store; the band is the registry tool
``declared_background``. Rule 4: every stochastic call takes a seed from P0's
configuration. Operator notes are data.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import tools

CONFIG_FILE = "p2_config.json"
STATE_FILE = "state.json"
REPORT_FILE = "report.json"
MESSAGES_FILE = "messages.jsonl"
DECISIONS_FILE = "decisions.jsonl"
MODEL = "adm1_fitted"
NEVER_IN_OBJECTIVE = ("temperature",)
"""A channel no calibratable parameter moves (P0's rule): placed and shown, never failed."""
BALANCE_STATS = ("cod_closure", "cod_closure_worst", "n_cod_inadmissible")
P0_ORDER = ("sensor", "influent", "initial_state", "parameter", "structural")
"""P0's order of the labels (its R1..R4, R3), by the label vocabulary's keys."""


# ------------------------------------------------------------------ arithmetic


def _f(x: Any) -> float | None:
    """A JSON-safe float (None for a non-finite value)."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def round6(x: Any) -> float | None:
    """Six significant digits, None for a non-finite value: the band driver's rounding."""
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return float(f"{x:.6g}")


def declared_sd(value: np.ndarray, cv: float, sd_abs: float, cal: dict[str, Any]) -> np.ndarray:
    """P0's weight of a sample: ``sqrt((cv |v|)^2 + sd_abs^2)``, floored (design §3)."""
    finite = value[np.isfinite(value)]
    scale = float(np.median(np.abs(finite))) if finite.size else 1.0
    floor = max(float(cal["min_relative_sd"]) * scale, float(cal["sd_floor_abs"]))
    return np.maximum(np.sqrt((cv * np.abs(np.nan_to_num(value))) ** 2 + sd_abs**2), floor)


def z_summary(
    t: np.ndarray,
    value: np.ndarray,
    sd: np.ndarray,
    t_model: np.ndarray,
    predicted: np.ndarray,
    window: tuple[float, float],
) -> dict[str, Any] | None:
    """``n``, ``mean_z`` and ``rms_z`` of ``(observed - predicted) / sd`` inside ``window``.

    The band driver's arithmetic (``_Series.summary``), reimplemented here because the
    workflow imports nothing from ``scripts/`` (design §3); a test pins the two together.
    """
    m = np.isfinite(value) & (t >= window[0]) & (t <= window[1])
    if int(m.sum()) < 1:
        return None
    pred = np.interp(t[m], np.asarray(t_model, dtype=float), np.asarray(predicted, dtype=float))
    z = (value[m] - pred) / sd[m]
    return {
        "n": int(m.sum()),
        "mean_z": round6(z.mean()),
        "rms_z": round6(math.sqrt(float(np.mean(z**2)))),
    }


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


EXCLUDED = ("abstain", "pending")
"""The outcomes no count may read as a label (the review's F-A; ruling (c))."""


def outcome(verdict: dict[str, Any], completed: bool, label: str) -> str:
    """What every P2 count keys on: ``pending``, ``abstain``, or the final label.

    The task state must carry a label from the closed vocabulary, so an abstaining or
    unfinished run writes the null label there; this is the field that says it is not one.
    A run that did not complete is ``pending`` whatever it wrote; a completed run whose
    verdict abstained is ``abstain``.
    """
    if not completed:
        return "pending"
    if verdict.get("verdict") == "abstain":
        return "abstain"
    return label


def first_in_p0_order(lab: dict[str, str], labels: Sequence[str]) -> str:
    """The first of ``labels`` in P0's order, or the null label (the differential's fallback)."""
    for key in P0_ORDER:
        if lab[key] in labels:
            return lab[key]
    return lab["none"]


# ------------------------------------------------------------------ quarantines (§2.2)


def constrain_quarantine(
    t: np.ndarray,
    selected: np.ndarray,
    flagged: np.ndarray,
    spikes: np.ndarray,
    first_hrt_end: float,
    holdout_start: float,
    *,
    trim: bool,
) -> dict[str, Any]:
    """``dq.trust``'s code constraints on a set of samples to quarantine (decision 4).

    Refused: a sample QC did not flag; a **spike** sample inside the first HRT (decision 4
    is about spikes: they go to the early/late test); a sample in the hold-out. A model's
    proposal that touches any of them is refused whole (``trim`` false). P0's fallback is
    trimmed instead: the offending samples are dropped from it and the rest stands (the
    review's R2).
    """
    unflagged = selected & ~flagged
    early_spike = selected & spikes & (t <= first_hrt_end)
    holdout = selected & (t >= holdout_start)
    bad = unflagged | early_spike | holdout
    reasons = [
        name
        for name, mask in (("unflagged", unflagged), ("first_hrt_spike", early_spike),
                           ("holdout", holdout))
        if mask.any()
    ]  # fmt: skip
    if not bad.any():
        return {"accepted": selected.copy(), "refused": False, "trimmed": 0, "reasons": []}
    if trim:
        return {
            "accepted": selected & ~bad,
            "refused": False,
            "trimmed": int(bad.sum()),
            "reasons": reasons,
        }
    return {
        "accepted": np.zeros_like(selected),
        "refused": True,
        "trimmed": 0,
        "reasons": reasons,
    }


def mask_windows(t: np.ndarray, mask: np.ndarray) -> list[list[float]]:
    """A sample mask as the contiguous windows it covers, [first, last] sample days."""
    out: list[list[float]] = []
    i = 0
    while i < mask.size:
        if mask[i]:
            j = i
            while j + 1 < mask.size and mask[j + 1]:
                j += 1
            out.append([float(t[i]), float(t[j])])
            i = j + 1
        else:
            i += 1
    return out


# ------------------------------------------------------------------ decision points (§2)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DqTrust(_Out):
    """``dq.trust``: which flagged windows to quarantine."""

    sensor: str
    quarantine: list[tuple[float, float]]
    reason: Literal["flatline", "spike_run", "outage"]


class DqAssay(_Out):
    """``dq.assay``: an assay against a suspected channel (or none)."""

    assay: str | None
    day: float | None
    target_sensor: str | None


class DqCoupled(_Out):
    """``dq.coupled``: what the coupled channels show."""

    sensor: str
    code: Literal[
        "coupled_inside", "coupled_outside", "assay_acquits", "assay_implicates", "insufficient"
    ]


class InfluentOnset(_Out):
    """``influent.onset``: the proposed onset, the feed, the anchors."""

    onset_day: float | None
    feed_id: str | None
    anchors: list[int] = Field(default_factory=list)


class InfluentWindow(_Out):
    """``influent.window``: the window reported as the worst."""

    window_index: int


class InfluentMechanism(_Out):
    """``influent.mechanism``: reported only, never a label."""

    code: Literal["fractionation", "moisture", "unrecorded_delivery", "mislabel", "none"]


class IdentSubset(_Out):
    """``ident.subset``: the fitted subset beyond the reference fit."""

    parameters: list[str] = Field(min_length=2, max_length=4)


class CalAccept(_Out):
    """``cal.accept``: accept or reject a fit."""

    accept: bool
    code: Literal["converged", "not_converged", "worse_than_reference", "bound_hit"]


class CalBound(_Out):
    """``cal.bound``: how to read a bound hit; there is no kinetic-update value."""

    code: Literal["identifiability_limit", "data_limit", "structure_hint"]


class CalSplit(_Out):
    """``cal.split``: the common step day, accepted only where code agrees."""

    common_step_day: float | None
    channels: list[str] = Field(default_factory=list)


class DesignAssay(_Out):
    """``design.assay``: the assay, its day and the prediction it tests (or none)."""

    assay: str | None
    day: float | None
    prediction: str | None


class VerifyDifferential(_Out):
    """``verify.differential``: one admitted label or the null label; codes for the rest."""

    label: str
    rejected: list[dict[str, str]] = Field(default_factory=list)


DECISIONS: dict[str, dict[str, Any]] = {
    "dq.trust": {"role": "data_quality", "model": DqTrust,
                 "inputs": ("sensor", "qc_findings", "flagged_windows", "first_hrt_d",
                            "sample_counts")},
    "dq.assay": {"role": "data_quality", "model": DqAssay,
                 "inputs": ("s1_table", "price_list", "units_left")},
    "dq.coupled": {"role": "data_quality", "model": DqCoupled,
                   "inputs": ("s1_table", "assays")},
    "influent.onset": {"role": "influent", "model": InfluentOnset,
                       "inputs": ("feed_log", "notes", "window_closures", "window_envelope")},
    "influent.window": {"role": "influent", "model": InfluentWindow,
                        "inputs": ("window_closures",)},
    "influent.mechanism": {"role": "influent", "model": InfluentMechanism,
                           "inputs": ("balance", "feed_log", "onset")},
    "ident.subset": {"role": "identifiability", "model": IdentSubset,
                     "inputs": ("forced", "morris_ranking", "morris_kept", "relative_crlb")},
    "cal.accept": {"role": "calibration", "model": CalAccept,
                   "inputs": ("chi2", "converged", "reference_chi2", "at_bound")},
    "cal.bound": {"role": "calibration", "model": CalBound,
                  "inputs": ("parameter", "bounds", "estimate", "sd")},
    "cal.split": {"role": "calibration", "model": CalSplit,
                  "inputs": ("steps",)},
    "design.assay": {"role": "design", "model": DesignAssay,
                     "inputs": ("request", "voi", "price_list", "units_left")},
    "verify.differential": {"role": "verification", "model": VerifyDifferential,
                            "inputs": ("null_table", "admitted", "tables", "holdout_failed")},
}  # fmt: skip
"""Every decision point: its role, its output schema and its declared inputs (§2)."""


def schema_sha256(model: type[BaseModel]) -> str:
    """The sha256 of an output schema, as recorded in every decision record."""
    text = json.dumps(model.model_json_schema(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


Responder = Callable[[str, str, dict[str, Any]], Any]
"""A decider: ``(point, template text, inputs) -> raw output or None``."""


def offline_responder(point: str, template: str, inputs: dict[str, Any]) -> None:
    """The offline decider of deliverable 2: no model; every point takes its fallback."""
    return None


class DecisionError(Exception):
    """A decision point asked with inputs it does not declare."""


class AttemptFailed(Exception):
    """One attempt at a decision failed (no decision call in the reply, a model error)."""


class ModelCapReached(Exception):
    """The gateway refused a request: a request, token or USD cap would be exceeded.

    The run stops asking and abstains (deliverable 3, F-E): it does not fall back to code
    for the rest of the run, so no live run is ever a silent mixture of the two.
    """


def decision_tool(point: str) -> dict[str, Any]:
    """The one tool a decision request offers: its input schema is the decision's schema.

    Deterministic, so the runner can freeze its digest beside the template's.
    """
    return {
        "name": point.replace(".", "_"),
        "description": "Return the decision as this tool's input. Its schema is the only "
        "form accepted.",
        "input_schema": DECISIONS[point]["model"].model_json_schema(),
    }


class LiveResponder:
    """The live decider (deliverable 3): one request per attempt through the gateway.

    The request is the template as the system prompt, the declared inputs as one user
    message (JSON), and the decision's single tool. Nothing else reaches the model. A
    reply without the decision's tool call, or a model error, is a failed attempt; a cap
    refusal stops the run (:class:`ModelCapReached`).
    """

    def __init__(self) -> None:
        """Start with no call ids pending."""
        self.pending: list[int] = []

    def take_call_ids(self) -> list[int]:
        """The gateway turn ids of the attempts since the last take."""
        out, self.pending = list(self.pending), []
        return out

    def __call__(self, point: str, template: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """One attempt."""
        tool = decision_tool(point)
        request = {
            "system": template,
            "messages": [{"role": "user", "content": json.dumps(_jsonable(inputs),
                                                                sort_keys=True)}],
            "tools": [tool],
        }  # fmt: skip
        try:
            reply = tools.llm(request)
        except tools.BudgetExceededError as exc:
            raise ModelCapReached(str(exc)) from exc
        except tools.ToolError as exc:
            raise AttemptFailed(f"model: {str(exc)[:200]}") from exc
        status = reply.get("status") or {}
        if "turns_used" in status:
            self.pending.append(int(status["turns_used"]) - 1)
        for block in (reply.get("response") or {}).get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == tool["name"]:
                return dict(block.get("input") or {})
        raise AttemptFailed("no decision call in the reply")


class Decider:
    """Asks a decision point, validates its answer twice at most, else takes the fallback."""

    def __init__(self, templates: dict[str, dict[str, str]], respond: Responder) -> None:
        """Set up with the templates (text and sha256) and the responder."""
        self.templates = templates
        self.respond = respond
        self.records: list[dict[str, Any]] = []

    def decide(
        self,
        point: str,
        inputs: dict[str, Any],
        fallback: dict[str, Any],
        *,
        check: Callable[[BaseModel], bool] | None = None,
    ) -> BaseModel:
        """The validated output of ``point``, or its fallback (recorded either way).

        ``check`` is a code constraint on a validated output (for example ``dq.trust``'s
        quarantine rule): an output it refuses counts as an invalid attempt.
        """
        spec = DECISIONS[point]
        extra = set(inputs) - set(spec["inputs"])
        if extra:
            raise DecisionError(f"{point}: undeclared inputs {sorted(extra)}")
        model: type[BaseModel] = spec["model"]
        template = self.templates[point]
        attempts = 0
        failures: list[str] = []
        output: BaseModel | None = None
        for _ in range(2):
            try:
                raw = self.respond(point, template["text"], inputs)
            except AttemptFailed as exc:
                attempts += 1
                failures.append(str(exc))
                continue
            if raw is None:
                break
            attempts += 1
            try:
                candidate = model.model_validate(raw)
            except ValidationError as exc:
                failures.append(f"schema: {exc.error_count()} errors")
                continue
            if check is not None and not check(candidate):
                failures.append("refused by the code constraint")
                continue
            output = candidate
            break
        used_fallback = output is None
        if output is None:
            output = model.model_validate(fallback)
        take = getattr(self.respond, "take_call_ids", None)
        self.records.append(
            {
                "role": spec["role"],
                "point": point,
                "template_sha256": template["sha256"],
                "schema_sha256": schema_sha256(model),
                "inputs_digest": _digest(inputs),
                "output": output.model_dump(mode="json"),
                "attempts": attempts,
                "failures": failures,
                "fallback_used": used_fallback,
                "llm_call_ids": take() if take is not None else [],
            }
        )
        return output


# ------------------------------------------------------------------ messages (§6.2)


class Message(BaseModel):
    """One typed message between roles: numbers, enums and references, no free text."""

    model_config = ConfigDict(extra="forbid")

    seq: int
    kind: Literal["task", "finding", "table", "decision", "proposal", "verdict"]
    from_role: str
    to_role: str
    step: str
    body: dict[str, Any]


class MessageLog:
    """The append-only message log, ``messages.jsonl``."""

    def __init__(self) -> None:
        """Start empty."""
        self.messages: list[Message] = []

    def send(
        self, kind: str, from_role: str, to_role: str, step: str, body: dict[str, Any]
    ) -> Message:
        """Append one message."""
        msg = Message(
            seq=len(self.messages),
            kind=kind,
            from_role=from_role,
            to_role=to_role,
            step=step,
            body=json.loads(json.dumps(body, default=_jsonable)),
        )
        self.messages.append(msg)
        return msg

    def lines(self) -> str:
        """The log as JSON lines."""
        return "".join(m.model_dump_json() + "\n" for m in self.messages)


def _jsonable(x: Any) -> Any:
    if isinstance(x, np.ndarray):
        return [_f(v) for v in x.tolist()]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return _f(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return str(x)


# ------------------------------------------------------------------ roles (§6.1)


class RoleRefused(Exception):
    """A role called a tool outside its allow-list."""


class Recorder:
    """Every tool call, named the way the visible log names it (P0's convention)."""

    def __init__(self) -> None:
        """Start with no actions, failures or refusals."""
        self.actions: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.refusals: list[dict[str, str]] = []
        self.by_role: dict[str, dict[str, float]] = {}

    def call(self, role: str, step: str, name: str, **args: Any) -> Any:
        """Call a tool, record it under the role, and re-raise its error after recording."""
        before = tools.remaining()
        record: dict[str, Any] = {
            "step": f"{role}.{step}",
            "name": name,
            "version": "",
            "args_hash": "",
            "seq": None,
            "call_index": int(before.n_calls),
            "outcome": "ok",
            "detail": "",
        }
        try:
            return tools.call(name, **args)
        except tools.BudgetExceededError as exc:
            record["outcome"], record["detail"] = "budget_exceeded", str(exc)[:300]
            raise
        except tools.ToolError as exc:
            record["outcome"], record["detail"] = "error", str(exc)[:300]
            raise
        finally:
            logged = tools.last_call() or {}
            record["version"] = str(logged.get("version", ""))
            record["args_hash"] = str(logged.get("args_hash", ""))
            record["seq"] = logged.get("seq")
            self.actions.append(record)
            after = tools.remaining()
            use = self.by_role.setdefault(role, {"evaluations": 0, "wall_clock_s": 0.0,
                                                 "assay_units": 0, "calls": 0})  # fmt: skip
            use["evaluations"] += int(before.simulator_evals) - int(after.simulator_evals)
            use["wall_clock_s"] += 60.0 * (float(before.wall_clock_min)
                                           - float(after.wall_clock_min))  # fmt: skip
            use["assay_units"] += int(before.assay_units) - int(after.assay_units)
            use["calls"] += 1

    def failure(self, step: str, name: str, kind: str, message: str, fallback: str) -> None:
        """Record a tool that did not deliver, and what was done instead."""
        self.failures.append(
            {
                "step": step,
                "name": name,
                "call_index": int(self.actions[-1]["call_index"]) if self.actions else None,
                "kind": kind,
                "message": message[:300],
                "fallback": fallback,
            }
        )

    @property
    def last_index(self) -> int | None:
        """The registry call index of the most recent call."""
        return int(self.actions[-1]["call_index"]) if self.actions else None


class RoleView:
    """One role's view of the run's registry: its allow-list, then the registry."""

    def __init__(self, role: str, allowed: Sequence[str], rec: Recorder) -> None:
        """Set up."""
        self.role = role
        self.allowed = frozenset(allowed)
        self.rec = rec

    def call(self, step: str, name: str, **args: Any) -> Any:
        """Call ``name`` if the role holds it; refuse and record it otherwise."""
        if name not in self.allowed:
            self.rec.refusals.append({"role": self.role, "step": step, "name": name})
            self.rec.failures.append(
                {
                    "step": f"{self.role}.{step}",
                    "name": f"p2.{self.role}.refused",
                    "call_index": None,
                    "kind": "error",
                    "message": f"{name} is not on the {self.role} role's list",
                    "fallback": "not called",
                }
            )
            raise RoleRefused(f"{self.role} may not call {name}")
        return self.rec.call(self.role, step, name, **args)


# ------------------------------------------------------------------ the plan (P0's)


class Plan:
    """P0's deterministic sizing (``docs/p0_design.md`` §4) and its runtime guard."""

    def __init__(self, plan_cfg: dict[str, Any]) -> None:
        """Set up."""
        self.cfg = plan_cfg
        self.sizes: dict[str, Any] = {}
        self.fallbacks: list[str] = []
        self.guards: list[str] = []
        self.skipped: dict[str, str] = {}
        self.completed: list[str] = []

    def fits(self, step: str, bound: int, share: float | None = None) -> bool:
        """Whether a call with this evaluation bound fits the plan and the guard."""
        rem = tools.remaining()
        share = float(self.cfg["step_share"]) if share is None else share
        left = float(rem.wall_clock_min) - float(self.cfg["wall_clock_reserve_min"])
        allowed = share * max(left, 0.0)
        if bound > int(rem.simulator_evals):
            return False
        if bound * float(self.cfg["eval_seconds_assumed"]) / 60.0 > allowed:
            return False
        used = int(rem.simulator_evals_total) - int(rem.simulator_evals)
        elapsed_s = (float(rem.wall_clock_min_total) - float(rem.wall_clock_min)) * 60.0
        if used >= 5 and elapsed_s > 0 and bound * elapsed_s / used / 60.0 > allowed:
            self.guards.append(f"{step}: bound {bound} at the measured rate")
            return False
        return True

    def ladder(self, initial: int, minimum: int) -> list[int]:
        """``initial, initial // 2, ...`` down to ``minimum``."""
        out, size = [], int(initial)
        while size >= int(minimum) and size >= 1:
            out.append(size)
            size //= 2
        return out


class Series:
    """One sensor: sample times, the raw values, the working values, P0's weights."""

    def __init__(self, name: str, raw: dict[str, Any], noise: dict[str, Any], cal: dict) -> None:
        """Set up."""
        self.name = name
        self.channel = str(raw["channel"])
        self.unit = str(raw["unit"])
        self.t = np.asarray(raw["sample_t_d"], dtype=float)
        self.raw = np.array([np.nan if v is None else float(v) for v in raw["value"]], dtype=float)
        self.value = self.raw.copy()
        self.cv, self.sd_abs = float(noise.get("cv", 0.0)), float(noise.get("sd_abs", 0.0))
        self.sd = declared_sd(self.raw, self.cv, self.sd_abs, cal)
        bound = noise.get("drift_bound")
        self.drift_bound = None if bound is None else float(bound)
        self.quarantined: list[list[float]] = []
        self.flags: list[str] = []
        self.missing_fraction = float(np.mean(~np.isfinite(self.raw))) if self.raw.size else None
        self.in_objective = False
        self.status = "ok"

    def weights(self, cal: dict[str, Any]) -> np.ndarray:
        """The declared sd under another pair of floors (the band's served procedure)."""
        return declared_sd(self.raw, self.cv, self.sd_abs, cal)

    def observed(
        self,
        window: tuple[float, float],
        *,
        raw: bool = False,
        sd: np.ndarray | None = None,
    ) -> dict[str, Any]:
        """An ``ObservedSeries`` payload restricted to ``window``."""
        keep = (self.t >= window[0]) & (self.t <= window[1])
        return {
            "output": self.channel,
            "t": self.t[keep],
            "value": (self.raw if raw else self.value)[keep],
            "sd": (self.sd if sd is None else sd)[keep],
            "unit": self.unit,
        }

    def count(self, window: tuple[float, float]) -> int:
        """Observed samples inside ``window``."""
        return int((np.isfinite(self.value) & (self.t >= window[0]) & (self.t <= window[1])).sum())


# ------------------------------------------------------------------ the workflow


class Workflow:
    """One run of P2: the coordinator's state machine over the roles' procedures (§5)."""

    def __init__(self, cfg: dict[str, Any], respond: Responder = offline_responder) -> None:
        """Set up from ``p2_config.json``."""
        self.cfg = cfg
        self.p0 = cfg["p0"]
        self.lab: dict[str, str] = dict(self.p0["labels"])
        self.attr = self.p0["attribution"]
        self.switch = cfg["ablation"]
        self.on = dict(self.switch["roles"])
        self.rec = Recorder()
        self.views = {role: RoleView(role, spec["tools"], self.rec)
                      for role, spec in cfg["roles"].items()}  # fmt: skip
        self.decider = Decider(cfg["templates"], respond)
        self.log = MessageLog()
        self.plan = Plan(self.p0["plan"])
        self.manifest = tools.run.manifest()
        self.plant, self.tier = str(self.manifest["plant"]), str(self.manifest["tier"])
        self.T = float(self.manifest["duration_days"])
        w = self.p0["windows"]
        cal_end = self.T * (1.0 - float(w["holdout_fraction"]))
        self.cal = (float(w["calibration_start_d"]), float(cal_end))
        self.holdout = (float(cal_end), self.T)
        self.series: dict[str, Series] = {}
        self.trace: list[str] = []
        self.codes: list[str] = []
        self.annotations: list[str] = []
        self.abstentions: list[str] = []
        self.evidence: list[dict[str, Any]] = []
        self.reference: dict[str, Any] | None = None
        self.reference_prediction: Any = None
        self.reference_fit: Any = None
        self.reference_optimum: dict[str, float] = {}
        self.balance_index: int | None = None
        self.reference_sd: dict[str, np.ndarray] = {}
        self.band: dict[str, Any] | None = None
        self.table: dict[str, Any] | None = None
        self.placement: Placement = {}
        self.residuals: dict[str, dict[str, Any]] = {}
        self.signatures: dict[str, Any] = {}
        self.tables: dict[str, Any] = {}
        self.verdict: dict[str, Any] = {}
        self.final_parameters: dict[str, dict[str, Any]] = {}
        self.interval_method = "none"
        self.validation: dict[str, Any] | None = None
        self.assay_checks: list[dict[str, Any]] = []
        self.classification: dict[str, Any] = {}
        self.prediction: Any = None
        self.prediction_index: int | None = None
        self.fit: Any = None
        self.optimum: dict[str, float] = {}
        self.approved: list[str] = []
        self.screening: dict[str, Any] = {}
        self.model: dict[str, Any] = {}
        self.notes: list[dict[str, Any]] = []
        self.completed = False
        # two switches are not yet wired through (design §14, deferred to deliverable 5);
        # the record says so rather than claiming an ablation that did not happen
        if not self.switch["persistent_state"]:
            self.annotations.append("ablation inert in this version: persistent_state")
        if not self.switch["coordinator"]:
            self.annotations.append(
                "ablation partial in this version: coordinator (only the REVISE round is removed)"
            )

    # -- persistence ---------------------------------------------------------------
    def checkpoint(self, step: str) -> None:
        """Mark a step done and write every record, so a stopped run keeps what it reached."""
        self.plan.completed.append(step)
        self.trace.append(step)
        self.write(completed=False)

    def write(self, *, completed: bool) -> None:
        """Write the task state, the report, the messages and the decisions."""
        doc = self.build_state(completed)
        tools.run.write_output(STATE_FILE, json.dumps(doc, indent=1, sort_keys=True))
        tools.run.write_output(REPORT_FILE, json.dumps(self.build_report(doc), indent=1))
        tools.run.write_output(MESSAGES_FILE, self.log.lines())
        tools.run.write_output(
            DECISIONS_FILE,
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in self.decider.records),
        )

    def call(self, role: str, step: str, name: str, **args: Any) -> Any:
        """A tool call through ``role``'s view."""
        return self.views[role].call(step, name, **args)

    # -- READ ------------------------------------------------------------------------
    def step_read(self) -> None:
        """The record, the model's interface, the declared loads, the default prediction."""
        noise = self.cfg.get("sensor_noise", {})
        record = tools.run.sensors()["sensors"]
        for name in sorted(record):
            self.series[name] = Series(name, record[name], noise.get(name, {}),
                                       self.p0["calibration"])  # fmt: skip
        self.notes = [
            {"day": int(n.get("day", 0)), "author": str(n.get("author", "")),
             "length": len(str(n.get("text", "")))}
            for n in tools.run.operator_notes()
        ]  # fmt: skip
        self.feed_log = tools.run.feed_log()
        desc = self.call("identifiability", "read", "describe_model", model=MODEL)
        self.model = {
            "parameters": list(desc.parameter_names),
            "lower": dict(zip(desc.parameter_names, map(float, desc.lower), strict=True)),
            "upper": dict(zip(desc.parameter_names, map(float, desc.upper), strict=True)),
            "units": dict(desc.parameter_units),
        }
        self.loads = self.call("influent", "read", "feed_loads", model=MODEL)
        self.baseline = self.call("calibration", "read", "simulate", model=MODEL)
        self.baseline_index = self.rec.last_index
        t = np.asarray(self.loads.t, dtype=float)
        q = np.asarray(self.loads.q_m3_d, dtype=float)
        inside = (t >= self.cal[0]) & (t <= self.cal[1]) & np.isfinite(q)
        geometry = self.cfg["plant_geometry"][self.plant]
        q_mean = float(q[inside].mean()) if inside.any() else float("nan")
        self.first_hrt = (
            float(geometry["V_liq_m3"]) / q_mean if q_mean > 0 else float(self.attr["transient_d"])
        )
        objective = set(self.p0["calibration"]["channels"])
        for s in self.series.values():
            s.in_objective = s.name in objective
        self.checkpoint("read")

    # -- QC (data quality) ---------------------------------------------------------------
    def event_windows(self) -> list[dict[str, float]]:
        """Days of high declared COD load (P0's QC event windows)."""
        load = np.asarray(self.loads.cod_kg_d, dtype=float)
        t = np.asarray(self.loads.t, dtype=float)
        high = load > np.quantile(load, float(self.p0["qc"]["event_load_quantile"]))
        return [{"start": w[0], "end": w[1] + 1.0} for w in mask_windows(t, high)]

    def step_qc(self) -> None:
        """QC, P0's exclusion rules, and ``dq.trust`` under its code constraints (§2.2)."""
        qc = self.p0["qc"]
        if not self.on["data_quality"]:
            self.plan.skipped["qc"] = "the data-quality role is off"
            return
        payload = [{"name": s.name, "t": s.t, "value": s.raw, "unit": s.unit}
                   for s in self.series.values()]  # fmt: skip
        out = self.call("data_quality", "qc", "data_qc", series=payload,
                        event_windows=self.event_windows())  # fmt: skip
        by_name = {r.name: r for r in out.results}
        for name, s in self.series.items():
            r = by_name[name]
            s.flags = list(r.flags)
            s.missing_fraction = float(r.missing_fraction)
            flat = np.zeros(s.t.shape, dtype=bool)
            for seg in r.flatlines:
                flat |= (s.t >= float(seg.start)) & (s.t <= float(seg.end))
                if float(seg.end) - float(seg.start) >= float(qc["flatline_flag_d"]):
                    s.status = "flagged"
                    self.abstentions.append(f"{name}_claims")
            spikes = np.isin(s.t, np.asarray(r.spikes, dtype=float))
            flagged = flat | spikes
            if flagged.any():
                fallback = constrain_quarantine(s.t, flagged, flagged, spikes, self.first_hrt,
                                                self.holdout[0], trim=True)  # fmt: skip

                def check(
                    o: BaseModel,
                    s: Series = s,
                    flagged: np.ndarray = flagged,
                    spikes: np.ndarray = spikes,
                ) -> bool:
                    sel = np.zeros(s.t.shape, dtype=bool)
                    for a, b in o.quarantine:
                        sel |= (s.t >= a) & (s.t <= b)
                    return not constrain_quarantine(
                        s.t, sel, flagged, spikes, self.first_hrt, self.holdout[0], trim=False
                    )["refused"]

                choice = self.decider.decide(
                    "dq.trust",
                    {"sensor": name, "qc_findings": list(r.flags),
                     "flagged_windows": mask_windows(s.t, flagged),
                     "first_hrt_d": self.first_hrt, "sample_counts": int(s.count(self.cal))},
                    {"sensor": name, "quarantine": mask_windows(s.t, fallback["accepted"]),
                     "reason": "flatline" if flat.any() else "spike_run"},
                    check=check,
                )  # fmt: skip
                sel = np.zeros(s.t.shape, dtype=bool)
                for a, b in choice.quarantine:
                    sel |= (s.t >= a) & (s.t <= b)
                accepted = sel & flagged & ~(spikes & (s.t <= self.first_hrt))
                accepted &= s.t < self.holdout[0]
                s.value = np.where(accepted, np.nan, s.value)
                s.quarantined = mask_windows(s.t, accepted)
                if fallback["trimmed"]:
                    self.codes.append(f"dq.trust_trimmed:{name}:{fallback['trimmed']}")
                if s.quarantined and s.status == "ok":
                    s.status = "quarantined"
            if r.drift_flag:
                span = float(s.t[np.isfinite(s.raw)][-1] - s.t[np.isfinite(s.raw)][0]) \
                    if np.isfinite(s.raw).sum() >= 2 else 0.0  # fmt: skip
                beyond = s.drift_bound is None or abs(float(r.drift_slope_per_d or 0.0)) * span \
                    > float(qc["drift_bound_factor"]) * s.drift_bound  # fmt: skip
                if beyond:
                    s.status, s.in_objective = "flagged", False
                else:
                    s.flags.append("drift_within_declared_bound")
            if r.informative_missingness:
                self.abstentions.append("missing_transient")
            if s.count(self.cal) < int(qc["min_samples"]):
                s.in_objective = False
                if s.status == "ok":
                    s.status = "excluded"
        self.log.send("table", "data_quality", "coordination", "qc",
                      {"statuses": {n: s.status for n, s in self.series.items()}})  # fmt: skip
        self.checkpoint("qc")

    # -- BALANCE and REFERENCE (the band's own procedure, §3) --------------------------------
    def step_reference(self) -> None:
        """The reference fit: the declared background's procedure, like for like (§3).

        Every size, window and seed is the ``procedure`` block the band tool serves, never
        retyped: on the raw record (the band's statistics are on the raw record), the
        balance over the calibration window in the band's windows, P0's Morris rule at the
        served size and seed, the Fisher rule, ``fit_lsq`` at the served sizes and seed,
        one ``simulate`` at the optimum. If any call fails the reference is incomplete and
        the run abstains (decision c, DECIDED 2026-10-07).
        """
        cal = self.cal
        try:
            band = self.call("calibration", "reference", "declared_background",
                             plant=self.plant, tier=self.tier)  # fmt: skip
            self.band = band.model_dump(mode="json")
            proc = self.band["procedure"]
            served_cal = (float(proc["calibration_start_d"]),
                          self.T * (1.0 - float(proc["holdout_fraction"])))  # fmt: skip
            if any(abs(a - b) > 1e-9 for a, b in zip(served_cal, cal, strict=True)):
                self.annotations.append("the served calibration window differs from P0's")
            self.reference = self._reference(proc, served_cal)
        except (tools.ToolError, RoleRefused) as exc:
            self.rec.failure("reference", "reference_fit", "error", str(exc),
                             "no null table: the run abstains")  # fmt: skip
            self.reference = None
            self.codes.append("no_null_table")
        self.checkpoint("reference")

    def _reference(self, proc: dict[str, Any], cal: tuple[float, float]) -> dict[str, Any]:
        objective = [s for s in self.series.values() if s.name in set(proc["objective_channels"])]
        # the noise floors are the served procedure's, like everything else (the review's F-J)
        floors = {"min_relative_sd": float(proc["min_relative_sd"]),
                  "sd_floor_abs": float(proc["sd_floor_abs"])}  # fmt: skip
        weights = {n: s.weights(floors) for n, s in self.series.items()}
        self.reference_sd = weights
        default = {n: z_summary(s.t, s.raw, weights[n], self.baseline.t,
                                self.baseline.outputs[s.channel], cal)
                   for n, s in self.series.items()
                   if s.channel in self.baseline.outputs}  # fmt: skip
        width = float(proc["balance_window_d"])
        windows, start = [], cal[0]
        while start + width <= cal[1] + 1e-9:
            windows.append({"start": start, "end": start + width})
            start += width
        geometry = self.cfg["plant_geometry"][self.plant]
        t_op = float(geometry["T_op_K"])
        temp = self.series.get("temperature")
        if temp is not None:
            m = np.isfinite(temp.raw) & (temp.t >= cal[0]) & (temp.t <= cal[1])
            if m.any():
                t_op = float(temp.raw[m].mean())

        def obs(name: str) -> dict[str, Any] | None:
            s = self.series.get(name)
            return None if s is None else s.observed(cal, raw=True)

        if windows:
            bal = self.call(
                "influent", "balance", "mass_balance",
                windows=windows, t=np.asarray(self.loads.t),
                q_in_m3_d=np.asarray(self.loads.q_m3_d),
                cod_in_kg_d=np.asarray(self.loads.cod_kg_d),
                tkn_in_kg_n_d=np.asarray(self.loads.tkn_kg_n_d),
                charge_in_keq_d=np.asarray(self.loads.charge_keq_d),
                gas_flow=obs("gas_flow"), ch4_fraction=obs("ch4_fraction"),
                cod_out=obs("cod_total"), tan_out=obs("tan"), ph=obs("ph"),
                alkalinity=obs("alkalinity"), vfa=obs("vfa_total"),
                V_liq_m3=float(geometry["V_liq_m3"]), T_op_K=t_op,
            )  # fmt: skip
            self.balance_index = self.rec.last_index
            cod = [w.cod_closure for w in bal.windows if w.cod_closure is not None]
            self.window_closures = [
                {
                    "start": float(w.window.start),
                    "end": float(w.window.end),
                    "closure": _f(w.cod_closure),
                }
                for w in bal.windows
            ]
            balance = {
                "n_windows": len(bal.windows),
                "n_cod_evaluable": len(cod),
                "n_cod_inadmissible": sum(1 for w in bal.windows if w.cod_admissible is False),
                "cod_closure_windows": [round6(c) for c in cod],
                "cod_closure_mean": round6(np.mean(cod)) if cod else None,
                "charge_drift": round6(bal.charge_drift),
                "charge_consistent": bal.charge_consistent,
                "admissible": bool(bal.admissible),
            }
        else:
            # a record shorter than one balance window: no closure to place (NB is not judged)
            self.balance_index = None
            self.window_closures = []
            balance = {"n_windows": 0, "n_cod_evaluable": 0, "n_cod_inadmissible": 0,
                       "cod_closure_windows": [], "cod_closure_mean": None,
                       "charge_drift": None, "charge_consistent": None,
                       "admissible": True}  # fmt: skip
            self.codes.append("no_balance_window")
        params = list(self.model["parameters"])
        data = [s.observed(cal, raw=True, sd=weights[s.name]) for s in objective]
        morris = self.call(
            "identifiability", "reference", "gsa_morris", model=MODEL, parameters=params,
            outputs=[s.channel for s in objective], summary=str(proc["gsa_summary"]),
            window={"start": cal[0], "end": cal[1]},
            n_trajectories=int(proc["morris_trajectories"]), seed=int(proc["morris_seed"]),
        )  # fmt: skip
        scores: dict[str, float] = {}
        for res in morris.results:
            mu = np.asarray(res.mu_star, dtype=float)
            top = float(np.nanmax(mu)) if np.isfinite(mu).any() and np.nanmax(mu) > 0 else 1.0
            for name, v in zip(morris.parameters, mu, strict=True):
                scores[name] = max(
                    scores.get(name, 0.0), float(v) / top if math.isfinite(v) else 0.0
                )
        ranking = sorted(params, key=lambda n: -scores.get(n, 0.0))
        kept = [n for n in ranking if scores.get(n, 0.0) >= float(proc["morris_min_relative"])]
        kept = kept[: int(proc["subset_max"])]
        if len(kept) < int(proc["subset_min"]):
            kept = ranking[: int(proc["subset_min"])]
        fim = self.call("identifiability", "reference", "fisher_info", model=MODEL, data=data,
                        parameters=kept, at={})  # fmt: skip
        relative: dict[str, float | None] = {}
        for name, sd in zip(fim.parameters, np.asarray(fim.crlb_sd, dtype=float), strict=True):
            width_b = self.model["upper"][name] - self.model["lower"][name]
            relative[name] = float(sd / width_b) if math.isfinite(sd) else None
        limit = float(proc["max_relative_crlb"])
        ok = [n for n in kept if relative[n] is not None and relative[n] <= limit]
        if len(ok) < int(proc["subset_min"]):
            ok = sorted(kept, key=lambda n: relative[n] if relative[n] is not None else np.inf)[
                : int(proc["subset_min"])
            ]
        approved = [n for n in kept if n in ok]
        fit = self.call(
            "calibration", "reference", "fit_lsq", model=MODEL, data=data, parameters=approved,
            n_starts=int(proc["lsq_starts"]),
            max_nfev_per_start=int(proc["lsq_max_nfev_per_start"]),
            seed=int(proc["fit_seed"]),
        )  # fmt: skip
        optimum = {n: float(v) for n, v in zip(fit.parameters, np.asarray(fit.theta), strict=True)}
        fitted = self.call("calibration", "reference", "simulate", model=MODEL, parameters=optimum)
        self.prediction, self.prediction_index = fitted, self.rec.last_index
        self.reference_prediction = fitted
        self.reference_fit, self.reference_optimum = fit, dict(optimum)
        self.fit, self.optimum, self.approved = fit, optimum, list(approved)
        self.screening = {
            "declared": params,
            "morris_ranking": ranking,
            "morris_kept": kept,
            "fisher_dropped": [n for n in kept if n not in ok],
            "fisher_relative_crlb": {n: round6(v) for n, v in relative.items()},
            "approved": list(approved),
        }
        channels = {}
        for name, s in self.series.items():
            after = (z_summary(s.t, s.raw, weights[name], fitted.t, fitted.outputs[s.channel], cal)
                     if s.channel in fitted.outputs else None)  # fmt: skip
            if default.get(name) is None or after is None:
                continue
            channels[name] = {
                "channel": s.channel,
                "n": default[name]["n"],
                "at_defaults": {k: default[name][k] for k in ("mean_z", "rms_z")},
                "after_fit": {k: after[k] for k in ("mean_z", "rms_z")},
            }
        return {
            "balance": balance,
            "channels": channels,
            "fit": {"parameters": list(fit.parameters), "chi2": round6(fit.chi2),
                    "at_bound": list(fit.at_bound), "converged": bool(fit.converged)},
        }  # fmt: skip

    # -- the null table (verifier, S7) ----------------------------------------------
    def step_null(self) -> None:
        """S7: the reference fit's statistics against the band as published (§2.7)."""
        role = "verification" if self.switch["verifier"] else "calibration"
        band = self.call(role, "null", "declared_background", plant=self.plant, tier=self.tier)
        self.band = band.model_dump(mode="json")
        if self.reference is None:
            self.checkpoint("null")
            return
        self.placement = band_placement(record_statistics(self.reference), self.band)
        if not self.placement:
            # nothing to place is no null table, not a null that stands (the review's F-H)
            self.codes.append("no_statistics_placed")
            self.checkpoint("null")
            return
        if self.switch["verifier"]:
            self.table = null_table(self.placement)
            self.log.send("table", "verification", "coordination", "null",
                          {"kind": "null", **{k: v for k, v in self.table.items()
                                              if k != "placement"}})  # fmt: skip
            if self.table["null_partial"]:
                self.codes.append("null_partial")
        self.checkpoint("null")

    # -- SCREEN (identifiability) --------------------------------------------------
    def step_screen(self) -> None:
        """``ident.subset`` over the forced list and the screen (§2.4)."""
        if not self.on["identifiability"] or self.reference is None:
            self.plan.skipped["screen"] = "the identifiability role is off, or no reference"
            return
        forced = list(self.cfg["forced_candidates"].get(self.plant, []))
        pool = set(forced) | set(self.screening.get("morris_kept", []))

        def check(o: BaseModel) -> bool:
            return set(o.parameters) <= pool

        choice = self.decider.decide(
            "ident.subset",
            {"forced": forced, "morris_ranking": self.screening.get("morris_ranking", []),
             "morris_kept": self.screening.get("morris_kept", []),
             "relative_crlb": self.screening.get("fisher_relative_crlb", {})},
            {"parameters": list(self.approved)},
            check=check,
        )  # fmt: skip
        self.screening["forced"] = forced
        if list(choice.parameters) != list(self.approved):
            self._subset_fit(list(choice.parameters))
        self.checkpoint("screen")

    def _subset_fit(self, params: list[str]) -> None:
        fit_cfg = self.p0["fit"]
        k, nfev = len(params), int(fit_cfg["lsq_max_nfev_per_start"])
        bound = nfev + 2 * k + 1 + 2 * k
        if not self.plan.fits("subset_lsq", bound):
            self.plan.fallbacks.append(f"subset_lsq: {bound} evaluations do not fit")
            return
        data = [s.observed(self.cal) for s in self.series.values() if s.in_objective]
        start = {n: self.optimum.get(n, 1.0) for n in params}
        try:
            fit = self.call("calibration", "fit", "fit_lsq", model=MODEL, data=data,
                            parameters=params, start=start, n_starts=1, max_nfev_per_start=nfev,
                            seed=int(self.p0["seeds"]["lsq"]))  # fmt: skip
        except tools.ToolError as exc:
            self.rec.failure("calibration.fit", "fit_lsq", "error", str(exc), "reference stands")
            return
        ref_chi2 = float(self.fit.chi2)
        accept = self.decider.decide(
            "cal.accept",
            {"chi2": _f(fit.chi2), "converged": bool(fit.converged), "reference_chi2": ref_chi2,
             "at_bound": list(fit.at_bound)},
            {"accept": float(fit.chi2) <= ref_chi2,
             "code": "converged" if float(fit.chi2) <= ref_chi2 else "worse_than_reference"},
        )  # fmt: skip
        if accept.accept:
            self.fit, self.approved = fit, list(params)
            self.optimum = {n: float(v) for n, v in zip(fit.parameters, fit.theta, strict=True)}
            self.prediction = self.call("calibration", "fit", "simulate", model=MODEL,
                                        parameters=self.optimum)  # fmt: skip
            self.prediction_index = self.rec.last_index

    # -- FIT (calibration) ---------------------------------------------------------
    def intervals_from_fit(self) -> None:
        """Fisher intervals from the fit's Jacobian covariance (P0's, clipped to bounds)."""
        z = float(self.p0["uncertainty"]["z"])
        self.final_parameters = {}
        fit = self.fit
        if fit is None:
            return
        sd = None if fit.sd is None else np.asarray(fit.sd, dtype=float)
        for i, name in enumerate(fit.parameters):
            est = float(fit.theta[i])
            lo = hi = None
            if sd is not None and math.isfinite(sd[i]):
                lo = max(est - z * float(sd[i]), self.model["lower"][name])
                hi = min(est + z * float(sd[i]), self.model["upper"][name])
            self.final_parameters[name] = {
                "estimate": est, "lower": _f(lo), "upper": _f(hi),
                "method": "fisher" if lo is not None else "none",
                "at_bound": name in fit.at_bound,
                "unit": str(self.model["units"].get(name, "")),
            }  # fmt: skip
            if name in fit.at_bound:
                self.decider.decide(
                    "cal.bound",
                    {"parameter": name, "bounds": [self.model["lower"][name],
                                                   self.model["upper"][name]],
                     "estimate": est, "sd": _f(sd[i]) if sd is not None else None},
                    {"code": "identifiability_limit"},
                )  # fmt: skip
        self.interval_method = "fisher" if sd is not None else "none"

    def step_mcmc(self) -> None:
        """``bayes_mcmc`` by procedure; ``posterior_intervals`` abstained only after a failure."""
        mc, plan = self.p0["mcmc"], self.p0["plan"]
        if self.fit is None or not self.on["calibration"]:
            self.plan.skipped["mcmc"] = "no fit, or the calibration role is off"
            self.abstentions.append("posterior_intervals")
            return
        params = list(self.fit.parameters)
        walkers = max(int(mc["walkers"]), 2 * len(params))
        out = None
        data = [s.observed(self.cal) for s in self.series.values() if s.in_objective]
        for steps in self.plan.ladder(int(mc["steps"]), int(plan["mcmc_min_steps"])):
            if not self.plan.fits("mcmc", walkers * (steps + 1)):
                self.plan.fallbacks.append(f"mcmc: {steps} steps do not fit")
                continue
            try:
                out = self.call("calibration", "mcmc", "bayes_mcmc", model=MODEL, data=data,
                                parameters=params, start=self.optimum,
                                likelihood=str(mc["likelihood"]), n_walkers=walkers,
                                n_steps=steps, seed=int(self.p0["seeds"]["mcmc"]))  # fmt: skip
            except tools.BudgetExceededError:
                continue
            except tools.ToolError as exc:
                self.rec.failure("calibration.mcmc", "bayes_mcmc", "error", str(exc),
                                 "Fisher intervals stand")  # fmt: skip
                break
            self.plan.sizes["mcmc_steps"], self.plan.sizes["mcmc_walkers"] = steps, walkers
            break
        if out is None or not out.converged:
            if out is not None:
                self.rec.failure("calibration.mcmc", "bayes_mcmc", "not_converged",
                                 f"R-hat max {float(np.nanmax(out.rhat)):.3g}",
                                 "posterior not reported; Fisher intervals stand")  # fmt: skip
            elif "mcmc_steps" not in self.plan.sizes:
                self.plan.skipped["mcmc"] = "no size fitted the plan"
            self.abstentions.append("posterior_intervals")
            self.checkpoint("mcmc")
            return
        q05 = np.asarray(out.quantiles["q05"], dtype=float)
        q95 = np.asarray(out.quantiles["q95"], dtype=float)
        for i, name in enumerate(out.parameters):
            if name in self.final_parameters:
                self.final_parameters[name].update(
                    {"lower": float(q05[i]), "upper": float(q95[i]), "method": "posterior"}
                )
        self.interval_method = "posterior"
        self.checkpoint("mcmc")

    # -- residuals (P0's arithmetic) ------------------------------------------------
    def covariates(self) -> list[dict[str, Any]]:
        """Load, time, feed batch and fractions, temperature (P0's covariates)."""
        t = np.asarray(self.loads.t, dtype=float)
        feeds = sorted(self.feed_log)
        cov = [
            {"name": "load", "t": t, "value": np.asarray(self.loads.cod_kg_d, dtype=float)},
            {"name": "time", "t": t, "value": t},
        ]
        if feeds:
            masses = np.stack([np.asarray(self.feed_log[f], dtype=float) for f in feeds], axis=1)
            total = masses.sum(axis=1)
            cov.append(
                {
                    "name": "feed_batch",
                    "t": t,
                    "value": np.argmax(masses, axis=1).astype(float),
                    "categorical": True,
                }
            )
            for i, f in enumerate(feeds):
                frac = np.where(total > 0, masses[:, i] / np.where(total > 0, total, 1.0), 0.0)
                cov.append({"name": f"feed_{f}", "t": t, "value": frac})  # fmt: skip
        temp = self.series.get("temperature")
        if temp is not None and np.isfinite(temp.value).sum() >= 4:
            m = np.isfinite(temp.value)
            cov.append({"name": "temperature", "t": temp.t[m], "value": temp.value[m]})
        return cov

    def step_residuals(self) -> None:
        """Residual structure of every objective channel against the **reference** fit.

        The signatures read these residuals (the early/late test, the feed covariate,
        the change point, R3), so they are taken on the raw record against the reference
        prediction with the served weights, never against a subset fit a decision chose
        nor on a record a decision quarantined (the review's F-B).
        """
        pred = self.reference_prediction
        if pred is None:
            return
        role = "calibration" if self.on["calibration"] else "identifiability"
        covariates = self.covariates()
        transient = self.cal[0] + float(self.attr["transient_d"])
        self.residuals = {}
        for s in self.series.values():
            if not s.in_objective or s.channel not in pred.outputs:
                continue
            m = np.isfinite(s.raw) & (s.t >= self.cal[0]) & (s.t <= self.cal[1])
            t = s.t[m]
            r = s.raw[m] - np.interp(
                t,
                np.asarray(pred.t, dtype=float),
                np.asarray(pred.outputs[s.channel], dtype=float),
            )
            if r.size < 4:
                continue
            z = r / self.reference_sd.get(s.name, s.sd)[m]
            n = int(z.size)
            se = (
                float(z.std(ddof=1) / math.sqrt(n))
                if n > 1 and z.std(ddof=1) > 0
                else 1 / math.sqrt(n)
            )
            summary: dict[str, Any] = {"channel": s.channel, "n": n, "bias_z": _f(z.mean() / se),
                                       "rmse_z": _f(math.sqrt(float(np.mean(z**2))))}  # fmt: skip
            best_z, best_day = 0.0, None
            for cut in range(4, n - 4):
                a, b = z[:cut], z[cut:]
                pooled = math.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
                if pooled > 0 and abs(float(a.mean() - b.mean())) / pooled > best_z:
                    best_z, best_day = abs(float(a.mean() - b.mean())) / pooled, float(t[cut])
            summary["step_z"] = _f(best_z) if best_day is not None else None
            summary["step_day"] = best_day

            def bias(x: np.ndarray) -> float | None:
                if x.size < 3:
                    return None
                s_e = x.std(ddof=1) / math.sqrt(x.size)
                return _f(x.mean() / s_e) if s_e > 0 else None

            summary["early_bias_z"] = bias(z[t <= transient])
            summary["late_bias_z"] = bias(z[t > transient])
            try:
                out = self.call(role, "residuals", "residual_diag", t=t, residual=r,
                                covariates=covariates)  # fmt: skip
                summary.update({
                    "serially_structured": bool(out.serially_structured),
                    "lag1_autocorrelation": _f(out.lag1_autocorrelation) or 0.0,
                    "trend_slope_per_d": _f(out.trend_slope_per_d) or 0.0,
                    "most_explanatory": out.most_explanatory,
                    "covariate_eta2": {c.name: (_f(c.eta_squared) or 0.0)
                                       for c in out.covariates if c.structured},
                    "call_index": self.rec.last_index,
                })  # fmt: skip
            except tools.ToolError as exc:
                self.rec.failure(f"{role}.residuals", "residual_diag", "error", str(exc),
                                 "time statistics only")  # fmt: skip
                summary.update({"serially_structured": False, "lag1_autocorrelation": 0.0,
                                "trend_slope_per_d": 0.0, "most_explanatory": None,
                                "covariate_eta2": {}})  # fmt: skip
            self.residuals[s.name] = summary
        self.checkpoint("residuals")

    # -- the code signatures ---------------------------------------------------------
    def step_state_test(self) -> None:
        """The early/late test (code) and, when it fires, the ``biomass_scale`` pair (§2.5)."""
        firing = early_late(self.residuals, self.attr)
        improves = False
        pair: dict[str, Any] = {}
        if firing and self.on["calibration"] and self.reference_prediction is not None:
            early = (self.cal[0], self.cal[0] + float(self.attr["transient_d"]))

            def early_rms(sim: Any) -> float:
                vals = []
                for name in firing:
                    s = self.series[name]
                    sd = self.reference_sd.get(name, s.sd)
                    summ = z_summary(s.t, s.raw, sd, sim.t, sim.outputs[s.channel], early)
                    if summ is not None:
                        vals.append(float(summ["rms_z"]))
                return float(np.mean(vals)) if vals else float("inf")

            # the reference fit's prediction and optimum, never a subset fit's (F-B)
            reference = early_rms(self.reference_prediction)
            for scale in self.cfg["biomass_scales"]:
                if not self.plan.fits("biomass_pair", 1):
                    self.plan.skipped["biomass_pair"] = "the plan does not allow it"
                    break
                sim = self.call("calibration", "state_test", "simulate", model=MODEL,
                                parameters=self.reference_optimum,
                                biomass_scale=float(scale))  # fmt: skip
                pair[str(scale)] = early_rms(sim)
            improves = any(v < reference for v in pair.values())
            pair["reference"] = reference
        self.signatures["early_late"] = firing
        self.signatures["biomass_pair"] = pair
        self.signatures["biomass_improves"] = improves
        self.log.send("table", "identifiability", "coordination", "state_test",
                      {"kind": "early_late", "firing": firing, "pair": pair,
                       "improves": improves})  # fmt: skip
        self.checkpoint("state_test")

    def step_profile(self) -> None:
        """The S1 table, the onset test, the change point, the inhibition check (code)."""
        p, coupled = self.placement, self.cfg["coupled_channels"]
        failed = failed_channels(p) if p else []
        # S1 (data quality)
        sensor: dict[str, Any] = {}
        if self.on["data_quality"] and self.table is not None and self.table["NS"]:
            channel = failed[0]
            table = s1_table(channel, p, coupled)
            reading = self.decider.decide("dq.coupled", {"s1_table": table, "assays": []},
                                          {"sensor": channel, "code": "insufficient"})  # fmt: skip
            sensor = {"channel": channel, "s1": table, "reading": reading.code,
                      "s1_holds": table["coupled_inside"]
                      and reading.code in ("coupled_inside", "assay_implicates")}  # fmt: skip
            self.tables["s1"] = table
        self.signatures["sensor"] = sensor
        self.signatures["sensor_proposed"] = bool(sensor.get("channel"))
        # the onset test (influent)
        primary = self.residuals.get(self.p0["calibration"]["primary_channel"])
        feed = feed_covariate(primary, self.attr)
        onset: dict[str, Any] = {"passes": False, "code": "influent_off"}
        candidates: list[float] = []
        if self.reference is not None and self.band and self.band.get("cod_closure_windows"):
            env = (float(self.band["cod_closure_windows"]["min"]),
                   float(self.band["cod_closure_windows"]["max"]))  # fmt: skip
            side = nb_side(p)
            candidates = candidate_onsets(self.window_closures, env, side, self.cfg["onset"])
            if self.on["influent"]:
                proposal = self.decider.decide(
                    "influent.onset",
                    {"feed_log": {k: _jsonable(v) for k, v in self.feed_log.items()},
                     "notes": list(self.notes), "window_closures": self.window_closures,
                     "window_envelope": list(env)},
                    {"onset_day": None, "feed_id": None, "anchors": []},
                )  # fmt: skip
                onset = onset_test(self.window_closures, env, side, proposal.onset_day,
                                   self.cfg["onset"])  # fmt: skip
                ev = [i for i, w in enumerate(self.window_closures) if w["closure"] is not None]
                worst = max(ev, key=lambda i: abs(self.window_closures[i]["closure"])) if ev else 0
                self.decider.decide("influent.window", {"window_closures": self.window_closures},
                                    {"window_index": worst})  # fmt: skip
                self.decider.decide("influent.mechanism",
                                    {"balance": self.reference["balance"], "onset": onset},
                                    {"code": "none"})  # fmt: skip
        self.signatures["onset"] = onset
        self.signatures["candidate_onsets"] = candidates
        self.signatures["feed_covariate"] = feed
        self.signatures["influent"] = self.on["influent"] and (onset["passes"] or feed)
        self.signatures["influent_proposed"] = self.on["influent"] and (
            bool(self.table and self.table["NB"]) or feed
        )
        # the change point and the inhibition check (calibration); the admitting change
        # point is tied to the failed channels and lies after the first HRT (2026-10-08)
        change = common_change_point(self.residuals, self.attr)
        transient_end = self.cal[0] + float(self.attr["transient_d"])
        tied = tied_change_point(self.residuals, failed, self.attr, transient_end)
        if self.on["calibration"]:
            steps = {ch: {"step_z": r.get("step_z"), "step_day": r.get("step_day")}
                     for ch, r in self.residuals.items()}  # fmt: skip

            def agrees(o: BaseModel) -> bool:
                return o.common_step_day is None or (
                    change["common"]
                    and abs(o.common_step_day - change["day"])
                    <= float(self.attr["step_day_tolerance_d"])
                )

            self.decider.decide("cal.split", {"steps": steps},
                                {"common_step_day": change["day"], "channels": change["channels"]},
                                check=agrees)  # fmt: skip
        inhib = inhibition(p) if p else {"available": False, "inhibited": False}
        self.signatures["change_point"] = change
        self.signatures["change_point_tied"] = tied
        self.signatures["inhibition"] = inhib
        self.signatures["parameter"] = self.on["calibration"] and (
            tied["common"] or inhib["inhibited"]) and not feed  # fmt: skip
        self.signatures["parameter_proposed"] = change["common"] or inhib["inhibited"]
        if change["common"] and not tied["common"] and not inhib["inhibited"]:
            self.signatures["parameter_code"] = "change_point_not_on_failed_channels_after_hrt"
        firing = self.signatures.get("early_late", [])
        self.signatures["initial_state"] = bool(set(firing) & set(failed)) and bool(
            self.signatures.get("biomass_improves")
        )
        self.signatures["initial_state_proposed"] = bool(firing)
        ref_fit = self.reference_fit
        at_bound = bool(ref_fit is not None and list(ref_fit.at_bound))
        r3_all = structured_channels(self.residuals, self.attr, at_bound)
        r3 = [c for c in r3_all if c in set(failed)]  # R3 on failed channels (2026-10-08)
        need = int(self.attr["structural_channels_min"])
        self.signatures["r3"] = len(r3) >= need
        self.signatures["r3_channels"] = r3
        self.signatures["r3_channels_all"] = r3_all
        self.signatures["structural_proposed"] = len(r3_all) >= need
        if len(r3_all) >= need and len(r3) < need:
            self.signatures["structural_code"] = "r3_not_on_failed_channels"
        for key in ("sensor", "influent", "initial_state", "parameter", "structural"):
            if self.signatures.get(f"{key}_proposed"):
                self.log.send(
                    "finding",
                    "coordination",
                    "verification",
                    "propose",
                    {"label": self.lab[key], "signature": bool(self.signatures.get(key))},
                )
        self.checkpoint("profile")

    # -- assays (design) -------------------------------------------------------------
    def step_assays(self) -> None:
        """``design.assay``: P0's declared spend as the fallback (§2.6)."""
        if not self.on["design"] or self.prediction is None:
            self.plan.skipped["assays"] = "the design role is off, or no prediction"
            return
        primary = self.series.get(self.p0["calibration"]["primary_channel"])
        if primary is None or primary.channel not in self.prediction.outputs:
            return
        m = np.isfinite(primary.value) & (primary.t >= self.cal[0]) & (primary.t <= self.cal[1])
        if not m.any():
            return
        pred = np.interp(
            primary.t[m],
            np.asarray(self.prediction.t, dtype=float),
            np.asarray(self.prediction.outputs[primary.channel], dtype=float),
        )
        day = float(primary.t[m][int(np.argmax(np.abs((primary.value[m] - pred) / primary.sd[m])))])
        catalogue = self.cfg["assay_catalogue"]
        prefs = list(self.p0["assays"]["preference"])
        requests = 0
        while prefs and requests < int(self.p0["assays"]["max_requests"]):
            units = int(tools.remaining().assay_units)
            fallback = next((a for a in prefs if int(catalogue[a]["unit_cost"]) <= units), None)
            choice = self.decider.decide(
                "design.assay",
                {"request": "largest_primary_residual", "voi": None,
                 "price_list": catalogue, "units_left": units},
                {"assay": fallback, "day": day if fallback else None,
                 "prediction": primary.name if fallback else None},
            )  # fmt: skip
            if choice.assay is None:
                break
            prefs = [a for a in prefs if a != choice.assay]
            try:
                out = self.call("design", "assay", "request_assay", assay=choice.assay,
                                day=float(choice.day))  # fmt: skip
            except tools.ToolError as exc:
                self.rec.failure("design.assay", "request_assay", "error", str(exc), "no assay")
                continue
            requests += 1
            for res in out.results:
                p = None
                if res.channel in self.prediction.outputs:
                    p = float(
                        np.interp(
                            choice.day,
                            np.asarray(self.prediction.t, dtype=float),
                            np.asarray(self.prediction.outputs[res.channel], dtype=float),
                        )
                    )
                zz = (
                    (float(res.value) - p) / float(res.sd) if p is not None and res.sd > 0 else None
                )
                self.assay_checks.append({
                    "assay": choice.assay, "channel": res.channel, "sample_day": float(choice.day),
                    "report_day": float(out.report_day), "value": float(res.value),
                    "unit": res.unit, "sd": float(res.sd), "predicted": _f(p), "z": _f(zz),
                    "disagrees": bool(zz is not None
                                      and abs(zz) >= float(self.p0["assays"]["disagreement_z"])),
                })  # fmt: skip
        self.checkpoint("assays")

    # -- VERIFY -----------------------------------------------------------------------
    def holdout_check(self) -> dict[str, Any]:
        """``holdout_failed`` (§12, question 3), from the verifier's own ``validate`` call.

        The call scores the **reference** prediction (the reference fit on the raw record,
        never a subset fit a decision chose) over the hold-out, in standardised form: the
        observed series is each sample's residual over its declared sd (the served floors)
        and the prediction is zero, so the tool's ``rmse`` is the hold-out ``rms_z``. The
        bit fails when enough channels' ``rms_z`` are above the band's after-fit maximum.
        It is ``None`` when the call cannot be made or fails (no hold-out bit, logged).
        """
        pred = self.reference_prediction
        out: dict[str, Any] = {"holdout_failed": None, "rms_z": {}, "call": None}
        if pred is None:
            return out
        t_pred = np.asarray(pred.t, dtype=float)
        observed, names = [], {}
        for name, s in self.series.items():
            if not s.in_objective or s.channel not in pred.outputs or s.count(self.holdout) < 1:
                continue
            sd = self.reference_sd.get(name, s.sd)
            z = (s.raw - np.interp(s.t, t_pred, np.asarray(pred.outputs[s.channel], float))) / sd
            observed.append({"output": s.channel, "t": s.t, "value": z,
                             "sd": np.ones(s.t.shape), "unit": "-"})  # fmt: skip
            names[s.channel] = name
        if not observed:
            return out
        try:
            val = self.call("verification", "holdout", "validate", observed=observed, t=t_pred,
                            predicted={o["output"]: np.zeros(t_pred.shape) for o in observed},
                            holdout={"start": self.holdout[0], "end": self.holdout[1]})  # fmt: skip
        except tools.ToolError as exc:
            self.rec.failure("verification.holdout", "validate", "error", str(exc),
                             "no hold-out bit")  # fmt: skip
            return out
        out["call"] = self.rec.last_index
        failed = 0
        for m in val.results:
            name = names.get(m.output)
            band = (self.band or {}).get("channels", {}).get(name)
            rms = _f(m.rmse)
            out["rms_z"][name] = rms
            if band is not None and rms is not None:
                failed += int(rms > float(band["after_fit"]["rms_z"]["max"]))
        out["holdout_failed"] = failed >= int(self.cfg["holdout"]["min_channels_failed"])
        return out

    def validate(self, role: str, step: str) -> dict[str, Any] | None:
        """One ``validate`` call on the current prediction over the hold-out."""
        observed = [s.observed((0.0, self.T)) for s in self.series.values()
                    if s.in_objective and s.count(self.holdout) >= 1]  # fmt: skip
        if not observed or self.prediction is None:
            return None
        predicted = {o["output"]: np.asarray(self.prediction.outputs[o["output"]], dtype=float)
                     for o in observed}  # fmt: skip
        try:
            if role == "harness":
                out = self.rec.call(
                    "harness",
                    step,
                    "validate",
                    observed=observed,
                    t=np.asarray(self.prediction.t),
                    predicted=predicted,
                    holdout={"start": self.holdout[0], "end": self.holdout[1]},
                )
            else:
                out = self.call(
                    role,
                    step,
                    "validate",
                    observed=observed,
                    t=np.asarray(self.prediction.t),
                    predicted=predicted,
                    holdout={"start": self.holdout[0], "end": self.holdout[1]},
                )
        except tools.ToolError as exc:
            self.rec.failure(f"{role}.{step}", "validate", "error", str(exc), "no validation")
            return None
        metrics = {m.output: {"n": float(m.n), "mae": _f(m.mae), "rmse": _f(m.rmse),
                              "nrmse": _f(m.nrmse), "bias": _f(m.bias),
                              "coverage_50": _f(m.coverage.get("50")),
                              "coverage_90": _f(m.coverage.get("90")),
                              "interval_score_90": _f(m.interval_score.get("90")),
                              "crps": _f(m.crps)}
                   for m in out.results}  # fmt: skip
        return {"holdout": [self.holdout[0], self.holdout[1]], "ensemble": bool(out.ensemble),
                "ensemble_size": 0, "metrics": metrics,
                "constraint_violations": int(sum(int(m.constraint_violations)
                                                 for m in out.results)),
                "calls": [self.rec.last_index]}  # fmt: skip

    def step_verify(self) -> None:
        """Admission, the hold-out bit, the differential, the verdict (§2.7, §5)."""
        lab = self.lab
        if self.reference is None or not self.placement:
            self.verdict = {
                "verdict": "abstain",
                "label": lab["none"],
                "admitted": [],
                "rejected": [],
                "holdout_failed": None,
                "reason": "no_null_table" if self.reference is None else "no_statistics_placed",
            }
            self.checkpoint("verify")
            return
        if not self.switch["verifier"]:
            labels = [lab[k] for k in P0_ORDER if self.signatures.get(k)]
            self.verdict = {
                "verdict": "unverified",
                "label": first_in_p0_order(lab, labels),
                "admitted": labels,
                "rejected": [],
                "holdout_failed": None,
            }
            self.checkpoint("verify")
            return
        holdout = self.holdout_check()
        self.tables["holdout"] = holdout
        holdout_failed = holdout["holdout_failed"]
        self.signatures["holdout_failed"] = holdout_failed
        self.signatures["structural"] = bool(self.signatures.get("r3", False) and holdout_failed)
        rounds = 2 if (self.switch["self_correction"] and self.switch["coordinator"]) else 1
        result: dict[str, Any] = {}
        for round_ in range(rounds):
            result = admit(lab, self.table, self.signatures)
            choice = self.decider.decide(
                "verify.differential",
                {"null_table": {k: v for k, v in self.table.items() if k != "placement"},
                 "admitted": result["admitted"], "tables": {"s1": self.tables.get("s1")},
                 "holdout_failed": holdout_failed},
                {"label": first_in_p0_order(lab, result["admitted"]),
                 "rejected": result["rejected"]},
                check=lambda o, adm=result["admitted"]: o.label in [*adm, lab["none"]],
            )  # fmt: skip
            # a fail is a rejected null that no admitted label explains; a signature
            # rejected because the null stands is the null case working: a pass on none
            verdict = "pass" if result["admitted"] or not self.table["null_rejected"] else "fail"
            self.verdict = {"verdict": verdict, "label": choice.label, **result,
                            "holdout_failed": holdout_failed, "round": round_ + 1}  # fmt: skip
            self.log.send("verdict", "verification", "coordination", "verify",
                          {k: v for k, v in self.verdict.items()})  # fmt: skip
            if verdict == "pass" or round_ + 1 == rounds:
                break
            # REVISE: the failing codes go back; offline, no decision can change
            self.codes.append("revise")
            self.trace.append("revise")
        self.checkpoint("verify")

    # -- CONCLUDE ---------------------------------------------------------------------
    def step_conclude(self) -> None:
        """The final label, its evidence, the abstentions and the final validation."""
        lab, attr, v = self.lab, self.attr, self.verdict
        label = v.get("label", lab["none"])
        rejected_null = bool(self.table and self.table["null_rejected"])
        if v.get("verdict") == "abstain":
            label, conf, rule = lab["none"], 0.0, f"abstain:{v['reason']}"
            self.abstentions += ["kinetic_attribution", "parameter_values", "structural_adequacy"]
        elif v.get("verdict") == "fail" or (label == lab["none"] and rejected_null):
            label, conf, rule = lab["none"], float(attr["confidence"]["multiple"]), \
                "null_failed_unexplained"  # fmt: skip
            self.codes.append("null_failed_unexplained")
        elif label == lab["none"]:
            conf, rule = float(attr["confidence"]["none"]), "null_stands"
        else:
            n = len(v.get("admitted", []))
            conf = float(attr["confidence"]["single" if n == 1 else "multiple"])
            if self.table is None:
                # the verifier is off: no null component was evaluated, so none is named
                component = "unverified"
            elif label == lab["influent"]:
                component = "NB"
            else:
                component = "NS" if self.table["NS"] else "NM"
            rule = f"{component}+{label}"
        secondary = [x for x in v.get("admitted", []) if x != label]
        flag = None
        scale: dict[str, float] = {}
        if label == lab["sensor"]:
            flag = self.signatures["sensor"]["channel"]
            if flag == "gas_flow":
                f = self.scale_factor(flag)
                if f is not None:
                    scale[flag] = f
        if label in (lab["sensor"], lab["influent"], lab["structural"]):
            self.abstentions.append("kinetic_attribution")
        if label == lab["structural"]:
            self.abstentions += ["parameter_values"] + [
                f"{self.residuals[c]['channel']}_budget" for c in self.signatures["r3_channels"]
            ]
        if label != lab["none"]:
            self.evidence.append({
                "rule": rule, "label": label,
                "statement": f"{rule}: the null case failed and the signature holds",
                "values": {"n_outside": self.table["n_outside"] if self.table else None,
                           "failed_channels": ",".join(self.table["failed_channels"])
                           if self.table else ""},
                "calls": [c for c in (self.prediction_index, self.balance_index) if c is not None],
            })  # fmt: skip
        vocab = set(self.cfg.get("abstentions", {}))
        self.abstentions = sorted({a for a in self.abstentions if not vocab or a in vocab})
        self.classification = {
            "label": label, "secondary_labels": secondary, "confidence": conf, "rule": rule,
            "evidence": self.evidence, "flag_sensor": flag, "scale_factor": scale,
            "revise_influent_mapping": label == lab["influent"],
            "recommend_structural_review": label == lab["structural"],
            "kinetic_update": label in (lab["parameter"], lab["none"]),
        }  # fmt: skip
        self.validation = self.validate("harness", "final")
        self.checkpoint("conclude")

    def scale_factor(self, sensor: str) -> float | None:
        """Median observed over predicted after the step (P0's), for a gas-meter label."""
        s = self.series[sensor]
        m = np.isfinite(s.value) & (s.t >= self.cal[0]) & (s.t <= self.cal[1])
        pred = np.interp(
            s.t[m],
            np.asarray(self.prediction.t, dtype=float),
            np.asarray(self.prediction.outputs[s.channel], dtype=float),
        )
        day = self.residuals.get(sensor, {}).get("step_day")
        after = (s.t[m] >= day) if day is not None else np.ones(int(m.sum()), dtype=bool)
        ok = after & (pred > 0)
        return _f(np.median(s.value[m][ok] / pred[ok])) if ok.sum() >= 3 else None

    # -- the record ----------------------------------------------------------------------
    def build_state(self, completed: bool) -> dict[str, Any]:
        """The shared task state (§6.6) with ``workflow`` = p2."""
        rem = tools.remaining()
        cls = self.classification or {
            "label": self.lab["none"], "secondary_labels": [], "confidence": 0.0,
            "rule": "pending", "evidence": [], "flag_sensor": None, "scale_factor": {},
            "revise_influent_mapping": False, "recommend_structural_review": False,
            "kinetic_update": False,
        }  # fmt: skip
        dq = {name: {"status": s.status, "flags": list(s.flags),
                     "missing_fraction": _f(s.missing_fraction),
                     "quarantined_windows": [list(w) for w in s.quarantined],
                     "in_objective": bool(s.in_objective), "notes": ""}
              for name, s in self.series.items()}  # fmt: skip
        scr = {k: v for k, v in self.screening.items()
               if k in ("morris_ranking", "morris_kept", "fisher_dropped",
                        "fisher_relative_crlb")}  # fmt: skip
        balance = {}
        if self.reference is not None:
            balance = {k: v for k, v in self.reference["balance"].items()
                       if k != "cod_closure_windows"}  # fmt: skip
        return {
            "schema_version": "1.0",
            "workflow": str(self.cfg["workflow"]),
            "workflow_version": str(self.cfg["workflow_version"]),
            "run_id": str(self.manifest["run_id"]),
            "plant": self.plant,
            "tier": self.tier,
            "duration_days": self.T,
            "calibration_window": [self.cal[0], self.cal[1]],
            "holdout_window": [self.holdout[0], self.holdout[1]],
            "candidate_model": MODEL,
            "model_parameters": list(self.model.get("parameters", [])),
            "calibrated_outputs": [s.channel for s in self.series.values() if s.in_objective],
            "data_quality": dq,
            "mass_balance": balance,
            "classification": cls,
            "screening": {
                "declared": list(self.model.get("parameters", [])),
                "approved": list(self.approved),
                **scr,
            },
            "residuals": {
                r["channel"]: {k: v for k, v in r.items() if k not in ("call_index", "channel")}
                for r in self.residuals.values()
            },
            "actions": list(self.rec.actions),
            "tool_failures": list(self.rec.failures),
            "budget": {
                "simulator_evals": int(rem.simulator_evals),
                "simulator_evals_total": int(rem.simulator_evals_total),
                "simulator_evals_used": int(rem.simulator_evals_total) - int(rem.simulator_evals),
                "wall_clock_min": float(rem.wall_clock_min),
                "wall_clock_min_total": float(rem.wall_clock_min_total),
                "assay_units": int(rem.assay_units),
                "assay_units_total": int(rem.assay_units_total),
                "assay_units_used": int(rem.assay_units_total) - int(rem.assay_units),
                "n_calls": int(rem.n_calls),
            },
            "validation": self.validation,
            "assay_checks": list(self.assay_checks),
            "abstentions": sorted(set(self.abstentions)),
            "final": {
                "label": cls["label"],
                "secondary_labels": cls["secondary_labels"],
                "confidence": cls["confidence"],
                "parameters": self.final_parameters,
                "interval_method": self.interval_method,
                "abstentions": sorted(set(self.abstentions)),
                "completed": bool(completed),
            },
            "plan": {
                "sizes": dict(self.plan.sizes),
                "fallbacks": list(self.plan.fallbacks) + list(self.codes),
                "guards_tripped": list(self.plan.guards),
                "eval_seconds_assumed": float(self.p0["plan"]["eval_seconds_assumed"]),
                "steps_completed": list(self.plan.completed),
                "steps_skipped": dict(self.plan.skipped),
            },
            "notes_seen": list(self.notes),
            "annotations": [
                f"decider: {self.cfg['decider']}",
                f"routing: {' > '.join(self.trace)}",
                f"ablation: {json.dumps(self.switch, sort_keys=True)}",
                f"codes: {sorted(set(self.codes))}",
                *self.annotations,
            ],
        }

    def build_report(self, doc: dict[str, Any]) -> dict[str, Any]:
        """The human-readable report, with the null table and the signatures."""
        cls = doc["classification"]
        return {
            "workflow": doc["workflow"],
            "run_id": doc["run_id"],
            "label": cls["label"],
            "outcome": outcome(self.verdict, bool(doc["final"]["completed"]), cls["label"]),
            "confidence": cls["confidence"],
            "rule": cls["rule"],
            "abstentions": doc["abstentions"],
            "null_table": self.table,
            "signatures": json.loads(json.dumps(self.signatures, default=_jsonable)),
            "verdict": self.verdict,
            "by_role": self.rec.by_role,
            "refusals": self.rec.refusals,
            "decisions": len(self.decider.records),
            "completed": doc["final"]["completed"],
        }

    # -- the run -------------------------------------------------------------------------
    def run(self) -> None:
        """The state machine of §5, in its fixed order.

        A model cap reached at any decision point stops the run's decisions: it abstains
        (``abstain:model_cap``), and the record says where (deliverable 3, F-E).
        """
        try:
            self.step_read()
            self.step_qc()
            self.step_reference()
            self.step_null()
            if self.reference is not None and self.placement:
                self.step_screen()
                self.intervals_from_fit()
                self.step_mcmc()
                self.step_residuals()
                self.step_state_test()
                self.step_profile()
                self.step_assays()
            self.step_verify()
        except ModelCapReached as exc:
            self.codes.append("model_cap")
            self.annotations.append(f"model cap reached after {self.trace}: {str(exc)[:200]}")
            self.verdict = {
                "verdict": "abstain",
                "label": self.lab["none"],
                "admitted": [],
                "rejected": [],
                "holdout_failed": None,
                "reason": "model_cap",
            }
        self.step_conclude()
        self.completed = True
        self.write(completed=True)


def responder_for(cfg: dict[str, Any]) -> Responder:
    """The decider the jail document names: live only if it says ``live``.

    The runner writes ``live`` only on its explicit flag; anything else, the default
    included, is the offline decider, which never calls ``tools.llm``.
    """
    return LiveResponder() if cfg.get("decider") == "live" else offline_responder


def main() -> int:
    """Run P2 on the run the registry serves."""
    with open(CONFIG_FILE, encoding="utf-8") as fh:
        cfg = json.load(fh)
    workflow = Workflow(cfg, responder_for(cfg))
    try:
        workflow.run()
    except Exception as exc:
        workflow.annotations.append(f"stopped: {type(exc).__name__}: {str(exc)[:200]}")
        try:
            workflow.write(completed=False)
        finally:
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
