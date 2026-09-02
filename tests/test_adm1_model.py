"""The simulate() API: shapes, influent handling, purity and determinism."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from sim.adm1 import N_STATES, STATE_NAMES, Influent, compile_model, rhs, simulate
from sim.adm1.model import _hold_segments


@pytest.fixture(scope="module")
def constant_influent(probe_common):
    return Influent.constant(np.array(probe_common.influent_vector(1.0)), probe_common.Q_IN_M3_D)


def _run(rj2006_state, influent, adm1_params, adm1_plant, adm1_matrix, adm1_solver, **kw: object):
    return simulate(
        y0=rj2006_state,
        influent=influent,
        params=adm1_params,
        plant=adm1_plant,
        matrix=adm1_matrix,
        solver=adm1_solver,
        **kw,
    )


def test_result_shapes_and_units(
    rj2006_state, constant_influent, adm1_params, adm1_plant, adm1_matrix, adm1_solver
):
    t_eval = np.linspace(0, 2, 5)
    r = _run(
        rj2006_state,
        constant_influent,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        t_span=(0, 2),
        t_eval=t_eval,
    )
    assert r.success
    assert r.y.shape == (N_STATES, 5) and np.array_equal(r.t, t_eval)
    assert r.pH.shape == (5,) and np.all((r.pH > 6) & (r.pH < 8.5))
    assert np.all(r.q_gas > 0) and np.all(r.q_gas_stp_dry < r.q_gas)
    assert set(r.final_state()) == set(STATE_NAMES)
    assert r.stats.n_segments == 1 and r.stats.nfev > 0


def test_without_t_eval_returns_accepted_steps(
    rj2006_state, constant_influent, adm1_params, adm1_plant, adm1_matrix, adm1_solver
):
    r = _run(
        rj2006_state,
        constant_influent,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        t_span=(0, 1),
    )
    assert r.t[0] == 0.0 and r.t[-1] == 1.0 and np.all(np.diff(r.t) > 0)
    assert r.t.size == r.stats.n_steps + 1


def test_deterministic_and_pure(
    rj2006_state, constant_influent, adm1_params, adm1_plant, adm1_matrix, adm1_solver
):
    y0 = rj2006_state.copy()
    a = _run(
        y0,
        constant_influent,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        t_span=(0, 3),
        t_eval=np.array([3.0]),
    )
    b = _run(
        y0,
        constant_influent,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        t_span=(0, 3),
        t_eval=np.array([3.0]),
    )
    assert np.array_equal(a.y, b.y) and np.array_equal(a.pH, b.pH)
    assert np.array_equal(y0, rj2006_state)  # y0 untouched
    model = compile_model(adm1_params, adm1_plant, adm1_matrix, adm1_solver)
    y = rj2006_state.copy()
    u = constant_influent.concentrations[0].copy()
    rhs(0.0, y, u, 170.0, model)
    assert np.array_equal(y, rj2006_state) and np.array_equal(
        u, constant_influent.concentrations[0]
    )


def test_hold_segments_cover_span_and_hold_back_first_sample():
    t = np.array([1.0, 2.0, 3.0])
    conc = np.tile(np.arange(26.0), (3, 1)) + np.array([[0.0], [100.0], [200.0]])
    inf = Influent(t=t, concentrations=conc, q=np.array([1.0, 2.0, 3.0]))
    segs = _hold_segments(inf, 0.0, 2.5)
    assert [(s.t0, s.t1, s.q) for s in segs] == [(0.0, 1.0, 1.0), (1.0, 2.0, 1.0), (2.0, 2.5, 2.0)]
    # the sample taken at t = 2 (row 1) is held over [2, 2.5]
    assert segs[0].conc[0] == 0.0 and segs[2].conc[0] == 100.0
    # breakpoints exactly on the span edges do not create empty segments
    assert len(_hold_segments(inf, 1.0, 3.0)) == 2


def test_step_change_is_applied_at_breakpoint(
    rj2006_state, probe_common, adm1_params, adm1_plant, adm1_matrix, adm1_solver
):
    u = np.array(probe_common.influent_vector(1.0))
    inf = Influent(
        t=np.array([0.0, 1.0]), concentrations=np.vstack([u, 3 * u]), q=np.array([170.0, 170.0])
    )
    r = _run(
        rj2006_state,
        inf,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        t_span=(0, 2),
        t_eval=np.array([0.5, 1.0, 1.5, 2.0]),
    )
    assert r.success and r.stats.n_segments == 2
    x_xc = r.y[STATE_NAMES.index("X_xc")]
    assert x_xc[3] > x_xc[1] > 0  # composites accumulate after the 3x step


def test_linear_mode_matches_hold_for_a_constant_series(
    rj2006_state, probe_common, adm1_params, adm1_plant, adm1_matrix, adm1_solver
):
    u = np.array(probe_common.influent_vector(1.0))
    hold = Influent(
        t=np.array([0.0, 1.0, 2.0]), concentrations=np.vstack([u, u, u]), q=np.array([170.0] * 3)
    )
    lin = hold.model_copy(update={"interpolation": "linear"})
    a = _run(
        rj2006_state,
        hold,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        t_span=(0, 2),
        t_eval=np.array([2.0]),
    )
    b = _run(
        rj2006_state,
        lin,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        t_span=(0, 2),
        t_eval=np.array([2.0]),
    )
    assert a.stats.n_segments == 2 and b.stats.n_segments == 1  # breakpoint at t = 1 only
    np.testing.assert_allclose(a.y, b.y, rtol=1e-5)


def test_radau_cross_check(
    rj2006_state, constant_influent, adm1_params, adm1_plant, adm1_matrix, adm1_solver
):
    radau = adm1_solver.model_copy(update={"method": "Radau"})
    a = _run(
        rj2006_state,
        constant_influent,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        t_span=(0, 20),
        t_eval=np.array([20.0]),
    )
    b = _run(
        rj2006_state,
        constant_influent,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        radau,
        t_span=(0, 20),
        t_eval=np.array([20.0]),
    )
    assert a.success and b.success
    np.testing.assert_allclose(a.y[:, -1], b.y[:, -1], rtol=1e-4)


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"t_span": (1.0, 1.0)}, "t1 > t0"),
        ({"t_span": (0.0, 1.0), "t_eval": np.array([0.0, 2.0])}, "within t_span"),
        ({"t_span": (0.0, 1.0), "t_eval": np.array([0.5, 0.2])}, "strictly increasing"),
    ],
)
def test_bad_arguments(
    rj2006_state, constant_influent, adm1_params, adm1_plant, adm1_matrix, adm1_solver, kw, match
):
    with pytest.raises(ValueError, match=match):
        _run(
            rj2006_state, constant_influent, adm1_params, adm1_plant, adm1_matrix, adm1_solver, **kw
        )


def test_wrong_state_length(constant_influent, adm1_params, adm1_plant, adm1_matrix, adm1_solver):
    with pytest.raises(ValueError, match="shape"):
        _run(
            np.ones(26),
            constant_influent,
            adm1_params,
            adm1_plant,
            adm1_matrix,
            adm1_solver,
            t_span=(0, 1),
        )


def test_influent_validation():
    with pytest.raises(ValidationError, match="strictly increasing"):
        Influent(t=np.array([0.0, 0.0]), concentrations=np.zeros((2, 26)), q=np.ones(2))
    with pytest.raises(ValidationError, match="shape"):
        Influent(t=np.array([0.0]), concentrations=np.zeros((1, 25)), q=np.ones(1))
    with pytest.raises(ValidationError, match="non-negative"):
        Influent(t=np.array([0.0]), concentrations=np.zeros((1, 26)), q=np.array([-1.0]))


def test_parameter_files_reject_typos(adm1_params):
    raw = adm1_params.model_dump()
    raw["kinetics"]["k_m_sugar"] = 1.0
    with pytest.raises(ValidationError, match="extra"):
        type(adm1_params).model_validate(raw)
    raw = adm1_params.model_dump()
    raw["stoichiometry"]["f_ac_su"] = 0.5
    with pytest.raises(ValidationError, match="sum to 1"):
        type(adm1_params).model_validate(raw)
