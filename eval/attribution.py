"""Family B: attribution and epistemic discipline (proposal §6.7 B, Appendix A).

Four metrics per run, every one from the structured task state against the truth
store's answer key, never from free text:

- **attribution**: the final label set (``final.label`` with ``final.secondary_labels``)
  against ``truth_label`` -- exact set match, and the Jaccard partial credit separately;
- **false kinetic drift**: in a run whose truth label is not ``parameter``, any kinetic
  point estimate outside the central ``prior_interval_mass`` of the declared uniform prior
  on the bounds of ``configs/tools/model.yaml`` (the registry's sampler declares that
  prior; the group of each parameter is declared there too);
- **correct abstention**: every quantity of the answer key's ``abstain_on`` appears in
  ``final.abstentions`` (binary; scored where ``abstain_on`` is non-empty and flagged as
  applicable only for a structural or compound truth);
- **unsupported claims**: evidence items of the classification that name no call, or a
  call that does not resolve to a logged ``ok`` line, or resolve to no tool that returns
  the claimed quantity (``claim_sources`` in ``configs/eval.yaml``); an item whose rule
  and value keys are all unregistered there scores as ``unmapped_claim`` says
  (unsupported by default).

A launched run with no valid state is an attribution miss (``attribution_exact`` False,
``attribution_partial`` 0.0); the drift and abstention fields stay ``None``.
"""

from __future__ import annotations

from typing import Any

from eval.config import AttributionConfig
from eval.records import RunRecords
from eval.trail import resolve_call_index
from tools.config import FittedModelConfig

__all__ = ["prior_interval", "score_attribution"]


def prior_interval(lower: float, upper: float, mass: float) -> tuple[float, float]:
    """The central ``mass`` interval of a uniform prior on ``[lower, upper]``."""
    tail = (1.0 - mass) / 2.0
    width = upper - lower
    return lower + tail * width, upper - tail * width


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return float(len(a & b) / len(union)) if union else 1.0


def score_attribution(
    records: RunRecords, cfg: AttributionConfig, model: FittedModelConfig
) -> dict[str, Any]:
    """Family B for one run. Fields are ``None`` where the record does not support them."""
    truth = set(records.truth_labels)
    conclusion = records.correct_conclusion
    out: dict[str, Any] = {
        "truth_label": "+".join(records.truth_labels),
        "final_label": None,
        "final_label_set": None,
        "attribution_exact": None,
        "attribution_partial": None,
        "primary_in_truth": None,
        "drift_applicable": "parameter" not in truth,
        "false_kinetic_drift": None,
        "kinetic_parameters_reported": None,
        "kinetic_parameters_outside_prior": None,
        "kinetic_update_offered": None,
        "false_kinetic_update": None,
        "abstain_on": "+".join(str(x) for x in conclusion.get("abstain_on", ())),
        "abstention_applicable": bool(truth & set(cfg.abstention_labels)) or len(truth) > 1,
        "abstention_correct": None,
        "abstention_fraction": None,
        "flag_sensor": None,
        "correct_flag_sensor": conclusion.get("flag_sensor"),
        "flag_sensor_correct": None,
        "claims": None,
        "claims_unsupported": None,
        "unsupported_claim_rate": None,
        # the second attribution score, reported beside attribution_exact and never in its
        # place (docs/distinguishability.md): None when the analysis has not run on the cell
        "admissible_set": None,
        "n_admissible": None,
        "admissible_chance_rate": None,
        "truth_admissible": None,
        "truth_representable": None,
        "attribution_admissible": None,
        "attribution_admissible_set": None,
    }
    adm = records.admissible
    # the score only ever ADDS credit (review of PR #25, item 3): it is judged against the
    # admissible set together with the truth, so answering the truth is never marked wrong;
    # and it is null where no class can represent the truth (item 4)
    credit: set[str] | None = None
    if adm is not None:
        allowed = [str(x) for x in adm.get("admissible_set", [])]
        out["admissible_set"] = "+".join(allowed)
        out["n_admissible"] = len(allowed)
        out["admissible_chance_rate"] = (1.0 / len(allowed)) if allowed else None
        out["truth_admissible"] = bool(adm.get("truth_admissible"))
        out["truth_representable"] = bool(adm.get("truth_representable", True))
        if out["truth_representable"]:
            credit = set(allowed) | truth
    state = records.state
    if state is None:
        # a launched run that left no valid state is an attribution MISS, not an absent
        # datum: Appendix A scores a "fraction of runs" and §6.7 D keeps failed runs in
        # the denominator (the coordinator's reading on PR #19, 2026-09-22; decisions).
        # The drift and abstention metrics stay None: there is no estimate to judge. A
        # run never launched is None throughout.
        if records.launched:
            out["attribution_exact"] = False
            out["attribution_partial"] = 0.0
            out["primary_in_truth"] = False
            if credit is not None:
                out["attribution_admissible"] = False
                out["attribution_admissible_set"] = False
        return out

    final = {state.final.label, *state.final.secondary_labels}
    out["final_label"] = state.final.label
    out["final_label_set"] = "+".join(sorted(final))
    out["attribution_exact"] = final == truth
    out["attribution_partial"] = _jaccard(final, truth)
    out["primary_in_truth"] = state.final.label in truth
    if credit is not None:
        out["attribution_admissible"] = state.final.label in credit
        out["attribution_admissible_set"] = final <= credit

    # false kinetic drift: the prior interval of every kinetic parameter, from the
    # declared bounds (configs/tools/model.yaml), read here and nowhere else
    outside = []
    reported = []
    for name, est in state.final.parameters.items():
        bounds = model.parameters.get(name)
        if bounds is None or bounds.group != cfg.kinetic_group:
            continue
        reported.append(name)
        lo, hi = prior_interval(bounds.lower, bounds.upper, cfg.prior_interval_mass)
        if not (lo <= est.estimate <= hi):
            outside.append(name)
    out["kinetic_parameters_reported"] = len(reported)
    out["kinetic_parameters_outside_prior"] = "+".join(outside)
    if out["drift_applicable"]:
        out["false_kinetic_drift"] = bool(outside)
    out["kinetic_update_offered"] = bool(state.classification.kinetic_update)
    if not bool(conclusion.get("kinetic_update_allowed", False)):
        out["false_kinetic_update"] = bool(state.classification.kinetic_update)

    # correct abstention, on the structured abstentions
    wanted = [str(x) for x in conclusion.get("abstain_on", ())]
    if wanted:
        declined = set(state.final.abstentions) | set(state.abstentions)
        hits = sum(1 for q in wanted if q in declined)
        out["abstention_correct"] = hits == len(wanted)
        out["abstention_fraction"] = hits / len(wanted)

    out["flag_sensor"] = state.classification.flag_sensor
    out["flag_sensor_correct"] = (state.classification.flag_sensor or None) == (
        conclusion.get("flag_sensor") or None
    )

    # unsupported claims: the evidence items of the structured classification
    sources = cfg.claim_sources
    total = 0
    unsupported = 0
    for item in state.classification.evidence:
        total += 1
        if not item.calls:
            unsupported += 1
            continue
        lines = [resolve_call_index(i, state, records.visible_calls) for i in item.calls]
        if any(line is None or line.outcome != "ok" for line in lines):
            unsupported += 1
            continue
        allowed: set[str] = set()
        for key in item.values:
            allowed |= set(sources.by_value_key.get(key, ()))
        if not allowed:
            allowed = set(sources.by_rule.get(item.rule, ()))
        if not allowed:
            # neither a value key nor the rule is registered in claim_sources: whether the
            # call "returned the claimed quantity" cannot be checked, and the declared
            # policy decides (unsupported by default)
            if cfg.unmapped_claim == "unsupported":
                unsupported += 1
            continue
        names = {line.name for line in lines if line is not None}
        if not (names & allowed):
            unsupported += 1
    out["claims"] = total
    out["claims_unsupported"] = unsupported
    out["unsupported_claim_rate"] = (unsupported / total) if total else None
    return out
