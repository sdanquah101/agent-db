"""Influent generator (proposal §6.1): feed composition, true fractionation, dynamics.

* :mod:`sim.influent.schema` — the declared feed-fractionation catalogue
  (``configs/influent/feed_fractionation.yaml``, keyed by the feed ids of
  ``configs/plants``; values provisional pending the lead's freeze). COD/VS is derived
  from the fractionation; the literature value is a checked field.
* :mod:`sim.influent.fractionation` — the seeded Dirichlet draw of each feed's hidden
  true COD fractionation (one ``default_rng(seed)`` stream, deterministic).
* :mod:`sim.influent.mapping` — feed recipe to the 26-state ADM1 influent (flow-weighted,
  derived COD/VS, OLR and COD loading, TKN consistency against the ADM1 N contents).
* :mod:`sim.influent.nitrogen` — the truth model's per-feed inert nitrogen (an
  intentional mismatch with the fitted model's ADM1 default) and the assay TKN.
* :mod:`sim.influent.generator` — the stochastic delivery process, moisture and seasonal
  drift, unrecorded and mis-logged deliveries, routine assays with noise and lag, and the
  daily sample-and-hold :class:`~sim.adm1.schema.Influent`
  (``configs/influent/generator.yaml``; Plant B/C statistics from the Muscatine daily
  file through ``anchor/ingest_muscatine.py``).

This package never writes ``truth_store/<id>/`` and never reads it (CLAUDE.md rule 1):
:class:`~sim.influent.generator.InfluentTruth` is returned to the run layer, which owns
that directory.
"""

from sim.influent.defaults import (
    CONFIG_DIR,
    FEED_FRACTIONATION,
    GENERATOR_CONFIG,
    load_feed_fractionation,
    load_generator_config,
)
from sim.influent.fractionation import (
    TrueFractionations,
    draw_true_fractionations,
    sample_fractionation,
    sample_true_fractionations,
)
from sim.influent.generator import (
    ASSAY_NAMES,
    AssayRecord,
    FeedTruth,
    GeneratedInfluent,
    GeneratorConfig,
    InfluentTruth,
    OperatorRecord,
    PlantGenerator,
    check_generator_against_plant,
    generate_influent,
)
from sim.influent.mapping import (
    COD_STATES,
    cod_loading_rate,
    constant_influent,
    extension_influent,
    feed_cod_per_m3,
    feed_concentrations,
    implied_tkn,
    mix_feeds,
    nominal_mass_rates,
    organic_loading_rate,
    tkn_consistent,
)
from sim.influent.nitrogen import feed_tkn, truth_inert_nitrogen, truth_parameters
from sim.influent.schema import (
    COD_EQUIVALENTS_KG_COD_PER_KG,
    FRACTION_NAMES,
    CODFractionation,
    FeedFractionation,
    FeedFractionationCatalogue,
)

__all__ = [
    "ASSAY_NAMES",
    "COD_EQUIVALENTS_KG_COD_PER_KG",
    "COD_STATES",
    "CONFIG_DIR",
    "FEED_FRACTIONATION",
    "FRACTION_NAMES",
    "GENERATOR_CONFIG",
    "AssayRecord",
    "CODFractionation",
    "FeedFractionation",
    "FeedFractionationCatalogue",
    "FeedTruth",
    "GeneratedInfluent",
    "GeneratorConfig",
    "InfluentTruth",
    "OperatorRecord",
    "PlantGenerator",
    "TrueFractionations",
    "check_generator_against_plant",
    "cod_loading_rate",
    "constant_influent",
    "draw_true_fractionations",
    "extension_influent",
    "feed_cod_per_m3",
    "feed_concentrations",
    "feed_tkn",
    "generate_influent",
    "implied_tkn",
    "load_feed_fractionation",
    "load_generator_config",
    "mix_feeds",
    "nominal_mass_rates",
    "organic_loading_rate",
    "sample_fractionation",
    "sample_true_fractionations",
    "tkn_consistent",
    "truth_inert_nitrogen",
    "truth_parameters",
]
