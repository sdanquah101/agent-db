"""Virtual-plant configuration contract (proposal §6.1, §7, §8).

A plant configuration is *visible* to workflows: it is what an operator would tell a
consultant — declared geometry, set points, feed catalogue, the plant's anchoring
status. The parts of the plant that are deliberately wrong or unknown (the hidden
active-volume error, imperfect mixing) are declared here only as *distributions*; their
realisations are sampled per run with an explicit seed (:mod:`sim.plants`) and written
by the run layer to ``truth_store/<id>/`` (CLAUDE.md rule 1), never back into a config.

Every quantity carries an explicit unit in its description (CLAUDE.md rule 6). Anchoring
numbers carry their source, so a reviewer can trace each statistic to the dataset or
paper it came from (``anchor/MANIFEST.json``, ``docs/anchor_datasets.md``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scenarios.schema import FaultType

_Pos = Annotated[float, Field(gt=0)]
_Frac = Annotated[float, Field(ge=0, le=1)]
_OpenFrac = Annotated[float, Field(gt=0, lt=1)]

COMPOUND_SCENARIO_IDS: tuple[str, ...] = (
    "compound_drift_feed_bias",
    "compound_sao_inhibition_shift",
)
"""Ids of the Level-7 compound scenarios of proposal §6.3 (two simultaneous faults: pH
drift + feed mislabelling; omitted SAO + ammonia-inhibition shift). Single-fault
scenarios are named by :class:`scenarios.schema.FaultType`."""

SCENARIO_IDS: frozenset[str] = frozenset(f.value for f in FaultType) | frozenset(
    COMPOUND_SCENARIO_IDS
)
"""Every scenario id a plant may assign or exclude."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Anchoring(StrEnum):
    """How a plant's statistics are tied to reality (proposal §6.1, decision 2026-09-02)."""

    STATISTICS = "statistics"
    """Operating envelope and feedstock tables from published summary statistics."""
    DATASET = "dataset"
    """Influent variability, missingness and sensor noise fitted to an open dataset."""


class Citation(_Frozen):
    """Where a number comes from."""

    key: str = Field(description="Short key used in `source` fields, e.g. 'muscatine_daily'")
    reference: str = Field(description="Human-readable reference")
    doi: str | None = Field(default=None, description="DOI, if any")
    manifest_id: str | None = Field(
        default=None, description="Dataset id in anchor/MANIFEST.json, if fetched"
    )


class Statistic(_Frozen):
    """A quantity summarised by its median and 10th/90th percentiles."""

    median: float
    p10: float
    p90: float
    unit: str = Field(description="Unit of all three values")
    source: str = Field(description="Citation key, plus how the number was derived")
    n: Annotated[int, Field(ge=1)] | None = Field(
        default=None, description="Number of observations behind it"
    )

    @model_validator(mode="after")
    def _ordered(self) -> Statistic:
        if not self.p10 <= self.median <= self.p90:
            raise ValueError(
                f"need p10 <= median <= p90, got {self.p10}, {self.median}, {self.p90}"
            )
        return self


class PositiveStatistic(Statistic):
    """A :class:`Statistic` of a strictly positive quantity (volumes, flows, times)."""

    median: _Pos
    p10: _Pos
    p90: _Pos


class NonNegativeStatistic(Statistic):
    """A :class:`Statistic` that may reach zero (batch feeds with no-delivery days)."""

    median: Annotated[float, Field(ge=0)]
    p10: Annotated[float, Field(ge=0)]
    p90: _Pos


class Geometry(_Frozen):
    """Declared reactor geometry — what the operator states, not what is true."""

    V_liq_declared: _Pos = Field(description="Declared active liquid volume, m3")
    V_gas: _Pos = Field(description="Headspace volume, m3")
    units_at_plant: Annotated[int, Field(ge=1)] = Field(
        description="Number of parallel digesters at the real plant; the benchmark models one"
    )
    note: str = Field(default="", description="Which physical unit is modelled and why")


class HiddenActiveVolume(_Frozen):
    """Distribution of the hidden error on the active volume (proposal §6.1: 5 to 15 %).

    The true active volume is ``V_liq_declared * (1 + sign * magnitude)`` with
    ``magnitude ~ Uniform(error_min, error_max)`` and the sign as configured. Sampled per
    run with a seed; the realisation is hidden truth.
    """

    error_min: _OpenFrac = Field(
        description=(
            "Smallest |relative error|, fraction of V_liq_declared; > 0 so a realisation "
            "is never exact"
        )
    )
    error_max: _OpenFrac = Field(
        description=(
            "Largest |relative error|, fraction of V_liq_declared; < 1 so the true volume "
            "stays positive"
        )
    )
    sign: Literal["random", "negative", "positive"] = Field(
        description="'negative' = dead volume only (true < declared); 'random' = either"
    )

    @model_validator(mode="after")
    def _range(self) -> HiddenActiveVolume:
        if self.error_min > self.error_max:
            raise ValueError("error_min must not exceed error_max")
        return self


class Temperature(_Frozen):
    """Heating set point and its observed day-to-day variability."""

    setpoint_K: _Pos = Field(description="Operating temperature set point, K")
    day_sd_K: Annotated[float, Field(ge=0)] = Field(
        description="Standard deviation of the daily-mean temperature about the set point, K"
    )
    p10_K: _Pos = Field(description="10th percentile of daily-mean temperature, K")
    p90_K: _Pos = Field(description="90th percentile of daily-mean temperature, K")
    source: str

    @model_validator(mode="after")
    def _ordered(self) -> Temperature:
        if not self.p10_K <= self.setpoint_K <= self.p90_K:
            raise ValueError("need p10_K <= setpoint_K <= p90_K")
        return self


class Hydraulics(_Frozen):
    """Feed flow and retention time of the modelled unit."""

    feed_flow_m3_d: PositiveStatistic = Field(description="Total liquid feed to the modelled unit")
    hrt_d: PositiveStatistic = Field(description="Hydraulic retention time of the modelled unit")
    srt_d: PositiveStatistic | None = Field(
        default=None, description="Solids retention time as reported by the plant, if any"
    )
    hrt_consistency_tolerance: _Frac = Field(
        description=(
            "Allowed relative mismatch between V_liq_declared / feed median and the HRT "
            "median; plants whose published numbers disagree say so here and in `note`"
        )
    )
    note: str = ""


class Mixing(_Frozen):
    """Mixing as declared in the plant contract: always an ideal CSTR.

    Imperfect mixing (a residence-time distribution) is not a plant property but a
    fault-injection *truth variant* of the Level-6 "Imperfect mixing" scenario (lead's
    decision 2026-09-02, answer 6): recorded here, implemented with the fault-injection
    API.
    """

    model: Literal["cstr"] = Field(description="Ideal CSTR; the only value the contract allows")
    note: str = ""


class Equalisation(_Frozen):
    """A declared, well-mixed buffer between the trucked deliveries and the digester.

    Trucked feed does not go straight into a digester: it is discharged into a receiving or
    blend tank and drawn from there. Muscatine's own plant description says so — the
    high-strength waste is "blended in a 65,000-gal tank" (``configs/plants/plant_B.yaml``) —
    and the omission of that tank was what made a clean Level-0 run on Plant B acidify on
    5 of 12 seeds: a run of large arrivals reached the biomass as an acid pulse rather than
    as a week of slightly heavier feeding (gate G1, 2026-09-03; the lead's ruling 1).

    It is part of the **declared contract**, not hidden truth: a workflow is told the tank
    exists, which feeds pass through it and how big it is, exactly as it is told the
    digester's volume. What stays hidden is the same as ever — the true composition of what
    was delivered into it.

    The model is one continuously stirred buffer per plant, holding the feeds named in
    ``feeds``: inflow is the day's deliveries, outflow is ``V / tau`` with ``tau`` the
    hold-up implied by the tank volume and the long-run buffered flow. Mass is conserved
    exactly and the tank cannot run dry or overflow (:mod:`sim.plants.equalisation`).
    """

    volume_m3: _Pos = Field(
        description="Working volume of the buffer serving the modelled unit, m3"
    )
    feeds: tuple[str, ...] = Field(
        min_length=1, description="Feed ids that pass through the buffer; the rest are direct"
    )
    source: str = Field(description="Where the volume comes from, and how it was apportioned")
    note: str = ""


class Baseline(_Frozen):
    """One **declared** community state a scenario may be staged on (lead's ruling 1, 2026-09-09).

    A plant can be a different digester depending on how its community has acclimated, and
    the difference is not a fault — it is what the plant *is*. Plant A has two such states:
    an **adapted** one, acclimated to its ammonia, where a loss of adaptation is the thing a
    scenario injects; and an **unadapted** one, where the community has not acclimated and
    a different pathway carries the acetate flux.

    They exist as named, declared variants rather than as a burn-in length or an implicit
    consequence of a config edit, because a Level-6 structural row is only meaningful if the
    pathway the fitted model omits is actually carrying flux in the truth — and which state
    the plant is in decides that.

    **Qualitative only** (lead's ruling B5, 2026-09-10). A workflow is told the states
    exist and what kind of digester each is, in words; it is not told which one a run is
    staged on (``baseline`` is redacted from the manifest) and it is not told anything
    numeric about either — the adapted inhibition constant, the measured biomass, acetate
    or ammonia of each state live in the truth-side record :mod:`sim.plants.truth`, which
    the harness reads and a workflow cannot. With the numbers here, the redaction hid
    nothing: the run's own acetate against a published table said which state it was in.
    The schema forbids extra fields, and ``tests/test_truth_isolation.py`` asserts that no
    number appears in these descriptions and that the visible file spells none of the
    truth-side names.
    """

    name: str = Field(description="Identifier a scenario selects with its `baseline` field")
    description: str = Field(description="What kind of digester this baseline is, in words")
    note: str = ""


class FeedStream(_Frozen):
    """One entry of a plant's feed catalogue (identity and delivery pattern only).

    COD fractionation and assay statistics belong to the influent generator (§6.1), not
    here; this is the list an operator would give.
    """

    name: str
    kind: Literal["slurry", "silage", "primary_sludge", "thickened_was", "hsw", "fog"]
    delivery: Literal["continuous", "batch"] = Field(
        description="'continuous' = pumped daily; 'batch' = discrete deliveries"
    )
    volume_m3_d: NonNegativeStatistic | None = Field(
        default=None, description="Delivered volume to the modelled unit, when known"
    )
    mass_t_fm_d: NonNegativeStatistic | None = Field(
        default=None, description="Delivered fresh mass, t/d, for feeds reported by mass"
    )
    zero_days_fraction: _Frac = Field(
        default=0.0, description="Fraction of days with no delivery of this feed"
    )
    schedule: str = Field(default="", description="Delivery pattern in words")
    source: str = ""


class TruthModel(_Frozen):
    """Which truth-model extensions this plant's simulator enables."""

    extensions: tuple[str, ...] = Field(
        description="Names from configs/adm1/extensions.yaml, in state order"
    )
    note: str = ""


class ScenarioSubset(_Frozen):
    """Which scenarios the plant runs (proposal §7; decision 2026-09-02)."""

    factorial: bool = Field(description="Contributes rows to the §7 factorial analysis")
    levels: tuple[Annotated[int, Field(ge=0, le=8)], ...]
    tiers: tuple[Literal["A", "B", "C"], ...]
    assigned_scenarios: tuple[str, ...] = Field(
        default=(),
        description=(
            "Named scenarios that run only on this plant (the ammonia scenarios on A) or "
            "are excluded elsewhere; empty = every scenario of the listed levels"
        ),
    )
    excluded_scenarios: tuple[str, ...] = Field(
        default=(), description="Named scenarios of the listed levels that do not run here"
    )
    note: str = ""

    @model_validator(mode="after")
    def _known_scenarios(self) -> ScenarioSubset:
        for field in ("assigned_scenarios", "excluded_scenarios"):
            unknown = set(getattr(self, field)) - SCENARIO_IDS
            if unknown:
                raise ValueError(
                    f"{field}: unknown scenario ids {sorted(unknown)}; known ids are the "
                    f"FaultType values plus {list(COMPOUND_SCENARIO_IDS)}"
                )
        both = set(self.assigned_scenarios) & set(self.excluded_scenarios)
        if both:
            raise ValueError(f"scenarios both assigned and excluded: {sorted(both)}")
        return self


class AmmoniaEnvelope(_Frozen):
    """The transcribed Plant-A ammonia block of ``configs/plant_a_statistics.yaml``.

    Only the fields the SAO-establishment check and the influent generator read are
    typed; ``digestate_pH`` and ``free_ammonia_kg_N_m3`` are allowed to be null with the
    reason kept in the YAML comments.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    anchor_plant: str
    source: str
    temperature_C: float
    digestate_TAN_kg_N_m3: dict[Literal["min", "max"], _Pos]
    digestate_pH: float | None = None
    free_ammonia_kg_N_m3: float | None = None
    feed_TAN_g_N_per_kg_TS: dict[str, tuple[float, float]]
    feed_TS_percent_FM: dict[str, tuple[float, float]]
    modelled_KI_NH3_acetoclastic_kg_m3: _Pos
    notes: str = ""

    @model_validator(mode="after")
    def _ordered(self) -> AmmoniaEnvelope:
        tan = self.digestate_TAN_kg_N_m3
        if tan["min"] > tan["max"]:
            raise ValueError("digestate_TAN_kg_N_m3: min must not exceed max")
        return self


class PlantConfig(_Frozen):
    """A virtual plant as declared to workflows."""

    id: Literal["A", "B", "C"]
    name: str
    domain: str = Field(description="One line: what kind of plant this is")
    anchoring: Anchoring
    anchor_sources: tuple[Citation, ...]
    geometry: Geometry
    hidden_active_volume: HiddenActiveVolume
    temperature: Temperature
    hydraulics: Hydraulics
    mixing: Mixing
    horizon_days: Annotated[float, Field(gt=0.0)] = Field(
        description="Run length of every cell on this plant, d. Uniform per plant (the "
        "lead's ruling 3 of 2026-09-11): a scenario's own duration_days is its horizon on "
        "its own plant, and the matrix runs it at the horizon of whichever plant the cell "
        "is on (sim.run.matrix.at_plant_horizon)."
    )
    baselines: tuple[Baseline, ...] = Field(
        default=(),
        description="Declared steady states a scenario may be staged on. A plant with none "
        "has exactly one, the ADM1 defaults.",
    )
    default_baseline: str | None = Field(
        default=None,
        description="Which baseline a scenario that names none is staged on. Required when "
        "the plant declares more than one.",
    )
    equalisation: Equalisation | None = Field(
        default=None,
        description="Declared blend/receiving tank the trucked feeds pass through, if any",
    )
    feeds: tuple[FeedStream, ...]
    truth_model: TruthModel
    scenario_subset: ScenarioSubset
    open_questions: tuple[str, ...] = Field(
        default=(), description="Design points not yet settled by the lead"
    )

    def baseline(self, name: str | None = None) -> Baseline | None:
        """The named declared baseline, or the plant's default one.

        Args:
            name: Baseline name, or None for :attr:`default_baseline`.

        Returns:
            The baseline, or None for a plant that declares none (the ADM1 defaults).

        Raises:
            ValueError: If the plant does not declare a baseline of that name. A scenario
                naming a baseline its plant does not have is a broken scenario, not a
                request to fall back to the default.
        """
        wanted = name if name is not None else self.default_baseline
        if wanted is None:
            return None
        for candidate in self.baselines:
            if candidate.name == wanted:
                return candidate
        raise ValueError(
            f"plant {self.id} declares no baseline {wanted!r}; "
            f"it has {sorted(b.name for b in self.baselines)}"
        )

    @model_validator(mode="after")
    def _consistent(self) -> PlantConfig:
        keys = {c.key for c in self.anchor_sources}
        names = [b.name for b in self.baselines]
        if len(set(names)) != len(names):
            raise ValueError("baseline names must be unique")
        if self.default_baseline is not None and self.default_baseline not in names:
            raise ValueError(
                f"default_baseline {self.default_baseline!r} is not one of {sorted(names)}"
            )
        if len(self.baselines) > 1 and self.default_baseline is None:
            raise ValueError(
                f"plant {self.id} declares {len(self.baselines)} baselines and must say "
                "which is the default; a scenario that names none must not get an arbitrary one"
            )
        if self.baselines and self.default_baseline is None:
            raise ValueError("a plant that declares a baseline must name the default one")
        if len(keys) != len(self.anchor_sources):
            raise ValueError("anchor_sources keys must be unique")
        if not self.feeds:
            raise ValueError("a plant needs at least one feed stream")
        names = [f.name for f in self.feeds]
        if len(set(names)) != len(names):
            raise ValueError("feed names must be unique")
        if self.equalisation is not None:
            unknown = set(self.equalisation.feeds) - set(names)
            if unknown:
                raise ValueError(
                    f"equalisation buffers feeds {sorted(unknown)}, which this plant does "
                    f"not declare; its feeds are {sorted(names)}"
                )
            if len(set(self.equalisation.feeds)) != len(self.equalisation.feeds):
                raise ValueError("equalisation.feeds must be unique")
        h = self.hydraulics
        implied = self.geometry.V_liq_declared / h.feed_flow_m3_d.median
        mismatch = abs(implied - h.hrt_d.median) / h.hrt_d.median
        if mismatch > h.hrt_consistency_tolerance:
            raise ValueError(
                f"V_liq_declared / feed median = {implied:.1f} d disagrees with the HRT "
                f"median {h.hrt_d.median:.1f} d by {mismatch:.0%} "
                f"(> {h.hrt_consistency_tolerance:.0%})"
            )
        return self
