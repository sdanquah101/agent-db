"""The workflow-facing view of a run: observations and nothing else (CLAUDE.md rule 1).

Rule 1 says hidden truth "is never readable by workflows" and asks for a test. The first
version of this module enforced that with a path sandbox, and the gate-G1 review broke it
twice on a real run without once writing the word ``truth``, so the static checker in
``tests/test_truth_isolation.py`` saw neither:

* ``root`` was a public dataclass field, so ``view.root / "truth" / "parameters.json"``
  read the true parameters outright — no traversal, no string the checker could match;
* ``view.path(".")`` was accepted, because the containment test read
  ``resolved != base and base not in resolved.parents`` and ``"."`` resolves *to* ``base``.
  It returned the observations directory, whose ``.parent`` is the run root.

Both were containment bugs in a sandbox that only had to be leak-proof because hidden truth
was sitting one level above it. The lead's ruling of 2026-09-04 removed that condition
rather than patching the sandbox a third time, and hardened the sandbox as well:

**Structural.** Hidden truth is a separate top-level tree, ``truth_store/<id>/``
(:mod:`sim.run.layout`). ``runs/<id>/`` holds the observations, the **redacted** manifest —
written redacted, not redacted on the way out — and the call log. A workflow rooted there
has nothing to escape *to*: the worst a containment bug can hand it is its own run.

**Defence in depth**, all of it, because "there is nothing to find" is a property of the
directory layout and this module should not depend on it:

* the run root is a **private** attribute, so no accessor hands a caller a foothold;
* every accessor returns **file contents**, never a :class:`~pathlib.Path`: a path is a
  capability, and handing one out re-creates the field this ruling removed;
* the resolver rejects ``"."`` and ``""`` (both name the observations directory itself),
  absolute paths, traversal and symlinks out of the tree, all with
  :class:`TruthAccessError`;
* :attr:`RunView.files` enumerates only what is inside the observations directory;
* the manifest is :class:`~sim.run.manifest.PublicManifest`, with no field for the
  scenario, the seeds or the fault layers (proposal §10).

The AST checker stays as the second layer: it catches the careless case in code that is
never executed, which no runtime sandbox can do.

What a workflow gets is exactly the benchmark card's visible column (§4): the sensor record
at its tier, the operator's feed log, the tier's feed assays, the operator's notes, and
enough provenance to know which simulator produced them.

The evaluator does not use this module — it reads ``truth_store/<id>/`` directly, which is
the point of the two being different code paths.
"""

from __future__ import annotations

import io
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
    """A read-only, observations-only window onto one run.

    Construct with :func:`open_run`. Every accessor returns *contents* — text, JSON,
    arrays, a validated manifest — and none returns a path or a directory, so there is no
    handle a caller can walk upwards from.
    """

    _root: Path
    """``runs/<id>/``. Private: an accessor for it would be a bypass of everything below."""

    # -- the sandbox ----------------------------------------------------------------
    @property
    def _base(self) -> Path:
        """The observations directory, resolved."""
        return (self._root / OBSERVATIONS_DIR).resolve()

    def _resolve(self, relative: str) -> Path:
        """Resolve ``relative`` to a file strictly inside the observations directory.

        Private, and it stays private: returning a path is handing over a capability, and
        the caller could walk it upwards. The public accessors read through it.

        Args:
            relative: A path relative to ``runs/<id>/observations/``, naming a file.

        Returns:
            The resolved path.

        Raises:
            TruthAccessError: If the path is empty, absolute, names the observations
                directory itself (``""``, ``"."``, ``"./"``), or resolves outside it —
                which is what asking for hidden truth looks like, however it is spelled.
                Symlinks are followed *before* the check, so a link out is not a door.
        """
        if not isinstance(relative, str) or not relative.strip():
            raise TruthAccessError(
                f"{relative!r}: a run view reads a named file inside its observations "
                "directory; the empty path names the directory itself"
            )
        candidate = Path(relative)
        if candidate.is_absolute():
            raise TruthAccessError(
                f"{relative!r}: a run view takes paths relative to its observations "
                "directory, never absolute ones"
            )
        base = self._base
        resolved = (base / candidate).resolve()
        if resolved == base:
            raise TruthAccessError(
                f"{relative!r} resolves to the observations directory itself. A run view "
                "reads files, not directories: a directory handle is a foothold "
                "(CLAUDE.md rule 1)."
            )
        if base not in resolved.parents:
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
        return self._resolve(relative).read_text(encoding="utf-8")

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

        ``runs/<id>/manifest.json`` is written redacted (the complete manifest — scenario,
        seeds, fault layers — is in the truth store), so this validates the file as it
        stands rather than projecting a secret it was handed.
        """
        raw = json.loads((self._root / "manifest.json").read_text(encoding="utf-8"))
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

        return read_feed_log(io.StringIO(self.read_text("feed_log.csv")))

    def feed_assays(self) -> list[dict[str, Any]]:
        """The feed assays this tier may see, ordered by report day."""
        from sim.run.artifacts import read_feed_assays

        return read_feed_assays(io.StringIO(self.read_text("feed_assays.csv")))

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
    return RunView(_root=root)
