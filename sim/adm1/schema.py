"""Typed schemas for the ADM1 core: parameters, plant, solver settings, inputs, results.

Every quantity carries an explicit unit in its field description (CLAUDE.md rule 6).
All models are frozen and reject unknown fields so that a parameter file with a typo
cannot silently fall back to a default.
"""

from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Canonical ordering of the 26 liquid-phase ADM1 state variables (Rosen & Jeppsson 2006).
LIQUID_STATE_NAMES: tuple[str, ...] = (
    "S_su", "S_aa", "S_fa", "S_va", "S_bu", "S_pro", "S_ac", "S_h2", "S_ch4", "S_IC",
    "S_IN", "S_I", "X_xc", "X_ch", "X_pr", "X_li", "X_su", "X_aa", "X_fa", "X_c4",
    "X_pro", "X_ac", "X_h2", "X_I", "S_cat", "S_an",
)  # fmt: skip
#: The three headspace states appended after the liquid states.
GAS_STATE_NAMES: tuple[str, ...] = ("S_gas_h2", "S_gas_ch4", "S_gas_co2")
#: Full state vector ordering used by :func:`sim.adm1.model.simulate`.
STATE_NAMES: tuple[str, ...] = LIQUID_STATE_NAMES + GAS_STATE_NAMES
N_LIQUID = len(LIQUID_STATE_NAMES)
N_GAS = len(GAS_STATE_NAMES)
N_STATES = len(STATE_NAMES)

_Frac = Annotated[float, Field(ge=0.0, le=1.0)]
_Pos = Annotated[float, Field(gt=0.0)]
_NonNeg = Annotated[float, Field(ge=0.0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StoichiometryParameters(_Frozen):
    """Product fractions, yields and elemental contents entering the Petersen matrix."""

    f_si_xc: _Frac = Field(description="Composite to soluble inerts, kg COD/kg COD")
    f_xi_xc: _Frac = Field(description="Composite to particulate inerts, kg COD/kg COD")
    f_ch_xc: _Frac = Field(description="Composite to carbohydrates, kg COD/kg COD")
    f_pr_xc: _Frac = Field(description="Composite to proteins, kg COD/kg COD")
    f_li_xc: _Frac = Field(description="Composite to lipids, kg COD/kg COD")
    f_fa_li: _Frac = Field(description="Lipids to LCFA (rest to sugars), kg COD/kg COD")
    f_h2_su: _Frac = Field(description="Sugar catabolism to H2, kg COD/kg COD")
    f_bu_su: _Frac = Field(description="Sugar catabolism to butyrate, kg COD/kg COD")
    f_pro_su: _Frac = Field(description="Sugar catabolism to propionate, kg COD/kg COD")
    f_ac_su: _Frac = Field(description="Sugar catabolism to acetate, kg COD/kg COD")
    f_h2_aa: _Frac = Field(description="Amino-acid catabolism to H2, kg COD/kg COD")
    f_va_aa: _Frac = Field(description="Amino-acid catabolism to valerate, kg COD/kg COD")
    f_bu_aa: _Frac = Field(description="Amino-acid catabolism to butyrate, kg COD/kg COD")
    f_pro_aa: _Frac = Field(description="Amino-acid catabolism to propionate, kg COD/kg COD")
    f_ac_aa: _Frac = Field(description="Amino-acid catabolism to acetate, kg COD/kg COD")
    f_h2_fa: _Frac = Field(description="LCFA catabolism to H2, kg COD/kg COD")
    f_ac_fa: _Frac = Field(description="LCFA catabolism to acetate, kg COD/kg COD")
    f_h2_va: _Frac = Field(description="Valerate catabolism to H2, kg COD/kg COD")
    f_pro_va: _Frac = Field(description="Valerate catabolism to propionate, kg COD/kg COD")
    f_ac_va: _Frac = Field(description="Valerate catabolism to acetate, kg COD/kg COD")
    f_h2_bu: _Frac = Field(description="Butyrate catabolism to H2, kg COD/kg COD")
    f_ac_bu: _Frac = Field(description="Butyrate catabolism to acetate, kg COD/kg COD")
    f_h2_pro: _Frac = Field(description="Propionate catabolism to H2, kg COD/kg COD")
    f_ac_pro: _Frac = Field(description="Propionate catabolism to acetate, kg COD/kg COD")
    Y_su: _Frac = Field(description="Biomass yield on sugars, kg COD_X/kg COD_S")
    Y_aa: _Frac = Field(description="Biomass yield on amino acids, kg COD_X/kg COD_S")
    Y_fa: _Frac = Field(description="Biomass yield on LCFA, kg COD_X/kg COD_S")
    Y_c4: _Frac = Field(description="Biomass yield on valerate/butyrate, kg COD_X/kg COD_S")
    Y_pro: _Frac = Field(description="Biomass yield on propionate, kg COD_X/kg COD_S")
    Y_ac: _Frac = Field(description="Biomass yield on acetate, kg COD_X/kg COD_S")
    Y_h2: _Frac = Field(description="Biomass yield on hydrogen, kg COD_X/kg COD_S")
    N_xc: _NonNeg = Field(description="N content of composites, kmol N/kg COD")
    N_I: _NonNeg = Field(description="N content of inerts (S_I, X_I), kmol N/kg COD")
    N_aa: _NonNeg = Field(description="N content of amino acids and proteins, kmol N/kg COD")
    N_bac: _NonNeg = Field(description="N content of biomass, kmol N/kg COD")
    C_xc: _NonNeg = Field(description="C content of composites, kmol C/kg COD")
    C_si: _NonNeg = Field(description="C content of soluble inerts, kmol C/kg COD")
    C_ch: _NonNeg = Field(description="C content of carbohydrates, kmol C/kg COD")
    C_pr: _NonNeg = Field(description="C content of proteins, kmol C/kg COD")
    C_li: _NonNeg = Field(description="C content of lipids, kmol C/kg COD")
    C_xi: _NonNeg = Field(description="C content of particulate inerts, kmol C/kg COD")
    C_su: _NonNeg = Field(description="C content of sugars, kmol C/kg COD")
    C_aa: _NonNeg = Field(description="C content of amino acids, kmol C/kg COD")
    C_fa: _NonNeg = Field(description="C content of LCFA, kmol C/kg COD")
    C_va: _NonNeg = Field(description="C content of valerate, kmol C/kg COD")
    C_bu: _NonNeg = Field(description="C content of butyrate, kmol C/kg COD")
    C_pro: _NonNeg = Field(description="C content of propionate, kmol C/kg COD")
    C_ac: _NonNeg = Field(description="C content of acetate, kmol C/kg COD")
    C_bac: _NonNeg = Field(description="C content of biomass, kmol C/kg COD")
    C_ch4: _NonNeg = Field(description="C content of methane, kmol C/kg COD")

    @model_validator(mode="after")
    def _fractions_close(self) -> StoichiometryParameters:
        """COD-conserving product fractions must sum to one (ADM1 STR Table 3.1)."""
        groups = {
            "composite": self.f_si_xc + self.f_xi_xc + self.f_ch_xc + self.f_pr_xc + self.f_li_xc,
            "sugars": self.f_h2_su + self.f_bu_su + self.f_pro_su + self.f_ac_su,
            "amino acids": self.f_h2_aa
            + self.f_va_aa
            + self.f_bu_aa
            + self.f_pro_aa
            + self.f_ac_aa,
            "LCFA": self.f_h2_fa + self.f_ac_fa,
            "valerate": self.f_h2_va + self.f_pro_va + self.f_ac_va,
            "butyrate": self.f_h2_bu + self.f_ac_bu,
            "propionate": self.f_h2_pro + self.f_ac_pro,
        }
        bad = {k: v for k, v in groups.items() if abs(v - 1.0) > 1e-9}
        if bad:
            raise ValueError(f"product fractions do not sum to 1: {bad}")
        return self


class KineticParameters(_Frozen):
    """Rate constants, half-saturation and inhibition constants, decay rates."""

    k_dis: _NonNeg = Field(description="Disintegration rate, 1/d")
    k_hyd_ch: _NonNeg = Field(description="Carbohydrate hydrolysis rate, 1/d")
    k_hyd_pr: _NonNeg = Field(description="Protein hydrolysis rate, 1/d")
    k_hyd_li: _NonNeg = Field(description="Lipid hydrolysis rate, 1/d")
    k_m_su: _NonNeg = Field(description="Max. specific uptake of sugars, kg COD_S/kg COD_X/d")
    K_S_su: _Pos = Field(description="Half-saturation for sugars, kg COD/m3")
    k_m_aa: _NonNeg = Field(description="Max. specific uptake of amino acids, kg COD_S/kg COD_X/d")
    K_S_aa: _Pos = Field(description="Half-saturation for amino acids, kg COD/m3")
    k_m_fa: _NonNeg = Field(description="Max. specific uptake of LCFA, kg COD_S/kg COD_X/d")
    K_S_fa: _Pos = Field(description="Half-saturation for LCFA, kg COD/m3")
    k_m_c4: _NonNeg = Field(description="Max. specific uptake of C4 acids, kg COD_S/kg COD_X/d")
    K_S_c4: _Pos = Field(description="Half-saturation for valerate/butyrate, kg COD/m3")
    k_m_pro: _NonNeg = Field(description="Max. specific uptake of propionate, kg COD_S/kg COD_X/d")
    K_S_pro: _Pos = Field(description="Half-saturation for propionate, kg COD/m3")
    k_m_ac: _NonNeg = Field(description="Max. specific uptake of acetate, kg COD_S/kg COD_X/d")
    K_S_ac: _Pos = Field(description="Half-saturation for acetate, kg COD/m3")
    k_m_h2: _NonNeg = Field(description="Max. specific uptake of hydrogen, kg COD_S/kg COD_X/d")
    K_S_h2: _Pos = Field(description="Half-saturation for hydrogen, kg COD/m3")
    K_S_IN: _Pos = Field(description="Inorganic-N limitation constant, kmol N/m3")
    K_I_h2_fa: _Pos = Field(description="H2 inhibition of LCFA uptake (50%), kg COD/m3")
    K_I_h2_c4: _Pos = Field(description="H2 inhibition of C4 uptake (50%), kg COD/m3")
    K_I_h2_pro: _Pos = Field(description="H2 inhibition of propionate uptake (50%), kg COD/m3")
    K_I_nh3: _Pos = Field(description="Free-ammonia inhibition of acetate uptake (50%), kmol N/m3")
    pH_UL_aa: float = Field(description="pH above which acidogens are uninhibited, pH units")
    pH_LL_aa: float = Field(description="pH below which acidogens are fully inhibited, pH units")
    pH_UL_ac: float = Field(description="Upper pH limit for acetoclastic methanogens, pH units")
    pH_LL_ac: float = Field(description="Lower pH limit for acetoclastic methanogens, pH units")
    pH_UL_h2: float = Field(description="Upper pH limit for hydrogenotrophs, pH units")
    pH_LL_h2: float = Field(description="Lower pH limit for hydrogenotrophs, pH units")
    k_dec_X_su: _NonNeg = Field(description="Decay rate of sugar degraders, 1/d")
    k_dec_X_aa: _NonNeg = Field(description="Decay rate of amino-acid degraders, 1/d")
    k_dec_X_fa: _NonNeg = Field(description="Decay rate of LCFA degraders, 1/d")
    k_dec_X_c4: _NonNeg = Field(description="Decay rate of C4 degraders, 1/d")
    k_dec_X_pro: _NonNeg = Field(description="Decay rate of propionate degraders, 1/d")
    k_dec_X_ac: _NonNeg = Field(description="Decay rate of acetate degraders, 1/d")
    k_dec_X_h2: _NonNeg = Field(description="Decay rate of hydrogen degraders, 1/d")
    eps_c4: _Pos = Field(
        description="Regularisation of the valerate/butyrate competition term, kg COD/m3"
    )

    @model_validator(mode="after")
    def _ph_limits_ordered(self) -> KineticParameters:
        """Each Hill inhibition needs pH_UL > pH_LL, otherwise its exponent is undefined."""
        for grp in ("aa", "ac", "h2"):
            if getattr(self, f"pH_UL_{grp}") <= getattr(self, f"pH_LL_{grp}"):
                raise ValueError(f"pH_UL_{grp} must exceed pH_LL_{grp}")
        return self


class PhysicoChemicalParameters(_Frozen):
    """Acid-base, Henry, vapour-pressure and gas-outflow parameters (BSM2 forms)."""

    R: _Pos = Field(description="Gas constant, bar m3/kmol/K")
    T_base: _Pos = Field(description="Reference temperature of the base constants, K")
    pK_w_base: float = Field(description="pK_w at T_base, -")
    pK_a_va: float = Field(description="pK_a of valeric acid (not T-corrected), -")
    pK_a_bu: float = Field(description="pK_a of butyric acid (not T-corrected), -")
    pK_a_pro: float = Field(description="pK_a of propionic acid (not T-corrected), -")
    pK_a_ac: float = Field(description="pK_a of acetic acid (not T-corrected), -")
    pK_a_co2_base: float = Field(description="pK_a of CO2/HCO3- at T_base, -")
    pK_a_IN_base: float = Field(description="pK_a of NH4+/NH3 at T_base, -")
    dH_K_w: float = Field(description="van 't Hoff enthalpy for K_w, J/mol")
    dH_K_a_co2: float = Field(description="van 't Hoff enthalpy for K_a,co2, J/mol")
    dH_K_a_IN: float = Field(description="van 't Hoff enthalpy for K_a,IN, J/mol")
    K_H_h2_base: _Pos = Field(description="Henry constant of H2 at T_base, kmol/m3/bar")
    K_H_ch4_base: _Pos = Field(description="Henry constant of CH4 at T_base, kmol/m3/bar")
    K_H_co2_base: _Pos = Field(description="Henry constant of CO2 at T_base, kmol/m3/bar")
    dH_K_H_h2: float = Field(description="van 't Hoff enthalpy for K_H,h2, J/mol")
    dH_K_H_ch4: float = Field(description="van 't Hoff enthalpy for K_H,ch4, J/mol")
    dH_K_H_co2: float = Field(description="van 't Hoff enthalpy for K_H,co2, J/mol")
    p_h2o_base: _Pos = Field(description="Water vapour pressure at T_base, bar")
    h2o_vapour_coefficient: float = Field(
        description="Clausius-Clapeyron coefficient: p_h2o = p_h2o_base exp(c (1/T_base - 1/T)), K"
    )
    P_atm: _Pos = Field(description="Atmospheric pressure, bar")
    k_La: _NonNeg = Field(description="Gas-liquid transfer coefficient, 1/d")
    k_p: _NonNeg = Field(description="Headspace outflow coefficient, m3/d/bar")


class ADM1Parameters(_Frozen):
    """The complete ADM1 parameter set."""

    stoichiometry: StoichiometryParameters
    kinetics: KineticParameters
    physchem: PhysicoChemicalParameters

    def namespace(self) -> dict[str, float]:
        """Flat ``{name: value}`` view used to evaluate Petersen-matrix expressions."""
        out: dict[str, float] = {}
        for group in (self.stoichiometry, self.kinetics, self.physchem):
            for name, value in group.model_dump().items():
                if name in out:
                    raise ValueError(f"duplicate parameter name across groups: {name}")
                out[name] = float(value)
        return out


class PlantGeometry(_Frozen):
    """Reactor volumes and operating temperature."""

    V_liq: _Pos = Field(description="Liquid volume, m3")
    V_gas: _Pos = Field(description="Headspace volume, m3")
    T_op: _Pos = Field(description="Operating temperature, K")


class PHSolverConfig(_Frozen):
    """Settings for the bracketed root-find on the charge balance."""

    bracket_pH: tuple[float, float] = Field(description="Search bracket in pH units")
    xtol_pH: _Pos = Field(description="Absolute tolerance on the root, pH units")
    rtol: _Pos = Field(description="Relative tolerance passed to brentq, -")
    maxiter: Annotated[int, Field(gt=0)] = Field(description="Maximum brentq iterations")

    @field_validator("bracket_pH")
    @classmethod
    def _ordered(cls, v: tuple[float, float]) -> tuple[float, float]:
        if v[0] >= v[1]:
            raise ValueError("bracket_pH must be (low, high) with low < high")
        return v


class SolverConfig(_Frozen):
    """ODE-solver settings; values come from ``configs/adm1/solver.yaml``."""

    method: Literal["BDF", "Radau", "LSODA"] = Field(description="solve_ivp method")
    rtol: _Pos = Field(description="Relative tolerance, -")
    atol: _Pos = Field(description="Absolute tolerance, state units")
    max_step: _Pos = Field(description="Maximum internal step, d (inf = unlimited)")
    clip_negative_states_in_rates: bool = Field(
        description="If true, rate expressions see max(y, 0); transport terms always see y"
    )
    pH_solver: PHSolverConfig


class Influent(_Frozen):
    """A time series of influent concentrations and flow.

    Between samples the series is either held constant (``hold``: sample-and-hold, the
    BSM2 convention for its 15-minute files) or linearly interpolated (``linear``). With
    ``hold`` the integrator is restarted at every breakpoint so the discontinuity is
    handled exactly; with ``linear`` one continuous integration is used with the internal
    step capped at the sample spacing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    t: np.ndarray = Field(description="Sample times, d, strictly increasing")
    concentrations: np.ndarray = Field(
        description="Shape (n, 26): liquid-state influent concentrations in STATE order"
    )
    q: np.ndarray = Field(description="Shape (n,): influent flow, m3/d")
    interpolation: Literal["hold", "linear"] = Field(
        default="hold", description="Sample-and-hold or linear interpolation between samples"
    )

    @model_validator(mode="after")
    def _shapes(self) -> Influent:
        t = np.asarray(self.t, dtype=float)
        c = np.asarray(self.concentrations, dtype=float)
        q = np.asarray(self.q, dtype=float)
        if t.ndim != 1 or t.size == 0:
            raise ValueError("t must be a non-empty 1-D array")
        if np.any(np.diff(t) <= 0):
            raise ValueError("t must be strictly increasing")
        if c.shape != (t.size, N_LIQUID):
            raise ValueError(
                f"concentrations must have shape ({t.size}, {N_LIQUID}), got {c.shape}"
            )
        if q.shape != (t.size,):
            raise ValueError(f"q must have shape ({t.size},), got {q.shape}")
        if not (np.all(np.isfinite(c)) and np.all(np.isfinite(q)) and np.all(np.isfinite(t))):
            raise ValueError("influent contains non-finite values")
        if np.any(q < 0):
            raise ValueError("influent flow must be non-negative")
        object.__setattr__(self, "t", t)
        object.__setattr__(self, "concentrations", c)
        object.__setattr__(self, "q", q)
        return self

    @classmethod
    def constant(cls, concentrations: np.ndarray, q: float, t0: float = 0.0) -> Influent:
        """A constant influent, valid for all times (a single-sample series)."""
        c = np.asarray(concentrations, dtype=float).reshape(1, -1)
        return cls(t=np.array([t0]), concentrations=c, q=np.array([float(q)]))


class SolverStats(_Frozen):
    """Integrator effort, summed over all segments of a run."""

    nfev: int = Field(description="Right-hand-side evaluations")
    njev: int = Field(description="Jacobian evaluations")
    nlu: int = Field(description="LU decompositions")
    n_steps: int = Field(description="Accepted internal steps")
    n_segments: int = Field(description="Integrator restarts (influent breakpoints + 1)")
    min_step: float = Field(description="Smallest accepted internal step, d")
    max_step: float = Field(description="Largest accepted internal step, d")
    wall_s: float = Field(description="Wall-clock time of the integration, s")


class SimulationResult(_Frozen):
    """Output of :func:`sim.adm1.model.simulate`.

    Arrays are indexed ``[state, time]`` for ``y`` and ``[time]`` for derived series.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    t: np.ndarray = Field(description="Output times, d")
    y: np.ndarray = Field(description="Shape (29, n): state trajectory in STATE_NAMES order")
    pH: np.ndarray = Field(description="pH from the algebraic charge balance, -")
    S_h: np.ndarray = Field(description="Proton concentration, kmol/m3")
    S_va_ion: np.ndarray = Field(description="Valerate anion, kg COD/m3")
    S_bu_ion: np.ndarray = Field(description="Butyrate anion, kg COD/m3")
    S_pro_ion: np.ndarray = Field(description="Propionate anion, kg COD/m3")
    S_ac_ion: np.ndarray = Field(description="Acetate anion, kg COD/m3")
    S_hco3_ion: np.ndarray = Field(description="Bicarbonate, kmol C/m3")
    S_co2: np.ndarray = Field(description="Free dissolved CO2, kmol C/m3")
    S_nh3: np.ndarray = Field(description="Free ammonia, kmol N/m3")
    S_nh4_ion: np.ndarray = Field(description="Ammonium, kmol N/m3")
    p_h2: np.ndarray = Field(description="Headspace H2 partial pressure, bar")
    p_ch4: np.ndarray = Field(description="Headspace CH4 partial pressure, bar")
    p_co2: np.ndarray = Field(description="Headspace CO2 partial pressure, bar")
    p_h2o: np.ndarray = Field(description="Water vapour pressure at T_op, bar")
    P_gas: np.ndarray = Field(description="Total headspace pressure, bar")
    q_gas: np.ndarray = Field(
        description="Biogas outflow, m3/d at T_op normalised to P_atm (BSM2 convention)"
    )
    q_gas_stp_dry: np.ndarray = Field(description="Dry biogas outflow at 0 degC and 1 atm, m3/d")
    success: bool = Field(description="Every integrator segment reported success")
    message: str = Field(description="Last integrator message")
    stats: SolverStats

    def final_state(self) -> dict[str, float]:
        """The last state vector as ``{name: value}``."""
        return {n: float(v) for n, v in zip(STATE_NAMES, self.y[:, -1], strict=True)}
