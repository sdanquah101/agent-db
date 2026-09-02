"""PARKED: two-zone imperfectly mixed digester — NOT part of the plant contract.

The plant contract is an ideal CSTR and allows nothing else
(:class:`sim.plants.schema.Mixing`; lead's decision of 2026-09-02, "Plant configurations
A/B/C — frozen", answer 6). Imperfect mixing is a *fault-injection truth variant* of the
Level-6 "Imperfect mixing" scenario. This module is the implementation of that truth
variant, salvaged from PR #7's ``sim/plants/reactor.py`` and kept here for the
fault-injection API to pick up; nothing in ``configs/plants`` or :class:`PlantConfig`
refers to it, and no plant carries mixing parameters.

The structure is the classical compartment model of a non-ideal stirred tank
(Levenspiel; used for full-scale digesters by Monteith & Stephenson 1978 and Capela et
al. 2009):

* a well-mixed **active zone** of volume ``V_main = V_liq (1 - phi)``;
* a **stagnant zone** of volume ``V_stag = V_liq phi`` that exchanges liquid with the
  active zone at ``Q_ex = k_ex V_stag`` (no inflow, no outflow, full biochemistry, gas
  transfer to the shared headspace);
* a **bypass**: a fraction ``beta`` of the influent short-circuits to the effluent
  without entering either zone.

With ``beta = phi = 0`` the state vector is the extended model's own and the right-hand
side is :func:`sim.adm1.extensions.rhs_extended` unchanged, so the ideal CSTR is
reproduced bit for bit (tested against :func:`sim.adm1.simulate`). ``V_liq`` is whatever
volume the caller passes: the *true* active volume from :func:`sim.plants.true_geometry`
for the truth model, the declared one for an operator's model.

Everything is a pure function of its arguments: no file I/O, no module-level mutable
state, no randomness.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

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
    N_LIQUID,
    N_STATES,
    ADM1Parameters,
    Influent,
    PlantGeometry,
    SolverConfig,
)

_GAS_SLICE = slice(N_STATES - N_GAS, N_STATES)

#: Liquid volume given to a stagnant-zone model when the stagnant share is zero but the
#: structure is still non-ideal (bypass only); the zone then has no dynamics of its own.
_EMPTY_ZONE_M3 = 1e-12


class MixingStructure(BaseModel):
    """The hidden mixing structure of the Level-6 truth variant. ``ideal`` is the CSTR."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bypass_fraction: Annotated[float, Field(ge=0.0, lt=1.0)] = Field(
        description="Influent fraction that short-circuits to the effluent, -"
    )
    stagnant_fraction: Annotated[float, Field(ge=0.0, lt=1.0)] = Field(
        description="Stagnant share of the liquid volume, -"
    )
    exchange_rate: Annotated[float, Field(ge=0.0)] = Field(
        description="Stagnant-zone exchange rate, 1/d (Q_ex / V_stagnant)"
    )

    @property
    def ideal(self) -> bool:
        """True when the structure is exactly the ideal CSTR."""
        return self.bypass_fraction == 0.0 and self.stagnant_fraction == 0.0

    @classmethod
    def cstr(cls) -> MixingStructure:
        """The ideal CSTR (no bypass, no stagnant zone)."""
        return cls(bypass_fraction=0.0, stagnant_fraction=0.0, exchange_rate=0.0)


@dataclass(frozen=True)
class TwoZoneModel:
    """A compiled reactor: the extended model on each zone plus the mixing structure."""

    main: ExtendedModel
    """Extended model compiled on the active-zone volume."""
    stagnant: ExtendedModel | None
    """Extended model compiled on the stagnant-zone volume; ``None`` when ideal."""
    mixing: MixingStructure
    V_main: float
    """Active-zone liquid volume, m3."""
    V_stag: float
    """Stagnant-zone liquid volume, m3 (0 when ideal)."""
    V_gas: float
    """Headspace volume, m3 (shared by both zones)."""

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
        liq = names[:N_LIQUID] + names[N_STATES:]
        return names + tuple(f"{n}_stag" for n in liq)

    def split(self, y: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
        """``(active-zone state, stagnant-zone liquid state or None)``."""
        n = self.main.n_states
        return y[:n], (None if self.ideal else y[n:])

    def liquid_of(self, y_main: np.ndarray) -> np.ndarray:
        """The liquid states of an active-zone vector (standard then extension)."""
        return np.concatenate((y_main[:N_LIQUID], y_main[N_STATES:]))


def compile_two_zone(
    params: ADM1Parameters,
    geometry: PlantGeometry,
    matrix: PetersenMatrix,
    solver: SolverConfig,
    extensions: ExtensionsConfig,
    enabled: Sequence[str],
    mixing: MixingStructure,
    overrides: Mapping[str, float] | None = None,
) -> TwoZoneModel:
    """Compile the extended truth model under a mixing structure.

    Args:
        params: ADM1 parameters.
        geometry: Liquid volume to split between the zones (the true active volume for
            the truth model), headspace volume and temperature.
        matrix: Standard Petersen matrix.
        solver: Solver settings.
        extensions: Parsed ``extensions.yaml``.
        enabled: Extension names to enable, in state order.
        mixing: The mixing structure; :meth:`MixingStructure.cstr` gives the ideal CSTR.
        overrides: Extension-parameter overrides, as for
            :func:`sim.adm1.extensions.compile_extended`.

    Returns:
        The compiled reactor.
    """
    V_stag = geometry.V_liq * mixing.stagnant_fraction
    V_main = geometry.V_liq - V_stag
    main = compile_extended(
        params,
        PlantGeometry(V_liq=V_main, V_gas=geometry.V_gas, T_op=geometry.T_op),
        matrix,
        solver,
        extensions,
        enabled,
        overrides,
    )
    stagnant = None
    if not mixing.ideal:
        stagnant = compile_extended(
            params,
            PlantGeometry(
                V_liq=max(V_stag, _EMPTY_ZONE_M3), V_gas=geometry.V_gas, T_op=geometry.T_op
            ),
            matrix,
            solver,
            extensions,
            enabled,
            overrides,
        )
    return TwoZoneModel(
        main=main,
        stagnant=stagnant,
        mixing=mixing,
        V_main=V_main,
        V_stag=V_stag,
        V_gas=geometry.V_gas,
    )


def rhs_two_zone(
    t: float,
    y: np.ndarray,
    u_conc: np.ndarray,
    u_q: float,
    model: TwoZoneModel,
    u_ext: np.ndarray,
) -> np.ndarray:
    """Time derivative of the reactor state under the mixing structure.

    Args:
        t: Time, d (unused).
        y: Reactor state (:attr:`TwoZoneModel.state_names` order).
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
    y_stag_full = np.concatenate((y_stag[:N_LIQUID], y_main[_GAS_SLICE], y_stag[N_LIQUID:]))
    d_stag_full = rhs_extended(t, y_stag_full, u_conc, 0.0, model.stagnant, u_ext)
    d_stag = np.concatenate((d_stag_full[:N_LIQUID], d_stag_full[N_STATES:]))

    # liquid exchange between the zones
    liq_main = model.liquid_of(y_main)
    k_ex = model.mixing.exchange_rate
    ex = k_ex * (y_stag - liq_main)  # per unit stagnant volume, towards the active zone
    d_stag = d_stag - ex
    ratio = model.V_stag / model.V_main
    d_main[:N_LIQUID] += ratio * ex[:N_LIQUID]
    d_main[N_STATES:] += ratio * ex[N_LIQUID:]

    # headspace: both zones transfer into it; the outflow term was counted in both calls
    pc, k, T = model.main.base.params.physchem, model.main.base.k, model.main.base.plant.T_op
    g = y_main[_GAS_SLICE]
    yr_g = np.maximum(g, 0.0) if model.main.base.solver.clip_negative_states_in_rates else g
    gas = physchem.gas_phase(yr_g[0], yr_g[1], yr_g[2], T, pc, k.p_h2o)
    d_main[_GAS_SLICE] += d_stag_full[_GAS_SLICE] + yr_g * gas.q_gas_raw / model.V_gas
    return np.concatenate((d_main, d_stag))


@dataclass(frozen=True)
class TwoZoneResult:
    """Trajectory of the reactor with derived quantities of the active zone."""

    t: np.ndarray
    """Output times, d."""
    y: np.ndarray
    """``(n_states, n_times)`` in :attr:`TwoZoneModel.state_names` order."""
    state_names: tuple[str, ...]
    active: ExtendedResult
    """The active-zone trajectory as an :class:`~sim.adm1.extensions.ExtendedResult`
    (pH, speciation, gas quantities; the headspace is shared, so its gas flows are the
    plant's)."""
    effluent: np.ndarray
    """``(n_liquid, n_times)`` effluent liquid concentrations after the bypass:
    ``(1 - beta) c_active + beta c_influent``; units as the states."""
    effluent_derived: Mapping[str, np.ndarray]
    """Speciation of the **effluent**, from :func:`~sim.adm1.extensions.derived_extended`
    on the effluent composition.

    A grab sample of digestate is the effluent, so its alkalinity, VFA anions and pH are
    the effluent's, not the active zone's — with a bypass the two differ, and mixing them
    would make FOS/TAC a ratio of two different liquids (:func:`channels_from_two_zone`).
    The gas entries of this dict are computed from the active zone's gas states, because
    the headspace is shared; use :attr:`active` for anything gas."""
    success: bool
    message: str

    def state(self, name: str) -> np.ndarray:
        """Trajectory of one state by name."""
        return self.y[self.state_names.index(name)]

    def final(self) -> dict[str, float]:
        """Final value of every derived quantity of the active zone."""
        return self.active.final()


def initial_state(
    model: TwoZoneModel, base_y0: np.ndarray, ext: Mapping[str, float] | None = None
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
    conc = np.stack(
        [np.interp(t, influent.t, influent.concentrations[:, j]) for j in range(N_LIQUID)]
    )
    return conc, np.interp(t, influent.t, influent.q)


def simulate_two_zone(
    *,
    y0: np.ndarray,
    influent: Influent,
    model: TwoZoneModel,
    t_span: tuple[float, float],
    t_eval: np.ndarray | None = None,
    u_ext: Mapping[str, float] | None = None,
) -> TwoZoneResult:
    """Integrate the reactor under its mixing structure (same influent handling as ADM1).

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
        return rhs_two_zone(t, y, c, q, model, u_ext_vec)

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
    liq = np.concatenate((y_main[:N_LIQUID], y_main[N_STATES:]), axis=0)
    beta = model.mixing.bypass_fraction
    if beta > 0.0:
        conc, _ = _influent_at(influent, traj.t)
        u_full = np.concatenate((conc, np.repeat(u_ext_vec[:, None], traj.t.size, axis=1)))
        effluent = (1.0 - beta) * liq + beta * u_full
    else:
        effluent = liq
    # the effluent's own speciation: its liquid and extension states with the shared
    # headspace's gas states, so pH and the anions are the sampled liquid's (beta = 0
    # makes this identical to the active zone's, and the test asserts that)
    y_eff = np.concatenate((effluent[:N_LIQUID], y_main[_GAS_SLICE], effluent[N_LIQUID:]), axis=0)
    return TwoZoneResult(
        t=traj.t,
        y=traj.y,
        state_names=model.state_names,
        active=active,
        effluent=effluent,
        effluent_derived=derived_extended(y_eff, model.main),
        success=traj.success,
        message=traj.message,
    )
