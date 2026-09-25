"""The sandbox: a workflow process in which the hidden things do not resolve.

The structural defence of decisions 2026-09-12 and design §4: ``sim``, ``scenarios`` and
``truth_store`` are neither importable nor readable from where the workflow runs, nor
from any process the workflow spawns, nor by any absolute path it is told or discovers.

**The jail** (the coordinator's review finding B1 of 2026-09-21, and the decision that
closed it). A venv alone closed ``sys.executable`` only: a workflow could run
``/usr/bin/python3`` -- the host interpreter, whose editable-install hook resolves ``sim``
-- or read ``/proc/<ppid>/cwd`` for the privileged process's working directory. So
:func:`launch` runs the workflow in a **user + mount + pid namespace with a private
root** (``unshare --user --map-root-user --mount --pid --fork --kill-child``, then a
shell script that builds a tmpfs root, bind-mounts into it only what the sandbox
interpreter needs, and ``pivot_root``s into it):

* ``/usr/lib`` (read-only; the C library and, on Debian, the standard library) and the
  interpreter's own library directory where it lies elsewhere, with every
  ``site-packages`` and ``dist-packages`` inside them **hidden** under an empty tmpfs --
  the host's install hook is never visible;
* the interpreter **binary alone** at ``/usr/bin/python-jail``, plus the symlinks the
  venv's ``bin/python`` chain needs (no ``/usr/bin/python3``, no ``/usr/local/bin``
  beyond that link);
* the sandbox environment at ``/venv`` (:func:`sandbox_interpreter`: numpy, scipy and
  pydantic, no project install), the sandbox directory at ``/box`` (the stub, the
  workflow, its cwd, the socket), ``/dev/{null,zero,random,urandom}``,
  ``/etc/ld.so.cache``, and a fresh ``/proc`` of the pid namespace -- the privileged
  process is not in it;
* nothing else: no ``/home``, no ``/tmp`` of the host, no repository, no run store.

**Fail closed.** If ``unshare`` is missing or the jail cannot be built, :func:`launch`
raises :class:`SandboxError`; there is no mode that runs unjailed. Inside, the bootstrap
refuses to run the workflow if a forbidden module resolves in its own process, in a
plain child of the sandbox interpreter, or in a plain child of any other interpreter it
can find (``/usr/bin/python3``, ``/usr/local/bin/python3``, ``shutil.which("python3")``).
The launcher also refuses a sandbox directory under the repository root, the run store or
the run store's parent.

What it does not do: it is not a boundary against a kernel exploit, and it does not limit
CPU or memory. ``tests/test_tool_sandbox.py`` drives every named route -- the relative
ones, the child-interpreter and host-interpreter ones, ``/proc`` of the parent, the
repository and the run store by absolute path -- with a negative control.
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

from tools.llm import ModelGateway
from tools.registry import Registry
from tools.server import RegistryServer

__all__ = [
    "FORBIDDEN_MODULES",
    "JAIL_EXIT",
    "JAIL_MARKER",
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

JAIL_EXIT = 111
"""Exit status of the jail script when the jail could not be built.

A workflow may exit with the same number, so :func:`launch` does not read the status
alone: the jail script writes :data:`JAIL_MARKER` into the sandbox directory once it has
pivoted and is about to start the interpreter, and a ``JAIL_EXIT`` *without* the marker is
the jail's failure, *with* it the workflow's exit code (jail review, 2026-09-21, nit 2)."""

JAIL_MARKER = "jail.started"
"""File the jail script creates in the sandbox directory just before it starts the
workflow interpreter; its absence after a ``JAIL_EXIT`` means the jail never got there."""

_PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = _PACKAGE_DIR.parent

_SCRUBBED_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
"""The environment every probe runs in: no ``PYTHONPATH``, nothing inherited (finding C1)."""


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


def _ask(python: str | Path, code: str) -> str:
    """Run one line of Python in a scrubbed environment and return its stdout."""
    out = subprocess.run(
        [str(python), "-I", "-c", code],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        env=dict(_SCRUBBED_ENV),
    )
    return out.stdout


def interpreter_site_directories(python: str | Path) -> list[str]:
    """The package directories of an interpreter, asked of the interpreter itself."""
    code = (
        "import json, sysconfig; p = sysconfig.get_paths(); "
        "print(json.dumps(sorted({p['purelib'], p['platlib']})))"
    )
    return [d for d in json.loads(_ask(python, code)) if Path(d).is_dir()]


def _library_directories(python: str | Path) -> list[str]:
    """Where an interpreter's standard library and shared library live."""
    code = (
        "import json, sysconfig; p = sysconfig.get_paths(); "
        "print(json.dumps(sorted({p['stdlib'], p['platstdlib'], "
        "sysconfig.get_config_var('LIBDIR') or p['stdlib']})))"
    )
    return [d for d in json.loads(_ask(python, code)) if Path(d).is_dir()]


def _forbidden_resolving(python: str | Path) -> list[str]:
    """Which forbidden modules a *plain* run of ``python`` resolves (no flags, site runs).

    The environment is scrubbed (finding C1): an ambient ``PYTHONPATH`` must not make a
    clean environment look dirty, nor a dirty one look clean.
    """
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
        env=dict(_SCRUBBED_ENV),
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


# ------------------------------------------------------------------ the jail

_JAIL_SCRIPT = textwrap.dedent(
    """\
    #!/bin/sh
    # Runs as PID 1 of a fresh user+mount+pid namespace (unshare -Urmpf). Builds the
    # private root and pivots into it; any failure exits with JAIL_EXIT and the workflow
    # never starts. Every tool is called by absolute path: after the pivot, PATH means
    # nothing of the host.
    fail() { echo "jail: $*" >&2; exit 111; }
    run() { "$@" || fail "failed: $*"; }
    R="$JAIL_ROOT"
    run /bin/mkdir -p "$R"
    run /bin/mount -t tmpfs -o nosuid,nodev tmpfs "$R"
    cd "$R" || fail "cd $R"
    run /bin/mkdir -p usr/lib usr/bin proc dev etc tmp venv box oldroot
    run /bin/ln -s usr/lib lib
    run /bin/mount --bind /usr/lib usr/lib
    if [ -d /usr/lib64 ]; then
        run /bin/mkdir -p usr/lib64
        run /bin/mount --bind /usr/lib64 usr/lib64
        run /bin/ln -s usr/lib64 lib64
    fi
    # the interpreter's own library directories, where they are not under /usr/lib
    for d in $JAIL_LIBDIRS; do
        case "$d" in /usr/lib/*|/usr/lib) continue ;; esac
        run /bin/mkdir -p "./$d"
        run /bin/mount --bind "$d" "./$d"
    done
    # hide every installed-package directory the host's interpreter would see: the
    # editable-install hook lives in one of these
    for d in $JAIL_HIDE; do
        [ -d "./$d" ] || continue
        run /bin/mount -t tmpfs -o nosuid,nodev,ro tmpfs "./$d"
    done
    # the interpreter binary alone, and the symlinks the venv's python chain resolves through
    run /bin/touch usr/bin/python-jail
    run /bin/mount --bind "$JAIL_PYBIN" usr/bin/python-jail
    for link in $JAIL_PYLINKS; do
        run /bin/mkdir -p "./$(/usr/bin/dirname "$link")"
        run /bin/ln -s /usr/bin/python-jail "./$link"
    done
    for d in null zero random urandom; do
        run /bin/touch "dev/$d"
        run /bin/mount --bind "/dev/$d" "dev/$d"
    done
    if [ -f /etc/ld.so.cache ]; then
        run /bin/touch etc/ld.so.cache
        run /bin/mount --bind /etc/ld.so.cache etc/ld.so.cache
    fi
    run /bin/mount --bind "$JAIL_VENV" venv
    run /bin/mount --bind "$JAIL_BOX" box
    run /bin/mount -t proc proc proc
    # read-only where the kernel lets an unprivileged namespace remount (best effort: the
    # isolation property is what is NOT mounted, not the write bit)
    /bin/mount -o remount,bind,ro usr/lib 2>/dev/null
    /bin/mount -o remount,bind,ro venv 2>/dev/null
    run /sbin/pivot_root . oldroot
    cd / || fail "cd /"
    # the old root goes with the binary that unmounts it; from here nothing of the host
    # but the mounts above exists
    run /oldroot/bin/umount -l /oldroot
    cd /box/cwd || fail "cd /box/cwd"
    export PATH=/venv/bin
    export HOME=/box/cwd
    unset JAIL_ROOT JAIL_LIBDIRS JAIL_HIDE JAIL_PYBIN JAIL_PYLINKS JAIL_VENV JAIL_BOX
    # the jail is built: from here an exit status is the workflow's (a shell builtin
    # redirection, because nothing of the host's /bin exists any more)
    : > "/box/$JAIL_MARKER" || fail "marker"
    unset JAIL_MARKER
    exec /venv/bin/python -I -S -c "$AD_AGENTBENCH_BOOTSTRAP"
    """
)

_BOOTSTRAP = textwrap.dedent(
    """
    import importlib.util, json, os, runpy, shutil, subprocess, sys
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
    # every interpreter a workflow could reach, run plain (no flags, site processing on):
    # its own, and whatever the host's names resolve to here. None may resolve a
    # forbidden module.
    probe = (
        "import importlib.util, json; names = json.loads(%r); "
        "print(json.dumps([n for n in names if importlib.util.find_spec(n) is not None]))"
        % json.dumps(forbidden)
    )
    candidates = [sys.executable, "/usr/bin/python3", "/usr/local/bin/python3",
                  "/usr/bin/python3.11", shutil.which("python3"), shutil.which("python")]
    for exe in dict.fromkeys(c for c in candidates if c and os.path.exists(c)):
        child = subprocess.run([exe, "-c", probe], capture_output=True, text=True)
        if child.returncode == 0:
            child_resolved = json.loads(child.stdout or "[]")
        else:
            child_resolved = ["<probe failed: %s>" % child.stderr.strip()[-120:]]
        if child_resolved:
            sys.stderr.write(
                "sandbox refused to start: a plain child of %s resolves %r\\n"
                % (exe, child_resolved)
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


def _python_chain(interpreter: Path) -> tuple[Path, list[str]]:
    """The interpreter's real binary and the symlink names its venv chain passes through."""
    links: list[str] = []
    venv_root = Path(interpreter).absolute().parent.parent
    current = Path(interpreter).absolute()
    seen = 0
    while current.is_symlink() and seen < 16:
        target = Path(os.readlink(current))
        if not target.is_absolute():
            target = current.parent / target
        current = Path(os.path.normpath(target))
        seen += 1
        if not _is_under(current, venv_root):
            # outside the venv: a host path the chain resolves through
            links.append(str(current))
    real = current.resolve()
    names = [link for link in links if link != str(real)]
    return real, names


def _hidden_package_dirs(libdirs: list[str]) -> list[str]:
    """Every ``site-packages`` / ``dist-packages`` under the mounted library directories."""
    hidden: list[str] = []
    for base in ["/usr/lib", *libdirs]:
        root = Path(base)
        if not root.is_dir():
            continue
        for candidate in root.glob("python3*"):
            for name in ("site-packages", "dist-packages"):
                target = candidate / name
                if target.is_dir():
                    hidden.append(str(target))
    return sorted(set(hidden))


def launch(
    script: str | Path,
    registry: Registry,
    *,
    sandbox: str | Path,
    run_dir: str | Path | None = None,
    timeout_s: float = 600.0,
    workflow: str | None = None,
    model_gateway: ModelGateway | None = None,
) -> SandboxResult:
    """Run a workflow script in the jail against ``registry``.

    Args:
        script: The workflow script (copied into the sandbox before it runs).
        registry: The registry to serve, from the privileged side.
        sandbox: A directory for the stub, the socket and the workflow's cwd. Must not lie
            under the repository root, the run store or the run store's parent. **It is
            single-use per launch**: the ``/box`` bind is read-write, so the workflow can
            leave anything in it (its cwd, files beside the stub), and a second launch in
            the same directory would start from what the first left behind. Give every
            launch a fresh directory; ``launch`` re-stages the stub, the workflow, the
            socket and the marker, but does not empty the directory.
        run_dir: ``runs/<id>/`` whose observations the run view serves, if any.
        timeout_s: Kill the workflow after this long.
        workflow: The workflow's name; with ``run_dir``, lets the workflow write its own
            outputs into ``runs/<id>/workflows/<workflow>/`` through ``tools.run.write_output``.
        model_gateway: For an LLM workflow, the gateway its model turns go through
            (``tools.llm``); it lives on this side, so no key or model setting enters the jail.

    Returns:
        The process outcome and how many requests the server answered. A workflow's own
        exit status is returned as it is, :data:`JAIL_EXIT` included (the jail's marker
        tells the two apart).

    Raises:
        SandboxError: If the sandbox directory is in a forbidden place, the sandbox
            environment cannot be built, ``unshare`` is unavailable, or the jail could
            not be built (the workflow is never run unjailed).
    """
    box = Path(sandbox).resolve()
    _check_location(box, None if run_dir is None else Path(run_dir))
    unshare = shutil.which("unshare")
    if unshare is None:
        raise SandboxError("unshare (util-linux) is not available; the jail cannot be built")
    interpreter = sandbox_interpreter()
    venv_root = interpreter.parent.parent
    real_binary, links = _python_chain(interpreter)
    libdirs = [d for d in _library_directories(interpreter) if not _is_under(Path(d), venv_root)]
    stage(box)
    work = box / "cwd"
    work.mkdir(exist_ok=True)
    staged_script = box / "workflow.py"
    shutil.copy2(script, staged_script)
    socket_path = box / "registry.sock"
    if socket_path.exists():
        socket_path.unlink()
    jail_root = box / "root"
    jail_root.mkdir(exist_ok=True)
    jail_script = box / "jail.sh"
    jail_script.write_text(_JAIL_SCRIPT, encoding="utf-8")
    marker = box / JAIL_MARKER
    if marker.exists():
        marker.unlink()
    # the venv's site-packages as seen from inside the jail (the venv is mounted at /venv)
    site_dirs = [
        "/venv" + d[len(str(venv_root)) :] if d.startswith(str(venv_root)) else d
        for d in interpreter_site_directories(interpreter)
    ]
    env = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "JAIL_ROOT": str(jail_root),
        "JAIL_LIBDIRS": " ".join(libdirs),
        "JAIL_HIDE": " ".join(_hidden_package_dirs(libdirs)),
        "JAIL_PYBIN": str(real_binary),
        "JAIL_PYLINKS": " ".join(links),
        "JAIL_VENV": str(venv_root),
        "JAIL_BOX": str(box),
        "JAIL_MARKER": JAIL_MARKER,
        "AD_AGENTBENCH_BOOTSTRAP": _BOOTSTRAP,
        "AD_AGENTBENCH_REGISTRY_SOCKET": "/box/registry.sock",
        "AD_AGENTBENCH_STUB_DIR": "/box/site",
        "AD_AGENTBENCH_SITE_DIRS": json.dumps(site_dirs),
        "AD_AGENTBENCH_FORBIDDEN": json.dumps(list(FORBIDDEN_MODULES)),
        "AD_AGENTBENCH_WORKFLOW": "/box/workflow.py",
    }
    command = [
        unshare,
        "--user",
        "--map-root-user",
        "--mount",
        "--pid",
        "--fork",
        "--kill-child",
        "/bin/sh",
        str(jail_script),
    ]
    server = RegistryServer(
        registry, socket_path, run_dir=run_dir, workflow=workflow, model_gateway=model_gateway
    )
    with server:
        completed = subprocess.run(
            command,
            cwd=box,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    jail_failed = completed.returncode == JAIL_EXIT and not marker.exists()
    if jail_failed or "unshare:" in completed.stderr[:200]:
        raise SandboxError(
            "the jail could not be built, so the workflow was not run: "
            + completed.stderr.strip()[-1000:]
        )
    return SandboxResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        n_requests=server.n_requests,
    )
