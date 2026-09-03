# Lessons

One line per lesson, naming the **cause**. Newest first.

## Confirmed

- **`mcp` 2.x renamed `FastMCP` to `MCPServer`.** `from mcp.server.fastmcp import
  FastMCP` raises a migration error on import under mcp >= 2. Use
  `from mcp.server.mcpserver import MCPServer, Image`; the `.tool()` decorator and
  `.run()` are unchanged. `pyproject.toml` pins `mcp>=2,<3`.

- **pytest could not import `server/`.** No `src` layout and the project is not
  installed, so the repo root was not on `sys.path`. Fixed with
  `pythonpath = ["."]` in `[tool.pytest.ini_options]`, not by adding
  `__init__.py` to `tests/`.

- **`compute_layout` no-ops an object already at its target.** A test assumed
  every member appears in the move list; an object already at the computed pixel
  is deliberately omitted so a second call is a no-op and the undo record stays
  small. Test fixed, behaviour kept.

## Unverified — first Rhino click-test must exercise these

The bridge's Grasshopper API calls cannot run outside Rhino. On first run in
Rhino 8, watch these specifically:

1. **UI-thread marshalling.** `Grasshopper.Instances.DocumentEditor.Invoke(
   System.Action(fn))` from the socket thread — that pythonnet delegate
   conversion and the synchronous `Invoke` returning before we read the result
   box. Fallback path `Rhino.RhinoApp.InvokeOnUiThread(System.Action, None)` with
   an `Event` wait is even less certain. This is the M1 risk; if it fails,
   nothing else matters.
2. **`scriptcontext.sticky` persistence** of the running server across solutions
   and across a script edit (toggle `enable` off/on to restart cleanly).
3. **`_find_proxy`** iterating `Grasshopper.Instances.ComponentServer.ObjectProxies`
   and `proxy.CreateInstance()` — proxy `.Obsolete` / `.Desc.Name` shape, and
   whether every proxy is safe to instantiate.
4. **Undo records.** `doc.UndoUtil.RecordAddObjectEvent` /
   `RecordGenericObjectEvent` / `RecordRemoveObjectEvent` signatures in Rhino 8,
   and whether `RecordRemoveObjectEvent` accepts a list (currently called
   per-object, so N undo entries for a multi-delete — batching into one record
   is a known future refinement).
5. **Slider set.** `GH_NumberSlider.SetSliderValue(System.Decimal(float))` — the
   `Decimal` construction from a Python float via pythonnet; fallback is
   `System.Decimal.Parse(str)`.
6. **`GH_Panel`.** `SetUserText` vs the `UserText` property, and the
   `p.Properties.Multiline / Wrap / DrawIndices / DrawPaths` names.
7. **`GH_Scribble`.** Constructor (`GH_Scribble(PointF)` vs parameterless) and
   whether setting `.Text` + `.FontSize` + `Attributes.Pivot` is enough to make
   it render. Group titles are the reliable heading mechanism if scribbles prove
   fragile.
8. **Canvas capture.** `GH_Canvas.GenerateHiResImage()` may not exist in this
   build; fallback is `canvas.DrawToBitmap`, which can return blank for
   custom-painted controls. `_zoom_fit` sets `Viewport.Target` / `.Zoom`
   directly — property names unverified.
9. **`get_value`.** `param.VolatileData` iteration via `.PathCount` / `.Path(i)`
   / `.Branch(path)` — method vs indexer form in the Rhino 8 `IGH_Structure`.
