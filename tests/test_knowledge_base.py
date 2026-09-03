"""resolve_component_name: shorthand -> canonical Grasshopper name."""
from __future__ import annotations

import pytest

from server.knowledge_base import known_aliases, resolve_component_name


@pytest.mark.parametrize(
    "shorthand, canonical",
    [
        ("slider", "Number Slider"),
        ("Number Slider", "Number Slider"),
        ("NUMBER SLIDER", "Number Slider"),
        ("py", "Python 3 Script"),
        ("python", "Python 3 Script"),
        ("ghpython", "Python 3 Script"),
        ("toggle", "Boolean Toggle"),
        ("circle", "Circle"),
        ("move", "Move"),
        ("vec", "Vector XYZ"),
        ("series", "Series"),
        ("panel", "Panel"),
        ("up", "Unit Z"),
    ],
)
def test_known_shorthands_resolve(shorthand, canonical):
    assert resolve_component_name(shorthand) == canonical


def test_typo_resolves_by_fuzzy_match():
    assert resolve_component_name("nunber slider") == "Number Slider"
    assert resolve_component_name("cirlce") == "Circle"


def test_unknown_name_passes_through_untouched():
    # trust the bridge's live catalogue match for anything not in the table
    assert resolve_component_name("Weaverbird Loop Subdivision") == "Weaverbird Loop Subdivision"
    assert resolve_component_name("Kangaroo2") == "Kangaroo2"


def test_whitespace_is_ignored():
    assert resolve_component_name("   slider  ") == "Number Slider"


def test_alias_table_is_self_consistent():
    for canonical, aliases in known_aliases().items():
        assert resolve_component_name(canonical) == canonical
        assert isinstance(aliases, tuple) and aliases
        assert len(aliases) == len(set(aliases))
