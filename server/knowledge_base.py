"""Friendly component name -> canonical Grasshopper name.

The bridge does the *authoritative* match against the real component catalogue in
the running Grasshopper (it has the actual proxy list). This module only expands
the shorthand a person or Claude would naturally type ("slider", "py", "vec")
into the canonical name Grasshopper registers, so the bridge's own fuzzy match
has an easy target. An unknown name is passed through untouched.
"""
from __future__ import annotations

import difflib

# canonical name -> tuple of aliases / shorthands
_ALIASES: dict[str, tuple[str, ...]] = {
    # inputs
    "Number Slider": ("slider", "number slider", "num slider", "range slider", "value slider"),
    "Boolean Toggle": ("toggle", "bool", "boolean", "switch", "true/false"),
    "Panel": ("panel", "text panel", "note", "comment box"),
    "Value List": ("value list", "dropdown", "list", "enum"),
    "MD Slider": ("md slider", "2d slider", "xy slider"),
    "Button": ("button", "momentary", "trigger button"),
    "Graph Mapper": ("graph mapper", "graph", "remap curve"),
    # geometry primitives
    "Point": ("point", "pt", "construct point"),
    "Line": ("line", "ln"),
    "Line SDL": ("line sdl", "line by direction", "line dir"),
    "Circle": ("circle", "circ"),
    "Circle CNR": ("circle cnr", "circle center radius"),
    "Rectangle": ("rectangle", "rect", "rectangle 2pt"),
    "Box 2Pt": ("box", "box 2pt", "bounding box corner"),
    "Sphere": ("sphere", "ball"),
    "Plane": ("plane", "pl", "xy plane"),
    "XY Plane": ("xy plane", "world xy", "ground plane"),
    "Interpolate": ("interpolate", "interp curve", "nurbs through points", "curve through points"),
    "Polyline": ("polyline", "pline"),
    # transforms
    "Move": ("move", "translate", "offset object"),
    "Rotate": ("rotate", "rot"),
    "Scale": ("scale", "resize"),
    "Orient": ("orient", "orient object"),
    "Mirror": ("mirror", "reflect"),
    # data / maths
    "Series": ("series", "sequence", "count up"),
    "Range": ("range", "domain divide", "linspace"),
    "Construct Domain": ("construct domain", "domain", "interval"),
    "Number": ("number", "num param", "float param"),
    "Multiplication": ("multiply", "mult", "times", "product"),
    "Addition": ("add", "addition", "sum", "plus"),
    "Subtraction": ("subtract", "minus", "difference"),
    "Division": ("divide", "division", "over"),
    "Expression": ("expression", "expr", "formula", "eval"),
    "Bounds": ("bounds", "min max"),
    "Dispatch": ("dispatch", "split list by pattern"),
    "List Item": ("list item", "item", "index list"),
    "List Length": ("list length", "count", "length"),
    "Cull Pattern": ("cull", "cull pattern", "filter list"),
    "Flatten Tree": ("flatten", "flatten tree"),
    "Graft Tree": ("graft", "graft tree"),
    # vectors
    "Unit X": ("unit x", "x axis", "world x"),
    "Unit Y": ("unit y", "y axis", "world y"),
    "Unit Z": ("unit z", "z axis", "world z", "up"),
    "Vector XYZ": ("vector", "vec", "vector xyz", "construct vector"),
    "Amplitude": ("amplitude", "set vector length", "scale vector"),
    # surface / mesh
    "Extrude": ("extrude", "pull surface"),
    "Loft": ("loft", "skin"),
    "Surface From Points": ("surface from points", "srf grid"),
    "Divide Surface": ("divide surface", "isotrim grid", "srf grid points"),
    "Mesh Surface": ("mesh surface", "mesh from surface"),
    "Delaunay Mesh": ("delaunay", "delaunay mesh", "triangulate"),
    "Weaverbird's Picture Frame": ("picture frame", "wb frame"),
    # scripting
    "Python 3 Script": ("python", "python 3", "py", "ghpython", "script", "gh python"),
    "C# Script": ("c#", "csharp", "c sharp script"),
    # output / display
    "Custom Preview": ("custom preview", "preview with colour", "colour preview"),
    "Bake": ("bake", "bake object"),
    "Text Tag 3D": ("text tag", "label 3d", "annotation"),
    "Point List": ("point list", "index points", "show indices"),
}

# reverse index: alias -> canonical
_LOOKUP: dict[str, str] = {}
for _canon, _al in _ALIASES.items():
    _LOOKUP[_canon.lower()] = _canon
    for _a in _al:
        _LOOKUP[_a.lower()] = _canon

_ALL_KEYS = list(_LOOKUP.keys())


def resolve_component_name(name: str) -> str:
    """Return the canonical Grasshopper component name for a shorthand.

    Exact alias hit wins; otherwise a close fuzzy match (>= 0.72 ratio) against
    the alias table; otherwise the original string, trusting the bridge's
    catalogue match to sort it out.
    """
    key = name.strip().lower()
    if key in _LOOKUP:
        return _LOOKUP[key]
    close = difflib.get_close_matches(key, _ALL_KEYS, n=1, cutoff=0.72)
    if close:
        return _LOOKUP[close[0]]
    return name


def known_aliases() -> dict[str, tuple[str, ...]]:
    """The full alias table -- surfaced in docs and tests."""
    return dict(_ALIASES)
