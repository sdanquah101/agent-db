"""The evidence module (``docs/p2_agents_design.md`` §2): the admission, shared by both arms.

Staged into the jail with its package (``tools/sandbox.py``, the lead's option A of
2026-10-26): the entry ``workflow.py`` imports it by the same dotted name as the host,
``workflows.p2_multi_agent.evidence``. Two admissions live here:

* :func:`admit`, the procedural arm's rule, frozen on 2026-10-07 (``docs/p2_design.md``
  §4.4) and moved here **verbatim** from ``workflow.py`` (a test pins its source to the
  frozen digest);
* :func:`admit_agent`, the agent arm's, which equals :func:`admit` on every label but
  ``structural`` and carries the amended ``structural`` case (docs/decisions.md,
  2026-10-25, Q13 and Q14) through :func:`structural_case`; :func:`admissible_alternative`
  is the code check of a verdict's alternative.

Rule 1: nothing here reads the truth store, and nothing here imports beyond the standard
library (a test pins the imports).
"""

from __future__ import annotations

from typing import Any


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
