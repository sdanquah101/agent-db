"""Frames and array encoding of the registry protocol (shared with the client stub).

A message is one JSON object; on the wire it is an 8-byte big-endian length followed by
the UTF-8 JSON. Numpy arrays inside a *request* travel as
``{"__ndarray__": {"dtype", "shape", "data": base64 of the bytes}}`` so a workflow's
arguments arrive bit for bit; a *response* carries the Pydantic output's JSON form
(arrays as lists), which the client validates back into the output model.

Imports the standard library and numpy only.
"""

from __future__ import annotations

import base64
import json
import socket
import struct
from typing import Any

import numpy as np

__all__ = ["decode_arrays", "encode_arrays", "read_message", "write_message"]

_HEADER = struct.Struct(">Q")
MAX_MESSAGE = 1 << 30
"""Largest message accepted, bytes: a guard against a corrupt header, not a budget."""


def encode_arrays(value: Any) -> Any:
    """Replace every numpy array in a JSON-like structure with its tagged encoding."""
    if isinstance(value, np.ndarray):
        contiguous = np.ascontiguousarray(value)
        return {
            "__ndarray__": {
                "dtype": str(contiguous.dtype),
                "shape": list(contiguous.shape),
                "data": base64.b64encode(contiguous.tobytes()).decode("ascii"),
            }
        }
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): encode_arrays(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [encode_arrays(v) for v in value]
    if hasattr(value, "model_dump"):
        return encode_arrays(value.model_dump())
    return value


def decode_arrays(value: Any) -> Any:
    """The inverse of :func:`encode_arrays`."""
    if isinstance(value, dict):
        if set(value) == {"__ndarray__"}:
            spec = value["__ndarray__"]
            raw = base64.b64decode(spec["data"])
            return np.frombuffer(raw, dtype=np.dtype(spec["dtype"])).reshape(spec["shape"]).copy()
        return {k: decode_arrays(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode_arrays(v) for v in value]
    return value


def write_message(sock: socket.socket, message: dict[str, Any]) -> None:
    """Send one framed JSON message."""
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sock.sendall(_HEADER.pack(len(payload)) + payload)


def _read_exactly(sock: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(min(remaining, 1 << 20))
        if not chunk:
            raise ConnectionError("the registry connection closed mid-message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(sock: socket.socket) -> dict[str, Any] | None:
    """Receive one framed JSON message, or ``None`` at a clean end of stream."""
    header = b""
    while len(header) < _HEADER.size:
        chunk = sock.recv(_HEADER.size - len(header))
        if not chunk:
            if header:
                raise ConnectionError("the registry connection closed mid-header")
            return None
        header += chunk
    (length,) = _HEADER.unpack(header)
    if length > MAX_MESSAGE:
        raise ConnectionError(f"message of {length} bytes exceeds the limit")
    payload = _read_exactly(sock, length)
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise ConnectionError("a message must be a JSON object")
    return message
