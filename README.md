# Grasshopper MCP Bridge

Chat to Claude Code, watch it build in Grasshopper. Claude can **read** your
definition, **see** the canvas and the resulting geometry, and **edit** the graph
— add components, wire them, set sliders, group and annotate — all on your live
canvas while you keep working in it.

```
Claude Code ──stdio(MCP)──► MCP server (this repo) ──localhost TCP/JSON──► Claude Bridge component ──► live Grasshopper
```

Nothing leaves your machine: the bridge listens on `127.0.0.1` only, and the MCP
server runs locally under Claude Code. No cloud, no account, no cost beyond your
normal Claude Code usage.

---

## What you get

| Area | Tools |
|---|---|
| **Liveness** | `gh_ping` |
| **Read** | `gh_get_canvas`, `gh_get_errors`, `gh_get_value`, `gh_solve` |
| **See** | `gh_capture_canvas`, `gh_capture_viewport` (real PNGs back to Claude) |
| **Edit** | `gh_add_component`, `gh_set_value`, `gh_connect`, `gh_disconnect`, `gh_delete` |
| **Explain** | `gh_set_nickname`, `gh_create_group`, `gh_add_panel`, `gh_add_scribble`, `gh_annotate`, `gh_auto_layout` |

Every edit is wrapped in a **named Grasshopper undo record** (`Claude: add Circle`,
`Claude: connect wire`, …) so you can `Ctrl+Z` anything and see exactly what it
was. Objects are addressed by **InstanceGuid**, so dragging things around while
Claude works never breaks its references.

---

## Setup (one time)

Full detail in [`docs/SETUP.md`](docs/SETUP.md). Short version:

1. **Register the MCP server.** `.mcp.json` in this repo already does it for
   Claude Code launched from this folder. It runs the server with
   [`uv`](https://docs.astral.sh/uv/) — install that if you don't have it.
2. **Add the bridge to Grasshopper.** In Rhino 8: open Grasshopper → drop a
   **Python 3 Script** component → paste all of
   [`grasshopper/claude_bridge.py`](grasshopper/claude_bridge.py) → give it a
   Boolean `enable` input (a Boolean Toggle) and an optional integer `port`
   input. Set `enable` to **True**. The component reads
   `Claude bridge LISTENING on 127.0.0.1:9911`.
3. **Check it.** Ask Claude: *"ping grasshopper."* You should get back your Rhino
   version and the open document's name.

---

## Using it

Just talk. *"Add a number slider and a circle, wire the slider to the circle
radius, set the slider to 12."* Claude will `gh_get_canvas`, place the
components, `gh_connect` them, `gh_set_value`, `gh_solve`, then `gh_capture_viewport`
to confirm the geometry looks right.

Claude's working loop (see [`CLAUDE.md`](CLAUDE.md)): **build → solve → read
errors → look at the result → fix → suggest next steps.** It reports what changed
and offers two or three concrete next moves after each step. You can edit the
canvas at any point; Claude re-reads before it writes.

For definitions other people will use, ask for the house style
([`docs/DOC_STYLE.md`](docs/DOC_STYLE.md)): colour-coded numbered groups, a
plain-language note panel per group, readable nicknames, and a README panel
top-left. `gh_auto_layout` then arranges the stages left to right.

---

## Status

- **Server side** (protocol, discovery, name resolution, layout maths) — covered
  by `pytest` (`uv run --extra dev pytest`), 52 tests, no Rhino needed.
- **Bridge side** — click-tested in Rhino 8.21 on 2026-09-03. Working: ping,
  get_canvas, get_errors, get_value, solve, capture_viewport, add_component,
  connect, set_value, delete, set_nickname, create_group, add_panel,
  add_scribble, batch, set_pivot. Known-weak: `capture_canvas` only grabs the
  visible canvas region (see [`LESSONS.md`](LESSONS.md)).

Built milestone by milestone (M1 liveness → M6 polish); see the git history and
[`docs/TOOLS.md`](docs/TOOLS.md).
