"""
Nodach Watch: the Windows side. Screen grabs, UI Automation lookups, and the full-screen overlay where you Point,
Select an area, Mark up (arrow, box, pen, text, numbered step, if/else label) or pick a window to keep out.

How a capture runs (watch_server calls capture()):
  1. grab the whole virtual screen once, black out every never-zone or kept-out window (watch_core.redact_rects)
  2. show that frozen, redacted picture full screen in a separate process (this file, `overlay` mode), so the
     drawing happens on a still image like an image editor and the Watch window isn't in the way
  3. read UI Automation at the points you used (the live UI hasn't moved), drop never/kept-out elements
  4. save the crop under %USERPROFILE%\\nodach-watch\\shots, append the pointer.v1 event to the Watch log and to the
     Pointer's events.jsonl (so get_pointed_elements / get_pointer_screenshot show it to Claude on this PC)
Imports anywhere; on a PC without pywin32/uiautomation/Pillow every function answers "not available".
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watch_core as core   # noqa: E402

try:
    import gate_win          # window/process helpers already used by Gate
except Exception:            # pragma: no cover
    gate_win = None
try:
    import uiautomation as uia
except Exception:
    uia = None
try:
    from PIL import Image, ImageDraw, ImageGrab
except Exception:
    Image = ImageDraw = ImageGrab = None

AVAILABLE = bool(gate_win and gate_win.AVAILABLE and ImageGrab is not None)
HOME = Path(os.environ.get("NODACH_WATCH_HOME", str(Path.home() / "nodach-watch")))
POINTER_EVENTS = Path(os.environ.get("NODACH_POINTER_HOME", str(Path.home() / "nodach-pointer"))) / "events.jsonl"


def dpi_aware():
    try:
        import ctypes
        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


# ---------------------------------------------------------------- windows and elements
def windows() -> list[dict]:
    """Visible top-level windows: [{app, title, rect, hwnd}], front to back."""
    if not AVAILABLE:
        return []
    out = []
    for w in gate_win.open_windows():
        try:
            r = gate_win.win32gui.GetWindowRect(w["hwnd"])
        except Exception:
            r = None
        if r and r[2] > r[0] and r[3] > r[1]:
            out.append(dict(w, rect=tuple(r)))
    return out


def window_at(x: int, y: int) -> dict:
    if not AVAILABLE:
        return {"app": "", "title": "", "rect": None}
    return gate_win.window_at(x, y)


def _rect_of(c) -> dict | None:
    try:
        r = c.BoundingRectangle
        return {"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom}
    except Exception:
        return None


def element_at(x: int, y: int) -> dict | None:
    """The UI Automation element at a point, with its window and process."""
    if uia is None:
        return None
    try:
        c = uia.ControlFromPoint(int(x), int(y))
    except Exception:
        return None
    if c is None:
        return None
    w = window_at(x, y)
    anc, p = [], None
    try:
        p = c.GetParentControl()
        while p is not None and len(anc) < 8:
            anc.append({"type": p.ControlTypeName, "name": (p.Name or "")[:80]})
            p = p.GetParentControl()
    except Exception:
        pass
    return {"type": getattr(c, "ControlTypeName", ""), "name": (getattr(c, "Name", "") or "")[:200],
            "automation_id": getattr(c, "AutomationId", "") or "", "class_name": getattr(c, "ClassName", "") or "",
            "rect": _rect_of(c), "app": w.get("app", ""), "window": {"title": w.get("title", ""), "app": w.get("app", "")},
            "ancestors": anc}


def elements_in(area: dict, samples: int = 12) -> list[dict]:
    """Elements inside a rectangle: UI Automation at a grid of points (up to samples x samples), de-duplicated."""
    a = core.as_rect(area)
    out, seen = [], set()
    w, h = max(1, a["right"] - a["left"]), max(1, a["bottom"] - a["top"])
    nx, ny = min(samples, max(2, w // 24)), min(samples, max(2, h // 24))
    for i in range(nx):
        for j in range(ny):
            x = a["left"] + int((i + 0.5) * w / nx)
            y = a["top"] + int((j + 0.5) * h / ny)
            e = element_at(x, y)
            if not e:
                continue
            key = (e["type"], e["name"], json.dumps(e["rect"], sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
    return out


# ---------------------------------------------------------------- pixels
def virtual_screen() -> tuple[int, int, int, int]:
    try:
        import ctypes
        u = ctypes.windll.user32
        x, y = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        return x, y, x + u.GetSystemMetrics(78), y + u.GetSystemMetrics(79)
    except Exception:
        return 0, 0, 1920, 1080


def grab_redacted(zones: dict):
    """(image, origin, screen): the whole virtual screen with never/kept-out windows blacked out."""
    img = ImageGrab.grab(all_screens=True)
    l, t, r, b = virtual_screen()
    d = ImageDraw.Draw(img)
    for rr in core.redact_rects(windows(), zones):
        d.rectangle([rr["left"] - l, rr["top"] - t, rr["right"] - l, rr["bottom"] - t], fill=(0, 0, 0))
    return img, (l, t), {"left": l, "top": t, "right": r, "bottom": b}


def save_crop(img, origin, box: dict, path: Path) -> str | None:
    if not box or img is None:
        return None
    l, t = origin
    crop = img.crop((box["left"] - l, box["top"] - t, box["right"] - l, box["bottom"] - t))
    path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(path, "PNG")
    return str(path)


def append_event(e: dict):
    HOME.mkdir(parents=True, exist_ok=True)
    line = json.dumps(e, ensure_ascii=False) + "\n"
    with open(HOME / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(line)
    try:   # the Pointer's tools show Watch events too (mode "watch": Live doesn't attach them on its own)
        POINTER_EVENTS.parent.mkdir(parents=True, exist_ok=True)
        with open(POINTER_EVENTS, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


# ---------------------------------------------------------------- the capture
def run_overlay(mode: str, image_path: Path, origin, preset: str | None = None, timeout: int = 600) -> dict:
    out = Path(tempfile.mkstemp(suffix=".json")[1])
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    cmd = [str(pyw if pyw.exists() else exe), str(HERE / "watch_win.py"), "overlay", "--mode", mode, "--image",
           str(image_path), "--origin", f"{origin[0]},{origin[1]}", "--out", str(out)] + (["--preset", preset] if preset else [])
    try:
        subprocess.run(cmd, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return json.loads(out.read_text(encoding="utf-8") or "{}")
    except Exception as e:
        return {"cancelled": True, "error": f"{type(e).__name__}"}
    finally:
        try:
            out.unlink()
        except OSError:
            pass


def capture(mode: str, zones: dict, preset: str | None = None, overlay=run_overlay) -> dict:
    """mode: point | area | markup | pick. Returns {"event": ...} (saved), {"pick": window, "choices": [...]} for a
    keep-out pick, or {"cancelled": True}."""
    if not AVAILABLE:
        return {"error": "Point, Select and Mark up need Windows with pywin32, uiautomation and Pillow."}
    img, origin, screen = grab_redacted(zones)
    tmp = HOME / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    frozen = tmp / "frozen.png"          # already redacted; deleted right after the overlay closes
    img.save(frozen, "PNG")
    try:
        got = overlay(mode, frozen, origin, preset)
    finally:
        try:
            frozen.unlink()
        except OSError:
            pass
    if got.get("cancelled"):
        return {"cancelled": True}
    t = core.utcnow()
    shots = HOME / "shots"
    if mode == "pick":
        x, y = got["x"], got["y"]
        w = window_at(x, y)
        r = core.never_reason(zones, w.get("app"), w.get("title"))
        if r:
            return {"pick": {"app": w.get("app"), "title": ""}, "already_out": r.split(":")[0], "choices": []}
        return {"pick": {"app": w.get("app"), "title": w.get("title")}, "choices": core.pick_choices(w)}
    if mode == "point":
        x, y = got["x"], got["y"]
        el = element_at(x, y) or {"type": "", "name": "", "rect": None, "window": window_at(x, y)}
        win = el.get("window") or {}
        box = core.pad(el["rect"], 24, screen) if el.get("rect") else core.pad(core.rect(x - 300, y - 200, x + 300, y + 200), 0, screen)
        e = core.point_event(t, cursor=(x, y), element=el, window=win, process={"name": win.get("app")},
                             ancestors=el.get("ancestors") or [], shot_box=[box["left"], box["top"], box["right"], box["bottom"]],
                             zones=zones)
    elif mode == "area":
        a = core.rect(*got["rect"])
        cx, cy = (a["left"] + a["right"]) // 2, (a["top"] + a["bottom"]) // 2
        win = window_at(cx, cy)
        e = core.area_event(t, area=a, elements=elements_in(a), window=win, process={"name": win.get("app")}, zones=zones)
    else:
        marks = got.get("marks") or []
        for m in marks:
            if m.get("type") == "arrow":
                m["from_element"] = element_at(*m["from"])
                m["to_element"] = element_at(*m["to"])
            if m.get("type") == "box":
                m["elements"] = elements_in(core.rect(*m["rect"]))
                m["rect"] = core.rect(*m["rect"])
        first = marks[0] if marks else {}
        p = first.get("from") or first.get("at") or (first.get("points") or [[0, 0]])[0] or [0, 0]
        if isinstance(p, dict):
            p = (p["x"], p["y"])
        win = window_at(*p) if marks else {}
        try:
            e = core.markup_event(t, marks=marks, window=win, process={"name": win.get("app")}, preset=preset,
                                  zones=zones, screen=screen)
        except ValueError as err:
            return {"error": str(err)}
    if not e.get("kept_out") and e.get("shot_box"):
        b = dict(zip(("left", "top", "right", "bottom"), e["shot_box"]))
        e["screenshot"] = save_crop(img, origin, b, shots / f"{e['id']}.png")
    if e.get("note") is None and got.get("note"):
        e["note"] = str(got["note"])[:500]
    append_event(e)
    return {"event": e}


# ---------------------------------------------------------------- the overlay (its own process)
TOOLS = [("arrow", "→ Arrow"), ("box", "▭ Box"), ("path", "✎ Pen"), ("text", "T Note"), ("step", "① Step"),
         ("branch", "◇ If / else")]


def overlay_main(a) -> int:
    dpi_aware()
    import tkinter as tk
    from tkinter import simpledialog
    ox, oy = (int(v) for v in a.origin.split(","))
    img = Image.open(a.image).convert("RGB")
    dim = Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), 0.25)
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{img.width}x{img.height}+{ox}+{oy}")
    root.attributes("-topmost", True)
    from PIL import ImageTk
    photo = ImageTk.PhotoImage(dim)
    cv = tk.Canvas(root, width=img.width, height=img.height, highlightthickness=0, cursor="crosshair")
    cv.pack()
    cv.create_image(0, 0, image=photo, anchor="nw")
    result = {"cancelled": True}
    st = {"tool": "arrow", "start": None, "item": None, "path": [], "marks": [], "step": 0}
    preset_tool = core.PRESETS.get(a.preset or "", {}).get("tool")
    if preset_tool:
        st["tool"] = preset_tool
    hint = {"point": "Click the element you mean. Esc cancels.", "pick": "Click the window to keep out. Esc cancels.",
            "area": "Drag a rectangle over the area. Esc cancels.",
            "markup": core.PRESETS.get(a.preset or "", {}).get("hint") or "Pick a tool, draw, then Done. Esc cancels."}[a.mode]
    bar = tk.Frame(root, bg="#18201f")
    tk.Label(bar, text=hint, fg="white", bg="#18201f", padx=10, pady=6).pack(side="left")

    def finish(res):
        result.clear()
        result.update(res)
        root.destroy()

    def done():
        if st["marks"]:
            finish({"marks": st["marks"]})
        else:
            finish({"cancelled": True})
    if a.mode == "markup":
        btns = {}

        def pick(t):
            st["tool"] = t
            for k, b in btns.items():
                b.config(relief="sunken" if k == t else "raised")
        for key, label in TOOLS:
            btns[key] = tk.Button(bar, text=label, command=lambda k=key: pick(k))
            btns[key].pack(side="left", padx=2, pady=4)
        tk.Button(bar, text="Undo", command=lambda: (st["marks"] and st["marks"].pop(), redraw())).pack(side="left", padx=6)
        tk.Button(bar, text="✓ Done", bg="#2a7", fg="white", command=done).pack(side="left", padx=6)
        pick(st["tool"])
    tk.Button(bar, text="Cancel", command=lambda: finish({"cancelled": True})).pack(side="left", padx=6)
    bar.place(x=img.width // 2, y=8, anchor="n")
    drawn = []

    def scr(x, y):
        return [x + ox, y + oy]

    def redraw():
        for i in drawn:
            cv.delete(i)
        drawn.clear()
        for m in st["marks"]:
            c = "#f60"
            if m["type"] == "arrow":
                (x1, y1), (x2, y2) = [(p[0] - ox, p[1] - oy) for p in (m["from"], m["to"])]
                drawn.append(cv.create_line(x1, y1, x2, y2, fill=c, width=4, arrow="last", arrowshape=(18, 22, 8)))
            elif m["type"] == "box":
                l, t, r, b = m["rect"]
                drawn.append(cv.create_rectangle(l - ox, t - oy, r - ox, b - oy, outline=c, width=3))
            elif m["type"] == "path" and len(m["points"]) > 1:
                drawn.append(cv.create_line(*[v for p in m["points"] for v in (p[0] - ox, p[1] - oy)], fill=c, width=3, smooth=True))
            else:
                x, y = m["at"][0] - ox, m["at"][1] - oy
                label = {"step": f"{m.get('step', '')}", "branch": m.get("label", "if")}.get(m["type"], "")
                if label:
                    drawn.append(cv.create_oval(x - 14, y - 14, x + 14, y + 14, fill=c, outline="white"))
                    drawn.append(cv.create_text(x, y, text=label[:6], fill="white", font=("Segoe UI", 9, "bold")))
                if m.get("text"):
                    drawn.append(cv.create_text(x + 20, y, text=m["text"][:80], fill="white", anchor="w", font=("Segoe UI", 11, "bold")))

    def ask(prompt):
        return simpledialog.askstring("Nodach Watch", prompt, parent=root) or ""

    def down(ev):
        if a.mode in ("point", "pick"):
            finish({"x": ev.x + ox, "y": ev.y + oy})
            return
        st["start"] = (ev.x, ev.y)
        st["path"] = [scr(ev.x, ev.y)]
        if a.mode == "markup" and st["tool"] in ("text", "step", "branch"):
            m = {"type": st["tool"], "at": scr(ev.x, ev.y)}
            if st["tool"] == "step":
                st["step"] += 1
                m["step"] = st["step"]
                m["text"] = ask(f"Step {st['step']}: what happens here? (optional)")
            elif st["tool"] == "branch":
                lab = ask("Branch label: if / else if / else / then").strip().lower() or "if"
                m["label"] = lab if lab in ("if", "else if", "else", "then") else "if"
                m["text"] = ask(f"{m['label']} … (the condition or what happens)")
            else:
                m["text"] = ask("Note")
                if not m["text"]:
                    return
            st["marks"].append(m)
            st["start"] = None
            redraw()

    def move(ev):
        if not st["start"]:
            return
        x0, y0 = st["start"]
        if st["item"]:
            cv.delete(st["item"])
        tool = "box" if a.mode == "area" else st["tool"]
        if tool == "arrow":
            st["item"] = cv.create_line(x0, y0, ev.x, ev.y, fill="#f60", width=4, arrow="last")
        elif tool == "path":
            st["path"].append(scr(ev.x, ev.y))
            st["item"] = cv.create_line(*[v for p in st["path"] for v in (p[0] - ox, p[1] - oy)], fill="#f60", width=3)
        else:
            st["item"] = cv.create_rectangle(x0, y0, ev.x, ev.y, outline="#f60", width=3)

    def up(ev):
        if not st["start"]:
            return
        x0, y0 = st["start"]
        st["start"] = None
        if st["item"]:
            cv.delete(st["item"])
            st["item"] = None
        if abs(ev.x - x0) + abs(ev.y - y0) < 6 and (a.mode == "area" or st["tool"] in ("arrow", "box")):
            return
        if a.mode == "area":
            finish({"rect": [x0 + ox, y0 + oy, ev.x + ox, ev.y + oy]})
            return
        tool = st["tool"]
        if tool == "arrow":
            st["marks"].append({"type": "arrow", "from": scr(x0, y0), "to": scr(ev.x, ev.y)})
            if a.preset == "wrong-place":       # the preset is one arrow: done as soon as it's drawn
                finish({"marks": st["marks"]})
                return
        elif tool == "box":
            st["marks"].append({"type": "box", "rect": [x0 + ox, y0 + oy, ev.x + ox, ev.y + oy]})
        elif tool == "path":
            st["marks"].append({"type": "path", "points": st["path"]})
        redraw()
    cv.bind("<ButtonPress-1>", down)
    cv.bind("<B1-Motion>", move)
    cv.bind("<ButtonRelease-1>", up)
    root.bind("<Escape>", lambda e: finish({"cancelled": True}))
    root.focus_force()
    root.mainloop()
    Path(a.out).write_text(json.dumps(result), encoding="utf-8")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    o = sub.add_parser("overlay")
    o.add_argument("--mode", choices=("point", "pick", "area", "markup"), required=True)
    o.add_argument("--image", required=True)
    o.add_argument("--origin", default="0,0")
    o.add_argument("--out", required=True)
    o.add_argument("--preset", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "overlay":
        return overlay_main(a)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
