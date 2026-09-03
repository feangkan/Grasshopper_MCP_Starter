"""M2 read tools forward the right command + args and pass results through."""
from __future__ import annotations

from server.gh_mcp_server import gh_get_canvas, gh_get_errors, gh_get_value, gh_solve


def test_get_canvas_forwards_plain(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"objects": [], "groups": [], "wires": []}}
    out = gh_get_canvas()
    assert fake_bridge.requests[-1]["cmd"] == "get_canvas"
    assert out == {"objects": [], "groups": [], "wires": []}


def test_get_errors_forwards_plain(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"error_count": 0, "messages": []}}
    gh_get_errors()
    assert fake_bridge.requests[-1]["cmd"] == "get_errors"


def test_get_value_passes_guid_and_param(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"count": 3, "values": ["1", "2", "3"]}}
    out = gh_get_value("abc-123", param="Radius")
    sent = fake_bridge.requests[-1]
    assert sent["cmd"] == "get_value"
    assert sent["args"] == {"guid": "abc-123", "param": "Radius"}
    assert out["count"] == 3


def test_get_value_param_defaults_to_none(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {}}
    gh_get_value("abc-123")
    assert fake_bridge.requests[-1]["args"] == {"guid": "abc-123", "param": None}


def test_solve_passes_force_flag(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"ran": True, "duration_ms": 1.0}}
    gh_solve(force=True)
    assert fake_bridge.requests[-1]["args"] == {"force": True}
    gh_solve()
    assert fake_bridge.requests[-1]["args"] == {"force": False}
