"""Observable channels: the quantities a plant could in principle measure.

A *channel* is a time series computed from the hidden truth trajectory (and, for the
solids channels, from the influent that produced it). It is still hidden truth: the
observation model (:mod:`sim.observation.model`) turns channels into sensor records by
sampling, noise, drift, fouling, flatlining, saturation, lag and missingness.

Every channel carries its unit and, where it needs one, its convention
(:data:`CHANNEL_UNITS`): gas volumes at 0 degC and 1 atm dry unless stated, gas fractions
on a dry basis, solids per m3 of digestate (CLAUDE.md rule 6).

Conversions used here, all from the ADM1 state definitions:

* **Alkalinity** — one equivalent of bicarbonate or of a VFA anion neutralises one
  equivalent of acid, so the alkalinity is the anion charge concentration times the
  equivalent mass of CaCO3 (50 kg per kmol charge). Partial alkalinity counts bicarbonate
  only (what a titration to pH 5.75 sees); total alkalinity adds the VFA anions.
* **VFA** — reported as acetic-acid equivalent (the plant convention behind FOS/TAC):
  each acid's COD is converted to moles by its own COD equivalent
  (:data:`VFA_COD_PER_KMOL`) and priced at the molar mass of acetic acid.
* **FOS/TAC** — total VFA as acetic acid over total alkalinity as CaCO3, the ratio the
  Muscatine plant reports, on the plant's own units (kg/m3 over kg CaCO3/m3): feeding the
  anchor's own VFA and alkalinity through this formula returns the anchor's own FOS/TAC
  column (tested). Our *simulated* healthy digester sits well below the plant's median,
  which is recorded in configs/observation/sensors.yaml and flagged.
* **Solids** — volatile solids are the COD states divided by the COD equivalent of the
  class they belong to (:data:`COD_PER_VS_BY_STATE`); the inert states use the influent's
  own inert equivalent, the COD-weighted mean over the fed feeds, exactly as the truth
  ``N_I`` is built (:mod:`sim.influent.nitrogen`). Ash is not an ADM1 state, so total
  solids need the conserved ash tracer of :func:`ash_trajectory`.

Pure functions; no file I/O, no randomness (the randomness is in the observation model).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

import numpy as np

from sim.adm1.extensions import ExtendedResult
from sim.adm1.schema import LIQUID_STATE_NAMES, N_STATES, Influent
from sim.influent.mapping import _check_rates, _feeds, feed_cod_per_m3
from sim.influent.schema import (
    COD_EQUIVALENTS_KG_COD_PER_KG,
    CODFractionation,
    FeedFractionation,
    FeedFractionationCatalogue,
)
from sim.plants.mixing import TwoZoneResult

__all__ = [
    "CHANNEL_UNITS",
    "COD_PER_VS_BY_STATE",
    "EXTENSION_COD_PER_VS",
    "EXTENSION_INORGANIC_SOLIDS",
    "EXTENSION_NO_SOLIDS",
    "KG_CACO3_PER_KMOL_CHARGE",
    "VFA_COD_PER_KMOL",
    "TruthChannels",
    "ash_trajectory",
    "channel_series",
    "channels_from_two_zone",
    "condition_flags",
    "flags_at",
    "influent_ash_concentration",
    "influent_inert_cod_equivalent",
]

KG_CACO3_PER_KMOL_CHARGE = 50.0
"""Equivalent mass of calcium carbonate, kg CaCO3 per kmol of anion charge (100.09 / 2)."""

M_ACETIC = 60.05
"""Molar mass of acetic acid, kg/kmol (VFA are reported as acetic-acid equivalent)."""

M_PROPIONIC = 74.08
M_BUTYRIC = 88.11
M_VALERIC = 102.13
"""Molar masses of the other VFA, kg/kmol."""

#: kg COD per kmol of each volatile fatty acid (ADM1 state definitions).
VFA_COD_PER_KMOL: Mapping[str, float] = MappingProxyType(
    {"S_ac": 64.0, "S_pro": 112.0, "S_bu": 160.0, "S_va": 208.0}
)

#: kg COD per kg of volatile solids for every COD-bearing liquid state. Sugars,
#: carbohydrates and the composite are carbohydrate-like (1.19); amino acids, proteins
#: and biomass protein-like (1.42); LCFA and lipids lipid-like (2.90); the VFA at their
#: own stoichiometry; dissolved methane and hydrogen carry no solids. ``S_I`` and ``X_I``
#: are not here: their equivalent is the influent's own
#: (:func:`influent_inert_cod_equivalent`), because it differs by feed (lead's freeze
#: 2026-09-02).
COD_PER_VS_BY_STATE: Mapping[str, float] = MappingProxyType(
    {
        "S_su": COD_EQUIVALENTS_KG_COD_PER_KG["f_ch"],
        "X_ch": COD_EQUIVALENTS_KG_COD_PER_KG["f_ch"],
        "X_xc": COD_EQUIVALENTS_KG_COD_PER_KG["f_ch"],
        "S_aa": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"],
        "X_pr": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"],
        "S_fa": COD_EQUIVALENTS_KG_COD_PER_KG["f_li"],
        "X_li": COD_EQUIVALENTS_KG_COD_PER_KG["f_li"],
        "S_va": 208.0 / M_VALERIC,  # 2.04 kg COD/kg valeric acid
        "S_bu": 160.0 / M_BUTYRIC,  # 1.82 kg COD/kg butyric acid
        "S_pro": 112.0 / M_PROPIONIC,  # 1.51 kg COD/kg propionic acid
        "S_ac": 64.0 / M_ACETIC,  # 1.07 kg COD/kg acetic acid
        "X_su": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"],
        "X_aa": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"],
        "X_fa": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"],
        "X_c4": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"],
        "X_pro": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"],
        "X_ac": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"],
        "X_h2": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"],
    }
)

#: Unit and convention of every channel (CLAUDE.md rule 6).
CHANNEL_UNITS: Mapping[str, str] = MappingProxyType(
    {
        "temperature": "K (reactor liquid; constant at the set point in the truth model)",
        "pH": "- (activity-based when the ionic-strength extension is on)",
        "q_gas_stp_dry": "m3/d at 0 degC and 1 atm, water vapour removed",
        "q_gas_operating": "m3/d at T_op normalised to P_atm (the BSM2 meter convention)",
        "ch4_fraction": "- (mole fraction of the dry gas)",
        "co2_fraction": "- (mole fraction of the dry gas)",
        "h2_ppm": "ppm by volume of the dry gas",
        "alkalinity_total": "kg CaCO3/m3 (bicarbonate + VFA anions)",
        "alkalinity_partial": "kg CaCO3/m3 (bicarbonate only)",
        "vfa_total": "kg/m3 as acetic-acid equivalent",
        "vfa_ac": "kg/m3 as acetic acid",
        "vfa_pro": "kg/m3 as propionic acid",
        "vfa_bu": "kg/m3 as butyric acid",
        "vfa_va": "kg/m3 as valeric acid",
        "tan": "kg N/m3 (total ammoniacal nitrogen, S_IN)",
        "free_ammonia": "kg N/m3 (NH3)",
        "cod_total": "kg COD/m3 (every COD-bearing liquid state, extensions included)",
        "vs": "kg VS/m3 of digestate",
        "ts": (
            "kg TS/m3 of digestate (VS + fed ash from the conserved tracer + inorganic "
            "solid formed in the reactor, e.g. calcite)"
        ),
        "fos_tac": "- (total VFA as acetic acid over total alkalinity as CaCO3)",
    }
)

KG_N_PER_KMOL = 14.007
"""Molar mass of nitrogen, kg N/kmol (``S_IN`` is kmol N/m3; TAN is kg N/m3)."""

#: kg COD per kg VS of each COD-bearing **extension** component
#: (``configs/adm1/extensions.yaml``). The base states live in
#: :data:`COD_PER_VS_BY_STATE`; extension components sit *after* the gas states in the
#: state vector, so they are not covered by the liquid slice and would otherwise be
#: silently dropped from ``cod_total`` and ``vs``. ``X_sao`` is biomass, so it takes the
#: protein-like equivalent every other biomass state takes.
EXTENSION_COD_PER_VS: Mapping[str, float] = MappingProxyType(
    {"X_sao": COD_EQUIVALENTS_KG_COD_PER_KG["f_pr"]}
)

#: kg of **inorganic** solid per unit of each extension state that is one, for total
#: solids only (it carries no COD and is not volatile). Calcite precipitated inside the
#: reactor is real suspended solids that the feed-ash tracer cannot know about, because it
#: is formed rather than fed. ``X_caco3`` is kmol/m3, so the factor is the molar mass.
EXTENSION_INORGANIC_SOLIDS: Mapping[str, float] = MappingProxyType({"X_caco3": 100.09})

#: Extension states that contribute neither COD nor solids, listed so that
#: ``tests/test_observation.py`` can assert every declared extension component is
#: classified — a new one must be placed deliberately, not forgotten. ``S_ca`` is
#: dissolved calcium; the dissolved-solids contribution of the ions is outside the
#: wet/dry solids convention used here (CLAUDE.md rule 6) and is declared absent.
EXTENSION_NO_SOLIDS: frozenset[str] = frozenset({"S_ca"})


class TruthChannels:
    """Every observable channel of one run, on the truth model's output times.

    Hidden truth: the run layer may write it to ``truth_store/<id>/``; a workflow sees only
    what :mod:`sim.observation.model` reports through the tier mask.
    """

    __slots__ = ("_series", "t")

    def __init__(self, t: np.ndarray, series: Mapping[str, np.ndarray]) -> None:
        """Store the output times and one array per channel (all the same length)."""
        self.t = np.asarray(t, dtype=float)
        unknown = set(series) - set(CHANNEL_UNITS)
        if unknown:
            raise ValueError(f"unknown channels: {sorted(unknown)}")
        for name, values in series.items():
            if np.shape(values) != np.shape(self.t):
                raise ValueError(f"channel {name}: shape {np.shape(values)} != {np.shape(self.t)}")
        self._series = dict(series)

    def __contains__(self, name: str) -> bool:
        """Whether a channel was computed for this run."""
        return name in self._series

    def __getitem__(self, name: str) -> np.ndarray:
        """The trajectory of one channel."""
        if name not in self._series:
            raise KeyError(f"channel {name!r} was not computed for this run")
        return self._series[name]

    @property
    def names(self) -> tuple[str, ...]:
        """Channels available, sorted."""
        return tuple(sorted(self._series))

    @property
    def units(self) -> Mapping[str, str]:
        """Unit and convention of every available channel."""
        return MappingProxyType({n: CHANNEL_UNITS[n] for n in self.names})


def influent_inert_cod_equivalent(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    mass_rates: Mapping[str, float],
    fractionations: Mapping[str, CODFractionation] | None = None,
) -> float:
    """Inert-COD-weighted mean inert COD equivalent of a recipe, kg COD/kg VS.

    The reactor's inerts are the blend the feeds delivered, so the equivalent that
    converts inert COD back to inert mass is the same weighted mean the truth ``N_I``
    uses (:func:`sim.influent.nitrogen.truth_inert_nitrogen`).

    Raises:
        ValueError: On an unknown feed, a negative rate, or a recipe with no inert COD.
    """
    feeds = _feeds(catalogue)
    _check_rates(feeds, mass_rates)
    weighted = weight = 0.0
    for name in sorted(mass_rates):
        m = float(mass_rates[name])
        if m == 0.0:
            continue
        spec = feeds[name]
        frac = (fractionations or {}).get(name, spec.fractionation)
        w = m / spec.density * feed_cod_per_m3(spec, frac) * (frac.f_xi + frac.f_si)
        weighted += w * spec.inert_cod_equivalent
        weight += w
    if weight <= 0.0:
        raise ValueError("recipe carries no inert COD; the inert equivalent is undefined")
    return weighted / weight


def influent_ash_concentration(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    mass_rates: Mapping[str, float],
    ts_overrides: Mapping[str, float] | None = None,
) -> float:
    """Ash (fixed solids) of a blended feed, kg/m3 of wet feed.

    Ash is ``TS x (1 - VS/TS)`` per feed, flow-weighted. It is inert and conserved, which
    is what makes :func:`ash_trajectory` a one-line balance.

    Raises:
        ValueError: On an unknown feed, a negative rate, or zero total flow.
    """
    feeds = _feeds(catalogue)
    _check_rates(feeds, mass_rates)
    ash = q_total = 0.0
    for name in sorted(mass_rates):
        m = float(mass_rates[name])
        if m == 0.0:
            continue
        spec = feeds[name]
        ts = float((ts_overrides or {}).get(name, spec.ts))
        q = m / spec.density
        ash += q * ts * (1.0 - spec.vs_of_ts) * spec.density
        q_total += q
    if q_total <= 0.0:
        raise ValueError("total influent flow is zero")
    return ash / q_total


def ash_trajectory(
    t: np.ndarray, influent: Influent, V_liq: float, ash_in: np.ndarray | float, ash0: float = 0.0
) -> np.ndarray:
    """Ash concentration in the digestate, kg/m3, from the conserved-tracer balance.

    ``dC/dt = (Q/V)(C_in - C)``, solved exactly over each output step with the flow and
    the feed ash held at their values at the start of the step. The flow follows the
    influent's declared ``interpolation``, so a sample-and-hold series is held rather
    than interpolated. Ash takes no part in any reaction, so this needs no state in the
    truth model.

    Args:
        t: Output times, d (increasing).
        influent: The influent series (its ``q`` gives the flow).
        V_liq: Liquid volume, m3.
        ash_in: Ash of the feed, kg/m3, as a scalar or one value per influent sample.
        ash0: Initial digestate ash, kg/m3.

    Returns:
        Ash concentration at each time in ``t``, kg/m3.
    """
    t = np.asarray(t, dtype=float)
    if influent.t.size > 1:
        idx = np.clip(np.searchsorted(influent.t, t, side="right") - 1, 0, influent.t.size - 1)
        # the flow follows the influent's own convention, exactly as the truth model reads it
        q_at = (
            influent.q[idx]
            if influent.interpolation == "hold"
            else np.interp(t, influent.t, influent.q)
        )
    else:
        idx = np.zeros(t.size, dtype=int)
        q_at = np.full(t.size, influent.q[0])
    if np.ndim(ash_in) == 0:
        c_in_at = np.full(t.size, float(ash_in))
    else:
        c_in = np.asarray(ash_in, dtype=float)
        c_in_at = c_in[np.clip(idx, 0, c_in.size - 1)]
    out = np.empty(t.size)
    c = float(ash0)
    out[0] = c
    for i in range(1, t.size):
        dt = t[i] - t[i - 1]
        k = q_at[i - 1] / V_liq
        # exact solution of the linear balance over a step with the input held
        c = c_in_at[i - 1] + (c - c_in_at[i - 1]) * np.exp(-k * dt) if k > 0 else c
        out[i] = c
    return out


def channel_series(
    result: ExtendedResult,
    *,
    T_op: float,
    inert_cod_equivalent: float | None = None,
    ash: np.ndarray | None = None,
    effluent: np.ndarray | None = None,
    effluent_derived: Mapping[str, np.ndarray] | None = None,
) -> TruthChannels:
    """Every observable channel of one truth trajectory.

    Args:
        result: The extended-model trajectory (or the active zone of a two-zone run).
        T_op: Operating temperature, K (the truth model integrates at a fixed set point).
        inert_cod_equivalent: kg COD per kg of inert VS for this run's influent
            (:func:`influent_inert_cod_equivalent`); solids channels are omitted without it.
        ash: Digestate ash, kg/m3, per output time (:func:`ash_trajectory`); ``ts`` is
            omitted without it.
        effluent: ``(n_liquid, n_times)`` effluent concentrations to measure instead of
            the reactor's own liquid states (the two-zone reactor's bypassed effluent).
        effluent_derived: The **effluent's** speciation, required whenever ``effluent`` is
            given. The sampled channels (alkalinity, VFA anions) must come from the same
            liquid as the sampled concentrations, or FOS/TAC would be a ratio of two
            different liquids. The probe channels (pH, free ammonia) and every gas channel
            stay the reactor's, because that is where the probe and the headspace are.

    Returns:
        The channels, on ``result.t``.

    Raises:
        ValueError: If ``effluent`` is given without ``effluent_derived``.
    """
    if effluent is not None and effluent_derived is None:
        raise ValueError(
            "effluent needs effluent_derived: alkalinity and the VFA anions must come from "
            "the sampled liquid, not from the reactor's"
        )
    liquid = result.y[: len(LIQUID_STATE_NAMES)] if effluent is None else np.asarray(effluent)
    idx = {name: i for i, name in enumerate(LIQUID_STATE_NAMES)}
    d = result.derived
    #: speciation of the liquid that is *sampled* (the effluent, when there is a bypass)
    ds = d if effluent_derived is None else effluent_derived
    n = result.t.size

    # kg COD/m3 / (kg COD/kmol) = kmol/m3, then x kg/kmol = kg/m3. There is no further
    # factor: the anchor's own columns are mg/L (alkalinity 5,043, VFA 1,178 at the median),
    # i.e. kg/m3 at 5.04 and 1.18, and the alkalinity term below carries no factor either.
    vfa_kmol = {acid: liquid[idx[acid]] / cod for acid, cod in VFA_COD_PER_KMOL.items()}
    vfa_total_acetic = sum(vfa_kmol.values()) * M_ACETIC  # kg/m3 as acetic acid
    anion_charge = ds["S_hco3_ion"] + sum(
        ds[f"{acid}_ion"] / cod for acid, cod in VFA_COD_PER_KMOL.items()
    )
    alk_total = KG_CACO3_PER_KMOL_CHARGE * anion_charge
    alk_partial = KG_CACO3_PER_KMOL_CHARGE * ds["S_hco3_ion"]

    dry = np.maximum(d["P_gas"] - d["p_h2o"], 1e-12)
    # extension components sit AFTER the gas states in the vector, so the liquid slice
    # above misses them; a run with SAO on would otherwise report a COD that omits the
    # oxidiser biomass, in the very scenario (Level 5/6 ammonia) where it is the signal
    ext = _extension_states(result, liquid)
    cod_states = [s for s in LIQUID_STATE_NAMES if s in COD_PER_VS_BY_STATE] + ["S_I", "X_I"]
    cod_total = sum(liquid[idx[s]] for s in cod_states) + liquid[idx["S_ch4"]] + liquid[idx["S_h2"]]
    cod_total = cod_total + sum(ext[s] for s in EXTENSION_COD_PER_VS if s in ext)

    series: dict[str, np.ndarray] = {
        "temperature": np.full(n, float(T_op)),
        "pH": d["pH"],
        "q_gas_stp_dry": d["q_gas_stp_dry"],
        "q_gas_operating": d["q_gas"],
        "ch4_fraction": d["p_ch4"] / dry,
        "co2_fraction": d["p_co2"] / dry,
        "h2_ppm": d["p_h2"] / dry * 1e6,
        "alkalinity_total": alk_total,
        "alkalinity_partial": alk_partial,
        "vfa_total": vfa_total_acetic,
        "vfa_ac": vfa_kmol["S_ac"] * M_ACETIC,
        "vfa_pro": vfa_kmol["S_pro"] * M_PROPIONIC,
        "vfa_bu": vfa_kmol["S_bu"] * M_BUTYRIC,
        "vfa_va": vfa_kmol["S_va"] * M_VALERIC,
        "tan": liquid[idx["S_IN"]] * KG_N_PER_KMOL,
        "free_ammonia": d["S_nh3"] * KG_N_PER_KMOL,
        "cod_total": cod_total,
        "fos_tac": vfa_total_acetic / np.maximum(alk_total, 1e-12),
    }
    if inert_cod_equivalent is not None:
        vs = sum(liquid[idx[s]] / e for s, e in COD_PER_VS_BY_STATE.items())
        vs = vs + (liquid[idx["S_I"]] + liquid[idx["X_I"]]) / inert_cod_equivalent
        vs = vs + sum(ext[s] / e for s, e in EXTENSION_COD_PER_VS.items() if s in ext)
        series["vs"] = vs
        if ash is not None:
            # calcite precipitated in the reactor is inorganic suspended solids: it belongs
            # in TS and not in VS, and the feed-ash tracer cannot know about it because it
            # is formed here rather than fed
            formed = sum(ext[s] * kg for s, kg in EXTENSION_INORGANIC_SOLIDS.items() if s in ext)
            series["ts"] = vs + np.asarray(ash, dtype=float) + formed
    return TruthChannels(result.t, series)


def _extension_states(result: ExtendedResult, liquid: np.ndarray) -> dict[str, np.ndarray]:
    """Extension-component trajectories of a run, by name (empty when none are enabled).

    Extension components are appended after the gas states in the state vector, so they
    follow the 26 standard liquid states in an *effluent* array but sit at
    ``N_STATES:`` in a reactor state matrix.
    """
    n_liquid = len(LIQUID_STATE_NAMES)
    names = list(result.state_names[N_STATES:])
    if not names:
        return {}
    rows = result.y[N_STATES:] if liquid.shape[0] <= n_liquid else liquid[n_liquid:]
    return {name: rows[i] for i, name in enumerate(names) if i < rows.shape[0]}


def channels_from_two_zone(
    result: TwoZoneResult,
    *,
    T_op: float,
    inert_cod_equivalent: float | None = None,
    ash: np.ndarray | None = None,
) -> TruthChannels:
    """Channels of a two-zone run, each from where its instrument actually is.

    Three different places, and the point of the Level-6 scenario is that they disagree:

    * **the headspace** — every gas channel, from the active zone, because the two zones
      share one headspace;
    * **the probe in the reactor** — pH and free ammonia, from the active zone, because
      that is where the electrode hangs and what the biomass experiences;
    * **the grab sample** — alkalinity, VFA (total and speciated), COD, TAN and the solids,
      from the effluent *and from the effluent's own speciation*, so that FOS/TAC is a
      ratio taken on one liquid rather than across two.

    That last point is not cosmetic: with a bypass the effluent's acetate can be well above
    the active zone's, so alkalinity taken from the reactor while VFA is taken from the
    sample would misstate FOS/TAC — the quantity that also raises the overload and foaming
    flags behind the missingness model.
    """
    return channel_series(
        result.active,
        T_op=T_op,
        inert_cod_equivalent=inert_cod_equivalent,
        ash=ash,
        effluent=result.effluent,
        effluent_derived=result.effluent_derived,
    )


def condition_flags(
    channels: TruthChannels,
    *,
    fos_tac_overload: float,
    fos_tac_foaming: float,
    gas_surge_ratio: float,
    gas_median_window_d: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Overload and foaming flags per output time (proposal §6.1, missingness).

    ``overload``: FOS/TAC above its threshold. ``foaming``: FOS/TAC above the (lower)
    foaming threshold **and** the gas rate above ``gas_surge_ratio`` times its trailing
    median over ``gas_median_window_d`` days. The trailing median uses only past samples,
    so a flag never depends on the future.

    Returns:
        ``(overload, foaming)`` boolean arrays.
    """
    fos_tac = channels["fos_tac"]
    gas = channels["q_gas_stp_dry"]
    t = channels.t
    overload = fos_tac > fos_tac_overload
    # the window start by binary search on the (increasing) output times, rather than a
    # full boolean mask per sample: the mask made this O(n^2) and it dominated the suite's
    # runtime at the horizons the missingness tests need
    lo = np.searchsorted(t, t - gas_median_window_d, side="left")
    trailing = np.empty(t.size)
    for i in range(t.size):
        trailing[i] = np.median(gas[lo[i] : i + 1])
    foaming = (fos_tac > fos_tac_foaming) & (gas > gas_surge_ratio * trailing)
    return overload, foaming


def flags_at(overload: np.ndarray, foaming: np.ndarray, i: int) -> frozenset[str]:
    """The condition flags raised at output index ``i``."""
    raised = set()
    if bool(overload[i]):
        raised.add("overload")
    if bool(foaming[i]):
        raised.add("foaming")
    return frozenset(raised)
