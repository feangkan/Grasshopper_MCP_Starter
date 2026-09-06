"""gh_set_script argument handling. The Grasshopper side needs Rhino; what is
provable offline is that the tool reads the file and refuses ambiguous input."""
from __future__ import annotations

import pytest

from server import gh_mcp_server as srv


class _FakeBridge:
    def __init__(self):
        self.calls = []

    def call(self, cmd, args):
        self.calls.append((cmd, args))
        return {"guid": args["guid"], "attr": "Code", "chars": len(args["code"])}


@pytest.fixture
def bridge(monkeypatch):
    fake = _FakeBridge()
    monkeypatch.setattr(srv, "_bridge", lambda: fake)
    return fake


def test_reads_the_file_and_sends_its_text(bridge, tmp_path):
    script = tmp_path / "cluster_field.py"
    script.write_text("a = 1\nb = 2\n", encoding="utf-8")

    out = srv.gh_set_script(guid="g-1", file_path=str(script))

    cmd, args = bridge.calls[0]
    assert cmd == "set_script"
    assert args == {"guid": "g-1", "code": "a = 1\nb = 2\n"}
    assert out["chars"] == 12


def test_literal_code_is_forwarded_unchanged(bridge):
    srv.gh_set_script(guid="g-2", code="x = 42")
    assert bridge.calls[0][1]["code"] == "x = 42"


def test_rejects_both_file_and_code(bridge, tmp_path):
    script = tmp_path / "s.py"
    script.write_text("x = 1", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        srv.gh_set_script(guid="g", file_path=str(script), code="x = 1")
    assert bridge.calls == []


def test_rejects_neither_file_nor_code(bridge):
    with pytest.raises(ValueError, match="exactly one"):
        srv.gh_set_script(guid="g")
    assert bridge.calls == []
