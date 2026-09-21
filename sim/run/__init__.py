"""The run harness: a scenario cell becomes a ``runs/<id>/`` directory (§6.1, gate G1).

* :mod:`sim.run.layout` — the on-disk contract: ``runs/<id>/`` (observations, the redacted
  manifest, ``calls.jsonl``), the separate ``truth_store/<id>/``, and the opaque run id.
* :mod:`sim.run.seeds` — one seed per stochastic component, in a fixed documented order.
* :mod:`sim.run.manifest` — the complete run manifest, and the redacted projection a
  workflow is given.
* :mod:`sim.run.notes` — the operator's log, including the Level-8 adversarial note.
* :mod:`sim.run.artifacts` — the writers: one for hidden truth, one for observations.
* :mod:`sim.run.harness` — :func:`~sim.run.harness.generate_run`, which wires the
  generator, the truth model, the channels and the tier mask together.
* :mod:`sim.run.matrix` — the §7 generation matrix over plants, scenarios and tiers.

**This package's ``__init__`` deliberately does not import the harness.** The
workflow-facing loader :mod:`state.run_view` needs :class:`sim.run.manifest.PublicManifest`,
and importing it must not drag in the module that knows how to *write* hidden truth. Import
the harness explicitly: ``from sim.run.harness import generate_run``.
"""

from sim.run.layout import (
    INDEX_FILE,
    OBSERVATIONS_DIR,
    RUNS_ROOT,
    TRUTH_STORE,
    TRUTH_STORE_DIR,
    RunPaths,
    run_id,
    truth_store_for,
)
from sim.run.manifest import (
    HARNESS_VERSION,
    REDACTED_FIELDS,
    ConfigVersions,
    PublicManifest,
    RunManifest,
)
from sim.run.seeds import STREAM_ORDER, RunSeeds

__all__ = [
    "HARNESS_VERSION",
    "INDEX_FILE",
    "OBSERVATIONS_DIR",
    "REDACTED_FIELDS",
    "RUNS_ROOT",
    "STREAM_ORDER",
    "TRUTH_STORE",
    "TRUTH_STORE_DIR",
    "ConfigVersions",
    "PublicManifest",
    "RunManifest",
    "RunPaths",
    "RunSeeds",
    "run_id",
    "truth_store_for",
]
