"""Protocol constants stay well-formed as commands are added per milestone."""
from __future__ import annotations

from server import protocol


def test_schema_is_versioned():
    assert protocol.SCHEMA.startswith("claude_gh_bridge/")


def test_every_command_is_unique_and_lowercase():
    cmds = protocol.COMMANDS
    assert len(cmds) == len(set(cmds))
    assert all(c == c.lower() and " " not in c for c in cmds)


def test_ping_is_always_present():
    assert "ping" in protocol.COMMANDS
