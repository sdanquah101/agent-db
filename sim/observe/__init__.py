"""Observation model (proposal §6.1, §6.4): what an operator sees of the hidden truth.

* :mod:`sim.observe.schema` — the declared contract: one catalogue of channels, the
  instruments that measure them (noise, quantisation, bounded drift, fouling, flatlining,
  saturation, conditional missingness), the tier masks of §6.4, the TS/VS convention and
  the compiled sensor faults the model consumes.
* :mod:`sim.observe.truth` — reactor states as measurable quantities, in stated units,
  with standard conditions on gas volumes and a wet/dry basis on solids.
* :mod:`sim.observe.model` — :func:`observe`, the seeded, pure mapping from truth to an
  operator's record, and the hidden record of what the instruments actually did.
* :mod:`sim.observe.defaults` — the loader for ``configs/observe/observation.yaml``
  (Plant B/C sensor statistics derived from the Muscatine 1-minute SCADA year through
  ``anchor/ingest_muscatine.py``; Plant A's are assumed and marked).

This package never writes ``runs/<id>/truth/`` and never reads it (CLAUDE.md rule 1):
:class:`~sim.observe.model.ObservationTruth` is returned to the run layer, which owns
that directory.
"""

from sim.observe.defaults import (
    CONFIG_DIR,
    OBSERVATION_CONFIG,
    load_observation_config,
)
from sim.observe.model import (
    AssayResult,
    Episode,
    Observation,
    ObservationTruth,
    ObservedRun,
    SensorSeries,
    observe,
    sample_times,
    stress_indicator,
)
from sim.observe.schema import (
    TIER_ORDER,
    Basis,
    ChannelKind,
    ChannelSpec,
    InstrumentModel,
    ObservationConfig,
    SensorEffect,
    SensorFault,
    SolidsConvention,
    StandardConditions,
    StressCoupling,
)
from sim.observe.truth import (
    TruthChannels,
    ash_concentration,
    influent_ash,
    reactor_ash,
    truth_channels,
)

__all__ = [
    "CONFIG_DIR",
    "OBSERVATION_CONFIG",
    "TIER_ORDER",
    "AssayResult",
    "Basis",
    "ChannelKind",
    "ChannelSpec",
    "Episode",
    "InstrumentModel",
    "Observation",
    "ObservationConfig",
    "ObservationTruth",
    "ObservedRun",
    "SensorEffect",
    "SensorFault",
    "SensorSeries",
    "SolidsConvention",
    "StandardConditions",
    "StressCoupling",
    "TruthChannels",
    "ash_concentration",
    "influent_ash",
    "load_observation_config",
    "observe",
    "reactor_ash",
    "sample_times",
    "stress_indicator",
    "truth_channels",
]
