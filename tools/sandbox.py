"""The sandbox: a workflow process in which the hidden things do not resolve.

The structural defence of decisions 2026-09-12 and design §4: ``sim``, ``scenarios`` and
``truth_store`` are neither importable nor readable from where the workflow runs, **nor
from any process the workflow spawns** (the coordinator's acceptance finding of
2026-09-21: a plain child interpreter of the sandbox process inherited the host
interpreter, whose editable-install hook resolved ``sim`` and, through ``sim.__file__``,
the repository root and its ``truth_store/``).

So the sandbox runs on a **dedicated interpreter environment**: a virtual environment
that contains numpy, scipy and pydantic and *not* the project install
(:func:`sandbox_interpreter`), built once per host interpreter and package set and
cached under ``AD_AGENTBENCH_SANDBOX_HOME`` (default ``~/.cache/ad-agentbench``). A child
interpreter spawned from the sandbox is that environment's interpreter, and its ``site``
has no hook to run.

:func:`stage` copies the client stub (:mod:`tools.client`, ``tools.schemas``,
``tools.transport``) into ``<sandbox>/site/tools/`` so that ``import tools`` in the
workflow is the stub. :func:`launch` then runs the workflow script with

* the sandbox interpreter, ``-I -S``: isolated mode (no ``PYTHONPATH``, no user site, no
  script directory on the path) and no site processing;
* ``sys.path`` set by a bootstrap to the standard library, the stub directory and the
  sandbox interpreter's own package directories;
* a **fail-closed check** before the script runs, twice: in the bootstrap's own process,
  if ``sim``, ``scenarios``, ``anchor``, ``eval`` or ``state`` resolves, or ``tools``
  resolves to anything but the stub; and in a **plain child interpreter** spawned with
  the sandbox's environment and no flags, if ``sim`` or its siblings resolve there. Either
  finding exits without running the workflow (the host interpreter with its editable
  install trips the second, which is the point);
* an empty scratch directory as the working directory, an environment holding the socket
  path and little else, and the registry server listening in *this* process;
* a **sandbox directory outside** the repository root, the run store and the run store's
  parent (the stub and socket paths are in the workflow's environment, so a sandbox inside
  any of them would hand the workflow a path into them); ``launch`` refuses otherwise.

What it does not do is stop a workflow that is *told* an absolute path from opening it:
that is a container's job (design §4) and the layout's (``truth_store/`` is a sibling the
workflow is never told the path of). The test drives the relative routes the requirement
names, the child-interpreter route, and a negative control.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from tools.registry import Registry
from tools.server import RegistryServer

__all__ = [
    "FORBIDDEN_MODULES",
    "SANDBOX_PACKAGES",
    "SandboxError",
    "SandboxResult",
    "interpreter_site_directories",
    "launch",
    "sandbox_interpreter",
    "stage",
]

FORBIDDEN_MODULES: tuple[str, ...] = ("sim", "scenarios", "anchor", "eval", "state")
"""Modules that must not resolve in the workflow process or any child of it."""

SANDBOX_PACKAGES: tuple[str, ...] = ("numpy", "scipy", "pydantic")
"""What the sandbox environment contains, pinned to the host's versions. Nothing else: not
the project, not emcee or cma (the tools run on the privileged side)."""

_PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = _PACKAGE_DIR.parent


class SandboxError(RuntimeError):
    """The sandbox could not be built or the launch was refused."""


# ------------------------------------------------------------------ the interpreter


def _sandbox_home() -> Path:
    override = os.environ.get("AD_AGENTBENCH_SANDBOX_HOME")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "ad-agentbench"


def _pins() -> list[str]:
    return [f"{name}=={importlib.metadata.version(name)}" for name in SANDBOX_PACKAGES]


def _cache_key(pins: list[str]) -> str:
    material = "|".join([sys.executable, sys.version, *pins])
    return hashlib.sha256(material.encode()).hexdigest()[:12]


def _venv_python(root: Path) -> Path:
    if os.name == "nt":  # pragma: no cover - the benchmark runs on Linux
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def interpreter_site_directories(python: str | Path) -> list[str]:
    """The package directories of an interpreter, asked of the interpreter itself."""
    code = (
        "import json, sysconfig; p = sysconfig.get_paths(); "
        "print(json.dumps(sorted({p['purelib'], p['platlib']})))"
    )
    out = subprocess.run(
        [str(python), "-I", "-c", code], capture_output=True, text=True, check=True, timeout=60
    )
    return [d for d in json.loads(out.stdout) if Path(d).is_dir()]


def _forbidden_resolving(python: str | Path, env: dict[str, str] | None = None) -> list[str]:
    """Which forbidden modules a *plain* run of ``python`` resolves (no flags, site runs)."""
    code = (
        "import importlib.util, json, sys; "
        f"names = {list(FORBIDDEN_MODULES)!r}; "
        "print(json.dumps([n for n in names if importlib.util.find_spec(n) is not None]))"
    )
    out = subprocess.run(
        [str(python), "-c", code],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        env=env,
        cwd=str(Path(python).resolve().parent),
    )
    return list(json.loads(out.stdout))


def sandbox_interpreter(*, rebuild: bool = False) -> Path:
    """The interpreter of the sandbox environment, building it on first use.

    A virtual environment of the host interpreter with :data:`SANDBOX_PACKAGES` pinned to
    the host's versions and nothing else, cached by (host interpreter, versions, pins).
    After building, a plain run of it is checked to resolve none of
    :data:`FORBIDDEN_MODULES`; a cached environment is re-checked on every call, which
    costs one interpreter start.

    Raises:
        SandboxError: If the environment cannot be built, or resolves a forbidden module.
    """
    pins = _pins()
    root = _sandbox_home() / f"sandbox-{_cache_key(pins)}"
    python = _venv_python(root)
    marker = root / "READY"
    if rebuild and root.exists():
        shutil.rmtree(root)
    if not (python.is_file() and marker.is_file()):
        if root.exists():
            shutil.rmtree(root)
        root.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", "--without-pip", str(root)],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            # install with the HOST's pip into the venv's site-packages: the venv itself
            # has no pip (and needs none), and the host's pip cache serves the same wheels
            site = interpreter_site_directories(python)[0]
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--disable-pip-version-check",
                    "--target",
                    site,
                    *pins,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=1800,
            )
        except subprocess.CalledProcessError as exc:
            raise SandboxError(
                f"building the sandbox environment failed: {exc.stderr[-2000:]}"
            ) from exc
        marker.write_text("\n".join(pins) + "\n", encoding="utf-8")
    resolving = _forbidden_resolving(python)
    if resolving:
        raise SandboxError(
            f"the sandbox interpreter {python} resolves {resolving}; the environment is "
            "not clean of the project install"
        )
    return python


# ------------------------------------------------------------------ the stub


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


# ------------------------------------------------------------------ the launch


_BOOTSTRAP = textwrap.dedent(
    """
    import importlib.util, json, os, runpy, subprocess, sys
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
    # a plain child of this interpreter, no flags, site processing on: what a workflow
    # gets if it spawns one. It must resolve nothing forbidden either.
    probe = (
        "import importlib.util, json; names = json.loads(%r); "
        "print(json.dumps([n for n in names if importlib.util.find_spec(n) is not None]))"
        % json.dumps(forbidden)
    )
    child = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    if child.returncode == 0:
        child_resolved = json.loads(child.stdout or "[]")
    else:
        child_resolved = ["<probe failed>"]
    if child_resolved:
        sys.stderr.write(
            "sandbox refused to start: a plain child interpreter resolves %r\\n"
            % (child_resolved,)
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


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _check_location(box: Path, run_dir: Path | None) -> None:
    """Refuse a sandbox inside the repository, the run store or the run store's parent."""
    forbidden = [("the repository root", REPO_ROOT.resolve())]
    if run_dir is not None:
        store = Path(run_dir).resolve().parent
        forbidden.append(("the run store", store))
        forbidden.append(("the run store's parent (which holds the truth store)", store.parent))
    for what, root in forbidden:
        if _is_under(box, root):
            raise SandboxError(
                f"sandbox {box} lies under {what} ({root}); the stub and socket paths are in "
                "the workflow's environment, so a sandbox there would hand it a path into it"
            )


def launch(
    script: str | Path,
    registry: Registry,
    *,
    sandbox: str | Path,
    run_dir: str | Path | None = None,
    timeout_s: float = 600.0,
    python: str | Path | None = None,
) -> SandboxResult:
    """Run a workflow script in the sandbox against ``registry``.

    Args:
        script: The workflow script (copied into the sandbox before it runs).
        registry: The registry to serve, from the privileged side.
        sandbox: A directory for the stub, the socket and the workflow's cwd. Must not lie
            under the repository root, the run store or the run store's parent.
        run_dir: ``runs/<id>/`` whose observations the run view serves, if any.
        timeout_s: Kill the workflow after this long.
        python: Interpreter to run it with (default: :func:`sandbox_interpreter`). Any
            interpreter is accepted here, and the bootstrap refuses to run the workflow
            if a plain child of it resolves a forbidden module -- passing the host
            interpreter of an editable install is the fail-closed test.

    Returns:
        The process outcome and how many requests the server answered.

    Raises:
        SandboxError: If the sandbox directory is in a forbidden place, or the sandbox
            environment cannot be built.
    """
    box = Path(sandbox).resolve()
    _check_location(box, None if run_dir is None else Path(run_dir))
    interpreter = Path(python) if python is not None else sandbox_interpreter()
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
        "AD_AGENTBENCH_SITE_DIRS": json.dumps(interpreter_site_directories(interpreter)),
        "AD_AGENTBENCH_FORBIDDEN": json.dumps(list(FORBIDDEN_MODULES)),
        "AD_AGENTBENCH_WORKFLOW": str(workflow),
    }
    server = RegistryServer(registry, socket_path, run_dir=run_dir)
    with server:
        completed = subprocess.run(
            [str(interpreter), "-I", "-S", "-c", _BOOTSTRAP],
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
