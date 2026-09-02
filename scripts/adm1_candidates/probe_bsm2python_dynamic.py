"""Probe bsm2-python on the BSM2 dynamic digester influent (Milestone-2 oracle).

The influent is the 15-minute ADM1-space time series that PyADM1 ships as
``src/digester_influent.csv`` (280 d, 26 881 rows, Q varying 59-466 m3/d, 35 degC),
trimmed to the 26 ADM1 states + Q + T and committed as
``data/bsm2_digester_influent_15min.csv.gz``; the SHA-256 of both the original and the
trimmed file are recorded in the result.

Three ways of applying the series are recorded, all from the R&J 2006 steady state:

* ``hold``   : sample-and-hold; one ``solve_ivp(BDF)`` call per 15-min segment
               (rtol 1e-6, atol 1e-8). This is the primary oracle.
* ``shipped``: sample-and-hold; ``odeint`` (LSODA) per 15-min segment with the
               package's own rtol = atol = 1e-6. Secondary check on the solver.
* ``linear`` : influent linearly interpolated between samples; one ``solve_ivp(BDF)``
               call over the whole horizon with ``max_step`` = 15 min.

Daily samples (t = 0, 1, ..., 280 d) of pH, q_gas (BSM2 convention), S_ac and a few
other quantities are recorded, plus the full 35-state vector at t = 280 d.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import sys
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import scipy
from bsm2_python.bsm2.adm1_bsm2 import adm1equations
from bsm2_python.bsm2.init import adm1init_bsm2 as adm1init
from common import RESULTS_DIR, T_OP_K, CandidateResult, ProbeResult
from probe_bsm2python import summarise
from scipy.integrate import odeint, solve_ivp

DATA = Path(__file__).resolve().parent / "data" / "bsm2_digester_influent_15min.csv.gz"
ORIGINAL_SHA256 = "df97e295977f173d023aa7b7a79d18bcd22d079dbb4f066203fd9f6e3173bb30"
PAR = adm1init.DIGESTERPAR
DIM = adm1init.DIM_D
STATE35 = [
    "S_su", "S_aa", "S_fa", "S_va", "S_bu", "S_pro", "S_ac", "S_h2", "S_ch4", "S_IC",
    "S_IN", "S_I", "X_xc", "X_ch", "X_pr", "X_li", "X_su", "X_aa", "X_fa", "X_c4",
    "X_pro", "X_ac", "X_h2", "X_I", "S_cat", "S_an", "S_va_ion", "S_bu_ion", "S_pro_ion",
    "S_ac_ion", "S_hco3_ion", "S_nh3", "S_gas_h2", "S_gas_ch4", "S_gas_co2",
]  # fmt: skip


def load_influent() -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """Return (t, conc(n,26), q(n)) and the SHA-256 of the uncompressed CSV."""
    with gzip.open(DATA, "rb") as fh:
        raw = fh.read()
    sha = hashlib.sha256(raw).hexdigest()
    rows = list(csv.reader(raw.decode().splitlines()))
    hdr, body = rows[0], np.array(rows[1:], dtype=float)
    assert hdr[0] == "time" and hdr[27] == "Q" and hdr[28] == "T_C", hdr
    assert np.all(body[:, 28] == 35.0), "expected a constant 35 degC series"
    return body[:, 0], body[:, 1:27], body[:, 27], sha


def yd_in_vector(conc: np.ndarray, q: float) -> np.ndarray:
    yd_in = np.zeros(42)
    yd_in[:26] = conc
    yd_in[35] = q
    yd_in[36] = T_OP_K - 273.15
    return yd_in


def initial_state() -> np.ndarray:
    y0 = adm1init.DIGESTERINIT.astype(float).copy()
    return y0


def sample(t: float, y: np.ndarray) -> dict[str, float]:
    s = summarise(t, y)
    s["S_IN_kmol_m3"] = float(y[10])
    s["S_IC_kmol_m3"] = float(y[9])
    return s


def run_hold(t: np.ndarray, conc: np.ndarray, q: np.ndarray, mode: str) -> dict:
    """Sample-and-hold, one solver call per 15-min segment."""
    y = initial_state()
    daily = [sample(0.0, y)]
    stats = {"nfev": 0, "njev": 0, "nlu": 0, "nst": 0, "min_last_step_d": np.inf}
    for k in range(len(t) - 1):
        yd_in = yd_in_vector(conc[k], q[k])
        if mode == "bdf":
            sol = solve_ivp(
                lambda tt, yy, u=yd_in: adm1equations(tt, yy, u, PAR, T_OP_K, DIM),
                (t[k], t[k + 1]),
                y,
                method="BDF",
                rtol=1e-6,
                atol=1e-8,
            )
            if not sol.success:
                raise RuntimeError(f"segment {k}: {sol.message}")
            y = sol.y[:, -1]
            stats["nfev"] += sol.nfev
            stats["njev"] += sol.njev
            stats["nlu"] += sol.nlu
            stats["nst"] += len(sol.t) - 1
        else:
            out, info = odeint(
                adm1equations,
                y,
                [t[k], t[k + 1]],
                tfirst=True,
                args=(yd_in, PAR, T_OP_K, DIM),
                rtol=1e-6,
                atol=1e-6,
                full_output=True,
            )
            if info["message"] != "Integration successful.":
                raise RuntimeError(f"segment {k}: {info['message']}")
            y = out[1]
            stats["nfev"] += int(info["nfe"][-1])
            stats["njev"] += int(info["nje"][-1])
            stats["nst"] += int(info["nst"][-1])
            stats["min_last_step_d"] = min(stats["min_last_step_d"], float(info["hu"][-1]))
        if abs(t[k + 1] - round(t[k + 1])) < 1e-6:
            daily.append(sample(float(round(t[k + 1])), y))
    if mode == "bdf":
        stats.pop("min_last_step_d")
    return {
        "daily": daily,
        "final_state": dict(zip(STATE35, y[:35].tolist(), strict=True)),
        "stats": stats,
    }


def run_linear(t: np.ndarray, conc: np.ndarray, q: np.ndarray) -> dict:
    """Linearly interpolated influent, one BDF call, max_step = sample spacing."""
    dt = float(np.diff(t).min())
    dc = np.diff(conc, axis=0) / np.diff(t)[:, None]
    dq = np.diff(q) / np.diff(t)

    def influent(tt: float) -> np.ndarray:
        i = min(max(int(np.searchsorted(t, tt, side="right")) - 1, 0), len(t) - 2)
        h = tt - t[i]
        return yd_in_vector(conc[i] + dc[i] * h, q[i] + dq[i] * h)

    days = np.arange(0.0, t[-1] + 1e-9, 1.0)
    sol = solve_ivp(
        lambda tt, yy: adm1equations(tt, yy, influent(tt), PAR, T_OP_K, DIM),
        (t[0], t[-1]),
        initial_state(),
        method="BDF",
        rtol=1e-6,
        atol=1e-8,
        max_step=dt,
        t_eval=days,
    )
    if not sol.success:
        raise RuntimeError(sol.message)
    daily = [sample(float(tt), yy) for tt, yy in zip(sol.t, sol.y.T, strict=True)]
    return {
        "daily": daily,
        "final_state": dict(zip(STATE35, sol.y[:35, -1].tolist(), strict=True)),
        "stats": {"nfev": sol.nfev, "njev": sol.njev, "nlu": sol.nlu},
    }


def main() -> None:
    t, conc, q, sha = load_influent()
    days = float(t[-1])
    result = CandidateResult(
        candidate="bsm2python_dynamic",
        source="https://pypi.org/project/bsm2-python/",
        version=version("bsm2-python"),
        licence="BSD-3-Clause",
        notes=[
            f"numpy {np.__version__}, scipy {scipy.__version__}",
            "Influent: PyADM1 src/digester_influent.csv (github.com/CaptainFerMag/PyADM1), "
            f"original SHA-256 {ORIGINAL_SHA256}; trimmed to time + 26 states + Q + T_C "
            f"(numeric text unchanged) as data/bsm2_digester_influent_15min.csv.gz, "
            f"uncompressed SHA-256 {sha}.",
            f"{len(t)} samples, {days} d, Q min/mean/max = "
            f"{q.min():.2f}/{q.mean():.2f}/{q.max():.2f} m3/d, T = 35 degC.",
            "Initial state: R&J 2006 steady state (bsm2-python DIGESTERINIT).",
            "Ion states are ODE states (R&J 'ODE implementation'); S_h2 is an ODE state.",
            "daily[k] is the state at t = k d exactly (segment boundaries).",
        ],
    )
    adm1equations(0.0, initial_state(), yd_in_vector(conc[0], q[0]), PAR, T_OP_K, DIM)
    runs = {
        "hold": (
            lambda: run_hold(t, conc, q, "bdf"),
            "scipy solve_ivp BDF, one call per 15-min sample-and-hold segment",
            {"rtol": 1e-6, "atol": 1e-8, "influent": "sample-and-hold"},
        ),
        "shipped": (
            lambda: run_hold(t, conc, q, "odeint"),
            "scipy odeint (LSODA), one call per 15-min sample-and-hold segment",
            {"rtol": 1e-6, "atol": 1e-6, "influent": "sample-and-hold"},
        ),
        "linear": (
            lambda: run_linear(t, conc, q),
            "scipy solve_ivp BDF over the whole horizon, max_step = 15 min",
            {
                "rtol": 1e-6,
                "atol": 1e-8,
                "max_step_d": 1.0 / 96.0,
                "influent": "linear interpolation",
            },
        ),
    }
    wanted = sys.argv[1:] or list(runs)
    for name in wanted:
        fn, solver, settings = runs[name]
        t0 = time.perf_counter()
        out = fn()
        wall = time.perf_counter() - t0
        daily = out["daily"]
        final = {k: v for k, v in daily[-1].items() if k != "t"}
        ph = np.array([d["pH"] for d in daily])
        result.probes.append(
            ProbeResult(
                name=f"BSM2_dynamic_280d[{name}]",
                ok=bool(np.all(np.isfinite([list(d.values()) for d in daily]))),
                wall_s=wall,
                wall_s_per_sim_day=wall / days,
                solver=solver,
                solver_settings=settings,
                stats={**out["stats"], "daily": daily, "final_state": out["final_state"]},
                final=final,
                extremes={
                    "pH_min": float(ph.min()),
                    "pH_max": float(ph.max()),
                    "q_gas_max_m3_d": float(max(d["q_gas_m3_d"] for d in daily)),
                },
            )
        )
        print(
            f"{name}: wall={wall:.1f}s final pH={final['pH']:.4f} "
            f"q_gas={final['q_gas_m3_d']:.1f} S_ac={final['S_ac_gCOD_m3']:.2f}"
        )
    RESULTS_DIR.mkdir(exist_ok=True)
    print("wrote", result.write())


if __name__ == "__main__":
    main()
