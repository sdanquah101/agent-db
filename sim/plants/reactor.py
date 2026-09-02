"""Imperfectly mixed digester: active zone, stagnant zone and short-circuit bypass.

The hidden mixing structure (proposal §6.1 "residence-time distribution to emulate
imperfect mixing") is the classical compartment model of a non-ideal stirred tank
(Levenspiel; used for full-scale digesters by Monteith & Stephenson 1978 and Capela et
al. 2009):

* a well-mixed **active zone** of volume ``V_main = V_true (1 - phi)``;
* a **stagnant zone** of volume ``V_stag = V_true phi`` that exchanges liquid with the
  active zone at ``Q_ex = k_ex V_stag`` (no inflow, no outflow, full biochemistry, gas
  transfer to the shared headspace);
* a **bypass**: a fraction ``beta`` of the influent short-circuits to the effluent
  without entering either zone.

With ``beta = phi = 0`` the state vector is the extended model's own and the right-hand
side is :func:`sim.adm1.extensions.rhs_extended` unchanged, so the ideal CSTR is
reproduced bit for bit (tested against :func:`sim.adm1.simulate`).

Everything is a pure function of its arguments: no file I/O, no module-level mutable
state, no randomness. Loading configuration is :mod:`sim.plants.defaults`' job; drawing
the hidden truth is :mod:`sim.plants.sampling`'s.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from sim.adm1 import physchem
from sim.adm1.extensions import (
    ExtendedModel,
    ExtendedResult,
    ExtensionsConfig,
    compile_extended,
    derived_extended,
    extended_state,
    rhs_extended,
)
from sim.adm1.model import integrate
from sim.adm1.petersen import PetersenMatrix
from sim.adm1.schema import (
    N_GAS,
    N_STATES,
    ADM1Parameters,
    Influent,
    PlantGeometry,
    SolverConfig,
)
from sim.plants.schema import MixingTruth, PlantDeclared, PlantTruth

_GAS_SLICE = slice(N_STATES - N_GAS, N_STATES)


def apply_parameter_overrides(
    params: ADM1Parameters, overrides: Mapping[str, float]
) -> ADM1Parameters:
    """Return a parameter set with ``'group.name' -> value`` overrides applied.

    Raises:
        ValueError: On a key that is not ``group.name`` or names an unknown parameter.
    """
    if not overrides:
        return params
    groups: dict[str, dict[str, float]] = {}
    for key, value in overrides.items():
        group, _, name = key.partition(".")
        if group not in ("stoichiometry", "kinetics", "physchem") or not name:
            raise ValueError(f"override key must be 'group.name', got {key!r}")
        if name not in type(getattr(params, group)).model_fields:
            raise ValueError(f"unknown parameter {name!r} in group {group!r}")
        groups.setdefault(group, {})[name] = float(value)
    return params.model_copy(
        update={g: getattr(params, g).model_copy(update=vals) for g, vals in groups.items()}
    )


@dataclass(frozen=True)
class ReactorModel:
    """A compiled plant: the extended model on each zone plus the mixing structure."""

    main: ExtendedModel
    """Extended model compiled on the active-zone volume."""
    stagnant: ExtendedModel | None
    """Extended model compiled on the stagnant-zone volume; ``None`` when ideal."""
    mixing: MixingTruth
    V_main: float
    """Active-zone liquid volume, m3."""
    V_stag: float
    """Stagnant-zone liquid volume, m3 (0 when ideal)."""
    V_gas: float
    """Headspace volume, m3."""

    @property
    def ideal(self) -> bool:
        """True when the reactor is the exact CSTR (no bypass, no stagnant zone)."""
        return self.stagnant is None

    @property
    def n_liquid(self) -> int:
        """Number of liquid states of one zone (26 standard + extension components)."""
        return self.main.n_states - N_GAS

    @property
    def n_states(self) -> int:
        """Length of the reactor state vector."""
        return self.main.n_states + (0 if self.ideal else self.n_liquid)

    @property
    def state_names(self) -> tuple[str, ...]:
        """Active-zone states, then stagnant-zone liquid states suffixed ``_stag``."""
        names = self.main.state_names
        if self.ideal:
            return names
        liq = names[: N_STATES - N_GAS] + names[N_STATES:]
        return names + tuple(f"{n}_stag" for n in liq)

    def split(self, y: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
        """``(active-zone state, stagnant-zone liquid state or None)``."""
        n = self.main.n_states
        return y[:n], (None if self.ideal else y[n:])

    def liquid_of(self, y_main: np.ndarray) -> np.ndarray:
        """The liquid states of an active-zone vector (standard then extension)."""
        return np.concatenate((y_main[: N_STATES - N_GAS], y_main[N_STATES:]))


def compile_reactor(
    declared: PlantDeclared,
    truth: PlantTruth,
    params: ADM1Parameters,
    matrix: PetersenMatrix,
    solver: SolverConfig,
    extensions: ExtensionsConfig,
    *,
    mixing: MixingTruth | None = None,
    V_liq: float | None = None,
) -> ReactorModel:
    """Compile the truth model of a plant under its hidden configuration.

    Args:
        declared: The declared plant (temperature, headspace, extensions, overrides).
        truth: The hidden configuration (true volume, mixing).
        params: Base ADM1 parameters; the plant's ``parameter_overrides`` are applied.
        matrix: Standard Petersen matrix.
        solver: Solver settings.
        extensions: Parsed ``extensions.yaml``.
        mixing: Override the mixing structure (e.g. :meth:`MixingTruth.cstr` for a
            Level-0 scenario where the fitted model is right); default ``truth.mixing``.
        V_liq: Override the liquid volume, m3 (e.g. the declared volume to build the
            operator's model); default ``truth.V_liq_true``.

    Returns:
        The compiled reactor.
    """
    mixing = truth.mixing if mixing is None else mixing
    V_true = truth.V_liq_true if V_liq is None else float(V_liq)
    p = apply_parameter_overrides(params, declared.parameter_overrides)
    ext_over = declared.extension_overrides or None
    V_stag = V_true * mixing.stagnant_fraction
    V_main = V_true - V_stag
    main = compile_extended(
        p,
        PlantGeometry(V_liq=V_main, V_gas=declared.V_gas, T_op=declared.T_op),
        matrix,
        solver,
        extensions,
        declared.extensions,
        ext_over,
    )
    stagnant = None
    if not mixing.ideal:
        stagnant = compile_extended(
            p,
            PlantGeometry(V_liq=max(V_stag, 1e-12), V_gas=declared.V_gas, T_op=declared.T_op),
            matrix,
            solver,
            extensions,
            declared.extensions,
            ext_over,
        )
    return ReactorModel(
        main=main,
        stagnant=stagnant,
        mixing=mixing,
        V_main=V_main,
        V_stag=V_stag,
        V_gas=declared.V_gas,
    )


def rhs_reactor(
    t: float,
    y: np.ndarray,
    u_conc: np.ndarray,
    u_q: float,
    model: ReactorModel,
    u_ext: np.ndarray,
) -> np.ndarray:
    """Time derivative of the reactor state under the mixing structure.

    Args:
        t: Time, d (unused).
        y: Reactor state (:attr:`ReactorModel.state_names` order).
        u_conc: Influent concentrations of the 26 standard liquid states.
        u_q: Influent flow, m3/d (before the bypass split).
        model: Compiled reactor.
        u_ext: Influent concentrations of the extension components.

    Returns:
        ``dy/dt``.
    """
    if model.ideal:
        return rhs_extended(t, y, u_conc, u_q, model.main, u_ext)

    n_main = model.main.n_states
    y_main, y_stag = y[:n_main], y[n_main:]
    q_main = (1.0 - model.mixing.bypass_fraction) * u_q
    d_main = rhs_extended(t, y_main, u_conc, q_main, model.main, u_ext)

    # stagnant zone: reaction + gas transfer against the shared headspace, no through-flow
    assert model.stagnant is not None
    n_liq = N_STATES - N_GAS
    y_stag_full = np.concatenate((y_stag[:n_liq], y_main[_GAS_SLICE], y_stag[n_liq:]))
    d_stag_full = rhs_extended(t, y_stag_full, u_conc, 0.0, model.stagnant, u_ext)
    d_stag = np.concatenate((d_stag_full[: N_STATES - N_GAS], d_stag_full[N_STATES:]))

    # liquid exchange between the zones
    liq_main = model.liquid_of(y_main)
    k_ex = model.mixing.exchange_rate
    ex = k_ex * (y_stag - liq_main)  # per unit stagnant volume, towards the active zone
    d_stag = d_stag - ex
    ratio = model.V_stag / model.V_main
    d_main[: N_STATES - N_GAS] += ratio * ex[: N_STATES - N_GAS]
    d_main[N_STATES:] += ratio * ex[N_STATES - N_GAS :]

    # headspace: both zones transfer into it; the outflow term was counted in both calls
    pc, k, T = model.main.base.params.physchem, model.main.base.k, model.main.base.plant.T_op
    g = y_main[_GAS_SLICE]
    yr_g = np.maximum(g, 0.0) if model.main.base.solver.clip_negative_states_in_rates else g
    gas = physchem.gas_phase(yr_g[0], yr_g[1], yr_g[2], T, pc, k.p_h2o)
    d_main[_GAS_SLICE] += d_stag_full[_GAS_SLICE] + yr_g * gas.q_gas_raw / model.V_gas
    return np.concatenate((d_main, d_stag))


@dataclass(frozen=True)
class ReactorResult:
    """Trajectory of the reactor with derived quantities of the active zone."""

    t: np.ndarray
    """Output times, d."""
    y: np.ndarray
    """``(n_states, n_times)`` in :attr:`ReactorModel.state_names` order."""
    state_names: tuple[str, ...]
    active: ExtendedResult
    """The active-zone trajectory as an :class:`~sim.adm1.extensions.ExtendedResult`
    (pH, speciation, gas quantities; the headspace is shared, so its gas flows are the
    plant's)."""
    effluent: np.ndarray
    """``(n_liquid, n_times)`` effluent liquid concentrations after the bypass:
    ``(1 - beta) c_active + beta c_influent``; units as the states."""
    success: bool
    message: str

    def state(self, name: str) -> np.ndarray:
        """Trajectory of one state by name."""
        return self.y[self.state_names.index(name)]

    def final(self) -> dict[str, float]:
        """Final value of every derived quantity of the active zone."""
        return self.active.final()


def initial_state(
    model: ReactorModel, base_y0: np.ndarray, ext: Mapping[str, float] | None = None
) -> np.ndarray:
    """Reactor initial state from a 29-state vector, both zones at the same composition."""
    y_main = extended_state(model.main, base_y0, dict(ext or {}))
    if model.ideal:
        return y_main
    return np.concatenate((y_main, model.liquid_of(y_main)))


def _influent_at(influent: Influent, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Influent concentrations and flow at output times (hold or linear, as declared)."""
    if influent.interpolation == "hold":
        idx = np.clip(np.searchsorted(influent.t, t, side="right") - 1, 0, influent.t.size - 1)
        return influent.concentrations[idx].T, influent.q[idx]
    conc = np.stack([np.interp(t, influent.t, influent.concentrations[:, j]) for j in range(26)])
    return conc, np.interp(t, influent.t, influent.q)


def simulate_reactor(
    *,
    y0: np.ndarray,
    influent: Influent,
    model: ReactorModel,
    t_span: tuple[float, float],
    t_eval: np.ndarray | None = None,
    u_ext: Mapping[str, float] | None = None,
) -> ReactorResult:
    """Integrate the plant under its mixing structure (same influent handling as ADM1).

    Args:
        y0: Reactor initial state (see :func:`initial_state`).
        influent: Influent series of the 26 standard liquid states, total flow.
        model: Compiled reactor.
        t_span: ``(t0, t1)`` in days.
        t_eval: Output times or ``None`` for every accepted step.
        u_ext: Constant influent concentrations of extension components (missing = 0).

    Returns:
        The trajectory with the active zone's derived quantities and the effluent.
    """
    y0 = np.asarray(y0, dtype=float)
    if y0.shape != (model.n_states,):
        raise ValueError(f"y0 must have shape ({model.n_states},), got {y0.shape}")
    ext_names = model.main.state_names[N_STATES:]
    u_ext_vec = np.zeros(len(ext_names))
    for name, value in (u_ext or {}).items():
        if name not in ext_names:
            raise ValueError(f"{name!r} is not an extension state of this model")
        u_ext_vec[ext_names.index(name)] = float(value)

    def fun(t: float, y: np.ndarray, c: np.ndarray, q: float) -> np.ndarray:
        return rhs_reactor(t, y, c, q, model, u_ext_vec)

    traj = integrate(
        y0=y0,
        influent=influent,
        solver=model.main.base.solver,
        fun=fun,
        t_span=t_span,
        t_eval=t_eval,
    )
    n_main = model.main.n_states
    y_main = traj.y[:n_main]
    active = ExtendedResult(
        t=traj.t,
        y=y_main,
        state_names=model.main.state_names,
        derived=derived_extended(y_main, model.main),
        success=traj.success,
        message=traj.message,
        stats=traj.stats,
    )
    liq = np.concatenate((y_main[: N_STATES - N_GAS], y_main[N_STATES:]), axis=0)
    beta = model.mixing.bypass_fraction
    if beta > 0.0:
        conc, _ = _influent_at(influent, traj.t)
        u_full = np.concatenate((conc, np.repeat(u_ext_vec[:, None], traj.t.size, axis=1)))
        effluent = (1.0 - beta) * liq + beta * u_full
    else:
        effluent = liq
    return ReactorResult(
        t=traj.t,
        y=traj.y,
        state_names=model.state_names,
        active=active,
        effluent=effluent,
        success=traj.success,
        message=traj.message,
    )
