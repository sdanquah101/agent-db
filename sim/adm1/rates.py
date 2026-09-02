"""Inhibition functions and the 19 biochemical process rates of standard ADM1.

The rate vector order must match the process order in ``configs/adm1/petersen_matrix.yaml``
(checked by a test). All functions are pure.
"""

from __future__ import annotations

import numpy as np

from sim.adm1.schema import KineticParameters

#: Process names in rate-vector order (must equal the matrix file's process order).
PROCESS_NAMES: tuple[str, ...] = (
    "disintegration",
    "hydrolysis_carbohydrates",
    "hydrolysis_proteins",
    "hydrolysis_lipids",
    "uptake_sugars",
    "uptake_amino_acids",
    "uptake_lcfa",
    "uptake_valerate",
    "uptake_butyrate",
    "uptake_propionate",
    "uptake_acetate",
    "uptake_hydrogen",
    "decay_X_su",
    "decay_X_aa",
    "decay_X_fa",
    "decay_X_c4",
    "decay_X_pro",
    "decay_X_ac",
    "decay_X_h2",
)


def inhibition_ph_hill(S_h: float, pH_UL: float, pH_LL: float) -> float:
    """BSM2 Hill-type pH inhibition on the proton concentration (ADM1 workshop 2005).

    ``I = K^n / (S_h^n + K^n)`` with ``K = 10^-((pH_UL + pH_LL)/2)`` and
    ``n = 3 / (pH_UL - pH_LL)``: 1 well above ``pH_UL``, 0.5 at the midpoint, ~0 below
    ``pH_LL``.
    """
    n = 3.0 / (pH_UL - pH_LL)
    K = 10.0 ** (-(pH_UL + pH_LL) / 2.0)
    Kn = K**n
    return Kn / (S_h**n + Kn)


def inhibition_noncompetitive(S_I: float, K_I: float) -> float:
    """``1 / (1 + S_I / K_I)`` (H2 and free-ammonia inhibition)."""
    return 1.0 / (1.0 + S_I / K_I)


def limitation_secondary_substrate(S: float, K_S: float) -> float:
    """``1 / (1 + K_S / S)`` (inorganic-nitrogen limitation); zero when ``S`` is zero."""
    if S <= 0.0:
        return 0.0
    return 1.0 / (1.0 + K_S / S)


def monod(S: float, K_S: float) -> float:
    """``S / (K_S + S)``."""
    return S / (K_S + S)


def process_rates(
    y: np.ndarray,
    S_h: float,
    S_nh3: float,
    kin: KineticParameters,
) -> np.ndarray:
    """The 19 ADM1 process rates (kg COD/m3/d) in :data:`PROCESS_NAMES` order.

    Args:
        y: Liquid states (at least the first 24, in STATE order). Callers decide whether
            negative values are clipped before this call.
        S_h: Proton concentration, kmol/m3.
        S_nh3: Free ammonia, kmol N/m3.
        kin: Kinetic parameters.
    """
    (
        S_su,
        S_aa,
        S_fa,
        S_va,
        S_bu,
        S_pro,
        S_ac,
        S_h2,
        _S_ch4,
        _S_IC,
        S_IN,
        _S_I,
        X_xc,
        X_ch,
        X_pr,
        X_li,
        X_su,
        X_aa,
        X_fa,
        X_c4,
        X_pro,
        X_ac,
        X_h2,
    ) = y[:23]

    I_pH_aa = inhibition_ph_hill(S_h, kin.pH_UL_aa, kin.pH_LL_aa)
    I_pH_ac = inhibition_ph_hill(S_h, kin.pH_UL_ac, kin.pH_LL_ac)
    I_pH_h2 = inhibition_ph_hill(S_h, kin.pH_UL_h2, kin.pH_LL_h2)
    I_IN = limitation_secondary_substrate(S_IN, kin.K_S_IN)
    I_h2_fa = inhibition_noncompetitive(S_h2, kin.K_I_h2_fa)
    I_h2_c4 = inhibition_noncompetitive(S_h2, kin.K_I_h2_c4)
    I_h2_pro = inhibition_noncompetitive(S_h2, kin.K_I_h2_pro)
    I_nh3 = inhibition_noncompetitive(S_nh3, kin.K_I_nh3)

    I_acido = I_pH_aa * I_IN
    c4_total = S_va + S_bu + kin.eps_c4

    return np.array(
        [
            kin.k_dis * X_xc,
            kin.k_hyd_ch * X_ch,
            kin.k_hyd_pr * X_pr,
            kin.k_hyd_li * X_li,
            kin.k_m_su * monod(S_su, kin.K_S_su) * X_su * I_acido,
            kin.k_m_aa * monod(S_aa, kin.K_S_aa) * X_aa * I_acido,
            kin.k_m_fa * monod(S_fa, kin.K_S_fa) * X_fa * I_acido * I_h2_fa,
            kin.k_m_c4 * monod(S_va, kin.K_S_c4) * X_c4 * (S_va / c4_total) * I_acido * I_h2_c4,
            kin.k_m_c4 * monod(S_bu, kin.K_S_c4) * X_c4 * (S_bu / c4_total) * I_acido * I_h2_c4,
            kin.k_m_pro * monod(S_pro, kin.K_S_pro) * X_pro * I_acido * I_h2_pro,
            kin.k_m_ac * monod(S_ac, kin.K_S_ac) * X_ac * I_pH_ac * I_IN * I_nh3,
            kin.k_m_h2 * monod(S_h2, kin.K_S_h2) * X_h2 * I_pH_h2 * I_IN,
            kin.k_dec_X_su * X_su,
            kin.k_dec_X_aa * X_aa,
            kin.k_dec_X_fa * X_fa,
            kin.k_dec_X_c4 * X_c4,
            kin.k_dec_X_pro * X_pro,
            kin.k_dec_X_ac * X_ac,
            kin.k_dec_X_h2 * X_h2,
        ]
    )
