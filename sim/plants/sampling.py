"""Drawing the hidden plant configuration from the declared priors.

:func:`sample_truth` is the only source of randomness in :mod:`sim.plants`. It takes an
explicit seed (CLAUDE.md rule 4) and uses one ``numpy.random.default_rng(seed)`` stream in
a fixed order (active-volume error, mixing, then feeds in sorted name order), so the same
seed always gives the same :class:`~sim.plants.schema.PlantTruth`.

Nothing here writes to disk: the run harness owns ``runs/<id>/truth/``.
"""

from __future__ import annotations

import numpy as np

from sim.plants.schema import (
    FRACTION_NAMES,
    CODFractionation,
    FeedstockTruth,
    MixingTruth,
    PlantDeclared,
    PlantTruth,
)


def sample_active_volume_error(declared: PlantDeclared, rng: np.random.Generator) -> float:
    """``sign * U(magnitude_min, magnitude_max)``; the sign is a fair coin."""
    prior = declared.active_volume_prior
    sign = -1.0 if rng.random() < 0.5 else 1.0
    return sign * rng.uniform(prior.magnitude_min, prior.magnitude_max)


def sample_mixing(declared: PlantDeclared, rng: np.random.Generator) -> MixingTruth:
    """Independent uniform draws of bypass, stagnant fraction and exchange rate."""
    prior = declared.mixing_prior
    return MixingTruth(
        bypass_fraction=float(rng.uniform(*prior.bypass_fraction)),
        stagnant_fraction=float(rng.uniform(*prior.stagnant_fraction)),
        exchange_rate=float(rng.uniform(*prior.exchange_rate)),
    )


def sample_fractionation(
    catalogue: CODFractionation, concentration: float, rng: np.random.Generator
) -> CODFractionation:
    """Dirichlet draw around the catalogue fractionation.

    ``alpha_i = kappa m_i`` over the components with ``m_i > 0``; components the catalogue
    puts at zero stay at zero (a Dirichlet needs strictly positive parameters, and a feed
    with no soluble inerts does not acquire them by sampling).
    """
    mean = np.array(catalogue.as_tuple())
    positive = mean > 0.0
    draw = np.zeros_like(mean)
    draw[positive] = rng.dirichlet(concentration * mean[positive])
    return CODFractionation(**dict(zip(FRACTION_NAMES, (float(v) for v in draw), strict=True)))


def sample_truth(declared: PlantDeclared, seed: int) -> PlantTruth:
    """Draw the hidden configuration of a plant.

    Args:
        declared: The declared plant with its priors.
        seed: Seed of the ``default_rng`` stream.

    Returns:
        The hidden truth. Deterministic in ``(declared, seed)``.
    """
    rng = np.random.default_rng(seed)
    error = sample_active_volume_error(declared, rng)
    mixing = sample_mixing(declared, rng)
    feeds = {
        name: FeedstockTruth(
            name=name,
            fractionation=sample_fractionation(
                spec.fractionation, spec.fractionation_concentration, rng
            ),
        )
        for name, spec in sorted(declared.feedstocks.items())
    }
    return PlantTruth(
        plant_id=declared.id,
        seed=int(seed),
        V_liq_true=declared.V_liq * (1.0 + error),
        active_volume_error=error,
        mixing=mixing,
        feedstocks=feeds,
    )
