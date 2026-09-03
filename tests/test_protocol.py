"""Protocol constants and the command surface stay in sync with the tools."""
from __future__ import annotations

from server import protocol
from server.gh_mcp_server import _annotate_plan


def test_schema_is_versioned():
    assert protocol.SCHEMA.startswith("claude_gh_bridge/")


def test_every_command_is_unique_and_lowercase():
    cmds = protocol.COMMANDS
    assert len(cmds) == len(set(cmds))
    assert all(c == c.lower() and " " not in c for c in cmds)


def test_command_set_matches_expectation():
    # a change here is a protocol change -- update the bridge HANDLERS to match
    assert set(protocol.COMMANDS) == {
        "ping",
        "get_canvas", "get_errors", "get_value", "solve",
        "capture_canvas", "capture_viewport",
        "add_component", "set_value", "connect", "disconnect", "delete", "set_pivot",
        "set_nickname", "create_group", "add_panel", "add_scribble",
        "batch",
    }


def test_annotate_plan_groups_then_notes_above():
    plan = _annotate_plan(["g1", "g2"], "INPUTS", "drag the green sliders", None, 1)

    assert [step["cmd"] for step in plan] == ["create_group", "add_panel"]
    group, panel = plan
    assert group["args"]["name"] == "1 - INPUTS"
    assert group["args"]["colour"] == "#d7ecd9"          # stage 1 -> green
    assert group["args"]["guids"] == ["g1", "g2"]
    assert panel["args"]["anchor"] == "above"
    assert panel["args"]["anchor_group_of"] == ["g1", "g2"]
    assert panel["args"]["text"] == "drag the green sliders"


def test_annotate_plan_defaults_later_stages_to_grey():
    plan = _annotate_plan(["g1"], "SOLVER", "internal", None, 3)
    assert plan[0]["args"]["colour"] == "#e6e6e6"
    assert plan[0]["args"]["name"] == "3 - SOLVER"


def test_annotate_plan_respects_explicit_colour():
    plan = _annotate_plan(["g1"], "GEOMETRY", "n", "#d8e6f3", 2)
    assert plan[0]["args"]["colour"] == "#d8e6f3"
