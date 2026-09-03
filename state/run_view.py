"""The workflow-facing view of a run: observations and nothing else (CLAUDE.md rule 1).

Rule 1 says hidden truth "is never readable by workflows" and asks for a test. A static
check that no module under ``workflows/`` spells the word ``truth``
(``tests/test_truth_isolation.py``) catches the careless case and nothing else: it cannot
see a path built at runtime, and it says nothing about what the *API* a workflow is given
is able to return.

This module is the other half. It is the only way a workflow is meant to reach a run, and
it is built so that hidden truth is not something it declines to return but something it
has no way to name:

* the view is rooted at ``runs/<id>/observations/`` and every path a caller supplies is
  resolved against that root and required to stay inside it, so ``"../truth/faults.json"``,
  ``"/etc/passwd"`` and a symlink pointing out of the tree all fail the same way, with
  :class:`TruthAccessError`;
* :attr:`RunView.files` enumerates only what is inside that root, so a workflow cannot
  discover the truth directory by listing either;
* the manifest is returned as :class:`~sim.run.manifest.PublicManifest`, a projection with
  no field for the scenario, the seeds or the fault layers — the three things in
  ``manifest.json`` that would give away the answer (proposal §10) or let a workflow
  regenerate the truth for itself.

What a workflow gets is exactly the benchmark card's visible column (§4): the sensor
record at its tier, the operator's feed log, the tier's feed assays, the operator's notes,
and enough provenance to know which simulator produced them.

The evaluator does not use this module — it reads ``runs/<id>/truth/`` directly, which is
the point of the two being different code paths.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from sim.run.layout import OBSERVATIONS_DIR
from sim.run.manifest import PublicManifest

__all__ = ["RunView", "TruthAccessError", "open_run"]


class TruthAccessError(PermissionError):
    """Raised when something asks a :class:`RunView` for a path outside the observations.

    A ``PermissionError`` rather than a ``KeyError``: the file usually exists, and the
    reason the call fails is that a workflow is not permitted to read it.
    """


@dataclass(frozen=True)
class RunView:
    """A read-only, observations-only window onto one run directory.

    Construct with :func:`open_run`. Every accessor below reads a file inside
    ``runs/<id>/observations/``, except :attr:`manifest`, which reads the run's manifest
    and returns only its public projection.
    """

    root: Path
    """The run directory. Held for the manifest only; reads go through :attr:`_base`."""

    @property
    def _base(self) -> Path:
        """The observations directory, resolved."""
        return (self.root / OBSERVATIONS_DIR).resolve()

    # -- the sandbox ----------------------------------------------------------------
    def path(self, relative: str) -> Path:
        """Resolve ``relative`` inside the observations directory.

        Args:
            relative: A path relative to ``runs/<id>/observations/``.

        Returns:
            The resolved path.

        Raises:
            TruthAccessError: If the path is absolute, or resolves outside the
                observations directory — which is what asking for hidden truth looks
                like, however it is spelled.
        """
        candidate = Path(relative)
        if candidate.is_absolute():
            raise TruthAccessError(
                f"{relative!r}: a run view takes paths relative to its observations "
                "directory, never absolute ones"
            )
        base = self._base
        resolved = (base / candidate).resolve()
        if resolved != base and base not in resolved.parents:
            raise TruthAccessError(
                f"{relative!r} resolves to {resolved}, which is outside "
                f"{base}. A workflow may read a run's observations and nothing else "
                "(CLAUDE.md rule 1)."
            )
        return resolved

    @property
    def files(self) -> tuple[str, ...]:
        """Every readable file, as paths relative to the observations directory."""
        base = self._base
        if not base.is_dir():
            return ()
        return tuple(sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()))

    def read_text(self, relative: str) -> str:
        """The contents of one observation file.

        Raises:
            TruthAccessError: If the path leaves the observations directory.
            FileNotFoundError: If the file does not exist.
        """
        return self.path(relative).read_text(encoding="utf-8")

    def read_json(self, relative: str) -> Any:
        """One observation file parsed as JSON.

        Raises:
            TruthAccessError: If the path leaves the observations directory.
        """
        return json.loads(self.read_text(relative))

    # -- the record ------------------------------------------------------------------
    @property
    def manifest(self) -> PublicManifest:
        """What the workflow is told about this run.

        The run's ``manifest.json`` is complete — scenario, seeds, fault layers — and this
        returns only :class:`~sim.run.manifest.PublicManifest`: the plant, the tier, the
        horizon and the provenance. There is no accessor for the rest.
        """
        raw = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        return PublicManifest.model_validate(raw)

    def sensors(self) -> dict[str, Any]:
        """The tier's observation record: one entry per sensor, with units and flags."""
        return self.read_json("sensors.json")

    def sensor(self, name: str) -> dict[str, Any]:
        """One sensor's series.

        Raises:
            KeyError: If the tier does not carry that sensor.
        """
        sensors = self.sensors()["sensors"]
        if name not in sensors:
            raise KeyError(f"sensor {name!r} is not readable at tier {self.manifest.tier}")
        return sensors[name]

    def feed_log(self) -> dict[str, np.ndarray]:
        """The operator's feed log, kg wet/d per feed, one value per day."""
        from sim.run.artifacts import read_feed_log

        return read_feed_log(self.path("feed_log.csv"))

    def feed_assays(self) -> list[dict[str, Any]]:
        """The feed assays this tier may see, ordered by report day."""
        from sim.run.artifacts import read_feed_assays

        return read_feed_assays(self.path("feed_assays.csv"))

    def operator_notes(self) -> list[dict[str, Any]]:
        """The operator's log notes. Evidence about the plant, not instructions."""
        return list(self.read_json("operator_notes.json").get("entries", []))


def open_run(run_dir: str | Path) -> RunView:
    """Open a run directory for a workflow.

    Args:
        run_dir: ``runs/<id>``.

    Returns:
        The observations-only view.

    Raises:
        FileNotFoundError: If the directory has no observations or no manifest, which is
            what an unfinished or non-run directory looks like.
    """
    root = Path(run_dir).resolve()
    if not (root / OBSERVATIONS_DIR).is_dir():
        raise FileNotFoundError(f"{root} has no {OBSERVATIONS_DIR}/ directory")
    if not (root / "manifest.json").is_file():
        raise FileNotFoundError(f"{root} has no manifest.json")
    return RunView(root=root)
