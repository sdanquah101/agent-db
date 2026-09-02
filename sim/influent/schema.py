"""Typed schemas of the feed-fractionation catalogue (proposal §6.1, influent generator).

A :class:`FeedFractionation` is what the influent generator knows about one feed of the
plant catalogue (:class:`sim.plants.schema.FeedStream` carries the feed's identity and
delivery pattern only, by the frozen plant decision of 2026-09-02): total-solids and
volatile-solids content, COD per VS, the six-way COD fractionation that maps onto the
ADM1 influent classes and its declared spread, and the dissolved species the feed
carries. The catalogue lives in ``configs/influent/feed_fractionation.yaml``, keyed by the
feed id used in the plant configurations.

Every numeric field carries its unit in the field description (CLAUDE.md rule 6). Solids
are on a stated wet (fresh-matter) or dry basis; dissolved species are per m3 of wet feed.
All models are frozen and reject unknown fields.

The values in the catalogue are **provisional**: the plant decision deliberately deferred
feed fractionation to the influent generator, and the numbers carried here come from the
superseded PR #7 for the lead's review (``docs/decisions.md``, "Feed fractionation values
are provisional").
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sim.plants.schema import FeedStream

_Frac = Annotated[float, Field(ge=0.0, le=1.0)]
_Pos = Annotated[float, Field(gt=0.0)]
_NonNeg = Annotated[float, Field(ge=0.0)]

#: COD fraction names of a feed, in the order the influent builder uses them.
FRACTION_NAMES: tuple[str, ...] = ("f_ch", "f_pr", "f_li", "f_xi", "f_si", "f_vfa")

#: Tolerance on "fractions sum to one" for a declared catalogue entry.
FRACTION_SUM_TOL = 1e-9

#: COD equivalents of the four degradable classes, kg COD per kg of the class (VS mass).
#: Carbohydrates 1.19, proteins 1.42, lipids 2.90 are the VDI 4630 theoretical methane
#: yields (0.415 / 0.496 / 1.014 m3 CH4 STP per kg) divided by 0.35 m3 CH4 per kg COD;
#: VFA as acetate 1.07 (stoichiometric, CH3COOH + 2 O2). The two INERT classes are not
#: here: their equivalent is **per feed** (``FeedFractionation.inert_cod_equivalent``,
#: lead's freeze of 2026-09-02, "Silage basis and per-feed inert COD equivalent"),
#: because a lignocellulosic inert and a sludge-derived inert are different materials.
COD_EQUIVALENTS_KG_COD_PER_KG: dict[str, float] = {
    "f_ch": 1.19,
    "f_pr": 1.42,
    "f_li": 2.90,
    "f_vfa": 1.07,
}

#: The two inert COD fractions, whose equivalent is declared per feed.
INERT_FRACTION_NAMES: tuple[str, ...] = ("f_xi", "f_si")

#: Feed kinds a catalogue entry may declare: the kinds of the plant contract
#: (:class:`sim.plants.schema.FeedStream`) plus ``food_waste``, which PR #7 carried and no
#: frozen plant uses (tested to stay a superset of the contract's kinds).
FeedKind = Literal[
    "slurry", "silage", "food_waste", "primary_sludge", "thickened_was", "hsw", "fog"
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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

    def equivalents(self, inert_cod_equivalent: float) -> dict[str, float]:
        """Class COD equivalents with the feed's own inert value, kg COD/kg."""
        if not inert_cod_equivalent > 0.0:
            raise ValueError(f"inert COD equivalent must be positive, got {inert_cod_equivalent}")
        return COD_EQUIVALENTS_KG_COD_PER_KG | dict.fromkeys(
            INERT_FRACTION_NAMES, float(inert_cod_equivalent)
        )

    def cod_per_vs(self, inert_cod_equivalent: float) -> float:
        """COD per kg of volatile solids implied by this fractionation, kg COD/kg VS.

        With COD shares ``f_i`` and class equivalents ``e_i`` (kg COD/kg), the mass share
        of class ``i`` is ``(f_i/e_i) / sum_j(f_j/e_j)`` and one kg of VS carries
        ``1 / sum_j(f_j/e_j)`` kg COD. Derived, never declared (lead's decision
        2026-09-02): the catalogue's literature value is a check, not an input. The inert
        equivalent is the feed's own (``FeedFractionation.inert_cod_equivalent``).
        """
        e = self.equivalents(inert_cod_equivalent)
        return 1.0 / sum(getattr(self, n) / e[n] for n in FRACTION_NAMES)

    def mass_shares(self, inert_cod_equivalent: float) -> dict[str, float]:
        """Mass share of each class in the volatile solids, kg/kg VS (sums to one)."""
        e = self.equivalents(inert_cod_equivalent)
        cod_per_vs = self.cod_per_vs(inert_cod_equivalent)
        return {n: getattr(self, n) / e[n] * cod_per_vs for n in FRACTION_NAMES}


class FeedFractionation(_Frozen):
    """One catalogue entry: the declared composition of a feed.

    Solids are on a wet (fresh-matter, FM) basis for ``ts`` and a dry basis for ``vs_of_ts``.
    Concentrations of dissolved species are per m3 of wet feed. ``fractionation`` is the
    *declared* (catalogue) fractionation; the hidden true fractionation of a run is a
    seeded Dirichlet draw around it (:mod:`sim.influent.fractionation`). COD per VS is
    **derived** from the fractionation (:attr:`CODFractionation.cod_per_vs`); the
    literature or measured value is carried as ``cod_per_vs_literature`` and must agree
    with the derived one within ``cod_per_vs_tolerance`` (validated here and tested).
    """

    feed_id: str = Field(description="Catalogue key; equals FeedStream.name in configs/plants")
    kind: FeedKind = Field(description="Feed kind, as in the plant contract's FeedStream.kind")
    status: Literal["provisional"] = Field(
        description="'provisional' until the lead freezes the value (decisions log)"
    )
    description: str = Field(description="What the feed is and where its numbers come from")
    density: _Pos = Field(description="Bulk density of the wet feed, kg/m3")
    ts: _Frac = Field(description="Total solids, kg TS/kg wet (fresh-matter basis)")
    vs_of_ts: _Frac = Field(description="Volatile solids, kg VS/kg TS (dry basis)")
    inert_cod_equivalent: _Pos = Field(
        description=(
            "COD equivalent of this feed's inerts (X_I, S_I), kg COD/kg VS mass; ~1.2 for "
            "lignocellulosic inerts (slurry, silage) and 1.4-1.5 for sludge-derived inerts "
            "(the Muscatine feeds, and by documented assumption FOG and food waste). "
            "Lead's freeze 2026-09-02; sources per entry in the catalogue"
        )
    )
    cod_per_vs_literature: _Pos = Field(
        description=(
            "Literature or measured total COD per volatile solids, kg COD/kg VS; a CHECK "
            "on the value derived from the fractionation, not an input"
        )
    )
    cod_per_vs_tolerance: _Frac = Field(
        description=(
            "Accepted relative gap between the derived COD/VS and `cod_per_vs_literature`, -"
        )
    )
    ph: Annotated[float, Field(ge=0.0, le=14.0)] = Field(
        description="pH of the wet feed as delivered, pH units (a routine assay of the generator)"
    )
    fractionation: CODFractionation = Field(description="Declared (catalogue) COD fractionation")
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
    inert_N_I: _NonNeg = Field(
        description=(
            "N content of this feed's inerts (X_I, S_I), kmol N/kg COD; the value under "
            "which the declared `tkn` is consistent with the fractionation (BSM2 N_I "
            "0.00429 for sludge-derived inerts, less for lignocellulosic and food-waste "
            "inerts). Applied by the truth model; the fitted model keeps the ADM1 default "
            "(lead's decision 2026-09-02, an intentional structural mismatch)"
        )
    )
    s_ic: _NonNeg = Field(description="Inorganic carbon of the wet feed, kmol C/m3")
    s_cat: _NonNeg = Field(description="Strong (monovalent) cations of the wet feed, kmol/m3")
    s_an: _NonNeg = Field(description="Strong (monovalent) anions of the wet feed, kmol/m3")
    s_ca: _NonNeg = Field(
        default=0.0,
        description="Dissolved calcium of the wet feed, kmol/m3 (precipitation extension)",
    )

    @model_validator(mode="after")
    def _nitrogen_ordered(self) -> FeedFractionation:
        if self.tan > self.tkn:
            raise ValueError(f"{self.feed_id}: ammoniacal N ({self.tan}) exceeds TKN ({self.tkn})")
        return self

    @model_validator(mode="after")
    def _cod_per_vs_checks(self) -> FeedFractionation:
        derived, lit = self.cod_per_vs, self.cod_per_vs_literature
        gap = abs(derived - lit) / lit
        if gap > self.cod_per_vs_tolerance:
            raise ValueError(
                f"{self.feed_id}: COD/VS derived from the fractionation ({derived:.3f}) "
                f"differs from the literature value ({lit:.3f}) by {gap:.1%} "
                f"(> {self.cod_per_vs_tolerance:.0%})"
            )
        return self

    @property
    def cod_per_vs(self) -> float:
        """Total COD per volatile solids derived from the declared fractionation, kg COD/kg VS."""
        return self.fractionation.cod_per_vs(self.inert_cod_equivalent)

    @property
    def cod_per_kg_wet(self) -> float:
        """Total COD per kg of wet feed, kg COD/kg (declared fractionation)."""
        return self.ts * self.vs_of_ts * self.cod_per_vs

    @property
    def cod_per_m3(self) -> float:
        """Total COD per m3 of wet feed, kg COD/m3."""
        return self.cod_per_kg_wet * self.density

    @property
    def vs_per_kg_wet(self) -> float:
        """Volatile solids per kg of wet feed, kg VS/kg."""
        return self.ts * self.vs_of_ts


class FeedFractionationCatalogue(_Frozen):
    """The declared catalogue, keyed by feed id (``configs/influent/feed_fractionation.yaml``)."""

    version: int = Field(description="Config schema version")
    feeds: dict[str, FeedFractionation] = Field(description="Feed id -> declared composition")

    @model_validator(mode="after")
    def _keys_match(self) -> FeedFractionationCatalogue:
        for key, spec in self.feeds.items():
            if spec.feed_id != key:
                raise ValueError(f"catalogue key {key!r} != feed_id {spec.feed_id!r}")
        return self

    def for_stream(self, feed: FeedStream) -> FeedFractionation:
        """The entry of a plant feed stream, looked up by name and checked for kind.

        Raises:
            KeyError: If the catalogue has no entry for ``feed.name``.
            ValueError: If the entry's kind differs from the stream's kind.
        """
        if feed.name not in self.feeds:
            raise KeyError(f"no feed_fractionation entry for feed {feed.name!r}")
        spec = self.feeds[feed.name]
        if spec.kind != feed.kind:
            raise ValueError(
                f"feed {feed.name!r}: catalogue kind {spec.kind!r} != plant kind {feed.kind!r}"
            )
        return spec
