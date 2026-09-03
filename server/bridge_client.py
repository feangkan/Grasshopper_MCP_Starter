"""TCP client for the Grasshopper bridge component.

Discovers the bridge's port from its lockfile, sends one JSON command, and
returns the parsed result. All network/JSON failure modes collapse to
`BridgeError` with a message aimed at a human who has Rhino open.
"""
from __future__ import annotations

import json
import socket
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .protocol import (
    DEFAULT_PORT,
    ENCODING,
    LOCKFILE_NAME,
    SCHEMA,
    TERMINATOR,
    BridgeError,
)

# The bridge can be slow: a big `get_canvas` or a `solve` on a heavy definition
# blocks the UI thread. Keep this generous.
DEFAULT_TIMEOUT = 30.0
CONNECT_TIMEOUT = 4.0


def lockfile_path() -> Path:
    return Path(tempfile.gettempdir()) / LOCKFILE_NAME


def read_lockfile() -> dict[str, Any] | None:
    """Return the parsed lockfile, or None if it is missing or unreadable."""
    path = lockfile_path()
    try:
        raw = path.read_text(encoding=ENCODING)
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _discover_port() -> int:
    data = read_lockfile()
    if not data:
        raise BridgeError(
            "The Grasshopper bridge is not running. In Rhino: open Grasshopper, "
            "place the 'Claude Bridge' component (paste grasshopper/claude_bridge.py "
            "into a Python 3 Script component), and set its `enable` input to True."
        )
    got = data.get("schema")
    if got != SCHEMA:
        raise BridgeError(
            f"Bridge lockfile schema mismatch: server expects {SCHEMA!r}, "
            f"bridge wrote {got!r}. Update grasshopper/claude_bridge.py to match this server."
        )
    port = data.get("port")
    if not isinstance(port, int):
        return DEFAULT_PORT
    return port


class BridgeClient:
    """One-shot request/response client. Not stateful; safe to construct per call."""

    def __init__(self, port: int | None = None, timeout: float = DEFAULT_TIMEOUT):
        self._port = port
        self._timeout = timeout

    def call(self, cmd: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        port = self._port or _discover_port()
        request = {"id": str(uuid.uuid4()), "cmd": cmd, "args": args or {}}
        payload = (json.dumps(request) + TERMINATOR).encode(ENCODING)

        try:
            with socket.create_connection(("127.0.0.1", port), CONNECT_TIMEOUT) as sock:
                sock.settimeout(self._timeout)
                sock.sendall(payload)
                raw = _recv_line(sock)
        except (ConnectionRefusedError, OSError) as exc:
            raise BridgeError(
                f"Could not reach the Grasshopper bridge on 127.0.0.1:{port} ({exc}). "
                "Is the 'Claude Bridge' component enabled? Try toggling `enable` off and on."
            ) from exc

        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BridgeError(f"Bridge sent malformed JSON: {raw[:200]!r}") from exc

        if not response.get("ok"):
            msg = response.get("error", "unknown error")
            trace = response.get("trace")
            raise BridgeError(msg if not trace else f"{msg}\n--- bridge traceback ---\n{trace}")
        return response.get("result", {})


def _recv_line(sock: socket.socket) -> str:
    """Read bytes until the first newline; the bridge sends exactly one line."""
    chunks: list[bytes] = []
    deadline = time.monotonic() + sock.gettimeout()
    while True:
        if time.monotonic() > deadline:
            raise BridgeError("Timed out waiting for the bridge to respond.")
        block = sock.recv(65536)
        if not block:
            break
        chunks.append(block)
        if b"\n" in block:
            break
    data = b"".join(chunks)
    return data.split(b"\n", 1)[0].decode(ENCODING)


def call(cmd: str, args: dict[str, Any] | None = None, *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Module-level convenience wrapper."""
    return BridgeClient(timeout=timeout).call(cmd, args)
