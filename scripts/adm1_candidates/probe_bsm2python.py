"""Probe bsm2-python (PyPI ``bsm2-python``), the BSM2 plant model incl. ADM1.

The digester is ``bsm2_python.bsm2.adm1_bsm2``: a numba-jitted ODE right-hand side over
the 42-state BSM2 vector (26 ADM1 states, 6 ion states, 3 gas states, Q, T, 5 dummies)
integrated with ``scipy.integrate.odeint`` (LSODA) one plant time step at a time. Two
modes are probed:

* ``shipped``: odeint per 15-min step, as the package does (its default step is 1 min).
* ``bdf``: one ``solve_ivp(method="BDF")`` call over the whole horizon using the same
  right-hand side, i.e. what a tool wrapper would do.
"""

from __future__ import annotations

import traceback
from importlib.metadata import version

import numpy as np
import pandas as pd
import scipy
from bsm2_python.bsm2.adm1_bsm2 import adm1equations
from bsm2_python.bsm2.init import adm1init_bsm2 as adm1init
from common import (
    PROBE1,
    PROBE2,
    Q_IN_M3_D,
    T_OP_K,
    CandidateResult,
    ProbeResult,
    Stopwatch,
    derived,
    gate,
    influent_vector,
)
from scipy.integrate import odeint, solve_ivp

DT_D = 1.0 / 96.0
PAR = adm1init.DIGESTERPAR
DIM = adm1init.DIM_D
#: The 35 model states of the 42-vector (26 ADM1 + 6 ion + 3 gas), recorded at the end
#: of each probe under ``stats.final_state`` so that a re-implementation can be
#: ring-tested state by state.
STATE35 = [
    "S_su", "S_aa", "S_fa", "S_va", "S_bu", "S_pro", "S_ac", "S_h2", "S_ch4", "S_IC",
    "S_IN", "S_I", "X_xc", "X_ch", "X_pr", "X_li", "X_su", "X_aa", "X_fa", "X_c4",
    "X_pro", "X_ac", "X_h2", "X_I", "S_cat", "S_an", "S_va_ion", "S_bu_ion", "S_pro_ion",
    "S_ac_ion", "S_hco3_ion", "S_nh3", "S_gas_h2", "S_gas_ch4", "S_gas_co2",
]  # fmt: skip


def influent_state(factor: float) -> np.ndarray:
    """42-vector influent: R&J concentrations x factor, Q and T in slots 35/36."""
    yd_in = np.zeros(42)
    yd_in[:26] = influent_vector(factor)
    yd_in[35] = Q_IN_M3_D
    yd_in[36] = T_OP_K - 273.15
    return yd_in


def initial_state() -> np.ndarray:
    """The package's own R&J steady-state initial vector with Q set to 170 m3/d."""
    y0 = adm1init.DIGESTERINIT.astype(float).copy()
    y0[35] = Q_IN_M3_D
    return y0


def summarise(t: float, yd: np.ndarray) -> dict[str, float]:
    """Post-process one 42-state vector exactly as ``ADM1Reactor.output`` does."""
    r, t_base, pk_w_base, p_atm, k_h_h2o_base, k_p = (
        PAR[77],
        PAR[78],
        PAR[80],
        PAR[93],
        PAR[95],
        PAR[99],
    )
    factor = (1.0 / t_base - 1.0 / T_OP_K) / (100.0 * r)
    k_w = 10 ** (-pk_w_base) * np.exp(55900.0 * factor)
    p_h2o = k_h_h2o_base * np.exp(5290.0 * (1.0 / t_base - 1.0 / T_OP_K))
    p_h2 = yd[32] * r * T_OP_K / 16.0
    p_ch4 = yd[33] * r * T_OP_K / 64.0
    p_co2 = yd[34] * r * T_OP_K
    P_gas = p_h2 + p_ch4 + p_co2 + p_h2o
    q_gas = max(k_p * (P_gas - p_atm), 0.0) * P_gas / p_atm
    phi = (
        yd[24]
        + (yd[10] - yd[31])
        - yd[30]
        - yd[29] / 64.0
        - yd[28] / 112.0
        - yd[27] / 160.0
        - yd[26] / 208.0
        - yd[25]
    )
    s_h = -phi * 0.5 + 0.5 * np.sqrt(phi**2 + 4.0 * k_w)
    return {
        "t": t,
        **derived(
            pH=-np.log10(s_h),
            p_h2=p_h2,
            p_ch4=p_ch4,
            p_co2=p_co2,
            p_h2o=p_h2o,
            q_gas=q_gas,
            S_va=yd[3],
            S_bu=yd[4],
            S_pro=yd[5],
            S_ac=yd[6],
        ),
    }


def run_shipped(days: float, step_day: float | None, factor: float) -> dict:
    """Odeint (LSODA) one 15-min step at a time, rtol=atol=1e-6 as in the package."""
    y, yd_in = initial_state(), influent_state(1.0)
    n = round(days / DT_D)
    rows, nst, nfe, nje, hmin, stiff_steps = [], 0, 0, 0, np.inf, 0
    for k in range(n):
        t0 = k * DT_D
        if step_day is not None and abs(t0 - step_day) < 1e-9:
            yd_in = influent_state(factor)
        sol, info = odeint(
            adm1equations,
            y,
            [t0, t0 + DT_D],
            tfirst=True,
            args=(yd_in, PAR, T_OP_K, DIM),
            rtol=1e-6,
            atol=1e-6,
            full_output=True,
        )
        if info["message"] != "Integration successful.":
            raise RuntimeError(f"odeint at t={t0:.4f}: {info['message']}")
        y = sol[1]
        nst += int(info["nst"][-1])
        nfe += int(info["nfe"][-1])
        nje += int(info["nje"][-1])
        hmin = min(hmin, float(info["hu"][-1]))
        stiff_steps += int(info["mused"][-1] == 2)
        rows.append(summarise(t0 + DT_D, y))
    return {
        "df": pd.DataFrame(rows),
        "y_final": [float(v) for v in y[:35]],
        "stats": {
            "outer_steps": n,
            "nst": nst,
            "nfe": nfe,
            "nje": nje,
            "min_last_step_d": hmin,
            "outer_steps_ending_in_BDF_mode": stiff_steps,
        },
    }


def run_bdf(days: float, step_day: float | None, factor: float) -> dict:
    """One solve_ivp BDF call per constant-influent segment; rtol 1e-6, atol 1e-8."""
    y = initial_state()
    segments = (
        [(0.0, days, 1.0)] if step_day is None else [(0.0, step_day, 1.0), (step_day, days, factor)]
    )
    rows, stats = [], {"nfev": 0, "njev": 0, "nlu": 0, "steps": 0, "min_dt_d": np.inf}
    for t0, t1, f in segments:
        yd_in = influent_state(f)
        sol = solve_ivp(
            lambda t, yy, u=yd_in: adm1equations(t, yy, u, PAR, T_OP_K, DIM),
            (t0, t1),
            y,
            method="BDF",
            rtol=1e-6,
            atol=1e-8,
            t_eval=np.arange(t0 + DT_D, t1 + 1e-9, DT_D),
        )
        if not sol.success:
            raise RuntimeError(f"solve_ivp BDF: {sol.message}")
        stats["nfev"] += sol.nfev
        stats["njev"] += sol.njev
        stats["nlu"] += sol.nlu
        # t_eval hides internal steps; re-run without it only to count them is wasteful,
        # so approximate min step from the dense output is not possible: report nfev/nlu.
        y = sol.y[:, -1]
        rows.extend(summarise(tt, yy) for tt, yy in zip(sol.t, sol.y.T, strict=True))
    stats.pop("steps")
    stats.pop("min_dt_d")
    return {"df": pd.DataFrame(rows), "y_final": [float(v) for v in y[:35]], "stats": stats}


def probe(spec: dict, mode: str) -> ProbeResult:
    """Run one probe in one mode and package the outcome."""
    runner, solver, settings = {
        "shipped": (
            run_shipped,
            "scipy odeint (LSODA), one call per 15-min step",
            {"rtol": 1e-6, "atol": 1e-6, "outer_dt_d": DT_D},
        ),
        "bdf": (
            run_bdf,
            "scipy solve_ivp BDF over the whole horizon",
            {"rtol": 1e-6, "atol": 1e-8, "t_eval_dt_d": DT_D},
        ),
    }[mode]
    try:
        with Stopwatch() as sw:
            out = runner(spec["days"], spec.get("step_day"), spec.get("factor", 1.0))
    except Exception as exc:
        return ProbeResult(
            name=f"{spec['name']}[{mode}]",
            ok=False,
            wall_s=float("nan"),
            wall_s_per_sim_day=float("nan"),
            solver=solver,
            solver_settings=settings,
            error=f"{exc}\n{traceback.format_exc(limit=3)}",
        )
    df = out["df"]
    final = df.iloc[-1].drop("t").to_dict()
    return ProbeResult(
        name=f"{spec['name']}[{mode}]",
        ok=bool(np.isfinite(df.drop(columns="t")).all().all()),
        wall_s=sw.wall_s,
        wall_s_per_sim_day=sw.wall_s / spec["days"],
        solver=solver,
        solver_settings=settings,
        stats={**out["stats"], "final_state": dict(zip(STATE35, out["y_final"], strict=True))},
        final=final,
        extremes={
            "pH_min": float(df.pH.min()),
            "vfa_max_gCOD_m3": float(df.vfa_total_gCOD_m3.max()),
            "q_gas_max_m3_d": float(df.q_gas_m3_d.max()),
        },
        gate=gate(final) if spec is PROBE1 else {},
    )


def main() -> None:
    """Run both probes in both modes and write results/bsm2python.json."""
    result = CandidateResult(
        candidate="bsm2python",
        source="https://pypi.org/project/bsm2-python/",
        version=version("bsm2-python"),
        licence="BSD-3-Clause",
        notes=[
            f"numpy {np.__version__}, scipy {scipy.__version__}",
            "Right-hand side is numba @jit(nopython=True); first call includes JIT compile "
            "(cached to disk afterwards). Timings below are for a warm cache.",
            "Ion states (S_hva..S_nh3) are ODE states (R&J 'ODE implementation'), not algebraic.",
        ],
    )
    # warm the numba cache so timings reflect execution, not compilation
    adm1equations(0.0, initial_state(), influent_state(1.0), PAR, T_OP_K, DIM)
    for mode in ("shipped", "bdf"):
        for spec in (PROBE1, PROBE2):
            r = probe(spec, mode)
            result.probes.append(r)
            print(f"{r.name}: ok={r.ok} wall={r.wall_s:.1f}s final={r.final} err={r.error}")
    print("wrote", result.write())


if __name__ == "__main__":
    main()
