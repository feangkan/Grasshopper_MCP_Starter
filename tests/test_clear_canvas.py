"""gh_clear_canvas forwards keep-list and dry_run to the bridge intact."""
from __future__ import annotations

from server.gh_mcp_server import gh_clear_canvas


def test_defaults_send_empty_keep_and_no_dry_run(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"deleted": 3}}
    out = gh_clear_canvas()
    sent = fake_bridge.requests[-1]
    assert sent["cmd"] == "clear_canvas"
    assert sent["args"] == {"keep": [], "dry_run": False}
    assert out == {"deleted": 3}


def test_keep_list_passes_through(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"deleted": 1}}
    gh_clear_canvas(keep=["Tower Study", "9f2a-guid"])
    assert fake_bridge.requests[-1]["args"]["keep"] == ["Tower Study", "9f2a-guid"]


def test_dry_run_flag_passes_through(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"would_delete": []}}
    gh_clear_canvas(dry_run=True)
    assert fake_bridge.requests[-1]["args"]["dry_run"] is True
