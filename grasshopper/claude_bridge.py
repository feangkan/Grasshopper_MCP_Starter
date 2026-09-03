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

Objects are addressed by InstanceGuid, so your manual dragging never invalidates
Claude's references.

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
# Document / object helpers
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


def is_component(obj):
    return hasattr(obj, "Params") and getattr(obj, "Params", None) is not None


def is_param(obj):
    return hasattr(obj, "AddSource")


def find(doc, guid):
    if doc is None or guid is None:
        return None
    try:
        g = System.Guid.Parse(str(guid))
    except Exception:
        return None
    obj = doc.FindObject(g, True)
    if obj is None:
        obj = doc.FindObject(g, False)
    return obj


def top_object(param):
    try:
        return param.Attributes.GetTopLevel.DocObject
    except Exception:
        return param


def _match_param(params, sel):
    plist = list(params)
    if not plist:
        raise RuntimeError("object has no parameters on that side")
    if sel is None:
        return plist[0]
    try:
        i = int(sel)
        if 0 <= i < len(plist):
            return plist[i]
    except (ValueError, TypeError):
        pass
    s = str(sel).strip().lower()
    for p in plist:
        if p.Name.lower() == s or p.NickName.lower() == s:
            return p
    for p in plist:
        if s in p.Name.lower():
            return p
    raise RuntimeError(
        "no parameter matching %r; available: %s" % (sel, [p.Name for p in plist])
    )


def pick_output_param(obj, sel):
    if is_component(obj):
        return _match_param(obj.Params.Output, sel)
    if is_param(obj):
        return obj
    raise RuntimeError("%s exposes no output" % getattr(obj, "Name", obj))


def rgb(color):
    try:
        return "#%02x%02x%02x" % (color.R, color.G, color.B)
    except Exception:
        return None


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


def _param_dict(p, role):
    return {
        "name": p.Name,
        "nickname": p.NickName,
        "role": role,
        "type": p.TypeName,
        "guid": str(p.InstanceGuid),
        "data_count": int(p.VolatileDataCount),
        "sources": [str(s.InstanceGuid) for s in p.Sources],
    }


def _object_extra(obj):
    tn = type(obj).__name__
    try:
        if tn == "GH_NumberSlider":
            return {"value": float(obj.CurrentValue),
                    "min": float(obj.Slider.Minimum),
                    "max": float(obj.Slider.Maximum)}
        if tn == "GH_BooleanToggle":
            return {"value": bool(obj.Value)}
        if tn == "GH_Panel":
            return {"value": obj.UserText}
    except Exception:
        pass
    return {}


def h_get_canvas(args):
    doc = active_doc()
    if doc is None:
        raise RuntimeError("no active Grasshopper document")
    limit = int(args.get("limit", 800))
    objects, groups, wires = [], [], []

    for obj in list(doc.Objects):
        tn = type(obj).__name__
        if tn == "GH_Group":
            groups.append({
                "guid": str(obj.InstanceGuid),
                "name": obj.NickName,
                "colour": rgb(obj.Colour),
                "member_guids": [str(g) for g in obj.ObjectIDs],
            })
            continue
        rec = {
            "guid": str(obj.InstanceGuid),
            "name": obj.Name,
            "nickname": obj.NickName,
            "kind": "component" if is_component(obj) else ("param" if is_param(obj) else tn),
            "type_name": tn,
        }
        try:
            piv = obj.Attributes.Pivot
            rec["pivot"] = {"x": float(piv.X), "y": float(piv.Y)}
        except Exception:
            rec["pivot"] = None
        rec.update(_object_extra(obj))
        if is_component(obj):
            rec["inputs"] = [_param_dict(p, "input") for p in obj.Params.Input]
            rec["outputs"] = [_param_dict(p, "output") for p in obj.Params.Output]
        objects.append(rec)
        if len(objects) >= limit:
            break

    for obj in list(doc.Objects):
        targets = obj.Params.Input if is_component(obj) else ([obj] if is_param(obj) else [])
        for tp in targets:
            for src in tp.Sources:
                wires.append({
                    "from_obj": str(top_object(src).InstanceGuid),
                    "from_param": src.Name,
                    "to_obj": str(obj.InstanceGuid),
                    "to_param": tp.Name,
                })

    return {
        "doc_name": doc.DisplayName,
        "object_count": doc.ObjectCount,
        "truncated": doc.ObjectCount > len(objects),
        "objects": objects,
        "groups": groups,
        "wires": wires,
    }


def _messages(doc, level):
    from Grasshopper.Kernel import GH_RuntimeMessageLevel  # noqa

    out = []
    lv = {"error": GH_RuntimeMessageLevel.Error,
          "warning": GH_RuntimeMessageLevel.Warning}[level]
    for obj in list(doc.Objects):
        fn = getattr(obj, "RuntimeMessages", None)
        if fn is None:
            continue
        try:
            for text in fn(lv):
                out.append({
                    "guid": str(obj.InstanceGuid),
                    "nickname": obj.NickName,
                    "name": obj.Name,
                    "level": level,
                    "text": text,
                })
        except Exception:
            pass
    return out


def h_get_errors(args):
    doc = active_doc()
    errors = _messages(doc, "error")
    warnings = _messages(doc, "warning")
    return {"error_count": len(errors), "warning_count": len(warnings),
            "messages": errors + warnings}


def h_get_value(args):
    doc = active_doc()
    obj = find(doc, args.get("guid"))
    if obj is None:
        raise RuntimeError("no object with guid %r" % args.get("guid"))
    param = pick_output_param(obj, args.get("param"))
    data = param.VolatileData
    cap = int(args.get("limit", 200))
    values, total = [], 0
    try:
        for i in range(data.PathCount):
            branch = data.Branch(data.Path(i))
            for goo in branch:
                total += 1
                if len(values) < cap:
                    values.append(str(goo))
    except Exception:
        pass
    return {"type": param.TypeName, "count": total, "truncated": total > len(values),
            "values": values}


def h_solve(args):
    doc = active_doc()
    t0 = datetime.datetime.now()
    doc.NewSolution(bool(args.get("force", False)))
    dt = (datetime.datetime.now() - t0).total_seconds() * 1000.0
    return {
        "ran": True,
        "duration_ms": round(dt, 1),
        "errors": len(_messages(doc, "error")),
        "warnings": len(_messages(doc, "warning")),
    }


# ---- vision -------------------------------------------------------------
def _png_b64(bmp):
    ms = System.IO.MemoryStream()
    bmp.Save(ms, System.Drawing.Imaging.ImageFormat.Png)
    return System.Convert.ToBase64String(ms.ToArray())


def _zoom_fit(canvas, doc):
    try:
        box = doc.BoundingBox(False)
        if box.Width <= 0 or box.Height <= 0:
            return
        pad = 40.0
        vp = canvas.Viewport
        vp.Target = System.Drawing.PointF(box.X + box.Width / 2.0, box.Y + box.Height / 2.0)
        zx = canvas.Width / (box.Width + pad * 2)
        zy = canvas.Height / (box.Height + pad * 2)
        vp.Zoom = max(0.1, min(1.0, min(zx, zy)))
        canvas.Refresh()
    except Exception:
        pass


def h_capture_canvas(args):
    canvas = Grasshopper.Instances.ActiveCanvas
    if canvas is None:
        raise RuntimeError("no active Grasshopper canvas (is the GH window open?)")
    if args.get("zoom_fit", True):
        _zoom_fit(canvas, active_doc())

    bmp, method = None, "GenerateHiResImage"
    gen = getattr(canvas, "GenerateHiResImage", None)
    if callable(gen):
        try:
            bmp = gen()
        except Exception:
            bmp = None
    if bmp is None:
        method = "DrawToBitmap"
        w, h = max(int(canvas.Width), 8), max(int(canvas.Height), 8)
        bmp = System.Drawing.Bitmap(w, h)
        canvas.DrawToBitmap(bmp, System.Drawing.Rectangle(0, 0, w, h))
    return {"png_base64": _png_b64(bmp), "width": int(bmp.Width),
            "height": int(bmp.Height), "method": method}


def h_capture_viewport(args):
    rdoc = Rhino.RhinoDoc.ActiveDoc
    view = rdoc.Views.ActiveView if rdoc else None
    if view is None:
        raise RuntimeError("no active Rhino viewport")
    size = System.Drawing.Size(int(args.get("width", 1280)), int(args.get("height", 720)))
    bmp = view.CaptureToBitmap(size)
    return {"png_base64": _png_b64(bmp), "width": int(bmp.Width), "height": int(bmp.Height)}


HANDLERS = {
    "ping": h_ping,
    "get_canvas": h_get_canvas,
    "get_errors": h_get_errors,
    "get_value": h_get_value,
    "solve": h_solve,
    "capture_canvas": h_capture_canvas,
    "capture_viewport": h_capture_viewport,
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
