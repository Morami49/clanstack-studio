"""
Nodach Watch window (the Driver's Watch, v0). Opened by Nodach Desktop when Watch is turned on; phone-shaped
(400 x 820), optionally always on top.

The UI is plain HTML/CSS/JS (web/) served by watch_server.py on 127.0.0.1, so the later Rust Driver (Tauri) can show
the same files. Here it is shown with pywebview (WebView2 on Windows). Without pywebview it opens in the default
browser instead (the Watch window still works; hiding itself during a capture and 'on top' need pywebview).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=TITLE)
    ap.add_argument("--browser", action="store_true", help="open in the default browser instead of a window")
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args(argv)
    if os.name == "nt":
        try:
            import watch_win
            watch_win.dpi_aware()
        except Exception:
            pass
    hooks = {"open_folder": _open_folder}
    w = server.Watch(hooks=hooks)
    srv, url, _key = server.serve(w, a.port)
    run = server.DESKTOP_ROOT / "run"
    run.mkdir(parents=True, exist_ok=True)
    server.write_json(run / "watch-window.json", {"pid": os.getpid(), "port": srv.server_address[1], "started": core.iso(core.utcnow())})
    webview = None
    if not a.browser:
        try:
            import webview as _wv
            webview = _wv
        except Exception:
            webview = None
    try:
        if webview is None:
            webbrowser.open(url)
            w.note("setup", "info", "pywebview isn't installed: opened in the browser (pip install pywebview)")
            while True:
                time.sleep(3600)
        win = webview.create_window(TITLE, url, width=SIZE[0], height=SIZE[1], on_top=bool(w.settings.get("on_top")),
                                    resizable=True, min_size=(340, 560))
        hooks["hide"] = win.hide
        hooks["show"] = win.show

        def on_top(v):
            win.on_top = bool(v)
        hooks["on_top"] = on_top
        webview.start()
        return 0
    finally:
        srv.shutdown()
        try:
            (run / "watch-window.json").unlink()
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
