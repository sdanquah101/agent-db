"""The fitted model a workflow calibrates: ``adm1_fitted`` (design §2).

``sim.adm1`` -- the BSM2 parameter set of ``configs/adm1/params_bsm2.yaml`` -- plus the
extensions the plant contract declares as fitted for this run (the plant's
``truth_model.extensions`` less what a Level-6 row removes; the privileged side reads that
set from the run's truth store and passes it here, and the model never reports it).

**Nothing hidden enters.** The influent is the operator's feed log mapped through the
**declared** catalogue at catalogue solids, day by day, sample-and-hold, with the declared
blend tank of Plant B applied to its declared feeds; the geometry is the declared volume
and set point; the dissolved calcium of the feed is the catalogue's; the inert COD
equivalent and the feed ash are the catalogue's. What the truth has and this does not --
the true fractionation and its drift, the true solids, the unrecorded deliveries, the
active-volume error, the per-feed inert nitrogen, a Level-6 mechanism -- is exactly the
background against which every scenario is scored.

**Calibratable parameters** are base ADM1 kinetic and stoichiometric parameters, by name,
as **multipliers** of the BSM2 default inside the bounds of ``configs/tools/model.yaml``;
the vector of ones is the default model. A product fraction (``f_*_xc``) is rescaled with
its group so the group still sums to one. Extension parameters are not calibratable and
the interface is the same on every run.

**Initial state.** A burn-in on the feed log's reference recipe at the parameters being
evaluated (the harness's own staging, on declared quantities), unless the caller passes an
``initial_state`` or a ``biomass_scale`` -- the Level-4 unknown. The burn-in is part of the
one simulator evaluation that includes it (the evaluation-counting rule).

**Outputs** are the observation channels of :func:`sim.observation.channel_series` on
the daily grid, in the channel units, so a residual against a sensor is one unit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from sim.adm1 import (
    ADM1Parameters,
    Influent,
    PetersenMatrix,
    SolverConfig,
    compile_extended,
    extended_state,
    load_extensions,
    load_initial_state,
    load_matrix,
    load_parameters,
    load_solver_config,
    simulate_extended,
)
from sim.adm1.extensions import ExtensionsConfig
from sim.adm1.schema import N_STATES
from sim.influent import (
    FeedFractionationCatalogue,
    constant_influent,
    extension_influent,
    feed_concentrations,
    feed_tkn,
    load_feed_fractionation,
)
from sim.observation import (
    CHANNEL_UNITS,
    ash_trajectory,
    channel_series,
    influent_ash_concentration,
    influent_inert_cod_equivalent,
)
from sim.plants import PlantConfig, declared_geometry
from sim.plants.equalisation import BufferedInfluent, apply_equalisation, buffer_series
from tools.config import FittedModelConfig, load_fitted_model
from tools.schemas import FeedLoadsOutput

__all__ = ["BIOMASS_STATES", "FittedADM1"]

BIOMASS_STATES: frozenset[str] = frozenset(
    {"X_su", "X_aa", "X_fa", "X_c4", "X_pro", "X_ac", "X_h2", "X_sao"}
)
"""The states a ``biomass_scale`` multiplies (the same set the Level-4 fault scales)."""

_COMPOSITE_FRACTIONS = ("f_si_xc", "f_xi_xc", "f_ch_xc", "f_pr_xc", "f_li_xc")
KG_N_PER_KMOL = 14.007


class FittedADM1:
    """The fitted ADM1 of one run, as a :class:`tools.models.Model`."""

    name = "adm1_fitted"

    def __init__(
        self,
        *,
        plant: PlantConfig,
        feed_log: Mapping[str, np.ndarray],
        extensions: Sequence[str],
        horizon_d: float,
        config: FittedModelConfig | None = None,
        catalogue: FeedFractionationCatalogue | None = None,
        parameters: ADM1Parameters | None = None,
        matrix: PetersenMatrix | None = None,
        solver: SolverConfig | None = None,
        extension_config: ExtensionsConfig | None = None,
    ) -> None:
        """Build the fitted model of a run from declared quantities only.

        Args:
            plant: The plant's visible contract.
            feed_log: The operator's feed log, feed id -> kg wet/d per day.
            extensions: The extensions the fitted model carries (from the privileged side).
            horizon_d: Length of the record, d.
            config: ``configs/tools/model.yaml`` (default: loaded).
            catalogue: The declared feed catalogue (default: loaded).
            parameters: Base ADM1 parameters (default: BSM2).
            matrix: The Petersen matrix (default: loaded).
            solver: Solver settings (default: ``configs/adm1/solver.yaml``).
            extension_config: ``configs/adm1/extensions.yaml`` (default: loaded).

        Raises:
            ValueError: If the feed log names a feed the plant does not declare, or an
                extension the configuration does not define.
        """
        self.config = config or load_fitted_model()
        self.plant = plant
        self.extensions = tuple(extensions)
        self.horizon_d = float(horizon_d)
        self._catalogue = catalogue or load_feed_fractionation()
        self._base = parameters or load_parameters()
        self._matrix = matrix or load_matrix()
        self._solver = solver or load_solver_config()
        self._ext_config = extension_config or load_extensions()
        self.geometry = declared_geometry(plant)
        self._last: tuple[bool, str] = (True, "")

        declared = {f.name: f for f in plant.feeds}
        unknown = set(feed_log) - set(declared)
        if unknown:
            raise ValueError(f"feed log names feeds the plant does not declare: {sorted(unknown)}")
        self._feed_ids = tuple(f.name for f in plant.feeds if f.name in feed_log)
        self._specs = {fid: self._catalogue.for_stream(declared[fid]) for fid in self._feed_ids}
        self._log = {fid: np.asarray(feed_log[fid], dtype=float) for fid in self._feed_ids}
        n_days = min(v.size for v in self._log.values())
        self.n_days = int(n_days)
        unknown_ext = set(self.extensions) - set(self._ext_config.extensions)
        if unknown_ext:
            raise ValueError(f"unknown extensions {sorted(unknown_ext)}")

        # -- calibratable parameters: multipliers of the base values ------------------
        self.parameter_names = tuple(self.config.parameters)
        namespace = self._base.namespace()
        for name, spec in self.config.parameters.items():
            group = getattr(self._base, spec.group)
            if not hasattr(group, name):
                raise ValueError(f"{name!r} is not a {spec.group} parameter of ADM1")
        self.defaults = np.ones(len(self.parameter_names))
        self.lower = np.array([self.config.parameters[n].lower for n in self.parameter_names])
        self.upper = np.array([self.config.parameters[n].upper for n in self.parameter_names])
        self.parameter_units = {
            n: f"- (multiplier of the BSM2 default {namespace[n]:.6g})"
            for n in self.parameter_names
        }

        # -- the influent, day by day, through the declared catalogue -----------------
        self.t = np.arange(0.0, self.horizon_d + 1e-9, self.config.output_interval_d)
        self._influent, self._buffered = self._build_influent()
        n_ref = max(1, min(int(self.config.reference_window_d), self.n_days))
        self._recipe = {fid: float(self._log[fid][:n_ref].mean()) for fid in self._feed_ids}
        self._burn_influent = constant_influent(self._catalogue, self._recipe)
        self._inert = influent_inert_cod_equivalent(self._catalogue, self._recipe)
        self._u_ext_all = {
            **extension_influent(self._catalogue, self._recipe),
            **self.config.influent_extension_states,
        }
        self._ash_in = self._ash_series()

        self.output_names = tuple(self.config.outputs)
        self.output_units = {n: CHANNEL_UNITS[n] for n in self.output_names}
        self.description = (
            f"ADM1 (BSM2 defaults) with extensions declared as fitted, on plant {plant.id}'s "
            f"declared geometry, fed the operator's log through the declared catalogue; "
            f"parameters are multipliers of the defaults"
        )

    # -- construction helpers ----------------------------------------------------------
    def _mass_rates(self, day: int) -> dict[str, float]:
        return {fid: float(self._log[fid][day]) for fid in self._feed_ids}

    def _build_influent(self) -> tuple[Influent, BufferedInfluent | None]:
        n = self.n_days
        t = np.arange(n, dtype=float)
        conc = np.zeros((n, N_STATES - 3))
        q = np.zeros(n)
        buffered_ids = tuple(self.plant.equalisation.feeds) if self.plant.equalisation else ()
        q_buf = np.zeros(n)
        load_buf = np.zeros((n, N_STATES - 3))
        for day in range(n):
            total = np.zeros(N_STATES - 3)
            q_total = 0.0
            for fid in self._feed_ids:
                m = float(self._log[fid][day])
                if m <= 0.0:
                    continue
                spec = self._specs[fid]
                q_f = m / spec.density
                c_f = feed_concentrations(spec, spec.fractionation)
                total += q_f * c_f
                q_total += q_f
                if fid in buffered_ids:
                    q_buf[day] += q_f
                    load_buf[day] += q_f * c_f
            q[day] = q_total
            conc[day] = total / q_total if q_total > 0.0 else 0.0
        influent = Influent(t=t, concentrations=conc, q=q)
        if not buffered_ids or not np.any(q_buf > 0.0):
            return influent, None
        buffered = apply_equalisation(influent, q_buf, load_buf, self.plant.equalisation)
        return buffered.influent, buffered

    def _ash_series(self) -> np.ndarray:
        """Feed ash per day, kg/m3 of the wet feed reaching the digester, tank applied."""
        n = self.n_days
        buffered_ids = set(self.plant.equalisation.feeds) if self.plant.equalisation else set()
        ash_load = {
            fid: self._log[fid] * self._specs[fid].ts * (1.0 - self._specs[fid].vs_of_ts)
            for fid in self._feed_ids
        }
        if self._buffered is not None:
            ids = [fid for fid in self._feed_ids if fid in buffered_ids]
            if ids:
                stacked = np.stack([ash_load[f] for f in ids], axis=1)
                _, out, _ = buffer_series(
                    self._buffered.passthrough_q_m3_d,
                    stacked,
                    self._buffered.hold_up_d,
                    init_window_d=self._buffered.hold_up_d,
                )
                for i, fid in enumerate(ids):
                    ash_load[fid] = out[:, i]
        total = sum(ash_load.values()) if ash_load else np.zeros(n)
        q = np.asarray(self._influent.q, dtype=float)
        out = np.zeros(n)
        last = 0.0
        for day in range(n):
            if q[day] > 0.0:
                last = float(total[day] / q[day])
            out[day] = last
        return out

    def _parameters(self, theta: np.ndarray) -> ADM1Parameters:
        """The ADM1 parameter set at a multiplier vector."""
        theta = np.asarray(theta, dtype=float)
        if theta.shape != self.defaults.shape:
            raise ValueError(f"theta must have shape {self.defaults.shape}, got {theta.shape}")
        updates: dict[str, dict[str, float]] = {"kinetics": {}, "stoichiometry": {}, "physchem": {}}
        for name, value in zip(self.parameter_names, theta, strict=True):
            group = self.config.parameters[name].group
            base = float(getattr(getattr(self._base, group), name))
            updates[group][name] = base * float(value)
        stoich = updates["stoichiometry"]
        touched = [n for n in _COMPOSITE_FRACTIONS if n in stoich]
        if touched:
            base_s = self._base.stoichiometry
            fixed = sum(stoich[n] for n in touched)
            rest = [n for n in _COMPOSITE_FRACTIONS if n not in touched]
            rest_base = sum(float(getattr(base_s, n)) for n in rest)
            if fixed >= 1.0 or rest_base <= 0.0:
                raise ValueError("the composite fractions cannot be rescaled to sum to one")
            scale = (1.0 - fixed) / rest_base
            for n in rest:
                stoich[n] = float(getattr(base_s, n)) * scale
        out = self._base
        for group, values in updates.items():
            if values:
                block = getattr(out, group).model_copy(update=values)
                out = out.model_copy(update={group: block})
        return out

    # -- the Model interface ---------------------------------------------------------
    def last_status(self) -> tuple[bool, str]:
        """``(success, message)`` of the last integration."""
        return self._last

    def evaluate(self, theta: np.ndarray, **options: object) -> dict[str, np.ndarray]:
        """One simulator evaluation: burn-in (unless a state is given) and the record.

        Options: ``initial_state`` (state name -> value, applied after the burn-in),
        ``biomass_scale`` (multiplier on every biomass state after the burn-in),
        ``t_end`` (integrate only to this day; the outputs are still on the full grid,
        held at their last value beyond it).
        """
        params = self._parameters(theta)
        model = compile_extended(
            params, self.geometry, self._matrix, self._solver, self._ext_config, self.extensions
        )
        ext_states = set(model.state_names[N_STATES:])
        u_ext = {k: v for k, v in self._u_ext_all.items() if k in ext_states}
        init_ext = {
            k: v for k, v in self.config.initial_extension_states.items() if k in ext_states
        }

        y0 = extended_state(model, load_initial_state(), init_ext)
        burn = simulate_extended(
            y0=y0,
            influent=self._burn_influent,
            model=model,
            t_span=(0.0, self.config.burn_in_days),
            t_eval=np.arange(
                0.0, self.config.burn_in_days + 1e-9, self.config.burn_in_output_interval_d
            ),
            u_ext=u_ext,
        )
        y_start = np.array(burn.y[:, -1], dtype=float)
        scale = options.get("biomass_scale")
        if scale is not None:
            for i, name in enumerate(model.state_names):
                if name in BIOMASS_STATES:
                    y_start[i] *= float(scale)
        overrides = options.get("initial_state")
        if overrides:
            for name, value in dict(overrides).items():
                if name not in model.state_names:
                    raise ValueError(f"{name!r} is not a state of the fitted model")
                y_start[model.index(name)] = float(value)

        t_end = float(options.get("t_end") or self.horizon_d)
        t_end = min(max(t_end, self.t[0]), self.horizon_d)
        grid = self.t[self.t <= t_end + 1e-9]
        result = simulate_extended(
            y0=y_start,
            influent=self._influent,
            model=model,
            t_span=(0.0, float(grid[-1])),
            t_eval=grid,
            u_ext=u_ext,
        )
        self._last = (bool(burn.success and result.success), str(result.message))
        ash = ash_trajectory(grid, self._influent, self.geometry.V_liq, self._ash_in)
        channels = channel_series(
            result,
            T_op=self.geometry.T_op,
            inert_cod_equivalent=self._inert,
            ash=ash,
            physchem=params.physchem,
        )
        out = {}
        for name in self.output_names:
            series = np.asarray(channels[name], dtype=float)
            if series.size < self.t.size:
                series = np.concatenate([series, np.full(self.t.size - series.size, series[-1])])
            out[name] = series
        return out

    # -- declared loads of the log ---------------------------------------------------
    def feed_loads(self) -> FeedLoadsOutput:
        """What the declared catalogue says the logged feed delivered, per day."""
        n = self.n_days
        t = np.arange(n, dtype=float)
        q = np.zeros(n)
        cod = np.zeros(n)
        tkn = np.zeros(n)
        tan = np.zeros(n)
        charge = np.zeros(n)
        stoich = self._base.stoichiometry
        for day in range(n):
            for fid in self._feed_ids:
                m = float(self._log[fid][day])
                if m <= 0.0:
                    continue
                spec = self._specs[fid]
                q_f = m / spec.density
                q[day] += q_f
                cod[day] += q_f * spec.cod_per_m3
                tkn[day] += q_f * feed_tkn(spec, stoich.N_aa, spec.fractionation) * KG_N_PER_KMOL
                tan[day] += q_f * spec.tan * KG_N_PER_KMOL
                charge[day] += q_f * (spec.s_cat - spec.s_an)
        return FeedLoadsOutput(
            t=t,
            q_m3_d=q,
            cod_kg_d=cod,
            tkn_kg_n_d=tkn,
            tan_kg_n_d=tan,
            charge_keq_d=charge,
            units={
                "q_m3_d": "m3/d",
                "cod_kg_d": "kg COD/d",
                "tkn_kg_n_d": "kg N/d",
                "tan_kg_n_d": "kg N/d",
                "charge_keq_d": "keq/d (strong cations minus strong anions)",
            },
        )

    @staticmethod
    def ash_of(catalogue: FeedFractionationCatalogue, rates: Mapping[str, float]) -> float:
        """The catalogue's feed ash of a recipe, kg/m3 (exposed for tests)."""
        return influent_ash_concentration(catalogue, rates)
