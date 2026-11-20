"""
Nodach Live client (B-live-session) — v0.1.0
=============================================
Talk into a Nodach Studio live session from your Windows PC. Speech is transcribed HERE, on your own CPU
(faster-whisper); the audio never leaves the PC. Only the text of each line is sent, to the hub, signed in as you.

  Ctrl+Alt+Space  push to talk: press to start, press again to send what you said
  Ctrl+Alt+A      always-on: toggle listening; each phrase (a pause ends it) becomes a line
  Ctrl+Alt+L      send the pointer's latest point on its own (from the Nodach Desktop Pointer, Ctrl+Alt+M)
  or type in this window: a line + Enter sends it · /point · /always · /end ends the session · /quit

A line starting "task:" or "build:" also makes a draft change item linked to the session (owners only; drafts are
never built until approved). A fresh pointer point (made in the last 2 minutes, not used yet) rides on the next line.

Sign-in: the client uses your Studio session (the nodach_session cookie). The first run asks for it once and keeps
it in %USERPROFILE%\\nodach-live\\ (one file per hub); it is never printed. Or set NODACH_LIVE_TOKEN.
No microphone, no faster-whisper, or --typed: typed lines only.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_core as core  # noqa: E402

HOME = Path(os.environ.get("NODACH_LIVE_HOME", str(Path.home() / "nodach-live")))
POINTER_EVENTS = Path(os.environ.get("NODACH_POINTER_HOME", str(Path.home() / "nodach-pointer"))) / "events.jsonl"
DEFAULT_HUB = os.environ.get("NODACH_HUB", "https://staging.nodach.com")
RATE = 16000
FRAME_MS = 30
HOTKEYS = {"<ctrl>+<alt>+<space>": "talk", "<ctrl>+<alt>+a": "always", "<ctrl>+<alt>+l": "point"}

# Optional packages, guarded so this module imports anywhere (tests, typed-only use).
try:
    import numpy as np
    import sounddevice as sd
except Exception as _e:  # ImportError, or PortAudio missing
    np = sd = None
    AUDIO_MISSING = str(_e)
else:
    AUDIO_MISSING = ""
try:
    from pynput import keyboard
except Exception:
    keyboard = None


# ---------------------------------------------------------------- hub
class Hub:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self._cookie = "nodach_session=" + token   # sent only to this hub, never printed

    def _req(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Cookie": self._cookie, "Accept": "application/json", "User-Agent": f"nodach-live/{core.VERSION}"}
        if body is not None:
            h.update({"Content-Type": "application/json", "x-nodach-studio": "1"})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", "")
            except Exception:
                msg = ""
            raise RuntimeError(f"hub said {e.code}{': ' + msg if msg else ''}") from None

    def me(self) -> dict:
        return self._req("GET", "/studio/api/me")

    def events(self):
        out, after = [], 0
        while True:
            r = self._req("GET", f"/studio/api/events?after={after}&limit=2000")
            out += r.get("events") or []
            nxt = r.get("next", after)
            if nxt <= after or nxt >= r.get("total", 0):
                return out
            after = nxt

    def post(self, event: dict, did: str | None = None) -> str:
        did = did or core.doc_id()
        self._req("POST", "/studio/api/events", {"doc_id": did, "event": event})
        return did


def _clipboard() -> str:
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        v = r.clipboard_get()
        r.destroy()
        return v
    except Exception:
        return ""


def token_file(hub_url: str) -> Path:
    host = urllib.parse.urlparse(hub_url).hostname or "hub"
    return HOME / f"session-{host}.txt"


def ask_token(hub_url: str) -> str:
    host = urllib.parse.urlparse(hub_url).hostname or "hub"
    print(f"Sign-in for {host}: copy the nodach_session Cookie Value in your browser (see README),")
    print("then just press Enter here: it's read from your clipboard and never shown.")
    for _ in range(3):
        typed = getpass.getpass("Press Enter (or right-click to paste, then Enter): ")
        t = core.clean_token(typed) or core.clean_token(_clipboard())
        if t:
            f = token_file(hub_url)
            HOME.mkdir(parents=True, exist_ok=True)
            f.write_text(t, encoding="utf-8")
            try:
                os.chmod(f, 0o600)
            except OSError:
                pass
            print("  Sign-in value read.")
            return t
        print("  That isn't a nodach_session value (it looks like name.numbers.long-code). Copy it again and retry.")
    raise SystemExit("No sign-in value; run start-live.bat again when you have it copied.")


def load_token(hub_url: str) -> str:
    t = core.clean_token(os.environ.get("NODACH_LIVE_TOKEN", ""))
    if t:
        return t
    f = token_file(hub_url)
    if f.exists():
        t = core.clean_token(f.read_text(encoding="utf-8"))
        if t:
            return t
    return ask_token(hub_url)


# ---------------------------------------------------------------- the session
class Live:
    def __init__(self, hub: Hub, me: dict, session: str, attach_points: bool = True):
        self.hub, self.me, self.session, self.attach = hub, me, session, attach_points
        self.used_points: set = set()
        self.out: "queue.Queue[tuple]" = queue.Queue()
        threading.Thread(target=self._sender, daemon=True).start()

    def _log(self, row: dict) -> None:   # append-only local record of what was sent (or not)
        HOME.mkdir(parents=True, exist_ok=True)
        with (HOME / "lines.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _point(self):
        if not self.attach or not POINTER_EVENTS.exists():
            return None
        try:
            lines = POINTER_EVENTS.read_text(encoding="utf-8").splitlines()[-200:]
        except OSError:
            return None
        p = core.latest_point(lines, core.utcnow(), self.used_points)
        if p:
            self.used_points.add(p.get("id"))
        return core.shareable_point(p)

    def say(self, text: str, via: str) -> None:
        text = core.clean_text(text)
        if text:
            self.out.put(("line", text, via, self._point()))

    def point_only(self) -> None:
        p = self._point()
        if p:
            self.out.put(("line", "", "pointer", p))
        else:
            print("  No fresh pointer point (point with Ctrl+Alt+M in the Nodach pointer first).")

    def _sender(self) -> None:
        while True:
            _, text, via, point = self.out.get()
            t = core.utcnow()
            ev = core.line_event(self.session, self.me, text, t, via, point)
            try:
                did = self.hub.post(ev)
                task = core.parse_task(text)
                drafted = ""
                if task and self.me.get("owner"):
                    tev = core.task_event(self.session, did, task, self.me, core.utcnow())
                    self.hub.post(tev)
                    drafted = f"  → draft {tev['body']['id']}"
                print(f"  sent{' + point' if point else ''}: {text or '(point)'}{drafted}")
                self._log({"ts": ev["ts"], "session": self.session, "doc_id": did, "text": text, "via": via, "sent": True})
            except Exception as e:
                print(f"  NOT sent ({e}). Kept in {HOME / 'lines.jsonl'}.")
                self._log({"ts": ev["ts"], "session": self.session, "text": text, "via": via, "sent": False, "error": str(e)[:200]})
            finally:
                self.out.task_done()

    def end(self) -> None:
        self.out.join()   # every line lands before the session closes
        t = core.iso(core.utcnow())
        if not self.me.get("owner"):
            print("  Only an owner can end a session.")
            return
        au = core.author(self.me)
        self.hub.post({"ts": t, "kind": "item.edit", "item": self.session, "branch": "main", "author": au,
                       "body": {"live": {"ended": t}, "body": f"Live session ended {t[:16].replace('T', ' ')} UTC from the desktop client."}})
        self.hub.post({"ts": t, "kind": "status", "item": self.session, "branch": "main", "author": au, "body": {"status": "open"}})
        print(f"  Ended {self.session}.")


# ---------------------------------------------------------------- voice (optional)
class Voice:
    def __init__(self, live: Live, model: str):
        from faster_whisper import WhisperModel   # optional; ImportError → typed only
        local = core.local_model_dir([Path(__file__).resolve().parent / "models", HOME / "models"], model)
        if local:
            print(f"Loading the {model} speech model from {local}…")
            self.model = WhisperModel(str(local), device="cpu", compute_type="int8")
        else:
            print(f"Loading the {model} speech model on this PC (first run downloads it once)…")
            try:
                self.model = WhisperModel(model, device="cpu", compute_type="int8")
            except Exception as e:
                raise RuntimeError(f"couldn't download the {model} model ({type(e).__name__}). Put the folder "
                                   f"faster-whisper-{model} (from the Nodach model zip) into {HOME / 'models'} and rerun") from None
        self.live = live
        self.talking = False
        self.always = False
        self.buf: list = []
        self.lock = threading.Lock()
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=RATE * FRAME_MS // 1000, callback=self._cb)
        self.stream.start()
        threading.Thread(target=self._always_loop, daemon=True).start()

    def _cb(self, data, frames, t, status):
        if self.talking or self.always:
            with self.lock:
                self.buf.append(data[:, 0].copy())

    def _transcribe(self, audio, via: str) -> None:
        if audio is None or len(audio) < RATE * 0.3:
            return
        segs, _ = self.model.transcribe(audio, language="en", vad_filter=True, beam_size=1)
        self.live.say(" ".join(s.text for s in segs), via)

    def _take(self, upto=None):
        with self.lock:
            frames, self.buf = (self.buf, []) if upto is None else (self.buf[:upto], self.buf[upto:])
        return np.concatenate(frames) if frames else None

    def toggle_talk(self) -> None:
        if self.always:
            print("  Always-on is listening already (Ctrl+Alt+A turns it off).")
            return
        if not self.talking:
            with self.lock:
                self.buf = []
            self.talking = True
            print("  ● listening… (Ctrl+Alt+Space again to send)")
        else:
            self.talking = False
            audio = self._take()
            threading.Thread(target=self._transcribe, args=(audio, "voice"), daemon=True).start()

    def toggle_always(self) -> None:
        self.talking = False
        with self.lock:
            self.buf = []
        self.always = not self.always
        print("  ● always-on: every phrase becomes a line" if self.always else "  always-on off")

    def _always_loop(self) -> None:
        threshold = float(os.environ.get("NODACH_LIVE_LEVEL", "0.015"))
        quiet = 800 // FRAME_MS
        while True:
            time.sleep(0.25)
            if not self.always:
                continue
            with self.lock:
                levels = [float(np.sqrt(np.mean(f * f))) for f in self.buf]
            if len(levels) * FRAME_MS > 30000:   # 30 s without a pause: send what there is
                self._transcribe(self._take(), "voice-always")
                continue
            done = [s for s in core.segments(levels, threshold, FRAME_MS) if len(levels) - s[1] >= quiet]
            if done:
                end = done[-1][1]
                audio = self._take(end + quiet // 2)
                self._transcribe(audio, "voice-always")
            elif levels and max(levels) < threshold and len(levels) > 2 * quiet:
                self._take(len(levels) - quiet)   # drop old silence


# ---------------------------------------------------------------- main
def pick_session(hub: Hub, me: dict, want: str | None, start: bool) -> str | None:
    if want:
        return want
    if not start:
        sid = core.latest_live_session(hub.events(), me["id"])
        if sid:
            return sid
        if not me.get("owner"):
            print("No live session of yours. Ask an owner for the session id and run with --session LV-…")
            return None
        if input("No live session of yours is open. Start one? [Y/n] ").strip().lower() not in ("", "y", "yes"):
            return None
    ev = core.session_event(me, core.utcnow())
    hub.post(ev)
    return ev["body"]["id"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Nodach Live: talk into a Studio live session (audio stays on this PC).")
    ap.add_argument("--hub", default=DEFAULT_HUB, help="hub address (default: staging, %(default)s)")
    ap.add_argument("--session", help="session id (LV-…); default: your newest live session")
    ap.add_argument("--start", action="store_true", help="start a new session")
    ap.add_argument("--typed", action="store_true", help="no microphone: typed lines only")
    ap.add_argument("--model", default=os.environ.get("NODACH_LIVE_MODEL", "base"), help="faster-whisper model: tiny, base or small")
    ap.add_argument("--no-point", action="store_true", help="never attach pointer points")
    a = ap.parse_args(argv)
    hub = Hub(a.hub, load_token(a.hub))
    try:
        me = hub.me()
    except Exception as e:
        if "401" not in str(e):
            print(f"Couldn't reach {a.hub} ({e}).")
            return 1
        # the stored value expired or was wrong: forget it and ask once more
        print("The saved sign-in wasn't accepted (expired, or from a different sign-in).")
        try:
            token_file(a.hub).unlink()
        except OSError:
            pass
        hub = Hub(a.hub, ask_token(a.hub))
        try:
            me = hub.me()
        except Exception as e2:
            print(f"Still couldn't sign in ({e2}). In the browser, open {a.hub}/studio, sign in with GitHub, "
                  "reload, copy nodach_session again, and rerun.")
            return 1
    sid = pick_session(hub, me, a.session, a.start)
    if not sid:
        return 1
    live = Live(hub, me, sid, attach_points=not a.no_point)
    print(f"Nodach Live {core.VERSION} · {a.hub} · session {sid} · signed in as {'an owner' if me.get('owner') else 'a member'}")
    voice = None
    if not a.typed:
        if AUDIO_MISSING:
            print(f"No microphone support ({AUDIO_MISSING}); typed lines only. Run: pip install -r requirements.txt")
        else:
            try:
                voice = Voice(live, a.model)
            except Exception as e:
                print(f"Voice is off ({type(e).__name__}: {e}); typed lines only.")
    if voice and keyboard is not None:
        jobs = {"talk": voice.toggle_talk, "always": voice.toggle_always, "point": live.point_only}
        keyboard.GlobalHotKeys({k: jobs[j] for k, j in HOTKEYS.items()}).start()
        print("Ctrl+Alt+Space talk/send · Ctrl+Alt+A always-on · Ctrl+Alt+L send latest point · or type below")
    else:
        print("Type a line and press Enter. /point sends the pointer's latest point · /end · /quit")
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        cmd = line.strip().lower()
        if cmd in ("/quit", "/q"):
            break
        if cmd == "/end":
            live.end()
            break
        if cmd == "/point":
            live.point_only()
        elif cmd == "/always" and voice:
            voice.toggle_always()
        elif cmd == "/help":
            print(__doc__)
        elif line.strip():
            live.say(line, "typed")
    live.out.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
