"""The registry server: the privileged process's end of the socket (design §4).

One thread, one Unix-domain socket, one request at a time -- the registry is a serial
resource (budgets, logs) and stays one. Requests are JSON objects with an ``op``:

============  ==================================================  ======================
``tools``     --                                                  the tool names
``describe``  ``name``                                            version and schemas
``remaining`` --                                                  the budget left
``call``      ``name``, ``args`` (arrays tagged)                  the call envelope
``run``       ``method``, ``args``: the run view's accessors      contents, never paths
============  ==================================================  ======================

The run view served here is :func:`state.run_view.open_run`, so a workflow gets exactly
what that loader gives and nothing else; the server never sends a path, a directory, or
anything from outside ``runs/<id>/``. An unknown ``op`` or ``method`` is an error reply,
never an exception in the server.

**The one write** (the P0 session, 2026-09-21; design ``docs/p0_design.md`` §5). A
workflow's task state and report (§6.6) belong in ``runs/<id>/workflows/<workflow>/``, and
the workflow is jailed, so the run method ``write_output(relative, content)`` writes text
there through :class:`OutputSink`: a plain relative file name inside that one directory,
nothing absolute, no traversal, no symlink out of it, never anywhere else under the run.
The sink exists only when the server was opened with a ``workflow`` name.
"""

from __future__ import annotations

import os
import socket
import threading
from pathlib import Path
from typing import Any

import numpy as np

from state.run_view import RunView, TruthAccessError, open_run
from state.task_state import OUTPUTS_DIR
from tools.registry import Registry
from tools.transport import decode_arrays, encode_arrays, read_message, write_message

__all__ = ["OUTPUTS_DIR", "OutputSink", "RegistryServer"]


MAX_OUTPUT_BYTES = 16 << 20
"""Largest single output file a workflow may write, bytes: a guard, not a budget."""


class OutputSink:
    """The write side of a run for one workflow: ``runs/<id>/workflows/<workflow>/``.

    Separate from :class:`~state.run_view.RunView` on purpose: the view is read-only and
    returns contents, never paths; this object writes and holds the one directory it may
    write into, resolved once, and refuses anything that does not land strictly inside it.
    """

    def __init__(self, run_dir: str | Path, workflow: str) -> None:
        """Open (creating) the workflow's output directory under the run.

        Raises:
            ValueError: If the workflow name is not a plain identifier.
        """
        if not workflow or not workflow.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"workflow name {workflow!r} must be a plain identifier")
        self.workflow = workflow
        self._root = (Path(run_dir).resolve() / OUTPUTS_DIR / workflow).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative.strip():
            raise TruthAccessError("write_output needs a file name")
        candidate = Path(relative)
        parts = candidate.parts
        if candidate.is_absolute() or not parts or ".." in parts or parts[0] in (".", ""):
            raise TruthAccessError(
                f"{relative!r}: a workflow writes plain relative names inside its own output "
                "directory, nothing absolute and no traversal (CLAUDE.md rule 1)"
            )
        if any(sep in relative for sep in ("\\", "\0")):
            raise TruthAccessError(f"{relative!r}: not a plain file name")
        target = self._root / candidate
        # resolve every existing prefix (a planted symlink would resolve elsewhere)
        resolved = target.resolve()
        if self._root != resolved and self._root not in resolved.parents:
            raise TruthAccessError(
                f"{relative!r} resolves outside the workflow's output directory (rule 1)"
            )
        if resolved == self._root or resolved.is_dir():
            raise TruthAccessError(f"{relative!r} names a directory, not a file")
        if target.is_symlink():
            raise TruthAccessError(f"{relative!r} is a symlink; refused")
        return resolved

    def write(self, relative: str, content: str) -> dict[str, Any]:
        """Write ``content`` (text) to ``relative`` inside the output directory.

        Returns:
            ``{"relative": ..., "bytes": n}``; never a path.

        Raises:
            TruthAccessError: If the name leaves the directory or is not a plain file.
            ValueError: If the content is not text or is too large.
        """
        if not isinstance(content, str):
            raise ValueError("write_output takes text; encode JSON before sending it")
        data = content.encode("utf-8")
        if len(data) > MAX_OUTPUT_BYTES:
            raise ValueError(f"output of {len(data)} bytes exceeds {MAX_OUTPUT_BYTES}")
        target = self._resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return {"relative": relative, "bytes": len(data)}

    def files(self) -> list[str]:
        """Every file written so far, relative to the output directory."""
        return sorted(str(p.relative_to(self._root)) for p in self._root.rglob("*") if p.is_file())


_RUN_METHODS = {
    "files": lambda view, args: list(view.files),
    "read_text": lambda view, args: view.read_text(str(args["relative"])),
    "read_json": lambda view, args: view.read_json(str(args["relative"])),
    "manifest": lambda view, args: view.manifest.model_dump(mode="json"),
    "sensors": lambda view, args: view.sensors(),
    "feed_log": lambda view, args: {k: v.tolist() for k, v in view.feed_log().items()},
    "feed_assays": lambda view, args: view.feed_assays(),
    "operator_notes": lambda view, args: view.operator_notes(),
}

_SINK_METHODS = {
    "write_output": lambda sink, args: sink.write(str(args["relative"]), args["content"]),
    "output_files": lambda sink, args: sink.files(),
}


class RegistryServer:
    """Serve one registry (and its run's view) on a Unix-domain socket."""

    def __init__(
        self,
        registry: Registry,
        socket_path: str | Path,
        *,
        run_dir: str | Path | None = None,
        run_view: RunView | None = None,
        workflow: str | None = None,
    ) -> None:
        """Bind the socket; :meth:`start` accepts connections on a thread.

        Args:
            registry: The registry to serve.
            socket_path: Where to listen. Its directory must exist; the file must not.
            run_dir: ``runs/<id>/`` to open a run view on (through ``open_run``).
            run_view: An already-open view (takes precedence over ``run_dir``).
            workflow: The workflow's name; when given (with ``run_dir``), the run method
                ``write_output`` writes into ``runs/<id>/workflows/<workflow>/``.
        """
        self.registry = registry
        self.socket_path = Path(socket_path)
        if run_view is None and run_dir is not None:
            run_view = open_run(run_dir)
        self._view = run_view
        self._sink = OutputSink(run_dir, workflow) if workflow and run_dir is not None else None
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.socket_path))
        self._sock.listen(4)
        self._sock.settimeout(0.2)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.n_requests = 0

    # -- lifecycle ---------------------------------------------------------------
    def start(self) -> RegistryServer:
        """Accept connections on a daemon thread."""
        self._thread = threading.Thread(target=self._serve, name="registry-server", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop accepting, close the socket and remove its file."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._sock.close()
        if self.socket_path.exists():
            os.unlink(self.socket_path)

    def __enter__(self) -> RegistryServer:
        """Start on entry."""
        return self.start()

    def __exit__(self, *exc: object) -> None:
        """Stop on exit."""
        self.stop()

    # -- the loop ----------------------------------------------------------------
    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(None)
                try:
                    while not self._stop.is_set():
                        request = read_message(conn)
                        if request is None:
                            break
                        self.n_requests += 1
                        write_message(conn, self._handle(request))
                except (ConnectionError, OSError):
                    continue

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        try:
            if op == "tools":
                return {"ok": True, "result": list(self.registry.tools)}
            if op == "describe":
                return {"ok": True, "result": self.registry.describe(str(request["name"]))}
            if op == "remaining":
                return {"ok": True, "result": self.registry.remaining().model_dump(mode="json")}
            if op == "call":
                args = decode_arrays(request.get("args") or {})
                return {"ok": True, "result": self.registry.call_json(str(request["name"]), args)}
            if op == "run":
                if self._view is None:
                    return {"ok": False, "error": "this registry serves no run", "kind": "RunError"}
                method = str(request.get("method"))
                if method in _SINK_METHODS:
                    if self._sink is None:
                        return {
                            "ok": False,
                            "error": "this registry serves no workflow output directory",
                            "kind": "RunError",
                        }
                    target, handler = self._sink, _SINK_METHODS[method]
                elif method in _RUN_METHODS:
                    target, handler = self._view, _RUN_METHODS[method]
                else:
                    return {
                        "ok": False,
                        "error": f"unknown run method {method!r}",
                        "kind": "RunError",
                    }
                try:
                    result = handler(target, request.get("args") or {})
                except Exception as exc:
                    # the loader's own message names the absolute path it refused, and a
                    # path is a capability (state.run_view): the workflow gets the kind
                    # and the rule, never the path
                    return {
                        "ok": False,
                        "error": f"{type(exc).__name__}: the run view reads a run's "
                        "observations and nothing else (CLAUDE.md rule 1)",
                        "kind": type(exc).__name__,
                    }
                return {"ok": True, "result": encode_arrays(_plain(result))}
            return {"ok": False, "error": f"unknown op {op!r}", "kind": "ProtocolError"}
        except Exception as exc:  # the server never dies on a bad request
            return {"ok": False, "error": str(exc), "kind": type(exc).__name__}


def _plain(value: Any) -> Any:
    """Numpy scalars and arrays inside a run-view result become JSON-safe values."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value
