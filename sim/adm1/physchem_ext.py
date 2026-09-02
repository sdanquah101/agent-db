"""Extended physico-chemistry for the truth-model extensions.

Adds to :mod:`sim.adm1.physchem`, without changing it:

* **Ionic-strength correction** (Davies activity coefficients on every acid-base
  constant, fixed-point iteration on the ionic strength);
* **Carbonate speciation** (second carbonic-acid dissociation in the charge balance and
  the inorganic-carbon split) and a divalent calcium term in the charge balance;
* the **calcite saturation-index rate**, which needs a carbonate concentration: the
  speciated one when the carbonate switch is on, otherwise a *diagnostic* estimate
  ``K_a2 [HCO3-] / [H+]`` that is reported but takes no part in the balance.

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

T_REF_DAVIES = 298.15
"""Reference temperature, K, at which the configured Debye-Hueckel A applies."""


class SpeciationOptions(NamedTuple):
    """Switches and constants of the extended speciation."""

    ionic_strength: bool
    """Apply Davies activity coefficients (fixed-point iteration on I)."""
    carbonate: bool
    """Include HCO3- -> CO3 2- + H+ in the charge balance and the S_IC split."""
    davies_A: float
    """Debye-Hueckel A **at the operating temperature**, kg^0.5 mol^-0.5."""
    davies_b: float
    """Davies linear coefficient, -."""
    I_max: float
    """Cap on the ionic strength, mol/L (Davies is unreliable above ~0.5 M)."""
    pK_a2_co2: float
    """pK of HCO3-/CO3 2- (not temperature-corrected), -."""
    pK_sp_caco3: float
    """Calcite solubility product, -log10 of (mol/L)^2 (NaN when calcite is not enabled)."""


def water_permittivity(T: float) -> float:
    """Relative permittivity of liquid water at ``T`` (K), Malmberg & Maryott (1956) fit.

    Valid 0-100 C; 78.30 at 25 C, 74.83 at 35 C, 68.34 at 55 C.
    """
    t = T - 273.15
    return 87.740 - 0.40008 * t + 9.398e-4 * t * t - 1.410e-6 * t * t * t


def water_density(T: float) -> float:
    """Density of liquid water at ``T`` (K), kg/L, polynomial after Kell (1975).

    The form quoted in McCutcheon, Martin & Barnwell (1993); 0.99705 at 25 C,
    0.98572 at 55 C.
    """
    t = T - 273.15
    return 1.0 - (t + 288.9414) / (508929.2 * (t + 68.12963)) * (t - 3.9863) ** 2


def debye_huckel_A(T: float) -> float:
    """Debye-Hueckel ``A`` (log10 form), kg^0.5 mol^-0.5, of water at ``T`` (K).

    ``A = 1.82483e6 sqrt(rho) / (eps T)^1.5`` (Robinson & Stokes; the form PHREEQC uses),
    with :func:`water_permittivity` and :func:`water_density`. Gives 0.511 at 25 C
    (tabulated values are 0.509-0.512 depending on the permittivity source), 0.520 at
    35 C and 0.539 at 55 C. The configured constant is scaled by the *ratio*
    ``A(T)/A(25 C)`` (:func:`davies_A_at`), so its 25 C value is what the config says and
    only the temperature trend comes from this formula.
    """
    return 1.82483e6 * math.sqrt(water_density(T)) / (water_permittivity(T) * T) ** 1.5


def davies_A_at(A_ref: float, T: float) -> float:
    """Scale a Debye-Hueckel ``A`` given at 25 C to the operating temperature ``T`` (K).

    Using the 25 C constant unscaled would understate ``log10 gamma`` by ≈ 1.7 % at 35 C
    and ≈ 5.6 % at 55 C (thermophilic digesters).
    """
    return A_ref * debye_huckel_A(T) / debye_huckel_A(T_REF_DAVIES)


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
    """CO3 2-, kmol/m3. With the carbonate switch on this is the speciated fraction of
    S_IC (in the charge balance and the S_IC split); with it off it is the diagnostic
    estimate ``K_a2 [HCO3-] / [H+]`` used only by the calcite rate."""
    S_co2: float
    S_nh3: float
    S_nh4_ion: float
    ionic_strength: float
    """I = 0.5 sum(c z^2) over the species in the charge balance, mol/L. Always computed
    from the returned speciation, whether or not the Davies correction is applied."""
    gamma1: float
    gamma2: float


def _ionic_strength(
    tot: _Totals, S_h: float, K_w: float, hco3: float, co3: float, nh3: float, vfa: float
) -> float:
    """I = 0.5 sum(c z^2), mol/L, with strong ions monovalent and ``vfa`` in kmol/m3."""
    return 0.5 * (
        tot.cat + tot.an + (tot.inn - nh3) + S_h + K_w / S_h + hco3 + 4.0 * co3 + 4.0 * tot.ca + vfa
    )


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
    ``K2 gamma1 / (gamma1 gamma2) = K2 / gamma2`` (always computed; whether it enters the
    charge balance is ``opts.carbonate``). ``K_sp`` stays thermodynamic; the activity
    product is formed with ``gamma2^2`` in :func:`precipitation_rate`.
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
        K_a2_co2=(10.0**-opts.pK_a2_co2) / gamma2,
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


def _ions(S_h: float, tot: _Totals, eq: Equilibria, carbonate: bool) -> tuple[float, ...]:
    """Ionised species at ``S_h``: hco3, co3, nh3, va-, bu-, pro-, ac- (in state units).

    With ``carbonate`` the inorganic carbon is split three ways (CO2 / HCO3- / CO3 2-)
    with the exact denominator ``[H+]^2 + K1 [H+] + K1 K2``; without it the base two-way
    split is used and ``co3`` is zero *in the balance* (the diagnostic estimate is added
    by the caller).
    """
    if carbonate:
        d = S_h * S_h + eq.K_a_co2 * S_h + eq.K_a_co2 * eq.K_a2_co2
        hco3 = tot.ic * eq.K_a_co2 * S_h / d
        co3 = tot.ic * eq.K_a_co2 * eq.K_a2_co2 / d
    else:
        hco3 = tot.ic * eq.K_a_co2 / (eq.K_a_co2 + S_h)
        co3 = 0.0
    return (
        hco3,
        co3,
        tot.inn * eq.K_a_IN / (eq.K_a_IN + S_h),
        tot.va * eq.K_a_va / (eq.K_a_va + S_h),
        tot.bu * eq.K_a_bu / (eq.K_a_bu + S_h),
        tot.pro * eq.K_a_pro / (eq.K_a_pro + S_h),
        tot.ac * eq.K_a_ac / (eq.K_a_ac + S_h),
    )


def _residual(pH: float, tot: _Totals, eq: Equilibria, carbonate: bool) -> float:
    S_h = 10.0**-pH
    hco3, co3, nh3, va, bu, pro, ac = _ions(S_h, tot, eq, carbonate)
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
        are reproduced bit for bit; ``S_co3_ion`` is then the diagnostic estimate.

    Raises:
        ValueError: If the charge balance has no root in the bracket, or the ionic-strength
            fixed-point iteration does not converge within
            ``cfg.ionic_strength_solver.max_iter`` iterations.
    """
    tot = _Totals(S_va, S_bu, S_pro, S_ac, S_IC, S_IN, S_cat, S_an, S_ca)
    if not opts.ionic_strength and not opts.carbonate and S_ca == 0.0:
        S_h = physchem.solve_pH(S_va, S_bu, S_pro, S_ac, S_IC, S_IN, S_cat, S_an, k, cfg)
        sp = physchem.speciate(S_h, S_va, S_bu, S_pro, S_ac, S_IC, S_IN, k)
        vfa = (
            sp.S_ac_ion / COD_PER_KMOL_AC
            + sp.S_pro_ion / COD_PER_KMOL_PRO
            + sp.S_bu_ion / COD_PER_KMOL_BU
            + sp.S_va_ion / COD_PER_KMOL_VA
        )
        return ExtendedSpeciation(
            S_h=S_h,
            pH=-math.log10(S_h),
            S_va_ion=sp.S_va_ion,
            S_bu_ion=sp.S_bu_ion,
            S_pro_ion=sp.S_pro_ion,
            S_ac_ion=sp.S_ac_ion,
            S_hco3_ion=sp.S_hco3_ion,
            S_co3_ion=(10.0**-opts.pK_a2_co2) * sp.S_hco3_ion / S_h,
            S_co2=sp.S_co2,
            S_nh3=sp.S_nh3,
            S_nh4_ion=sp.S_nh4_ion,
            ionic_strength=_ionic_strength(tot, S_h, k.K_w, sp.S_hco3_ion, 0.0, sp.S_nh3, vfa),
            gamma1=1.0,
            gamma2=1.0,
        )

    gamma1 = gamma2 = 1.0
    ionic = 0.0
    lo, hi = cfg.bracket_pH
    carb = opts.carbonate
    isc = cfg.ionic_strength_solver
    converged = not opts.ionic_strength
    for _ in range(isc.max_iter if opts.ionic_strength else 1):
        eq = equilibria(k, opts, gamma1, gamma2)
        f_lo, f_hi = _residual(lo, tot, eq, carb), _residual(hi, tot, eq, carb)
        if f_lo * f_hi > 0.0:
            raise ValueError(
                f"charge balance has no root in pH bracket [{lo}, {hi}]: "
                f"residual({lo})={f_lo:.3e}, residual({hi})={f_hi:.3e}"
            )
        pH_c = brentq(
            _residual,
            lo,
            hi,
            args=(tot, eq, carb),
            xtol=cfg.xtol_pH,
            rtol=cfg.rtol,
            maxiter=cfg.maxiter,
        )
        S_h = 10.0**-pH_c
        hco3, co3, nh3, va, bu, pro, ac = _ions(S_h, tot, eq, carb)
        vfa = (
            ac / COD_PER_KMOL_AC
            + pro / COD_PER_KMOL_PRO
            + bu / COD_PER_KMOL_BU
            + va / COD_PER_KMOL_VA
        )
        ionic_new = _ionic_strength(tot, S_h, eq.K_w, hco3, co3, nh3, vfa)
        if not opts.ionic_strength:
            ionic = ionic_new
            break
        ionic_new = min(ionic_new, opts.I_max)
        gamma1 = davies_gamma(ionic_new, 1, opts.davies_A, opts.davies_b)
        gamma2 = davies_gamma(ionic_new, 2, opts.davies_A, opts.davies_b)
        converged = abs(ionic_new - ionic) <= isc.rtol_I * ionic_new
        ionic = ionic_new
        if converged:
            break
    if not converged:
        raise ValueError(
            f"ionic-strength fixed-point iteration did not converge in {isc.max_iter} "
            f"iterations (I = {ionic:.4e} mol/L, rtol_I = {isc.rtol_I:g})"
        )
    S_co2 = S_IC - hco3 - co3
    if not carb:
        co3 = eq.K_a2_co2 * hco3 / S_h  # diagnostic only (not in the balance or S_co2)
    return ExtendedSpeciation(
        S_h=S_h,
        pH=-math.log10(S_h * gamma1),
        S_va_ion=va,
        S_bu_ion=bu,
        S_pro_ion=pro,
        S_ac_ion=ac,
        S_hco3_ion=hco3,
        S_co3_ion=co3,
        S_co2=S_co2,
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
