"""Virtual-plant configuration contract (proposal §6.1, §7, §8).

A plant configuration is *visible* to workflows: it is what an operator would tell a
consultant — declared geometry, set points, feed catalogue, the plant's anchoring
status. The parts of the plant that are deliberately wrong or unknown (the hidden
active-volume error, imperfect mixing) are declared here only as *distributions*; their
realisations are sampled per run with an explicit seed (:mod:`sim.plants`) and written
by the run layer to ``runs/<id>/truth/`` (CLAUDE.md rule 1), never back into a config.

Every quantity carries an explicit unit in its description (CLAUDE.md rule 6). Anchoring
numbers carry their source, so a reviewer can trace each statistic to the dataset or
paper it came from (``anchor/MANIFEST.json``, ``docs/anchor_datasets.md``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_Pos = Annotated[float, Field(gt=0)]
_Frac = Annotated[float, Field(ge=0, le=1)]


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
    n: int | None = Field(default=None, description="Number of observations behind it")

    @model_validator(mode="after")
    def _ordered(self) -> Statistic:
        if not self.p10 <= self.median <= self.p90:
            raise ValueError(
                f"need p10 <= median <= p90, got {self.p10}, {self.median}, {self.p90}"
            )
        return self


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

    error_min: _Frac = Field(description="Smallest |relative error|, fraction of V_liq_declared")
    error_max: _Frac = Field(description="Largest |relative error|, fraction of V_liq_declared")
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

    feed_flow_m3_d: Statistic = Field(description="Total liquid feed to the modelled unit")
    hrt_d: Statistic = Field(description="Hydraulic retention time of the modelled unit")
    srt_d: Statistic | None = Field(
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
    """Residence-time distribution used by the truth model (proposal §6.1)."""

    model: Literal["cstr", "tanks_in_series"] = Field(
        description="'cstr' = ideal mixing; 'tanks_in_series' = n equal CSTRs"
    )
    n_tanks: Annotated[int, Field(ge=1)] = Field(
        default=1, description="Tanks for the series model"
    )
    hidden_dead_volume_fraction: _Frac = Field(
        default=0.0,
        description=(
            "Fraction of V_liq that does not exchange with the feed; 0 when the dead volume "
            "is represented by the hidden active-volume error instead"
        ),
    )
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
    volume_m3_d: Statistic | None = Field(
        default=None, description="Delivered volume to the modelled unit, when known"
    )
    mass_t_fm_d: Statistic | None = Field(
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
    structural_scenarios: tuple[str, ...] = Field(
        default=(), description="Named Level-6/7 scenarios assigned to this plant"
    )
    note: str = ""


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
    feeds: tuple[FeedStream, ...]
    truth_model: TruthModel
    scenario_subset: ScenarioSubset
    open_questions: tuple[str, ...] = Field(
        default=(), description="Design points not yet settled by the lead"
    )

    @model_validator(mode="after")
    def _consistent(self) -> PlantConfig:
        keys = {c.key for c in self.anchor_sources}
        if len(keys) != len(self.anchor_sources):
            raise ValueError("anchor_sources keys must be unique")
        if not self.feeds:
            raise ValueError("a plant needs at least one feed stream")
        names = [f.name for f in self.feeds]
        if len(set(names)) != len(names):
            raise ValueError("feed names must be unique")
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
