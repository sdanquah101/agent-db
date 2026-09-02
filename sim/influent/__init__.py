"""Influent generator (proposal §6.1): feed composition, true fractionation, ADM1 mapping.

What is here now, salvaged from PR #7 and fitted to the frozen plant contract of PR #6:

* :mod:`sim.influent.schema` — the declared feed-fractionation catalogue
  (``configs/influent/feed_fractionation.yaml``, keyed by the feed ids of
  ``configs/plants``; values provisional pending the lead's review);
* :mod:`sim.influent.fractionation` — the seeded Dirichlet draw of each feed's hidden
  true COD fractionation (one ``default_rng(seed)`` stream, deterministic);
* :mod:`sim.influent.mapping` — feed recipe to the 26-state ADM1 influent (flow-weighted,
  COD/VS conversions, OLR and COD loading, TKN consistency against the ADM1 N contents).

What is not here yet: the stochastic delivery process, assay noise and lag, seasonal
drift and mis-logged deliveries (§6.1 "Influent generator"), which a later session adds
on top of these pure functions. This package never writes ``runs/<id>/truth/`` and never
reads it (CLAUDE.md rule 1).
"""

from sim.influent.defaults import CONFIG_DIR, FEED_FRACTIONATION, load_feed_fractionation
from sim.influent.fractionation import (
    TrueFractionations,
    sample_fractionation,
    sample_true_fractionations,
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
    "COD_EQUIVALENTS_KG_COD_PER_KG",
    "COD_STATES",
    "CONFIG_DIR",
    "FEED_FRACTIONATION",
    "FRACTION_NAMES",
    "CODFractionation",
    "FeedFractionation",
    "FeedFractionationCatalogue",
    "TrueFractionations",
    "cod_loading_rate",
    "constant_influent",
    "extension_influent",
    "feed_cod_per_m3",
    "feed_concentrations",
    "feed_tkn",
    "implied_tkn",
    "load_feed_fractionation",
    "mix_feeds",
    "nominal_mass_rates",
    "organic_loading_rate",
    "sample_fractionation",
    "sample_true_fractionations",
    "tkn_consistent",
    "truth_inert_nitrogen",
    "truth_parameters",
]
