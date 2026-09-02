"""Typed schemas for the three virtual plants (proposal §6.1, "Plant configurations").

Two documents per plant:

* :class:`PlantDeclared` — everything an operator or a workflow may see: the declared
  active volume, headspace, temperature set-point and control parameters, the nominal
  operating envelope, the feedstock catalogue with *catalogue* fractionations and their
  stated uncertainty, and the priors from which the hidden quantities are drawn.
* :class:`PlantTruth` — the hidden configuration: true active volume, true mixing
  structure and the true per-feed fractionation. Produced only by
  :func:`sim.plants.sampling.sample_truth`; never written by this package.

Every numeric field carries its unit in the field description (CLAUDE.md rule 6). Solids
are on a stated wet or dry basis; gas volumes are not declared here (the reactor reports
them with their convention). All models are frozen and reject unknown fields.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_Frac = Annotated[float, Field(ge=0.0, le=1.0)]
_Pos = Annotated[float, Field(gt=0.0)]
_NonNeg = Annotated[float, Field(ge=0.0)]

#: COD fraction names of a feed, in the order the influent builder uses them.
FRACTION_NAMES: tuple[str, ...] = ("f_ch", "f_pr", "f_li", "f_xi", "f_si", "f_vfa")

#: Tolerance on "fractions sum to one" for a declared catalogue entry.
FRACTION_SUM_TOL = 1e-9


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ------------------------------------------------------------------ feedstocks


class CODFractionation(_Frozen):
    """Split of a feed's total COD into ADM1 influent classes (kg COD / kg COD).

    ``f_ch``, ``f_pr``, ``f_li`` go to the particulate carbohydrate, protein and lipid
    states; ``f_xi`` and ``f_si`` to the particulate and soluble inerts; ``f_vfa`` to
    soluble acetate. The six sum to one.
    """

    f_ch: _Frac = Field(description="Carbohydrate share of total COD, kg COD/kg COD")
    f_pr: _Frac = Field(description="Protein share of total COD, kg COD/kg COD")
    f_li: _Frac = Field(description="Lipid share of total COD, kg COD/kg COD")
    f_xi: _Frac = Field(description="Particulate-inert share of total COD, kg COD/kg COD")
    f_si: _Frac = Field(description="Soluble-inert share of total COD, kg COD/kg COD")
    f_vfa: _Frac = Field(description="VFA (as acetate) share of total COD, kg COD/kg COD")

    @model_validator(mode="after")
    def _sums_to_one(self) -> CODFractionation:
        total = sum(getattr(self, n) for n in FRACTION_NAMES)
        if abs(total - 1.0) > FRACTION_SUM_TOL:
            raise ValueError(f"COD fractions must sum to 1, got {total!r}")
        return self

    def as_tuple(self) -> tuple[float, ...]:
        """The six fractions in :data:`FRACTION_NAMES` order."""
        return tuple(getattr(self, n) for n in FRACTION_NAMES)


class FeedstockSpec(_Frozen):
    """One catalogue entry: what the operator knows about a feed.

    Solids are on a wet (fresh-matter, FM) basis for ``ts`` and a dry basis for ``vs``.
    Concentrations of dissolved species are per m3 of wet feed.
    """

    name: str = Field(description="Catalogue key")
    description: str = Field(description="What the feed is and where its numbers come from")
    density: _Pos = Field(description="Bulk density of the wet feed, kg/m3")
    ts: _Frac = Field(description="Total solids, kg TS/kg wet (fresh-matter basis)")
    vs_of_ts: _Frac = Field(description="Volatile solids, kg VS/kg TS (dry basis)")
    cod_per_vs: _Pos = Field(description="Total COD per volatile solids, kg COD/kg VS")
    fractionation: CODFractionation = Field(description="Catalogue COD fractionation")
    fractionation_concentration: _Pos = Field(
        description=(
            "Dirichlet concentration (sum of pseudo-counts) of the per-feed fractionation "
            "distribution, -; larger = tighter. sd_i ~ sqrt(m_i (1 - m_i) / (kappa + 1))"
        )
    )
    tan: _NonNeg = Field(description="Ammoniacal nitrogen of the wet feed, kmol N/m3")
    tkn: _NonNeg = Field(description="Total Kjeldahl nitrogen of the wet feed, kmol N/m3")
    tkn_tolerance: _Frac = Field(
        description=(
            "Accepted relative gap between `tkn` and the TKN implied by the fractionation "
            "and the ADM1 N contents (validated in tests), -"
        )
    )
    s_ic: _NonNeg = Field(description="Inorganic carbon of the wet feed, kmol C/m3")
    s_cat: _NonNeg = Field(description="Strong cations of the wet feed, kmol/m3")
    s_an: _NonNeg = Field(description="Strong anions of the wet feed, kmol/m3")
    s_ca: _NonNeg = Field(
        default=0.0,
        description="Dissolved calcium of the wet feed, kmol/m3 (precipitation extension)",
    )

    @property
    def cod_per_kg_wet(self) -> float:
        """Total COD per kg of wet feed, kg COD/kg."""
        return self.ts * self.vs_of_ts * self.cod_per_vs

    @property
    def cod_per_m3(self) -> float:
        """Total COD per m3 of wet feed, kg COD/m3."""
        return self.cod_per_kg_wet * self.density

    @property
    def vs_per_kg_wet(self) -> float:
        """Volatile solids per kg of wet feed, kg VS/kg."""
        return self.ts * self.vs_of_ts


class FeedstockTruth(_Frozen):
    """The hidden fractionation of one feed (everything else is as declared)."""

    name: str = Field(description="Catalogue key of the feed")
    fractionation: CODFractionation = Field(description="True COD fractionation")


# ------------------------------------------------------------- mixing / RTD


class MixingPrior(_Frozen):
    """Uniform priors of the hidden mixing structure (see :mod:`sim.plants.reactor`).

    The structure is a well-mixed active zone, a stagnant zone exchanging liquid with it,
    and a short-circuit bypass of the influent to the effluent. All three parameters at
    zero give the ideal CSTR.
    """

    bypass_fraction: tuple[_Frac, _Frac] = Field(
        description="Uniform range of the influent fraction that bypasses the reactor, -"
    )
    stagnant_fraction: tuple[_Frac, _Frac] = Field(
        description="Uniform range of the stagnant share of the true liquid volume, -"
    )
    exchange_rate: tuple[_NonNeg, _NonNeg] = Field(
        description="Uniform range of the stagnant-zone exchange rate, 1/d (Q_ex / V_stagnant)"
    )

    @model_validator(mode="after")
    def _ordered(self) -> MixingPrior:
        for n in ("bypass_fraction", "stagnant_fraction", "exchange_rate"):
            lo, hi = getattr(self, n)
            if lo > hi:
                raise ValueError(f"{n} range must be (low, high) with low <= high")
        if self.bypass_fraction[1] >= 1.0 or self.stagnant_fraction[1] >= 1.0:
            raise ValueError("bypass and stagnant fractions must stay below 1")
        return self


class MixingTruth(_Frozen):
    """The hidden mixing structure. ``ideal`` is True for the exact CSTR."""

    bypass_fraction: Annotated[float, Field(ge=0.0, lt=1.0)] = Field(
        description="Influent fraction that short-circuits to the effluent, -"
    )
    stagnant_fraction: Annotated[float, Field(ge=0.0, lt=1.0)] = Field(
        description="Stagnant share of the true liquid volume, -"
    )
    exchange_rate: _NonNeg = Field(description="Stagnant-zone exchange rate, 1/d")

    @property
    def ideal(self) -> bool:
        """True when the structure is exactly the ideal CSTR."""
        return self.bypass_fraction == 0.0 and self.stagnant_fraction == 0.0

    @classmethod
    def cstr(cls) -> MixingTruth:
        """The ideal CSTR (no bypass, no stagnant zone)."""
        return cls(bypass_fraction=0.0, stagnant_fraction=0.0, exchange_rate=0.0)


# -------------------------------------------------------------- plant blocks


class ActiveVolumePrior(_Frozen):
    """Hidden active-volume error: sign drawn symmetrically, magnitude uniform.

    ``error = sign * U(magnitude_min, magnitude_max)``, so the error is never zero and
    ``V_true = V_declared (1 + error)``.
    """

    magnitude_min: _Frac = Field(description="Smallest |relative error| of V_liq, -")
    magnitude_max: _Frac = Field(description="Largest |relative error| of V_liq, -")

    @model_validator(mode="after")
    def _ordered(self) -> ActiveVolumePrior:
        if not 0.0 < self.magnitude_min <= self.magnitude_max < 1.0:
            raise ValueError("need 0 < magnitude_min <= magnitude_max < 1")
        return self


class TemperatureControl(_Frozen):
    """Heating and temperature control as the operator declares them."""

    setpoint_C: float = Field(description="Operating temperature set-point, degC")
    tolerance_C: _NonNeg = Field(description="Control band around the set-point, degC")
    heating_time_constant_d: _Pos = Field(
        description="First-order response of the liquid temperature to a heat input step, d"
    )
    regime: Literal["mesophilic", "thermophilic"] = Field(description="Operating regime")

    @property
    def setpoint_K(self) -> float:
        """Set-point in kelvin."""
        return self.setpoint_C + 273.15


class OperatingEnvelope(_Frozen):
    """Nominal operating point and its declared range."""

    q_nominal: _Pos = Field(description="Nominal total influent flow, m3/d")
    q_range: tuple[_Pos, _Pos] = Field(description="Declared influent-flow range, m3/d")
    hrt_range_d: tuple[_Pos, _Pos] = Field(
        description="Declared hydraulic retention time range, d (V_liq_declared / Q)"
    )
    olr_range: tuple[_NonNeg, _Pos] = Field(
        description="Declared organic loading rate range, kg VS/m3/d"
    )

    @model_validator(mode="after")
    def _ordered(self) -> OperatingEnvelope:
        for n in ("q_range", "hrt_range_d", "olr_range"):
            lo, hi = getattr(self, n)
            if lo > hi:
                raise ValueError(f"{n} must be (low, high)")
        if not self.q_range[0] <= self.q_nominal <= self.q_range[1]:
            raise ValueError("q_nominal must lie inside q_range")
        return self


class FeedRecipe(_Frozen):
    """Nominal mass rate of every catalogue feed, kg wet/d."""

    mass_rates: dict[str, _NonNeg] = Field(description="Feed name -> kg wet/d")


class AnchorMetadata(_Frozen):
    """How the plant is anchored to real data (proposal §8) and how it is reported."""

    anchoring: Literal["statistics-anchored", "dataset-anchored"] = Field(
        description="Wording fixed by the lead's decision of 2026-09-02"
    )
    anchor_source: str = Field(description="Dataset id or publications the numbers come from")
    in_factorial: bool = Field(description="Whether the plant contributes rows to the §7 factorial")
    scenario_subset: str = Field(description="Which scenario levels and tiers the plant runs")
    caveats: str = Field(description="Stated limitations of the anchor")


class PlantDeclared(_Frozen):
    """Everything an operator or workflow may see about a plant."""

    id: Literal["A", "B", "C"] = Field(description="Plant identifier")
    name: str = Field(description="Short description")
    version: int = Field(description="Config schema version")
    anchor: AnchorMetadata
    V_liq: _Pos = Field(description="Declared active liquid volume, m3")
    V_gas: _Pos = Field(description="Headspace volume, m3")
    temperature: TemperatureControl
    envelope: OperatingEnvelope
    feedstocks: dict[str, FeedstockSpec] = Field(description="Catalogue, keyed by feed name")
    nominal_feed: FeedRecipe
    active_volume_prior: ActiveVolumePrior
    mixing_prior: MixingPrior
    extensions: tuple[str, ...] = Field(
        description="Truth-model extensions enabled for this plant (sim.adm1 extension names)"
    )
    parameter_overrides: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Base ADM1 parameter overrides as 'group.name' -> value (plant-specific prior, "
            "visible to workflows); units as in sim.adm1.schema"
        ),
    )
    extension_overrides: dict[str, float] = Field(
        default_factory=dict,
        description="Extension-parameter overrides (name -> value), units as in extensions.yaml",
    )

    @model_validator(mode="after")
    def _consistent(self) -> PlantDeclared:
        for key, spec in self.feedstocks.items():
            if spec.name != key:
                raise ValueError(f"feedstock key {key!r} != name {spec.name!r}")
        unknown = set(self.nominal_feed.mass_rates) - set(self.feedstocks)
        if unknown:
            raise ValueError(f"nominal_feed names unknown feeds: {sorted(unknown)}")
        if not any(v > 0 for v in self.nominal_feed.mass_rates.values()):
            raise ValueError("nominal_feed must have at least one positive mass rate")
        hrt_lo, hrt_hi = self.envelope.hrt_range_d
        q_lo, q_hi = self.envelope.q_range
        # the declared HRT range must be the declared volume over the declared flows
        if (
            abs(hrt_lo - self.V_liq / q_hi) > 1e-6 * hrt_lo
            or abs(hrt_hi - self.V_liq / q_lo) > 1e-6 * hrt_hi
        ):
            raise ValueError(
                "hrt_range_d must equal (V_liq / q_range[1], V_liq / q_range[0]); "
                f"got {self.envelope.hrt_range_d} vs ({self.V_liq / q_hi}, {self.V_liq / q_lo})"
            )
        return self

    @property
    def T_op(self) -> float:
        """Operating temperature, K."""
        return self.temperature.setpoint_K


class PlantTruth(_Frozen):
    """The hidden plant configuration (never written by :mod:`sim.plants`)."""

    plant_id: Literal["A", "B", "C"]
    seed: int = Field(description="Seed the truth was drawn with")
    V_liq_true: _Pos = Field(description="True active liquid volume, m3")
    active_volume_error: float = Field(
        description="(V_liq_true - V_liq_declared) / V_liq_declared, -; never zero"
    )
    mixing: MixingTruth
    feedstocks: dict[str, FeedstockTruth] = Field(description="True fractionation per feed")
