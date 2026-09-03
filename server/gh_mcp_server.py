"""MCP server exposing a live Grasshopper canvas to Claude Code.

Run by Claude Code over stdio (see .mcp.json). Every tool is a thin wrapper: it
forwards a command to the Grasshopper bridge component and returns the result.
The bridge does the actual Grasshopper API work on Rhino's UI thread.

Tools are grouped by the milestone that introduced them:
  M1  gh_ping
"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

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


if __name__ == "__main__":
    mcp.run()
