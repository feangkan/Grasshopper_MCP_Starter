"""Shared fixtures. The Grasshopper half cannot run here, so we stand up a fake
bridge: a plain TCP server that speaks the same newline-JSON protocol and returns
canned responses. That lets us test the whole server-side path (framing, lockfile
discovery, error mapping) without Rhino.
"""
from __future__ import annotations

import json
import socket
import socketserver
import threading
from pathlib import Path

import pytest

from server import bridge_client
from server.protocol import SCHEMA


class _FakeBridgeHandler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline()
        if not raw:
            return
        req = json.loads(raw.decode("utf-8"))
        self.server.requests.append(req)
        responder = self.server.responder
        resp = responder(req) if callable(responder) else responder
        resp.setdefault("id", req.get("id"))
        self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))


class _FakeBridge(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _FakeBridgeHandler)
        self.requests: list[dict] = []
        self.responder = {"ok": True, "result": {}}

    @property
    def port(self) -> int:
        return self.server_address[1]


@pytest.fixture
def fake_bridge(tmp_path, monkeypatch):
    """A running fake bridge plus a lockfile the client will discover.

    Yields the server object. Set ``fake_bridge.responder`` to a dict or a
    callable(request)->dict to control replies; read ``fake_bridge.requests``
    to assert what the server sent.
    """
    lock = tmp_path / "claude_gh_bridge.json"
    monkeypatch.setattr(bridge_client, "lockfile_path", lambda: lock)

    server = _FakeBridge()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    lock.write_text(json.dumps({"schema": SCHEMA, "port": server.port, "pid": 0}))

    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
