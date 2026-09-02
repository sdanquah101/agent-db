"""Probe ADM1F (lanl/ADM1F): C++/PETSc implementation driven as a subprocess.

ADM1F is a command-line executable: it reads ``params.dat`` (100 values), ``ic.dat``
(45 states) and ``influent.dat`` (26 states + Q + T) from the working directory and
writes one ``adm1_output-NNN.out`` (54 values) per accepted time step. The integrator is
PETSc TSARKIMEX with an ADOL-C automatic-differentiation Jacobian; the time horizon is
set with ``-ts_max_time``. A step change in influent requires two chained runs.

Two variants exist in ``build/``: ``adm1f.cxx`` (standard ADM1 kinetics) and
``adm1f_srt.cxx`` (SRT decoupling plus a Haldane/LCFA-inhibited acetate uptake). The
shipped makefile builds only the latter; both are probed here.

Usage: ``probe_adm1f.py <path-to-ADM1F-checkout> <exe-name> <candidate-label>``
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
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
    initial_vector,
)
from common import (
    STEADY_STATE_IONS_GAS_RJ2006 as IONS,
)

MONITOR_RE = re.compile(r"^\s*(\d+) TS dt (\S+) time (\S+)")
TS_OPTS = ["-ts_monitor", "-ts_exact_final_time", "matchstep", "-ts_max_steps", "100000"]


def write_vec(path: Path, values: list[float]) -> None:
    """Write one value per line, the format ADM1F's readers expect."""
    path.write_text("".join(f"{v:.10e}\n" for v in values))


def initial_state_45() -> list[float]:
    """ic.dat layout: 26 states, 6 ion states, 3 gas states, Q, T, 5 dummies, H+, CO2, NH4+."""
    s = initial_vector()
    ions = [
        IONS[k] for k in ("S_va_ion", "S_bu_ion", "S_pro_ion", "S_ac_ion", "S_hco3_ion", "S_nh3")
    ]
    gas = [IONS[k] for k in ("S_gas_h2", "S_gas_ch4", "S_gas_co2")]
    S_IC, S_IN = s[9], s[10]
    return [
        *s,
        *ions,
        *gas,
        Q_IN_M3_D,
        T_OP_K - 273.15,
        0,
        0,
        0,
        0,
        0,
        IONS["S_H_ion"],
        S_IC - IONS["S_hco3_ion"],
        S_IN - IONS["S_nh3"],
    ]


def output_to_ic(y: np.ndarray) -> list[float]:
    """Rebuild a 45-state ic.dat vector from a 54-value adm1_output row."""
    return [*y[0:26], *y[35:40], y[41], *y[43:46], y[26], y[27], *y[28:33], y[34], y[40], y[42]]


def read_out(path: Path) -> np.ndarray:
    """Parse a PETSc ASCII VecView file (two header lines, then one value per line)."""
    return np.array([float(x) for x in path.read_text().splitlines()[2:]])


def run_segment(
    exe: Path, params: Path, workdir: Path, ic: list[float], factor: float, days: float
) -> dict:
    """Run ADM1F once for ``days`` with a constant influent; return the trajectory."""
    for f in workdir.glob("*.out"):
        f.unlink()
    shutil.copy(params, workdir / "params.dat")
    write_vec(workdir / "ic.dat", ic)
    write_vec(workdir / "influent.dat", [*influent_vector(factor), Q_IN_M3_D, T_OP_K - 273.15])
    proc = subprocess.run(
        [str(exe), "-ts_max_time", str(days), *TS_OPTS],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"adm1f exited {proc.returncode}: {proc.stderr[-2000:]}")
    steps = [
        (int(m.group(1)), float(m.group(2)), float(m.group(3)))
        for line in proc.stdout.splitlines()
        if (m := MONITOR_RE.match(line))
    ]
    if not steps:
        raise RuntimeError(f"no -ts_monitor lines in stdout:\n{proc.stdout[-2000:]}")
    times = {n: t for n, _, t in steps}
    rows = []
    for f in sorted(workdir.glob("adm1_output-*.out")):
        n = int(f.stem.split("-")[1])
        if n in times and times[n] > 0:
            rows.append((times[n], read_out(f)))
    dts = np.array([dt for _, dt, _ in steps])
    return {
        "rows": rows,
        "steps": len(steps),
        "min_dt_d": float(dts.min()),
        "max_dt_d": float(dts.max()),
        "last_time": steps[-1][2],
        "diverged": "DIVERGED" in proc.stdout + proc.stderr,
    }


def summarise(t: float, y: np.ndarray) -> dict[str, float]:
    """Post-process one 54-value ADM1F output row."""
    P_gas, p_h2, p_ch4, p_co2 = y[49], y[46], y[47], y[48]
    return {
        "t": t,
        **derived(
            pH=y[33],
            p_h2=p_h2,
            p_ch4=p_ch4,
            p_co2=p_co2,
            p_h2o=P_gas - p_h2 - p_ch4 - p_co2,
            q_gas=y[50],
            S_va=y[3],
            S_bu=y[4],
            S_pro=y[5],
            S_ac=y[6],
        ),
    }


def run(exe: Path, params: Path, days: float, step_day: float | None, factor: float) -> dict:
    """Run one or two chained segments and collect the trajectory and step statistics."""
    segments = [(days, 1.0)] if step_day is None else [(step_day, 1.0), (days - step_day, factor)]
    ic, t_off, rows, stats = (
        initial_state_45(),
        0.0,
        [],
        {"steps": 0, "min_dt_d": np.inf, "max_dt_d": 0.0},
    )
    with tempfile.TemporaryDirectory() as tmp:
        for seg_days, f in segments:
            out = run_segment(exe, params, Path(tmp), ic, f, seg_days)
            if out["diverged"] or abs(out["last_time"] - seg_days) > 1e-6:
                raise RuntimeError(
                    f"segment ended at t={out['last_time']} of {seg_days} "
                    f"(diverged={out['diverged']})"
                )
            rows.extend(summarise(t_off + t, y) for t, y in out["rows"])
            stats["steps"] += out["steps"]
            stats["min_dt_d"] = min(stats["min_dt_d"], out["min_dt_d"])
            stats["max_dt_d"] = max(stats["max_dt_d"], out["max_dt_d"])
            ic, t_off = output_to_ic(out["rows"][-1][1]), t_off + seg_days
    return {"df": pd.DataFrame(rows), "stats": stats}


def probe(exe: Path, params: Path, spec: dict) -> ProbeResult:
    """Run one probe and package the outcome."""
    solver = "PETSc TSARKIMEX (default ARK 3) with ADOL-C AD Jacobian; adaptive dt from 1e-3 d"
    settings = {
        "ts_type": "arkimex",
        "initial_dt_d": 1e-3,
        "ts_exact_final_time": "matchstep",
        "tolerances": "PETSc TSAdapt defaults (rtol 1e-4, atol 1e-4)",
    }
    try:
        with Stopwatch() as sw:
            out = run(exe, params, spec["days"], spec.get("step_day"), spec.get("factor", 1.0))
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


def main(repo: Path, exe_name: str, label: str) -> None:
    """Run both probes against ``build/<exe_name>`` and write results/<label>.json."""
    exe, params = repo / "build" / exe_name, repo / "simulations" / "params.dat"
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    petsc = subprocess.run(
        ["pkg-config", "--modversion", "PETSc"], capture_output=True, text=True
    ).stdout.strip()
    result = CandidateResult(
        candidate=label,
        source="https://github.com/lanl/ADM1F",
        version=commit,
        licence="BSD-3-Clause",
        notes=[
            f"Built from build/{exe_name} source against system PETSc {petsc or '?'} "
            "and ADOL-C 2.7.2 "
            "(Ubuntu packages) with adolc-utils copied from the PETSc source tree; the shipped "
            "makefile does not work with PETSc >= 3.15.",
            "Uses the shipped simulations/params.dat (BSM2 defaults, but Henry constants and "
            "water vapour pressure use Metcalf & Eddy / Antoine forms, not the R&J 2006 ones).",
            "Driven by files + subprocess; one output file per accepted step.",
        ],
    )
    for spec in (PROBE1, PROBE2):
        r = probe(exe, params, spec)
        result.probes.append(r)
        print(f"{r.name}: ok={r.ok} wall={r.wall_s:.1f}s final={r.final} err={r.error}")
    print("wrote", result.write())


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
