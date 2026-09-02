"""Truth-model extensions: SAO, ionic-strength correction, calcite precipitation.

Each extension must (a) reduce to standard ADM1 when inert, (b) do what it claims when
active, (c) conserve COD, C and N row by row, and (d) keep the model integrable. The
extended right-hand side is also run against the bsm2-python oracle with every
extension enabled but inert, so the extension code path itself is ring-tested.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from sim.adm1 import LIQUID_STATE_NAMES, STATE_NAMES, Influent, simulate
from sim.adm1.extensions import (
    EXTENSION_RATES,
    RateContext,
    compile_extended,
    conservation_residuals,
    extended_state,
    load_extensions,
    simulate_extended,
)
from sim.adm1.physchem_ext import (
    ExtendedSpeciation,
    davies_A_at,
    davies_gamma,
    debye_huckel_A,
    equilibria,
)
from sim.adm1.rates import inhibition_noncompetitive
from tests.conftest import CANDIDATES_DIR

ALL = ("sao", "ionic_strength", "carbonate", "precipitation")


@pytest.fixture(scope="module")
def ext_config():
    return load_extensions()


@pytest.fixture(scope="module")
def feed(probe_common):
    return np.array(probe_common.influent_vector(1.0)), probe_common.Q_IN_M3_D


def _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, enabled, **over: float):
    return compile_extended(
        adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, enabled, over or None
    )


def _run(model, rj2006_state, feed, days, *, q=None, feed_over=None, y_ext=None, u_ext=None):
    u, q0 = feed
    u = u.copy()
    for name, value in (feed_over or {}).items():
        u[LIQUID_STATE_NAMES.index(name)] = value
    return simulate_extended(
        y0=extended_state(model, rj2006_state, y_ext or {}),
        influent=Influent.constant(u, q if q is not None else q0),
        model=model,
        t_span=(0.0, days),
        t_eval=np.arange(0.0, days + 1e-9, 0.25),
        u_ext=u_ext,
    )


def _base(
    rj2006_state,
    feed,
    adm1_params,
    adm1_plant,
    adm1_matrix,
    adm1_solver,
    days,
    q=None,
    feed_over=None,
):
    u, q0 = feed
    u = u.copy()
    for name, value in (feed_over or {}).items():
        u[LIQUID_STATE_NAMES.index(name)] = value
    return simulate(
        y0=rj2006_state,
        influent=Influent.constant(u, q if q is not None else q0),
        params=adm1_params,
        plant=adm1_plant,
        matrix=adm1_matrix,
        solver=adm1_solver,
        t_span=(0.0, days),
        t_eval=np.arange(0.0, days + 1e-9, 0.25),
    )


# ----------------------------------------------------------------- config / matrix


def test_config_loads_and_every_process_has_rate_code(ext_config):
    assert set(ext_config.extensions) == set(ALL)
    for spec in ext_config.extensions.values():
        for proc in spec.processes:
            assert proc.name in EXTENSION_RATES, proc.name
        for par in spec.parameters.values():
            assert par.unit


@pytest.mark.parametrize("enabled", [(), *[(e,) for e in ALL], ALL])
def test_rows_conserve_cod_c_n_and_charge(
    adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, enabled
):
    model = _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, enabled)
    res = conservation_residuals(model)
    assert np.max(np.abs(res["COD"])) < 1e-12
    assert np.max(np.abs(res["C"])) < 1e-12
    assert np.max(np.abs(res["N"])) < 1e-12
    names = [p.name for p in model.processes]
    for j, name in enumerate(names, start=19):
        # The calcite row {S_ca: -1, S_IC: -1, X_caco3: +1} shows -2 because S_IC is an
        # uncharged *total* in the matrix (its CO2/HCO3-/CO3 2- split is algebraic) while
        # the species that actually leaves is CO3 2-. After speciation the balance closes:
        # the carbonate removed carried -2, matching the +2 of the calcium removed
        # (checked dynamically in test_precipitation_leaves_the_charge_balance_closed).
        expected = -2.0 if name == "precipitation_caco3" else 0.0
        assert res["charge"][j] == pytest.approx(expected, abs=1e-12), name
    assert np.max(np.abs(res["charge"][:19])) < 1e-12


def test_state_layout_and_matrix_shape(
    adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    m = _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ALL)
    assert m.state_names[:29] == STATE_NAMES
    assert m.state_names[29:] == ("X_sao", "S_ca", "X_caco3")
    assert m.nu.shape == (26 + 3, 19 + 3)
    np.testing.assert_array_equal(m.nu[:26, :19], m.base.nu)
    j = [p.name for p in m.processes].index("precipitation_caco3") + 19
    assert m.nu[m.components.index(next(c for c in m.components if c.name == "S_IC")), j] == -1.0


def test_compile_rejects_bad_inputs(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config):
    with pytest.raises(ValueError, match="unknown extensions"):
        _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("magic",))
    with pytest.raises(ValueError, match="not a parameter of an enabled"):
        _model(
            adm1_params,
            adm1_plant,
            adm1_matrix,
            adm1_solver,
            ext_config,
            ("sao",),
            k_prec_caco3=0.0,
        )
    with pytest.raises(ValueError, match="repeated"):
        _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("sao", "sao"))


# ------------------------------------------------------------ inert == standard


def test_inert_extensions_reproduce_the_oracle(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, probe_common
):
    """Probe 1 through the extended RHS with SAO, ionic strength and calcite on but inert.

    Inert: zero rates, A = 0, no calcium. The carbonate switch is left off: it is a
    genuine (small) model change even with nothing precipitating;
    ``test_carbonate_switch_is_a_small_model_change`` pins it.
    """
    model = _model(
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        ext_config,
        ("sao", "ionic_strength", "precipitation"),
        k_m_sao=0.0,
        davies_A=0.0,
        k_prec_caco3=0.0,
    )
    r = _run(model, rj2006_state, feed, probe_common.PROBE1["days"])
    assert r.success
    oracle = json.loads((CANDIDATES_DIR / "results" / "bsm2python.json").read_text())
    ref = {p["name"]: p for p in oracle["probes"]}["P1_sludge_100d[bdf]"]["final"]
    f = r.final()
    for key, val in (("pH", f["pH"]), ("q_gas_m3_d", f["q_gas"]), ("p_ch4_bar", f["p_ch4"])):
        assert abs(val - ref[key]) / abs(ref[key]) <= 5e-4, key
    vfa = 1000.0 * sum(r.state(n)[-1] for n in ("S_va", "S_bu", "S_pro", "S_ac"))
    assert abs(vfa - ref["vfa_total_gCOD_m3"]) / ref["vfa_total_gCOD_m3"] <= 5e-4


def test_sao_inert_reduces_to_base(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    base = _base(rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, 30.0)
    model = _model(
        adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("sao",), k_m_sao=0.0
    )
    r = _run(model, rj2006_state, feed, 30.0)
    # the extra state changes the BDF step sequence, so agreement is to solver tolerance
    np.testing.assert_allclose(r.y[:29], base.y, rtol=1e-4, atol=1e-10)
    assert np.all(r.state("X_sao") == 0.0)


def test_ionic_strength_inert_reduces_to_base(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    base = _base(rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, 30.0)
    model = _model(
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        ext_config,
        ("ionic_strength",),
        davies_A=0.0,
    )
    r = _run(model, rj2006_state, feed, 30.0)
    # same dimension, same equations; only root-find rounding differs
    np.testing.assert_allclose(r.y, base.y, rtol=1e-6, atol=1e-12)
    assert np.all(r.derived["gamma1"] == 1.0)


def test_precipitation_inert_reduces_to_base(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """k_prec = 0 and no calcium: the same equations as standard ADM1.

    With the carbonate second dissociation on its own switch (off here) the speciation
    delegates to the base routine, so the only difference is the two extra states
    changing the BDF step sequence: the same 1e-4 as the SAO inert case.
    """
    base = _base(rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, 30.0)
    model = _model(
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        ext_config,
        ("precipitation",),
        k_prec_caco3=0.0,
    )
    r = _run(model, rj2006_state, feed, 30.0)
    np.testing.assert_allclose(r.y[:29], base.y, rtol=1e-4, atol=1e-10)
    assert np.all(r.state("X_caco3") == 0.0)
    assert abs(r.final()["pH"] - float(base.pH[-1])) < 1e-4


def test_carbonate_switch_is_a_small_model_change(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """The second dissociation is in the balance and the S_IC split only when switched on.

    At pH ~7.5 carbonate is ~0.1 % of bicarbonate: pH shifts by thousandths, not more.
    """
    base = _base(rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, 30.0)
    model = _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("carbonate",))
    r = _run(model, rj2006_state, feed, 30.0)
    f = r.final()
    assert 1e-5 < abs(f["pH"] - float(base.pH[-1])) < 1e-2
    assert 0.0 < f["S_co3_ion"] < 1e-2 * f["S_hco3_ion"]
    s_ic = float(r.state("S_IC")[-1])
    assert f["S_co2"] + f["S_hco3_ion"] + f["S_co3_ion"] == pytest.approx(s_ic, rel=1e-12)


def test_diagnostic_carbonate_without_the_switch(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """Calcite without `carbonate`: S_co3_ion is reported but outside the S_IC split."""
    model = _model(
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        ext_config,
        ("precipitation",),
        k_prec_caco3=0.0,
    )
    ca = {"S_ca": 0.01}
    r = _run(model, rj2006_state, feed, 5.0, y_ext=ca, u_ext=ca)
    f = r.final()
    assert f["S_co3_ion"] > 0.0
    s_ic = float(r.state("S_IC")[-1])
    assert f["S_co2"] + f["S_hco3_ion"] == pytest.approx(s_ic, rel=1e-12)
    assert f["S_co3_ion"] == pytest.approx(10.0**-10.33 * f["S_hco3_ion"] / f["S_h"], rel=1e-9)


# ------------------------------------------------------------------ SAO active


def test_sao_takes_over_under_free_ammonia_inhibition(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """With acetoclastic methanogens inhibited by NH3, SAO removes acetate.

    Feed TAN 2.8 g N/L gives ~250 mg/L free ammonia at the resulting pH: acetoclastic
    uptake is at < 10 % (BSM2 K_I_nh3 = 25 mg/L) and the reactor sours; SAO keeps ~75 %
    of its rate (K_I_nh3_sao = 700 mg/L). Run at a 60-day HRT for 300 days: SAO's
    maximum growth rate (0.08 d^-1) minus decay (0.02) leaves little margin over the
    dilution rate, so takeover is slow, as observed in practice; at the BSM2 20-day HRT
    it washes out by design (next test).
    """
    high_n = {"S_IN": 0.2}  # kmol N/m3 (2.8 g N/L)
    q = feed[1] / 3.0
    no_sao = _base(
        rj2006_state,
        feed,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        300.0,
        q=q,
        feed_over=high_n,
    )
    model = _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("sao",))
    sao = _run(model, rj2006_state, feed, 300.0, q=q, feed_over=high_n, y_ext={"X_sao": 0.05})
    assert sao.success
    assert float(no_sao.S_nh3[-1]) > 5.0 * adm1_params.kinetics.K_I_nh3  # acetoclasts inhibited
    assert sao.state("X_sao")[-1] > 3.0 * 0.05  # syntrophs grow
    assert sao.state("S_ac")[-1] < 0.5 * float(no_sao.y[6, -1])
    q_ch4_base = float(
        no_sao.q_gas[-1] * (273.15 / adm1_plant.T_op) * no_sao.p_ch4[-1] / no_sao.P_gas[-1]
    )
    assert sao.final()["q_ch4_stp"] > q_ch4_base  # methane restored via hydrogenotrophs


def test_sao_washes_out_at_short_srt(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    model = _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("sao",))
    r = _run(model, rj2006_state, feed, 60.0, y_ext={"X_sao": 0.05})
    assert r.state("X_sao")[-1] < 0.05


def test_sao_ammonia_inhibition_is_separate_and_weaker(
    adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """At S_nh3 = K_I_nh3 the acetoclastic rate is halved; SAO keeps > 50 % of its rate."""
    model = _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("sao",))
    kin = adm1_params.kinetics
    assert model.ext_params["K_I_nh3_sao"] > kin.K_I_nh3
    y = dict.fromkeys(model.state_names, 0.0)
    y.update({"S_ac": 1.0, "X_sao": 1.0, "S_IN": 0.1, "S_h2": 0.0})
    sp0 = ExtendedSpeciation(*([1e-7, 7.0] + [0.0] * 9 + [0.0, 1.0, 1.0]))
    eq = equilibria(model.base.k, model.options, 1.0, 1.0)
    rate = EXTENSION_RATES["uptake_acetate_sao"]

    def at(s_nh3: float) -> float:
        ctx = RateContext(y, 1e-7, sp0._replace(S_nh3=s_nh3), kin, model.ext_params, eq)
        return rate(ctx)

    ratio = at(kin.K_I_nh3) / at(0.0)
    k_i_sao = model.ext_params["K_I_nh3_sao"]
    assert ratio == pytest.approx(inhibition_noncompetitive(kin.K_I_nh3, k_i_sao))
    assert 0.5 < ratio < 1.0
    assert at(10.0 * kin.K_I_nh3) < at(kin.K_I_nh3)  # still inhibited, just less


# ------------------------------------------------------- ionic strength active


def test_davies_gamma_limits():
    assert davies_gamma(0.0, 1, 0.5085, 0.3) == 1.0
    g1 = davies_gamma(0.1, 1, 0.5085, 0.3)
    g2 = davies_gamma(0.1, 2, 0.5085, 0.3)
    assert 0.7 < g1 < 1.0
    assert g2 == pytest.approx(g1**4, rel=1e-12)


def test_debye_huckel_A_temperature_dependence(
    adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """A(T) from the permittivity and density of water; the config value is the 25 C one."""
    a25 = debye_huckel_A(298.15)
    assert a25 == pytest.approx(0.5085, rel=1e-2)  # tabulated 0.509-0.512
    assert debye_huckel_A(308.15) / a25 == pytest.approx(1.017, abs=3e-3)
    assert debye_huckel_A(328.15) / a25 == pytest.approx(1.056, abs=5e-3)
    temps = np.arange(273.15, 373.15, 5.0)
    assert np.all(np.diff([debye_huckel_A(t) for t in temps]) > 0.0)
    assert davies_A_at(0.5085, 298.15) == pytest.approx(0.5085, rel=1e-12)
    model = _model(
        adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("ionic_strength",)
    )
    assert model.options.davies_A == pytest.approx(davies_A_at(0.5085, adm1_plant.T_op))
    assert model.options.davies_A > 0.5085  # T_op = 35 C


def test_ionic_strength_shifts_ph_and_free_ammonia(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    base = _base(rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, 30.0)
    model = _model(
        adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("ionic_strength",)
    )
    r = _run(model, rj2006_state, feed, 30.0)
    f = r.final()
    assert 0.0 < f["ionic_strength"] < 0.5
    assert 1e-3 < abs(f["pH"] - float(base.pH[-1])) < 0.5
    assert f["S_nh3"] != pytest.approx(float(base.S_nh3[-1]), rel=1e-3)


# -------------------------------------------------------- precipitation active


def test_precipitation_sinks_inorganic_carbon(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    ca = {"S_ca": 0.02}  # kmol/m3 (0.8 g/L) in reactor and feed
    active = _model(
        adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ("precipitation",)
    )
    inert = _model(
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        ext_config,
        ("precipitation",),
        k_prec_caco3=0.0,
    )
    r = _run(active, rj2006_state, feed, 40.0, y_ext=ca, u_ext=ca)
    ref = _run(inert, rj2006_state, feed, 40.0, y_ext=ca, u_ext=ca)
    assert r.success and ref.success
    assert r.state("X_caco3")[-1] > 0.0
    assert r.state("S_ca")[-1] < ref.state("S_ca")[-1]
    assert r.final()["S_hco3_ion"] < ref.final()["S_hco3_ion"]
    assert r.final()["pH"] < ref.final()["pH"]


def test_precipitation_leaves_the_charge_balance_closed(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """The -2 matrix residual is an artefact: after speciation the solution is neutral.

    With `carbonate` on, the speciated charge (cations - anions, including 2 Ca2+ and
    2 CO3 2-) is zero at every output time while calcite is forming.
    """
    ca = {"S_ca": 0.02}
    both = ("carbonate", "precipitation")
    model = _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, both)
    r = _run(model, rj2006_state, feed, 20.0, y_ext=ca, u_ext=ca)
    assert r.state("X_caco3")[-1] > 0.0
    d = r.derived
    cod = {"S_va": 208.0, "S_bu": 160.0, "S_pro": 112.0, "S_ac": 64.0}
    vfa_charge = sum(d[f"{n}_ion"] / c for n, c in cod.items())
    charge = (
        r.state("S_cat")
        + 2.0 * r.state("S_ca")
        + d["S_nh4_ion"]
        + d["S_h"]
        - d["S_hco3_ion"]
        - 2.0 * d["S_co3_ion"]
        - vfa_charge
        - r.state("S_an")
        - model.base.k.K_w / d["S_h"]
    )
    assert np.max(np.abs(charge)) < 1e-9


# ---------------------------------------------------------------- all together


def test_all_extensions_integrate_and_stay_finite(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    model = _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ALL)
    r = _run(
        model, rj2006_state, feed, 20.0, y_ext={"X_sao": 0.01, "S_ca": 0.01}, u_ext={"S_ca": 0.01}
    )
    assert r.success
    assert np.all(np.isfinite(r.y))
    assert r.y.min() > -1e-9
    assert model.n_states == 29 + 3


def test_extended_run_is_deterministic(
    rj2006_state, feed, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    model = _model(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, ALL)
    a = _run(model, rj2006_state, feed, 5.0, y_ext={"X_sao": 0.01, "S_ca": 0.01})
    b = _run(model, rj2006_state, feed, 5.0, y_ext={"X_sao": 0.01, "S_ca": 0.01})
    assert np.array_equal(a.y, b.y)
