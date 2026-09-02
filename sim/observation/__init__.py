"""Observation model (proposal §6.1, §6.4): truth channels, sensor models, tier masks.

* :mod:`sim.observation.channels` — the observable quantities of a truth trajectory (pH,
  gas flow and composition, alkalinity, VFA, TAN, COD, digestate solids, the FOS/TAC
  stress index), each with its unit and convention; still hidden truth.
* :mod:`sim.observation.schema` — the declared model of an instrument (schedule, noise,
  bounded-random-walk drift, fouling and flatline episodes, saturation, turnaround,
  conditional missingness) and the tier masks of §6.4.
* :mod:`sim.observation.model` — :func:`observe`, which applies a tier's sensors to a
  run's channels from one seeded stream and returns the workflow-visible record.

Tiers are masks on identical underlying truth: a higher tier only adds channels
(validated by the schema, tested). Nothing here writes files; the run layer owns
``runs/<id>/`` (CLAUDE.md rule 1).
"""

from sim.observation.channels import (
    CHANNEL_UNITS,
    COD_PER_VS_BY_STATE,
    TruthChannels,
    ash_trajectory,
    channel_series,
    channels_from_two_zone,
    condition_flags,
    influent_ash_concentration,
    influent_inert_cod_equivalent,
)
from sim.observation.defaults import CONFIG_DIR, SENSORS, load_observation_config
from sim.observation.model import (
    ObservationRecord,
    SensorSeries,
    episode_mask,
    observe,
    sample_times,
)
from sim.observation.schema import (
    ConditionThresholds,
    DriftModel,
    EpisodeModel,
    FoulingModel,
    MissingnessModel,
    MissingnessPolicy,
    NoiseModel,
    ObservationConfig,
    SaturationModel,
    SensorSpec,
    TierSpec,
)

__all__ = [
    "CHANNEL_UNITS",
    "COD_PER_VS_BY_STATE",
    "CONFIG_DIR",
    "SENSORS",
    "ConditionThresholds",
    "DriftModel",
    "EpisodeModel",
    "FoulingModel",
    "MissingnessModel",
    "MissingnessPolicy",
    "NoiseModel",
    "ObservationConfig",
    "ObservationRecord",
    "SaturationModel",
    "SensorSeries",
    "SensorSpec",
    "TierSpec",
    "TruthChannels",
    "ash_trajectory",
    "channel_series",
    "channels_from_two_zone",
    "condition_flags",
    "episode_mask",
    "influent_ash_concentration",
    "influent_inert_cod_equivalent",
    "load_observation_config",
    "observe",
    "sample_times",
]
