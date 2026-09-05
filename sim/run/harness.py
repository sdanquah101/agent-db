"""The run harness: one scenario cell in, one ``runs/<id>/`` directory out (§6.1, gate G1).

This is the layer the proposal describes in one sentence — "the simulator logs hidden truth
alongside observations, in a separate file never exposed to workflows" — and it is where
every frozen component built so far is finally wired together:

.. code-block:: text

    scenario YAML
        |
        +-- sim.faults.build_plan ......... six typed per-layer directives
        |
        +-- sim.plants.sample_hidden_geometry ... the run's active-volume error   [truth]
        +-- sim.influent.generate_influent ...... deliveries, assays, mis-logs    [truth + log]
        +-- burn-in on the plant's median recipe  ... a digester already running
        +-- the truth model, in segments .......... a parameter fault changes it   [truth]
        +-- sim.observation.channel_series ........ every observable quantity      [truth]
        +-- sim.observation.observe ............... the tier's mask                [visible]
        +-- sim.run.notes ......................... the operator's log             [visible]
        |
        +-> runs/<id>/{truth,observations}/, manifest.json, calls.jsonl

**Three properties this module exists to hold.**

*Hidden truth is separated at the point it is produced.* Every quantity that identifies the
answer — the true parameters, the true influent and its drift, the true fractionation, the
realised volume error, the realised mixing structure, the state trajectory, the condition
flags, the fault plan and its labels — is written under ``truth/``. Everything a workflow
may read is written under ``observations/``. The two are written by different functions of
:mod:`sim.run.artifacts` and read back by different loaders, and :mod:`state.run_view` (the
workflow-facing one) cannot address the truth directory at all.

*A scenario starts on a running digester.* Integrating from a textbook steady state would
make the first weeks of every run a start-up transient that no fault caused, and Level-4's
"unknown initial biomass" would be indistinguishable from it. So the harness burns in on
the plant's own median recipe first (``configs/runs/harness.yaml``) and starts the scenario
from the state that burn-in reaches. The Level-4 fault is then applied to *that* state, which
is what makes it a mis-initialisation rather than a different digester.

*Every stochastic component has its own seed.* Five streams, in the fixed order of
:mod:`sim.run.seeds`, all derived from the scenario's base seed. The tier is deliberately
not part of the derivation, so the three tiers of a cell are one digester seen through three
windows (§6.4).

**Reused truth.** Because the tier changes only the mask, :func:`generate_cells` integrates
the truth once per (plant, scenario) and writes one run directory per tier from it. Each
directory is still self-contained: it carries its own complete copy of the truth, so
deleting one run never damages another.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

from scenarios.schema import FaultType, Scenario, Tier
from sim.adm1 import (
    ADM1Parameters,
    ExtendedModel,
    ExtendedResult,
    Influent,
    PetersenMatrix,
    PlantGeometry,
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
from sim.adm1.schema import SolverStats
from sim.faults import (
    FaultPlan,
    apply_state_faults,
    build_plan,
    declared_faults,
    fitted_extensions,
    load_fault_config,
    parameter_segments,
    truth_mixing,
)
from sim.influent import (
    FeedFractionationCatalogue,
    GeneratedInfluent,
    constant_influent,
    generate_influent,
    load_feed_fractionation,
    load_generator_config,
    truth_parameters,
)
from sim.influent.mapping import feed_concentrations
from sim.observation import (
    ObservationRecord,
    TruthChannels,
    ash_trajectory,
    channel_series,
    channels_from_two_zone,
    condition_flags,
    influent_inert_cod_equivalent,
    load_observation_config,
    observe,
)
from sim.plants import (
    HiddenGeometry,
    PlantConfig,
    load_plant_config,
    sample_hidden_geometry,
    true_geometry,
)
from sim.plants.equalisation import (
    BufferedInfluent,
    apply_equalisation,
    buffer_series,
    feed_contribution,
)
from sim.plants.mixing import (
    MixingStructure,
    TwoZoneModel,
    TwoZoneResult,
    compile_two_zone,
    initial_state,
    simulate_two_zone,
)
from sim.run.artifacts import write_observations, write_truth
from sim.run.layout import INDEX_FILE, RUNS_ROOT, RunPaths, run_id, truth_store_for
from sim.run.manifest import (
    HARNESS_VERSION,
    RunManifest,
    config_versions,
    git_sha,
    write_index_entry,
)
from sim.run.notes import LogNote, load_log_notes, operator_notes
from sim.run.seeds import RunSeeds
from state.provenance import CallLog

__all__ = [
    "HARNESS_CONFIG",
    "SIM_API_VERSION",
    "DigesterHealth",
    "HarnessConfig",
    "HealthThresholds",
    "RunArtifacts",
    "RunTruth",
    "apply_adaptation",
    "assess_health",
    "generate_cells",
    "generate_run",
    "load_harness_config",
    "simulate_truth",
    "split_for_equalisation",
]

HARNESS_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "runs" / "harness.yaml"

SIM_API_VERSION = "1.0"
"""Version string logged for the harness's own simulator calls.

The tool registry of §6.2 owns per-tool versions and lands in a later milestone; until it
does, the harness logs its calls under one version so that ``calls.jsonl`` is complete from
the first run rather than starting when the registry arrives (CLAUDE.md rule 3)."""


class HealthThresholds(BaseModel):
    """When a generated run counts as a working digester rather than a crashed one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_pH_median: float = Field(description="Lowest median pH a sound run may have, pH")
    min_ch4_fraction_mean: float = Field(
        description="Lowest mean methane content a sound run may have, - (dry mole fraction)"
    )
    settling_days: float = Field(ge=0.0, description="Days dropped from the head, d")


class HarnessConfig(BaseModel):
    """``configs/runs/harness.yaml``: how a scenario is staged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    health: HealthThresholds
    burn_in_days: float = Field(gt=0.0, description="Length of the pre-scenario burn-in, d")
    burn_in_output_interval_d: float = Field(gt=0.0, description="Burn-in output spacing, d")
    output_interval_d: float = Field(gt=0.0, description="Scenario output spacing, d")
    initial_extension_states: dict[str, float] = Field(
        description="Extension states at the start of the burn-in, in their own units"
    )
    influent_extension_states: dict[str, float] = Field(
        default_factory=dict,
        description="Extension components carried by the feed, beyond the catalogue's S_ca",
    )
    extension_influent: str = Field(description="How the per-day S_ca series becomes a constant")


def load_harness_config(path: Path = HARNESS_CONFIG) -> HarnessConfig:
    """Parse the harness settings.

    Raises:
        ValueError: If the file is not a YAML mapping.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return HarnessConfig.model_validate(raw)


@dataclass(frozen=True)
class DigesterHealth:
    """Whether a generated run is a working digester, and the numbers behind the verdict.

    A scenario staged on a digester that has acidified is not the scenario it claims to be:
    a Level-0 "clean" run that crashed is no control, and a fault injected into a crash is
    unattributable. So every run carries this label and the generation report counts it,
    rather than the question being answered once for one seed and assumed thereafter.
    """

    sound: bool
    pH_median: float
    ch4_fraction_mean: float
    vfa_total_median: float
    """kg/m3 as acetic acid."""
    fos_tac_median: float
    q_gas_stp_dry_mean: float
    """m3/d at 0 degC and 1 atm, water vapour removed."""
    settled_from_d: float

    def as_dict(self) -> dict[str, float | bool]:
        """The verdict and its numbers, for the truth record and the report."""
        return dict(asdict(self))


def assess_health(channels: TruthChannels, thresholds: HealthThresholds) -> DigesterHealth:
    """Label one run sound or soured from its own channels.

    The head of the run is dropped before any statistic is taken, so a Level-4
    mis-initialisation transient does not by itself condemn a digester that recovers.
    """
    settled = channels.t >= thresholds.settling_days
    if not settled.any():
        settled = np.ones_like(channels.t, dtype=bool)
    ph = float(np.median(channels["pH"][settled]))
    ch4 = float(np.mean(channels["ch4_fraction"][settled]))
    return DigesterHealth(
        sound=ph > thresholds.min_pH_median and ch4 > thresholds.min_ch4_fraction_mean,
        pH_median=ph,
        ch4_fraction_mean=ch4,
        vfa_total_median=float(np.median(channels["vfa_total"][settled])),
        fos_tac_median=float(np.median(channels["fos_tac"][settled])),
        q_gas_stp_dry_mean=float(np.mean(channels["q_gas_stp_dry"][settled])),
        settled_from_d=float(thresholds.settling_days),
    )


@dataclass(frozen=True)
class RunTruth:
    """Everything hidden about one run. Written only to ``runs/<id>/truth/``."""

    plant_id: str
    geometry: HiddenGeometry
    """Realised active-volume error (the operator is told the declared volume)."""
    mixing: MixingStructure
    """Realised mixing structure of the truth reactor; ideal unless Level-6 says otherwise."""
    influent: GeneratedInfluent
    """True deliveries, true fractionation and drift, plus the operator's record."""
    parameters: ADM1Parameters
    """True parameters before any onset; the segments carry the changes."""
    segments: tuple[tuple[float, float, ADM1Parameters], ...]
    """``(t_start, t_end, parameters)`` of each integration segment."""
    inert_cod_equivalent: float
    """kg COD per kg inert VS of this run's influent (solids channels need it)."""
    ash: np.ndarray
    """Digestate ash from the conserved tracer, kg/m3 per output time."""
    burn_in_state: np.ndarray
    """State the burn-in reached, before the Level-4 state fault."""
    initial_state: np.ndarray
    """State the scenario starts from, after the Level-4 state fault."""
    t: np.ndarray
    y: np.ndarray
    """``(n_states, n_times)`` truth trajectory in ``state_names`` order."""
    state_names: tuple[str, ...]
    channels: TruthChannels
    overload: np.ndarray
    foaming: np.ndarray
    """Condition flags behind conditional missingness; truth, never observed."""
    plan: FaultPlan
    fitted_extensions: tuple[str, ...]
    """Extensions the *fitted* model may carry: the truth's, less the omitted ones."""
    health: DigesterHealth
    """Whether this run is a working digester (:func:`assess_health`)."""
    solver_success: bool
    solver_message: str


@dataclass(frozen=True)
class RunArtifacts:
    """One generated cell: where it was written, what it contains, and what it cost."""

    run_id: str
    paths: RunPaths
    manifest: RunManifest
    truth: RunTruth
    record: ObservationRecord
    notes: tuple[LogNote, ...]
    workflow_faults: tuple[tuple[str, float], ...]
    """``(tool, failure probability)`` the tool registry must apply for this run. Handed
    to the registry **in memory** and written under ``truth/``: knowing in advance which
    tool will fail is the answer to the Level-8 row."""
    wall_s: float


# ------------------------------------------------------------------ integration


def _segment_grid(t_eval: np.ndarray, start: float, end: float, first: bool) -> np.ndarray:
    """Output times of one segment: ``[start, end]`` for the first, ``(start, end]`` after.

    The boundary belongs to exactly one segment, so the stitched trajectory has no repeated
    time. A segment with no grid point still gets its own end time, because the integrator
    must be asked for something.
    """
    inside = (t_eval >= start) & (t_eval <= end) if first else (t_eval > start) & (t_eval <= end)
    grid = t_eval[inside]
    return grid if grid.size else np.array([end])


def _stitch_stats(parts: Sequence[SolverStats]) -> SolverStats:
    """Sum the integrator effort of several segments into one record."""
    return SolverStats(
        nfev=sum(p.nfev for p in parts),
        njev=sum(p.njev for p in parts),
        nlu=sum(p.nlu for p in parts),
        n_steps=sum(p.n_steps for p in parts),
        n_segments=sum(p.n_segments for p in parts),
        min_step=min(p.min_step for p in parts),
        max_step=max(p.max_step for p in parts),
        wall_s=sum(p.wall_s for p in parts),
    )


def _stitch_extended(parts: Sequence[ExtendedResult]) -> ExtendedResult:
    """Concatenate per-segment extended results into one trajectory.

    The derived quantities are concatenated rather than recomputed: a parameter fault
    changes the *kinetics*, and each segment's derived block was computed under the
    kinetics that actually held there.
    """
    if len(parts) == 1:
        return parts[0]
    keys = parts[0].derived.keys()
    return ExtendedResult(
        t=np.concatenate([p.t for p in parts]),
        y=np.concatenate([p.y for p in parts], axis=1),
        state_names=parts[0].state_names,
        derived={k: np.concatenate([p.derived[k] for p in parts]) for k in keys},
        success=all(p.success for p in parts),
        message="; ".join(dict.fromkeys(p.message for p in parts if p.message)),
        stats=_stitch_stats([p.stats for p in parts]),
    )


def _stitch_two_zone(parts: Sequence[TwoZoneResult]) -> TwoZoneResult:
    """Concatenate per-segment two-zone results into one trajectory."""
    if len(parts) == 1:
        return parts[0]
    keys = parts[0].effluent_derived.keys()
    return TwoZoneResult(
        t=np.concatenate([p.t for p in parts]),
        y=np.concatenate([p.y for p in parts], axis=1),
        state_names=parts[0].state_names,
        active=_stitch_extended([p.active for p in parts]),
        effluent=np.concatenate([p.effluent for p in parts], axis=1),
        effluent_derived={k: np.concatenate([p.effluent_derived[k] for p in parts]) for k in keys},
        success=all(p.success for p in parts),
        message="; ".join(dict.fromkeys(p.message for p in parts if p.message)),
    )


def _compile(
    params: ADM1Parameters,
    geometry: PlantGeometry,
    enabled: Sequence[str],
    mixing: MixingStructure,
    matrix: PetersenMatrix,
    solver: SolverConfig,
    extensions: ExtensionsConfig,
) -> ExtendedModel | TwoZoneModel:
    """Compile the truth reactor: the extended model, or the two-zone one if not ideal."""
    if mixing.ideal:
        return compile_extended(params, geometry, matrix, solver, extensions, enabled)
    return compile_two_zone(params, geometry, matrix, solver, extensions, enabled, mixing)


# ------------------------------------------------------------------ generation


def _ash_load(
    catalogue: FeedFractionationCatalogue, truth: GeneratedInfluent, feed_ids: Sequence[str]
) -> dict[str, np.ndarray]:
    """Ash delivered by each feed on each day, kg/d.

    Ash is ``mass x TS x (1 - VS/TS)``, per feed and per day rather than from the mean
    recipe, because the whole point of the Level-3 moisture fault is that a feed's solids
    drift: an ash series taken from the mean would hold the fault out of the solids
    channels it is supposed to move.
    """
    feeds = truth.truth.feeds
    return {
        fid: feeds[fid].delivered_kg * feeds[fid].ts * (1.0 - catalogue.feeds[fid].vs_of_ts)
        for fid in feed_ids
    }


def _ash_concentration(ash_load: Mapping[str, np.ndarray], q: np.ndarray) -> np.ndarray:
    """Blend an ash load into a concentration, kg/m3 of the wet feed reaching the digester.

    A day with no feed has no defined feed ash, so the previous day's value is held rather
    than a zero being invented.
    """
    total = sum(ash_load.values())
    out = np.zeros_like(q)
    last = 0.0
    for t in range(q.size):
        if q[t] > 0.0:
            last = float(total[t] / q[t])
        out[t] = last
    return out


def apply_adaptation(params: ADM1Parameters, plant: PlantConfig) -> ADM1Parameters:
    """Apply the plant's declared community adaptation to the truth parameters.

    A plant whose contract declares no adaptation keeps the ADM1 defaults untouched, which
    is Plants B and C.

    Raises:
        ValueError: If the contract names an adapted constant this function does not know
            how to apply — better than silently ignoring it.
    """
    block = plant.adaptation
    if block is None or block.K_I_nh3 is None:
        return params
    kinetics = params.kinetics.model_copy(update={"K_I_nh3": float(block.K_I_nh3)})
    return params.model_copy(update={"kinetics": kinetics})


def split_for_equalisation(
    plant: PlantConfig,
    catalogue: FeedFractionationCatalogue,
    generated: GeneratedInfluent,
    plan: FaultPlan,
    feed_ids: Sequence[str],
) -> tuple[np.ndarray, np.ndarray]:
    """The flow and load passing through the declared buffer, ``(q, load)``.

    One side of the split is reconstructed from the catalogue and this run's true
    fractionation and solids; the other comes free as ``total - reconstructed``, which is
    exact whatever composition the feeds on that side happen to have. So the choice of
    which side to reconstruct is a **correctness** question, not a style one: it must be
    the side no composition-altering fault touches.

    A mislabelled batch is the case in point. On Plant B the buffer holds the
    high-strength waste and the mislabelling targets the FOG, so the buffered side is the
    clean one; if a scenario ever targeted the buffered feed instead, the direct side
    would be, and this picks whichever applies. If a fault touched both sides there would
    be no exact reconstruction and this raises rather than quietly returning something
    close.

    Raises:
        ValueError: If composition-altering faults touch both sides of the split.
    """
    buffered = tuple(f for f in feed_ids if f in set(plant.equalisation.feeds))
    direct = tuple(f for f in feed_ids if f not in set(plant.equalisation.feeds))
    altered = {m.feed_id for m in plan.influent.mislabelled}

    if not altered & set(buffered):
        reconstruct, residual_of_total = buffered, False
    elif not altered & set(direct):
        reconstruct, residual_of_total = direct, True
    else:
        raise ValueError(
            f"composition-altering faults touch both sides of the buffer split "
            f"({sorted(altered)}); neither side can be reconstructed exactly"
        )

    feeds = generated.truth.feeds
    per_feed_q: dict[str, np.ndarray] = {}
    per_feed_conc: dict[str, np.ndarray] = {}
    for fid in reconstruct:
        spec = catalogue.feeds[fid]
        per_feed_q[fid] = feeds[fid].delivered_kg / spec.density
        frac = generated.truth.fractionations[fid]
        per_feed_conc[fid] = np.stack(
            [feed_concentrations(spec, frac, float(ts)) for ts in feeds[fid].ts]
        )
    q, load = feed_contribution(reconstruct, per_feed_q, per_feed_conc)
    if not residual_of_total:
        return q, load
    q_total = np.asarray(generated.truth.influent.q, dtype=float)
    load_total = q_total[:, None] * np.asarray(generated.truth.influent.concentrations, dtype=float)
    return np.maximum(q_total - q, 0.0), load_total - load


def _equalise(
    plant: PlantConfig,
    catalogue: FeedFractionationCatalogue,
    generated: GeneratedInfluent,
    plan: FaultPlan,
    feed_ids: Sequence[str],
    ash_load: Mapping[str, np.ndarray],
) -> BufferedInfluent | None:
    """Send the trucked feeds through the plant's declared blend tank, if it has one.

    Returns:
        The buffered influent, or ``None`` for a plant whose contract declares no tank.
    """
    if plant.equalisation is None:
        return None
    _ = ash_load  # buffered separately, once the tank's hold-up is known
    q, load = split_for_equalisation(plant, catalogue, generated, plan, feed_ids)
    return apply_equalisation(generated.truth.influent, q, load, plant.equalisation)


def _buffered_ash_load(
    plant: PlantConfig, buffered: BufferedInfluent, ash_load: Mapping[str, np.ndarray]
) -> dict[str, np.ndarray]:
    """The ash load reaching the digester once the buffered feeds have passed the tank.

    Ash is conserved and inert, so it goes through the same tank as everything else: the
    buffered feeds' ash is pushed through :func:`~sim.plants.equalisation.buffer_series`
    at the tank's own hold-up and flow, and the direct feeds' ash is untouched.
    """
    buffered_ids = [f for f in ash_load if f in set(plant.equalisation.feeds)]
    if not buffered_ids:
        return dict(ash_load)
    stacked = np.stack([ash_load[f] for f in buffered_ids], axis=1)
    _, out, _ = buffer_series(buffered.passthrough_q_m3_d, stacked, buffered.hold_up_d)
    smoothed = dict(ash_load)
    for i, fid in enumerate(buffered_ids):
        smoothed[fid] = out[:, i]
    return smoothed


def _mean_s_ca(truth: GeneratedInfluent) -> float:
    """Flow-weighted mean dissolved calcium of the feed over the horizon, kmol/m3."""
    q = np.asarray(truth.truth.influent.q, dtype=float)
    s_ca = np.asarray(truth.truth.s_ca, dtype=float)
    total = float(q.sum())
    return float((q * s_ca).sum() / total) if total > 0.0 else 0.0


def _feed_ids_in_plant_order(plant: PlantConfig) -> tuple[str, ...]:
    """The plant's feed ids as the plant declares them, co-substrate last.

    :func:`sim.faults.build_plan` targets an influent fault at the last id it is handed and
    documents that this is the co-substrate "for every frozen plant"; that is true of the
    *declaration* order (Plant A silage, Plant B FOG) and false of the sorted order, so the
    harness passes the declared order and never a sorted one.
    """
    return tuple(feed.name for feed in plant.feeds)


def simulate_truth(
    scenario: Scenario,
    plant: PlantConfig,
    seeds: RunSeeds,
    *,
    harness: HarnessConfig | None = None,
    target_feed: str | None = None,
    log: CallLog | None = None,
) -> RunTruth:
    """Integrate one scenario's hidden truth, tier-independent.

    Everything a tier could change happens in :func:`observe`, so this is computed once per
    (plant, scenario) and shared by the tiers of that cell.

    Args:
        scenario: The validated scenario.
        plant: The plant configuration it runs on.
        seeds: The run's derived seeds.
        harness: Staging settings (default: ``configs/runs/harness.yaml``).
        target_feed: Feed an influent fault acts on (default: the plant's co-substrate).
        log: Call log to record the simulator calls in, if any.

    Returns:
        The run's hidden truth.

    Raises:
        RuntimeError: If the burn-in or a scenario segment fails to integrate.
    """
    cfg = harness or load_harness_config()
    catalogue = load_feed_fractionation()
    generator = load_generator_config()
    params = load_parameters()
    matrix, solver, extensions = load_matrix(), load_solver_config(), load_extensions()
    n_days = round(scenario.duration_days)

    feed_ids = _feed_ids_in_plant_order(plant)
    plan = build_plan(scenario, feed_ids, fault_seed=seeds.fault, target_feed=target_feed)

    hidden = sample_hidden_geometry(plant, seeds.geometry)
    geometry = true_geometry(plant, hidden)
    mixing = truth_mixing(plan, load_fault_config())

    generated = _logged(
        log,
        "sim.generate_influent",
        {"plant": plant.id, "seed": seeds.influent, "n_days": n_days, "faults": str(plan.influent)},
        lambda: generate_influent(
            plant,
            catalogue,
            generator,
            params,
            seed=seeds.influent,
            n_days=n_days,
            faults=plan.influent,
        ),
    )
    truth_frac = generated.truth.fractionations.fractionations
    truth_params = truth_parameters(params, catalogue, generated.truth.mean_recipe_kg_d, truth_frac)
    truth_params = apply_adaptation(truth_params, plant)
    # the adaptation is applied BEFORE the segments, so a Level-5 ammonia fault multiplies
    # the constant this community actually has rather than the sludge default it does not:
    # that is what makes a multiplier below 1 a *loss of adaptation* (lead's ruling 2)
    segments = tuple(parameter_segments(plan, truth_params))
    enabled = tuple(plant.truth_model.extensions)
    u_ext = {"S_ca": _mean_s_ca(generated), **cfg.influent_extension_states}

    # --- the declared blend tank, where the plant contract has one -------------------
    ash_load = _ash_load(catalogue, generated, feed_ids)
    buffered = _equalise(plant, catalogue, generated, plan, feed_ids, ash_load)
    fed_influent = generated.truth.influent if buffered is None else buffered.influent
    ash_in = _ash_concentration(
        ash_load if buffered is None else _buffered_ash_load(plant, buffered, ash_load),
        np.asarray(fed_influent.q, dtype=float),
    )

    # --- burn-in: the digester the scenario finds already running -------------------
    burn_model = _compile(segments[0][2], geometry, enabled, mixing, matrix, solver, extensions)
    burn_influent = constant_influent(catalogue, generated.truth.mean_recipe_kg_d, truth_frac)
    # the burn-in runs on the mean recipe, which the tank passes through unchanged: a
    # constant inflow leaves a well-mixed buffer as the same constant
    y0 = (
        extended_state(burn_model, load_initial_state(), cfg.initial_extension_states)
        if mixing.ideal
        else initial_state(burn_model, load_initial_state(), cfg.initial_extension_states)
    )
    burn = _logged(
        log,
        "sim.burn_in",
        {"plant": plant.id, "days": cfg.burn_in_days, "mixing": mixing.model_dump()},
        lambda: _simulate(
            y0=y0,
            influent=burn_influent,
            model=burn_model,
            t_span=(0.0, cfg.burn_in_days),
            t_eval=np.arange(0.0, cfg.burn_in_days + 1e-9, cfg.burn_in_output_interval_d),
            u_ext=u_ext,
            mixing=mixing,
        ),
    )
    if not burn.success:
        raise RuntimeError(
            f"burn-in failed for scenario {scenario.id} on plant {plant.id}: {burn.message}"
        )
    burn_state = np.array(burn.y[:, -1], dtype=float)

    # --- the scenario itself, in segments ------------------------------------------
    state_names = burn_model.state_names
    y_start = apply_state_faults(burn_state, plan, state_names)
    grid = np.arange(0.0, scenario.duration_days + 1e-9, cfg.output_interval_d)
    parts = []
    y = y_start
    for index, (start, end, seg_params) in enumerate(segments):
        model = _compile(seg_params, geometry, enabled, mixing, matrix, solver, extensions)
        t_eval = _segment_grid(grid, start, end, first=index == 0)
        part = _logged(
            log,
            "sim.simulate_truth_segment",
            {"scenario": scenario.id, "segment": index, "t_span": [start, end]},
            lambda m=model, yy=y, span=(start, end), te=t_eval: _simulate(
                y0=yy,
                influent=fed_influent,
                model=m,
                t_span=span,
                t_eval=te,
                u_ext=u_ext,
                mixing=mixing,
            ),
        )
        if not part.success:
            raise RuntimeError(
                f"segment {index} of scenario {scenario.id} on plant {plant.id} failed: "
                f"{part.message}"
            )
        parts.append(part)
        y = np.array(part.y[:, -1], dtype=float)

    result = _stitch_extended(parts) if mixing.ideal else _stitch_two_zone(parts)

    # --- channels ------------------------------------------------------------------
    inert = influent_inert_cod_equivalent(catalogue, generated.truth.mean_recipe_kg_d, truth_frac)
    ash = ash_trajectory(result.t, fed_influent, geometry.V_liq, ash_in)
    channels = _logged(
        log,
        "sim.channel_series",
        {"scenario": scenario.id, "n_times": int(result.t.size), "ideal_mixing": mixing.ideal},
        lambda: (
            channel_series(result, T_op=geometry.T_op, inert_cod_equivalent=inert, ash=ash)
            if mixing.ideal
            else channels_from_two_zone(
                result, T_op=geometry.T_op, inert_cod_equivalent=inert, ash=ash
            )
        ),
    )
    obs_cfg = load_observation_config()
    overload, foaming = condition_flags(
        channels,
        fos_tac_overload=obs_cfg.conditions.fos_tac_overload,
        fos_tac_foaming=obs_cfg.conditions.fos_tac_foaming,
        gas_surge_ratio=obs_cfg.conditions.gas_surge_ratio,
        gas_median_window_d=obs_cfg.conditions.gas_median_window_d,
    )
    active = result if mixing.ideal else result.active
    return RunTruth(
        plant_id=plant.id,
        geometry=hidden,
        mixing=mixing,
        influent=generated,
        parameters=truth_params,
        segments=segments,
        inert_cod_equivalent=float(inert),
        ash=ash,
        burn_in_state=burn_state,
        initial_state=y_start,
        t=result.t,
        y=result.y,
        state_names=tuple(result.state_names),
        channels=channels,
        overload=overload,
        foaming=foaming,
        plan=plan,
        fitted_extensions=fitted_extensions(plan, enabled),
        health=assess_health(channels, cfg.health),
        solver_success=bool(active.success),
        solver_message=str(active.message),
    )


def _simulate(
    *,
    y0: np.ndarray,
    influent: Influent,
    model: object,
    t_span: tuple[float, float],
    t_eval: np.ndarray,
    u_ext: Mapping[str, float],
    mixing: MixingStructure,
) -> ExtendedResult | TwoZoneResult:
    """Integrate with whichever reactor the plan's mixing structure calls for."""
    if mixing.ideal:
        return simulate_extended(
            y0=y0, influent=influent, model=model, t_span=t_span, t_eval=t_eval, u_ext=u_ext
        )
    return simulate_two_zone(
        y0=y0, influent=influent, model=model, t_span=t_span, t_eval=t_eval, u_ext=u_ext
    )


def _logged(log: CallLog | None, name: str, args: Mapping[str, object], call):  # noqa: ANN001, ANN202
    """Run ``call``, logging it to ``calls.jsonl`` when there is a log (CLAUDE.md rule 3)."""
    if log is None:
        return call()
    with log.record(name, SIM_API_VERSION, args):
        return call()


def generate_run(
    scenario: Scenario,
    tier: str | Tier,
    *,
    plant: PlantConfig | None = None,
    seed: int | None = None,
    replicate: int = 0,
    runs_root: Path = RUNS_ROOT,
    truth: RunTruth | None = None,
    target_feed: str | None = None,
    write: bool = True,
) -> RunArtifacts:
    """Generate one cell of the matrix and write its run directory.

    Args:
        scenario: The validated scenario.
        tier: Instrumentation tier to observe at. A scenario's own ``tier`` field is the
            tier it is *defined* at; the matrix runs the same scenario at every tier the
            plant declares, so the tier is an argument here.
        plant: The plant configuration (default: the scenario's own plant).
        seed: Base seed (default: the scenario's ``seed``; a scenario without one is an
            error, because CLAUDE.md rule 4 forbids an implicit seed).
        replicate: Repeat index within the cell.
        runs_root: Root of the run store.
        truth: A truth already integrated for this (plant, scenario) — the tiers of one
            cell share it. Recomputed when absent.
        target_feed: Feed an influent fault acts on.
        write: Whether to write the run directory (False is for tests that only want the
            objects).

    Returns:
        The generated run.

    Raises:
        ValueError: If no seed is available, or the plant does not match the scenario's.
    """
    started = time.perf_counter()
    tier_id = str(tier)
    plant_cfg = plant or load_plant_config(str(scenario.plant))
    base = scenario.seed if seed is None else seed
    if base is None:
        raise ValueError(
            f"scenario {scenario.id} carries no seed and none was supplied; "
            "no stochastic component may run unseeded (CLAUDE.md rule 4)"
        )
    seeds = RunSeeds.derive(base, plant_cfg.id, replicate)
    rid = run_id(scenario.id, plant_cfg.id, tier_id, base, replicate)
    paths = RunPaths.for_run(rid, runs_root)
    if write:
        paths.create()
    log = CallLog(paths.root) if write else None

    if truth is None:
        truth = simulate_truth(scenario, plant_cfg, seeds, target_feed=target_feed, log=log)

    obs_cfg = load_observation_config()
    record = _logged(
        log,
        "sim.observe",
        {"tier": tier_id, "seed": seeds.observation, "faults": str(truth.plan.observation)},
        lambda: observe(
            truth.channels,
            obs_cfg,
            tier_id,
            seed=seeds.observation,
            faults=truth.plan.observation,
        ),
    )

    adversarial = any(f.type is FaultType.ADVERSARIAL_LOG_NOTE for f in scenario.faults)
    onset = next(
        (f.onset_day for f in scenario.faults if f.type is FaultType.ADVERSARIAL_LOG_NOTE), 0.0
    )
    notes = operator_notes(
        truth.influent.truth.n_days,
        seeds.notes,
        adversarial=adversarial,
        scenario_id=scenario.id,
        adversarial_day=int(onset),
        config=load_log_notes(),
    )

    manifest = RunManifest(
        run_id=rid,
        scenario_id=scenario.id,
        level=scenario.level,
        plant=plant_cfg.id,
        tier=tier_id,
        duration_days=scenario.duration_days,
        n_days=truth.influent.truth.n_days,
        start_doy=truth.influent.truth.start_doy,
        start_weekday=0,
        seeds=seeds.as_dict(),
        fault_layers=declared_faults(scenario),
        target_feed=target_feed,
        notes_seeded=len(notes),
        created_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        git_sha=git_sha(),
        configs=_config_versions(),
    )

    if write:
        write_truth(paths, truth, scenario)
        write_observations(paths, truth, record, notes, obs_cfg.tiers[tier_id])
        # the complete manifest is hidden truth (it names the scenario, every seed and the
        # declared fault layers); only the projection is written where a workflow can reach
        manifest.write(paths.truth_manifest)
        manifest.public().write(paths.manifest)
        write_index_entry(
            truth_store_for(runs_root) / INDEX_FILE,
            {
                "run_id": rid,
                "scenario_id": scenario.id,
                "level": scenario.level,
                "plant": plant_cfg.id,
                "tier": tier_id,
                "seed": base,
                "replicate": replicate,
            },
        )
    return RunArtifacts(
        run_id=rid,
        paths=paths,
        manifest=manifest,
        truth=truth,
        record=record,
        notes=notes,
        workflow_faults=truth.plan.workflow.tool_failure,
        wall_s=time.perf_counter() - started,
    )


def _config_versions() -> object:
    """Declared versions and content hashes of every config a run reads."""
    from sim.adm1.defaults import (
        EXTENSIONS_YAML,
        INITIAL_STATE_RJ2006,
        PARAMS_BSM2,
        PETERSEN_MATRIX,
        SOLVER_DEFAULT,
    )
    from sim.faults.defaults import INJECTION as FAULTS_CONFIG
    from sim.influent.defaults import FEED_FRACTIONATION, GENERATOR_CONFIG
    from sim.observation.defaults import SENSORS
    from sim.plants import CONFIG_DIR as PLANTS_DIR
    from sim.run.notes import LOG_NOTES_CONFIG

    paths = {
        "adm1_extensions": EXTENSIONS_YAML,
        "adm1_initial_state": INITIAL_STATE_RJ2006,
        "adm1_parameters": PARAMS_BSM2,
        "adm1_petersen": PETERSEN_MATRIX,
        "adm1_solver": SOLVER_DEFAULT,
        "faults_injection": FAULTS_CONFIG,
        "faults_log_notes": LOG_NOTES_CONFIG,
        "harness": HARNESS_CONFIG,
        "influent_feed_fractionation": FEED_FRACTIONATION,
        "influent_generator": GENERATOR_CONFIG,
        "observation_sensors": SENSORS,
        "plant_A": PLANTS_DIR / "plant_A.yaml",
        "plant_B": PLANTS_DIR / "plant_B.yaml",
        "plant_C": PLANTS_DIR / "plant_C.yaml",
    }
    versions = {
        "adm1_extensions": load_extensions().version,
        "faults_injection": load_fault_config().version,
        "faults_log_notes": load_log_notes().version,
        "harness": load_harness_config().version,
        "influent_feed_fractionation": load_feed_fractionation().version,
        "influent_generator": load_generator_config().version,
        "observation_sensors": load_observation_config().version,
    }
    return config_versions(paths, versions)


def generate_cells(
    scenario: Scenario,
    plant: PlantConfig,
    tiers: Sequence[str],
    *,
    seed: int | None = None,
    replicate: int = 0,
    runs_root: Path = RUNS_ROOT,
    target_feed: str | None = None,
    write: bool = True,
) -> list[RunArtifacts]:
    """Every tier of one (plant, scenario), sharing a single integration of the truth.

    §6.4: "tiers are observation masks on identical underlying truth". Integrating once and
    masking three times is not only three times cheaper, it is the only way to *guarantee*
    the property rather than rely on two integrations agreeing.
    """
    truth = None
    out = []
    for tier in tiers:
        run = generate_run(
            scenario,
            tier,
            plant=plant,
            seed=seed,
            replicate=replicate,
            runs_root=runs_root,
            truth=truth,
            target_feed=target_feed,
            write=write,
        )
        truth = run.truth
        out.append(run)
    return out
