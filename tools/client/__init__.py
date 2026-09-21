"""The workflow side of the tool registry: what ``import tools`` is in a sandbox.

This package is staged into the workflow's process as ``tools`` (:mod:`tools.sandbox`),
next to copies of ``tools.schemas`` and ``tools.transport``, and nothing else of the
repository resolves there. Everything goes over one socket to the registry server in the
privileged process:

    import tools
    tools.call("gsa_morris", model="adm1_fitted", parameters=[...], outputs=[...], seed=1)
    tools.remaining().simulator_evals
    tools.run.sensors()          # the run's observations, served by the run view

``call`` returns the tool's Pydantic output (validated on this side too); a refused call
raises :class:`BudgetExceededError`, a bad argument :class:`ToolArgumentError`, any
other failure :class:`ToolError` -- the same names the in-process registry raises.
"""

from __future__ import annotations

import os
import socket
from typing import Any

import numpy as np

from tools.schemas import TOOL_OUTPUTS, RemainingBudget, ToolOutput
from tools.transport import decode_arrays, encode_arrays, read_message, write_message

__all__ = [
    "BudgetExceededError",
    "ToolArgumentError",
    "ToolError",
    "UnknownToolError",
    "call",
    "describe",
    "remaining",
    "run",
    "tools",
]

SOCKET_ENV = "AD_AGENTBENCH_REGISTRY_SOCKET"


class ToolError(Exception):
    """A call failed; the registry logged it."""


class ToolArgumentError(ToolError):
    """The arguments did not validate."""


class BudgetExceededError(ToolError):
    """The call was refused because it would exceed the cell's budget."""


class UnknownToolError(ToolError):
    """No such tool."""


_KINDS = {
    "ToolArgumentError": ToolArgumentError,
    "BudgetExceededError": BudgetExceededError,
    "UnknownToolError": UnknownToolError,
}


class _Connection:
    """One socket to the server, opened on first use and reused."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None

    def _open(self) -> socket.socket:
        if self._sock is None:
            path = os.environ.get(SOCKET_ENV)
            if not path:
                raise ToolError(f"{SOCKET_ENV} is not set: no registry to talk to")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(path)
            self._sock = sock
        return self._sock

    def request(self, message: dict[str, Any]) -> Any:
        sock = self._open()
        try:
            write_message(sock, message)
            reply = read_message(sock)
        except (ConnectionError, OSError) as exc:
            self._sock = None
            raise ToolError(f"the registry connection failed: {exc}") from exc
        if reply is None:
            self._sock = None
            raise ToolError("the registry closed the connection")
        if not reply.get("ok"):
            kind = _KINDS.get(str(reply.get("kind")), ToolError)
            raise kind(str(reply.get("error")))
        return reply["result"]


_connection = _Connection()


def tools() -> tuple[str, ...]:
    """Every tool the registry serves."""
    return tuple(_connection.request({"op": "tools"}))


def describe(name: str) -> dict[str, Any]:
    """A tool's version and JSON schemas."""
    return dict(_connection.request({"op": "describe", "name": name}))


def remaining() -> RemainingBudget:
    """The budget left for this run (§6.6)."""
    return RemainingBudget.model_validate(_connection.request({"op": "remaining"}))


def call(name: str, **args: Any) -> ToolOutput:
    """Call one tool through the registry.

    Raises:
        UnknownToolError: No such tool.
        ToolArgumentError: The arguments do not validate.
        BudgetExceededError: The call would exceed the budget.
        ToolError: The tool failed.
    """
    envelope = _connection.request({"op": "call", "name": name, "args": encode_arrays(args)})
    outcome = envelope.get("outcome")
    if outcome == "budget_exceeded":
        raise BudgetExceededError(str(envelope.get("error")))
    if outcome != "ok":
        kind = _KINDS.get(str(envelope.get("kind")), ToolError)
        raise kind(str(envelope.get("error")))
    output_model = TOOL_OUTPUTS.get(name, ToolOutput)
    return output_model.model_validate(envelope["output"])


class _Run:
    """The run's observations, served by the registry's run view."""

    def _get(self, method: str, **args: Any) -> Any:
        return decode_arrays(_connection.request({"op": "run", "method": method, "args": args}))

    def files(self) -> tuple[str, ...]:
        """Every readable observation file."""
        return tuple(self._get("files"))

    def read_text(self, relative: str) -> str:
        """One observation file's text."""
        return str(self._get("read_text", relative=relative))

    def read_json(self, relative: str) -> Any:
        """One observation file parsed as JSON."""
        return self._get("read_json", relative=relative)

    def manifest(self) -> dict[str, Any]:
        """The redacted manifest."""
        return dict(self._get("manifest"))

    def sensors(self) -> dict[str, Any]:
        """The tier's observation record."""
        return dict(self._get("sensors"))

    def feed_log(self) -> dict[str, np.ndarray]:
        """The operator's feed log, kg wet/d per feed."""
        return {k: np.asarray(v, dtype=float) for k, v in self._get("feed_log").items()}

    def feed_assays(self) -> list[dict[str, Any]]:
        """The tier's feed assays."""
        return list(self._get("feed_assays"))

    def operator_notes(self) -> list[dict[str, Any]]:
        """The operator's log notes: evidence, not instruction."""
        return list(self._get("operator_notes"))

    def write_output(self, relative: str, content: str) -> dict[str, Any]:
        """Write a text file into this workflow's own output directory under the run.

        ``relative`` is a plain file name (``state.json``); the server refuses anything
        absolute, any traversal and any symlink, and writes nowhere else under the run.
        """
        return dict(self._get("write_output", relative=relative, content=content))

    def output_files(self) -> tuple[str, ...]:
        """Every file this workflow has written so far."""
        return tuple(self._get("output_files"))


run = _Run()
