# Lessons

One line per lesson, naming the **cause**. Newest first.

## Confirmed in Rhino 8 (first click-test, 2026-09-03 — Rhino 8.21.25188)

- **The Python 3 Script component's variable IS the input's nickname,
  case-sensitive.** Inputs named `Enable` / `Port` left the code's `enable` /
  `port` undefined -> `NameError` -> caught -> bridge silently stayed OFF. Fix:
  entry point reads `globals().get("enable", globals().get("Enable", False))`;
  still, name the inputs lowercase.

- **`type(obj).__name__` returns the interface (`IGH_DocumentObject`) under
  pythonnet, not the concrete class.** Every slider/panel/toggle check and all
  value reads silently no-opped. Fix: `type_name(obj)` -> `obj.GetType().Name`
  (gives `GH_NumberSlider`, `GH_Panel`, `Component_Circle`, `Python3Component`).

- **`IGH_Structure` volatile-data iteration.** `data.PathCount` / `data.Path(i)`
  / `data.Branch(path)` threw, was swallowed by a bare `except`, so `get_value`
  returned `count: 0` even when `VolatileDataCount` was 1. Fix: iterate
  `param.VolatileData.AllData(True)` and take `count` from
  `param.VolatileDataCount`. Read errors now surface as `read_error` in the
  result instead of an empty list.

- **Never swallow a Rhino API exception silently.** All three bugs above were
  masked by bare `except: pass`. Handlers now attach the error to the response
  (`*_err`, `read_error`) so the next probe sees it.

- **`GH_NumberSlider.SetSliderValue` clamps to the slider's range.** Setting 11
  on a default 0..1 slider silently became 1.0. `set_value` now widens
  `Slider.Minimum` / `Slider.Maximum` to fit and returns `applied` + a `note`.

- **Decimal -> float via pythonnet is flaky.** `float(obj.CurrentValue)` on a
  `System.Decimal` could throw. Use `float(str(x))` (`_num`).

- **`mcp` 2.x renamed `FastMCP` to `MCPServer`.** `from mcp.server.mcpserver
  import MCPServer, Image`; `.tool()` / `.run()` unchanged. Pinned `mcp>=2,<3`.

- **pytest could not import `server/`.** Fixed with `pythonpath = ["."]` in
  `[tool.pytest.ini_options]`.

## Verified working in Rhino 8

M1 ping · M2 get_canvas / get_errors / get_value / solve · M3 capture_viewport ·
M4 add_component (catalogue fuzzy match) / connect (by param name) / set_value /
delete · M5 set_nickname / create_group (+colour) / add_panel / add_scribble /
batch / set_pivot. Undo records show as `Claude: ...` in the Edit menu.

## Still weak

- **`capture_canvas` only grabs the visible canvas region.**
  `GH_Canvas.GenerateHiResImage` does not exist in this build; the `DrawToBitmap`
  fallback captures the control at its current on-screen size, so a hidden or
  small Grasshopper window yields a cropped shot. Workaround: bring the GH window
  forward and size it before asking. A proper full-definition renderer (walk
  `doc` attributes onto a sized `Graphics`) is deferred. `capture_viewport` (the
  geometry) is unaffected and reliable — prefer it.

- **Multi-delete writes one undo record per object**, not one combined record.
  Cosmetic; `GH_UndoRecord` batching is a future refinement.
