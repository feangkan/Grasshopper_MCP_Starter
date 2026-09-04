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

Every command that changes the canvas is wrapped in a named Grasshopper undo
record, so anything Claude does can be undone with Ctrl+Z and is labelled
"Claude: ..." in the Edit menu. Objects are addressed by InstanceGuid, so your
manual dragging never invalidates Claude's references.

Safety: listens on loopback only, no authentication -- it assumes anything able
to open a local socket on your machine is you. Toggle `enable` off when not in use.

To pick up edits to this file: toggle `enable` off, then on.
"""

import datetime
import json
import os
import socket
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


def type_name(obj):
    """Concrete .NET class name. `type(obj).__name__` under pythonnet often
    yields the interface ('IGH_DocumentObject'), so ask the CLR directly."""
    try:
        return obj.GetType().Name
    except Exception:
        return type(obj).__name__


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


def pick_input_param(obj, sel):
    if is_component(obj):
        return _match_param(obj.Params.Input, sel)
    if is_param(obj):
        return obj
    raise RuntimeError("%s exposes no input" % getattr(obj, "Name", obj))


def hex_to_color(text):
    t = str(text).lstrip("#")
    r, g, b = int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
    return System.Drawing.Color.FromArgb(255, r, g, b)


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


def _num(x):
    """.NET Decimal / Single -> float, robustly (pythonnet Decimal->float is flaky)."""
    return float(str(x))


def _object_extra(obj):
    tn = type_name(obj)
    if tn == "GH_NumberSlider":
        out = {}
        for key, getter in (("value", lambda: obj.CurrentValue),
                            ("min", lambda: obj.Slider.Minimum),
                            ("max", lambda: obj.Slider.Maximum)):
            try:
                out[key] = _num(getter())
            except Exception as exc:
                out[key + "_err"] = str(exc)
        try:
            out["accuracy"] = str(obj.Slider.Type)
            out["decimals"] = int(obj.Slider.DecimalPlaces)
        except Exception:
            pass
        return out
    if tn == "GH_BooleanToggle":
        try:
            return {"value": bool(obj.Value)}
        except Exception as exc:
            return {"value_err": str(exc)}
    if tn == "GH_Panel":
        try:
            return {"value": obj.UserText}
        except Exception as exc:
            return {"value_err": str(exc)}
    return {}


def h_get_canvas(args):
    doc = active_doc()
    if doc is None:
        raise RuntimeError("no active Grasshopper document")
    limit = int(args.get("limit", 800))
    objects, groups, wires = [], [], []

    for obj in list(doc.Objects):
        tn = type_name(obj)
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
    cap = int(args.get("limit", 200))
    total = int(param.VolatileDataCount)
    values, read_error = [], None
    try:
        for goo in param.VolatileData.AllData(True):
            if len(values) >= cap:
                break
            values.append(str(goo))
    except Exception as exc:
        read_error = str(exc)
    out = {"type": param.TypeName, "count": total,
           "truncated": total > len(values), "values": values}
    if read_error:
        out["read_error"] = read_error
    return out


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
    return {"png_base64": _png_b64(bmp), "width": int(bmp.Width), "height": int(bmp.Height),
            "method": "CaptureToBitmap"}


# ---- edit -------------------------------------------------------------
def _find_proxy(name):
    key = str(name).strip().lower()
    server = Grasshopper.Instances.ComponentServer
    proxies = [p for p in server.ObjectProxies if not p.Obsolete]
    for p in proxies:
        if p.Desc.Name.lower() == key:
            return p
    contains = sorted(
        (p for p in proxies if key in p.Desc.Name.lower()),
        key=lambda p: len(p.Desc.Name),
    )
    if contains:
        return contains[0]
    import difflib
    names = {p.Desc.Name.lower(): p for p in proxies}
    m = difflib.get_close_matches(key, list(names), n=1, cutoff=0.7)
    return names[m[0]] if m else None


def h_add_component(args):
    doc = active_doc()
    proxy = _find_proxy(args["name"]) or _find_proxy(args.get("requested", args["name"]))
    if proxy is None:
        raise RuntimeError(
            "no component matches %r; use the exact name from the GH ribbon" %
            args.get("requested", args["name"])
        )
    obj = proxy.CreateInstance()
    obj.CreateAttributes()
    obj.Attributes.Pivot = System.Drawing.PointF(float(args["x"]), float(args["y"]))
    obj.Attributes.ExpireLayout()
    doc.UndoUtil.RecordAddObjectEvent("Claude: add " + obj.Name, obj)
    doc.AddObject(obj, False)
    if args.get("nickname"):
        obj.NickName = args["nickname"]
    doc.NewSolution(False)
    return {"guid": str(obj.InstanceGuid), "name": obj.Name,
            "nickname": obj.NickName, "matched_from": proxy.Desc.Name}


# ---- typed inputs: pick the right widget + settings for the job ----------
# role -> (widget kind, {accuracy, min, max, decimals})
_INPUT_ROLES = {
    "count":     ("slider", "Integer", 0.0,  50.0,   0),
    "integer":   ("slider", "Integer", 0.0,  100.0,  0),
    "n":         ("slider", "Integer", 0.0,  50.0,   0),
    "divisions": ("slider", "Integer", 1.0,  50.0,   0),
    "even":      ("slider", "Even",    0.0,  100.0,  0),
    "odd":       ("slider", "Odd",     1.0,  99.0,   0),
    "fraction":  ("slider", "Float",   0.0,  1.0,    3),
    "factor":    ("slider", "Float",   0.0,  1.0,    3),
    "ratio":     ("slider", "Float",   0.0,  1.0,    3),
    "percent":   ("slider", "Float",   0.0,  100.0,  0),
    "angle":     ("slider", "Float",   0.0,  360.0,  1),
    "length":    ("slider", "Float",   0.0,  1000.0, 1),
    "distance":  ("slider", "Float",   0.0,  1000.0, 1),
    "number":    ("slider", "Float",   0.0,  100.0,  2),
    "seed":      ("seed",   "Integer", 0.0,  9999.0, 0),
    "toggle":    ("toggle", None, None, None, None),
    "boolean":   ("toggle", None, None, None, None),
    "switch":    ("toggle", None, None, None, None),
    "graph":        ("graph", None, None, None, None),
    "profile":      ("graph", None, None, None, None),
    "falloff":      ("graph", None, None, None, None),
    "distribution": ("graph", None, None, None, None),
    "curve_control":("graph", None, None, None, None),
}


def h_add_input(args):
    doc = active_doc()
    role = str(args.get("role", "number")).strip().lower()
    spec = _INPUT_ROLES.get(role, ("slider", "Float", 0.0, 100.0, 2))
    kind, acc, d_lo, d_hi, d_dp = spec
    x, y = float(args["x"]), float(args["y"])
    nick = args.get("nickname")
    lo = args.get("min", d_lo)
    hi = args.get("max", d_hi)
    val = args.get("value")

    if kind == "toggle":
        return _place_toggle(doc, x, y, nick, bool(val) if val is not None else False)
    if kind == "graph":
        return _place_graph(doc, x, y, nick, args.get("graph_type", "Bezier"))
    if kind == "seed":
        return _place_seed(doc, x, y, nick, int(lo), int(hi),
                           int(val) if val is not None else None)
    return _place_slider(doc, x, y, nick, acc, lo, hi, d_dp, val, role)


def _place_slider(doc, x, y, nick, acc, lo, hi, dp, val, role):
    from Grasshopper.Kernel.Special import GH_NumberSlider
    s = GH_NumberSlider()
    s.CreateAttributes()
    s.Attributes.Pivot = System.Drawing.PointF(x, y)
    try:
        from Grasshopper.GUI.Base import GH_SliderAccuracy
        s.Slider.Type = getattr(GH_SliderAccuracy, acc or "Float")
    except Exception:
        pass
    try:
        if lo is not None:
            s.Slider.Minimum = System.Decimal(float(lo))
        if hi is not None:
            s.Slider.Maximum = System.Decimal(float(hi))
        s.Slider.DecimalPlaces = int(dp)
    except Exception:
        pass
    doc.UndoUtil.RecordAddObjectEvent("Claude: add %s slider" % role, s)
    doc.AddObject(s, False)
    if nick:
        s.NickName = nick
    if val is None and lo is not None and hi is not None:
        val = (float(lo) + float(hi)) / 2.0
        if acc and acc != "Float":
            val = round(val)
    if val is not None:
        try:
            s.SetSliderValue(System.Decimal(float(val)))
        except Exception:
            pass
    doc.NewSolution(False)
    return {"guid": str(s.InstanceGuid), "kind": "Number Slider", "role": role,
            "accuracy": acc, "min": lo, "max": hi, "decimals": int(dp),
            "nickname": s.NickName, "value": _num(s.CurrentValue)}


def _place_toggle(doc, x, y, nick, value):
    from Grasshopper.Kernel.Special import GH_BooleanToggle
    t = GH_BooleanToggle()
    t.CreateAttributes()
    t.Attributes.Pivot = System.Drawing.PointF(x, y)
    t.Value = bool(value)
    doc.UndoUtil.RecordAddObjectEvent("Claude: add toggle", t)
    doc.AddObject(t, False)
    if nick:
        t.NickName = nick
    t.ExpireSolution(True)
    doc.NewSolution(False)
    return {"guid": str(t.InstanceGuid), "kind": "Boolean Toggle",
            "nickname": t.NickName, "value": bool(t.Value)}


def _place_seed(doc, x, y, nick, lo, hi, val):
    proxy = _find_proxy("Digit Scroller")
    if proxy is not None:
        try:
            obj = proxy.CreateInstance()
            obj.CreateAttributes()
            obj.Attributes.Pivot = System.Drawing.PointF(x, y)
            for attr, v in (("MinimumValue", System.Decimal(lo)),
                            ("MaximumValue", System.Decimal(hi)),
                            ("DecimalPlaces", 0)):
                try:
                    setattr(obj, attr, v)
                except Exception:
                    pass
            doc.UndoUtil.RecordAddObjectEvent("Claude: add seed scroller", obj)
            doc.AddObject(obj, False)
            if nick:
                obj.NickName = nick
            if val is not None:
                try:
                    obj.Value = System.Decimal(int(val))
                except Exception:
                    pass
            doc.NewSolution(False)
            return {"guid": str(obj.InstanceGuid), "kind": "Digit Scroller",
                    "role": "seed", "min": lo, "max": hi, "nickname": obj.NickName}
        except Exception:
            pass
    out = _place_slider(doc, x, y, nick, "Integer", lo, hi, 0, val, "seed")
    out["kind"] = "Number Slider (integer)"
    out["note"] = "Digit Scroller unavailable in this build; used an integer slider"
    return out


_GRAPH_CLASSES = {
    "bezier": "GH_BezierGraph", "linear": "GH_LinearGraph",
    "sine": "GH_SinGraph", "sin": "GH_SinGraph",
    "parabola": "GH_ParabolaGraph", "power": "GH_PowerGraph",
    "perlin": "GH_PerlinGraph", "gaussian": "GH_GaussianGraph",
    "conic": "GH_ConicGraph", "square_root": "GH_SqrtGraph",
}


def _place_graph(doc, x, y, nick, graph_type):
    from Grasshopper.Kernel.Special import GH_GraphMapper
    g = GH_GraphMapper()
    g.CreateAttributes()
    g.Attributes.Pivot = System.Drawing.PointF(x, y)
    applied = None
    try:
        import Grasshopper.Kernel.Graphs as GR
        cls = _GRAPH_CLASSES.get(str(graph_type).strip().lower(), "GH_BezierGraph")
        graph = getattr(GR, cls)()
        try:
            g.Container.Graph = graph
        except Exception:
            g.Graph = graph
        applied = cls
    except Exception:
        applied = None
    doc.UndoUtil.RecordAddObjectEvent("Claude: add graph mapper", g)
    doc.AddObject(g, False)
    if nick:
        g.NickName = nick
    doc.NewSolution(False)
    out = {"guid": str(g.InstanceGuid), "kind": "Graph Mapper", "nickname": g.NickName}
    if applied:
        out["graph_type"] = applied
    else:
        out["note"] = ("placed, but graph type not set - right-click the mapper, "
                       "Graph Types > Bezier, then drag the curve")
    return out


def _set_decimal(slider, value):
    try:
        slider.SetSliderValue(System.Decimal(float(value)))
    except Exception:
        slider.SetSliderValue(System.Decimal.Parse(str(value)))


def _slider_is_integer(slider):
    try:
        return str(slider.Slider.Type) in ("Integer", "Even", "Odd")
    except Exception:
        return False


def h_set_value(args):
    doc = active_doc()
    obj = find(doc, args["guid"])
    if obj is None:
        raise RuntimeError("no object with guid %r" % args["guid"])
    value, tn = args["value"], type_name(obj)
    doc.UndoUtil.RecordGenericObjectEvent("Claude: set value on " + obj.NickName, obj)
    note = None
    if tn == "GH_NumberSlider":
        lo, hi = _num(obj.Slider.Minimum), _num(obj.Slider.Maximum)
        want = float(value)
        if _slider_is_integer(obj):
            want = float(round(want))          # honour the slider's own rounding
        if not lo <= want <= hi:
            note = "requested %s is outside the slider range %s..%s; widened it" % (want, lo, hi)
            if want < lo:
                obj.Slider.Minimum = System.Decimal(want)
            if want > hi:
                obj.Slider.Maximum = System.Decimal(want)
        _set_decimal(obj, want)
    elif tn == "GH_BooleanToggle":
        obj.Value = bool(value)
    elif tn == "GH_Panel":
        obj.SetUserText(str(value))
    elif tn == "GH_ValueList":
        _select_value_list(obj, value)
    else:
        raise RuntimeError("%s (%s) is not a settable input" % (obj.NickName, tn))
    obj.ExpireSolution(True)
    doc.NewSolution(False)
    out = {"guid": args["guid"], "value": value, "type": tn}
    if tn == "GH_NumberSlider":
        out["applied"] = _num(obj.CurrentValue)
    if note:
        out["note"] = note
    return out


def _select_value_list(vlist, value):
    want = str(value).strip().lower()
    for i, item in enumerate(vlist.ListItems):
        if item.Name.lower() == want or item.Expression.strip().lower() == want:
            vlist.SelectItem(i)
            return
    raise RuntimeError("value list has no item %r" % value)


def h_connect(args):
    doc = active_doc()
    src = find(doc, args["source"])
    tgt = find(doc, args["target"])
    if src is None or tgt is None:
        raise RuntimeError("source or target guid not found")
    sp = pick_output_param(src, args.get("source_param"))
    tp = pick_input_param(tgt, args.get("target_param"))
    doc.UndoUtil.RecordGenericObjectEvent("Claude: connect wire", tgt if is_component(tgt) else tp)
    tp.AddSource(sp)
    doc.NewSolution(False)
    return {"from_param": sp.Name, "to_param": tp.Name}


def h_disconnect(args):
    doc = active_doc()
    src = find(doc, args["source"])
    tgt = find(doc, args["target"])
    if src is None or tgt is None:
        raise RuntimeError("source or target guid not found")
    sp = pick_output_param(src, args.get("source_param"))
    tp = pick_input_param(tgt, args.get("target_param"))
    doc.UndoUtil.RecordGenericObjectEvent("Claude: remove wire", tgt if is_component(tgt) else tp)
    try:
        tp.RemoveSource(sp)
    except Exception:
        raise RuntimeError("those parameters were not connected")
    doc.NewSolution(False)
    return {"from_param": sp.Name, "to_param": tp.Name}


def h_delete(args):
    doc = active_doc()
    objs = [o for o in (find(doc, g) for g in args["guids"]) if o is not None]
    if not objs:
        raise RuntimeError("no matching objects to delete")
    for o in objs:
        doc.UndoUtil.RecordRemoveObjectEvent("Claude: delete " + o.NickName, o)
        doc.RemoveObject(o, False)
    doc.NewSolution(False)
    return {"deleted": [str(o.InstanceGuid) for o in objs]}


def h_set_pivot(args):
    doc = active_doc()
    obj = find(doc, args["guid"])
    if obj is None:
        raise RuntimeError("no object with guid %r" % args["guid"])
    doc.UndoUtil.RecordGenericObjectEvent("Claude: move " + obj.NickName, obj)
    obj.Attributes.Pivot = System.Drawing.PointF(float(args["x"]), float(args["y"]))
    obj.Attributes.ExpireLayout()
    _refresh()
    return {"guid": args["guid"], "x": args["x"], "y": args["y"]}


def _bridge_cluster(doc):
    """Guids of this bridge component and whatever is wired straight to it (its
    enable toggle, status panel). clear_canvas must never touch these."""
    try:
        me = ghenv.Component  # noqa: F821 - injected by GH
    except Exception:
        return set()
    ids = {str(me.InstanceGuid)}
    try:
        for p in list(me.Params.Input):
            for s in p.Sources:
                ids.add(str(top_object(s).InstanceGuid))
        for p in list(me.Params.Output):
            for r in p.Recipients:
                ids.add(str(top_object(r).InstanceGuid))
    except Exception:
        pass
    return ids


def h_clear_canvas(args):
    doc = active_doc()
    if doc is None:
        raise RuntimeError("no active Grasshopper document")
    keep_tokens = {str(k).strip().lower() for k in (args.get("keep") or []) if str(k).strip()}
    protected = _bridge_cluster(doc)

    groups = [o for o in list(doc.Objects) if type_name(o) == "GH_Group"]
    kept_group_ids = set()
    for g in groups:
        nn = (g.NickName or "").lower()
        gid = str(g.InstanceGuid).lower()
        if gid in keep_tokens or any(t in nn for t in keep_tokens if len(t) > 2):
            kept_group_ids.add(str(g.InstanceGuid))
            for member in g.ObjectIDs:
                keep_tokens.add(str(member).lower())

    def kept(o):
        gid = str(o.InstanceGuid)
        return gid in protected or gid.lower() in keep_tokens

    victims = [o for o in list(doc.Objects)
               if type_name(o) != "GH_Group" and not kept(o)]
    dead_groups = [g for g in groups if str(g.InstanceGuid) not in kept_group_ids]

    if args.get("dry_run"):
        return {"would_delete": [{"guid": str(o.InstanceGuid), "name": o.Name,
                                  "nickname": o.NickName} for o in victims],
                "would_remove_groups": len(dead_groups),
                "protected": sorted(protected)}

    label = "Claude: clear canvas (%d)" % (len(victims) + len(dead_groups))
    removed = 0
    for o in victims + dead_groups:
        try:
            doc.UndoUtil.RecordRemoveObjectEvent(label, o)
            doc.RemoveObject(o, False)
            removed += 1
        except Exception:
            pass
    doc.NewSolution(False)
    _refresh()
    return {"deleted": len(victims), "groups_removed": len(dead_groups),
            "removed_total": removed, "protected": sorted(protected)}


# ---- legibility ------------------------------------------------------
def h_set_nickname(args):
    doc = active_doc()
    obj = find(doc, args["guid"])
    if obj is None:
        raise RuntimeError("no object with guid %r" % args["guid"])
    doc.UndoUtil.RecordGenericObjectEvent("Claude: rename", obj)
    obj.NickName = args["nickname"]
    try:
        obj.Attributes.ExpireLayout()
    except Exception:
        pass
    obj.ExpireSolution(True)
    doc.NewSolution(False)
    return {"guid": args["guid"], "nickname": obj.NickName}


def h_create_group(args):
    from Grasshopper.Kernel.Special import GH_Group

    doc = active_doc()
    g = GH_Group()
    g.CreateAttributes()
    g.NickName = args["name"]
    if args.get("colour"):
        try:
            g.Colour = hex_to_color(args["colour"])
        except Exception:
            pass
    doc.UndoUtil.RecordAddObjectEvent("Claude: group " + args["name"], g)
    doc.AddObject(g, False)
    added = 0
    for gid in args["guids"]:
        try:
            g.AddObject(System.Guid.Parse(str(gid)))
            added += 1
        except Exception:
            pass
    g.ExpireCaches()
    _refresh()
    return {"guid": str(g.InstanceGuid), "members": added}


def _anchor_xy(doc, args):
    ids = args.get("anchor_group_of")
    if not ids:
        return float(args.get("x", 0.0)), float(args.get("y", 0.0))
    xs, ys = [], []
    for gid in ids:
        o = find(doc, gid)
        try:
            b = o.Attributes.Bounds
            xs.append(float(b.X))
            ys.append(float(b.Y))
        except Exception:
            pass
    if not xs:
        return float(args.get("x", 0.0)), float(args.get("y", 0.0))
    return min(xs), min(ys) - float(args.get("height", 90)) - 28.0


def h_add_panel(args):
    from Grasshopper.Kernel.Special import GH_Panel

    doc = active_doc()
    p = GH_Panel()
    p.CreateAttributes()
    x, y = _anchor_xy(doc, args)
    w, h = float(args.get("width", 200)), float(args.get("height", 90))
    p.Attributes.Bounds = System.Drawing.RectangleF(x, y, w, h)
    p.Attributes.Pivot = System.Drawing.PointF(x, y)
    for name, val in (("Multiline", True), ("Wrap", True),
                      ("DrawIndices", False), ("DrawPaths", False)):
        try:
            setattr(p.Properties, name, val)
        except Exception:
            pass
    try:
        p.SetUserText(str(args["text"]))
    except Exception:
        p.UserText = str(args["text"])
    if args.get("nickname"):
        p.NickName = args["nickname"]
    doc.UndoUtil.RecordAddObjectEvent("Claude: note panel", p)
    doc.AddObject(p, False)
    p.ExpireSolution(True)
    return {"guid": str(p.InstanceGuid)}


def h_add_scribble(args):
    from Grasshopper.Kernel.Special import GH_Scribble

    doc = active_doc()
    x, y = float(args["x"]), float(args["y"])
    pt = System.Drawing.PointF(x, y)
    try:
        s = GH_Scribble(pt)
    except Exception:
        s = GH_Scribble()
    s.CreateAttributes()
    try:
        s.Text = str(args["text"])
    except Exception:
        pass
    try:
        s.FontSize = float(args.get("size", 20))
    except Exception:
        pass
    try:
        s.Attributes.Pivot = pt
    except Exception:
        pass
    doc.UndoUtil.RecordAddObjectEvent("Claude: scribble", s)
    doc.AddObject(s, False)
    _refresh()
    return {"guid": str(s.InstanceGuid)}


def h_batch(args):
    results = []
    for cmd in args.get("commands", []):
        fn = HANDLERS.get(cmd.get("cmd"))
        if fn is None:
            results.append({"ok": False, "error": "unknown: %s" % cmd.get("cmd")})
            continue
        try:
            results.append({"ok": True, "result": fn(cmd.get("args", {}))})
        except Exception as exc:
            results.append({"ok": False, "error": str(exc),
                            "trace": traceback.format_exc()})
    return {"results": results, "count": len(results)}


def _refresh():
    try:
        Grasshopper.Instances.ActiveCanvas.Refresh()
    except Exception:
        pass


HANDLERS = {
    "ping": h_ping,
    "get_canvas": h_get_canvas,
    "get_errors": h_get_errors,
    "get_value": h_get_value,
    "solve": h_solve,
    "capture_canvas": h_capture_canvas,
    "capture_viewport": h_capture_viewport,
    "add_component": h_add_component,
    "add_input": h_add_input,
    "set_value": h_set_value,
    "connect": h_connect,
    "disconnect": h_disconnect,
    "delete": h_delete,
    "set_pivot": h_set_pivot,
    "set_nickname": h_set_nickname,
    "create_group": h_create_group,
    "add_panel": h_add_panel,
    "add_scribble": h_add_scribble,
    "clear_canvas": h_clear_canvas,
    "batch": h_batch,
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
# The script variable IS the input parameter's nickname, case-sensitive. Accept
# either capitalisation so a stray "Enable" / "Port" nickname still works.
_g = globals()
_enable = bool(_g.get("enable", _g.get("Enable", False)))
_raw_port = _g.get("port", _g.get("Port", None))
try:
    _port = int(_raw_port) if _raw_port else DEFAULT_PORT
except (TypeError, ValueError):
    _port = DEFAULT_PORT

if _enable:
    _rec = ensure_server(_port)
    log = "Claude bridge LISTENING on 127.0.0.1:%d   doc: %s" % (_rec["port"], _safe_doc_name())
else:
    stop_server()
    log = "Claude bridge OFF   (set enable = True to start)"

a = log  # default output name in the Rhino 8 script editor
