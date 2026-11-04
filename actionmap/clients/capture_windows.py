"""Whole-desktop capture for Windows (the 'human' and 'screen' lanes).

Records: window focus changes, clicks (with the UI element's accessible name),
typing (length only by default), hotkeys, and windows that appear on their own.
It does NOT record screenshots or keystroke content unless you turn that on.

    pip install pynput uiautomation psutil pywin32 httpx pyyaml websockets
    python -m clients.capture_windows

Ctrl+Alt+P toggles capture for this machine (logged as a control event).
"""
from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path

from .common import ROOT, Spine, config

if sys.platform != "win32":
    sys.exit("capture_windows runs on Windows. Use `python -m clients.simulate` elsewhere.")

import psutil                      # noqa: E402
import uiautomation as auto        # noqa: E402
import win32gui                    # noqa: E402
import win32process                # noqa: E402
from pynput import keyboard, mouse  # noqa: E402

CFG = config().get("capture", {})
SKIP = {a.lower() for a in CFG.get("skip_apps", [])}
RECORD_TEXT = bool(CFG.get("record_typed_text", False))
GAP = CFG.get("min_event_gap_ms", 150) / 1000
BUSY = ROOT / "data" / "executor.busy"      # executor touches this while it acts

raw: "queue.Queue[tuple]" = queue.Queue()
mods: set = set()
enabled = {"on": True}


def executor_busy() -> bool:
    try:
        return time.time() - BUSY.stat().st_mtime < 1.5
    except FileNotFoundError:
        return False


def fg_window() -> tuple[str, str, int]:
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd) or ""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        app = psutil.Process(pid).name()
    except Exception:
        app = "?"
    return app, title, hwnd


# ---------------------------------------------------------------- listeners
def on_click(x, y, button, pressed, *_):
    if pressed and not executor_busy():
        raw.put(("click", x, y, str(button)))


def key_name(k) -> str:
    if isinstance(k, keyboard.KeyCode):
        return (k.char or f"vk{k.vk}").lower()
    return str(k).replace("Key.", "")


MOD_KEYS = {"ctrl_l", "ctrl_r", "alt_l", "alt_r", "alt_gr", "cmd", "cmd_l", "cmd_r", "shift", "shift_r"}


def on_press(k):
    if executor_busy():
        return
    n = key_name(k)
    if n in MOD_KEYS:
        mods.add(n.split("_")[0])
        return
    hard = mods - {"shift"}
    if hard:
        raw.put(("hotkey", "+".join(sorted(hard) + [n])))
    elif n in ("enter", "tab", "esc", "delete", "f5"):
        raw.put(("hotkey", n))
    else:
        raw.put(("char", k.char if isinstance(k, keyboard.KeyCode) and k.char else ""))


def on_release(k):
    n = key_name(k)
    if n in MOD_KEYS:
        mods.discard(n.split("_")[0])


# ------------------------------------------------------------------ worker
def worker(sp: Spine):
    with auto.UIAutomationInitializerInThread():
        typing = {"n": 0, "text": "", "target": None, "t": 0.0}
        last = {"win": None, "t": 0.0}

        def emit_human(action, target, payload=None):
            app = (target.get("app") or "").lower()
            if app in SKIP or not enabled["on"]:
                return
            try:
                sp.emit("human", HUMAN, "action", action, target=target, payload=payload or {})
            except Exception as e:
                print("[emit]", e)

        def flush_typing():
            if typing["n"]:
                p = {"chars": typing["n"], "redacted": not RECORD_TEXT}
                if RECORD_TEXT:
                    p["text"] = typing["text"]
                emit_human("type_text", typing["target"], p)
            typing.update(n=0, text="", target=None)

        while True:
            try:
                item = raw.get(timeout=0.3)
            except queue.Empty:
                item = None
            now = time.time()
            app, title, hwnd = fg_window()

            # focus change / window appearing by itself
            if title and (app, title) != last["win"]:
                flush_typing()
                tgt = {"app": app, "window": title, "element": title, "role": "Window"}
                user_caused = now - last["t"] < 1.0
                if user_caused:
                    emit_human("focus_window", tgt)
                elif enabled["on"] and app.lower() not in SKIP:
                    sp.emit("screen", f"screen:{sp.node_id}", "observation", "appeared", target=tgt)
                last["win"] = (app, title)

            if item is None:
                if typing["n"] and now - typing["t"] > 1.5:
                    flush_typing()
                continue
            last["t"] = now
            kind = item[0]
            if kind == "click":
                flush_typing()
                _, x, y, btn = item
                try:
                    c = auto.ControlFromPoint(x, y)
                    el, role, aid = c.Name or c.AutomationId or c.ClassName, c.ControlTypeName, c.AutomationId
                except Exception:
                    el, role, aid = "", "", ""
                emit_human("click", {"app": app, "window": title, "element": el or f"({role})",
                                     "role": role, "path": aid},
                           {"button": btn, "x": x, "y": y})
                time.sleep(GAP)
            elif kind == "hotkey":
                flush_typing()
                if item[1] in ("alt+ctrl+p", "ctrl+alt+p"):
                    enabled["on"] = not enabled["on"]
                    sp.control("set_capture", node_id=sp.node_id, enabled=enabled["on"])
                    print("capture", "ON" if enabled["on"] else "OFF")
                    continue
                emit_human("hotkey", {"app": app, "window": title, "element": item[1]}, {"keys": item[1]})
            elif kind == "char":
                if typing["target"] is None:
                    try:
                        f = auto.GetFocusedControl()
                        el = f.Name or f.AutomationId or f.ControlTypeName
                    except Exception:
                        el = ""
                    typing["target"] = {"app": app, "window": title, "element": el or "text field"}
                typing["n"] += 1
                typing["t"] = now
                if RECORD_TEXT:
                    typing["text"] += item[1]


HUMAN = "human:local"


def main():
    global HUMAN
    sp = Spine()
    HUMAN = f"human:{config().get('client', {}).get('human_id', 'local')}"
    sp.register_node(["capture.desktop.windows"] +
                     (["exec.desktop.windows"] if config().get("executor", {}).get("enabled") else []))
    print(f"capturing node={sp.node_id} session={sp.session_id} -> {sp.url}  (Ctrl+Alt+P toggles)")
    threading.Thread(target=worker, args=(sp,), daemon=True).start()
    with mouse.Listener(on_click=on_click), keyboard.Listener(on_press=on_press, on_release=on_release) as kl:
        kl.join()


if __name__ == "__main__":
    main()
