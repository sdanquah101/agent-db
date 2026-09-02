"""Probe QSDsan (PyPI ``qsdsan``) ADM1 via the EXPOsan ``adm`` example system.

QSDsan implements ADM1 as a Petersen-matrix ``Processes`` object (``qsdsan.processes.ADM1``)
attached to an ``AnaerobicCSTR`` sanunit; the system is integrated with
``scipy.integrate.solve_ivp`` (BDF here). pH is solved algebraically inside the rate
function by a bracketed root find (brenth) on the charge balance; S_h2 is an ODE state.
"""

from __future__ import annotations

import traceback
from importlib.metadata import version

import numpy as np
import pandas as pd
import scipy
from common import (
    PROBE1,
    PROBE2,
    Q_IN_M3_D,
    R_BAR_M3_KMOL_K,
    T_OP_K,
    CandidateResult,
    ProbeResult,
    Stopwatch,
    derived,
    gate,
)
from exposan.adm import create_system, default_inf_kwargs
from qsdsan.processes._adm1 import solve_pH

DT_EVAL_D = 0.25
RTOL, ATOL = 1e-6, 1e-8


def set_influent(inf, factor: float) -> None:
    """Scale every R&J influent concentration by ``factor`` at constant Q."""
    conc = {k: v * factor for k, v in default_inf_kwargs["concentrations"].items()}
    inf.set_flow_by_concentration(Q_IN_M3_D, concentrations=conc, units=default_inf_kwargs["units"])
    inf._init_state()  # push the new concentrations into the stream's dynamic state array


def summarise(AD, t: float, state: np.ndarray) -> dict[str, float]:
    """Post-process one recorded AnaerobicCSTR state row (31 entries)."""
    cmps = AD.components
    params = AD.model.rate_function._params
    pH = -np.log10(solve_pH(state, params["Ka"], params["unit_conv"]))
    gas = state[len(cmps) : len(cmps) + 3]  # kmol/m3 in headspace: H2, CH4, CO2(IC)
    p_h2, p_ch4, p_co2 = gas * R_BAR_M3_KMOL_K * T_OP_K
    p_h2o = AD.p_vapor(convert_to_bar=True)
    P_gas = p_h2 + p_ch4 + p_co2 + p_h2o
    q_gas = max(AD.pipe_resistance * (P_gas - AD.external_P), 0.0) * P_gas / AD.external_P
    idx = {k: cmps.index(k) for k in ("S_va", "S_bu", "S_pro", "S_ac")}
    kg = {k: state[i] for k, i in idx.items()}  # the recorded state is in kg COD/m3
    return {
        "t": t,
        **derived(pH=pH, p_h2=p_h2, p_ch4=p_ch4, p_co2=p_co2, p_h2o=p_h2o, q_gas=q_gas, **kg),
    }


def run(days: float, step_day: float | None, factor: float) -> dict:
    """Simulate; on a step, re-set the influent and continue from the current state."""
    sys_ = create_system()
    AD, inf = sys_.flowsheet.unit.AD, sys_.flowsheet.stream.Influent
    set_influent(inf, 1.0)
    segments = (
        [(0.0, days, 1.0)] if step_day is None else [(0.0, step_day, 1.0), (step_day, days, factor)]
    )
    rows, stats = [], {"nfev": 0, "njev": 0, "nlu": 0, "steps": 0, "min_dt_d": np.inf}
    for i, (t0, t1, f) in enumerate(segments):
        set_influent(inf, f)
        sys_.simulate(
            t_span=(t0, t1),
            t_eval=np.arange(t0, t1 + 1e-9, DT_EVAL_D),
            method="BDF",
            rtol=RTOL,
            atol=ATOL,
            state_reset_hook="reset_cache" if i == 0 else None,
        )
        sol = sys_.scope.sol
        if sol.status != 0:
            raise RuntimeError(f"solve_ivp: {sol.message}")
        stats["nfev"] += sol.nfev
        stats["njev"] += sol.njev
        stats["nlu"] += sol.nlu
        # the scope records every accepted step (and accumulates across calls)
        ts = np.asarray(AD.scope.time_series)
        rec = np.asarray(AD.scope.record)
        seg = sorted(
            (t, r) for t, r in zip(ts, rec, strict=True) if t0 < t <= t1 or (t0 == 0.0 and t == 0.0)
        )
        rows.extend(summarise(AD, t, r) for t, r in seg)
    stats.pop("steps")
    stats.pop("min_dt_d")
    ts = pd.DataFrame(rows)["t"].to_numpy()
    dts = np.diff(np.unique(ts))
    stats.update(accepted_steps=len(dts), min_dt_d=float(dts.min()), max_dt_d=float(dts.max()))
    return {"df": pd.DataFrame(rows), "stats": stats}


def probe(spec: dict) -> ProbeResult:
    """Run one probe and package the outcome."""
    solver = "scipy solve_ivp BDF (system DAE assembled by biosteam); pH by brenth inside RHS"
    settings = {"method": "BDF", "rtol": RTOL, "atol": ATOL, "t_eval_dt_d": DT_EVAL_D}
    try:
        with Stopwatch() as sw:
            out = run(spec["days"], spec.get("step_day"), spec.get("factor", 1.0))
    except Exception as exc:
        return ProbeResult(
            name=spec["name"],
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
        name=spec["name"],
        ok=bool(np.isfinite(df.drop(columns="t")).all().all()),
        wall_s=sw.wall_s,
        wall_s_per_sim_day=sw.wall_s / spec["days"],
        solver=solver,
        solver_settings=settings,
        stats=out["stats"],
        final=final,
        extremes={
            "pH_min": float(df.pH.min()),
            "vfa_max_gCOD_m3": float(df.vfa_total_gCOD_m3.max()),
            "q_gas_max_m3_d": float(df.q_gas_m3_d.max()),
        },
        gate=gate(final) if spec is PROBE1 else {},
    )


def main() -> None:
    """Run both probes and write results/qsdsan.json."""
    result = CandidateResult(
        candidate="qsdsan",
        source="https://pypi.org/project/qsdsan/ (+ exposan.adm example)",
        version=f"qsdsan {version('qsdsan')}, exposan {version('exposan')}",
        licence="UIUC/NCSA (permissive)",
        notes=[
            f"numpy {np.__version__}, scipy {scipy.__version__}",
            "First simulate() includes numba/thermosteam warm-up; a 5-day warm-up run is "
            "done first.",
            "Also ships ADM1p (Flores-Alsina 2016 P/S/Fe extension) with ionic speciation and "
            "seven mineral precipitation processes in qsdsan.processes._adm1_p_extension.",
        ],
    )
    run(5.0, None, 1.0)  # warm-up
    for spec in (PROBE1, PROBE2):
        r = probe(spec)
        result.probes.append(r)
        print(f"{r.name}: ok={r.ok} wall={r.wall_s:.1f}s final={r.final} err={r.error}")
    print("wrote", result.write())


if __name__ == "__main__":
    main()
