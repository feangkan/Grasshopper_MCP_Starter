"""M3 vision tools decode the bridge's base64 PNG into an MCP Image."""
from __future__ import annotations

import base64
import struct
import zlib

from server.gh_mcp_server import gh_capture_canvas, gh_capture_viewport


def _tiny_png() -> bytes:
    # 1x1 opaque black PNG, built by hand so the test has no image deps
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_chunk = _chunk(b"IHDR", ihdr)
    raw = b"\x00\x00\x00\x00"
    idat_chunk = _chunk(b"IDAT", zlib.compress(raw))
    iend_chunk = _chunk(b"IEND", b"")
    return sig + ihdr_chunk + idat_chunk + iend_chunk


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


PNG_B64 = base64.b64encode(_tiny_png()).decode()


def test_capture_canvas_returns_png_image(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"png_base64": PNG_B64, "width": 1, "height": 1}}
    img = gh_capture_canvas()
    content = img.to_image_content()
    assert "png" in getattr(content, "mime_type", getattr(content, "mimeType", ""))
    assert base64.b64decode(content.data)[:8] == b"\x89PNG\r\n\x1a\n"
    assert fake_bridge.requests[-1]["cmd"] == "capture_canvas"
    assert fake_bridge.requests[-1]["args"] == {"zoom_fit": True}


def test_capture_canvas_passes_zoom_fit_false(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"png_base64": PNG_B64}}
    gh_capture_canvas(zoom_fit=False)
    assert fake_bridge.requests[-1]["args"] == {"zoom_fit": False}


def test_capture_viewport_passes_size(fake_bridge):
    fake_bridge.responder = {"ok": True, "result": {"png_base64": PNG_B64}}
    gh_capture_viewport(width=800, height=600)
    sent = fake_bridge.requests[-1]
    assert sent["cmd"] == "capture_viewport"
    assert sent["args"] == {"width": 800, "height": 600}
