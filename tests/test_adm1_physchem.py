"""Temperature corrections, speciation, the pH root-find and the gas phase."""

from __future__ import annotations

import math

import numpy as np
import pytest

from sim.adm1 import physchem
from sim.adm1.rates import inhibition_ph_hill


@pytest.fixture(scope="module")
def k35(adm1_params):
    return physchem.temperature_corrected(adm1_params.physchem, 308.15)


def test_no_correction_at_base_temperature(adm1_params):
    pc = adm1_params.physchem
    k = physchem.temperature_corrected(pc, pc.T_base)
    assert k.K_w == pytest.approx(10.0**-pc.pK_w_base)
    assert k.K_a_co2 == pytest.approx(10.0**-pc.pK_a_co2_base)
    assert k.K_a_IN == pytest.approx(10.0**-pc.pK_a_IN_base)
    assert k.K_H_co2 == pytest.approx(pc.K_H_co2_base)
    assert k.p_h2o == pytest.approx(pc.p_h2o_base)


def test_bsm2_values_at_35_degc(k35):
    """Spot values reproduced from the BSM2 report / bsm2-python arithmetic."""
    assert k35.p_h2o == pytest.approx(0.0557, rel=2e-3)  # R&J 2006: 0.0557 bar
    assert -math.log10(k35.K_w) == pytest.approx(13.68, abs=0.01)  # pK_w drops with T
    assert k35.K_H_co2 < 0.035 and k35.K_H_ch4 < 0.0014 and k35.K_H_h2 < 7.8e-4  # less soluble
    assert k35.K_a_IN > 10**-9.25  # ammonia more acidic when warmer


def test_pure_water_has_neutral_ph(adm1_params, adm1_solver):
    pc = adm1_params.physchem
    k = physchem.temperature_corrected(pc, pc.T_base)
    S_h = physchem.solve_pH(0, 0, 0, 0, 0, 0, 0, 0, k, adm1_solver.pH_solver)
    assert -math.log10(S_h) == pytest.approx(7.0, abs=1e-9)


def test_root_closes_charge_balance(k35, adm1_solver, probe_common):
    ss = probe_common.STEADY_STATE_RJ2006
    args = (
        ss["S_va"],
        ss["S_bu"],
        ss["S_pro"],
        ss["S_ac"],
        ss["S_IC"],
        ss["S_IN"],
        ss["S_cat"],
        ss["S_an"],
    )
    S_h = physchem.solve_pH(*args, k35, adm1_solver.pH_solver)
    assert abs(physchem.charge_balance(S_h, *args, k35)) < 1e-14
    # R&J 2006 Table 5 reports pH 7.2631 for this state; the table's ion states are
    # rounded to four decimals, which moves the charge-balance pH by a few thousandths
    assert -math.log10(S_h) == pytest.approx(7.2631, abs=5e-3)


def test_charge_balance_is_monotone(k35, probe_common):
    ss = probe_common.STEADY_STATE_RJ2006
    pHs = np.linspace(0, 14, 500)
    vals = [
        physchem.charge_balance(
            10.0**-p,
            ss["S_va"],
            ss["S_bu"],
            ss["S_pro"],
            ss["S_ac"],
            ss["S_IC"],
            ss["S_IN"],
            ss["S_cat"],
            ss["S_an"],
            k35,
        )
        for p in pHs
    ]
    assert np.all(np.diff(vals) < 0)


def test_algebraic_root_equals_bsm2_ode_formulation(k35, adm1_solver, probe_common):
    """At equilibrium, the BSM2 quadratic in phi gives the same S_h as our root-find."""
    ss = probe_common.STEADY_STATE_RJ2006
    S_h = physchem.solve_pH(
        ss["S_va"],
        ss["S_bu"],
        ss["S_pro"],
        ss["S_ac"],
        ss["S_IC"],
        ss["S_IN"],
        ss["S_cat"],
        ss["S_an"],
        k35,
        adm1_solver.pH_solver,
    )
    sp = physchem.speciate(
        S_h, ss["S_va"], ss["S_bu"], ss["S_pro"], ss["S_ac"], ss["S_IC"], ss["S_IN"], k35
    )
    phi = (
        ss["S_cat"]
        + sp.S_nh4_ion
        - sp.S_hco3_ion
        - sp.S_ac_ion / 64
        - sp.S_pro_ion / 112
        - sp.S_bu_ion / 160
        - sp.S_va_ion / 208
        - ss["S_an"]
    )
    S_h_bsm2 = -phi / 2 + math.sqrt(phi * phi + 4 * k35.K_w) / 2
    assert S_h_bsm2 == pytest.approx(S_h, rel=1e-10)


def test_bracket_without_sign_change_raises(k35, adm1_solver):
    cfg = adm1_solver.pH_solver.model_copy(update={"bracket_pH": (12.0, 14.0)})
    with pytest.raises(ValueError, match="no root"):
        physchem.solve_pH(0.01, 0.01, 0.01, 0.1, 0.1, 0.1, 0.0, 0.0, k35, cfg)


def test_speciation_fractions(k35):
    sp = physchem.speciate(10**-7.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, k35)
    # VFAs are almost fully dissociated at pH 7 (pKa ~ 4.8), ammonia mostly NH4+
    assert 0.99 < sp.S_ac_ion < 1.0
    assert sp.S_nh3 + sp.S_nh4_ion == pytest.approx(1.0)
    assert sp.S_nh3 < 0.05
    assert sp.S_co2 + sp.S_hco3_ion == pytest.approx(1.0)


def test_gas_phase_reproduces_rj2006_pressures(adm1_params, k35, probe_common):
    """Same arithmetic as the harness's RJ2006_GAS (derived, not copied, from S_gas)."""
    ref = probe_common.RJ2006_GAS
    g = physchem.gas_phase(1.1032e-5, 1.6535, 0.0135, 308.15, adm1_params.physchem, k35.p_h2o)
    assert g.p_ch4 == pytest.approx(ref["p_ch4_bar"])
    assert g.p_co2 == pytest.approx(ref["p_co2_bar"])
    assert g.p_h2 == pytest.approx(ref["p_h2_bar"])
    assert g.p_h2o == pytest.approx(ref["p_h2o_bar"], rel=2e-3)
    assert g.q_gas == pytest.approx(ref["q_gas_m3_d"], rel=1e-2)


def test_gas_outflow_is_clipped_at_zero(adm1_params, k35):
    g = physchem.gas_phase(0.0, 0.0, 0.0, 308.15, adm1_params.physchem, k35.p_h2o)
    assert g.P_gas == pytest.approx(k35.p_h2o) and g.q_gas == 0.0 and g.q_gas_raw == 0.0


def test_stp_dry_conversion():
    q = physchem.q_gas_stp_dry(1000.0, 1.069, 0.0557, 308.15)
    assert q == pytest.approx(1000.0 * 273.15 / 308.15 * (1 - 0.0557 / 1.069))


def test_hill_ph_inhibition_shape():
    ul, ll = 7.0, 6.0
    assert inhibition_ph_hill(10.0**-8, ul, ll) > 0.999
    assert inhibition_ph_hill(10.0**-6.5, ul, ll) == pytest.approx(0.5)
    assert inhibition_ph_hill(10.0**-5, ul, ll) < 0.01
