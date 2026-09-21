"""Per-feed inert nitrogen: the truth model's ``N_I`` and the feed TKN the operator sees.

**The mismatch here is intentional and must not be "fixed".** The lead's decision of
2026-09-02 (``docs/decisions.md``, "Per-feed inert nitrogen in the truth model; the fitted
model keeps the ADM1 default") is that

* the **truth model** applies the per-feed inert nitrogen content ``inert_N_I`` of the
  catalogue (``configs/influent/feed_fractionation.yaml``: kmol N per kg COD of
  ``X_I``/``S_I``; a sludge-derived 0.00429 for primary sludge and thickened WAS, far
  less for lignocellulosic and food-waste inerts). ADM1 carries one ``N_I`` per reactor,
  so the truth value is the **inert-COD-weighted mean** of the fed feeds' values
  (:func:`truth_inert_nitrogen`), recomputed whenever the recipe changes. It is a
  plant-level *hidden truth parameter* derived from the catalogue and the recipe: the run
  layer may write it to ``truth_store/<id>/``; it is never a workflow-visible config;
* the **fitted model** (standard ADM1) keeps the BSM2 ``N_I`` for every plant
  (``configs/adm1/params_bsm2.yaml`` is untouched by anything here; tested);
* the **TKN the influent generator reports as a routine assay** is the one implied by the
  per-feed values (:func:`feed_tkn`), so the operator's data are consistent with the
  truth, and the fitted model's nitrogen balance is wrong by exactly the inert-N gap.

That gap is a small, real structural mismatch of the kind the benchmark exists to
expose (proposal §6.1: "the fitted model is structurally wrong by design"). Aligning the
two values, loosening a tolerance to hide the gap, or passing the truth ``N_I`` to a
workflow would each remove the thing being measured. A scenario that wants the values
aligned says so explicitly.

Pure functions; nothing here reads or writes files.
"""

from __future__ import annotations

from collections.abc import Mapping

from sim.adm1.schema import ADM1Parameters
from sim.influent.mapping import _check_rates, _feeds, feed_cod_per_m3
from sim.influent.schema import CODFractionation, FeedFractionation, FeedFractionationCatalogue

__all__ = ["feed_tkn", "truth_inert_nitrogen", "truth_parameters"]


def truth_inert_nitrogen(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    mass_rates: Mapping[str, float],
    fractionations: Mapping[str, CODFractionation] | None = None,
) -> float:
    """The truth model's ``N_I`` for a recipe, kmol N per kg COD of inerts.

    The inert-COD-weighted mean of the fed feeds' ``inert_N_I``: with feed ``k``
    delivering ``m_k`` kg wet/d at ``COD_k`` kg COD/kg wet and inert share
    ``f_inert,k = f_xi + f_si``, ``N_I = sum_k(w_k N_I,k) / sum_k(w_k)`` with
    ``w_k = m_k COD_k f_inert,k``. Weighting by inert COD (rather than by total COD or
    by mass) is the choice under which the inert nitrogen load of the blend is exactly
    the sum of the per-feed loads (``docs/decisions.md``, "Truth N_I weighting").

    Args:
        catalogue: The declared catalogue (or its ``feeds`` mapping).
        mass_rates: Feed id -> kg wet/d. Feeds at zero rate carry no weight.
        fractionations: Feed id -> fractionation whose inert share and COD/VS to use;
            missing feeds use the catalogue value. Pass the hidden truth to weight by
            the true inert COD.

    Returns:
        ``N_I``, kmol N/kg COD. Hidden truth.

    Raises:
        ValueError: On an unknown feed, a negative rate, or a recipe with no inert COD
            (then no mean is defined).
    """
    feeds = _feeds(catalogue)
    _check_rates(feeds, mass_rates)
    weighted = 0.0
    weight = 0.0
    for name in sorted(mass_rates):
        m = float(mass_rates[name])
        if m == 0.0:
            continue
        spec = feeds[name]
        frac = (fractionations or {}).get(name, spec.fractionation)
        w = m / spec.density * feed_cod_per_m3(spec, frac) * (frac.f_xi + frac.f_si)
        weighted += w * spec.inert_N_I
        weight += w
    if weight <= 0.0:
        raise ValueError("recipe carries no inert COD; the truth N_I is undefined")
    return weighted / weight


def truth_parameters(
    params: ADM1Parameters,
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    mass_rates: Mapping[str, float],
    fractionations: Mapping[str, CODFractionation] | None = None,
) -> ADM1Parameters:
    """A copy of ``params`` carrying the truth ``N_I`` of the recipe.

    ``params`` itself (normally the BSM2 set the fitted model keeps) is not modified;
    the returned object is what the truth model is compiled with.
    """
    n_i = truth_inert_nitrogen(catalogue, mass_rates, fractionations)
    stoich = params.stoichiometry.model_copy(update={"N_I": n_i})
    return params.model_copy(update={"stoichiometry": stoich})


def feed_tkn(
    spec: FeedFractionation,
    N_aa: float,
    fractionation: CODFractionation | None = None,
    ts: float | None = None,
) -> float:
    """TKN of one wet feed under its own inert nitrogen content, kmol N/m3.

    Ammoniacal N plus the organic N of proteins (``N_aa``, kmol N/kg COD, the ADM1
    value) and of the inerts (the feed's ``inert_N_I``). This is the "routine assay"
    TKN the generator reports; a fitted model using the ADM1 default ``N_I`` cannot
    reproduce it for non-sludge feeds, by design (see the module docstring).

    Args:
        spec: The catalogue entry.
        N_aa: N content of proteins, kmol N/kg COD.
        fractionation: Fractionation to use (default: the declared one).
        ts: Total solids override, kg TS/kg wet (the generator's per-delivery moisture).
    """
    frac = spec.fractionation if fractionation is None else fractionation
    cod = feed_cod_per_m3(spec, frac, ts)
    return spec.tan + cod * (frac.f_pr * N_aa + (frac.f_xi + frac.f_si) * spec.inert_N_I)
