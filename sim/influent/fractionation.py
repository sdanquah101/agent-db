"""Seeded draw of the hidden true COD fractionation of every feed (proposal §6.1).

The influent generator emits "a *true* COD fractionation drawn from a per-feed
distribution" alongside the routine assays an operator sees. This module is that draw:
a Dirichlet around the declared catalogue fractionation with the feed's declared
concentration, from one ``numpy.random.default_rng(seed)`` stream consumed in sorted
feed-id order, so the same seed always gives the same :class:`TrueFractionations`
(CLAUDE.md rule 4). The stochastic *dynamics* of the generator (delivery process,
seasonal drift, mis-logged masses) are a later session's work and will consume the same
stream after this draw.

The result is hidden truth. Nothing here writes to disk: the run layer owns
``runs/<id>/truth/`` (CLAUDE.md rule 1), and this package never reads that path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np

from sim.influent.schema import (
    FRACTION_NAMES,
    CODFractionation,
    FeedFractionation,
    FeedFractionationCatalogue,
)


def sample_fractionation(
    catalogue: CODFractionation, concentration: float, rng: np.random.Generator
) -> CODFractionation:
    """Dirichlet draw around the catalogue fractionation.

    ``alpha_i = kappa m_i`` over the components with ``m_i > 0``; components the catalogue
    puts at zero stay at zero (a Dirichlet needs strictly positive parameters, and a feed
    with no soluble inerts does not acquire them by sampling). The draw consumes exactly
    one Dirichlet variate of ``rng``.
    """
    if not concentration > 0.0:
        raise ValueError(f"Dirichlet concentration must be positive, got {concentration}")
    mean = np.array(catalogue.as_tuple())
    positive = mean > 0.0
    draw = np.zeros_like(mean)
    draw[positive] = rng.dirichlet(concentration * mean[positive])
    return CODFractionation(**dict(zip(FRACTION_NAMES, (float(v) for v in draw), strict=True)))


@dataclass(frozen=True)
class TrueFractionations:
    """The per-run realisation of every feed's true COD fractionation. Hidden truth."""

    seed: int
    """Seed of the ``default_rng`` stream the draw was made from."""
    fractionations: Mapping[str, CODFractionation]
    """Feed id -> true fractionation, for every feed that was sampled."""

    def __getitem__(self, feed_id: str) -> CODFractionation:
        """The true fractionation of one feed."""
        return self.fractionations[feed_id]


def draw_true_fractionations(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    feed_ids: Iterable[str],
    rng: np.random.Generator,
    seed: int,
) -> TrueFractionations:
    """The draw of :func:`sample_true_fractionations` from a caller-owned stream.

    The influent generator (:mod:`sim.influent.generator`) owns one stream per run and
    makes this draw first, then consumes the same stream for its dynamics. ``seed`` is
    recorded on the result and must be the seed ``rng`` was created from.
    """
    feeds = catalogue.feeds if isinstance(catalogue, FeedFractionationCatalogue) else catalogue
    ids = sorted(feed_ids)
    if len(set(ids)) != len(ids):
        raise ValueError(f"feed ids must be unique, got {ids}")
    missing = [i for i in ids if i not in feeds]
    if missing:
        raise KeyError(f"no feed_fractionation entry for {missing}")
    drawn = {
        fid: sample_fractionation(
            feeds[fid].fractionation, feeds[fid].fractionation_concentration, rng
        )
        for fid in ids
    }
    return TrueFractionations(seed=int(seed), fractionations=drawn)


def sample_true_fractionations(
    catalogue: FeedFractionationCatalogue | Mapping[str, FeedFractionation],
    feed_ids: Iterable[str],
    seed: int,
) -> TrueFractionations:
    """Draw the hidden true fractionation of the listed feeds for one run.

    Args:
        catalogue: The declared catalogue (or its ``feeds`` mapping).
        feed_ids: Feeds to sample; order is irrelevant (sorted before drawing).
        seed: Seed of the ``default_rng`` stream.

    Returns:
        The realisation. Deterministic in ``(catalogue, feed_ids, seed)``.

    Raises:
        KeyError: If a feed id is not in the catalogue.
        ValueError: If a feed id is listed twice.
    """
    return draw_true_fractionations(catalogue, feed_ids, np.random.default_rng(seed), seed)
