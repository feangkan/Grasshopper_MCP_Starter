"""Claude Bridge -- paste this whole file into a Grasshopper 'Python 3 Script' component.

    Inputs   enable : bool   (a Boolean Toggle)   -- True starts the listener
             port   : int    (optional)           -- default 9911
    Output   log    : str                          -- shows the bridge state

What it does
------------
When `enable` is True it runs a tiny JSON-over-TCP server on 127.0.0.1 that the
Claude MCP server connects to. Commands received on that socket are executed on
Rhino's UI thread against the Grasshopper document this component lives in, then
a one-line JSON reply is sent back.

Safety: listens on loopback only, no authentication -- it assumes anything able
to open a local socket on your machine is you. Toggle `enable` off when not in use.

To pick up edits to this file: toggle `enable` off, then on.
"""

import datetime
import json
import os
import socketserver
import tempfile
import threading
import traceback

import System
import Rhino
import Grasshopper

# Must match server/protocol.py SCHEMA.
SCHEMA = "claude_gh_bridge/1"
DEFAULT_PORT = 9911
STICKY_KEY = "claude_gh_bridge_server"
UI_TIMEOUT = 25.0

try:
    import scriptcontext as sc
except Exception:  # pragma: no cover - only inside Rhino
    sc = None


# =========================================================================
# Document helpers
# =========================================================================
def active_doc():
    """The GH_Document this component lives in (falls back to the active canvas)."""
    try:
        d = ghenv.Component.OnPingDocument()  # noqa: F821 - injected by GH
        if d is not None:
            return d
    except Exception:
        pass
    try:
        return Grasshopper.Instances.ActiveCanvas.Document
    except Exception:
        return None


def _safe_doc_name():
    d = active_doc()
    try:
        return d.DisplayName if d else "<none>"
    except Exception:
        return "<none>"


# =========================================================================
# UI-thread marshalling -- every handler runs through here
# =========================================================================
def run_on_ui_thread(func):
    box = {}

    def wrapped():
        try:
            box["result"] = func()
        except Exception as exc:  # captured, re-raised on the socket thread
            box["error"] = str(exc)
            box["trace"] = traceback.format_exc()

    editor = None
    try:
        editor = Grasshopper.Instances.DocumentEditor
    except Exception:
        editor = None

    if editor is not None and editor.InvokeRequired:
        editor.Invoke(System.Action(wrapped))
    elif editor is not None:
        wrapped()
    else:
        done = threading.Event()

        def wrapped_ev():
            wrapped()
            done.set()

        Rhino.RhinoApp.InvokeOnUiThread(System.Action(wrapped_ev), None)
        if not done.wait(UI_TIMEOUT):
            raise RuntimeError(
                "Rhino UI thread did not respond in %ss (a modal dialog may be open)" % UI_TIMEOUT
            )

    if "error" in box:
        err = RuntimeError(box["error"])
        err._trace = box.get("trace")
        raise err
    return box.get("result")


# =========================================================================
# Command handlers  (all run on the UI thread)
# =========================================================================
def _gh_version():
    try:
        import clr
        asm = System.Reflection.Assembly.GetAssembly(
            clr.GetClrType(Grasshopper.Kernel.GH_Document)
        )
        return str(asm.GetName().Version)
    except Exception:
        return "unknown"


def h_ping(args):
    doc = active_doc()
    return {
        "bridge_schema": SCHEMA,
        "rhino": str(Rhino.RhinoApp.Version),
        "rhino_build": int(Rhino.RhinoApp.ExeVersion),
        "grasshopper": _gh_version(),
        "doc_name": doc.DisplayName if doc else None,
        "doc_path": (doc.FilePath if doc else None) or None,
        "object_count": doc.ObjectCount if doc else 0,
    }


HANDLERS = {
    "ping": h_ping,
}


# =========================================================================
# Socket server
# =========================================================================
class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _Handler(socketserver.StreamRequestHandler):
    timeout = 120

    def handle(self):
        try:
            raw = self.rfile.readline()
        except Exception:
            return
        if not raw:
            return
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            self._send({"id": None, "ok": False, "error": "bad JSON: %s" % exc})
            return
        self._send(_dispatch(req))

    def _send(self, obj):
        try:
            self.wfile.write((json.dumps(obj, default=str) + "\n").encode("utf-8"))
        except Exception:
            pass


def _dispatch(req):
    rid = req.get("id")
    fn = HANDLERS.get(req.get("cmd"))
    if fn is None:
        return {"id": rid, "ok": False, "error": "unknown command: %r" % req.get("cmd")}
    args = req.get("args") or {}
    try:
        return {"id": rid, "ok": True, "result": run_on_ui_thread(lambda: fn(args))}
    except Exception as exc:
        return {"id": rid, "ok": False, "error": str(exc),
                "trace": getattr(exc, "_trace", None) or traceback.format_exc()}


# =========================================================================
# Lockfile
# =========================================================================
def lockfile_path():
    return os.path.join(tempfile.gettempdir(), "claude_gh_bridge.json")


def write_lockfile(port):
    data = {
        "schema": SCHEMA,
        "port": port,
        "pid": os.getpid(),
        "rhino": str(Rhino.RhinoApp.ExeVersion),
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    try:
        with open(lockfile_path(), "w") as fh:
            json.dump(data, fh)
    except OSError:
        pass


def remove_lockfile():
    try:
        os.remove(lockfile_path())
    except OSError:
        pass


# =========================================================================
# Lifecycle
# =========================================================================
def ensure_server(port):
    rec = sc.sticky.get(STICKY_KEY) if sc else None
    if rec and rec.get("alive") and rec.get("port") == port:
        return rec
    if rec:
        _shutdown(rec)
    srv = _Server(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=srv.serve_forever, name="claude-gh-bridge", daemon=True)
    thread.start()
    rec = {"srv": srv, "thread": thread, "port": port, "alive": True}
    if sc:
        sc.sticky[STICKY_KEY] = rec
    write_lockfile(port)
    return rec


def stop_server():
    rec = sc.sticky.pop(STICKY_KEY, None) if sc else None
    if rec:
        _shutdown(rec)
    remove_lockfile()


def _shutdown(rec):
    try:
        rec["alive"] = False
        rec["srv"].shutdown()
        rec["srv"].server_close()
    except Exception:
        pass


# =========================================================================
# Component entry point -- runs on every solution
# =========================================================================
try:
    _enable = bool(enable)  # noqa: F821 - component input
except NameError:
    _enable = False

try:
    _port = int(port) if port else DEFAULT_PORT  # noqa: F821 - component input
except (NameError, TypeError, ValueError):
    _port = DEFAULT_PORT

if _enable:
    _rec = ensure_server(_port)
    log = "Claude bridge LISTENING on 127.0.0.1:%d   doc: %s" % (_rec["port"], _safe_doc_name())
else:
    stop_server()
    log = "Claude bridge OFF   (set enable = True to start)"

a = log  # default output name in the Rhino 8 script editor
