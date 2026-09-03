# House style — definitions a stranger can use

The goal: someone who did not build the definition can open it, know where to
poke, and change it safely without asking you. Five layers, applied together.

## 1. Colour-coded groups

| Colour | Hex | Meaning |
|---|---|---|
| Green | `#d7ecd9` | **Inputs you edit** — sliders, toggles, points to pick |
| Blue | `#d8e6f3` | Geometry construction |
| Orange | `#f6e0c8` | Outputs — what to bake / bring to Rhino |
| Grey | `#e6e6e6` | Internal machinery — leave alone |

A newcomer scans for green first. Nothing outside a group.

## 2. Numbered stage titles

`1 - INPUTS - Tower Dimensions`, `2 - GEOMETRY - Floor Plates`,
`3 - OUTPUT - Bake`. The number sets reading order and drives `gh_auto_layout`.

## 3. One note panel per group

Anchored just above the group. Plain language, three things:
- what this stage produces,
- which inputs to touch,
- sensible ranges / units.

> *"Sets the overall tower envelope. Drag the two green sliders. Height 20–80 m,
> floor count 5–40. Everything downstream rebuilds from these."*

## 4. Readable nicknames

Every input renamed: `Tower Height (m)`, not `Number Slider`. Every group's
output param renamed to what it carries. Hovering anything should make sense.

## 5. A README panel, top-left

Before stage 1. What the whole definition does, which groups to touch, what comes
out, any gotchas.

## Layout

`gh_auto_layout` after the groups exist: stages left-to-right, components stacked
in each column, consistent gaps. Reads as a flow, not a web.

---

## How Claude applies this

`gh_annotate(guids, title, note, stage=N)` does layers 1–3 for one group in a
single call. Then `gh_set_nickname` per input for layer 4, one `gh_add_panel`
top-left for layer 5, and `gh_auto_layout` last.

## Opting down

Tell Claude if you want it lighter:
- **"scribbles not panels"** — headings only, no long text (less clutter, less
  guidance).
- **"colours and titles only"** — skip the note panels.
- **"no layout"** — annotate in place, don't move anything.
