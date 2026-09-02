"""The three virtual plants (sim/plants, configs/plants): declared vs. hidden configuration.

What is tested and why it cannot pass vacuously:

* every plant config loads, validates and has a usable feedstock catalogue (a broken
  catalogue entry is shown to be rejected);
* ``sample_truth`` is seed-deterministic, its active-volume error is never zero and stays
  inside the declared band, both signs occur, fractionations sum to one and zeros stay
  zero (checked over many seeds);
* the mixing structure reduces *bit for bit* to ``sim.adm1.simulate`` when ideal, and a
  non-ideal structure is shown to change the answer; the structure itself is checked
  against the analytical two-compartment tracer solution and against the well-mixed
  limit of a fast-exchanging stagnant zone (which also checks the shared headspace);
* each plant runs 100 days at its nominal feed under a sampled truth and lands inside
  the Milestone-1 plausibility gate (``scripts/adm1_candidates/common.py`` PLAUSIBLE),
  with the biogas range reused as a methane yield per kg COD fed because the BSM2 range
  assumes the BSM2 inert share; Plant B shows the high-TAN behaviour it was designed for;
* the catalogue fractionations conserve COD (sum to one) and their nitrogen is consistent
  with the ADM1 N contents (a deliberately wrong TKN is shown to fail);
* nothing under ``sim/plants`` writes files (CLAUDE.md rule 1: the run harness owns
  ``runs/<id>/truth/``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.linalg import expm

from sim.adm1 import LIQUID_STATE_NAMES, Influent, load_extensions, simulate
from sim.adm1.model import state_vector
from sim.plants import (
    CODFractionation,
    FeedstockSpec,
    MixingTruth,
    PlantDeclared,
    apply_parameter_overrides,
    cod_loading_rate,
    compile_reactor,
    constant_influent,
    extension_influent,
    implied_tkn,
    initial_state,
    load_plant_a_statistics,
    load_plant_declared,
    organic_loading_rate,
    sample_truth,
    simulate_reactor,
    tkn_consistent,
)
from sim.plants.defaults import CONFIG_DIR, PLANT_FILES
from sim.plants.schema import FRACTION_NAMES
from tests.conftest import REPO_ROOT, RJ2006_GAS_STATE

PLANTS = ("A", "B", "C")
_L = {n: i for i, n in enumerate(LIQUID_STATE_NAMES)}


@pytest.fixture(scope="module")
def ext_config():
    return load_extensions()


@pytest.fixture(scope="module")
def declared() -> dict[str, PlantDeclared]:
    return {p: load_plant_declared(p) for p in PLANTS}


def _ext_init(u_ext: dict[str, float]) -> dict[str, float]:
    return {"X_sao": 0.01, "S_ca": u_ext["S_ca"]}


def _run_plant(
    d: PlantDeclared,
    seed,
    params,
    matrix,
    solver,
    ext_config,
    rj2006_state,
    days=100.0,
    **kw: object,
):
    truth = sample_truth(d, seed)
    model = compile_reactor(d, truth, params, matrix, solver, ext_config, **kw)
    rates = d.nominal_feed.mass_rates
    fractions = {n: f.fractionation for n, f in truth.feedstocks.items()}
    influent = constant_influent(d.feedstocks, rates, fractions)
    u_ext = extension_influent(d.feedstocks, rates)
    r = simulate_reactor(
        y0=initial_state(model, rj2006_state, _ext_init(u_ext)),
        influent=influent,
        model=model,
        t_span=(0.0, days),
        t_eval=np.arange(0.0, days + 1e-9, 1.0),
        u_ext=u_ext,
    )
    return truth, model, influent, r


# ------------------------------------------------------------------ configs


@pytest.mark.parametrize("plant", PLANTS)
def test_declared_config_loads_and_is_consistent(plant, declared):
    d = declared[plant]
    assert d.id == plant
    assert PLANT_FILES[plant].is_file()
    assert d.feedstocks and all(n == s.name for n, s in d.feedstocks.items())
    assert set(d.nominal_feed.mass_rates) <= set(d.feedstocks)
    # the nominal recipe sits inside the declared envelope
    _, q = (
        constant_influent(d.feedstocks, d.nominal_feed.mass_rates).concentrations[0],
        constant_influent(d.feedstocks, d.nominal_feed.mass_rates).q[0],
    )
    assert d.envelope.q_range[0] <= q <= d.envelope.q_range[1]
    assert abs(q - d.envelope.q_nominal) < 1e-6 * q
    hrt = d.V_liq / q
    assert d.envelope.hrt_range_d[0] <= hrt <= d.envelope.hrt_range_d[1]
    olr = organic_loading_rate(d.feedstocks, d.nominal_feed.mass_rates, d.V_liq)
    assert d.envelope.olr_range[0] <= olr <= d.envelope.olr_range[1]
    assert set(d.extensions) <= {"sao", "ionic_strength", "carbonate", "precipitation"}
    assert d.temperature.regime == "mesophilic"  # proposal §6.1: all three plants
    # units in every numeric field description (CLAUDE.md rule 6)
    for model_cls in (PlantDeclared, FeedstockSpec):
        for name, field in model_cls.model_fields.items():
            if field.annotation in (float, int) or "float" in str(field.annotation):
                assert field.description, f"{model_cls.__name__}.{name} has no description"


def test_plant_a_is_reported_outside_the_factorial(declared):
    a, b, c = (declared[p] for p in PLANTS)
    assert a.anchor.anchoring == "statistics-anchored" and not a.anchor.in_factorial
    assert "2-5" in a.anchor.scenario_subset and "Tier A" in a.anchor.scenario_subset
    assert b.anchor.anchoring == "dataset-anchored" and b.anchor.in_factorial
    assert c.anchor.anchoring == "dataset-anchored" and c.anchor.in_factorial
    assert "Muscatine" in b.anchor.caveats  # the caveats are stated, not implied


def test_plant_a_statistics_file_matches_the_declared_config(declared):
    stats = load_plant_a_statistics()
    hills = stats["plants"]["afbi_hillsborough"]
    a = declared["A"]
    assert a.V_liq == hills["V_liq_m3"]
    assert a.temperature.setpoint_C == hills["T_primary_C"]
    assert list(a.envelope.olr_range) == hills["olr_kg_VS_m3_d"]
    assert a.envelope.hrt_range_d[0] == hills["hrt_d"]
    t1 = stats["feedstock_table_T2026_table_1"]
    assert a.feedstocks["cattle_slurry"].ts == pytest.approx(t1["cattle_manure"]["TS_pct_FM"] / 100)
    assert a.feedstocks["grass_silage"].vs_of_ts == pytest.approx(
        t1["grass_silage"]["VS_pct_TS"] / 100
    )


def test_every_design_parameter_is_marked(declared):
    """Every numeric leaf that the lead must review carries a `# DESIGN` marker."""
    for plant in PLANTS:
        text = PLANT_FILES[plant].read_text(encoding="utf-8")
        assert text.count("# DESIGN") >= 40, plant
        for key in ("V_liq:", "V_gas:", "setpoint_C:", "magnitude_min:", "bypass_fraction:"):
            line = next(ln for ln in text.splitlines() if ln.strip().startswith(key))
            assert "# DESIGN" in line, (plant, key)
    assert (CONFIG_DIR / "plant_a_statistics.yaml").read_text(encoding="utf-8").count("T2024") > 5


def test_config_rejects_inconsistent_declarations(declared):
    d = declared["C"]
    raw = d.model_dump()
    raw["envelope"]["hrt_range_d"] = (10.0, 20.0)  # not V_liq / q_range
    with pytest.raises(ValidationError, match="hrt_range_d"):
        PlantDeclared.model_validate(raw)
    raw = d.model_dump()
    raw["extra"] = 1
    with pytest.raises(ValidationError):
        PlantDeclared.model_validate(raw)
    with pytest.raises(ValidationError, match="sum to 1"):
        CODFractionation(f_ch=0.5, f_pr=0.5, f_li=0.1, f_xi=0.0, f_si=0.0, f_vfa=0.0)


# ------------------------------------------------------------ sample_truth


@pytest.mark.parametrize("plant", PLANTS)
def test_sample_truth_is_deterministic_and_inside_the_declared_band(plant, declared):
    d = declared[plant]
    a, b = sample_truth(d, 12345), sample_truth(d, 12345)
    assert a == b
    assert a != sample_truth(d, 12346)
    lo, hi = d.active_volume_prior.magnitude_min, d.active_volume_prior.magnitude_max
    signs = set()
    for seed in range(300):
        t = sample_truth(d, seed)
        e = t.active_volume_error
        assert e != 0.0
        assert lo <= abs(e) <= hi, (seed, e)
        assert t.V_liq_true == pytest.approx(d.V_liq * (1 + e))
        signs.add(np.sign(e))
        m = t.mixing
        assert (
            d.mixing_prior.bypass_fraction[0]
            <= m.bypass_fraction
            <= d.mixing_prior.bypass_fraction[1]
        )
        assert (
            d.mixing_prior.stagnant_fraction[0]
            <= m.stagnant_fraction
            <= d.mixing_prior.stagnant_fraction[1]
        )
        assert d.mixing_prior.exchange_rate[0] <= m.exchange_rate <= d.mixing_prior.exchange_rate[1]
        for name, ft in t.feedstocks.items():
            cat = d.feedstocks[name].fractionation
            assert sum(ft.fractionation.as_tuple()) == pytest.approx(1.0, abs=1e-9)
            for fname in FRACTION_NAMES:
                if getattr(cat, fname) == 0.0:
                    assert getattr(ft.fractionation, fname) == 0.0, (name, fname)
    assert signs == {-1.0, 1.0}


def test_sampled_fractionation_scatters_around_the_catalogue(declared):
    """The Dirichlet draws are centred on the catalogue and genuinely vary."""
    d = declared["B"]
    spec = d.feedstocks["food_waste"]
    draws = np.array(
        [sample_truth(d, s).feedstocks["food_waste"].fractionation.as_tuple() for s in range(400)]
    )
    mean = np.array(spec.fractionation.as_tuple())
    np.testing.assert_allclose(draws.mean(axis=0), mean, atol=0.02)
    kappa = spec.fractionation_concentration
    expected_sd = np.sqrt(mean * (1 - mean) / (kappa + 1))
    positive = mean > 0
    np.testing.assert_allclose(draws.std(axis=0)[positive], expected_sd[positive], rtol=0.25)
    assert np.all(draws.std(axis=0)[positive] > 0.01)


# ------------------------------------------------------------- feedstocks


@pytest.mark.parametrize("plant", PLANTS)
def test_catalogue_conserves_cod_and_nitrogen(plant, declared, adm1_params):
    d = declared[plant]
    p = apply_parameter_overrides(adm1_params, d.parameter_overrides)
    for name, spec in d.feedstocks.items():
        assert sum(spec.fractionation.as_tuple()) == pytest.approx(1.0, abs=1e-9), name
        assert tkn_consistent(spec, p.stoichiometry), (
            name,
            spec.tkn,
            implied_tkn(spec, p.stoichiometry),
        )
        assert spec.tan <= spec.tkn
        if spec.cod_per_m3 > 0:
            assert 0.9 < spec.cod_per_vs < 3.0, name  # between carbohydrate and lipid
    # the check is not vacuous: a wrong TKN fails it
    spec = d.feedstocks[next(n for n, s in d.feedstocks.items() if s.tkn > 0)]
    wrong = spec.model_copy(update={"tkn": spec.tkn * 2.0})
    assert not tkn_consistent(wrong, p.stoichiometry)


def test_mixed_influent_is_flow_weighted_and_cod_consistent(declared):
    d = declared["C"]
    rates = d.nominal_feed.mass_rates
    inf = constant_influent(d.feedstocks, rates)
    c = inf.concentrations[0]
    cod_states = ("X_ch", "X_pr", "X_li", "X_I", "S_I", "S_ac")
    total_cod = sum(c[_L[n]] for n in cod_states) * inf.q[0]
    assert total_cod == pytest.approx(cod_loading_rate(d.feedstocks, rates, d.V_liq) * d.V_liq)
    assert inf.q[0] == pytest.approx(sum(m / d.feedstocks[n].density for n, m in rates.items()))
    assert c[_L["S_IN"]] == pytest.approx(0.01)  # both sludges carry the BSM2 S_IN
    with pytest.raises(ValueError, match="unknown feeds"):
        constant_influent(d.feedstocks, {"cake": 1.0})


def test_parameter_overrides_are_applied_and_validated(adm1_params, declared):
    p = apply_parameter_overrides(adm1_params, declared["A"].parameter_overrides)
    assert p.stoichiometry.N_I == 0.001 and adm1_params.stoichiometry.N_I != 0.001
    assert p.kinetics == adm1_params.kinetics
    with pytest.raises(ValueError, match=r"group\.name"):
        apply_parameter_overrides(adm1_params, {"N_I": 0.001})
    with pytest.raises(ValueError, match="unknown parameter"):
        apply_parameter_overrides(adm1_params, {"kinetics.k_magic": 1.0})


# -------------------------------------------------------------- reactor / RTD


@pytest.fixture(scope="module")
def bsm2_plant_c(declared) -> PlantDeclared:
    """Plant C without extensions or overrides: exactly the BSM2 digester."""
    return declared["C"].model_copy(update={"extensions": (), "parameter_overrides": {}})


def test_ideal_mixing_reduces_bitwise_to_the_adm1_core(
    bsm2_plant_c,
    probe_common,
    rj2006_state,
    adm1_params,
    adm1_plant,
    adm1_matrix,
    adm1_solver,
    ext_config,
):
    """With beta = phi = 0 at the declared volume this is sim.adm1.simulate on BSM2."""
    assert bsm2_plant_c.V_liq == adm1_plant.V_liq and bsm2_plant_c.T_op == adm1_plant.T_op
    truth = sample_truth(bsm2_plant_c, 7)
    model = compile_reactor(
        bsm2_plant_c,
        truth,
        adm1_params,
        adm1_matrix,
        adm1_solver,
        ext_config,
        mixing=MixingTruth.cstr(),
        V_liq=bsm2_plant_c.V_liq,
    )
    assert model.ideal and model.n_states == 29
    influent = Influent.constant(
        np.array(probe_common.influent_vector(1.0)), probe_common.Q_IN_M3_D
    )
    t_eval = np.arange(0.0, 100.01, 0.5)
    r = simulate_reactor(
        y0=initial_state(model, rj2006_state),
        influent=influent,
        model=model,
        t_span=(0, 100),
        t_eval=t_eval,
    )
    base = simulate(
        y0=rj2006_state,
        influent=influent,
        params=adm1_params,
        plant=adm1_plant,
        matrix=adm1_matrix,
        solver=adm1_solver,
        t_span=(0, 100),
        t_eval=t_eval,
    )
    assert r.success and base.success
    assert np.array_equal(r.y, base.y)  # bitwise
    np.testing.assert_allclose(r.active.derived["pH"], base.pH, rtol=1e-10)
    np.testing.assert_allclose(r.active.derived["q_gas"], base.q_gas, rtol=1e-10)
    np.testing.assert_array_equal(r.effluent, base.y[:26])


def test_non_ideal_mixing_changes_the_answer(
    bsm2_plant_c, probe_common, rj2006_state, adm1_params, adm1_matrix, adm1_solver, ext_config
):
    """The reduction test above is not vacuous: bypass and a stagnant zone move things."""
    truth = sample_truth(bsm2_plant_c, 7)
    influent = Influent.constant(
        np.array(probe_common.influent_vector(1.0)), probe_common.Q_IN_M3_D
    )
    t_eval = np.arange(0.0, 60.01, 1.0)

    def run(mixing):
        m = compile_reactor(
            bsm2_plant_c,
            truth,
            adm1_params,
            adm1_matrix,
            adm1_solver,
            ext_config,
            mixing=mixing,
            V_liq=3400.0,
        )
        return simulate_reactor(
            y0=initial_state(m, rj2006_state),
            influent=influent,
            model=m,
            t_span=(0, 60),
            t_eval=t_eval,
        )

    ideal = run(MixingTruth.cstr())
    bypass = run(MixingTruth(bypass_fraction=0.2, stagnant_fraction=0.0, exchange_rate=0.0))
    stagnant = run(MixingTruth(bypass_fraction=0.0, stagnant_fraction=0.3, exchange_rate=0.05))
    assert bypass.success and stagnant.success
    # bypass: 20 % of the feed leaves unreacted, so effluent X_pr rises and gas drops
    assert bypass.effluent[_L["X_pr"], -1] > 1.5 * ideal.effluent[_L["X_pr"], -1]
    assert bypass.final()["q_gas"] < 0.9 * ideal.final()["q_gas"]
    # a slowly exchanging stagnant zone starves the active zone of 30 % of the volume
    assert stagnant.y.shape[0] == 29 + 26  # active zone + stagnant liquid states
    # (the feed enters the active zone only, so the stagnant zone is substrate-poor)
    assert stagnant.state("X_ch_stag")[-1] < 0.5 * stagnant.state("X_ch")[-1]
    assert abs(stagnant.final()["q_gas"] - ideal.final()["q_gas"]) > 0.01 * ideal.final()["q_gas"]


def test_mixing_structure_matches_the_analytical_tracer_solution(
    bsm2_plant_c, probe_common, rj2006_state, adm1_params, adm1_matrix, adm1_solver, ext_config
):
    """S_cat is a conservative tracer (no reaction, no gas transfer).

    A step in influent S_cat must follow the two-compartment linear system
    ``d/dt [c_main, c_stag] = A [c_main, c_stag] + b`` with
    ``A = [[-(1-beta) Q / V_main - k_ex V_stag / V_main, k_ex V_stag / V_main],
    [k_ex, -k_ex]]`` and the effluent ``(1 - beta) c_main + beta u``. This pins the
    bypass split, the exchange terms and the volume bookkeeping independently of the
    biochemistry.
    """
    beta, phi, k_ex = 0.1, 0.25, 0.3
    truth = sample_truth(bsm2_plant_c, 11)
    mixing = MixingTruth(bypass_fraction=beta, stagnant_fraction=phi, exchange_rate=k_ex)
    V = 3000.0
    model = compile_reactor(
        bsm2_plant_c,
        truth,
        adm1_params,
        adm1_matrix,
        adm1_solver,
        ext_config,
        mixing=mixing,
        V_liq=V,
    )
    u = np.array(probe_common.influent_vector(1.0))
    u_cat = 0.3
    u[_L["S_cat"]] = u_cat
    q = probe_common.Q_IN_M3_D
    influent = Influent.constant(u, q)
    t_eval = np.arange(0.0, 40.01, 2.0)
    y0 = initial_state(model, rj2006_state)
    c0 = float(y0[_L["S_cat"]])
    r = simulate_reactor(y0=y0, influent=influent, model=model, t_span=(0, 40), t_eval=t_eval)
    assert r.success
    V_stag, V_main = V * phi, V * (1 - phi)
    A = np.array(
        [
            [-(1 - beta) * q / V_main - k_ex * V_stag / V_main, k_ex * V_stag / V_main],
            [k_ex, -k_ex],
        ]
    )
    b = np.array([(1 - beta) * q / V_main * u_cat, 0.0])
    x_inf = -np.linalg.solve(A, b)
    x0 = np.array([c0, c0])
    expected = np.array([x_inf + expm(A * t) @ (x0 - x_inf) for t in t_eval])
    np.testing.assert_allclose(r.state("S_cat"), expected[:, 0], rtol=2e-5)
    np.testing.assert_allclose(r.state("S_cat_stag"), expected[:, 1], rtol=2e-5)
    np.testing.assert_allclose(
        r.effluent[_L["S_cat"]], (1 - beta) * expected[:, 0] + beta * u_cat, rtol=2e-5
    )
    # and the tracer really moved (not a trivially constant solution)
    assert expected[-1, 0] > 2.0 * c0 and expected[-1, 1] < expected[-1, 0]


def test_fast_exchange_recovers_the_well_mixed_reactor(
    bsm2_plant_c, probe_common, rj2006_state, adm1_params, adm1_matrix, adm1_solver, ext_config
):
    """A stagnant zone exchanging at 10,000/d is part of a CSTR of the full volume.

    The zones differ by (dilution term) / k_ex, about 0.1 % on the fast-turning X_ch at
    this rate (1 % at 1,000/d), so the tolerance below is the finite-exchange residual,
    not solver error.

    Checks the two-zone biochemistry and, through q_gas, that the stagnant zone's gas
    reaches the shared headspace (a lost stagnant contribution would show as a 30 %
    gas deficit).
    """
    truth = sample_truth(bsm2_plant_c, 5)
    influent = Influent.constant(
        np.array(probe_common.influent_vector(1.0)), probe_common.Q_IN_M3_D
    )
    t_eval = np.arange(0.0, 30.01, 1.0)
    fast = compile_reactor(
        bsm2_plant_c,
        truth,
        adm1_params,
        adm1_matrix,
        adm1_solver,
        ext_config,
        mixing=MixingTruth(bypass_fraction=0.0, stagnant_fraction=0.3, exchange_rate=1e4),
        V_liq=3400.0,
    )
    ideal = compile_reactor(
        bsm2_plant_c,
        truth,
        adm1_params,
        adm1_matrix,
        adm1_solver,
        ext_config,
        mixing=MixingTruth.cstr(),
        V_liq=3400.0,
    )
    rf = simulate_reactor(
        y0=initial_state(fast, rj2006_state),
        influent=influent,
        model=fast,
        t_span=(0, 30),
        t_eval=t_eval,
    )
    ri = simulate_reactor(
        y0=initial_state(ideal, rj2006_state),
        influent=influent,
        model=ideal,
        t_span=(0, 30),
        t_eval=t_eval,
    )
    assert rf.success and ri.success
    np.testing.assert_allclose(rf.y[:29], ri.y, rtol=2e-3, atol=1e-8)
    np.testing.assert_allclose(rf.active.derived["q_gas"], ri.active.derived["q_gas"], rtol=2e-3)
    np.testing.assert_allclose(rf.active.derived["pH"], ri.active.derived["pH"], atol=2e-3)


# --------------------------------------------------------- 100-day plausibility


def _methane_yield_gate(probe_common) -> tuple[float, float]:
    """The BSM2 biogas gate as a methane yield per kg COD fed, m3 CH4 (dry STP)/kg COD.

    The lower bound is PLAUSIBLE q_gas[0] at the lower CH4 fraction, converted to STP
    and divided by the BSM2 feed COD load; the upper bound is the COD-balance limit
    (0.35 m3 CH4/kg COD). The BSM2 m3/d range itself cannot be transplanted: it assumes
    the BSM2 feed's 45 % inert share.
    """
    lo_q = probe_common.PLAUSIBLE["q_gas_m3_d"][0]
    ch4_lo = probe_common.PLAUSIBLE["ch4_fraction_dry"][0]
    g = probe_common.RJ2006_GAS
    q_dry_stp = lo_q * (273.15 / probe_common.T_OP_K) * (1.0 - g["p_h2o_bar"] / g["P_gas_bar"])
    no_cod = {"S_IC", "S_IN", "S_cat", "S_an"}
    load = sum(v for k, v in probe_common.INFLUENT_RJ2006.items() if k not in no_cod)
    load *= probe_common.Q_IN_M3_D
    return q_dry_stp * ch4_lo / load, 0.35


@pytest.fixture(scope="module")
def plant_runs(declared, adm1_params, adm1_matrix, adm1_solver, ext_config, rj2006_state):
    return {
        p: _run_plant(
            declared[p], 2026, adm1_params, adm1_matrix, adm1_solver, ext_config, rj2006_state
        )
        for p in PLANTS
    }


@pytest.mark.parametrize("plant", PLANTS)
def test_plant_runs_100_days_inside_the_plausibility_gate(
    plant, plant_runs, probe_common, declared
):
    truth, model, _influent, r = plant_runs[plant]
    d = declared[plant]
    assert r.success and np.all(np.isfinite(r.y)) and r.y.min() > -1e-9
    assert not model.ideal and model.V_main + model.V_stag == pytest.approx(truth.V_liq_true)
    f = r.final()
    gate = probe_common.PLAUSIBLE
    assert gate["pH"][0] <= f["pH"] <= gate["pH"][1], f["pH"]
    ch4_dry = f["p_ch4"] / (f["P_gas"] - f["p_h2o"])
    assert gate["ch4_fraction_dry"][0] <= ch4_dry <= gate["ch4_fraction_dry"][1], ch4_dry
    vfa = 1000.0 * sum(r.active.state(n)[-1] for n in ("S_va", "S_bu", "S_pro", "S_ac"))
    assert gate["vfa_total_gCOD_m3"][0] <= vfa <= gate["vfa_total_gCOD_m3"][1], vfa
    cod_load = cod_loading_rate(d.feedstocks, d.nominal_feed.mass_rates, d.V_liq) * d.V_liq
    y_lo, y_hi = _methane_yield_gate(probe_common)
    yield_ch4 = f["q_ch4_stp"] / cod_load
    assert y_lo < yield_ch4 < y_hi, (yield_ch4, y_lo, y_hi)
    # near steady state at day 100: gas within 5 % of the day-80 value
    q = r.active.derived["q_gas"]
    assert abs(q[-1] - q[-21]) < 0.05 * q[-1]
    # the extensions are live in the truth, not switched off
    assert r.state("X_caco3")[-1] > 0.0 and f["ionic_strength"] > 0.05


def test_plant_b_shows_high_tan_and_visible_ammonia_inhibition(plant_runs, adm1_params):
    """Plant B is the high-nitrogen plant.

    TAN >= 1.5 g N/L with free ammonia at the acetoclastic inhibition constant, while
    the sludge control (Plant C) stays below it.
    """
    _, _, _, rb = plant_runs["B"]
    _, _, _, rc = plant_runs["C"]
    tan_b, tan_c = rb.active.state("S_IN")[-1], rc.active.state("S_IN")[-1]
    assert tan_b >= 1.5 / 14.0  # kmol N/m3
    assert tan_b > 1.2 * tan_c
    k_i = adm1_params.kinetics.K_I_nh3
    nh3_b, nh3_c = rb.final()["S_nh3"], rc.final()["S_nh3"]
    assert nh3_b >= 0.8 * k_i  # acetoclastic uptake at <= 55 % of its uninhibited rate
    assert nh3_b > nh3_c
    # yet not soured: the gate test above holds, and acetate is being turned over
    assert rb.active.state("S_ac")[-1] < 0.2


def test_plant_a_and_c_loadings_match_their_anchors(declared):
    a, c = declared["A"], declared["C"]
    olr_a = organic_loading_rate(a.feedstocks, a.nominal_feed.mass_rates, a.V_liq)
    assert 1.4 <= olr_a <= 1.6  # Tisocco et al. 2024 data set A: 1.4 kg VS/m3/d
    assert constant_influent(c.feedstocks, c.nominal_feed.mass_rates).q[0] == pytest.approx(170.0)


# ------------------------------------------------------------ rule 1 hygiene


_WRITERS = {"open", "write_text", "write_bytes", "to_csv", "dump", "safe_dump", "savetxt", "save"}


def _write_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
            if name in _WRITERS:
                found.append(f"{path.name}:{node.lineno}: {name}")
    return found


def test_plants_package_never_writes_files(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("from pathlib import Path\nPath('x').write_text('truth')\nopen('y', 'w')\n")
    assert len(_write_calls(bad)) == 2  # the checker sees both patterns
    modules = sorted((REPO_ROOT / "sim" / "plants").glob("*.py"))
    assert modules
    calls = [c for m in modules for c in _write_calls(m)]
    assert not calls, calls


def test_rj2006_gas_state_fixture_is_the_one_used_here(rj2006_state):
    assert rj2006_state.shape == (29,)
    assert rj2006_state[27] == RJ2006_GAS_STATE["S_gas_ch4"]
    assert np.array_equal(
        rj2006_state,
        state_vector(
            dict(zip(LIQUID_STATE_NAMES, rj2006_state[:26], strict=True)), RJ2006_GAS_STATE
        ),
    )
