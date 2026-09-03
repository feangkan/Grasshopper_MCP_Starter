"""MCP server exposing a live Grasshopper canvas to Claude Code.

Run by Claude Code over stdio (see .mcp.json). Every tool is a thin wrapper: it
forwards a command to the Grasshopper bridge component and returns the result.
The bridge does the actual Grasshopper API work on Rhino's UI thread.

Tools are grouped by the milestone that introduced them:
  M1  gh_ping
  M2  gh_get_canvas, gh_get_errors, gh_get_value, gh_solve
  M3  gh_capture_canvas, gh_capture_viewport
  M4  gh_add_component, gh_set_value, gh_connect, gh_disconnect, gh_delete
  M5  gh_set_nickname, gh_create_group, gh_add_panel, gh_add_scribble,
      gh_annotate, gh_auto_layout
"""
from __future__ import annotations

import base64
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from .bridge_client import BridgeClient
from .knowledge_base import resolve_component_name
from .layout import compute_layout

mcp = MCPServer("grasshopper")


def _bridge() -> BridgeClient:
    return BridgeClient()


# ---------------------------------------------------------------------------
# M1 -- liveness
# ---------------------------------------------------------------------------
@mcp.tool()
def gh_ping() -> dict[str, Any]:
    """Check that the Grasshopper bridge is alive.

    Returns Rhino/Grasshopper versions, the active document name, and how many
    objects are on the canvas. Call this first when something seems wrong.
    """
    return _bridge().call("ping")


# ---------------------------------------------------------------------------
# M2 -- read the canvas
# ---------------------------------------------------------------------------
@mcp.tool()
def gh_get_canvas() -> dict[str, Any]:
    """Read the whole definition: every component, its InstanceGuid, nickname,
    position, parameters and current values, plus wires and groups.

    Objects are identified by 'guid' (Grasshopper's InstanceGuid) everywhere in
    this API. That id is stable when the user drags things around, so a snapshot
    stays valid across manual edits -- but re-read before writing if the user has
    been editing.
    """
    return _bridge().call("get_canvas")


@mcp.tool()
def gh_get_errors() -> dict[str, Any]:
    """List runtime errors and warnings currently shown on components
    (the red/orange bubbles), each with the owning component's guid and nickname.
    """
    return _bridge().call("get_errors")


@mcp.tool()
def gh_get_value(guid: str, param: str | None = None) -> dict[str, Any]:
    """Read the computed data on a component's parameter (or a standalone
    parameter like a slider/panel).

    guid   InstanceGuid from gh_get_canvas.
    param  Output parameter name or nickname. Omit for a single-output object
           (slider, panel) or to get the first output.
    """
    return _bridge().call("get_value", {"guid": guid, "param": param})


@mcp.tool()
def gh_solve(force: bool = False) -> dict[str, Any]:
    """Recompute the definition and report how long it took and the resulting
    error/warning counts. force=True expires every object first (a full rebuild).
    """
    return _bridge().call("solve", {"force": force})


# ---------------------------------------------------------------------------
# M3 -- vision
# ---------------------------------------------------------------------------
@mcp.tool()
def gh_capture_canvas(zoom_fit: bool = True) -> Image:
    """Return a PNG screenshot of the Grasshopper canvas so Claude can see the
    node graph. zoom_fit=True asks Grasshopper to frame all components first.
    """
    result = _bridge().call("capture_canvas", {"zoom_fit": zoom_fit})
    return _png(result)


@mcp.tool()
def gh_capture_viewport(width: int = 1280, height: int = 720) -> Image:
    """Return a PNG screenshot of the active Rhino viewport so Claude can see the
    geometry the definition produces.
    """
    result = _bridge().call("capture_viewport", {"width": width, "height": height})
    return _png(result)


def _png(result: dict[str, Any]) -> Image:
    data = base64.b64decode(result["png_base64"])
    return Image(data=data, format="png")


# ---------------------------------------------------------------------------
# M4 -- edit the canvas (every mutation is wrapped in a named Grasshopper undo
# record, so the user can Ctrl+Z anything Claude does and see what it was)
# ---------------------------------------------------------------------------
@mcp.tool()
def gh_add_component(name: str, x: float, y: float, nickname: str | None = None) -> dict[str, Any]:
    """Place a component on the canvas.

    name      Friendly or exact name -- "slider", "number slider", "circle",
              "python", "panel", "move", "series"... resolved by fuzzy match.
    x, y      Canvas pixel coordinates (origin top-left, +x right, +y down).
              Space stages ~260px apart in x, components ~90px apart in y.
    nickname  Optional human label, e.g. "Tower Height (m)".

    Returns the new object's guid and which catalogue name it matched.
    """
    canonical = resolve_component_name(name)
    return _bridge().call(
        "add_component",
        {"name": canonical, "requested": name, "x": x, "y": y, "nickname": nickname},
    )


@mcp.tool()
def gh_set_value(guid: str, value: Any) -> dict[str, Any]:
    """Set the value of a slider, boolean toggle, panel, or value list.
    For a slider pass a number; for a toggle pass true/false; for a panel pass text.
    """
    return _bridge().call("set_value", {"guid": guid, "value": value})


@mcp.tool()
def gh_connect(
    source: str,
    target: str,
    source_param: str | None = None,
    target_param: str | None = None,
) -> dict[str, Any]:
    """Wire an output to an input.

    source / target   component or parameter guids.
    source_param       output name/nickname/index on the source (omit if single-output).
    target_param       input name/nickname/index on the target (omit if single-input).
    """
    return _bridge().call(
        "connect",
        {
            "source": source,
            "target": target,
            "source_param": source_param,
            "target_param": target_param,
        },
    )


@mcp.tool()
def gh_disconnect(source: str, target: str, target_param: str | None = None) -> dict[str, Any]:
    """Remove a wire from source into target (optionally a specific input param)."""
    return _bridge().call(
        "disconnect", {"source": source, "target": target, "target_param": target_param}
    )


@mcp.tool()
def gh_delete(guids: list[str]) -> dict[str, Any]:
    """Delete one or more objects by guid. Wrapped in a single undo record."""
    return _bridge().call("delete", {"guids": guids})


# ---------------------------------------------------------------------------
# M5 -- make the definition legible to someone who did not build it
# ---------------------------------------------------------------------------
@mcp.tool()
def gh_set_nickname(guid: str, nickname: str) -> dict[str, Any]:
    """Rename an object's nickname (what shows on the component and on hover)."""
    return _bridge().call("set_nickname", {"guid": guid, "nickname": nickname})


@mcp.tool()
def gh_create_group(
    guids: list[str], name: str, colour: str | None = None
) -> dict[str, Any]:
    """Group objects and give the group a title.

    colour  Optional "#rrggbb". Convention:
            green  #d7ecd9  inputs the user edits
            blue   #d8e6f3  geometry
            orange #f6e0c8  outputs
            grey   #e6e6e6  internal machinery
    """
    return _bridge().call("create_group", {"guids": guids, "name": name, "colour": colour})


@mcp.tool()
def gh_add_panel(
    x: float, y: float, text: str, nickname: str | None = None,
    width: float = 200, height: float = 90,
) -> dict[str, Any]:
    """Drop a text panel on the canvas -- use it as a how-to note next to a group."""
    return _bridge().call(
        "add_panel",
        {"x": x, "y": y, "text": text, "nickname": nickname, "width": width, "height": height},
    )


@mcp.tool()
def gh_add_scribble(x: float, y: float, text: str, size: float = 20) -> dict[str, Any]:
    """Add a large free-floating scribble label (a heading on the canvas)."""
    return _bridge().call("add_scribble", {"x": x, "y": y, "text": text, "size": size})


@mcp.tool()
def gh_annotate(
    guids: list[str],
    title: str,
    note: str,
    colour: str | None = None,
    stage: int | None = None,
) -> dict[str, Any]:
    """One call to make a group legible: colour + title it, and place a how-to
    note panel just above it.

    guids   objects to group.
    title   group heading, e.g. "INPUTS -- Tower Dimensions".
    note    plain-language instructions shown in a panel above the group.
    colour  "#rrggbb"; defaults to green if stage in (None, 1), else grey.
    stage   optional stage number; prefixes the title as "N - ...".
    """
    return _bridge().call(
        "batch",
        {"commands": _annotate_plan(guids, title, note, colour, stage)},
    )


@mcp.tool()
def gh_auto_layout(
    origin_x: float = 80, origin_y: float = 80,
    col_gap: float = 260, row_gap: float = 90,
) -> dict[str, Any]:
    """Tidy the canvas: lay groups out left-to-right in stage order on a grid,
    stacking each group's components vertically. Reads the canvas, computes new
    positions, and moves everything in one undo record.
    """
    canvas = _bridge().call("get_canvas")
    moves = compute_layout(
        canvas,
        origin_x=origin_x, origin_y=origin_y, col_gap=col_gap, row_gap=row_gap,
    )
    if not moves:
        return {"moved": 0}
    cmds = [{"cmd": "set_pivot", "args": m} for m in moves]
    _bridge().call("batch", {"commands": cmds})
    return {"moved": len(moves)}


def _annotate_plan(guids, title, note, colour, stage):
    heading = f"{stage} - {title}" if stage is not None else title
    if colour is None:
        colour = "#d7ecd9" if stage in (None, 1) else "#e6e6e6"
    return [
        {"cmd": "create_group", "args": {"guids": guids, "name": heading, "colour": colour}},
        {"cmd": "add_panel", "args": {
            "x": 0, "y": 0, "text": note, "nickname": f"{heading} - how to",
            "anchor_group_of": guids, "anchor": "above",
        }},
    ]


if __name__ == "__main__":
    mcp.run()
