"""BridgeClient: framing, lockfile discovery, and error mapping."""
from __future__ import annotations

import json

import pytest

from server import bridge_client
from server.bridge_client import BridgeClient, call, read_lockfile
from server.protocol import SCHEMA, BridgeError


def test_call_sends_wellformed_request(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"pong": 1}}

    result = call("ping", {"foo": "bar"})

    assert result == {"pong": 1}
    sent = fake_bridge.requests[-1]
    assert sent["cmd"] == "ping"
    assert sent["args"] == {"foo": "bar"}
    assert isinstance(sent["id"], str) and sent["id"]


def test_response_id_is_not_required_to_match(fake_bridge):
    # the client does not currently correlate ids; a mismatched id still resolves
    fake_bridge.responder = lambda req: {"ok": True, "result": {"echo": req["cmd"]}, "id": "other"}
    assert call("get_canvas") == {"echo": "get_canvas"}


def test_bridge_error_response_becomes_exception(fake_bridge):
    fake_bridge.responder = {"ok": False, "error": "no active document"}
    with pytest.raises(BridgeError, match="no active document"):
        call("get_canvas")


def test_bridge_error_includes_trace_when_present(fake_bridge):
    fake_bridge.responder = {"ok": False, "error": "boom", "trace": "Traceback ..."}
    with pytest.raises(BridgeError, match="bridge traceback"):
        call("solve")


def test_missing_lockfile_raises_helpful_error(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_client, "lockfile_path", lambda: tmp_path / "nope.json")
    with pytest.raises(BridgeError, match="bridge is not running"):
        call("ping")


def test_schema_mismatch_is_reported(tmp_path, monkeypatch):
    lock = tmp_path / "claude_gh_bridge.json"
    lock.write_text(json.dumps({"schema": "claude_gh_bridge/999", "port": 1}))
    monkeypatch.setattr(bridge_client, "lockfile_path", lambda: lock)
    with pytest.raises(BridgeError, match="schema mismatch"):
        call("ping")


def test_connection_refused_is_wrapped(tmp_path, monkeypatch, free_port):
    lock = tmp_path / "claude_gh_bridge.json"
    lock.write_text(json.dumps({"schema": SCHEMA, "port": free_port}))
    monkeypatch.setattr(bridge_client, "lockfile_path", lambda: lock)
    with pytest.raises(BridgeError, match="Could not reach"):
        BridgeClient(timeout=1.0).call("ping")


def test_read_lockfile_returns_none_for_garbage(tmp_path, monkeypatch):
    lock = tmp_path / "claude_gh_bridge.json"
    lock.write_text("{not json")
    monkeypatch.setattr(bridge_client, "lockfile_path", lambda: lock)
    assert read_lockfile() is None


def test_explicit_port_skips_lockfile(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"ok": 1}}
    client = BridgeClient(port=fake_bridge.port)
    assert client.call("ping") == {"ok": 1}
