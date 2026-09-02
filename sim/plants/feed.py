"""Feedstock catalogue to ADM1 influent, and the nitrogen consistency of a catalogue entry.

Pure functions. A feed recipe (kg wet per day of each catalogue feed) plus a
fractionation per feed (catalogue or hidden truth) gives the 26 liquid-state influent
concentrations and the total flow. Total COD of a feed is ``TS x VS/TS x COD/VS``; the
fractionation splits it into carbohydrates, proteins, lipids, particulate and soluble
inerts and VFA (as acetate). Dissolved species (ammoniacal N, inorganic C, strong ions)
are flow-weighted.

COD equivalents used to build the catalogue values (documented in the YAML files, not
used here): 1.19 kg COD/kg carbohydrate, 1.42 kg COD/kg protein, 2.90 kg COD/kg lipid
(VDI 4630 theoretical methane yields 0.415 / 0.496 / 1.014 m3 CH4 (STP)/kg divided by
0.35 m3 CH4/kg COD).
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from sim.adm1.schema import LIQUID_STATE_NAMES, Influent, StoichiometryParameters
from sim.plants.schema import CODFractionation, FeedstockSpec

_L = {name: i for i, name in enumerate(LIQUID_STATE_NAMES)}


def implied_tkn(spec: FeedstockSpec, stoich: StoichiometryParameters) -> float:
    """TKN of a wet feed implied by its fractionation and the ADM1 N contents, kmol N/m3.

    Ammoniacal N plus the organic N carried by proteins (``N_aa``) and by the inerts
    (``N_I``); carbohydrates, lipids and VFA carry no N in ADM1.
    """
    f = spec.fractionation
    cod = spec.cod_per_m3
    return spec.tan + cod * (f.f_pr * stoich.N_aa + (f.f_xi + f.f_si) * stoich.N_I)


def tkn_consistent(spec: FeedstockSpec, stoich: StoichiometryParameters) -> bool:
    """Whether the declared TKN is within ``tkn_tolerance`` of the implied one."""
    implied = implied_tkn(spec, stoich)
    if spec.tkn == 0.0:
        return implied == 0.0
    return abs(implied - spec.tkn) / spec.tkn <= spec.tkn_tolerance


def feed_concentrations(spec: FeedstockSpec, fractionation: CODFractionation) -> np.ndarray:
    """The 26 ADM1 liquid concentrations of one wet feed (kg COD/m3, kmol/m3)."""
    c = np.zeros(len(LIQUID_STATE_NAMES))
    cod = spec.cod_per_m3
    c[_L["X_ch"]] = cod * fractionation.f_ch
    c[_L["X_pr"]] = cod * fractionation.f_pr
    c[_L["X_li"]] = cod * fractionation.f_li
    c[_L["X_I"]] = cod * fractionation.f_xi
    c[_L["S_I"]] = cod * fractionation.f_si
    c[_L["S_ac"]] = cod * fractionation.f_vfa
    c[_L["S_IN"]] = spec.tan
    c[_L["S_IC"]] = spec.s_ic
    c[_L["S_cat"]] = spec.s_cat
    c[_L["S_an"]] = spec.s_an
    return c


def mix_feeds(
    feedstocks: Mapping[str, FeedstockSpec],
    mass_rates: Mapping[str, float],
    fractionations: Mapping[str, CODFractionation] | None = None,
) -> tuple[np.ndarray, float]:
    """Blend feeds into one influent: ``(concentrations (26,), Q m3/d)``.

    Args:
        feedstocks: The catalogue.
        mass_rates: Feed name -> kg wet/d.
        fractionations: Feed name -> fractionation to use; missing feeds use the
            catalogue value. Pass the hidden truth here to build the true influent.

    Returns:
        Flow-weighted concentrations in :data:`~sim.adm1.schema.LIQUID_STATE_NAMES`
        order and the total volumetric flow.

    Raises:
        ValueError: On an unknown feed, a negative rate, or zero total flow.
    """
    unknown = set(mass_rates) - set(feedstocks)
    if unknown:
        raise ValueError(f"unknown feeds: {sorted(unknown)}")
    total = np.zeros(len(LIQUID_STATE_NAMES))
    q_total = 0.0
    for name in sorted(mass_rates):
        m = float(mass_rates[name])
        if m < 0.0:
            raise ValueError(f"negative mass rate for {name!r}")
        if m == 0.0:
            continue
        spec = feedstocks[name]
        frac = (fractionations or {}).get(name, spec.fractionation)
        q = m / spec.density
        total += q * feed_concentrations(spec, frac)
        q_total += q
    if q_total <= 0.0:
        raise ValueError("total influent flow is zero")
    return total / q_total, q_total


def extension_influent(
    feedstocks: Mapping[str, FeedstockSpec], mass_rates: Mapping[str, float]
) -> dict[str, float]:
    """Flow-weighted influent of the extension components (``S_ca`` only), kmol/m3."""
    q_total = 0.0
    ca = 0.0
    for name, m in mass_rates.items():
        spec = feedstocks[name]
        q = float(m) / spec.density
        q_total += q
        ca += q * spec.s_ca
    if q_total <= 0.0:
        raise ValueError("total influent flow is zero")
    return {"S_ca": ca / q_total}


def constant_influent(
    feedstocks: Mapping[str, FeedstockSpec],
    mass_rates: Mapping[str, float],
    fractionations: Mapping[str, CODFractionation] | None = None,
) -> Influent:
    """A constant :class:`~sim.adm1.schema.Influent` from a feed recipe."""
    conc, q = mix_feeds(feedstocks, mass_rates, fractionations)
    return Influent.constant(conc, q)


def organic_loading_rate(
    feedstocks: Mapping[str, FeedstockSpec], mass_rates: Mapping[str, float], V_liq: float
) -> float:
    """Organic loading rate of a recipe on a declared volume, kg VS/m3/d."""
    vs = sum(float(m) * feedstocks[n].vs_per_kg_wet for n, m in mass_rates.items())
    return vs / V_liq


def cod_loading_rate(
    feedstocks: Mapping[str, FeedstockSpec], mass_rates: Mapping[str, float], V_liq: float
) -> float:
    """COD loading rate of a recipe on a declared volume, kg COD/m3/d."""
    cod = sum(float(m) * feedstocks[n].cod_per_kg_wet for n, m in mass_rates.items())
    return cod / V_liq
