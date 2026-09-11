"""The run harness: one scenario cell in, two directories out (§6.1, gate G1).

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
        +-> runs/<id>/{observations/, manifest.json (redacted), calls.jsonl}
        +-> truth_store/<id>/ ....... hidden truth and the complete manifest

**Three properties this module exists to hold.**

*Hidden truth is separated at the point it is produced.* Every quantity that identifies the
answer — the true parameters, the true influent and its drift, the true fractionation, the
realised volume error, the realised mixing structure, the state trajectory, the condition
flags, the fault plan and its labels, and the complete manifest — is written under
``truth_store/<id>/``, which since the lead's ruling of 2026-09-04 is a **separate top-level
tree** rather than a subdirectory of the run. Everything a workflow may read is written under
``runs/<id>/``. The two are written by different functions of :mod:`sim.run.artifacts` and
read back by different loaders, and :mod:`state.run_view` (the workflow-facing one) is rooted
at the observations and has nothing above it to reach.

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
directory is still self-contained: it carries its own complete copy of the truth, **and its
own complete call log** — the calls that produced the shared integration are copied into
every tier's log (full and visible), so the evaluator, which reads logs only, sees the
integration behind each of the three tiers rather than only behind the first (final
review, finding F4, 2026-09-10). Deleting one run never damages another.

**No visible wall-clock.** Nothing under ``runs/<id>/`` says *when* it was generated: the
visible manifest has no ``created_utc``, the visible call log has no ``t_utc`` and no
``runtime_s``, and every visible file's modification time is set to one fixed instant
(:data:`VISIBLE_MTIME`). The generation order is a permutation of the public library, and
a permutation that can be recovered from timestamps maps position to cell (final review,
finding F1); the runtime of the burn-in alone marked the one two-zone row (finding F3).
The truth-side copies keep all of it.
"""

from __future__ import annotations

import os
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
from sim.plants.truth import PlantTruthRecord, load_plant_truth
from sim.run.artifacts import write_observations, write_truth
from sim.run.layout import INDEX_FILE, RUNS_ROOT, RunPaths, run_id, store_salt, truth_store_for
from sim.run.manifest import (
    HARNESS_VERSION,
    RunManifest,
    config_versions,
    git_sha,
    write_index_entry,
)
from sim.run.notes import LogNote, load_log_notes, operator_notes
from sim.run.seeds import RunSeeds
from state.provenance import CallLog, read_calls

__all__ = [
    "HARNESS_CONFIG",
    "NO_WRITE_KEY",
    "SIM_API_VERSION",
    "VISIBLE_MTIME",
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
    """Everything hidden about one run. Written only to ``truth_store/<id>/``."""

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


def apply_adaptation(
    params: ADM1Parameters,
    plant: PlantConfig,
    baseline: str | None = None,
    *,
    record: PlantTruthRecord | None = None,
) -> ADM1Parameters:
    """Apply a declared baseline's community adaptation to the truth parameters.

    The baseline is *named* by the visible contract and *defined* by the truth-side record
    (:mod:`sim.plants.truth`, lead's ruling B5 of 2026-09-10): the contract says the state
    exists, the record says what constant its community carries. A plant with no record
    keeps the ADM1 defaults untouched — Plants B and C always — and so does a baseline the
    record gives no adaptation, which is Plant A's ``unadapted`` one, the state its Level-6
    structural row is staged on (lead's ruling 1, 2026-09-09).

    Args:
        params: The truth parameters before adaptation.
        plant: The plant's visible configuration.
        baseline: Declared baseline to stage on, or None for the plant's default.
        record: The plant's truth record, if the caller already holds it; loaded otherwise.

    Returns:
        The parameters this baseline's community carries.

    Raises:
        ValueError: If the plant declares no baseline of that name, or its record and
            contract disagree about which baselines exist.
    """
    declared = plant.baseline(baseline)
    if declared is None:
        return params
    truth_record = record if record is not None else load_plant_truth(plant)
    if truth_record is None:
        return params
    block = truth_record.baseline(declared.name).adaptation
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
    _, out, _ = buffer_series(
        buffered.passthrough_q_m3_d, stacked, buffered.hold_up_d, init_window_d=buffered.hold_up_d
    )
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
    log: RunLogs | None = None,
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
        visible_args={"plant": plant.id, "n_days": n_days},
    )
    truth_frac = generated.truth.fractionations.fractionations
    truth_params = truth_parameters(params, catalogue, generated.truth.mean_recipe_kg_d, truth_frac)
    truth_params = apply_adaptation(truth_params, plant, scenario.baseline)
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
        visible_args={"plant": plant.id, "days": cfg.burn_in_days},
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
    integration_started = time.perf_counter()
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
            visible_name="",  # the segment structure is hidden truth (finding B2)
        )
        if not part.success:
            raise RuntimeError(
                f"segment {index} of scenario {scenario.id} on plant {plant.id} failed: "
                f"{part.message}"
            )
        parts.append(part)
        y = np.array(part.y[:, -1], dtype=float)
    if log is not None:
        # ONE visible record for the whole integration, whatever the segment count: the
        # number of segments is the number of parameter-fault onsets, which is hidden
        # truth (finding B2). The full log above has every segment with its real span.
        log.visible.append(
            "sim.simulate_truth",
            SIM_API_VERSION,
            {"plant": plant.id, "n_days": n_days},
            time.perf_counter() - integration_started,
            "ok",
        )

    result = _stitch_extended(parts) if mixing.ideal else _stitch_two_zone(parts)

    # --- channels ------------------------------------------------------------------
    inert = influent_inert_cod_equivalent(catalogue, generated.truth.mean_recipe_kg_d, truth_frac)
    ash = ash_trajectory(result.t, fed_influent, geometry.V_liq, ash_in)
    channels = _logged(
        log,
        "sim.channel_series",
        {"scenario": scenario.id, "n_times": int(result.t.size), "ideal_mixing": mixing.ideal},
        lambda: (
            channel_series(
                result,
                T_op=geometry.T_op,
                inert_cod_equivalent=inert,
                ash=ash,
                physchem=truth_params.physchem,
            )
            if mixing.ideal
            else channels_from_two_zone(
                result,
                T_op=geometry.T_op,
                inert_cod_equivalent=inert,
                ash=ash,
                physchem=truth_params.physchem,
            )
        ),
        visible_args={"n_times": int(result.t.size)},
    )
    obs_cfg = load_observation_config()
    overload, foaming = condition_flags(
        channels,
        vfa_surge_ratio=obs_cfg.conditions.vfa_surge_ratio,
        vfa_median_window_d=obs_cfg.conditions.vfa_median_window_d,
        gas_surge_ratio=obs_cfg.conditions.gas_surge_ratio,
        gas_median_window_d=obs_cfg.conditions.gas_median_window_d,
        foaming_vfa_ratio=obs_cfg.conditions.foaming_vfa_ratio,
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


@dataclass(frozen=True)
class RunLogs:
    """The two call logs of one generation: the complete one and its redacted projection.

    **Why two** (review finding B2, 2026-09-10; the mechanism needed no ruling).
    ``runs/<id>/calls.jsonl`` is declared workflow-visible, and its ``args_hash`` used to
    cover the real arguments of every harness call: the scenario id, the segment index and
    span, the derived influent and observation seeds, the influent and observation fault
    plans as strings, and the realised mixing structure. Every one of those is drawn from a
    small public space -- committed scenario ids, committed seeds, an enumerable fault
    catalogue -- so the hashes inverted: ``75fbaaa4b387afcc`` gave ``('S0-01', 0, 0.0,
    180.0)`` on a real run, and the *number* of segment records alone said whether a
    parameter fault existed. That is CLAUDE.md rule 1 broken through rule 3.

    So the record is kept twice. :attr:`full` lives in ``truth_store/<id>/`` with the real
    arguments and every segment -- the evaluator reads it (rule 3 says evaluation reads
    logs only). :attr:`visible` lives in ``runs/<id>/`` and is a **projection**: the same
    calls, in the same order, with the same outcomes, but hashed over nothing the visible
    manifest does not already state, with the segment structure collapsed to one record,
    and -- since the final review's findings F1 and F3 -- with no timestamp and no runtime.
    A workflow still sees that the simulator ran and whether it succeeded, which is what
    rule 3 is for; it no longer sees which rung of the ladder it is standing on, nor its
    position in the generation order, nor the wall-clock that marked the two-zone row.
    """

    full: CallLog
    """``truth_store/<id>/calls.jsonl``: real arguments, one record per segment."""
    visible: CallLog
    """``runs/<id>/calls.jsonl``: redacted arguments, segments collapsed, no wall-clock."""

    @classmethod
    def fresh(cls, paths: RunPaths) -> RunLogs:
        """Open both logs, starting each over: a generation's log is that generation's.

        The visible log is a *projection* (:class:`state.provenance.CallLog`): its records
        carry no timestamp and no runtime (findings F1 and F3).
        """
        return cls(
            full=CallLog(paths.truth, fresh=True),
            visible=CallLog(paths.root, fresh=True, projection=True),
        )

    def copy_truth_calls(self, shared: RunPaths) -> None:
        """Copy the shared integration's records from another tier's logs into these.

        Every record of the other tier's logs except its observation call, which is that
        tier's own. The full log keeps the copied timestamps and runtimes; the projection
        drops them as it drops its own.
        """
        for source, target in ((shared.truth, self.full), (shared.root, self.visible)):
            for record in read_calls(source):
                if record.name != "sim.observe":
                    target.copy(record)


def _logged(  # noqa: ANN202
    logs: RunLogs | None,
    name: str,
    args: Mapping[str, object],
    call,  # noqa: ANN001
    *,
    visible_args: Mapping[str, object] | None = None,
    visible_name: str | None = None,
):
    """Run ``call``, logging it to both logs when there are logs (CLAUDE.md rule 3).

    ``args`` go to the full, truth-side log. ``visible_args`` go to the workflow-visible
    projection and must contain nothing the visible manifest does not already say; when
    ``None`` the visible record carries an empty argument set. ``visible_name`` renames the
    visible record (the segment calls are collapsed under it, see :func:`simulate_truth`);
    passing it as ``""`` writes no visible record at all.
    """
    if logs is None:
        return call()
    started = time.perf_counter()
    with logs.full.record(name, SIM_API_VERSION, args) as pending:
        try:
            result = call()
        except Exception as exc:
            if visible_name != "":
                logs.visible.append(
                    visible_name or name,
                    SIM_API_VERSION,
                    visible_args or {},
                    time.perf_counter() - started,
                    "error",
                    f"{type(exc).__name__}: {exc}",
                )
            raise
    if visible_name != "":
        logs.visible.append(
            visible_name or name,
            SIM_API_VERSION,
            visible_args or {},
            time.perf_counter() - started,
            pending.outcome,
            pending.detail,
        )
    return result


def generate_run(
    scenario: Scenario,
    tier: str | Tier,
    *,
    plant: PlantConfig | None = None,
    seed: int | None = None,
    replicate: int = 0,
    runs_root: Path = RUNS_ROOT,
    truth: RunTruth | None = None,
    shared_from: RunPaths | None = None,
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
        shared_from: The run the shared ``truth`` was integrated for; its logged calls are
            copied into this run's logs so every tier's record is complete (finding F4).
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
    # keyed with the store's secret, so the id is opaque to anything without it (B1). A
    # no-write generation creates nothing, not even the salt (finding F5): a store that has
    # one keys the id as usual, and one that has none gets a key that is never written down.
    key = store_salt(truth_store_for(runs_root), create=write)
    rid = run_id(
        scenario.id,
        plant_cfg.id,
        tier_id,
        base,
        replicate,
        key=key if key is not None else NO_WRITE_KEY,
    )
    paths = RunPaths.for_run(rid, runs_root)
    if write:
        paths.create()
    log = RunLogs.fresh(paths) if write else None
    if log is not None and truth is not None and shared_from is not None:
        log.copy_truth_calls(shared_from)

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
        visible_args={"tier": tier_id},
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
        baseline=plant_cfg.baseline(scenario.baseline).name
        if plant_cfg.baseline(scenario.baseline) is not None
        else None,
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
        _fix_visible_mtimes(paths.root)
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


VISIBLE_MTIME = 946684800.0
"""Modification time given to every file under ``runs/<id>/``: 2000-01-01T00:00:00Z.

A file's mtime is a timestamp a workflow can read without opening anything, and the
order of generation is the leak of finding F1; so every visible file gets the same fixed
instant. The truth-side tree keeps real mtimes."""

NO_WRITE_KEY = b"ad-agentbench/no-write: an id that is never written anywhere"
"""Key for the run id of a ``write=False`` generation into a store that has no salt.

Not a secret and not meant to be: such an id names nothing on disk. A store that already
has a salt keys a no-write id with it, so an in-memory generation agrees with the written
one (finding F5)."""


def _fix_visible_mtimes(run_root: Path) -> None:
    """Set every visible file's and directory's atime and mtime to :data:`VISIBLE_MTIME`."""
    for path in run_root.rglob("*"):
        os.utime(path, (VISIBLE_MTIME, VISIBLE_MTIME))
    os.utime(run_root, (VISIBLE_MTIME, VISIBLE_MTIME))


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
    out: list[RunArtifacts] = []
    for tier in tiers:
        run = generate_run(
            scenario,
            tier,
            plant=plant,
            seed=seed,
            replicate=replicate,
            runs_root=runs_root,
            truth=truth,
            shared_from=out[0].paths if out and write else None,
            target_feed=target_feed,
            write=write,
        )
        truth = run.truth
        out.append(run)
    return out
