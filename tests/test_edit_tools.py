"""M4 edit tools: correct command + args, and name resolution before send."""
from __future__ import annotations

from server.gh_mcp_server import (
    gh_add_component,
    gh_connect,
    gh_delete,
    gh_disconnect,
    gh_set_value,
)


def test_add_component_resolves_shorthand_before_sending(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"guid": "new-1", "matched_from": "Number Slider"}}
    gh_add_component("slider", 100, 200, nickname="Height")
    sent = fake_bridge.requests[-1]
    assert sent["cmd"] == "add_component"
    assert sent["args"]["name"] == "Number Slider"      # resolved
    assert sent["args"]["requested"] == "slider"         # original kept for the bridge
    assert sent["args"]["x"] == 100 and sent["args"]["y"] == 200
    assert sent["args"]["nickname"] == "Height"


def test_add_component_passes_unknown_name_through(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"guid": "x"}}
    gh_add_component("Kangaroo2 Solver", 0, 0)
    assert fake_bridge.requests[-1]["args"]["name"] == "Kangaroo2 Solver"


def test_set_value_forwards_guid_and_value(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"value": 12}}
    gh_set_value("slider-guid", 12)
    assert fake_bridge.requests[-1]["args"] == {"guid": "slider-guid", "value": 12}


def test_connect_carries_optional_params(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"from_param": "N", "to_param": "R"}}
    gh_connect("src", "tgt", target_param="Radius")
    args = fake_bridge.requests[-1]["args"]
    assert args["source"] == "src" and args["target"] == "tgt"
    assert args["source_param"] is None
    assert args["target_param"] == "Radius"


def test_disconnect_and_delete(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {}}
    gh_disconnect("src", "tgt")
    assert fake_bridge.requests[-1]["cmd"] == "disconnect"

    fake_bridge.responder = {"ok": True, "result": {"deleted": ["a", "b"]}}
    out = gh_delete(["a", "b"])
    assert fake_bridge.requests[-1]["args"] == {"guids": ["a", "b"]}
    assert out["deleted"] == ["a", "b"]
