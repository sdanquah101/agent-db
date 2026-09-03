"""One seed per stochastic component, derived from the scenario's base seed (CLAUDE.md rule 4).

"Every stochastic component takes an explicit seed. No unseeded randomness anywhere."

A run has five stochastic components. Each gets its **own** stream, in a fixed order that
is part of the contract, so that adding a component later appends to the list rather than
reshuffling every existing run:

===  ================  ========================================================
0    ``geometry``      the hidden active-volume error
                       (:func:`sim.plants.sample_hidden_geometry`)
1    ``influent``      the delivery, moisture, mis-log and assay draws
                       (:func:`sim.influent.generate_influent`)
2    ``fault``         the fault layer's own stream (the mislabelled-feed redraw)
3    ``observation``   sensor noise, drift, fouling, flatlines and gaps
                       (:func:`sim.observation.observe`)
4    ``notes``         where the operator's log notes fall (:mod:`sim.run.notes`)
===  ================  ========================================================

**The tier is deliberately not part of the derivation.** §6.4 says a tier is a mask on
identical underlying truth, so two tiers of one cell must be the same digester seen
through different windows: same geometry, same deliveries, same faults — and the same
observation stream, so that every difference between two tiers' records comes from the
tier's own policy (its base missing rate, its laboratory turnaround, its recalibration
cadence) rather than from a different draw. The plant *is* part of it, because Plant B and
Plant C are different digesters.

Derivation is ``numpy.random.SeedSequence`` over the tuple ``(base seed, plant code,
replicate)``, which is the library's own way of turning one seed into independent streams
and is stable across platforms and numpy versions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

__all__ = ["STREAM_ORDER", "RunSeeds"]

STREAM_ORDER: tuple[str, ...] = ("geometry", "influent", "fault", "observation", "notes")
"""The five streams, in the order :meth:`RunSeeds.derive` assigns them. Append only."""

_PLANT_CODE = {"A": 1, "B": 2, "C": 3}


@dataclass(frozen=True)
class RunSeeds:
    """The seed of every stochastic component of one run."""

    base: int
    """The scenario's own seed, as written in its YAML (or supplied by the harness)."""
    plant: str
    replicate: int
    geometry: int
    influent: int
    fault: int
    observation: int
    notes: int

    @classmethod
    def derive(cls, base: int, plant: str, replicate: int = 0) -> RunSeeds:
        """Derive the five streams of a cell from its base seed.

        Args:
            base: The scenario's base seed.
            plant: Plant id (``"A"``, ``"B"`` or ``"C"``): two plants are two digesters,
                so they must not share draws.
            replicate: Repeat index within the cell (the §7 seed replicates).

        Returns:
            The derived seeds.

        Raises:
            ValueError: If the plant id is unknown or the replicate is negative.
        """
        if plant not in _PLANT_CODE:
            raise ValueError(f"unknown plant {plant!r}; expected one of {sorted(_PLANT_CODE)}")
        if replicate < 0:
            raise ValueError(f"replicate must be non-negative, got {replicate}")
        entropy = [int(base), _PLANT_CODE[plant], int(replicate)]
        drawn = np.random.SeedSequence(entropy).generate_state(len(STREAM_ORDER), dtype=np.uint32)
        return cls(
            base=int(base),
            plant=plant,
            replicate=int(replicate),
            **{name: int(value) for name, value in zip(STREAM_ORDER, drawn, strict=True)},
        )

    def as_dict(self) -> dict[str, int | str]:
        """Every field, for the run manifest."""
        return dict(asdict(self))
