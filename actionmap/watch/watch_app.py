"""
Nodach Watch window (the Driver's Watch, v0). Opened by Nodach Desktop when Watch is turned on; phone-shaped
(400 x 820), optionally always on top.

The UI is plain HTML/CSS/JS (web/) served by watch_server.py on 127.0.0.1, so the later Rust Driver (Tauri) can show
the same files. Here it is shown with pywebview (WebView2 on Windows). Without pywebview it opens in the default
browser instead (the Watch window still works; hiding itself during a capture and 'on top' need pywebview).

21 Nov fixes:
- Placement at display scaling: the process is per-monitor DPI aware before pywebview starts, the work area and
  scale come from Windows, watch_core.place() works out the rectangle in physical pixels, and once the window is
  shown it is moved there with SetWindowPos (pywebview's own units differ between versions).
- Code changes load by themselves: every 2 s (never mid-capture) a change to app\\watch\\*.py restarts this app
  (a new process, same arguments; run\\watch.pid follows it) and a change under web\\ reloads the page.
- Claude's test hook: the port and key go to %USERPROFILE%\\nodach\\run\\watch.json (user-only access), which
  the Desktop worker reads to call /api/test/... (see watch_server).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watch_server as server   # noqa: E402
import watch_core as core       # noqa: E402

TITLE = "Nodach Watch"
SIZE = (400, 820)


def _open_folder(p: Path):
    p.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(p))  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(p)])


# ---------------------------------------------------------------- Windows: work area, scale, moving the window
def work_area_and_scale():
    """((left, top, right, bottom) of the primary monitor's work area in physical px, scale) or None off Windows.
    Needs the process to be DPI aware first (watch_win.dpi_aware), else Windows reports scaled-down numbers."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        r = wintypes.RECT()
        if not u.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):     # SPI_GETWORKAREA
            return None
        try:
            dpi = u.GetDpiForSystem()
        except Exception:
            dpi = 96
        return (r.left, r.top, r.right, r.bottom), (dpi or 96) / 96.0
    except Exception:
        return None


def find_hwnd(win) -> int:
    try:
        h = win.native.Handle          # pywebview winforms backend
        return int(h.ToInt64()) if hasattr(h, "ToInt64") else int(h)
    except Exception:
        pass
    try:
        import ctypes
        return int(ctypes.windll.user32.FindWindowW(None, TITLE) or 0)
    except Exception:
        return 0


def move_window(hwnd: int, r: dict) -> bool:
    try:
        import ctypes
        SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
        return bool(ctypes.windll.user32.SetWindowPos(hwnd, 0, r["x"], r["y"], r["width"], r["height"], SWP_NOZORDER | SWP_NOACTIVATE))
    except Exception:
        return False


def window_visible(hwnd: int):
    try:
        import ctypes
        u = ctypes.windll.user32
        return bool(u.IsWindowVisible(hwnd)) and not bool(u.IsIconic(hwnd))
    except Exception:
        return None


def write_private_json(p: Path, data: dict):
    """run\\watch.json holds the per-start key: readable by this user only (the Desktop worker runs as him)."""
    server.write_json(p, data)
    try:
        if os.name == "nt":
            user = os.environ.get("USERNAME") or ""
            if user:
                subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", f"{user}:F"], capture_output=True,
                               timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.chmod(p, 0o600)
    except Exception:
        pass


# ---------------------------------------------------------------- restart / reload on change
def respawn(argv) -> int:
    """Start a fresh copy of this app (same interpreter and arguments) and point run\\watch.pid at it."""
    root = server.DESKTOP_ROOT
    (root / "logs").mkdir(parents=True, exist_ok=True)
    out = open(root / "logs" / "watch-app.log", "ab")
    try:
        env = dict(os.environ, NODACH_WATCH_RESTARTED="1")
        p = subprocess.Popen([sys.executable, str(HERE / "watch_app.py"), *argv], cwd=os.getcwd(), env=env,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    finally:
        out.close()
    server.write_json(root / "run" / "watch.pid", {"pid": p.pid, "started": core.iso(core.utcnow()), "script": "watch_app.py",
                                                    "restarted_from": os.getpid()})
    return p.pid


def watch_for_changes(w, on_restart, on_reload, stop: threading.Event, every_s: float = 2.0):
    prev = core.files_signature(HERE)
    while not stop.wait(every_s):
        try:
            cur = core.files_signature(HERE)
            d = core.reload_decision(prev, cur, w.capturing)
            if d is None and w.capturing:
                continue                     # keep prev: decide again after the capture
            prev = cur
            if d == "restart":
                w.note("restart", "info", "Watch's code changed: restarting")
                on_restart()
                return
            if d == "reload":
                w.note("reload", "info", "Watch's page changed: reloading")
                on_reload()
        except Exception:
            traceback.print_exc()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=TITLE)
    ap.add_argument("--browser", action="store_true", help="open in the default browser instead of a window")
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args(argv)
    if os.name == "nt":
        try:
            import watch_win
            watch_win.dpi_aware()           # before pywebview starts, so sizes and positions are physical pixels
        except Exception:
            pass
    hooks = {"open_folder": _open_folder}
    w = server.Watch(hooks=hooks)
    if os.environ.pop("NODACH_WATCH_RESTARTED", None):
        w.note("restart", "ok", "restarted with the new code")
    srv, url, key = server.serve(w, a.port)
    run = server.DESKTOP_ROOT / "run"
    run.mkdir(parents=True, exist_ok=True)
    port = srv.server_address[1]
    started = core.iso(core.utcnow())
    server.write_json(run / "watch-window.json", {"pid": os.getpid(), "port": port, "started": started})
    write_private_json(run / "watch.json", {"pid": os.getpid(), "port": port, "key": key, "started": started})
    stop = threading.Event()
    webview = None
    if not a.browser:
        try:
            import webview as _wv
            webview = _wv
        except Exception:
            webview = None

    def restart():
        respawn(argv)
        try:
            srv.shutdown()
        finally:
            os._exit(0)                     # the new process owns run\watch*.json now: don't remove them
    try:
        if webview is None:
            webbrowser.open(url)
            w.note("setup", "info", "pywebview isn't installed: opened in the browser (pip install pywebview)")
            threading.Thread(target=watch_for_changes, args=(w, restart, lambda: None, stop), daemon=True).start()
            while True:
                time.sleep(3600)
        wa = work_area_and_scale()
        pos = {}
        if wa:
            r = core.place(wa[0], wa[1], SIZE)
        else:   # not Windows: pywebview's own screen size
            r = None
            try:
                scr = webview.screens[0]
                r = core.place((int(scr.x), int(scr.y), int(scr.x) + int(scr.width), int(scr.y) + int(scr.height)), 1.0, SIZE)
            except Exception:
                pass
        if r:
            # logical numbers as a first guess (safe whichever units this pywebview uses); the exact physical
            # rectangle is set with SetWindowPos once the window exists
            pos = dict(x=r["lx"], y=r["ly"], width=r["lwidth"], height=r["lheight"])
        else:
            pos = dict(width=SIZE[0], height=SIZE[1])
        win = webview.create_window(TITLE, url, on_top=bool(w.settings.get("on_top")), resizable=True,
                                    min_size=(340, 560), **pos)
        flags = {"visible": False, "hwnd": 0}

        def on_shown():
            flags["visible"] = True
            flags["hwnd"] = find_hwnd(win)
            if wa and flags["hwnd"]:
                if move_window(flags["hwnd"], r):
                    w.note("window", "ok", f"placed at {r['x']},{r['y']} {r['width']}x{r['height']} px (scale {r['scale']:g})")

        def hide():
            flags["visible"] = False
            win.hide()

        def show():
            win.show()
            flags["visible"] = True

        def visible():
            v = window_visible(flags["hwnd"]) if flags["hwnd"] else None
            return flags["visible"] if v is None else v
        for ev, fn in (("shown", on_shown), ("minimized", lambda: flags.update(visible=False)),
                       ("restored", lambda: flags.update(visible=True)), ("closed", lambda: flags.update(visible=False))):
            try:
                getattr(win.events, ev).__iadd__(fn)
            except Exception:
                pass
        hooks["hide"], hooks["show"], hooks["visible"] = hide, show, visible
        n = {"reload": 0}

        def reload_page():
            n["reload"] += 1
            base, _, frag = url.partition("#")
            win.load_url(f"{base}?r={n['reload']}#{frag}")

        def on_top(v):
            win.on_top = bool(v)
        hooks["on_top"] = on_top
        threading.Thread(target=watch_for_changes, args=(w, restart, reload_page, stop), daemon=True).start()
        webview.start()
        return 0
    finally:
        stop.set()
        srv.shutdown()
        for f in ("watch-window.json", "watch.json"):
            try:
                (run / f).unlink()
            except OSError:
                pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        home = server.HOME
        home.mkdir(parents=True, exist_ok=True)
        (home / "watch-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
