"""The sandbox: a workflow process in which the hidden things do not resolve.

The structural defence of decisions 2026-09-12 and design §4: ``sim``, ``scenarios`` and
``truth_store`` are neither importable nor readable from where the workflow runs.

:func:`stage` copies the client stub (:mod:`tools.client`, ``tools.schemas``,
``tools.transport``) into ``<sandbox>/site/tools/`` so that ``import tools`` in the
workflow is the stub. :func:`launch` then runs the workflow script with

* ``python -I -S``: isolated mode (no ``PYTHONPATH``, no user site, no script directory
  on the path) and **no site processing**, so the repository's editable-install hook --
  a ``.pth`` file only ``site`` reads -- never runs and the repository root is never on
  the path;
* ``sys.path`` set by a bootstrap to the standard library, the stub directory and the
  interpreter's package directories (for numpy, scipy, pydantic); a directory on
  ``sys.path`` does not process ``.pth`` files, so the hook stays dormant;
* a **fail-closed check** before the script runs: if ``sim``, ``scenarios``, ``anchor``,
  ``eval`` or ``state`` resolves, or ``tools`` resolves to anything but the stub, the
  process exits without running the workflow (a non-editable install into site-packages
  would trip this, which is the point);
* an empty scratch directory as the working directory, an environment holding the socket
  path and little else, and the registry server listening in *this* process.

What it does not do is stop a workflow that is told an absolute path from opening it:
that is a container's job (design §4, "what it does not buy") and the layout's
(``truth_store/`` is a sibling the workflow is never told the path of). The test drives
the relative routes the requirement names, with a negative control.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import textwrap
from dataclasses import dataclass
from pathlib import Path

from tools.registry import Registry
from tools.server import RegistryServer

__all__ = ["FORBIDDEN_MODULES", "SandboxResult", "launch", "site_directories", "stage"]

FORBIDDEN_MODULES: tuple[str, ...] = ("sim", "scenarios", "anchor", "eval", "state")
"""Modules that must not resolve in the workflow process."""

_PACKAGE_DIR = Path(__file__).resolve().parent


def stage(sandbox: str | Path) -> Path:
    """Copy the client stub into ``<sandbox>/site/tools/`` and return the site directory.

    The stub's ``__init__.py`` is :mod:`tools.client`; ``schemas/`` and ``transport.py``
    are copied from this package so the two sides cannot drift.
    """
    site = Path(sandbox) / "site"
    target = site / "tools"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(_PACKAGE_DIR / "client" / "__init__.py", target / "__init__.py")
    shutil.copy2(_PACKAGE_DIR / "transport.py", target / "transport.py")
    shutil.copytree(
        _PACKAGE_DIR / "schemas",
        target / "schemas",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return site


def site_directories() -> list[str]:
    """The interpreter's package directories (numpy, scipy, pydantic live there).

    Taken from this process's ``sys.path``: the entries that are a ``site-packages`` or
    ``dist-packages`` directory. The repository root and the current directory are not
    among them by construction.
    """
    out: list[str] = []
    for entry in sys.path:
        if not entry:
            continue
        path = Path(entry)
        if path.name in ("site-packages", "dist-packages") and path.is_dir():
            resolved = str(path.resolve())
            if resolved not in out:
                out.append(resolved)
    for key in ("purelib", "platlib"):
        candidate = sysconfig.get_paths().get(key)
        if candidate and Path(candidate).is_dir() and str(Path(candidate).resolve()) not in out:
            out.append(str(Path(candidate).resolve()))
    return out


_BOOTSTRAP = textwrap.dedent(
    """
    import importlib.util, json, os, runpy, sys
    stub = os.environ["AD_AGENTBENCH_STUB_DIR"]
    site_dirs = json.loads(os.environ["AD_AGENTBENCH_SITE_DIRS"])
    sys.path[:0] = [stub]
    sys.path.extend(site_dirs)
    forbidden = json.loads(os.environ["AD_AGENTBENCH_FORBIDDEN"])
    resolved = [name for name in forbidden if importlib.util.find_spec(name) is not None]
    spec = importlib.util.find_spec("tools")
    origin = getattr(spec, "origin", None) or ""
    if resolved or not origin.startswith(stub):
        sys.stderr.write(
            "sandbox refused to start: forbidden modules resolve %r; tools origin %r\\n"
            % (resolved, origin)
        )
        sys.exit(3)
    sys.argv = [os.environ["AD_AGENTBENCH_WORKFLOW"]]
    runpy.run_path(os.environ["AD_AGENTBENCH_WORKFLOW"], run_name="__main__")
    """
)


@dataclass(frozen=True)
class SandboxResult:
    """What a sandboxed workflow returned."""

    returncode: int
    stdout: str
    stderr: str
    n_requests: int
    """Requests the registry server answered."""


def launch(
    script: str | Path,
    registry: Registry,
    *,
    sandbox: str | Path,
    run_dir: str | Path | None = None,
    timeout_s: float = 600.0,
    python: str | None = None,
) -> SandboxResult:
    """Run a workflow script in the sandbox against ``registry``.

    Args:
        script: The workflow script (copied into the sandbox before it runs).
        registry: The registry to serve, from the privileged side.
        sandbox: A directory for the stub, the socket and the workflow's cwd.
        run_dir: ``runs/<id>/`` whose observations the run view serves, if any.
        timeout_s: Kill the workflow after this long.
        python: Interpreter to run it with (default: this one).

    Returns:
        The process outcome and how many requests the server answered.
    """
    box = Path(sandbox).resolve()
    site = stage(box)
    work = box / "cwd"
    work.mkdir(exist_ok=True)
    workflow = box / "workflow.py"
    shutil.copy2(script, workflow)
    socket_path = box / "registry.sock"
    if socket_path.exists():
        socket_path.unlink()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(work),
        "LANG": "C.UTF-8",
        "AD_AGENTBENCH_REGISTRY_SOCKET": str(socket_path),
        "AD_AGENTBENCH_STUB_DIR": str(site),
        "AD_AGENTBENCH_SITE_DIRS": json.dumps(site_directories()),
        "AD_AGENTBENCH_FORBIDDEN": json.dumps(list(FORBIDDEN_MODULES)),
        "AD_AGENTBENCH_WORKFLOW": str(workflow),
    }
    server = RegistryServer(registry, socket_path, run_dir=run_dir)
    with server:
        completed = subprocess.run(
            [python or sys.executable, "-I", "-S", "-c", _BOOTSTRAP],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    return SandboxResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        n_requests=server.n_requests,
    )
