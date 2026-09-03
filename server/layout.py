"""Pure geometry for gh_auto_layout.

Given a canvas snapshot (the dict returned by the bridge's `get_canvas`), work
out a tidy new pivot for every object: groups become columns, left to right, in
stage order; each group's members stack vertically in their current visual
order; anything ungrouped goes in a trailing column.

No Grasshopper, no I/O -- so this is unit-tested against known coordinates.
"""
from __future__ import annotations

import re
from typing import Any

_STAGE_RE = re.compile(r"^\s*(\d+)")


def _stage_key(group: dict[str, Any], fallback: int) -> tuple[int, str]:
    """Sort groups by a leading number in the title ('1 - INPUTS'), else by title."""
    name = group.get("name") or group.get("nickname") or ""
    m = _STAGE_RE.match(name)
    return (int(m.group(1)) if m else 1000 + fallback, name.lower())


def compute_layout(
    canvas: dict[str, Any],
    *,
    origin_x: float = 80.0,
    origin_y: float = 80.0,
    col_gap: float = 260.0,
    row_gap: float = 90.0,
) -> list[dict[str, Any]]:
    """Return [{"guid": ..., "x": ..., "y": ...}, ...] for objects that should move.

    Objects already at their target pixel (within 0.5px) are omitted, so a second
    call is a no-op and the undo record stays small.
    """
    objects = {o["guid"]: o for o in canvas.get("objects", [])}
    groups = list(canvas.get("groups", []))

    # order groups by stage
    ordered = sorted(
        (g for g in groups if g.get("member_guids")),
        key=lambda g: _stage_key(g, groups.index(g)),
    )

    placed: set[str] = set()
    moves: list[dict[str, Any]] = []
    col = 0

    for group in ordered:
        members = [gid for gid in group["member_guids"] if gid in objects and gid not in placed]
        if not members:
            continue
        members.sort(key=lambda gid: _current_y(objects[gid]))
        x = origin_x + col * col_gap
        for row, gid in enumerate(members):
            _emit(moves, objects[gid], x, origin_y + row * row_gap)
            placed.add(gid)
        col += 1

    # trailing column: ungrouped objects, skipping groups/panels/scribbles which
    # follow their neighbours anyway
    loose = [
        o for gid, o in objects.items()
        if gid not in placed and o.get("kind") not in ("group", "scribble")
    ]
    loose.sort(key=_current_y)
    if loose:
        x = origin_x + col * col_gap
        for row, o in enumerate(loose):
            _emit(moves, o, x, origin_y + row * row_gap)

    return moves


def _current_y(obj: dict[str, Any]) -> float:
    piv = obj.get("pivot") or {}
    return float(piv.get("y", 0.0))


def _emit(moves: list, obj: dict, x: float, y: float) -> None:
    piv = obj.get("pivot") or {}
    if abs(float(piv.get("x", 1e9)) - x) < 0.5 and abs(float(piv.get("y", 1e9)) - y) < 0.5:
        return
    moves.append({"guid": obj["guid"], "x": x, "y": y})
