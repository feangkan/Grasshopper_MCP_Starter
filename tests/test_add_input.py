"""gh_add_input forwards role + overrides to the bridge; the widget choice
itself is made in the bridge (needs Rhino) so only the wiring is tested here."""
from __future__ import annotations

from server.gh_mcp_server import gh_add_input


def test_role_and_position_forwarded(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"kind": "Number Slider", "role": "count"}}
    gh_add_input("count", 100, 200, nickname="Floors")
    sent = fake_bridge.requests[-1]
    assert sent["cmd"] == "add_input"
    assert sent["args"]["role"] == "count"
    assert sent["args"]["x"] == 100 and sent["args"]["y"] == 200
    assert sent["args"]["nickname"] == "Floors"


def test_defaults_leave_range_unset_for_the_bridge_to_fill(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {}}
    gh_add_input("factor", 0, 0)
    args = fake_bridge.requests[-1]["args"]
    assert args["min"] is None and args["max"] is None and args["value"] is None
    assert args["graph_type"] == "Bezier"


def test_overrides_pass_through(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {}}
    gh_add_input("length", 0, 0, min=500, max=8000, value=3000)
    args = fake_bridge.requests[-1]["args"]
    assert (args["min"], args["max"], args["value"]) == (500, 8000, 3000)


def test_graph_type_forwarded(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"kind": "Graph Mapper"}}
    gh_add_input("falloff", 0, 0, graph_type="Gaussian")
    assert fake_bridge.requests[-1]["args"]["graph_type"] == "Gaussian"


def test_seed_role_forwarded(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"kind": "Digit Scroller", "role": "seed"}}
    out = gh_add_input("seed", 40, 40)
    assert fake_bridge.requests[-1]["args"]["role"] == "seed"
    assert out["kind"] == "Digit Scroller"
