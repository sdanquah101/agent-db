"""The truth series the observation model masks: reactor states as measurable quantities.

The observation model never touches the ODE state vector directly. This module is the
one place where a truth trajectory (:class:`~sim.adm1.schema.SimulationResult` or
:class:`~sim.adm1.extensions.ExtendedResult`) becomes the quantities an operator could in
principle measure, in the units the catalogue declares
(:mod:`sim.observe.schema`): pH, corrected biogas volume at stated standard conditions,
methane fraction on a dry basis, off-gas hydrogen, total and speciated VFA as the acids,
total ammoniacal nitrogen, alkalinity, total and soluble COD, TKN, total and volatile
solids, and a methanogenic-activity test.

**Conventions, all of them stated rather than silent** (CLAUDE.md rule 6):

* *Gas volumes* are the model's ``q_gas_stp_dry`` — dry, 0 degC, 1.013 bar — and the
  catalogue attaches those conditions to the channel. The wet, T_op-referenced BSM2
  ``q_gas`` is never reported as "the biogas volume".
* *VFA* are reported as the acids (kg/m3), converting each COD state at its own
  stoichiometric COD demand (:data:`VFA_COD_PER_KG`), not as COD.
* *Alkalinity* is the bicarbonate (partial) alkalinity ``50 x S_hco3`` kg CaCO3/m3, the
  same proxy the influent generator uses for a feed, not a titration to pH 4.3.
* *Solids* follow a declared :class:`~sim.observe.schema.SolidsConvention`: VS is the
  organic COD converted at per-class COD equivalents, TS is VS plus the inorganic solids
  — the conservative ash the feed carries (:func:`ash_concentration`) plus any calcite the
  precipitation extension has formed. VFA are excluded from VS because they volatilise at
  105 degC.
* The *activity test* is the maximum acetoclastic methanogenesis rate of the sludge,
  ``k_m_ac x X_ac`` kg COD/m3/d: a batch assay at saturating acetate with no inhibition,
  which is what a specific-methanogenic-activity test measures.

Pure functions; no file I/O, no randomness.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from sim.adm1.extensions import ExtendedResult
from sim.adm1.schema import STATE_NAMES, ADM1Parameters, PlantGeometry, SimulationResult
from sim.influent.generator import InfluentTruth
from sim.influent.schema import FeedFractionationCatalogue
from sim.observe.schema import SolidsConvention

__all__ = [
    "KG_CACO3_PER_KMOL_HCO3",
    "KG_N_PER_KMOL",
    "VFA_COD_PER_KG",
    "TruthChannels",
    "ash_concentration",
    "influent_ash",
    "reactor_ash",
    "truth_channels",
]

KG_N_PER_KMOL = 14.007
"""Molar mass of nitrogen, kg N/kmol."""

KG_CACO3_PER_KMOL_HCO3 = 50.0
"""CaCO3 equivalent of one kmol of bicarbonate charge, kg/kmol (100.09 / 2)."""

KG_CACO3_PER_KMOL = 100.09
"""Molar mass of calcite, kg/kmol."""

VFA_COD_PER_KG: Mapping[str, float] = {
    "S_ac": 64.0 / 60.05,
    "S_pro": 112.0 / 74.08,
    "S_bu": 160.0 / 88.11,
    "S_va": 208.0 / 102.13,
}
"""Stoichiometric COD demand of each acid, kg COD/kg acid (CH3(CH2)nCOOH + O2 -> CO2 +
H2O): acetic 1.066, propionic 1.512, butyric 1.816, valeric 2.037."""

VFA_CHANNEL: Mapping[str, str] = {
    "S_ac": "vfa_acetate",
    "S_pro": "vfa_propionate",
    "S_bu": "vfa_butyrate",
    "S_va": "vfa_valerate",
}

_SOLUBLE_COD_STATES: tuple[str, ...] = (
    "S_su", "S_aa", "S_fa", "S_va", "S_bu", "S_pro", "S_ac", "S_h2", "S_ch4", "S_I",
)  # fmt: skip
_PARTICULATE_COD_STATES: tuple[str, ...] = (
    "X_xc", "X_ch", "X_pr", "X_li", "X_su", "X_aa", "X_fa", "X_c4", "X_pro", "X_ac",
    "X_h2", "X_I",
)  # fmt: skip
_BIOMASS_STATES: tuple[str, ...] = (
    "X_su", "X_aa", "X_fa", "X_c4", "X_pro", "X_ac", "X_h2",
)  # fmt: skip
#: Derived series read off a :class:`~sim.adm1.schema.SimulationResult` (the extended
#: result carries the same names in its ``derived`` mapping).
_DERIVED_FROM_RESULT: tuple[str, ...] = (
    "pH", "S_hco3_ion", "S_nh3", "S_nh4_ion", "p_h2", "p_ch4", "p_co2", "p_h2o", "P_gas",
    "q_gas", "q_gas_stp_dry",
)  # fmt: skip

#: Biomass components an extension may add (they are biomass for COD, N and VS alike).
_EXTENSION_BIOMASS: tuple[str, ...] = ("X_sao",)


@dataclass(frozen=True)
class TruthChannels:
    """Measurable truth quantities on a common time grid. Hidden truth."""

    t: np.ndarray
    """Times, d."""
    values: dict[str, np.ndarray]
    """Quantity name -> series, in :attr:`units`."""
    units: dict[str, str]
    """Unit of every series (CLAUDE.md rule 6)."""

    def __post_init__(self) -> None:
        """Check that every series matches the time grid and carries a unit."""
        for name, series in self.values.items():
            if series.shape != self.t.shape:
                raise ValueError(f"{name}: shape {series.shape} != time grid {self.t.shape}")
            if name not in self.units:
                raise ValueError(f"{name}: no unit declared")

    def at(self, name: str, t: np.ndarray) -> np.ndarray:
        """Linear interpolation of one series onto sample times (clipped at the ends)."""
        return np.interp(t, self.t, self.values[name])


def ash_concentration(
    t: np.ndarray, ash_influent: np.ndarray, q: np.ndarray, V_liq: float, initial: float
) -> np.ndarray:
    """Inorganic (ash) solids in the reactor, kg/m3, as a conservative tracer.

    ADM1 carries no ash, but the feed does (the catalogue's ``TS`` and ``VS/TS``), and TS
    cannot be reported without it. Ash neither reacts nor settles here, so over a segment
    with a constant feed the CSTR balance ``V dX/dt = Q (u - X)`` integrates exactly to
    ``X_{k+1} = u_k + (X_k - u_k) exp(-Q_k dt / V)``. This is bookkeeping on the
    observation side: it adds no state to the truth model and changes none of its physics.

    Args:
        t: Segment start times, d (the influent's own sample-and-hold grid).
        ash_influent: Ash concentration of the feed on each segment, kg/m3 of feed.
        q: Feed flow on each segment, m3/d.
        V_liq: Reactor liquid volume, m3.
        initial: Ash concentration at ``t[0]``, kg/m3.

    Returns:
        Ash concentration at each time in ``t``, kg/m3.
    """
    t = np.asarray(t, dtype=float)
    u = np.asarray(ash_influent, dtype=float)
    flow = np.asarray(q, dtype=float)
    if not (t.shape == u.shape == flow.shape):
        raise ValueError("t, ash_influent and q must have the same shape")
    out = np.empty_like(t)
    out[0] = initial
    for k in range(t.size - 1):
        decay = np.exp(-flow[k] * (t[k + 1] - t[k]) / V_liq)
        out[k + 1] = u[k] + (out[k] - u[k]) * decay
    return out


def influent_ash(catalogue: FeedFractionationCatalogue, truth: InfluentTruth) -> np.ndarray:
    """Ash concentration of the generated influent on each of its days, kg/m3 of feed.

    The ash a feed carries is its non-volatile dry matter, ``TS x (1 - VS/TS)``, at the
    delivery's *true* total solids; the mixture is flow-weighted, exactly as
    :func:`sim.influent.mapping.mix_feeds` weights the ADM1 states. Days with no feed
    carry zero (nothing enters, and the reactor's own ash is a state of
    :func:`ash_concentration`, not of the feed).
    """
    q_total = np.zeros(truth.n_days)
    ash = np.zeros(truth.n_days)
    for feed_id, feed in truth.feeds.items():
        spec = catalogue.feeds[feed_id]
        q = feed.delivered_kg / spec.density
        q_total += q
        ash += feed.delivered_kg * feed.ts * (1.0 - spec.vs_of_ts)
    return np.divide(ash, q_total, out=np.zeros_like(ash), where=q_total > 0.0)


def reactor_ash(
    catalogue: FeedFractionationCatalogue,
    truth: InfluentTruth,
    V_liq: float,
    t_out: np.ndarray,
    initial: float = 0.0,
) -> np.ndarray:
    """Reactor ash at arbitrary output times, kg/m3, from a generated influent.

    The influent is piecewise constant (the generator's sample-and-hold days), so within
    a day the conservative balance has the closed form
    ``x(t) = u_k + (x_k - u_k) exp(-Q_k (t - t_k) / V)``; this evaluates it at ``t_out``.

    Args:
        catalogue: The feed catalogue the run used.
        truth: The generated influent truth (hidden).
        V_liq: Reactor liquid volume, m3 (the *true* one for the truth model).
        t_out: Output times, d.
        initial: Reactor ash at the first influent sample, kg/m3.

    Returns:
        Ash concentration at each time of ``t_out``, kg/m3.
    """
    t_in = np.asarray(truth.influent.t, dtype=float)
    q = np.asarray(truth.influent.q, dtype=float)
    u = influent_ash(catalogue, truth)
    at_breaks = ash_concentration(t_in, u, q, V_liq, initial)
    t_out = np.asarray(t_out, dtype=float)
    k = np.clip(np.searchsorted(t_in, t_out, side="right") - 1, 0, t_in.size - 1)
    return u[k] + (at_breaks[k] - u[k]) * np.exp(-q[k] * (t_out - t_in[k]) / V_liq)


def _trajectory(
    result: SimulationResult | ExtendedResult,
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray]]:
    """``(t, states, derived)`` from either result type."""
    if isinstance(result, ExtendedResult):
        states = {n: result.y[i] for i, n in enumerate(result.state_names)}
        return result.t, states, dict(result.derived)
    states = {n: result.y[i] for i, n in enumerate(STATE_NAMES)}
    derived = {name: getattr(result, name) for name in _DERIVED_FROM_RESULT}
    return result.t, states, derived


def truth_channels(
    result: SimulationResult | ExtendedResult,
    params: ADM1Parameters,
    geometry: PlantGeometry,
    solids: SolidsConvention,
    ash_kg_m3: np.ndarray,
) -> TruthChannels:
    """Every measurable truth quantity of a run, on the trajectory's own time grid.

    Args:
        result: The truth trajectory (standard or extended model).
        params: The **truth** parameters the run was integrated with (the N contents and
            ``k_m_ac`` enter TKN and the activity test).
        geometry: The geometry the run used; ``T_op`` is the reactor temperature.
        solids: The declared TS/VS convention (``configs/observe/observation.yaml``).
        ash_kg_m3: Inorganic solids in the reactor at each output time, kg/m3, from
            :func:`ash_concentration`. Required: TS is not defined without it, and
            defaulting it to zero would be a silent unit choice (CLAUDE.md rule 6).

    Returns:
        The truth channels, keyed by the catalogue's ``truth_quantity`` names.

    Raises:
        ValueError: If ``ash_kg_m3`` does not match the trajectory's time grid.
    """
    t, states, derived = _trajectory(result)
    ash = np.asarray(ash_kg_m3, dtype=float)
    if ash.shape != t.shape:
        raise ValueError(f"ash_kg_m3 has shape {ash.shape}, expected {t.shape}")
    stoich = params.stoichiometry
    ones = np.ones_like(t)

    dry_gas = derived["P_gas"] - derived["p_h2o"]
    values: dict[str, np.ndarray] = {
        "reactor_temperature": geometry.T_op * ones,
        "ph": derived["pH"],
        "biogas_volume": derived["q_gas_stp_dry"],
        "ch4_fraction": derived["p_ch4"] / dry_gas,
        "offgas_h2": derived["p_h2"] / dry_gas * 1e6,
        "alkalinity": KG_CACO3_PER_KMOL_HCO3 * derived["S_hco3_ion"],
        "tan": KG_N_PER_KMOL * states["S_IN"],
        "activity_ac": params.kinetics.k_m_ac * states["X_ac"],
    }
    for state, channel in VFA_CHANNEL.items():
        values[channel] = states[state] / VFA_COD_PER_KG[state]
    values["vfa_total"] = sum(values[c] for c in VFA_CHANNEL.values())

    biomass = [n for n in (*_BIOMASS_STATES, *_EXTENSION_BIOMASS) if n in states]
    values["cod_soluble"] = sum(states[n] for n in _SOLUBLE_COD_STATES)
    values["cod_total"] = (
        values["cod_soluble"]
        + sum(states[n] for n in _PARTICULATE_COD_STATES if n not in _BIOMASS_STATES)
        + sum(states[n] for n in biomass)
    )
    values["tkn"] = KG_N_PER_KMOL * (
        states["S_IN"]
        + stoich.N_aa * (states["S_aa"] + states["X_pr"])
        + stoich.N_I * (states["S_I"] + states["X_I"])
        + stoich.N_xc * states["X_xc"]
        + stoich.N_bac * sum(states[n] for n in biomass)
    )

    equivalents = solids.cod_per_vs
    vs = (
        (states["S_su"] + states["X_ch"]) / equivalents["carbohydrate"]
        + (states["S_aa"] + states["X_pr"]) / equivalents["protein"]
        + (states["S_fa"] + states["X_li"]) / equivalents["lipid"]
        + (states["S_I"] + states["X_I"]) / equivalents["inert"]
        + states["X_xc"] / equivalents["composite"]
        + sum(states[n] for n in biomass) / equivalents["biomass"]
    )
    if solids.include_vfa_in_vs:
        vs = vs + sum(values[c] for c in VFA_CHANNEL.values())
    inorganic = ash + KG_CACO3_PER_KMOL * states.get("X_caco3", np.zeros_like(t))
    ts = vs + inorganic
    values["ts"] = ts
    values["vs"] = np.divide(vs, ts, out=np.zeros_like(ts), where=ts > 0.0)

    units = {
        "reactor_temperature": "K",
        "ph": "pH units",
        "biogas_volume": "m3/d",
        "ch4_fraction": "m3 CH4/m3 dry biogas",
        "offgas_h2": "ppmv (dry biogas)",
        "alkalinity": "kg CaCO3/m3",
        "tan": "kg N/m3",
        "activity_ac": "kg COD/m3/d",
        "vfa_total": "kg/m3 (as the acids)",
        "cod_total": "kg COD/m3",
        "cod_soluble": "kg COD/m3",
        "tkn": "kg N/m3",
        "ts": "kg TS/m3",
        "vs": "kg VS/kg TS",
    }
    units.update({c: "kg/m3 (as the acid)" for c in VFA_CHANNEL.values()})
    return TruthChannels(t=np.asarray(t, dtype=float), values=values, units=units)
