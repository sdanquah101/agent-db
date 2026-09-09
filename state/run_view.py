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

* the run root is **not an attribute at all** — it is captured in the closures
  :func:`open_run` builds, so ``view._root`` does not exist to be read (lead's ruling E,
  2026-09-09; a private attribute would have left the same object graph one underscore
  away). A closure cell is still reachable by a determined caller, which is why the
  structural layer above is the one that actually protects truth;
* every accessor returns **file contents**, never a :class:`~pathlib.Path`: a path is a
  capability, and handing one out re-creates the field this ruling removed;
* the resolver rejects ``"."`` and ``""`` (both name the observations directory itself),
  absolute paths, traversal and symlinks out of the tree, all with
  :class:`TruthAccessError`;
* :attr:`RunView.files` enumerates only what is inside the observations directory **and
  only what the resolver would actually return**, so the listing never advertises a
  planted symlink that a read would then refuse;
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
from collections.abc import Callable
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

    **The run directory is not an attribute of this object.** It is captured in the
    closures below, built by :func:`open_run`, so ``view._root`` does not exist to be read
    (lead's ruling E, 2026-09-09). The review's second bypass was a *public* field; making
    it private would have left the same object graph one underscore away. A closure cell is
    still reachable by a caller determined enough to walk ``__closure__``, and that is
    stated rather than glossed: the layer that actually protects hidden truth is that it is
    **not under this directory at all** (:mod:`sim.run.layout`). This one removes the
    accident, not the adversary.
    """

    _read_file: Callable[[str], str]
    """Read one observation file's text, or raise :class:`TruthAccessError`."""
    _list_files: Callable[[], tuple[str, ...]]
    """Every readable observation file, relative to the observations directory."""
    _read_manifest: Callable[[], PublicManifest]
    """The redacted manifest of this run."""

    @property
    def files(self) -> tuple[str, ...]:
        """Every readable file, as paths relative to the observations directory.

        **Only what :meth:`read_text` would actually return.** A planted symlink pointing
        out of the tree used to be listed here and then refused on read; the listing and
        the resolver now agree, so the view never advertises something it will not hand
        over (lead's ruling E).
        """
        return self._list_files()

    def read_text(self, relative: str) -> str:
        """The contents of one observation file.

        Raises:
            TruthAccessError: If the path leaves the observations directory.
            FileNotFoundError: If the file does not exist.
        """
        return self._read_file(relative)

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
        return self._read_manifest()

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


def _resolver(base: Path) -> Callable[[str], Path]:
    """Build the path resolver of one run, closed over its observations directory.

    Private, and it stays private: returning a path is handing over a capability, and the
    caller could walk it upwards. The public accessors read through it.

    Args:
        base: The resolved observations directory.

    Returns:
        A function resolving a caller-supplied relative path to a file strictly inside
        ``base``, raising :class:`TruthAccessError` otherwise.
    """

    def resolve(relative: str) -> Path:
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

    return resolve


def open_run(run_dir: str | Path) -> RunView:
    """Open a run directory for a workflow.

    The run root is captured in the returned view's closures and is never stored on it, so
    there is no attribute to read it back from (lead's ruling E, 2026-09-09).

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
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{root} has no manifest.json")
    base = (root / OBSERVATIONS_DIR).resolve()
    resolve = _resolver(base)

    def read_file(relative: str) -> str:
        return resolve(relative).read_text(encoding="utf-8")

    def list_files() -> tuple[str, ...]:
        if not base.is_dir():
            return ()
        readable = []
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(base))
            try:
                resolve(relative)
            except TruthAccessError:
                # a planted symlink out of the tree: read_text would refuse it, so the
                # listing must not advertise it (lead's ruling E)
                continue
            readable.append(relative)
        return tuple(readable)

    def read_manifest() -> PublicManifest:
        return PublicManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))

    return RunView(_read_file=read_file, _list_files=list_files, _read_manifest=read_manifest)
