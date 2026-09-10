"""Feed catalogue to ADM1 influent, and the nitrogen consistency of a catalogue entry.

Pure functions. A feed recipe (kg wet per day of each catalogue feed) plus a
fractionation per feed (catalogue, or the hidden truth) gives the 26 liquid-state
influent concentrations and the total flow. Total COD of a feed is
``TS x VS/TS x COD/VS`` where COD/VS is **derived from the fractionation in use**
(:attr:`sim.influent.schema.CODFractionation.cod_per_vs`, from the class COD
equivalents :data:`~sim.influent.schema.COD_EQUIVALENTS_KG_COD_PER_KG`): the volatile
solids are what a feed delivers, and a different true composition carries a different
COD. The fractionation splits that COD into carbohydrates, proteins, lipids, particulate
and soluble inerts and VFA (as acetate); proteins, carbohydrates and lipids are fed
directly (no composite ``X_xc``). Dissolved species (ammoniacal N, inorganic C, strong
ions, calcium) are flow-weighted.

Recipes are mass rates (kg wet/d) because the plant contract reports batch feeds by
fresh mass (silage) and pumped feeds by volume; :func:`nominal_mass_rates` converts a
plant's feed catalogue to one recipe at the declared medians.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from sim.adm1.schema import LIQUID_STATE_NAMES, Influent, StoichiometryParameters
from sim.influent.schema import CODFractionation, FeedFractionation, FeedFractionationCatalogue
from sim.plants.schema import PlantConfig

_L = {name: i for i, name in enumerate(LIQUID_STATE_NAMES)}

#: Liquid states that carry COD in the influent built here.
COD_STATES: tuple[str, ...] = ("X_ch", "X_pr", "X_li", "X_I", "S_I", "S_ac")

KG_PER_TONNE = 1000.0


def implied_tkn(spec: FeedFractionation, stoich: StoichiometryParameters) -> float:
    """TKN of a wet feed implied by its fractionation and the ADM1 N contents, kmol N/m3.

    Ammoniacal N plus the organic N carried by proteins (``N_aa``) and by the inerts
    (``N_I``); carbohydrates, lipids and VFA carry no N in ADM1.
    """
    f = spec.fractionation
    cod = spec.cod_per_m3
    return spec.tan + cod * (f.f_pr * stoich.N_aa + (f.f_xi + f.f_si) * stoich.N_I)


def tkn_consistent(spec: FeedFractionation, stoich: StoichiometryParameters) -> bool:
    """Whether the declared TKN is within ``tkn_tolerance`` of the implied one."""
    implied = implied_tkn(spec, stoich)
    if spec.tkn == 0.0:
        return implied == 0.0
    return abs(implied - spec.tkn) / spec.tkn <= spec.tkn_tolerance


def feed_cod_per_m3(
    spec: FeedFractionation, fractionation: CODFractionation, ts: float | None = None
) -> float:
    """Total COD of one wet feed under a fractionation, kg COD/m3.

    ``TS x VS/TS x COD/VS(fractionation) x density``; ``ts`` overrides the catalogue
    total solids (the generator's per-delivery moisture), kg TS/kg wet.
    """
    ts_used = spec.ts if ts is None else float(ts)
    cod_per_vs = fractionation.cod_per_vs(spec.inert_cod_equivalent)
    return ts_used * spec.vs_of_ts * cod_per_vs * spec.density


def liquor_fraction(spec: FeedFractionation, ts: float | None = None) -> float:
    """How much liquor a delivery carries, relative to the catalogue entry's, -.

    ``(1 - ts) / (1 - ts_catalogue)``, the water fraction of the wet feed against the
    water fraction the catalogue's dissolved concentrations were declared at.

    **Why dissolved species need it** (the lead's ruling of 2026-09-10, an approved change
    to a frozen component). The catalogue declares ``s_cat``, ``s_an``, ``tan``, ``s_ic``
    and ``s_ca`` per m3 of *wet feed*, at the catalogue's own total solids. They are not
    properties of the wet feed, though: they are solutes carried in its **liquor**. A
    delivery that arrives drier is the same solute load in less water per m3 of stream, so
    the concentration per m3 of stream moves with the liquor and not with the solids.

    Holding them fixed while the free acetate scaled with the COD -- which does scale with
    solids -- was the root cause of finding B2 of 2026-09-09: it made every stream
    **electroneutral only at catalogue TS** and let its implied pH drift with every
    delivery. Under this scaling both sides of that balance carry the same factor, so a
    stream's charge consistency is a property of the catalogue entry rather than of the
    weather.

    Returns 1.0 at the catalogue's own solids, which is what makes the correction visible
    as a factor rather than hidden inside the numbers.
    """
    ts_used = spec.ts if ts is None else float(ts)
    return (1.0 - ts_used) / (1.0 - spec.ts)


def feed_free_acetate(
    spec: FeedFractionation, fractionation: CODFractionation, ts: float | None = None
) -> float:
    """Free (dissolved) acetate of one wet feed, kg COD/m3.

    The fractionation's VFA share of the COD **at the catalogue's solids**, carried to this
    delivery by :func:`liquor_fraction`. Free VFA is dissolved in the liquor, so it follows
    the liquor; the particulate classes follow the solids (lead's ruling, 2026-09-10).
    """
    return feed_cod_per_m3(spec, fractionation) * fractionation.f_vfa * liquor_fraction(spec, ts)


def feed_concentrations(
    spec: FeedFractionation, fractionation: CODFractionation, ts: float | None = None
) -> np.ndarray:
    """The 26 ADM1 liquid concentrations of one wet feed (kg COD/m3, kmol/m3).

    COD follows the fractionation given (declared or true); ``ts`` optionally overrides
    the catalogue total solids.

    **Solids and liquor scale differently** (lead's ruling, 2026-09-10). The particulate
    classes and the soluble inert follow the delivery's solids, as its COD does. The
    dissolved species -- ammoniacal N, inorganic C, the strong ions and the free acetate --
    follow its **liquor** (:func:`liquor_fraction`), because that is what they are dissolved
    in. ``S_I`` stays with the COD deliberately and is flagged rather than moved: it is a
    soluble lump, so the same argument reaches it, but it carries no charge, so moving it
    would re-open the ``cod_per_vs`` derivation without fixing anything the ruling is about.
    Recorded in ``docs/decisions.md`` for the lead.
    """
    c = np.zeros(len(LIQUID_STATE_NAMES))
    cod = feed_cod_per_m3(spec, fractionation, ts)
    liquor = liquor_fraction(spec, ts)
    c[_L["X_ch"]] = cod * fractionation.f_ch
    c[_L["X_pr"]] = cod * fractionation.f_pr
    c[_L["X_li"]] = cod * fractionation.f_li
    c[_L["X_I"]] = cod * fractionation.f_xi
    c[_L["S_I"]] = cod * fractionation.f_si
    c[_L["S_ac"]] = feed_free_acetate(spec, fractionation, ts)
    c[_L["S_IN"]] = spec.tan * liquor
    c[_L["S_IC"]] = spec.s_ic * liquor
    c[_L["S_cat"]] = spec.s_cat * liquor
    c[_L["S_an"]] = spec.s_an * liquor
    return c


def _feeds(catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation]) -> Mapping:
    return catalogue.feeds if isinstance(catalogue, FeedFractionationCatalogue) else catalogue


def _check_rates(feeds: Mapping[str, FeedFractionation], mass_rates: Mapping[str, float]) -> None:
    unknown = set(mass_rates) - set(feeds)
    if unknown:
        raise ValueError(f"unknown feeds: {sorted(unknown)}")
    negative = [n for n, m in mass_rates.items() if float(m) < 0.0]
    if negative:
        raise ValueError(f"negative mass rate for {sorted(negative)}")


def mix_feeds(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    mass_rates: Mapping[str, float],
    fractionations: Mapping[str, CODFractionation] | None = None,
) -> tuple[np.ndarray, float]:
    """Blend feeds into one influent: ``(concentrations (26,), Q m3/d)``.

    Args:
        catalogue: The declared catalogue.
        mass_rates: Feed id -> kg wet/d.
        fractionations: Feed id -> fractionation to use; missing feeds use the
            catalogue value. Pass the hidden truth here to build the true influent.

    Returns:
        Flow-weighted concentrations in :data:`~sim.adm1.schema.LIQUID_STATE_NAMES`
        order and the total volumetric flow.

    Raises:
        ValueError: On an unknown feed, a negative rate, or zero total flow.
    """
    feeds = _feeds(catalogue)
    _check_rates(feeds, mass_rates)
    total = np.zeros(len(LIQUID_STATE_NAMES))
    q_total = 0.0
    for name in sorted(mass_rates):
        m = float(mass_rates[name])
        if m == 0.0:
            continue
        spec = feeds[name]
        frac = (fractionations or {}).get(name, spec.fractionation)
        q = m / spec.density
        total += q * feed_concentrations(spec, frac)
        q_total += q
    if q_total <= 0.0:
        raise ValueError("total influent flow is zero")
    return total / q_total, q_total


def extension_influent(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    mass_rates: Mapping[str, float],
) -> dict[str, float]:
    """Flow-weighted influent of the extension components (``S_ca`` only), kmol/m3."""
    feeds = _feeds(catalogue)
    _check_rates(feeds, mass_rates)
    q_total = 0.0
    ca = 0.0
    for name, m in mass_rates.items():
        spec = feeds[name]
        q = float(m) / spec.density
        q_total += q
        ca += q * spec.s_ca
    if q_total <= 0.0:
        raise ValueError("total influent flow is zero")
    return {"S_ca": ca / q_total}


def constant_influent(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    mass_rates: Mapping[str, float],
    fractionations: Mapping[str, CODFractionation] | None = None,
) -> Influent:
    """A constant :class:`~sim.adm1.schema.Influent` from a feed recipe."""
    conc, q = mix_feeds(catalogue, mass_rates, fractionations)
    return Influent.constant(conc, q)


def organic_loading_rate(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    mass_rates: Mapping[str, float],
    V_liq: float,
) -> float:
    """Organic loading rate of a recipe on a liquid volume, kg VS/m3/d."""
    feeds = _feeds(catalogue)
    _check_rates(feeds, mass_rates)
    vs = sum(float(m) * feeds[n].vs_per_kg_wet for n, m in mass_rates.items())
    return vs / V_liq


def cod_loading_rate(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    mass_rates: Mapping[str, float],
    V_liq: float,
) -> float:
    """COD loading rate of a recipe on a liquid volume, kg COD/m3/d."""
    feeds = _feeds(catalogue)
    _check_rates(feeds, mass_rates)
    cod = sum(float(m) * feeds[n].cod_per_kg_wet for n, m in mass_rates.items())
    return cod / V_liq


def nominal_mass_rates(
    plant: PlantConfig, catalogue: FeedFractionationCatalogue
) -> dict[str, float]:
    """A plant's feed catalogue at its declared medians as a recipe, feed id -> kg wet/d.

    Feeds reported by volume use ``volume_m3_d.median x density``; feeds reported by
    fresh mass use ``mass_t_fm_d.median x 1000``. The delivery pattern (batch days,
    zero-delivery fraction) is the influent generator's job and is not applied here.

    Raises:
        ValueError: If a feed stream reports neither a volume nor a mass, or the
            catalogue kind disagrees with the plant's.
    """
    rates: dict[str, float] = {}
    for feed in plant.feeds:
        spec = catalogue.for_stream(feed)
        if feed.volume_m3_d is not None:
            rates[feed.name] = feed.volume_m3_d.median * spec.density
        elif feed.mass_t_fm_d is not None:
            rates[feed.name] = feed.mass_t_fm_d.median * KG_PER_TONNE
        else:
            raise ValueError(f"feed {feed.name!r} of plant {plant.id} reports no volume or mass")
    return rates
