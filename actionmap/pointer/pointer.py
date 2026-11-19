"""
Nodach Desktop Pointer (P-desktop-pointer) — v0.1.0
====================================================
Point at any element in any Windows app and tell your agent what you want.

  Ctrl+Alt+M  capture (mark) the element under the mouse, then type a note (Enter saves,
              Shift+Enter = new line, Esc discards)
  Ctrl+Alt+B  add the element under the mouse to a batch (no note yet); the next
              Ctrl+Alt+M closes the batch and its note applies to every item
  Ctrl+Alt+Q  quit

Each capture writes:
  - one append-only line to  <home>/events.jsonl   (schema "pointer.v1", never overwritten)
  - a cropped screenshot to  <home>/shots/<id>.png
  - a prompt-ready block to the clipboard (paste into any AI chat)

<home> defaults to %USERPROFILE%\\nodach-pointer (override with NODACH_POINTER_HOME).
pointer_mcp.py exposes the same events to Claude Desktop / Claude Code as MCP tools.

Privacy: the script never reads field values (so typed passwords are not captured),
but screenshots show whatever is on screen. Don't point at things you wouldn't share.
"""
import ctypes
import datetime as dt
import json
import os
import queue
import sys
import urllib.request
import uuid
from pathlib import Path

# Physical-pixel coordinates so UI Automation rectangles and screenshots line up on scaled displays.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk

import psutil
import uiautomation as auto
from PIL import ImageGrab
from pynput import keyboard

VERSION = "0.1.3"
SCHEMA = "pointer.v1"
HOME = Path(os.environ.get("NODACH_POINTER_HOME", str(Path.home() / "nodach-pointer")))
SHOTS = HOME / "shots"
EVENTS = HOME / "events.jsonl"
PAD = 24                      # pixels of context around the element in the screenshot
MAX_AREA = 4_000_000          # elements bigger than this (whole windows) get a cursor-centred crop
HOTKEYS = {"<ctrl>+<alt>+m": "point", "<ctrl>+<alt>+b": "batch", "<ctrl>+<alt>+q": "quit"}

jobs: "queue.Queue[str]" = queue.Queue()
pending_batch: list = []      # ids captured with Ctrl+Alt+B, waiting for a note


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def new_id(t: dt.datetime) -> str:
    # Stable prefix "PE-" (pointer event); renaming views or categories never changes ids.
    return f"PE-{t:%y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def rect_of(c) -> dict:
    r = c.BoundingRectangle
    return {"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom}


def ancestors(c, limit: int = 8) -> list:
    out, p, n = [], safe(c.GetParentControl), 0
    while p is not None and n < limit:
        out.append({"type": safe(lambda: p.ControlTypeName, ""), "name": (safe(lambda: p.Name, "") or "")[:80]})
        p, n = safe(p.GetParentControl), n + 1
    return out


def top_window(c):
    root = auto.GetRootControl()
    w = c
    while True:
        p = safe(w.GetParentControl)
        if p is None or safe(lambda: auto.ControlsAreSame(p, root), False):
            return w
        w = p


def grab(eid: str, rect: dict, x: int, y: int):
    l, t, r, b = rect["left"] - PAD, rect["top"] - PAD, rect["right"] + PAD, rect["bottom"] + PAD
    if r - l < 8 or b - t < 8 or (r - l) * (b - t) > MAX_AREA:
        l, t, r, b = x - 300, y - 200, x + 300, y + 200
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{eid}.png"
    ImageGrab.grab(bbox=(l, t, r, b), all_screens=True).save(path)
    return str(path)


def capture() -> dict | None:
    x, y = auto.GetCursorPos()
    c = safe(lambda: auto.ControlFromPoint(x, y))
    if c is None:
        return None
    t = utcnow()
    eid = new_id(t)
    win = top_window(c)
    pid = safe(lambda: c.ProcessId)
    rect = safe(lambda: rect_of(c), {"left": x, "top": y, "right": x, "bottom": y})
    shot, shot_error = None, None
    try:
        shot = grab(eid, rect, x, y)
    except Exception as e:  # screenshot failure must not lose the element data
        shot_error = str(e)
    return {
        "schema": SCHEMA,
        "tool": "nodach-desktop-pointer",
        "tool_version": VERSION,
        "id": eid,
        "kind": "pointer.desktop",
        "at": t.isoformat(),
        "cursor": {"x": x, "y": y},
        "element": {
            "type": safe(lambda: c.ControlTypeName, ""),
            "name": (safe(lambda: c.Name, "") or "")[:200],
            "automation_id": safe(lambda: c.AutomationId, ""),
            "class_name": safe(lambda: c.ClassName, ""),
            "rect": rect,
        },
        "window": {
            "title": (safe(lambda: win.Name, "") or "")[:200],
            "class_name": safe(lambda: win.ClassName, ""),
            "handle": safe(lambda: win.NativeWindowHandle),
        },
        "process": {"pid": pid, "name": safe(lambda: psutil.Process(pid).name())},
        "ancestors": ancestors(c),
        "screenshot": shot,
        "screenshot_error": shot_error,
        "note": None,
        "batch_refs": [],
        "mode": None,
    }


def append(event: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


ACTIONMAP_URL = os.environ.get("ACTIONMAP_URL", "http://127.0.0.1:8765").rstrip("/")
ACTIONMAP_TOKEN = os.environ.get("ACTIONMAP_TOKEN", "")


def to_actionmap(e: dict) -> str:
    """Also record the point in ActionMap's spine (actionmap/event/v1) when it's running, so every
    tool that reads ActionMap (its map UI, its MCP connector) sees what you pointed at.
    The local events.jsonl line stays the source of truth; this never rewrites it."""
    el, w, p = e["element"], e["window"], e["process"]
    ev = {
        "schema_version": 1, "session_id": "pointer", "node_id": os.environ.get("COMPUTERNAME", "win-desktop"),
        "actor": {"kind": "human", "id": "human:" + os.environ.get("ACTIONMAP_HUMAN_ID", "local")}, "kind": "annotation", "action": "point",
        "target": {"app": p["name"], "window": w["title"], "element": el["name"], "control_type": el["type"],
                   "automation_id": el["automation_id"], "rect": el["rect"]},
        "payload": {"pointer_id": e["id"], "note": e["note"], "batch_refs": e["batch_refs"],
                    "screenshot_local": e["screenshot"], "ancestors": e["ancestors"], "pointer_schema": SCHEMA},
        "causes": [],
    }
    req = urllib.request.Request(f"{ACTIONMAP_URL}/events", data=json.dumps(ev).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          **({"X-ActionMap-Token": ACTIONMAP_TOKEN} if ACTIONMAP_TOKEN else {})})
    try:
        with urllib.request.urlopen(req, timeout=2):
            return "sent to ActionMap"
    except Exception:
        return "ActionMap not running (saved locally only)"


def summary(e: dict) -> str:
    el, w, p = e["element"], e["window"], e["process"]
    path = " > ".join(f'{a["type"]} "{a["name"]}"' if a["name"] else a["type"] for a in reversed(e["ancestors"]))
    return (
        f"[Nodach pointer {e['id']}] app={p['name']} window=\"{w['title']}\"\n"
        f"element: {el['type']} \"{el['name']}\" (AutomationId={el['automation_id'] or '-'}, Class={el['class_name'] or '-'})\n"
        f"path: {path or '-'}\n"
        f"rect: {el['rect']}\n"
        f"screenshot: {e['screenshot'] or e['screenshot_error']}"
    )


def ask_note(root: tk.Tk, e: dict):
    """Returns (note, keep). keep=False when the user pressed Esc."""
    win = tk.Toplevel(root)
    win.title("Nodach pointer")
    win.attributes("-topmost", True)
    win.geometry(f"+{e['cursor']['x'] + 20}+{e['cursor']['y'] + 20}")
    head = summary(e).split("\n")[1]
    if pending_batch:
        head += f"\n(+ {len(pending_batch)} batched element(s))"
    tk.Label(win, text=head, justify="left", wraplength=460).pack(padx=10, pady=(10, 4), anchor="w")
    box = tk.Text(win, width=62, height=4)
    box.pack(padx=10, pady=(0, 4))
    tk.Label(win, text="Enter = save · Shift+Enter = new line · Esc = discard", fg="#666").pack(padx=10, pady=(0, 8), anchor="w")
    result = {"note": None, "keep": True}

    def save(_=None):
        result["note"] = box.get("1.0", "end").strip() or None
        win.destroy()
        return "break"

    def discard(_=None):
        result["keep"] = False
        win.destroy()

    box.bind("<Return>", save)
    box.bind("<Shift-Return>", lambda _: None)  # default behaviour: newline
    win.bind("<Escape>", discard)
    win.protocol("WM_DELETE_WINDOW", discard)
    win.after(50, box.focus_force)
    root.wait_window(win)
    return result["note"], result["keep"]


def handle(root: tk.Tk, job: str) -> None:
    if job == "quit":
        root.quit()
        return
    e = capture()
    if e is None:
        print("No element under the cursor.")
        return
    if job == "batch":
        e["mode"] = "batch-item"
        append(e)
        pending_batch.append(e["id"])
        print(f"Batched {e['id']} ({len(pending_batch)} waiting)")
        return
    note, keep = ask_note(root, e)
    if not keep:
        print(f"Discarded {e['id']}")
        return
    e.update(note=note, batch_refs=list(pending_batch), mode="point")
    pending_batch.clear()
    append(e)
    block = summary(e)
    if e["batch_refs"]:
        block += f"\nbatch: {', '.join(e['batch_refs'])}"
    block += f"\nnote: {note or '-'}"
    root.clipboard_clear()
    root.clipboard_append(block)
    print(f"Saved {e['id']} — copied to clipboard — {to_actionmap(e)}")


def pump(root: tk.Tk) -> None:
    try:
        while True:
            handle(root, jobs.get_nowait())
    except queue.Empty:
        pass
    root.after(50, pump, root)


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Nodach Desktop Pointer runs on Windows only.")
    HOME.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    listener = keyboard.GlobalHotKeys({k: (lambda j=j: jobs.put(j)) for k, j in HOTKEYS.items()})
    listener.start()
    print(f"Nodach Desktop Pointer {VERSION} — writing to {EVENTS}")
    print("Ctrl+Alt+M mark + note · Ctrl+Alt+B add to batch · Ctrl+Alt+Q quit")
    root.after(50, pump, root)
    root.mainloop()
    listener.stop()


if __name__ == "__main__":
    main()
