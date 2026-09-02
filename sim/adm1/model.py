"""Standard ADM1 as a Petersen-matrix ODE model with algebraic pH, and its integrator.

:func:`simulate` is the only entry point the tool registry should need. It is pure: it
takes an initial state, an :class:`~sim.adm1.schema.Influent`, parameters, plant geometry,
the parsed Petersen matrix and a solver configuration, and returns a typed
:class:`~sim.adm1.schema.SimulationResult`. Nothing here reads files or keeps state.

The segment-wise integration loop (:func:`integrate`) and the gas-exchange terms
(:func:`gas_exchange`) are shared with the truth-model extensions in
:mod:`sim.adm1.extensions`, which add states and matrix rows but reuse this core.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

from sim.adm1 import physchem
from sim.adm1.petersen import PetersenMatrix, compile_stoichiometry
from sim.adm1.rates import PROCESS_NAMES, process_rates
from sim.adm1.schema import (
    LIQUID_STATE_NAMES,
    N_GAS,
    N_LIQUID,
    N_STATES,
    STATE_NAMES,
    ADM1Parameters,
    Influent,
    PlantGeometry,
    SimulationResult,
    SolverConfig,
    SolverStats,
)

_IDX = {name: i for i, name in enumerate(STATE_NAMES)}
_I_VA, _I_BU, _I_PRO, _I_AC = (_IDX[n] for n in ("S_va", "S_bu", "S_pro", "S_ac"))
_I_IC, _I_IN, _I_CAT, _I_AN = (_IDX[n] for n in ("S_IC", "S_IN", "S_cat", "S_an"))

RhsFunction = Callable[[float, np.ndarray, np.ndarray, float], np.ndarray]
"""``f(t, y, u_conc, u_q) -> dy/dt`` as consumed by :func:`integrate`."""


@dataclass(frozen=True)
class _Transfer:
    liquid: int
    gas: int
    K_H: float
    cod_per_kmol: float
    free_co2: bool


@dataclass(frozen=True)
class CompiledModel:
    """Everything the right-hand side needs, evaluated once per :func:`simulate` call."""

    nu: np.ndarray
    """Stoichiometric matrix, (26, 19)."""
    params: ADM1Parameters
    plant: PlantGeometry
    solver: SolverConfig
    k: physchem.TemperatureCorrected
    transfers: tuple[_Transfer, ...]


def compile_model(
    params: ADM1Parameters,
    plant: PlantGeometry,
    matrix: PetersenMatrix,
    solver: SolverConfig,
) -> CompiledModel:
    """Evaluate the stoichiometry and temperature corrections for one parameter set."""
    if matrix.process_names != PROCESS_NAMES:
        raise ValueError(
            "process order in the Petersen matrix does not match rates.PROCESS_NAMES:\n"
            f"  matrix: {matrix.process_names}\n  rates:  {PROCESS_NAMES}"
        )
    k = physchem.temperature_corrected(params.physchem, plant.T_op)
    transfers = tuple(
        _Transfer(
            liquid=_IDX[g.liquid],
            gas=_IDX[g.gas],
            K_H=getattr(k, g.henry),
            cod_per_kmol=g.cod_per_kmol,
            free_co2=g.liquid_species == "free_co2",
        )
        for g in matrix.gas_transfer
    )
    nu = compile_stoichiometry(matrix, params)
    nu.setflags(write=False)
    return CompiledModel(
        nu=nu,
        params=params,
        plant=plant,
        solver=solver,
        k=k,
        transfers=transfers,
    )


def gas_exchange(
    yr: np.ndarray, S_co2: float, model: CompiledModel
) -> tuple[np.ndarray, np.ndarray]:
    """Liquid-gas transfer rates and headspace derivatives (BSM2 T8-T10 and gas ODEs).

    Args:
        yr: State vector as seen by the rate expressions (clipped if configured).
        S_co2: Free dissolved CO2, kmol C/m3, from the speciation.
        model: Compiled model (transfers, Henry constants, plant, gas-law parameters).

    Returns:
        ``(rho_T, dy_gas)``: the transfer rate per unit liquid volume for each transfer
        (to be subtracted from the corresponding liquid state) and the derivative of
        the three headspace states, in transfer order.
    """
    plant, pc, k = model.plant, model.params.physchem, model.k
    RT = pc.R * plant.T_op
    P_gas = k.p_h2o
    p = np.empty(len(model.transfers))
    for i, tr in enumerate(model.transfers):
        p[i] = yr[tr.gas] * RT / tr.cod_per_kmol
        P_gas += p[i]
    q_raw = max(pc.k_p * (P_gas - pc.P_atm), 0.0)

    ratio = plant.V_liq / plant.V_gas
    rho_T = np.empty(len(model.transfers))
    dy_gas = np.empty(len(model.transfers))
    for i, tr in enumerate(model.transfers):
        liquid = S_co2 if tr.free_co2 else yr[tr.liquid]
        rho_T[i] = pc.k_La * (liquid - tr.cod_per_kmol * tr.K_H * p[i])
        dy_gas[i] = -yr[tr.gas] * q_raw / plant.V_gas + rho_T[i] * ratio
    return rho_T, dy_gas


def rhs(
    t: float,
    y: np.ndarray,
    u_conc: np.ndarray,
    u_q: float,
    model: CompiledModel,
) -> np.ndarray:
    """Time derivative of the 29-state vector for a given influent.

    Args:
        t: Time, d (unused; the influent is resolved by the caller).
        y: State vector in :data:`~sim.adm1.schema.STATE_NAMES` order.
        u_conc: Influent liquid concentrations, (26,).
        u_q: Influent flow, m3/d.
        model: Compiled model.

    Returns:
        ``dy/dt`` in state units per day.
    """
    del t
    plant, k = model.plant, model.k
    yr = np.maximum(y, 0.0) if model.solver.clip_negative_states_in_rates else y

    S_h = physchem.solve_pH(
        yr[_I_VA],
        yr[_I_BU],
        yr[_I_PRO],
        yr[_I_AC],
        yr[_I_IC],
        yr[_I_IN],
        yr[_I_CAT],
        yr[_I_AN],
        k,
        model.solver.pH_solver,
    )
    sp = physchem.speciate(
        S_h, yr[_I_VA], yr[_I_BU], yr[_I_PRO], yr[_I_AC], yr[_I_IC], yr[_I_IN], k
    )
    rho = process_rates(yr, S_h, sp.S_nh3, model.params.kinetics)

    dy = np.empty(N_STATES)
    dy[:N_LIQUID] = (u_q / plant.V_liq) * (u_conc - y[:N_LIQUID]) + model.nu @ rho

    rho_T, dy_gas = gas_exchange(yr, sp.S_co2, model)
    for i, tr in enumerate(model.transfers):
        dy[tr.liquid] -= rho_T[i]
        dy[tr.gas] = dy_gas[i]
    return dy


@dataclass(frozen=True)
class _Segment:
    t0: float
    t1: float
    conc: np.ndarray
    q: float


def _hold_segments(influent: Influent, t0: float, t1: float) -> list[_Segment]:
    """Constant-influent intervals covering [t0, t1] for sample-and-hold interpolation."""
    ts, cs, qs = influent.t, influent.concentrations, influent.q
    inside = (ts > t0) & (ts < t1)
    edges = np.concatenate(([t0], ts[inside], [t1]))
    segments = []
    for a, b in itertools.pairwise(edges):
        i = max(int(np.searchsorted(ts, a, side="right")) - 1, 0)
        segments.append(_Segment(float(a), float(b), cs[i], float(qs[i])))
    return segments


class _LinearInfluent:
    """Piecewise-linear influent lookup, clamped to the end samples outside the series."""

    def __init__(self, influent: Influent) -> None:
        self.t = influent.t
        self.c = influent.concentrations
        self.q = influent.q
        n = self.t.size
        if n > 1:
            dt = np.diff(self.t)[:, None]
            self.dc = np.diff(self.c, axis=0) / dt
            self.dq = np.diff(self.q) / dt[:, 0]
        else:
            self.dc = np.zeros((0, self.c.shape[1]))
            self.dq = np.zeros(0)

    def __call__(self, t: float) -> tuple[np.ndarray, float]:
        i = int(np.searchsorted(self.t, t, side="right")) - 1
        if i < 0:
            return self.c[0], float(self.q[0])
        if i >= self.t.size - 1:
            return self.c[-1], float(self.q[-1])
        dt = t - self.t[i]
        return self.c[i] + self.dc[i] * dt, float(self.q[i] + self.dq[i] * dt)


@dataclass(frozen=True)
class Trajectory:
    """Raw output of :func:`integrate` before derived quantities are attached."""

    t: np.ndarray
    y: np.ndarray
    success: bool
    message: str
    stats: SolverStats


def integrate(
    *,
    y0: np.ndarray,
    influent: Influent,
    solver: SolverConfig,
    fun: RhsFunction,
    t_span: tuple[float, float],
    t_eval: np.ndarray | None,
) -> Trajectory:
    """Segment-wise integration of ``fun`` under an influent series.

    Sample-and-hold influent restarts the integrator at every breakpoint; linear
    interpolation uses one continuous integration with the internal step capped at the
    sample spacing. Shared by :func:`simulate` and the extended model.

    Args:
        y0: Initial state (any length; ``fun`` must accept it).
        influent: Influent series.
        solver: Solver settings.
        fun: ``f(t, y, u_conc, u_q)``.
        t_span: ``(t0, t1)`` in days.
        t_eval: Output times or ``None`` for every accepted step.

    Returns:
        The trajectory and solver statistics.
    """
    y0 = np.asarray(y0, dtype=float)
    t0, t1 = float(t_span[0]), float(t_span[1])
    if t1 <= t0:
        raise ValueError("t_span must satisfy t1 > t0")
    if t_eval is not None:
        t_eval = np.asarray(t_eval, dtype=float)
        if t_eval.ndim != 1 or np.any(np.diff(t_eval) <= 0):
            raise ValueError("t_eval must be 1-D and strictly increasing")
        if t_eval[0] < t0 or t_eval[-1] > t1:
            raise ValueError("t_eval must lie within t_span")

    if influent.interpolation == "hold":
        segments = _hold_segments(influent, t0, t1)
        lookup = None
        max_step = solver.max_step
    else:
        segments = [_Segment(t0, t1, influent.concentrations[0], float(influent.q[0]))]
        lookup = _LinearInfluent(influent)
        spacing = np.diff(influent.t)
        max_step = min(solver.max_step, float(spacing.min())) if spacing.size else solver.max_step

    ts: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    nfev = njev = nlu = n_steps = 0
    min_step, max_step_seen = np.inf, 0.0
    success, message = True, ""
    y = y0
    wall0 = time.perf_counter()
    for seg in segments:
        if lookup is None:
            conc, q = seg.conc, seg.q

            def seg_fun(
                t: float, yy: np.ndarray, _c: np.ndarray = conc, _q: float = q
            ) -> np.ndarray:
                return fun(t, yy, _c, _q)

        else:

            def seg_fun(t: float, yy: np.ndarray) -> np.ndarray:
                c, q = lookup(t)
                return fun(t, yy, c, q)

        sol = solve_ivp(
            seg_fun,
            (seg.t0, seg.t1),
            y,
            method=solver.method,
            rtol=solver.rtol,
            atol=solver.atol,
            max_step=max_step,
            dense_output=t_eval is not None,
        )
        nfev, njev, nlu = nfev + sol.nfev, njev + sol.njev, nlu + sol.nlu
        steps = np.diff(sol.t)
        if steps.size:
            n_steps += steps.size
            min_step = min(min_step, float(steps.min()))
            max_step_seen = max(max_step_seen, float(steps.max()))
        if t_eval is None:
            # drop the duplicated segment start (it is the previous segment's end)
            start = 1 if ts else 0
            ts.append(sol.t[start:])
            ys.append(sol.y[:, start:])
        else:
            last = seg is segments[-1]
            mask = (t_eval >= seg.t0) & ((t_eval <= seg.t1) if last else (t_eval < seg.t1))
            if mask.any():
                ts.append(t_eval[mask])
                ys.append(sol.sol(t_eval[mask]))
        y = sol.y[:, -1]
        message = str(sol.message)
        if not sol.success:
            success = False
            break
    wall = time.perf_counter() - wall0

    t_out = np.concatenate(ts) if ts else np.array([t0])
    y_out = np.concatenate(ys, axis=1) if ys else y0[:, None]
    stats = SolverStats(
        nfev=nfev,
        njev=njev,
        nlu=nlu,
        n_steps=n_steps,
        n_segments=len(segments),
        min_step=float(min_step) if np.isfinite(min_step) else 0.0,
        max_step=float(max_step_seen),
        wall_s=wall,
    )
    return Trajectory(t_out, y_out, success, message, stats)


def simulate(
    *,
    y0: np.ndarray,
    influent: Influent,
    params: ADM1Parameters,
    plant: PlantGeometry,
    matrix: PetersenMatrix,
    solver: SolverConfig,
    t_span: tuple[float, float],
    t_eval: np.ndarray | None = None,
) -> SimulationResult:
    """Integrate ADM1 over ``t_span`` and return the typed result.

    Args:
        y0: Initial state, (29,) in :data:`~sim.adm1.schema.STATE_NAMES` order.
        influent: Influent series (constant, sample-and-hold or linear).
        params: ADM1 parameters.
        plant: Volumes and temperature.
        matrix: Parsed Petersen matrix.
        solver: Solver settings (tolerances, method, pH root-find).
        t_span: ``(t0, t1)`` in days.
        t_eval: Output times, d, inside ``t_span``; if ``None`` every accepted step is
            returned.

    Returns:
        The trajectory, derived quantities and solver statistics. ``success`` is False
        if any segment failed; the trajectory up to the failure is still returned.
    """
    y0 = np.asarray(y0, dtype=float)
    if y0.shape != (N_STATES,):
        raise ValueError(f"y0 must have shape ({N_STATES},), got {y0.shape}")
    model = compile_model(params, plant, matrix, solver)

    def fun(t: float, y: np.ndarray, c: np.ndarray, q: float) -> np.ndarray:
        return rhs(t, y, c, q, model)

    traj = integrate(y0=y0, influent=influent, solver=solver, fun=fun, t_span=t_span, t_eval=t_eval)
    return _assemble(traj.t, traj.y, model, traj.success, traj.message, traj.stats)


def derived_quantities(y: np.ndarray, model: CompiledModel) -> dict[str, np.ndarray]:
    """pH, ion speciation and gas-phase quantities for a ``(29, n)`` trajectory."""
    pc, plant, k, cfg = model.params.physchem, model.plant, model.k, model.solver.pH_solver
    n = y.shape[1]
    yr = np.maximum(y, 0.0) if model.solver.clip_negative_states_in_rates else y
    out = {
        name: np.empty(n)
        for name in (
            "pH",
            "S_h",
            "S_va_ion",
            "S_bu_ion",
            "S_pro_ion",
            "S_ac_ion",
            "S_hco3_ion",
            "S_co2",
            "S_nh3",
            "S_nh4_ion",
            "p_h2",
            "p_ch4",
            "p_co2",
            "p_h2o",
            "P_gas",
            "q_gas",
            "q_gas_stp_dry",
        )
    }
    g_h2, g_ch4, g_co2 = (_IDX[n_] for n_ in ("S_gas_h2", "S_gas_ch4", "S_gas_co2"))
    for j in range(n):
        col = yr[:, j]
        S_h = physchem.solve_pH(
            col[_I_VA],
            col[_I_BU],
            col[_I_PRO],
            col[_I_AC],
            col[_I_IC],
            col[_I_IN],
            col[_I_CAT],
            col[_I_AN],
            k,
            cfg,
        )
        sp = physchem.speciate(
            S_h, col[_I_VA], col[_I_BU], col[_I_PRO], col[_I_AC], col[_I_IC], col[_I_IN], k
        )
        gas = physchem.gas_phase(col[g_h2], col[g_ch4], col[g_co2], plant.T_op, pc, k.p_h2o)
        out["pH"][j] = -np.log10(S_h)
        out["S_h"][j] = S_h
        for name in (
            "S_va_ion",
            "S_bu_ion",
            "S_pro_ion",
            "S_ac_ion",
            "S_hco3_ion",
            "S_co2",
            "S_nh3",
            "S_nh4_ion",
        ):
            out[name][j] = getattr(sp, name)
        for name in ("p_h2", "p_ch4", "p_co2", "p_h2o", "P_gas", "q_gas"):
            out[name][j] = getattr(gas, name)
        out["q_gas_stp_dry"][j] = physchem.q_gas_stp_dry(
            gas.q_gas, gas.P_gas, gas.p_h2o, plant.T_op
        )
    return out


def state_vector(liquid: dict[str, float], gas: dict[str, float]) -> np.ndarray:
    """Build a (29,) state vector from named liquid and gas concentrations."""
    missing = set(LIQUID_STATE_NAMES) - set(liquid)
    if missing:
        raise ValueError(f"missing liquid states: {sorted(missing)}")
    vec = [liquid[n] for n in LIQUID_STATE_NAMES] + [gas[n] for n in STATE_NAMES[N_LIQUID:]]
    assert len(vec) == N_LIQUID + N_GAS
    return np.asarray(vec, dtype=float)


def _assemble(
    t: np.ndarray,
    y: np.ndarray,
    model: CompiledModel,
    success: bool,
    message: str,
    stats: SolverStats,
) -> SimulationResult:
    return SimulationResult(
        t=t, y=y, success=success, message=message, stats=stats, **derived_quantities(y, model)
    )
