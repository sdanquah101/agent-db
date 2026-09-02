"""Probe: can SAO establish at Plant A's operating envelope in the truth model?

Runs the extended ADM1 (SAO enabled, current configured kinetics) at the AFBI
Hillsborough geometry recorded in ``docs/anchor_datasets.md`` (650 m3 primary CSTR,
41 C) over HRTs of 28, 35 and 45 d with the ADM1 STR sewage-sludge probe feed and a
range of feed total ammonia, seeding a small SAO population, and reports whether X_sao
grows and what fraction of acetate it removes. Decision input for the plant
configurations (decisions log 2026-09-02: with mu_max 0.08 d^-1 SAO did not establish
at 28 d, which led to the fast-end kinetics and the 35-45 d HRT); not a test.

Usage: ``python scripts/plant_a_sao_probe.py`` (prints a table).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from sim.adm1 import (  # noqa: E402
    LIQUID_STATE_NAMES,
    Influent,
    PlantGeometry,
    compile_extended,
    extended_state,
    load_extensions,
    load_matrix,
    load_parameters,
    load_solver_config,
    simulate,
    simulate_extended,
)
from sim.adm1.model import state_vector  # noqa: E402
from sim.plants import KG_N_PER_KMOL  # noqa: E402

RJ2006_GAS_STATE = {"S_gas_h2": 1.1032e-5, "S_gas_ch4": 1.6535, "S_gas_co2": 0.0135}
I_S_AC = LIQUID_STATE_NAMES.index("S_ac")


def _probe_common():
    spec = importlib.util.spec_from_file_location(
        "adm1_probe_common", REPO / "scripts" / "adm1_candidates" / "common.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    """Run the envelope sweep and print one row per (HRT, feed TAN) case."""
    common = _probe_common()
    params, matrix, solver, ext = (
        load_parameters(),
        load_matrix(),
        load_solver_config(),
        load_extensions(),
    )
    y0 = state_vector(common.STEADY_STATE_RJ2006, RJ2006_GAS_STATE)
    u = np.array(common.influent_vector(1.0))
    V_liq, V_gas, T_op = 650.0, 65.0, 273.15 + 41.0  # AFBI primary digester, 41 C
    plant = PlantGeometry(V_liq=V_liq, V_gas=V_gas, T_op=T_op)
    model = compile_extended(params, plant, matrix, solver, ext, ("sao",))
    horizon = 400.0
    print(
        f"Plant A envelope: V_liq {V_liq} m3, T {T_op - 273.15:.0f} C, "
        f"ADM1 STR feed, X_sao seed 0.05 kg COD/m3, {horizon:.0f} d"
    )
    print(
        f"{'HRT d':>6} {'TAN g/L':>8} {'pH':>6} {'FA mg/L':>8} {'S_ac base':>10} "
        f"{'S_ac SAO':>9} {'X_sao end':>10} {'grew':>5}"
    )
    for hrt in (28.0, 35.0, 45.0):
        q = V_liq / hrt
        for s_in in (0.10, 0.15, 0.20, 0.25):
            uu = u.copy()
            uu[LIQUID_STATE_NAMES.index("S_IN")] = s_in
            base = simulate(
                y0=y0,
                influent=Influent.constant(uu, q),
                params=params,
                plant=plant,
                matrix=matrix,
                solver=solver,
                t_span=(0.0, horizon),
                t_eval=np.array([horizon]),
            )
            r = simulate_extended(
                y0=extended_state(model, y0, {"X_sao": 0.05}),
                influent=Influent.constant(uu, q),
                model=model,
                t_span=(0.0, horizon),
                t_eval=np.array([horizon]),
            )
            fa = float(base.S_nh3[-1]) * KG_N_PER_KMOL * 1000.0
            x_end = float(r.state("X_sao")[-1])
            print(
                f"{hrt:6.0f} {s_in * KG_N_PER_KMOL:8.2f} {float(base.pH[-1]):6.2f} {fa:8.0f} "
                f"{float(base.y[I_S_AC, -1]):10.2f} {float(r.state('S_ac')[-1]):9.2f} "
                f"{x_end:10.3f} {'yes' if x_end > 0.05 else 'no':>5}"
            )


if __name__ == "__main__":
    main()
