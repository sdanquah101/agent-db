"""Truth-model extensions on top of the standard ADM1 core (proposal §6.1).

An extension adds liquid-phase components, Petersen rows and parameters
(``configs/adm1/extensions.yaml``) and/or switches on extended speciation
(:mod:`sim.adm1.physchem_ext`). :func:`compile_extended` appends them to a compiled
standard model without modifying it; :func:`simulate_extended` integrates the extended
state with the same segment loop and gas exchange as :func:`sim.adm1.model.simulate`.

State layout: the 29 standard states in :data:`~sim.adm1.schema.STATE_NAMES` order,
followed by the extension components in the order they are enabled. Extension rows are
evaluated against the base parameter namespace plus the extension parameters; rates
are code (:data:`EXTENSION_RATES`), matching the base model's "matrix is data, rates are
code" convention.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from sim.adm1 import physchem, physchem_ext
from sim.adm1.model import CompiledModel, compile_model, gas_exchange, integrate
from sim.adm1.petersen import Component, PetersenMatrix, Process, evaluate_expression
from sim.adm1.rates import (
    PROCESS_NAMES,
    inhibition_noncompetitive,
    inhibition_ph_hill,
    limitation_secondary_substrate,
    monod,
    process_rates,
)
from sim.adm1.schema import (
    N_LIQUID,
    N_STATES,
    STATE_NAMES,
    ADM1Parameters,
    Influent,
    KineticParameters,
    PlantGeometry,
    SolverConfig,
    SolverStats,
)

_IDX = {name: i for i, name in enumerate(STATE_NAMES)}
nan = math.nan

DERIVED_UNITS: Mapping[str, str] = MappingProxyType(
    {
        "pH": "- (-log10 of the proton activity; concentration when ideal)",
        "S_h": "kmol/m3 (proton concentration)",
        "S_va_ion": "kg COD/m3",
        "S_bu_ion": "kg COD/m3",
        "S_pro_ion": "kg COD/m3",
        "S_ac_ion": "kg COD/m3",
        "S_hco3_ion": "kmol C/m3",
        "S_co3_ion": "kmol C/m3 (diagnostic estimate unless the carbonate switch is on)",
        "S_co2": "kmol C/m3 (free CO2)",
        "S_nh3": "kmol N/m3",
        "S_nh4_ion": "kmol N/m3",
        "ionic_strength": "mol/L (0.5 sum c z^2 over the charge-balance species)",
        "gamma1": "- (Davies activity coefficient, |z| = 1; 1 when the correction is off)",
        "p_h2": "bar",
        "p_ch4": "bar",
        "p_co2": "bar",
        "p_h2o": "bar",
        "P_gas": "bar (headspace total)",
        "q_gas": "m3/d at T_op normalised to P_atm (BSM2 convention)",
        "q_gas_stp_dry": "m3/d at 0 C and 1 atm, water vapour removed",
        "q_ch4_stp": "m3 CH4/d at 0 C and 1 atm, wet-gas fraction basis",
    }
)
"""Units of every entry of :attr:`ExtendedResult.derived` (CLAUDE.md rule 6)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExtensionParameter(_Frozen):
    """A parameter of an extension, with its unit."""

    value: float
    unit: str
    description: str = ""


class SpeciationSwitches(_Frozen):
    """Which extended-speciation terms an extension turns on."""

    ionic_strength: bool = False
    carbonate: bool = False


class ExtensionSpec(_Frozen):
    """One entry of ``extensions.yaml``."""

    description: str
    components: tuple[Component, ...] = ()
    processes: tuple[Process, ...] = ()
    parameters: dict[str, ExtensionParameter] = Field(default_factory=dict)
    speciation: SpeciationSwitches = SpeciationSwitches()


class ExtensionsConfig(_Frozen):
    """The parsed extensions file (loaded by :func:`sim.adm1.defaults.load_extensions`)."""

    version: int
    shared_parameters: dict[str, ExtensionParameter] = Field(default_factory=dict)
    """Constants used by more than one extension (always loaded, overridable)."""
    extensions: dict[str, ExtensionSpec]


# --------------------------------------------------------------------------- rates


@dataclass(frozen=True)
class RateContext:
    """What an extension rate expression may see at one state."""

    y: Mapping[str, float]
    """All states by name (clipped at zero if the solver config says so)."""
    S_h: float
    """Proton activity (concentration when ideal), kmol/m3."""
    sp: physchem_ext.ExtendedSpeciation
    kin: KineticParameters
    ext: Mapping[str, float]
    """Extension parameters by name."""
    eq: physchem_ext.Equilibria


RateFunction = Callable[[RateContext], float]


def _rate_uptake_acetate_sao(c: RateContext) -> float:
    """SAO acetate uptake: Monod, pH (acidogen form), IN limitation, own NH3 and H2 terms.

    Free-ammonia inhibition uses the SAO-specific ``K_I_nh3_sao`` (weaker than the
    acetoclastic ``K_I_nh3``), not the acetoclastic function.
    """
    return (
        c.ext["k_m_sao"]
        * monod(c.y["S_ac"], c.ext["K_S_sao"])
        * c.y["X_sao"]
        * inhibition_ph_hill(c.S_h, c.kin.pH_UL_aa, c.kin.pH_LL_aa)
        * limitation_secondary_substrate(c.y["S_IN"], c.kin.K_S_IN)
        * inhibition_noncompetitive(c.sp.S_nh3, c.ext["K_I_nh3_sao"])
        * inhibition_noncompetitive(c.y["S_h2"], c.ext["K_I_h2_sao"])
    )


def _rate_decay_X_sao(c: RateContext) -> float:
    return c.ext["k_dec_X_sao"] * c.y["X_sao"]


def _rate_precipitation_caco3(c: RateContext) -> float:
    return physchem_ext.precipitation_rate(
        c.y["S_ca"],
        c.sp.S_co3_ion,
        c.eq.K_sp_caco3,
        c.sp.gamma2,
        c.ext["k_prec_caco3"],
        c.ext["n_prec_caco3"],
    )


EXTENSION_RATES: Mapping[str, RateFunction] = MappingProxyType(
    {
        "uptake_acetate_sao": _rate_uptake_acetate_sao,
        "decay_X_sao": _rate_decay_X_sao,
        "precipitation_caco3": _rate_precipitation_caco3,
    }
)
"""Rate code for every extension process the config may name (read-only)."""


# ------------------------------------------------------------------- compilation


@dataclass(frozen=True)
class ExtendedModel:
    """A compiled standard model plus the enabled extensions."""

    base: CompiledModel
    enabled: tuple[str, ...]
    state_names: tuple[str, ...]
    """29 standard states then the extension components."""
    components: tuple[Component, ...]
    """All liquid components: 26 standard then extension components."""
    processes: tuple[Process, ...]
    """Extension processes, in rate-vector order after the 19 standard ones."""
    nu: np.ndarray
    """Stoichiometry, ``(26 + n_ext_components, 19 + n_ext_processes)``."""
    ext_params: dict[str, float]
    options: physchem_ext.SpeciationOptions

    @property
    def n_ext(self) -> int:
        """Number of extension components (= extra states)."""
        return len(self.state_names) - N_STATES

    @property
    def n_states(self) -> int:
        """Length of the extended state vector."""
        return len(self.state_names)

    def index(self, name: str) -> int:
        """Position of a state in the extended vector."""
        return self.state_names.index(name)


def _content(value: str | float, ns: Mapping[str, float]) -> float:
    return float(ns[value]) if isinstance(value, str) else float(value)


def compile_extended(
    params: ADM1Parameters,
    plant: PlantGeometry,
    matrix: PetersenMatrix,
    solver: SolverConfig,
    config: ExtensionsConfig,
    enabled: Sequence[str],
    overrides: Mapping[str, float] | None = None,
) -> ExtendedModel:
    """Compile the standard model and append the enabled extensions.

    Args:
        params: Standard ADM1 parameters.
        plant: Volumes and temperature.
        matrix: Standard Petersen matrix.
        solver: Solver settings.
        config: Parsed ``extensions.yaml``.
        enabled: Extension names to enable, in state order.
        overrides: Extension-parameter overrides (``name -> value``); base parameters
            are changed through ``params`` instead.

    Returns:
        The extended model.

    Raises:
        ValueError: On unknown extension, duplicate component or parameter names,
            unknown rate code, or an override of a parameter that is not enabled.
    """
    unknown = set(enabled) - set(config.extensions)
    if unknown:
        raise ValueError(
            f"unknown extensions {sorted(unknown)}; known: {sorted(config.extensions)}"
        )
    if len(set(enabled)) != len(enabled):
        raise ValueError("extensions must not be repeated")

    base = compile_model(params, plant, matrix, solver)
    ns = params.namespace()
    components = list(matrix.components)
    processes: list[Process] = []
    ext_params: dict[str, float] = {}
    for pname, par in config.shared_parameters.items():
        if pname in ns:
            raise ValueError(f"shared parameter {pname!r} redefines a base parameter")
        ext_params[pname] = par.value
    ionic = carbonate = False
    for name in enabled:
        spec = config.extensions[name]
        for comp in spec.components:
            if comp.name in {c.name for c in components} or comp.name in _IDX:
                raise ValueError(f"extension {name!r} redefines component {comp.name!r}")
            components.append(comp)
        for proc in spec.processes:
            if proc.name in PROCESS_NAMES or proc.name in {p.name for p in processes}:
                raise ValueError(f"extension {name!r} redefines process {proc.name!r}")
            if proc.name not in EXTENSION_RATES:
                raise ValueError(f"no rate code for extension process {proc.name!r}")
            processes.append(proc)
        for pname, par in spec.parameters.items():
            if pname in ns or pname in ext_params:
                raise ValueError(f"extension {name!r} redefines parameter {pname!r}")
            ext_params[pname] = par.value
        ionic = ionic or spec.speciation.ionic_strength
        carbonate = carbonate or spec.speciation.carbonate
    for pname, value in (overrides or {}).items():
        if pname not in ext_params:
            raise ValueError(f"override {pname!r} is not a parameter of an enabled extension")
        ext_params[pname] = float(value)

    full_ns = {**ns, **ext_params}
    n_comp, n_proc = len(components), len(PROCESS_NAMES) + len(processes)
    nu = np.zeros((n_comp, n_proc))
    nu[:N_LIQUID, : len(PROCESS_NAMES)] = base.nu
    col = {c.name: i for i, c in enumerate(components)}
    for j, proc in enumerate(processes, start=len(PROCESS_NAMES)):
        for comp, expr in proc.stoichiometry.items():
            if comp not in col:
                raise ValueError(f"process {proc.name!r} references unknown component {comp!r}")
            nu[col[comp], j] = evaluate_expression(expr, full_ns)

    if "pK_a2_co2" not in ext_params:
        raise ValueError("extensions config must declare the shared parameter 'pK_a2_co2'")
    calcite = any(p.name == "precipitation_caco3" for p in processes)
    if calcite and "pK_sp_caco3" not in ext_params:
        raise ValueError("the calcite extension must declare 'pK_sp_caco3'")
    if ionic and not {"davies_A", "davies_b", "I_max"} <= ext_params.keys():
        raise ValueError("the ionic-strength extension must declare davies_A, davies_b and I_max")
    nu.setflags(write=False)
    options = physchem_ext.SpeciationOptions(
        ionic_strength=ionic,
        carbonate=carbonate,
        # the configured A is the 25 C value; scale it to the operating temperature.
        # Values of switched-off terms are NaN so that an accidental use is loud.
        davies_A=physchem_ext.davies_A_at(ext_params["davies_A"], plant.T_op) if ionic else nan,
        davies_b=ext_params["davies_b"] if ionic else nan,
        I_max=ext_params["I_max"] if ionic else nan,
        pK_a2_co2=ext_params["pK_a2_co2"],
        pK_sp_caco3=ext_params["pK_sp_caco3"] if calcite else nan,
    )
    ext_names = tuple(c.name for c in components[N_LIQUID:])
    return ExtendedModel(
        base=base,
        enabled=tuple(enabled),
        state_names=STATE_NAMES + ext_names,
        components=tuple(components),
        processes=tuple(processes),
        nu=nu,
        ext_params=ext_params,
        options=options,
    )


def conservation_residuals(model: ExtendedModel) -> dict[str, np.ndarray]:
    """Per-process COD, C, N and charge residuals of the extended matrix.

    Same convention as :func:`sim.adm1.petersen.conservation_residuals`. The calcite row
    shows a charge residual of -2: S_IC is an uncharged *total* in the matrix (its split
    into CO2 / HCO3- / CO3 2- is algebraic), so removing one CO3 2- with one Ca2+ counts
    as +2 leaving and 0 leaving. The balance closes after speciation: the carbonate that
    left carried -2, which is exactly the +2 of the calcium. See ``extensions.yaml``.
    """
    ns = {**model.base.params.namespace(), **model.ext_params}
    cod = np.array([c.cod for c in model.components])
    carbon = np.array([_content(c.carbon, ns) for c in model.components])
    nitrogen = np.array([_content(c.nitrogen, ns) for c in model.components])
    charge = np.array([c.charge for c in model.components])
    return {
        "COD": cod @ model.nu,
        "C": carbon @ model.nu,
        "N": nitrogen @ model.nu,
        "charge": charge @ model.nu,
    }


# ---------------------------------------------------------------- right-hand side


def _speciation(yr: np.ndarray, model: ExtendedModel) -> physchem_ext.ExtendedSpeciation:
    g = _IDX
    S_ca = yr[model.index("S_ca")] if "S_ca" in model.state_names else 0.0
    return physchem_ext.speciate_extended(
        yr[g["S_va"]],
        yr[g["S_bu"]],
        yr[g["S_pro"]],
        yr[g["S_ac"]],
        yr[g["S_IC"]],
        yr[g["S_IN"]],
        yr[g["S_cat"]],
        yr[g["S_an"]],
        S_ca,
        model.base.k,
        model.base.solver.pH_solver,
        model.options,
    )


def rhs_extended(
    t: float,
    y: np.ndarray,
    u_conc: np.ndarray,
    u_q: float,
    model: ExtendedModel,
    u_ext: np.ndarray,
) -> np.ndarray:
    """Time derivative of the extended state vector.

    Args:
        t: Time, d (unused).
        y: Extended state, ``model.state_names`` order.
        u_conc: Influent concentrations of the 26 standard liquid states.
        u_q: Influent flow, m3/d.
        model: Extended model.
        u_ext: Influent concentrations of the extension components (constant).

    Returns:
        ``dy/dt``.
    """
    del t
    base, plant = model.base, model.base.plant
    yr = np.maximum(y, 0.0) if base.solver.clip_negative_states_in_rates else y
    sp = _speciation(yr, model)
    S_h_eff = sp.S_h * sp.gamma1  # proton activity; equals concentration when ideal

    rho = np.empty(model.nu.shape[1])
    rho[: len(PROCESS_NAMES)] = process_rates(yr, S_h_eff, sp.S_nh3, base.params.kinetics)
    if model.processes:
        named = dict(zip(model.state_names, yr, strict=True))
        eq = physchem_ext.equilibria(base.k, model.options, sp.gamma1, sp.gamma2)
        ctx = RateContext(named, S_h_eff, sp, base.params.kinetics, model.ext_params, eq)
        for j, proc in enumerate(model.processes, start=len(PROCESS_NAMES)):
            rho[j] = EXTENSION_RATES[proc.name](ctx)
    reaction = model.nu @ rho

    dy = np.empty(model.n_states)
    dy[:N_LIQUID] = (u_q / plant.V_liq) * (u_conc - y[:N_LIQUID]) + reaction[:N_LIQUID]
    dy[N_STATES:] = (u_q / plant.V_liq) * (u_ext - y[N_STATES:]) + reaction[N_LIQUID:]
    rho_T, dy_gas = gas_exchange(yr, sp.S_co2, base)
    for i, tr in enumerate(base.transfers):
        dy[tr.liquid] -= rho_T[i]
        dy[tr.gas] = dy_gas[i]
    return dy


# ---------------------------------------------------------------------- simulate


@dataclass(frozen=True)
class ExtendedResult:
    """Trajectory of the extended model with derived quantities."""

    t: np.ndarray
    """Output times, d."""
    y: np.ndarray
    """``(n_states, n_times)`` in ``state_names`` order; units as in the component list
    (kg COD/m3, kmol C/m3 or kmol N/m3 per state)."""
    state_names: tuple[str, ...]
    derived: dict[str, np.ndarray]
    """Per-time derived quantities; units in :data:`DERIVED_UNITS` / :attr:`units`."""
    success: bool
    message: str
    stats: SolverStats

    @property
    def units(self) -> Mapping[str, str]:
        """Unit of every ``derived`` entry."""
        return DERIVED_UNITS

    def state(self, name: str) -> np.ndarray:
        """Trajectory of one state by name."""
        return self.y[self.state_names.index(name)]

    def final(self) -> dict[str, float]:
        """Final value of every derived quantity."""
        return {k: float(v[-1]) for k, v in self.derived.items()}


def derived_extended(y: np.ndarray, model: ExtendedModel) -> dict[str, np.ndarray]:
    """Derived quantities per column: activity-based pH, speciation, ionic strength, gas."""
    base = model.base
    pc, plant, k = base.params.physchem, base.plant, base.k
    yr = np.maximum(y, 0.0) if base.solver.clip_negative_states_in_rates else y
    names = tuple(DERIVED_UNITS)
    n = y.shape[1]
    out = {name: np.empty(n) for name in names}
    g_h2, g_ch4, g_co2 = (_IDX[n_] for n_ in ("S_gas_h2", "S_gas_ch4", "S_gas_co2"))
    for j in range(n):
        col = yr[:, j]
        sp = _speciation(col, model)
        gas = physchem.gas_phase(col[g_h2], col[g_ch4], col[g_co2], plant.T_op, pc, k.p_h2o)
        for name in names[:13]:
            out[name][j] = getattr(sp, name)
        for name in ("p_h2", "p_ch4", "p_co2", "p_h2o", "P_gas", "q_gas"):
            out[name][j] = getattr(gas, name)
        out["q_gas_stp_dry"][j] = physchem.q_gas_stp_dry(
            gas.q_gas, gas.P_gas, gas.p_h2o, plant.T_op
        )
        out["q_ch4_stp"][j] = gas.q_gas * (273.15 / plant.T_op) * (gas.p_ch4 / gas.P_gas)
    return out


def extended_state(
    model: ExtendedModel, base_y0: np.ndarray, ext: Mapping[str, float]
) -> np.ndarray:
    """Append extension initial values (missing = 0) to a 29-state vector."""
    y0 = np.zeros(model.n_states)
    y0[:N_STATES] = np.asarray(base_y0, dtype=float)
    for name, value in ext.items():
        if name not in model.state_names[N_STATES:]:
            raise ValueError(f"{name!r} is not an extension state of this model")
        y0[model.index(name)] = float(value)
    return y0


def simulate_extended(
    *,
    y0: np.ndarray,
    influent: Influent,
    model: ExtendedModel,
    t_span: tuple[float, float],
    t_eval: np.ndarray | None = None,
    u_ext: Mapping[str, float] | None = None,
) -> ExtendedResult:
    """Integrate the extended model (same influent handling as :func:`sim.adm1.simulate`).

    Args:
        y0: Extended initial state, ``model.state_names`` order.
        influent: Influent series for the 26 standard liquid states.
        model: Compiled extended model.
        t_span: ``(t0, t1)`` in days.
        t_eval: Output times or ``None`` for every accepted step.
        u_ext: Constant influent concentrations of extension components (missing = 0).

    Returns:
        The trajectory with derived quantities.
    """
    y0 = np.asarray(y0, dtype=float)
    if y0.shape != (model.n_states,):
        raise ValueError(f"y0 must have shape ({model.n_states},), got {y0.shape}")
    u_ext_vec = np.zeros(model.n_ext)
    for name, value in (u_ext or {}).items():
        if name not in model.state_names[N_STATES:]:
            raise ValueError(f"{name!r} is not an extension state of this model")
        u_ext_vec[model.index(name) - N_STATES] = float(value)

    def fun(t: float, y: np.ndarray, c: np.ndarray, q: float) -> np.ndarray:
        return rhs_extended(t, y, c, q, model, u_ext_vec)

    traj = integrate(
        y0=y0, influent=influent, solver=model.base.solver, fun=fun, t_span=t_span, t_eval=t_eval
    )
    return ExtendedResult(
        t=traj.t,
        y=traj.y,
        state_names=model.state_names,
        derived=derived_extended(traj.y, model),
        success=traj.success,
        message=traj.message,
        stats=traj.stats,
    )
