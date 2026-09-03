"""MCP server exposing a live Grasshopper canvas to Claude Code.

Run by Claude Code over stdio (see .mcp.json). Every tool is a thin wrapper: it
forwards a command to the Grasshopper bridge component and returns the result.
The bridge does the actual Grasshopper API work on Rhino's UI thread.

Tools are grouped by the milestone that introduced them:
  M1  gh_ping
  M2  gh_get_canvas, gh_get_errors, gh_get_value, gh_solve
  M3  gh_capture_canvas, gh_capture_viewport
  M4  gh_add_component, gh_set_value, gh_connect, gh_disconnect, gh_delete
"""
from __future__ import annotations

import base64
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from .bridge_client import BridgeClient
from .knowledge_base import resolve_component_name

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
    """Delete one or more objects by guid. Each is a named undo record."""
    return _bridge().call("delete", {"guids": guids})


if __name__ == "__main__":
    mcp.run()
