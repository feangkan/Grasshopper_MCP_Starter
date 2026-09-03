"""compute_layout: canvas snapshot -> tidy pivots, checked against known coords."""
from __future__ import annotations

from server.layout import compute_layout


def _obj(guid, x, y, kind="component"):
    return {"guid": guid, "kind": kind, "pivot": {"x": x, "y": y}}


def _canvas(objects, groups):
    return {"objects": objects, "groups": groups}


def test_groups_become_columns_in_stage_order():
    objs = [
        _obj("a", 500, 500), _obj("b", 10, 900),
        _obj("c", 999, 40),
    ]
    groups = [
        {"name": "2 - GEOMETRY", "member_guids": ["c"]},
        {"name": "1 - INPUTS", "member_guids": ["a", "b"]},
    ]
    moves = {m["guid"]: (m["x"], m["y"]) for m in compute_layout(_canvas(objs, groups))}

    # stage 1 column at origin_x=80, stage 2 column one col_gap (260) over
    assert moves["a"][0] == 80 and moves["b"][0] == 80
    assert moves["c"][0] == 340
    # within stage 1, 'a' (y=500) sits above 'b' (y=900): rows 0 and 1
    assert moves["a"][1] == 80
    assert moves["b"][1] == 170


def test_members_stack_in_current_visual_order():
    objs = [_obj("hi", 0, 300), _obj("lo", 0, 10), _obj("mid", 0, 150)]
    groups = [{"name": "1 - S", "member_guids": ["hi", "lo", "mid"]}]
    moves = {m["guid"]: m["y"] for m in compute_layout(_canvas(objs, groups))}
    assert moves["lo"] == 80
    assert moves["mid"] == 170
    assert moves["hi"] == 260


def test_ungrouped_objects_go_in_a_trailing_column():
    objs = [_obj("g", 0, 0), _obj("loose", 700, 700)]
    groups = [{"name": "1 - A", "member_guids": ["g"]}]
    moves = {m["guid"]: (m["x"], m["y"]) for m in compute_layout(_canvas(objs, groups))}
    assert moves["g"] == (80, 80)
    assert moves["loose"] == (340, 80)


def test_already_tidy_canvas_is_a_noop():
    objs = [_obj("a", 80, 80), _obj("b", 80, 170)]
    groups = [{"name": "1 - S", "member_guids": ["a", "b"]}]
    assert compute_layout(_canvas(objs, groups)) == []


def test_custom_spacing_is_honoured():
    objs = [_obj("a", 5, 5), _obj("b", 0, 500)]
    groups = [{"name": "1 - S", "member_guids": ["a", "b"]}]
    moves = {m["guid"]: (m["x"], m["y"])
             for m in compute_layout(_canvas(objs, groups),
                                     origin_x=0, origin_y=0, col_gap=100, row_gap=50)}
    assert moves["a"] == (0, 0)     # row 0 at the custom origin
    assert moves["b"] == (0, 50)    # row 1 one custom row_gap down


def test_groups_without_stage_number_keep_declaration_order():
    objs = [_obj("x", 0, 0), _obj("y", 0, 0)]
    groups = [
        {"name": "Alpha", "member_guids": ["x"]},
        {"name": "Beta", "member_guids": ["y"]},
    ]
    moves = {m["guid"]: m["x"] for m in compute_layout(_canvas(objs, groups))}
    assert moves["x"] == 80
    assert moves["y"] == 340


def test_empty_canvas_is_safe():
    assert compute_layout(_canvas([], [])) == []
