"""The on-disk contract of a run: two separate top-level trees, one of them hidden.

CLAUDE.md rule 1 is a *directory* boundary, so the directory names are declared once, here,
and every reader and writer imports them rather than spelling them out.

**Truth is not a subdirectory of the run.** It was, until the G1 review demonstrated two
live bypasses of :mod:`state.run_view` that never spelled the word ``truth`` and so were
invisible to the static checker: the loader's ``root`` was a public field, so
``view.root / "truth" / "parameters.json"`` read the true parameters outright, and
``view.path(".")`` returned the observations directory, whose ``.parent`` is the run root.
Both were containment bugs in a sandbox that only *had* to be leak-proof because hidden
truth was sitting one level above it. So the lead's ruling of 2026-09-04 moved the truth
out of reach instead of patching the sandbox again:

==========================  ==================================================================
``runs/<id>/``              **what a workflow may see, and nothing else.**
``  observations/``         the tier's mask: sensor record, operator feed log, tier feed
                            assays, operator notes.
``  manifest.json``         the **redacted** manifest
                            (:class:`~sim.run.manifest.PublicManifest`) — plant, tier,
                            horizon, provenance. Not the scenario, the seeds or the faults.
``  calls.jsonl``           the provenance log of rule 3, an append-only file of call
                            *fingerprints* (:mod:`state.provenance`); no argument values.
--------------------------  ------------------------------------------------------------------
``truth_store/<id>/``       **hidden truth.** The harness writes it; the evaluator reads it;
                            nothing under ``workflows/`` may read or import it. It carries
                            the run's *complete* manifest too, since the scenario id, the
                            seeds and the declared fault layers are themselves the answer.
``truth_store/index.jsonl`` the evaluator's map from opaque run id back to its cell.
==========================  ==================================================================

A workflow rooted at ``runs/<id>/observations/`` therefore has nothing to escape *to*: the
worst a containment bug could hand it is its own run directory. The two trees are siblings
(``truth_store`` beside ``runs``), so a store built for a test lands beside that test's run
store and never beside the repository's.

The run id is an opaque, deterministic token rather than ``S2-03-PB-TA``: proposal §10
lists "agents leak information via prompts (e.g. scenario names)" as a risk and mitigates
it with randomised scenario ids, and a directory whose name spells out the scenario would
reintroduce exactly that leak the moment a path appeared in a prompt. It is still
reproducible — :func:`run_id` is a hash of the cell, so the same cell always lands in the
same pair of directories.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "INDEX_FILE",
    "OBSERVATIONS_DIR",
    "RUNS_ROOT",
    "TRUTH_STORE",
    "TRUTH_STORE_DIR",
    "RunPaths",
    "run_id",
    "truth_store_for",
]

RUNS_ROOT = Path(__file__).resolve().parents[2] / "runs"
"""Default root of the run store (git-ignored)."""

TRUTH_STORE_DIR = "truth_store"
"""Name of the hidden-truth tree. Nothing under ``workflows/`` may reference it."""

TRUTH_STORE = RUNS_ROOT.parent / TRUTH_STORE_DIR
"""Default root of the hidden-truth store (git-ignored), a sibling of ``runs/``."""

OBSERVATIONS_DIR = "observations"
"""Workflow-visible subdirectory of a run."""

INDEX_FILE = "index.jsonl"
"""Evaluator-side map from opaque run id back to (scenario, plant, tier, seed). It lives in
the **truth store**: it names the scenario of every run, which is the answer key."""


def truth_store_for(runs_root: Path) -> Path:
    """The truth store that belongs beside a given run store.

    One rule with no special case for the repository: the two trees are siblings, so a
    temporary run store gets a temporary truth store and the repository's ``runs/`` gets
    the repository's ``truth_store/``.

    The corollary is that a parent directory holds **one** run store: two run stores
    sharing a parent share a truth store, and two runs of the same cell would then
    overwrite each other's truth. Give each store its own parent (``<tmp>/runs``, not
    ``<tmp1>`` and ``<tmp2>`` beside each other), or pass ``truth_store`` explicitly to
    :meth:`RunPaths.for_run`.

    Args:
        runs_root: Root of a run store.

    Returns:
        ``<runs_root>/../truth_store``.
    """
    return Path(runs_root).parent / TRUTH_STORE_DIR


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
    """Every path of one run, named once so no caller spells them out.

    Two roots, because the run is two trees: :attr:`root` is ``runs/<id>/``, everything a
    workflow may see, and :attr:`truth` is ``truth_store/<id>/``, which is not underneath it.
    """

    root: Path
    """``runs/<id>/`` — observations, the redacted manifest, the call log."""
    truth: Path
    """``truth_store/<id>/`` — hidden truth and the complete manifest. Not under `root`."""

    @classmethod
    def for_run(
        cls, run: str, runs_root: Path = RUNS_ROOT, truth_store: Path | None = None
    ) -> RunPaths:
        """Paths of run ``run`` under a store root.

        Args:
            run: The opaque run id.
            runs_root: Root of the run store.
            truth_store: Root of the truth store (default: :func:`truth_store_for`, the
                sibling of ``runs_root``).
        """
        store = truth_store_for(runs_root) if truth_store is None else Path(truth_store)
        return cls(root=Path(runs_root) / run, truth=store / run)

    # -- regions ---------------------------------------------------------------
    @property
    def observations(self) -> Path:
        """The workflow-visible directory."""
        return self.root / OBSERVATIONS_DIR

    @property
    def manifest(self) -> Path:
        """The **redacted** manifest a workflow may read."""
        return self.root / "manifest.json"

    @property
    def truth_manifest(self) -> Path:
        """The complete manifest: scenario, seeds, fault layers, config hashes, git SHA."""
        return self.truth / "manifest.json"

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
        """Create both trees of the run, and return self."""
        self.truth.mkdir(parents=True, exist_ok=True)
        self.observations.mkdir(parents=True, exist_ok=True)
        return self
