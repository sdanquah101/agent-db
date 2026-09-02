"""Ring tests of sim/adm1 against bsm2-python (the primary oracle, decisions log 2026-09-02).

Oracle values were produced in a throwaway venv by ``scripts/adm1_candidates/
probe_bsm2python.py`` (Probes 1 and 2) and ``probe_bsm2python_dynamic.py`` (BSM2 dynamic
influent) and committed as JSON; this module needs only the repository's own
dependencies.

"Agreement to 3 significant figures" is implemented as a relative difference of at most
``REL_TOL_3SF = 5e-4`` (half a unit in the third significant figure of a number with
leading digit 1; stricter for larger leading digits). Do not loosen it to make a case
pass: a failing assertion here is a finding to report (CLAUDE.md, decisions log).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json

import numpy as np
import pytest

from sim.adm1 import STATE_NAMES, Influent, simulate
from tests.conftest import CANDIDATES_DIR

REL_TOL_3SF = 5e-4
ORACLE_PROBES = CANDIDATES_DIR / "results" / "bsm2python.json"
ORACLE_DYNAMIC = CANDIDATES_DIR / "results" / "bsm2python_dynamic.json"
INFLUENT_GZ = CANDIDATES_DIR / "data" / "bsm2_digester_influent_15min.csv.gz"
ION_NAMES = ("S_va_ion", "S_bu_ion", "S_pro_ion", "S_ac_ion", "S_hco3_ion", "S_nh3")


def _assert_3sf(mine: dict[str, float], oracle: dict[str, float], label: str) -> None:
    rows = []
    for name, ref in oracle.items():
        val = mine[name]
        rel = abs(val - ref) / abs(ref) if ref != 0 else abs(val)
        rows.append((rel, name, val, ref))
    rows.sort(reverse=True)
    worst = "\n".join(
        f"  {n:14s} model={v:.6g} oracle={r:.6g} rel={e:.2e}" for e, n, v, r in rows[:8]
    )
    assert rows[0][0] <= REL_TOL_3SF, f"{label}: largest discrepancies\n{worst}"


def _summary(result, idx: int = -1) -> dict[str, float]:
    """The same derived quantities the oracle harness records (common.derived)."""
    y = result.y[:, idx]
    P_gas, p_h2o = float(result.P_gas[idx]), float(result.p_h2o[idx])
    return {
        "pH": float(result.pH[idx]),
        "P_gas_bar": P_gas,
        "p_ch4_bar": float(result.p_ch4[idx]),
        "p_co2_bar": float(result.p_co2[idx]),
        "p_h2_bar": float(result.p_h2[idx]),
        "ch4_fraction_wet": float(result.p_ch4[idx]) / P_gas,
        "ch4_fraction_dry": float(result.p_ch4[idx]) / (P_gas - p_h2o),
        "q_gas_m3_d": float(result.q_gas[idx]),
        "q_gas_STP_dry_m3_d": float(result.q_gas_stp_dry[idx]),
        "vfa_total_gCOD_m3": float(1000.0 * y[3:7].sum()),
        "S_ac_gCOD_m3": float(1000.0 * y[6]),
        "S_pro_gCOD_m3": float(1000.0 * y[5]),
        "S_IN_kmol_m3": float(y[10]),
        "S_IC_kmol_m3": float(y[9]),
    }


def _states(result, idx: int = -1) -> dict[str, float]:
    out = dict(zip(STATE_NAMES, result.y[:, idx].tolist(), strict=True))
    for name in ION_NAMES:
        out[name] = float(getattr(result, name)[idx])
    return out


@pytest.fixture(scope="module")
def oracle_probes() -> dict[str, dict]:
    doc = json.loads(ORACLE_PROBES.read_text(encoding="utf-8"))
    assert doc["candidate"] == "bsm2python"
    return {p["name"]: p for p in doc["probes"]}


@pytest.fixture(scope="module")
def oracle_dynamic() -> dict[str, dict]:
    doc = json.loads(ORACLE_DYNAMIC.read_text(encoding="utf-8"))
    assert doc["candidate"] == "bsm2python_dynamic"
    return {p["name"]: p for p in doc["probes"]}


@pytest.fixture(scope="module")
def probe1(rj2006_state, probe_common, adm1_params, adm1_plant, adm1_matrix, adm1_solver):
    """Probe 1 exactly as common.py defines it: 100 d, constant STR feed, Q = 170."""
    u = np.array(probe_common.influent_vector(1.0))
    return simulate(
        y0=rj2006_state,
        influent=Influent.constant(u, probe_common.Q_IN_M3_D),
        params=adm1_params,
        plant=adm1_plant,
        matrix=adm1_matrix,
        solver=adm1_solver,
        t_span=(0.0, probe_common.PROBE1["days"]),
        t_eval=np.array([probe_common.PROBE1["days"]]),
    )


@pytest.fixture(scope="module")
def probe2(rj2006_state, probe_common, adm1_params, adm1_plant, adm1_matrix, adm1_solver):
    """Probe 2: 20 d, all feed concentrations x3 from day 10, constant Q."""
    spec = probe_common.PROBE2
    u = np.array(probe_common.influent_vector(1.0))
    influent = Influent(
        t=np.array([0.0, spec["step_day"]]),
        concentrations=np.vstack([u, spec["factor"] * u]),
        q=np.array([probe_common.Q_IN_M3_D] * 2),
    )
    return simulate(
        y0=rj2006_state,
        influent=influent,
        params=adm1_params,
        plant=adm1_plant,
        matrix=adm1_matrix,
        solver=adm1_solver,
        t_span=(0.0, spec["days"]),
        t_eval=np.arange(0.0, spec["days"] + 1e-9, 1.0 / 96.0),  # 15-min samples like the oracle
    )


class TestProbe1:
    def test_summary_quantities(self, probe1, oracle_probes):
        assert probe1.success
        _assert_3sf(_summary(probe1), oracle_probes["P1_sludge_100d[bdf]"]["final"], "Probe 1")

    def test_every_state(self, probe1, oracle_probes):
        ref = oracle_probes["P1_sludge_100d[bdf]"]["stats"]["final_state"]
        assert len(ref) == 35
        _assert_3sf(_states(probe1), ref, "Probe 1 final state")

    def test_radau_cross_check(
        self,
        rj2006_state,
        probe_common,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        oracle_probes,
    ):
        radau = adm1_solver.model_copy(update={"method": "Radau"})
        u = np.array(probe_common.influent_vector(1.0))
        r = simulate(
            y0=rj2006_state,
            influent=Influent.constant(u, probe_common.Q_IN_M3_D),
            params=adm1_params,
            plant=adm1_plant,
            matrix=adm1_matrix,
            solver=radau,
            t_span=(0.0, 100.0),
            t_eval=np.array([100.0]),
        )
        assert r.success
        _assert_3sf(_summary(r), oracle_probes["P1_sludge_100d[bdf]"]["final"], "Probe 1 (Radau)")

    def test_plausibility_gate(self, probe1, probe_common):
        s = _summary(probe1)
        s["ch4_fraction_dry"] = float(probe1.p_ch4[-1] / (probe1.P_gas[-1] - probe1.p_h2o[-1]))
        gate = probe_common.gate(s)
        assert all(gate.values()), gate


class TestProbe2:
    def test_summary_quantities(self, probe2, oracle_probes):
        assert probe2.success
        _assert_3sf(_summary(probe2), oracle_probes["P2_olr_step_x3[bdf]"]["final"], "Probe 2")

    def test_every_state(self, probe2, oracle_probes):
        ref = oracle_probes["P2_olr_step_x3[bdf]"]["stats"]["final_state"]
        _assert_3sf(_states(probe2), ref, "Probe 2 final state")

    def test_extremes(self, probe2, oracle_probes):
        ext = oracle_probes["P2_olr_step_x3[bdf]"]["extremes"]
        _assert_3sf(
            {"pH_min": float(probe2.pH.min()), "q_gas_max_m3_d": float(probe2.q_gas.max())},
            {k: ext[k] for k in ("pH_min", "q_gas_max_m3_d")},
            "Probe 2 extremes",
        )

    def test_no_step_size_collapse_on_overload(self, probe2):
        """The 3x overload must integrate without failure and with a sane step count."""
        st = probe2.stats
        assert probe2.success, probe2.message
        assert st.n_segments == 2
        assert st.n_steps < 2000, st  # bsm2-python's own BDF run took 737 RHS evaluations
        assert st.nfev < 5000, st
        assert st.min_step > 1e-9, st  # no collapse towards machine precision
        assert np.all(np.isfinite(probe2.y))


def _load_influent() -> Influent:
    with gzip.open(INFLUENT_GZ, "rb") as fh:
        raw = fh.read()
    rows = list(csv.reader(raw.decode().splitlines()))
    body = np.array(rows[1:], dtype=float)
    assert rows[0][0] == "time" and rows[0][27] == "Q" and rows[0][28] == "T_C"
    assert np.all(body[:, 28] == 35.0)
    return Influent(t=body[:, 0], concentrations=body[:, 1:27], q=body[:, 27]), hashlib.sha256(
        raw
    ).hexdigest()


@pytest.fixture(scope="module")
def dynamic_influent(oracle_dynamic) -> Influent:
    influent, sha = _load_influent()
    doc_notes = json.loads(ORACLE_DYNAMIC.read_text(encoding="utf-8"))["notes"]
    assert any(sha in n for n in doc_notes), "influent file differs from the oracle's"
    assert oracle_dynamic["BSM2_dynamic_280d[hold]"]["ok"]
    assert influent.t[-1] == 280.0 and influent.t.size == 26881
    return influent


def _daily_table(result) -> dict[str, np.ndarray]:
    return {
        "pH": result.pH,
        "q_gas_m3_d": result.q_gas,
        "S_ac_gCOD_m3": 1000.0 * result.y[6],
    }


def _assert_day0_ph_artefact(
    result, oracle_probe: dict, adm1_params, adm1_plant, adm1_solver, probe_common
) -> None:
    """The oracle's day-0 pH is an artefact of its ODE ion states, not a model difference.

    bsm2-python initialises the six ion states from the rounded R&J 2006 table, which does
    not close the charge balance to better than ~1e-6 kmol/m3; its pH at t = 0 is computed
    from those states before they relax (microseconds of simulated time) and comes out at
    8.49. The algebraic pH of the same state is 7.27, which is what this model reports.
    """
    from sim.adm1 import physchem

    ss = probe_common.STEADY_STATE_RJ2006
    k = physchem.temperature_corrected(adm1_params.physchem, adm1_plant.T_op)
    S_h = physchem.solve_pH(
        ss["S_va"],
        ss["S_bu"],
        ss["S_pro"],
        ss["S_ac"],
        ss["S_IC"],
        ss["S_IN"],
        ss["S_cat"],
        ss["S_an"],
        k,
        adm1_solver.pH_solver,
    )
    assert result.pH[0] == pytest.approx(-np.log10(S_h), abs=1e-9)
    assert result.pH[0] == pytest.approx(7.267, abs=2e-3)
    assert oracle_probe["stats"]["daily"][0]["pH"] == pytest.approx(8.49, abs=0.01)


def _assert_daily(result, oracle_probe: dict, label: str) -> None:
    daily = oracle_probe["stats"]["daily"]
    t_ref = np.array([d["t"] for d in daily])
    assert np.array_equal(result.t, t_ref)
    mine = _daily_table(result)
    worst = []
    for key, vals in mine.items():
        ref = np.array([d[key] for d in daily])
        rel = np.abs(vals - ref) / np.abs(ref)
        if key == "pH":
            rel = rel[1:]  # day 0 is the oracle artefact checked by _assert_day0_ph_artefact
            t_key = t_ref[1:]
        else:
            t_key = t_ref
        i = int(np.argmax(rel))
        worst.append(
            (
                float(rel[i]),
                key,
                float(t_key[i]),
                float(vals[i + (key == "pH")]),
                float(ref[i + (key == "pH")]),
            )
        )
    worst.sort(reverse=True)
    msg = "\n".join(
        f"  {k:14s} day {t:5.0f}: model={v:.6g} oracle={r:.6g} rel={e:.2e}"
        for e, k, t, v, r in worst
    )
    assert worst[0][0] <= REL_TOL_3SF, f"{label}: largest daily discrepancies\n{msg}"


@pytest.fixture(scope="module")
def hold_run(rj2006_state, dynamic_influent, adm1_params, adm1_plant, adm1_matrix, adm1_solver):
    """The full 280-day sample-and-hold run (about two minutes; shared by the class)."""
    return simulate(
        y0=rj2006_state,
        influent=dynamic_influent,
        params=adm1_params,
        plant=adm1_plant,
        matrix=adm1_matrix,
        solver=adm1_solver,
        t_span=(0.0, 280.0),
        t_eval=np.arange(0.0, 280.0 + 1e-9, 1.0),
    )


class TestDynamicInfluent:
    """The BSM2 dynamic digester influent, 280 d at 15-min resolution."""

    def test_hold_daily_samples(self, hold_run, oracle_dynamic):
        assert hold_run.success, hold_run.message
        assert hold_run.stats.n_segments == 26880
        _assert_daily(hold_run, oracle_dynamic["BSM2_dynamic_280d[hold]"], "dynamic (hold)")

    def test_day0_ph_is_the_oracle_artefact(
        self, hold_run, oracle_dynamic, adm1_params, adm1_plant, adm1_solver, probe_common
    ):
        _assert_day0_ph_artefact(
            hold_run,
            oracle_dynamic["BSM2_dynamic_280d[hold]"],
            adm1_params,
            adm1_plant,
            adm1_solver,
            probe_common,
        )

    def test_hold_final_state(self, hold_run, oracle_dynamic):
        ref = oracle_dynamic["BSM2_dynamic_280d[hold]"]["stats"]["final_state"]
        _assert_3sf(_states(hold_run), ref, "dynamic (hold) final state")

    def test_hold_final_summary(self, hold_run, oracle_dynamic):
        _assert_3sf(
            _summary(hold_run),
            oracle_dynamic["BSM2_dynamic_280d[hold]"]["final"],
            "dynamic (hold) final summary",
        )

    def test_linear_interpolation_first_30_days(
        self,
        rj2006_state,
        dynamic_influent,
        adm1_params,
        adm1_plant,
        adm1_matrix,
        adm1_solver,
        oracle_dynamic,
    ):
        """The linearly interpolated variant, against the oracle's single-call BDF run."""
        lin = dynamic_influent.model_copy(update={"interpolation": "linear"})
        r = simulate(
            y0=rj2006_state,
            influent=lin,
            params=adm1_params,
            plant=adm1_plant,
            matrix=adm1_matrix,
            solver=adm1_solver,
            t_span=(0.0, 30.0),
            t_eval=np.arange(0.0, 30.0 + 1e-9, 1.0),
        )
        assert r.success and r.stats.n_segments == 1
        probe = oracle_dynamic["BSM2_dynamic_280d[linear]"]
        truncated = {**probe, "stats": {**probe["stats"], "daily": probe["stats"]["daily"][:31]}}
        _assert_daily(r, truncated, "dynamic (linear, 30 d)")
