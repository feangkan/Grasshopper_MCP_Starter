# Example — "slider → circle", annotated

A walkthrough of what Claude does from a single sentence. Nothing to run here;
this is the shape of a session.

---

**You:** Add a slider and a circle, wire the slider to the circle's radius, set
it to 12, then tidy and label it so my studio group can use it.

**Claude:**

1. `gh_get_canvas` — sees an empty document.
2. `gh_add_component("number slider", 200, 200, nickname="Radius (m)")`
   → `guid: 5f2a…`, `matched_from: "Number Slider"`
3. `gh_add_component("circle", 460, 200)` → `guid: a91c…`
   (Circle's inputs: `Plane`, `Radius`.)
4. `gh_connect("5f2a…", "a91c…", target_param="Radius")`
   → wired `Number → Radius`
5. `gh_set_value("5f2a…", 12)`
6. `gh_solve()` → `duration_ms: 4.1, errors: 0`
7. `gh_get_errors()` → none
8. `gh_capture_viewport()` → *(image: a circle on the XY plane)*
9. `gh_annotate(["5f2a…"], "INPUTS - Circle Size",
   "Drag the green slider to set the circle radius in metres. 1–50.", stage=1)`
   → green group titled `1 - INPUTS - Circle Size`, note panel above it
10. `gh_annotate(["a91c…"], "GEOMETRY - Circle",
    "The circle itself. Rebuilds from the slider. Bake this.", stage=2,
    colour="#d8e6f3")`
11. `gh_add_panel(40, 40, "Parametric circle. Touch only the green slider. "
    "Output: one circle on the world XY plane.", nickname="README")`
12. `gh_auto_layout()` → `moved: 2` (INPUTS column, then GEOMETRY column)
13. `gh_capture_canvas()` → *(image: two tidy labelled groups, left to right)*

**Claude:** Done — one circle driven by `Radius (m) = 12`, no errors. Two labelled
stages, README top-left. Next you could:
- add a **Move** stage to lift the circle by a second slider,
- swap the circle for a **Polygon** with a side-count slider,
- add a **Custom Preview** so it bakes with a colour.
