"""The on-disk contract of ``runs/<id>/``: what is written where, and what is hidden.

CLAUDE.md rule 1 is a *directory* boundary, so the directory names are declared once, here,
and every reader and writer imports them rather than spelling them out. Three regions:

=====================  ==========================================================
``truth/``             hidden truth. The run harness writes it; the evaluator reads
                       it; nothing under ``workflows/`` may read or import it.
``observations/``      what the tier's mask permits: the sensor record, the
                       operator's feed log, the tier's feed assays, operator notes.
``manifest.json``      the run's provenance. Complete — scenario id, every seed,
``calls.jsonl``        the declared fault layers — and therefore **not** handed to a
                       workflow verbatim; :mod:`state.run_view` returns a redacted
                       projection of it (see :class:`sim.run.manifest.PublicManifest`).
=====================  ==========================================================

The run id is an opaque, deterministic token rather than ``S2-03-PB-TA``: proposal §10
lists "agents leak information via prompts (e.g. scenario names)" as a risk and mitigates
it with randomised scenario ids, and a directory whose name spells out the scenario would
reintroduce exactly that leak the moment a path appeared in a prompt. It is still
reproducible — :func:`run_id` is a hash of the cell, so the same cell always lands in the
same directory — and ``runs/index.jsonl`` maps ids back to cells for the evaluator.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "INDEX_FILE",
    "OBSERVATIONS_DIR",
    "RUNS_ROOT",
    "TRUTH_DIR",
    "RunPaths",
    "run_id",
]

RUNS_ROOT = Path(__file__).resolve().parents[2] / "runs"
"""Default root of the run store (git-ignored)."""

TRUTH_DIR = "truth"
"""Hidden-truth subdirectory. The one name nothing under ``workflows/`` may reference."""

OBSERVATIONS_DIR = "observations"
"""Workflow-visible subdirectory."""

INDEX_FILE = "index.jsonl"
"""Evaluator-side map from opaque run id back to (scenario, plant, tier, seed)."""

_ID_SALT = "ad-agentbench/g1"
"""Fixed salt, so ids are stable across machines but not guessable from a scenario id
alone by anything that does not already have this module."""


def run_id(scenario_id: str, plant: str, tier: str, seed: int, replicate: int = 0) -> str:
    """The opaque directory name of one generation cell.

    Deterministic in the cell (CLAUDE.md rule 4): regenerating a cell overwrites its own
    directory rather than accumulating copies.

    Args:
        scenario_id: Scenario identifier, e.g. ``"S2-03"``.
        plant: Plant id, ``"A"``, ``"B"`` or ``"C"``.
        tier: Instrumentation tier.
        seed: The scenario's base seed for this run.
        replicate: Repeat index within the cell (the §7 seed replicates).

    Returns:
        ``"run_"`` followed by 12 hex characters.
    """
    key = f"{_ID_SALT}|{scenario_id}|{plant}|{tier}|{seed}|{replicate}"
    return "run_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class RunPaths:
    """Every path of one run directory, named once so no caller spells them out."""

    root: Path

    @classmethod
    def for_run(cls, run: str, runs_root: Path = RUNS_ROOT) -> RunPaths:
        """Paths of run ``run`` under a store root."""
        return cls(root=Path(runs_root) / run)

    # -- regions ---------------------------------------------------------------
    @property
    def truth(self) -> Path:
        """The hidden-truth directory."""
        return self.root / TRUTH_DIR

    @property
    def observations(self) -> Path:
        """The workflow-visible directory."""
        return self.root / OBSERVATIONS_DIR

    @property
    def manifest(self) -> Path:
        """The complete run manifest (redacted before a workflow sees it)."""
        return self.root / "manifest.json"

    @property
    def calls(self) -> Path:
        """The provenance log (:mod:`state.provenance`)."""
        return self.root / "calls.jsonl"

    # -- hidden truth ----------------------------------------------------------
    @property
    def truth_parameters(self) -> Path:
        """True ADM1 parameters per integration segment, truth ``N_I``, extensions."""
        return self.truth / "parameters.json"

    @property
    def truth_influent(self) -> Path:
        """True influent series, per-feed true deliveries and true solids."""
        return self.truth / "influent.npz"

    @property
    def truth_fractionation(self) -> Path:
        """True COD fractionation per feed, and any mislabelled redraw."""
        return self.truth / "fractionation.json"

    @property
    def truth_geometry(self) -> Path:
        """Realised active-volume error and the realised mixing structure."""
        return self.truth / "geometry.json"

    @property
    def truth_states(self) -> Path:
        """The full state trajectory of the truth model."""
        return self.truth / "states.npz"

    @property
    def truth_channels(self) -> Path:
        """Every observable channel and the condition flags behind missingness."""
        return self.truth / "channels.npz"

    @property
    def truth_faults(self) -> Path:
        """The fault plan, its labels and the scenario's answer key."""
        return self.truth / "faults.json"

    # -- observations ----------------------------------------------------------
    @property
    def sensors(self) -> Path:
        """The tier's :class:`~sim.observation.model.ObservationRecord`."""
        return self.observations / "sensors.json"

    @property
    def feed_log(self) -> Path:
        """The operator's feed log, kg wet/d per feed per day."""
        return self.observations / "feed_log.csv"

    @property
    def feed_assays(self) -> Path:
        """The tier's feed assays, with report days and units."""
        return self.observations / "feed_assays.csv"

    @property
    def operator_notes(self) -> Path:
        """The operator's log notes, including any Level-8 adversarial note."""
        return self.observations / "operator_notes.json"

    def create(self) -> RunPaths:
        """Create the run directory and both regions, and return self."""
        self.truth.mkdir(parents=True, exist_ok=True)
        self.observations.mkdir(parents=True, exist_ok=True)
        return self
