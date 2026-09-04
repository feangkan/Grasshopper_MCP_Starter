# Tools

Every tool is an MCP tool on the `grasshopper` server. All coordinates are
Grasshopper canvas pixels: origin top-left, `+x` right, `+y` down. Stages are
usually ~260 px apart in `x`; components in a stage ~90 px apart in `y`.

Objects are identified by `guid` — Grasshopper's InstanceGuid, as returned by
`gh_get_canvas`. That id survives the user dragging the object, renaming it, or
regrouping it.

---

## M1 — liveness

### `gh_ping()`
Round-trip check. Returns `bridge_schema`, `rhino`, `rhino_build`,
`grasshopper`, `doc_name`, `doc_path`, `object_count`. Call it first whenever
something behaves oddly.

---

## M2 — read the canvas

### `gh_get_canvas()`
The whole definition:
- `objects[]` — `guid`, `name`, `nickname`, `kind` (`component` / `param` /
  type name), `type_name`, `pivot {x,y}`. Components also carry `inputs[]` and
  `outputs[]` (each: `name`, `nickname`, `type`, `guid`, `data_count`,
  `sources[]`). Sliders carry `value/min/max`; toggles and panels carry `value`.
- `groups[]` — `guid`, `name`, `colour`, `member_guids[]`.
- `wires[]` — `from_obj`, `from_param`, `to_obj`, `to_param`.
- `truncated` — true if the definition exceeded the read cap (800 objects).

### `gh_get_errors()`
`messages[]` of `{guid, nickname, name, level, text}` for every red (error) and
orange (warning) bubble, plus `error_count` / `warning_count`.

### `gh_get_value(guid, param=None)`
The computed data on an output. `param` is an output name / nickname / index;
omit for a slider, panel, or single-output component. Returns `type`, `count`,
`values[]` (stringified, capped at 200), `truncated`.

### `gh_solve(force=False)`
Recompute. `force=True` expires every object first. Returns `duration_ms`,
`errors`, `warnings`.

---

## M3 — see

### `gh_capture_canvas(zoom_fit=True)`
PNG of the node graph. `zoom_fit` frames all components first. Returns an image.

### `gh_capture_viewport(width=1280, height=720)`
PNG of the active Rhino viewport — the geometry the definition produces.

---

## M4 — edit  (each call = one named undo record)

### `gh_add_component(name, x, y, nickname=None)`
`name` is fuzzy-matched: `"slider"`, `"number slider"`, `"circle"`, `"py"`,
`"move"`, `"series"`… (`server/knowledge_base.py` lists the shorthands; the
bridge also matches against the live component catalogue). Returns `guid`,
`name`, `nickname`, `matched_from`.

### `gh_add_input(role, x, y, nickname=None, min=None, max=None, value=None, graph_type="Bezier")`
Place a **correctly-configured input widget** — prefer this over
`gh_add_component` for anything the user will tune. `role` is chosen by meaning:

| role | widget | default range / accuracy |
|---|---|---|
| `count` `integer` `n` `divisions` | Number Slider | integer, 0–50, 0 dp |
| `even` `odd` | Number Slider | snapped even / odd |
| `fraction` `factor` `ratio` | Number Slider | float 0–1, 3 dp |
| `percent` | Number Slider | float 0–100, 0 dp |
| `angle` | Number Slider | float 0–360, 1 dp |
| `length` `distance` | Number Slider | float 0–1000, 1 dp |
| `number` | Number Slider | float 0–100, 2 dp |
| `seed` | Digit Scroller (integer slider if absent) | 0–9999 |
| `toggle` `boolean` `switch` | Boolean Toggle | — |
| `graph` `profile` `falloff` `distribution` `curve_control` | Graph Mapper | `graph_type`: Bezier (default), Linear, Sine, Parabola, Power, Perlin, Gaussian |

`min` / `max` / `value` override the role defaults. A slider given no value starts
at the midpoint. Returns the widget kind, resolved range/accuracy, and value.

### `gh_set_value(guid, value)`
Slider → number (rounded to the slider's own accuracy — integer sliders stay
integer); Boolean Toggle → true/false; Panel → text; Value List → item name or
expression. Out-of-range numbers widen the slider and are reported in `note`.

### `gh_connect(source, target, source_param=None, target_param=None)`
Wire an output to an input. Params are name / nickname / index; omit for
single-output / single-input objects.

### `gh_disconnect(source, target, target_param=None)`
Remove one wire.

### `gh_delete(guids)`
Delete objects by guid.

---

## M5 — explain

### `gh_set_nickname(guid, nickname)`
Rename what shows on the object and on hover.

### `gh_create_group(guids, name, colour=None)`
Group objects, title the group. `colour` is `"#rrggbb"`. Convention: green
`#d7ecd9` inputs, blue `#d8e6f3` geometry, orange `#f6e0c8` outputs, grey
`#e6e6e6` internals.

### `gh_add_panel(x, y, text, nickname=None, width=200, height=90)`
A text panel — use as a how-to note beside a group.

### `gh_add_scribble(x, y, text, size=20)`
A large free-floating canvas heading.

### `gh_annotate(guids, title, note, colour=None, stage=None)`
**One call** to make a group legible: it groups + colours the objects and drops a
plain-language note panel just above them. `stage` prefixes the title (`2 - …`)
and, when `colour` is omitted, picks green for stage 1 / grey for later stages.
Prefer this over calling `gh_create_group` + `gh_add_panel` separately.

### `gh_auto_layout(origin_x=80, origin_y=80, col_gap=260, row_gap=90)`
Reads the canvas, lays groups out left-to-right in stage order (a leading number
in the group title sets the order), stacks each group's members vertically, and
moves everything. Ungrouped objects go in a trailing column. Objects already in
place are not touched.

---

## Housekeeping

The bridge drives **one** Grasshopper canvas, shared by every session. Nodes from
earlier work stay put until removed.

### `gh_clear_canvas(keep=None, dry_run=False)`
Delete everything on the canvas except:
- the **Claude Bridge** component and whatever is wired to it — always protected,
  so clearing can't sever the connection;
- any InstanceGuid listed in `keep`;
- any group whose **title contains** a string in `keep` — keeps that whole group
  and its members (e.g. `keep=["Tower Study"]`).

`dry_run=True` returns `would_delete[]` and changes nothing — use it to show the
list and confirm first. One undo record; `Ctrl+Z` restores everything.
