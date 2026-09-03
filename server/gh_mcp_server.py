"""MCP server exposing a live Grasshopper canvas to Claude Code.

Run by Claude Code over stdio (see .mcp.json). Every tool is a thin wrapper: it
forwards a command to the Grasshopper bridge component and returns the result.
The bridge does the actual Grasshopper API work on Rhino's UI thread.

Tools are grouped by the milestone that introduced them:
  M1  gh_ping
  M2  gh_get_canvas, gh_get_errors, gh_get_value, gh_solve
  M3  gh_capture_canvas, gh_capture_viewport
"""
from __future__ import annotations

import base64
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from .bridge_client import BridgeClient

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


if __name__ == "__main__":
    mcp.run()
