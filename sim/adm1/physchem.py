"""Physico-chemistry: temperature corrections, acid-base speciation, pH, gas phase.

Everything here is a pure function of its arguments. Forms follow Rosen & Jeppsson (2006)
so that the model can be ring-tested against the BSM2 implementation.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from scipy.optimize import brentq

from sim.adm1.schema import PHSolverConfig, PhysicoChemicalParameters

#: kg COD per kmol for the VFA anions in the charge balance (valerate, butyrate,
#: propionate, acetate): 208, 160, 112, 64.
COD_PER_KMOL_VA = 208.0
COD_PER_KMOL_BU = 160.0
COD_PER_KMOL_PRO = 112.0
COD_PER_KMOL_AC = 64.0
COD_PER_KMOL_H2 = 16.0
COD_PER_KMOL_CH4 = 64.0


class TemperatureCorrected(NamedTuple):
    """Equilibrium, Henry and vapour constants at the operating temperature."""

    K_w: float
    """Water ion product, (kmol/m3)^2."""
    K_a_va: float
    K_a_bu: float
    K_a_pro: float
    K_a_ac: float
    K_a_co2: float
    K_a_IN: float
    K_H_h2: float
    """kmol/m3/bar."""
    K_H_ch4: float
    K_H_co2: float
    p_h2o: float
    """bar."""


def van_t_hoff(k_base: float, dH_J_mol: float, T_base: float, T: float, R_bar: float) -> float:
    """Temperature-correct an equilibrium constant with the van 't Hoff relation.

    Args:
        k_base: Constant at ``T_base``.
        dH_J_mol: Reaction enthalpy, J/mol.
        T_base: Reference temperature, K.
        T: Target temperature, K.
        R_bar: Gas constant in bar m3/kmol/K (BSM2 uses ``100 * R_bar`` J/mol/K).

    Returns:
        The constant at ``T``.
    """
    return k_base * math.exp(dH_J_mol / (100.0 * R_bar) * (1.0 / T_base - 1.0 / T))


def temperature_corrected(pc: PhysicoChemicalParameters, T: float) -> TemperatureCorrected:
    """All temperature-dependent constants at temperature ``T`` (K)."""
    return TemperatureCorrected(
        K_w=van_t_hoff(10.0**-pc.pK_w_base, pc.dH_K_w, pc.T_base, T, pc.R),
        K_a_va=10.0**-pc.pK_a_va,
        K_a_bu=10.0**-pc.pK_a_bu,
        K_a_pro=10.0**-pc.pK_a_pro,
        K_a_ac=10.0**-pc.pK_a_ac,
        K_a_co2=van_t_hoff(10.0**-pc.pK_a_co2_base, pc.dH_K_a_co2, pc.T_base, T, pc.R),
        K_a_IN=van_t_hoff(10.0**-pc.pK_a_IN_base, pc.dH_K_a_IN, pc.T_base, T, pc.R),
        K_H_h2=van_t_hoff(pc.K_H_h2_base, pc.dH_K_H_h2, pc.T_base, T, pc.R),
        K_H_ch4=van_t_hoff(pc.K_H_ch4_base, pc.dH_K_H_ch4, pc.T_base, T, pc.R),
        K_H_co2=van_t_hoff(pc.K_H_co2_base, pc.dH_K_H_co2, pc.T_base, T, pc.R),
        p_h2o=pc.p_h2o_base * math.exp(pc.h2o_vapour_coefficient * (1.0 / pc.T_base - 1.0 / T)),
    )


class Speciation(NamedTuple):
    """Ion split of the weak acids and bases at a given proton concentration."""

    S_va_ion: float
    S_bu_ion: float
    S_pro_ion: float
    S_ac_ion: float
    S_hco3_ion: float
    S_co2: float
    S_nh3: float
    S_nh4_ion: float


def speciate(
    S_h: float,
    S_va: float,
    S_bu: float,
    S_pro: float,
    S_ac: float,
    S_IC: float,
    S_IN: float,
    k: TemperatureCorrected,
) -> Speciation:
    """Equilibrium ion fractions for the monoprotic weak acids and ammonium.

    VFA totals and anions are in kg COD/m3; inorganic C and N in kmol/m3.
    """
    hco3 = S_IC * k.K_a_co2 / (k.K_a_co2 + S_h)
    nh3 = S_IN * k.K_a_IN / (k.K_a_IN + S_h)
    return Speciation(
        S_va_ion=S_va * k.K_a_va / (k.K_a_va + S_h),
        S_bu_ion=S_bu * k.K_a_bu / (k.K_a_bu + S_h),
        S_pro_ion=S_pro * k.K_a_pro / (k.K_a_pro + S_h),
        S_ac_ion=S_ac * k.K_a_ac / (k.K_a_ac + S_h),
        S_hco3_ion=hco3,
        S_co2=S_IC - hco3,
        S_nh3=nh3,
        S_nh4_ion=S_IN - nh3,
    )


def charge_balance(
    S_h: float,
    S_va: float,
    S_bu: float,
    S_pro: float,
    S_ac: float,
    S_IC: float,
    S_IN: float,
    S_cat: float,
    S_an: float,
    k: TemperatureCorrected,
) -> float:
    """Net charge (kmol/m3) at proton concentration ``S_h``; zero at the true pH.

    Cations minus anions: ``S_cat + NH4+ + H+ - HCO3- - Ac-/64 - Pro-/112 - Bu-/160
    - Va-/208 - S_an - OH-``. Strictly increasing in ``S_h``.
    """
    sp = speciate(S_h, S_va, S_bu, S_pro, S_ac, S_IC, S_IN, k)
    return (
        S_cat
        + sp.S_nh4_ion
        + S_h
        - sp.S_hco3_ion
        - sp.S_ac_ion / COD_PER_KMOL_AC
        - sp.S_pro_ion / COD_PER_KMOL_PRO
        - sp.S_bu_ion / COD_PER_KMOL_BU
        - sp.S_va_ion / COD_PER_KMOL_VA
        - S_an
        - k.K_w / S_h
    )


def solve_pH(
    S_va: float,
    S_bu: float,
    S_pro: float,
    S_ac: float,
    S_IC: float,
    S_IN: float,
    S_cat: float,
    S_an: float,
    k: TemperatureCorrected,
    cfg: PHSolverConfig,
) -> float:
    """Proton concentration (kmol/m3) that closes the charge balance.

    A bracketed Brent root-find in pH units over ``cfg.bracket_pH``; the residual is
    monotone in pH so the root is unique whenever the bracket contains it.

    Raises:
        ValueError: if the charge balance does not change sign across the bracket.
    """
    lo, hi = cfg.bracket_pH
    # Same algebra as charge_balance(), inlined with the acid anions pre-scaled to kmol/m3
    # because this residual is the innermost loop of the whole model.
    va, bu = S_va / COD_PER_KMOL_VA, S_bu / COD_PER_KMOL_BU
    pro, ac = S_pro / COD_PER_KMOL_PRO, S_ac / COD_PER_KMOL_AC
    strong = S_cat - S_an
    K_va, K_bu, K_pro, K_ac = k.K_a_va, k.K_a_bu, k.K_a_pro, k.K_a_ac
    K_co2, K_IN, K_w = k.K_a_co2, k.K_a_IN, k.K_w

    def residual(pH: float) -> float:
        S_h = 10.0**-pH
        return (
            strong
            + S_IN * S_h / (K_IN + S_h)
            + S_h
            - S_IC * K_co2 / (K_co2 + S_h)
            - ac * K_ac / (K_ac + S_h)
            - pro * K_pro / (K_pro + S_h)
            - bu * K_bu / (K_bu + S_h)
            - va * K_va / (K_va + S_h)
            - K_w / S_h
        )

    f_lo, f_hi = residual(lo), residual(hi)
    if f_lo * f_hi > 0.0:
        raise ValueError(
            f"charge balance has no root in pH bracket [{lo}, {hi}]: "
            f"residual({lo})={f_lo:.3e}, residual({hi})={f_hi:.3e}"
        )
    pH = brentq(residual, lo, hi, xtol=cfg.xtol_pH, rtol=cfg.rtol, maxiter=cfg.maxiter)
    return 10.0**-pH


class GasPhase(NamedTuple):
    """Headspace partial pressures and outflow."""

    p_h2: float
    p_ch4: float
    p_co2: float
    p_h2o: float
    P_gas: float
    """Total pressure, bar."""
    q_gas_raw: float
    """Volumetric outflow at headspace pressure and T_op, m3/d (drives the gas ODE)."""
    q_gas: float
    """Outflow normalised to P_atm at T_op, m3/d (BSM2 reporting convention)."""


def gas_phase(
    S_gas_h2: float,
    S_gas_ch4: float,
    S_gas_co2: float,
    T: float,
    pc: PhysicoChemicalParameters,
    p_h2o: float,
) -> GasPhase:
    """Partial pressures from headspace concentrations and the BSM2 outflow law.

    ``q_gas_raw = k_p (P_gas - P_atm)``, clipped at zero; the reported ``q_gas`` is
    ``q_gas_raw * P_gas / P_atm``.
    """
    RT = pc.R * T
    p_h2 = S_gas_h2 * RT / COD_PER_KMOL_H2
    p_ch4 = S_gas_ch4 * RT / COD_PER_KMOL_CH4
    p_co2 = S_gas_co2 * RT
    P_gas = p_h2 + p_ch4 + p_co2 + p_h2o
    q_raw = max(pc.k_p * (P_gas - pc.P_atm), 0.0)
    return GasPhase(p_h2, p_ch4, p_co2, p_h2o, P_gas, q_raw, q_raw * P_gas / pc.P_atm)


def q_gas_stp_dry(q_gas: float, P_gas: float, p_h2o: float, T: float) -> float:
    """Dry gas flow at 0 degC / 1 atm from the BSM2-convention flow (CLAUDE.md rule 6).

    The BSM2 flow is already normalised to atmospheric pressure, so only the temperature
    ratio and the water-vapour fraction remain.
    """
    return q_gas * (273.15 / T) * (1.0 - p_h2o / P_gas)
