# Setup

## Requirements

| Need | Why | Check |
|---|---|---|
| Rhino 8 (Windows or Mac) | hosts Grasshopper and the bridge component | — |
| [`uv`](https://docs.astral.sh/uv/) | runs the MCP server and its `mcp` dependency in an isolated env | `uv --version` |
| Claude Code | the MCP client | — |

No manual `pip install`. `uv` reads `pyproject.toml` and builds the environment
on first run.

## 1. Register the MCP server with Claude Code

This repo ships `.mcp.json`:

```json
{
  "mcpServers": {
    "grasshopper": {
      "command": "uv",
      "args": ["run", "--directory", "D:\\Claude code\\Grasshopper_MCP",
               "python", "-m", "server.gh_mcp_server"]
    }
  }
}
```

Launch Claude Code from `D:\Claude code\Grasshopper_MCP` (or point your global
`~/.claude.json` at the same command) and it starts the server over stdio. If you
cloned elsewhere, edit the `--directory` path.

Confirm Claude Code sees it: the `grasshopper` server should list 18 `gh_*`
tools.

## 2. Add the bridge component in Grasshopper

1. Open Rhino 8, run `Grasshopper`.
2. Drop a **Python 3 Script** component on the canvas (Maths ▸ Script, or
   double-click the canvas and type `python`).
3. Open its editor. Delete the sample code. Paste **all of**
   `grasshopper/claude_bridge.py`.
4. Give the component its inputs (right-click the component ▸ zoom in ▸ use the
   `+` on the input side, or edit in the script editor's parameter panel):
   - `enable` — type **bool**. Wire a **Boolean Toggle** to it.
   - `port` — type **int**, optional. Leave unwired to use `9911`.
5. Rename the single output to `log` if you like (the code also writes the
   default `a`).
6. Set the Boolean Toggle to **True**.

The component should show:

```
Claude bridge LISTENING on 127.0.0.1:9911   doc: unsaved
```

and a file `claude_gh_bridge.json` appears in your temp folder (that is how the
server finds the port — it is git-ignored and deleted when you toggle `enable`
off).

## 3. Smoke test

In Claude Code:

> ping grasshopper

Expect something like:

```json
{
  "bridge_schema": "claude_gh_bridge/1",
  "rhino": "8.x.xxxxx",
  "grasshopper": "8.x.xxxxx.x",
  "doc_name": "unsaved",
  "object_count": 2
}
```

Then try:

> read my canvas

> add a number slider at 200,200 and a circle at 450,200, wire them, set the slider to 10, and show me the viewport

## Troubleshooting

| Symptom | Fix |
|---|---|
| *"bridge is not running"* | Toggle `enable` off then on. Confirm the component says `LISTENING`. |
| *"Could not reach the bridge on …"* | A stale `claude_gh_bridge.json` from a previous Rhino session. Toggle `enable` off (removes it) then on. |
| *"schema mismatch"* | `claude_bridge.py` on the canvas is a different version from `server/protocol.py`. Re-paste the file. |
| Bridge says `LISTENING` but calls hang | A modal dialog is open in Rhino/Grasshopper, blocking the UI thread. Close it. |
| Panel wired to output shows nothing | Wire it to the **`a`** output, not `out`. `out` is only the print stream; the status line is in the script variable `a`. |
| Bridge stays `OFF` with the toggle on | The inputs must be named **`enable`** / **`port`** (lowercase) — the script variable is the parameter nickname, case-sensitive. Rename them and flip the toggle. |
| Edits don't appear | Check `gh_get_errors`. Also make sure you pasted the whole file — a truncated paste fails silently on some commands. |
| `gh_capture_canvas` looks cropped | It captures the visible Grasshopper canvas. Bring the GH window forward and size it first. `gh_capture_viewport` (the geometry) is unaffected. |
| Port already in use | Wire an integer to `port` (e.g. `9912`) and toggle `enable` off/on. |
| Picked up code edits? | Toggle `enable` **off then on** — that restarts the socket server with the new code. |
