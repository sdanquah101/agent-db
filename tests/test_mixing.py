"""The parked two-zone mixing model (sim/plants/mixing.py), the Level-6 truth variant.

What is tested and why it cannot pass vacuously:

* with ``beta = phi = 0`` the model reduces *bit for bit* to ``sim.adm1.simulate`` (no
  extensions) and to ``simulate_extended`` (extensions on), and a non-ideal structure is
  shown to change the answer;
* the structure is checked against the analytical two-compartment tracer solution on
  S_cat (bypass split, exchange terms, volume bookkeeping, independent of biochemistry);
* the well-mixed limit of a fast-exchanging stagnant zone recovers the CSTR, which also
  checks that the stagnant zone's gas reaches the shared headspace (a lost stagnant
  contribution would show as a 30 % gas deficit);
* the plant contract stays an ideal CSTR: no plant config carries mixing parameters,
  the schema rejects any other model, and the mixing module is not part of the
  ``sim.plants`` API; the true geometry of a plant compiles under the structure.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.linalg import expm

import sim.plants
from sim.adm1 import (
    LIQUID_STATE_NAMES,
    Influent,
    PlantGeometry,
    compile_extended,
    extended_state,
    load_extensions,
    simulate,
    simulate_extended,
)
from sim.plants import CONFIG_DIR, load_plant_config, sample_hidden_geometry, true_geometry
from sim.plants.mixing import (
    MixingStructure,
    compile_two_zone,
    initial_state,
    simulate_two_zone,
)
from sim.plants.schema import Mixing, PlantConfig

_L = {n: i for i, n in enumerate(LIQUID_STATE_NAMES)}


@pytest.fixture(scope="module")
def ext_config():
    return load_extensions()


@pytest.fixture(scope="module")
def bsm2_influent(probe_common) -> Influent:
    return Influent.constant(np.array(probe_common.influent_vector(1.0)), probe_common.Q_IN_M3_D)


def _compile(adm1_params, plant, adm1_matrix, adm1_solver, ext_config, mixing, enabled=()):
    return compile_two_zone(
        adm1_params, plant, adm1_matrix, adm1_solver, ext_config, enabled, mixing
    )


# ------------------------------------------------------------ CSTR reduction


def test_ideal_mixing_reduces_bitwise_to_the_adm1_core(
    bsm2_influent, rj2006_state, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """With beta = phi = 0 and no extensions this is sim.adm1.simulate on BSM2."""
    model = _compile(
        adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, MixingStructure.cstr()
    )
    assert model.ideal and model.n_states == 29 and model.state_names[-1] == "S_gas_co2"
    t_eval = np.arange(0.0, 100.01, 0.5)
    r = simulate_two_zone(
        y0=initial_state(model, rj2006_state),
        influent=bsm2_influent,
        model=model,
        t_span=(0, 100),
        t_eval=t_eval,
    )
    base = simulate(
        y0=rj2006_state,
        influent=bsm2_influent,
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


def test_ideal_mixing_reduces_bitwise_to_the_extended_model(
    bsm2_influent, rj2006_state, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """Extensions on: the ideal two-zone model is simulate_extended, state for state."""
    enabled = ("sao", "ionic_strength", "carbonate", "precipitation")
    model = _compile(
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        ext_config,
        MixingStructure.cstr(),
        enabled,
    )
    ext_model = compile_extended(
        adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, enabled
    )
    assert model.n_states == ext_model.n_states == 32
    init = {"X_sao": 0.05, "S_ca": 0.01}
    u_ext = {"S_ca": 0.01}
    t_eval = np.arange(0.0, 30.01, 1.0)
    r = simulate_two_zone(
        y0=initial_state(model, rj2006_state, init),
        influent=bsm2_influent,
        model=model,
        t_span=(0, 30),
        t_eval=t_eval,
        u_ext=u_ext,
    )
    e = simulate_extended(
        y0=extended_state(ext_model, rj2006_state, init),
        influent=bsm2_influent,
        model=ext_model,
        t_span=(0, 30),
        t_eval=t_eval,
        u_ext=u_ext,
    )
    assert r.success and e.success
    assert np.array_equal(r.y, e.y)
    assert r.state("X_caco3")[-1] > 0.0  # the extensions are live in both


def test_non_ideal_mixing_changes_the_answer(
    bsm2_influent, rj2006_state, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """The reduction tests above are not vacuous: bypass and a stagnant zone move things."""
    t_eval = np.arange(0.0, 60.01, 1.0)

    def run(mixing):
        m = _compile(adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, mixing)
        return simulate_two_zone(
            y0=initial_state(m, rj2006_state),
            influent=bsm2_influent,
            model=m,
            t_span=(0, 60),
            t_eval=t_eval,
        )

    ideal = run(MixingStructure.cstr())
    bypass = run(MixingStructure(bypass_fraction=0.2, stagnant_fraction=0.0, exchange_rate=0.0))
    stagnant = run(MixingStructure(bypass_fraction=0.0, stagnant_fraction=0.3, exchange_rate=0.05))
    assert bypass.success and stagnant.success
    # bypass: 20 % of the feed leaves unreacted, so effluent X_pr rises and gas drops
    assert bypass.effluent[_L["X_pr"], -1] > 1.5 * ideal.effluent[_L["X_pr"], -1]
    assert bypass.final()["q_gas"] < 0.9 * ideal.final()["q_gas"]
    # a slowly exchanging stagnant zone starves the active zone of 30 % of the volume
    assert stagnant.y.shape[0] == 29 + 26  # active zone + stagnant liquid states
    # (the feed enters the active zone only, so the stagnant zone is substrate-poor)
    assert stagnant.state("X_ch_stag")[-1] < 0.5 * stagnant.state("X_ch")[-1]
    assert abs(stagnant.final()["q_gas"] - ideal.final()["q_gas"]) > 0.01 * ideal.final()["q_gas"]


# ------------------------------------------------------------- structure checks


def test_mixing_structure_matches_the_analytical_tracer_solution(
    probe_common, rj2006_state, adm1_params, adm1_matrix, adm1_solver, ext_config
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
    mixing = MixingStructure(bypass_fraction=beta, stagnant_fraction=phi, exchange_rate=k_ex)
    V = 3000.0
    geometry = PlantGeometry(V_liq=V, V_gas=300.0, T_op=probe_common.T_OP_K)
    model = _compile(adm1_params, geometry, adm1_matrix, adm1_solver, ext_config, mixing)
    assert model.V_main + model.V_stag == pytest.approx(V)
    u = np.array(probe_common.influent_vector(1.0))
    u_cat = 0.3
    u[_L["S_cat"]] = u_cat
    q = probe_common.Q_IN_M3_D
    influent = Influent.constant(u, q)
    t_eval = np.arange(0.0, 40.01, 2.0)
    y0 = initial_state(model, rj2006_state)
    c0 = float(y0[_L["S_cat"]])
    r = simulate_two_zone(y0=y0, influent=influent, model=model, t_span=(0, 40), t_eval=t_eval)
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
    bsm2_influent, rj2006_state, adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config
):
    """A stagnant zone exchanging at 10,000/d is part of a CSTR of the full volume.

    The zones differ by (dilution term) / k_ex, about 0.1 % on the fast-turning X_ch at
    this rate (1 % at 1,000/d), so the tolerance below is the finite-exchange residual,
    not solver error.

    Checks the two-zone biochemistry and, through q_gas, that the stagnant zone's gas
    reaches the shared headspace (a lost stagnant contribution would show as a 30 %
    gas deficit).
    """
    t_eval = np.arange(0.0, 30.01, 1.0)
    fast = _compile(
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        ext_config,
        MixingStructure(bypass_fraction=0.0, stagnant_fraction=0.3, exchange_rate=1e4),
    )
    ideal = _compile(
        adm1_params, adm1_plant, adm1_matrix, adm1_solver, ext_config, MixingStructure.cstr()
    )
    rf = simulate_two_zone(
        y0=initial_state(fast, rj2006_state),
        influent=bsm2_influent,
        model=fast,
        t_span=(0, 30),
        t_eval=t_eval,
    )
    ri = simulate_two_zone(
        y0=initial_state(ideal, rj2006_state),
        influent=bsm2_influent,
        model=ideal,
        t_span=(0, 30),
        t_eval=t_eval,
    )
    assert rf.success and ri.success
    np.testing.assert_allclose(rf.y[:29], ri.y, rtol=2e-3, atol=1e-8)
    np.testing.assert_allclose(rf.active.derived["q_gas"], ri.active.derived["q_gas"], rtol=2e-3)
    np.testing.assert_allclose(rf.active.derived["pH"], ri.active.derived["pH"], atol=2e-3)


# ---------------------------------------------------- parked, not in the contract


def test_plant_contract_stays_an_ideal_cstr():
    """No mixing parameters in PlantConfig or the YAMLs; the module is not plant API."""
    with pytest.raises(ValidationError):
        Mixing(model="two_zone")
    with pytest.raises(ValidationError):
        Mixing(model="cstr", bypass_fraction=0.1)
    assert "mixing" in PlantConfig.model_fields and set(Mixing.model_fields) == {"model", "note"}
    for path in sorted(CONFIG_DIR.glob("plant_*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert "model: cstr" in text
        for word in ("bypass", "stagnant", "exchange_rate", "two_zone"):
            assert word not in text, (path.name, word)
    assert "MixingStructure" not in sim.plants.__all__
    assert "NOT part of the plant contract" in sim.plants.mixing.__doc__
    with pytest.raises(ValidationError):
        MixingStructure(bypass_fraction=1.0, stagnant_fraction=0.0, exchange_rate=0.0)


def test_true_geometry_compiles_under_the_truth_variant(
    adm1_params, adm1_matrix, adm1_solver, ext_config
):
    cfg = load_plant_config("A")
    geometry = true_geometry(cfg, sample_hidden_geometry(cfg, seed=1))
    mixing = MixingStructure(bypass_fraction=0.05, stagnant_fraction=0.2, exchange_rate=0.5)
    model = _compile(
        adm1_params,
        geometry,
        adm1_matrix,
        adm1_solver,
        ext_config,
        mixing,
        cfg.truth_model.extensions,
    )
    assert not model.ideal
    assert model.V_main + model.V_stag == pytest.approx(geometry.V_liq)
    assert model.V_gas == cfg.geometry.V_gas
    assert model.n_states == 32 + 29 and model.state_names[-1] == "X_caco3_stag"
