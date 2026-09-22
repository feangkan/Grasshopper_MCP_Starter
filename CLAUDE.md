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

## Reconciling the canvas before a new definition
The bridge shares **one** live Grasshopper canvas across every session and every
project, so nodes from earlier work are routinely still there. Do not just build
on top of them.
- **Read first.** Begin any new definition with `gh_get_canvas`. If objects are
  present that are not part of what the user is now asking for, name them (by
  nickname) and ask: **keep or clear?** Never assume.
- **Clear on request.** "start fresh" / "new project" / "clear the canvas" →
  `gh_clear_canvas`. Run it with `dry_run=True` first, show the user the list,
  then run it for real. It always protects the Claude Bridge component and its
  toggle/panel; pass `keep=[…]` for guids or group-title substrings to spare.
- **Group what you build.** Put each project's nodes in one titled group
  (`gh_annotate` / `gh_create_group`). Then "this project" is a single unit that
  can be kept (`keep=["Tower Study"]`) or cleared later.
- **Never delete the user's manual work** without asking. An object you did not
  create this session and that is not obviously an orphan gets a question first.
- After a build, leave no disconnected leftovers from your own scaffolding —
  delete a component you added and then decided against.

## Choosing input widgets (use `gh_add_input`, not `gh_add_component`)
A generic 3-decimal 0..1 Number Slider is the wrong control for most inputs. For
anything the user will tune, call `gh_add_input` with a `role` chosen by what the
number *means*:
- a **count / N / division count** → `count` (integer slider, no decimals). Never
  a float slider — that is also what caused the "slider re-snapped itself" bug.
- a **0..1 weight / blend / factor** → `factor`; a **percentage** → `percent`;
  an **angle** → `angle`; a **length / distance in mm** → `length`.
- a **random seed** → `seed` (Digit Scroller — scroll each digit over a wide
  integer range; a slider is a poor fit for seeds).
- **on/off** → `toggle`; **pick-one-of-a-set** → a Value List via
  `gh_add_component`.
- **shaping a 1-D form** — a taper, a falloff, a profile, a distribution along a
  length: one **Graph Mapper** (`role="graph"`, `graph_type="Bezier"`) beats
  three sliders. The user drags the curve. If the graph type will not set
  programmatically, say so and tell them the two-click fix.
Pass `min` / `max` / `value` when the context implies a specific range. Always
name the input (`nickname`) in the user's terms and units.

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

## Starting a new Grasshopper project from this repo
This repo is the **starter**, not a home for project work. It stays generic: the
bridge, the server, the docs. Any actual design definition lives in its own
folder outside it.

When the user opens a session with this repo and names a project:
1. **Make the project folder** as a sibling of this repo, named for the project
   (`D:\Claude code\<Project_Name>\`). Never put project files in `grasshopper/`
   -- that directory is gitignored except for `claude_bridge.py`.
2. **Scaffold it**: `<project>/scripts/` for the paste-in `.py` files,
   `<project>/gh/` for the `.gh` definitions, and a `SPEC.md`.
3. **Write `SPEC.md` before writing code.** Reference images, and the 3-5 rules
   the geometry must obey. Sessions sprawl when the target is renegotiated
   mid-iteration; a written spec is what stops that. Re-read it before each
   major change and say so if a request contradicts it.
4. **`gh_ping` immediately** and report whether the bridge is live. If it is
   not, tell the user to open **[`template/Gh_MCP_Starter.gh`](template/Gh_MCP_Starter.gh)**
   in Rhino -- the bridge component is already built and toggled on in that
   file, so this is a one-click open, never a from-scratch paste -- then
   **File > Save As** it into `<project>/gh/` **before any other edit**, so
   Rhino's live document points at the project copy, not the template.
   **Do not build on the template file itself and do not let `Ctrl+S` fire
   while `gh_ping`'s `doc_path` still reads `template/Gh_MCP_Starter.gh`** --
   that silently overwrites the shared starting canvas for every future
   project. If a session's `gh_ping` ever reports that path once real
   components are being added, stop and tell the user to Save As immediately.
5. Reconcile the canvas (see the section above) -- it is shared across projects.

### What the user still has to do by hand
Say this list at the start of every new project, then stop repeating it:
- Open Rhino -> Grasshopper.
- Open **[`template/Gh_MCP_Starter.gh`](template/Gh_MCP_Starter.gh)** (double-click,
  or File > Open) as the starting canvas -- it already has the Claude Bridge
  component pasted in, its `enable` toggle set `true`, wired to `port` (defaults
  9911). This is the one canonical starting point for every new project; nobody
  should paste `claude_bridge.py` by hand again.
- **Immediately File > Save As** into the new project's own `gh/` folder, under
  the project name, *before touching anything else on the canvas*. Never keep
  working in `template/Gh_MCP_Starter.gh` itself and never plain-save (`Ctrl+S`)
  while it is still open under that name -- it must stay pristine, bridge-only,
  for the next project to copy from. If it does get overwritten, restore it
  with `git checkout -- template/Gh_MCP_Starter.gh` (it is tracked in git for
  exactly this reason).
- **File > Save As** again for each further `.gh` version -- the bridge has no
  save command.
- Add or rename a script component's **inputs/outputs** -- `set_script` swaps
  only the body.

## Pushing code into a script component
`gh_set_script(guid, file_path=...)` replaces a Python 3 / GhPython component's
source straight from a file on disk. Use it instead of asking the user to
copy-paste; the `.py` file stays the single source of truth and nothing large
travels through the conversation. It does **not** create inputs or outputs -- ask
the user to add those once, then iterate the body freely.

If it fails, the error names the component type and every property tried; add
the right one to `_SCRIPT_ATTRS` in `claude_bridge.py` rather than working
around it.

## Versioning
- **This repo: git only.** No `_V2` / `(copy)` files. Commit per milestone; tag
  milestones (`git tag v1`). Commit messages describe the behaviour change.
- **Project design scripts: numbered files.** In a project folder, each version
  the user accepts is saved as a new file -- `cluster_field_v1.py`,
  `cluster_field_v2.py`, ... -- and **never overwritten**. `.gh` is binary and
  `.py` design scripts are iterated fast and reverted often; git alone is too
  coarse to get "the one that looked right" back. Before writing, list the
  folder and take the next unused number.
- Python files are `snake_case.py`.

## Milestones (delivered)
M1 liveness · M2 read state · M3 vision · M4 edit · M5 legibility · M6 polish.
Built in fast mode (batched click-tests). The riskiest unknown — a socket server
inside a GH Python component marshalling onto the UI thread — is M1.
