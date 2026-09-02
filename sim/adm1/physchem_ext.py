"""Extended physico-chemistry for the truth-model extensions.

Adds to :mod:`sim.adm1.physchem`, without changing it:

* **Ionic-strength correction** (Davies activity coefficients on every acid-base
  constant, fixed-point iteration on the ionic strength);
* **Carbonate speciation** (second carbonic-acid dissociation, needed by the
  calcite-precipitation extension) and a divalent calcium term in the charge balance;
* the **calcite saturation-index rate**.

When every option is off and there is no calcium, :func:`speciate_extended` delegates
to the base functions, so the standard model's numbers are reproduced exactly.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from scipy.optimize import brentq

from sim.adm1 import physchem
from sim.adm1.physchem import (
    COD_PER_KMOL_AC,
    COD_PER_KMOL_BU,
    COD_PER_KMOL_PRO,
    COD_PER_KMOL_VA,
    TemperatureCorrected,
)
from sim.adm1.schema import PHSolverConfig


class SpeciationOptions(NamedTuple):
    """Switches and constants of the extended speciation."""

    ionic_strength: bool
    """Apply Davies activity coefficients (fixed-point iteration on I)."""
    carbonate: bool
    """Include HCO3- -> CO3 2- + H+ (needed for calcite)."""
    davies_A: float
    """Debye-Hueckel A, kg^0.5 mol^-0.5."""
    davies_b: float
    """Davies linear coefficient, -."""
    I_max: float
    """Cap on the ionic strength, mol/L (Davies is unreliable above ~0.5 M)."""
    pK_a2_co2: float
    """pK of HCO3-/CO3 2- (not temperature-corrected), -."""
    pK_sp_caco3: float
    """Calcite solubility product, -log10 of (mol/L)^2."""


OPTIONS_OFF = SpeciationOptions(False, False, 0.0, 0.0, 0.5, 10.33, 8.48)


class Equilibria(NamedTuple):
    """Concentration-based constants at given activity coefficients."""

    K_w: float
    K_a_va: float
    K_a_bu: float
    K_a_pro: float
    K_a_ac: float
    K_a_co2: float
    K_a_IN: float
    K_a2_co2: float
    K_sp_caco3: float


class ExtendedSpeciation(NamedTuple):
    """Speciation result with activity and carbonate information."""

    S_h: float
    """Proton concentration, kmol/m3."""
    pH: float
    """-log10 of the proton *activity* (equals concentration when ideal)."""
    S_va_ion: float
    S_bu_ion: float
    S_pro_ion: float
    S_ac_ion: float
    S_hco3_ion: float
    S_co3_ion: float
    S_co2: float
    S_nh3: float
    S_nh4_ion: float
    ionic_strength: float
    gamma1: float
    gamma2: float


def davies_gamma(ionic_strength: float, z: int, A: float, b: float) -> float:
    """Davies activity coefficient for charge ``z`` at ionic strength ``I`` (mol/L)."""
    if ionic_strength <= 0.0:
        return 1.0
    sqrt_i = math.sqrt(ionic_strength)
    return 10.0 ** (-A * z * z * (sqrt_i / (1.0 + sqrt_i) - b * ionic_strength))


def equilibria(
    k: TemperatureCorrected, opts: SpeciationOptions, gamma1: float, gamma2: float
) -> Equilibria:
    """Convert thermodynamic constants to concentration constants.

    ``HA -> H+ + A-``: ``K / (gamma_H gamma_A) = K / gamma1^2``. ``NH4+ -> NH3 + H+``:
    the two monovalent coefficients cancel. ``HCO3- -> CO3 2- + H+``:
    ``K2 gamma1 / (gamma1 gamma2) = K2 / gamma2``. ``K_sp`` stays thermodynamic; the
    activity product is formed with ``gamma2^2`` in :func:`precipitation_rate`.
    """
    g11 = gamma1 * gamma1
    return Equilibria(
        K_w=k.K_w / g11,
        K_a_va=k.K_a_va / g11,
        K_a_bu=k.K_a_bu / g11,
        K_a_pro=k.K_a_pro / g11,
        K_a_ac=k.K_a_ac / g11,
        K_a_co2=k.K_a_co2 / g11,
        K_a_IN=k.K_a_IN,
        K_a2_co2=(10.0**-opts.pK_a2_co2) / gamma2 if opts.carbonate else 0.0,
        K_sp_caco3=10.0**-opts.pK_sp_caco3,
    )


class _Totals(NamedTuple):
    va: float
    bu: float
    pro: float
    ac: float
    ic: float
    inn: float
    cat: float
    an: float
    ca: float


def _ions(S_h: float, tot: _Totals, eq: Equilibria) -> tuple[float, ...]:
    """Ionised species at ``S_h``: hco3, co3, nh3, va-, bu-, pro-, ac- (in state units)."""
    hco3_tot = tot.ic * eq.K_a_co2 / (eq.K_a_co2 + S_h)
    co3 = eq.K_a2_co2 * hco3_tot / S_h if eq.K_a2_co2 > 0.0 else 0.0
    return (
        hco3_tot - co3,
        co3,
        tot.inn * eq.K_a_IN / (eq.K_a_IN + S_h),
        tot.va * eq.K_a_va / (eq.K_a_va + S_h),
        tot.bu * eq.K_a_bu / (eq.K_a_bu + S_h),
        tot.pro * eq.K_a_pro / (eq.K_a_pro + S_h),
        tot.ac * eq.K_a_ac / (eq.K_a_ac + S_h),
    )


def _residual(pH: float, tot: _Totals, eq: Equilibria) -> float:
    S_h = 10.0**-pH
    hco3, co3, nh3, va, bu, pro, ac = _ions(S_h, tot, eq)
    return (
        tot.cat
        + 2.0 * tot.ca
        + (tot.inn - nh3)
        + S_h
        - hco3
        - 2.0 * co3
        - ac / COD_PER_KMOL_AC
        - pro / COD_PER_KMOL_PRO
        - bu / COD_PER_KMOL_BU
        - va / COD_PER_KMOL_VA
        - tot.an
        - eq.K_w / S_h
    )


def speciate_extended(
    S_va: float,
    S_bu: float,
    S_pro: float,
    S_ac: float,
    S_IC: float,
    S_IN: float,
    S_cat: float,
    S_an: float,
    S_ca: float,
    k: TemperatureCorrected,
    cfg: PHSolverConfig,
    opts: SpeciationOptions,
) -> ExtendedSpeciation:
    """Charge-balance pH and speciation with the optional activity and carbonate terms.

    Args:
        S_va: Total valerate, kg COD/m3.
        S_bu: Total butyrate, kg COD/m3.
        S_pro: Total propionate, kg COD/m3.
        S_ac: Total acetate, kg COD/m3.
        S_IC: Inorganic carbon, kmol/m3.
        S_IN: Inorganic nitrogen, kmol/m3.
        S_cat: Strong cations (monovalent), kmol/m3.
        S_an: Strong anions (monovalent), kmol/m3.
        S_ca: Dissolved calcium (divalent), kmol/m3.
        k: Temperature-corrected constants.
        cfg: pH root-find settings.
        opts: Extension switches and constants.

    Returns:
        The speciation. With all options off and no calcium this is the base model's
        speciation (delegated to :mod:`sim.adm1.physchem`), so the standard ADM1 numbers
        are reproduced bit for bit.
    """
    if not opts.ionic_strength and not opts.carbonate and S_ca == 0.0:
        S_h = physchem.solve_pH(S_va, S_bu, S_pro, S_ac, S_IC, S_IN, S_cat, S_an, k, cfg)
        sp = physchem.speciate(S_h, S_va, S_bu, S_pro, S_ac, S_IC, S_IN, k)
        return ExtendedSpeciation(
            S_h=S_h,
            pH=-math.log10(S_h),
            S_va_ion=sp.S_va_ion,
            S_bu_ion=sp.S_bu_ion,
            S_pro_ion=sp.S_pro_ion,
            S_ac_ion=sp.S_ac_ion,
            S_hco3_ion=sp.S_hco3_ion,
            S_co3_ion=0.0,
            S_co2=sp.S_co2,
            S_nh3=sp.S_nh3,
            S_nh4_ion=sp.S_nh4_ion,
            ionic_strength=0.0,
            gamma1=1.0,
            gamma2=1.0,
        )

    tot = _Totals(S_va, S_bu, S_pro, S_ac, S_IC, S_IN, S_cat, S_an, S_ca)
    gamma1 = gamma2 = 1.0
    ionic = 0.0
    lo, hi = cfg.bracket_pH
    for _ in range(8 if opts.ionic_strength else 1):
        eq = equilibria(k, opts, gamma1, gamma2)
        f_lo, f_hi = _residual(lo, tot, eq), _residual(hi, tot, eq)
        if f_lo * f_hi > 0.0:
            raise ValueError(
                f"charge balance has no root in pH bracket [{lo}, {hi}]: "
                f"residual({lo})={f_lo:.3e}, residual({hi})={f_hi:.3e}"
            )
        pH_c = brentq(
            _residual, lo, hi, args=(tot, eq), xtol=cfg.xtol_pH, rtol=cfg.rtol, maxiter=cfg.maxiter
        )
        S_h = 10.0**-pH_c
        hco3, co3, nh3, va, bu, pro, ac = _ions(S_h, tot, eq)
        if not opts.ionic_strength:
            break
        ionic_new = min(
            0.5
            * (
                tot.cat
                + tot.an
                + (tot.inn - nh3)
                + S_h
                + eq.K_w / S_h
                + hco3
                + 4.0 * co3
                + 4.0 * tot.ca
                + ac / COD_PER_KMOL_AC
                + pro / COD_PER_KMOL_PRO
                + bu / COD_PER_KMOL_BU
                + va / COD_PER_KMOL_VA
            ),
            opts.I_max,
        )
        gamma1 = davies_gamma(ionic_new, 1, opts.davies_A, opts.davies_b)
        gamma2 = davies_gamma(ionic_new, 2, opts.davies_A, opts.davies_b)
        converged = abs(ionic_new - ionic) < 1e-10
        ionic = ionic_new
        if converged:
            break
    return ExtendedSpeciation(
        S_h=S_h,
        pH=-math.log10(S_h * gamma1),
        S_va_ion=va,
        S_bu_ion=bu,
        S_pro_ion=pro,
        S_ac_ion=ac,
        S_hco3_ion=hco3,
        S_co3_ion=co3,
        S_co2=S_IC - hco3 - co3,
        S_nh3=nh3,
        S_nh4_ion=S_IN - nh3,
        ionic_strength=ionic,
        gamma1=gamma1,
        gamma2=gamma2,
    )


def precipitation_rate(
    S_ca: float, S_co3: float, K_sp: float, gamma2: float, k_prec: float, n: float
) -> float:
    """Calcite precipitation rate, kmol/m3/d: ``k (SI^(1/2) - 1)^n`` for SI > 1, else 0.

    ``SI = a_Ca a_CO3 / K_sp`` with activities ``gamma2 * concentration`` (Koutsoukos 1980
    form as used by ADM1-P, Flores-Alsina et al. 2016).
    """
    si = max(S_ca, 0.0) * max(S_co3, 0.0) * gamma2 * gamma2 / K_sp
    if si <= 1.0:
        return 0.0
    return k_prec * (math.sqrt(si) - 1.0) ** n
