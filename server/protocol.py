"""Wire contract between the MCP server and the Grasshopper bridge component.

Transport: newline-delimited JSON over a localhost TCP socket. One request per
line, one response per line, synchronous per connection. The MCP server opens a
fresh connection for every call (simple and robust; no multiplexing).

Request   {"id": "<uuid>", "cmd": "<name>", "args": {...}}
Response  {"id": "<uuid>", "ok": true,  "result": {...}}
          {"id": "<uuid>", "ok": false, "error": "<message>", "trace": "<optional>"}

The bridge writes a lockfile so the server can discover the port without
configuration. Both halves must agree on SCHEMA; bump it on any breaking change
and the mismatched side logs loudly rather than guessing.
"""

SCHEMA = "claude_gh_bridge/1"

# Lockfile lives in the OS temp dir; see bridge_client.lockfile_path().
LOCKFILE_NAME = "claude_gh_bridge.json"

# Default port the bridge listens on when the component's `port` input is unset.
DEFAULT_PORT = 9911

# Socket framing.
ENCODING = "utf-8"
TERMINATOR = "\n"

# Every command name the bridge understands. Kept here so the server and the
# test suite share one source of truth. Grows as milestones land.
COMMANDS = (
    # --- M1: liveness -----------------------------------------------------
    "ping",
    # --- M2: read state -------------------------------------------------
    "get_canvas",
    "get_errors",
    "get_value",
    "solve",
    # --- M3: vision ---------------------------------------------------
    "capture_canvas",
    "capture_viewport",
    # --- M4: edit ---------------------------------------------------
    "add_component",
    "set_value",
    "connect",
    "disconnect",
    "delete",
    "set_pivot",
)


class BridgeError(RuntimeError):
    """Raised by the client when the bridge reports ok:false or cannot be reached."""
