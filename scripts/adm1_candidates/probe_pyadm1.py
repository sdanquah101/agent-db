"""Probe PyADM1 (CaptainFerMag/PyADM1, single-file script).

PyADM1 is a 736-line script that reads CSVs and runs a simulation at import time, so it
cannot be imported as a library. This probe executes the definitions section of the
script (everything before its ``## time array definition`` marker) into a namespace,
then reproduces its own stepping loop: per influent step, ``solve_ivp`` over the ODE
states, then a Newton solve for S_H+ and S_h2 (the R&J 2006 DAE formulation).

Usage: ``probe_pyadm1.py <path-to-PyADM1-checkout>``
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
from common import (
    PROBE1,
    PROBE2,
    Q_IN_M3_D,
    STATE_NAMES,
    CandidateResult,
    ProbeResult,
    Stopwatch,
    derived,
    gate,
    influent_vector,
)

DT_D = 1.0 / 96.0  # 15-minute stepping, as in the shipped influent file

# the script names the strong-ion states S_cation / S_anion
ODE_STATE_NAMES = [
    *[{"S_cat": "S_cation", "S_an": "S_anion"}.get(n, n) for n in STATE_NAMES],
    "S_H_ion",
    "S_va_ion",
    "S_bu_ion",
    "S_pro_ion",
    "S_ac_ion",
    "S_hco3_ion",
    "S_co2",
    "S_nh3",
    "S_nh4_ion",
    "S_gas_h2",
    "S_gas_ch4",
    "S_gas_co2",
]


def load_namespace(src_dir: Path) -> dict:
    """Execute PyADM1.py's definitions (not its main loop) and return the namespace."""
    source = (src_dir / "PyADM1.py").read_text()
    head = source.split("## time array definition")[0]
    ns: dict = {}
    cwd = os.getcwd()
    os.chdir(src_dir)  # the script reads its CSVs relative to cwd
    try:
        exec(compile(head, str(src_dir / "PyADM1.py"), "exec"), ns)
    finally:
        os.chdir(cwd)
    return ns


def set_influent(ns: dict, factor: float) -> None:
    """Point the script's influent globals at the R&J influent scaled by ``factor``."""
    row = dict(zip(STATE_NAMES, influent_vector(factor), strict=True))
    row["S_cation"] = row.pop("S_cat")
    row["S_anion"] = row.pop("S_an")
    ns["influent_state"] = pd.DataFrame([row])
    ns["setInfluent"](0)
    # ADM1_ODE reads the feed from the global list the script's main loop builds, not
    # from the *_in globals setInfluent sets, so rebuild that list too.
    ns["state_input"] = [ns[f"{name}_in"] for name in ODE_STATE_NAMES[:26]]
    ns["q_ad"] = Q_IN_M3_D  # the script ignores the Q column and uses a constant


def run(ns: dict, days: float, method: str, step_day: float | None, factor: float) -> dict:
    """Replicate the script's loop for ``days`` at DT_D; return series and solver stats."""
    set_influent(ns, 1.0)
    state = list(ns["state_zero"])
    n_steps = round(days / DT_D)
    t_grid = np.arange(n_steps + 1) * DT_D
    rows, nfev, min_dt, max_dt, n_int_steps = [], 0, np.inf, 0.0, 0
    for k in range(1, n_steps + 1):
        if step_day is not None and abs(t_grid[k - 1] - step_day) < 1e-9:
            set_influent(ns, factor)
        sol = scipy.integrate.solve_ivp(
            ns["ADM1_ODE"], (t_grid[k - 1], t_grid[k]), state, method=method
        )
        if not sol.success:
            raise RuntimeError(f"solve_ivp failed at t={t_grid[k]:.4f}: {sol.message}")
        nfev += sol.nfev
        n_int_steps += len(sol.t) - 1
        if len(sol.t) > 1:
            dts = np.diff(sol.t)
            min_dt, max_dt = min(min_dt, dts.min()), max(max_dt, dts.max())
        for name, value in zip(ODE_STATE_NAMES, sol.y[:, -1], strict=True):
            ns[name] = float(value)
        ns["DAESolve"]()
        ns["S_nh4_ion"] = ns["S_IN"] - ns["S_nh3"]
        ns["S_co2"] = ns["S_IC"] - ns["S_hco3_ion"]
        state = [ns[name] for name in ODE_STATE_NAMES]
        R, T = ns["R"], ns["T_op"]
        p_h2 = ns["S_gas_h2"] * R * T / 16
        p_ch4 = ns["S_gas_ch4"] * R * T / 64
        p_co2 = ns["S_gas_co2"] * R * T
        p_h2o = ns["p_gas_h2o"]
        P_gas = p_h2 + p_ch4 + p_co2 + p_h2o
        q_gas = max(ns["k_p"] * (P_gas - ns["p_atm"]), 0.0) * P_gas / ns["p_atm"]
        rows.append(
            {
                "t": t_grid[k],
                **derived(
                    pH=ns["pH"],
                    p_h2=p_h2,
                    p_ch4=p_ch4,
                    p_co2=p_co2,
                    p_h2o=p_h2o,
                    q_gas=q_gas,
                    S_va=ns["S_va"],
                    S_bu=ns["S_bu"],
                    S_pro=ns["S_pro"],
                    S_ac=ns["S_ac"],
                ),
            }
        )
    df = pd.DataFrame(rows)
    return {
        "df": df,
        "stats": {
            "outer_steps": n_steps,
            "inner_integrator_steps": n_int_steps,
            "nfev": nfev,
            "min_inner_dt_d": float(min_dt),
            "max_inner_dt_d": float(max_dt),
        },
    }


def probe(ns: dict, spec: dict, method: str) -> ProbeResult:
    """Run one probe with one solver and package the outcome."""
    settings = {
        "method": method,
        "rtol": "solve_ivp default 1e-3",
        "atol": "solve_ivp default 1e-6",
        "outer_dt_d": DT_D,
    }
    try:
        with Stopwatch() as sw:
            out = run(ns, spec["days"], method, spec.get("step_day"), spec.get("factor", 1.0))
    except Exception as exc:
        return ProbeResult(
            name=f"{spec['name']}[{method}]",
            ok=False,
            wall_s=float("nan"),
            wall_s_per_sim_day=float("nan"),
            solver=f"scipy solve_ivp {method}",
            solver_settings=settings,
            error=f"{exc}\n{traceback.format_exc(limit=3)}",
        )
    df = out["df"]
    final = df.iloc[-1].drop("t").to_dict()
    return ProbeResult(
        name=f"{spec['name']}[{method}]",
        ok=bool(np.isfinite(df.drop(columns="t")).all().all()),
        wall_s=sw.wall_s,
        wall_s_per_sim_day=sw.wall_s / spec["days"],
        solver=f"scipy solve_ivp {method} + Newton DAE for S_H+, S_h2 between steps",
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


def main(src_dir: Path) -> None:
    """Run both probes with the shipped solver (DOP853) and with a stiff solver (BDF)."""
    commit = subprocess.run(
        ["git", "-C", str(src_dir), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    result = CandidateResult(
        candidate="pyadm1",
        source="https://github.com/CaptainFerMag/PyADM1",
        version=commit,
        licence="MIT",
        notes=[
            f"numpy {np.__version__}, scipy {scipy.__version__}, pandas {pd.__version__}",
            "Script, not a package: definitions exec'd from source; main loop reproduced here.",
            "Ships with solvermethod='DOP853' (explicit RK); BDF added here for comparison.",
            "Ignores the influent Q column; q_ad is a module constant (set to 170 here).",
        ],
    )
    ns = load_namespace(src_dir / "src")
    for method in ("DOP853", "BDF"):
        for spec in (PROBE1, PROBE2):
            r = probe(ns, spec, method)
            result.probes.append(r)
            print(f"{r.name}: ok={r.ok} wall={r.wall_s:.1f}s final={r.final} err={r.error}")
    print("wrote", result.write())


if __name__ == "__main__":
    main(Path(sys.argv[1]))
