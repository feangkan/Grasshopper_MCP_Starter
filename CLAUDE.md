# Project rules (auto-loaded by Claude Code)

This repo is a **Claude <-> Grasshopper bridge**: an MCP server (`server/`) plus a
paste-in Grasshopper component (`grasshopper/claude_bridge.py`). It is not a
Rhino Eto tool, so the CONFIG -> ENGINE -> RHINO I/O -> GUI layering of the
architectural-python-starter does not apply. These rules do.

## Architecture
- **Two halves, one contract.** `server/protocol.py` holds `SCHEMA` and the
  command list. The server sends commands; the bridge executes them. If you
  change the wire format, bump `SCHEMA` in *both* `protocol.py` and
  `claude_bridge.py` — the client refuses a mismatch loudly rather than guessing.
- **The server is thin.** Each MCP tool forwards one command and returns the
  result. Real logic that can be unit-tested (name resolution, layout maths)
  lives in its own module (`knowledge_base.py`, `layout.py`), never inline in a
  tool.
- **The bridge is one self-contained file.** It must paste into a Grasshopper
  Python 3 Script component with no local imports, so it is exempt from the
  "split by responsibility into multiple files" rule. Keep functions <= 60 lines
  and handlers small; that is the budget that still applies.
- **Everything that touches the Grasshopper document runs on the UI thread**, via
  `run_on_ui_thread`. Never call a `GH_Document` / `IGH_*` method from the socket
  thread directly — it will corrupt state or crash Rhino intermittently.

## Safety and the live-edit contract (do not weaken these)
- Address objects by **InstanceGuid**, never by index or canvas position. The
  user drags things while we work; a stale index points at the wrong object.
- **Re-read before you write.** Call `gh_get_canvas` again if the user may have
  edited since the last snapshot. Do not act on a snapshot from three steps ago.
- **Never clear-and-rebuild.** Diff and patch. The user's manual work on the
  canvas must survive everything we do.
- **Every mutation is wrapped in a named undo record** — `doc.UndoUtil.Record*`
  with a `"Claude: ..."` label — so the user can `Ctrl+Z` it and see what it was.
  A new handler that mutates the document without an undo record is a bug.
- The bridge listens on `127.0.0.1` only and has no auth. Do not add a bind
  address option that accepts anything else.

## The working loop (this is the product, not a nicety)
After each build step, in order:
1. `gh_solve` (or rely on the auto-solve the mutation triggered).
2. `gh_get_errors` — read the red/orange bubbles. Fix the cause, not the symptom.
3. `gh_capture_viewport` and/or `gh_capture_canvas` — actually look. Is the
   geometry what was asked for? Is the graph sane?
4. Report to the user: what changed, what you noticed, and **two or three
   concrete next moves** they can pick from. Keep offering suggestions as you
   build — that is an explicit requirement, not an optional extra.
5. If something is wrong, close the loop: root-cause fix -> offline regression
   test if it is reproducible without Rhino -> one line in `LESSONS.md` naming
   the cause -> its own commit.

## Making definitions legible (`docs/DOC_STYLE.md`)
When the user asks for something usable by other people, apply the full house
style unless they opt out:
- Colour-coded groups: green `#d7ecd9` = inputs they edit, blue `#d8e6f3` =
  geometry, orange `#f6e0c8` = outputs, grey `#e6e6e6` = internals.
- Numbered stage titles: `1 - INPUTS - Tower Dimensions`.
- One note panel per group, anchored above it, in plain language: what this
  stage does, which sliders to touch, sensible ranges.
- Readable nicknames on every input (`Tower Height (m)`, not `Number Slider`).
- A README panel top-left: what the whole definition does, what to touch, what
  comes out.
- `gh_auto_layout` to arrange stages left to right once the groups exist.
`gh_annotate` does group + colour + note panel in one call; prefer it.

## Testing
- Offline tests (`uv run --extra dev pytest`) prove the server halves that do not
  need Rhino: protocol framing, lockfile discovery, error mapping, name
  resolution, `compute_layout` against known coordinates. Assert analytic
  answers, not current output.
- Offline tests **cannot** prove the bridge's Grasshopper API calls. Those are
  verified by opening Rhino and trying them. Every such call that has not yet
  been run in Rhino is listed in `LESSONS.md` under "Unverified".
- A bridge bug found in Rhino gets: root-cause fix, a `LESSONS.md` line naming
  the cause, and its own commit.

## Versioning
- Git only. No `_V2` / `(copy)` files. Commit per milestone; tag milestones
  (`git tag v1`). Commit messages describe the behaviour change.
- Python files are `snake_case.py`.

## Milestones (delivered)
M1 liveness · M2 read state · M3 vision · M4 edit · M5 legibility · M6 polish.
Built in fast mode (batched click-tests). The riskiest unknown — a socket server
inside a GH Python component marshalling onto the UI thread — is M1.
