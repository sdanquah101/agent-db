"""Shared definitions for the Milestone-1 ADM1 candidate probes.

Everything a probe needs to be comparable across candidates lives here: the influent,
the initial state, the two probe definitions, the plausibility gate with its literature
sources, and the result record written to ``results/<candidate>.json``.

Units follow the BSM2 ADM1 report (Rosen & Jeppsson 2006): soluble/particulate COD in
kg COD m^-3, inorganic C and N in kmol m^-3, ions in kmol m^-3, flows in m^3 d^-1,
temperature in K unless stated. Gas volumes are reported with their convention stated.
"""

from __future__ import annotations

import json
import platform
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# --- Probe definitions -------------------------------------------------------------

#: Mesophilic sewage-sludge digester, the BSM2 reference case. Volumes from BSM2.
V_LIQ_M3 = 3400.0
V_GAS_M3 = 300.0
T_OP_K = 308.15  # 35 degC
Q_IN_M3_D = 170.0

#: Constant sewage-sludge influent used by the ADM1 reference examples (the ADM1 STR
#: benchmark feed, Batstone et al. 2002; also the default of EXPOsan's ``adm`` example and
#: the feed the BSM2 report's steady-state tables are quoted for). NOTE: the published
#: R&J 2006 steady state below has S_cat ~ 0 and S_an = 0.0052, i.e. it was produced with a
#: different strong-ion loading than this feed, so Probe 1 is a 100-day transient from
#: that state to this feed's steady state, not a strict ring test. Implementations are
#: therefore compared with each other and against the plausibility ranges, not to R&J
#: digit-for-digit. Order is the canonical 26-state ADM1 state vector.
STATE_NAMES = [
    "S_su", "S_aa", "S_fa", "S_va", "S_bu", "S_pro", "S_ac", "S_h2", "S_ch4", "S_IC",
    "S_IN", "S_I", "X_xc", "X_ch", "X_pr", "X_li", "X_su", "X_aa", "X_fa", "X_c4",
    "X_pro", "X_ac", "X_h2", "X_I", "S_cat", "S_an",
]  # fmt: skip
INFLUENT_RJ2006 = {
    "S_su": 0.01, "S_aa": 0.001, "S_fa": 0.001, "S_va": 0.001, "S_bu": 0.001,
    "S_pro": 0.001, "S_ac": 0.001, "S_h2": 1e-8, "S_ch4": 1e-5, "S_IC": 0.04,
    "S_IN": 0.01, "S_I": 0.02, "X_xc": 2.0, "X_ch": 5.0, "X_pr": 20.0, "X_li": 5.0,
    "X_su": 0.0, "X_aa": 0.01, "X_fa": 0.01, "X_c4": 0.01, "X_pro": 0.01, "X_ac": 0.01,
    "X_h2": 0.01, "X_I": 25.0, "S_cat": 0.04, "S_an": 0.02,
}  # fmt: skip

#: BSM2 ADM1 steady-state solution for that influent (Rosen & Jeppsson 2006, Table 5).
#: Used as the initial state so that Probe 1 is a ring test against published values.
STEADY_STATE_RJ2006 = {
    "S_su": 0.0124, "S_aa": 0.0055, "S_fa": 0.1074, "S_va": 0.0123, "S_bu": 0.0140,
    "S_pro": 0.0176, "S_ac": 0.0893, "S_h2": 2.5055e-7, "S_ch4": 0.0555, "S_IC": 0.0951,
    "S_IN": 0.0945, "S_I": 0.1309, "X_xc": 0.1079, "X_ch": 0.0205, "X_pr": 0.0842,
    "X_li": 0.0436, "X_su": 0.3122, "X_aa": 0.9317, "X_fa": 0.3384, "X_c4": 0.3258,
    "X_pro": 0.1011, "X_ac": 0.6772, "X_h2": 0.2848, "X_I": 17.2162, "S_cat": 3.5659e-43,
    "S_an": 0.0052,
}  # fmt: skip
#: Ion and gas-phase steady state, same source.
STEADY_STATE_IONS_GAS_RJ2006 = {
    "S_va_ion": 0.0123, "S_bu_ion": 0.0140, "S_pro_ion": 0.0175, "S_ac_ion": 0.0890,
    "S_hco3_ion": 0.0857, "S_nh3": 0.0019, "S_gas_h2": 1.1032e-5, "S_gas_ch4": 1.6535,
    "S_gas_co2": 0.0135, "S_H_ion": 5.4562e-8, "pH": 7.2631,
}  # fmt: skip
#: Gas phase at that steady state, *derived* from the S_gas values above with the BSM2
#: gas equations (p_i = S_gas_i R T / COD-equivalent, p_h2o = 0.0557 bar at 35 degC,
#: q_gas = k_p (P_gas - P_atm) P_gas / P_atm with k_p = 5e4 m3 d^-1 bar^-1). Not copied
#: from the report, so that a transcription error cannot propagate into the gate.
_RT = 0.083145 * 308.15
RJ2006_GAS = {
    "p_ch4_bar": 1.6535 / 64 * _RT,  # 0.662
    "p_co2_bar": 0.0135 * _RT,  # 0.346
    "p_h2_bar": 1.1032e-5 / 16 * _RT,  # 1.8e-5
    "p_h2o_bar": 0.0557,
}
RJ2006_GAS["P_gas_bar"] = sum(RJ2006_GAS.values())  # 1.064
RJ2006_GAS["q_gas_m3_d"] = (
    5e4 * (RJ2006_GAS["P_gas_bar"] - 1.013) * RJ2006_GAS["P_gas_bar"] / 1.013
)  # ~2660
RJ2006_GAS["ch4_fraction_dry"] = RJ2006_GAS["p_ch4_bar"] / (
    RJ2006_GAS["P_gas_bar"] - 0.0557
)  # 0.657

PROBE1 = {"name": "P1_sludge_100d", "days": 100.0, "description":
          "100 d mesophilic sewage sludge, BSM2 steady-state influent, default parameters, "
          "initialised at the published steady state (ring test)."}  # fmt: skip
PROBE2 = {"name": "P2_olr_step_x3", "days": 20.0, "step_day": 10.0, "factor": 3.0,
          "description": "20 d; all 26 influent concentrations x3 from day 10 at constant "
          "Q (organic loading ~3.1 -> ~9.3 kg COD m^-3 d^-1)."}  # fmt: skip

# --- Plausibility gate ---------------------------------------------------------------

#: Physically plausible ranges for a stable mesophilic sewage-sludge digester. Sources
#: are listed in docs/adm1_comparison.md: BSM2 steady state (Rosen & Jeppsson 2006:
#: pH 7.26, q_gas 2955.7 m3/d, p_ch4 0.65 bar, VFA 133 g COD/m3 for its own feed); the
#: ADM1 STR (Batstone et al. 2002); Appels et al. 2008 (methanogenesis 6.5-8.0, optimum
#: 7.0-7.2; biogas 55-70 % CH4; stable digesters < ~1 g/L VFA).
PLAUSIBLE = {
    "pH": (6.5, 7.8),
    "ch4_fraction_dry": (0.55, 0.72),
    "q_gas_m3_d": (2200.0, 3300.0),  # BSM2 convention; R&J 2955.7 for a similar feed
    "vfa_total_gCOD_m3": (1.0, 1000.0),  # R&J 133; the STR feed is more buffered
}


def gate(final: dict[str, float]) -> dict[str, bool]:
    """Apply the plausibility ranges to the final-state summary of Probe 1."""
    return {k: (lo <= final.get(k, float("nan")) <= hi) for k, (lo, hi) in PLAUSIBLE.items()}


# --- Derived quantities ----------------------------------------------------------------

R_BAR_M3_KMOL_K = 0.083145


def derived(
    *, pH: float, p_h2: float, p_ch4: float, p_co2: float, p_h2o: float, q_gas: float,
    S_va: float, S_bu: float, S_pro: float, S_ac: float,
) -> dict[str, float]:  # fmt: skip
    """Compute the gated quantities from partial pressures (bar) and VFA (kg COD/m3).

    ``q_gas`` must be in the BSM2 convention (m^3/d at T_op, normalised to P_atm).
    """
    P_gas = p_h2 + p_ch4 + p_co2 + p_h2o
    return {
        "pH": pH,
        "P_gas_bar": P_gas,
        "p_ch4_bar": p_ch4,
        "p_co2_bar": p_co2,
        "p_h2_bar": p_h2,
        "ch4_fraction_wet": p_ch4 / P_gas,
        "ch4_fraction_dry": p_ch4 / (P_gas - p_h2o),
        "q_gas_m3_d": q_gas,
        "q_gas_STP_dry_m3_d": q_gas * (273.15 / T_OP_K) * (1 - p_h2o / P_gas),
        "vfa_total_gCOD_m3": 1000.0 * (S_va + S_bu + S_pro + S_ac),
        "S_ac_gCOD_m3": 1000.0 * S_ac,
        "S_pro_gCOD_m3": 1000.0 * S_pro,
    }


# --- Result record -------------------------------------------------------------------


@dataclass
class ProbeResult:
    """Outcome of one probe on one candidate."""

    name: str
    ok: bool
    wall_s: float
    wall_s_per_sim_day: float
    solver: str
    solver_settings: dict[str, Any]
    stats: dict[str, Any] = field(default_factory=dict)
    final: dict[str, float] = field(default_factory=dict)
    extremes: dict[str, float] = field(default_factory=dict)
    gate: dict[str, bool] = field(default_factory=dict)
    error: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class CandidateResult:
    """Everything recorded for one candidate implementation."""

    candidate: str
    source: str
    version: str
    python: str = field(default_factory=platform.python_version)
    platform: str = field(default_factory=platform.platform)
    licence: str = ""
    probes: list[ProbeResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def write(self) -> Path:
        """Write the record as JSON under ``results/`` and return the path."""
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"{self.candidate}.json"
        path.write_text(json.dumps(asdict(self), indent=2, default=float) + "\n")
        return path


class Stopwatch:
    """Minimal wall-clock timer usable as a context manager."""

    def __enter__(self) -> Stopwatch:
        """Start the clock."""
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        """Stop the clock and store the elapsed wall-clock seconds."""
        self.wall_s = time.perf_counter() - self.t0


def influent_vector(factor: float = 1.0) -> list[float]:
    """The R&J 2006 influent as a 26-vector, all concentrations scaled by ``factor``."""
    return [INFLUENT_RJ2006[k] * factor for k in STATE_NAMES]


def initial_vector() -> list[float]:
    """The R&J 2006 steady state as a 26-vector."""
    return [STEADY_STATE_RJ2006[k] for k in STATE_NAMES]
