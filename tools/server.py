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
"""

from __future__ import annotations

import os
import socket
import threading
from pathlib import Path
from typing import Any

import numpy as np

from state.run_view import RunView, open_run
from tools.registry import Registry
from tools.transport import decode_arrays, encode_arrays, read_message, write_message

__all__ = ["RegistryServer"]

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


class RegistryServer:
    """Serve one registry (and its run's view) on a Unix-domain socket."""

    def __init__(
        self,
        registry: Registry,
        socket_path: str | Path,
        *,
        run_dir: str | Path | None = None,
        run_view: RunView | None = None,
    ) -> None:
        """Bind the socket; :meth:`start` accepts connections on a thread.

        Args:
            registry: The registry to serve.
            socket_path: Where to listen. Its directory must exist; the file must not.
            run_dir: ``runs/<id>/`` to open a run view on (through ``open_run``).
            run_view: An already-open view (takes precedence over ``run_dir``).
        """
        self.registry = registry
        self.socket_path = Path(socket_path)
        if run_view is None and run_dir is not None:
            run_view = open_run(run_dir)
        self._view = run_view
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
                if method not in _RUN_METHODS:
                    return {
                        "ok": False,
                        "error": f"unknown run method {method!r}",
                        "kind": "RunError",
                    }
                try:
                    result = _RUN_METHODS[method](self._view, request.get("args") or {})
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
