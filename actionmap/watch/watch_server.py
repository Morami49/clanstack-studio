"""
Nodach Watch: the local server behind the Watch window. It serves web/ (the UI) and a small JSON API on
http://127.0.0.1:<port> only, guarded by a key made fresh at each start (the page gets it in its address), so no
other page or program can drive it. pywebview shows the page in a window; without pywebview it opens in the
default browser. The later Rust Driver (Tauri) can serve the same web/ folder against the same API.

API (JSON; every call needs the X-Watch-Key header):
  GET  /api/state                 status strip, sign-in, sessions, chips, presets, voice
  GET  /api/stream?session=LV-…   the session stream (live.line, replies, show steps), as Studio's Live panel
  POST /api/signin                read the nodach_session value from the clipboard (Live's saved sign-in)
  POST /api/session {id}          pick a session        POST /api/session/start   start one (owners)
  POST /api/send {text, chip, opts, attach, picture}   one live.line (attach: a Watch event id)
  POST /api/capture {mode, preset}                      point | area | markup  -> the saved pointer.v1 event
  GET  /api/keepout  POST /api/keepout/pick  /add {entry}  /remove {id}  GET /api/windows
  GET  /api/shots                 earlier Watch captures (for 'Looks off' > compare with an earlier one)
  POST /api/reference             pick a reference or design image for 'Looks off' (kept on this PC)
  POST /api/card-markup {carousel, card, marks, size}  mark up a draft card (U9)
  POST /api/route {carousel, route, card, text, attach}  drafts | gate | automation as a [for-claude] line (U10)
  GET  /api/shot?id=  GET /api/plain?id=   a capture's picture (Enlarge) / its elements as plain actions (U15)
  POST /api/session/end {lesson}  end the session; lesson: keep it in Studio as a replayable lesson (U14)
  POST /api/clip                  keep the last 10 s (Gate's clip)        POST /api/stop   Pause all
  POST /api/mic {action: start|stop, ...send fields}    click to talk, click to send
  POST /api/ontop {on}            POST /api/settings {stuck}   ('looks like you're stuck' offers, off by default)
  POST /api/export {id, note}     a capture as a self-contained HTML page + zip in nodach-watch/exports
  POST /api/ui {…}                the page reports what it shows (chip, attachment, picture, visible controls)
  POST /api/test/select_area {x1,y1,x2,y2}  POST /api/test/point {x,y}  POST /api/test/state
                                  Claude's test hook (decision 77a b), called only by the Desktop worker, which reads
                                  the port and key from %USERPROFILE%\\nodach\\run\\watch.json. Same pipeline as a
                                  finished overlay drag/click (only the overlay is skipped); shown in the chat as a
                                  grey 'test input from Claude' note. Refused while Watch is off, the window isn't
                                  open, or the area touches a kept-out window.
Nothing here prints or stores the sign-in value except Live's own session file; no email addresses are shown.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watch_core as core   # noqa: E402  (puts app\gate, app\live, app\shell on the path)
import gate_core            # noqa: E402
import live_core            # noqa: E402

WEB = HERE / "web"
HOME = Path(os.environ.get("NODACH_WATCH_HOME", str(Path.home() / "nodach-watch")))
GATE_HOME = Path(os.environ.get("NODACH_GATE_HOME", str(Path.home() / "nodach-gate")))
DESKTOP_ROOT = Path(os.environ.get("NODACH_DESKTOP_HOME", str(Path.home() / "nodach")))
HUBS = live_core.HUBS
PICTURE_MAX = 10 * 1024 * 1024


def read_json(p: Path, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def write_json(p: Path, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


class Watch:
    """Everything the API does, testable without HTTP (hub, capture and voice can be swapped for fakes)."""

    def __init__(self, home: Path = HOME, gate_home: Path = GATE_HOME, root: Path = DESKTOP_ROOT, hub_factory=None,
                 capture=None, token_store=None, voice=None, hooks=None, test_capture=None):
        self.home, self.gate_home, self.root = Path(home), Path(gate_home), Path(root)
        self.home.mkdir(parents=True, exist_ok=True)
        self.settings = read_json(self.home / "settings.json", {}) or {}
        self.settings.setdefault("hub", "staging")
        self.settings.setdefault("on_top", True)
        self.settings.setdefault("stuck", dict(core.STUCK_DEFAULTS))   # U1b: off by default
        self.last_offer = None
        self.hub_factory = hub_factory or _live_hub
        self.capture_fn = capture
        self.test_capture_fn = test_capture
        self.capturing = False             # a capture is running (the app doesn't restart itself mid-capture)
        self.test_last = None              # the latest test input, for the page to attach and note
        self.test_seq = 0
        self.chat_notes: list[dict] = []   # Watch's own grey rows (test inputs, a session ended for quiet), by session
        self.pending = None                # the last line sent, until a reply comes (the 'waiting' row)
        self.watch_since = time.time()     # when Watch was (last seen) turned on: older glitch clips are never offered
        self.ui, self.ui_t = {}, 0.0       # what the page last reported it shows
        self.tokens = token_store or _LiveTokens()
        self.voice = voice
        self.hooks = hooks or {}
        self.lock = threading.Lock()
        self._hub, self._me, self._docs, self._after, self._pulled = None, None, [], 0, 0.0
        self.activity: list[dict] = []

    # ------------------------------------------------------------ helpers
    def note(self, step: str, outcome: str, detail: str = ""):
        row = {"ts": core.iso(core.utcnow()), "step": step, "outcome": outcome, "detail": gate_core.scrub(detail)[:200]}
        self.activity.append(row)
        self.activity = self.activity[-100:]
        with open(self.home / "activity.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def save_settings(self):
        write_json(self.home / "settings.json", self.settings)

    def hub_url(self) -> str:
        return HUBS.get(self.settings.get("hub"), HUBS["staging"])

    def zones_path(self) -> Path:
        return self.gate_home / "zones.json"

    def zones(self) -> dict:
        return gate_core.load_zones(self.zones_path())

    def gate_state(self) -> dict:
        return read_json(self.gate_home / "state.json", {}) or {}

    def hub(self):
        if self._hub is None:
            tok = self.tokens.get(self.hub_url())
            if not tok:
                raise ApiError("Not signed in: copy your nodach_session value and click Sign in", 401)
            h = self.hub_factory(self.hub_url(), tok)
            try:
                self._me = h.me()
            except Exception as e:
                raise ApiError(f"Sign-in not accepted ({type(e).__name__}): sign in again", 401) from None
            self._hub = h
        return self._hub

    def me(self) -> dict:
        self.hub()
        return self._me

    def pull(self, force=False) -> list:
        """New shared-record events since the last pull (at most every 2 s)."""
        h = self.hub()
        if not force and time.time() - self._pulled < 2:
            return self._docs
        with self.lock:
            while True:
                r = h._req("GET", f"/studio/api/events?after={self._after}&limit=2000")
                self._docs += r.get("events") or []
                nxt = r.get("next", self._after)
                if nxt <= self._after:
                    break
                self._after = nxt
                if nxt >= r.get("total", 0):
                    break
            self._pulled = time.time()
        return self._docs

    # ------------------------------------------------------------ state
    def state(self) -> dict:
        st = self.gate_state()
        try:
            import desktop_core
            acting = desktop_core.acting_state(self.root)
        except Exception:
            acting = {"active": False}
        kept = len(core.keep_out_list(self.zones_path()))
        signed, role, sessions, err = False, None, [], ""
        try:
            me = self.me()
            signed, role = True, ("owner" if me.get("owner") else "member")
            sessions = core.session_list(self.pull(), me)
        except ApiError as e:
            err = str(e)
        except Exception as e:
            err = f"hub: {type(e).__name__}"
        live = [s for s in sessions if s["state"] == "live"]
        if self.settings.get("session") not in {s["id"] for s in sessions} and live:
            self.settings["session"] = live[0]["id"]
        strip = core.status_strip(watch=bool(st.get("watch")), paused=bool(st.get("paused")), acting=acting, kept_out=kept,
                                  signed_in=signed, session=self.settings.get("session"), privacy=self.privacy())
        return {"version": core.VERSION, "strip": strip, "role": role, "hub": self.settings["hub"], "error": err,
                "sessions": sessions[:20], "session": self.settings.get("session"), "on_top": bool(self.settings.get("on_top")),
                "chips": core.CHIPS, "presets": {k: {"label": v["label"], "hint": v["hint"]} for k, v in core.PRESETS.items()},
                "compare": core.COMPARE, "save": core.SAVE, "voice": self.voice_status(),
                "audience": core.audience_for(self._me) if signed else None,
                "stuck": {"on": bool(self.settings["stuck"].get("on"))}, "offer": self.offer(),
                "test": self.test_public()}

    def privacy(self) -> str | None:
        """U16: a sign-in page or payment form in front pauses Watch (Gate refuses; captures black it out)."""
        fg = self.hooks.get("foreground")
        if fg is None:
            try:
                import gate_win
                fg = gate_win.foreground if gate_win.AVAILABLE else (lambda: {})
            except Exception:
                fg = lambda: {}   # noqa: E731
        try:
            return gate_core.privacy_moment((fg() or {}).get("title") or "")
        except Exception:
            return None

    def plain(self, eid: str) -> dict:
        e = self.find_event(eid)
        if not e:
            raise ApiError("That capture isn't on this PC any more", 404)
        return {"actions": core.plain_actions(e)}

    def shot_bytes(self, eid: str) -> bytes:
        e = self.find_event(eid)
        if not e or not e.get("screenshot") or e.get("kept_out"):
            raise ApiError("No picture for that capture", 404)
        try:
            return Path(e["screenshot"]).read_bytes()
        except OSError:
            raise ApiError("The picture isn't on this PC any more", 404) from None

    def end_session(self, lesson: bool = False) -> dict:
        """End the session (owners), and if he chose to, keep it in Studio as a replayable lesson (U14)."""
        me, sid = self.me(), self.settings.get("session")
        if not sid:
            raise ApiError("No session to end")
        if not me.get("owner"):
            raise ApiError("Only an owner can end a session", 403)
        h, t = self.hub(), core.utcnow()
        out = {"ended": sid}
        if lesson:
            ev = core.lesson_event(sid, me, t, self.stream(sid))
            h.post(ev)
            out["lesson"] = ev["body"]["id"]
        self._end(sid, me, "from the Watch window")
        self.pull(force=True)
        self.note("session", "ok", f"ended {sid}" + (f", kept as lesson {out['lesson']}" if lesson else ""))
        return out

    def gate_log(self, n: int = 200) -> list:
        out = []
        try:
            lines = (self.gate_home / "actions.jsonl").read_text(encoding="utf-8").splitlines()[-n:]
        except OSError:
            return out
        for line in lines:
            try:
                e = json.loads(line)
                e["_t"] = dt.datetime.fromisoformat(str(e.get("ts")).replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                continue
            out.append(e)
        return out

    def offer(self, now: float | None = None):
        """U1b: 'looks like you're stuck' (Settings toggle, off by default)."""
        now = now or time.time()
        if not self.gate_state().get("watch"):
            self.watch_since = None
            return None
        if self.watch_since is None:
            self.watch_since = now
        log = self.gate_log()
        asked = self.settings.setdefault("glitch_asked", {})
        o = core.glitch_offer(log, asked, now, since=self.watch_since)        # U4: always on, at most once per app per hour
        if o:
            self.save_settings()
        else:
            o = core.stuck_offer(log, now, self.settings.get("stuck"), self.last_offer)
        if o:
            self.last_offer = now
            self.note("offer", "info", f"{o['reason']}: {o['detail']}")
        return o

    def set_settings(self, body: dict) -> dict:
        if "stuck" in body:
            self.settings["stuck"] = dict(self.settings.get("stuck") or core.STUCK_DEFAULTS, on=bool(body["stuck"]))
        self.save_settings()
        return {"stuck": {"on": bool(self.settings["stuck"]["on"])}}

    def export(self, eid: str, note: str = "") -> dict:
        """U2b (1): keep a capture as a self-contained page + zip (to watch back, or send to a vendor)."""
        e = self.find_event(eid)
        if not e:
            raise ApiError("That capture isn't on this PC any more", 404)
        if e.get("kept_out"):
            raise ApiError("That capture landed on a kept-out window: nothing to export")
        png = None
        if e.get("screenshot"):
            try:
                png = Path(e["screenshot"]).read_bytes()
            except OSError:
                png = None
        r = core.export_bundle(e, png, self.home / "exports", note=note)
        self.note("export", "ok", f"{eid} exported")
        fn = self.hooks.get("open_folder")
        if fn:
            fn(self.home / "exports")
        return {"html": Path(r["html"]).name, "zip": Path(r["zip"]).name, "folder": "nodach-watch/exports"}

    def chat_note(self, text: str, session: str | None = None, kind: str = "note"):
        """A grey row from Watch itself in the chat (SC-golden-looksoff-1 #6: the test-input note didn't show)."""
        t = core.utcnow()
        self.chat_notes.append({"id": f"wn-{len(self.chat_notes) + 1}", "ts": core.iso(t), "time": core.iso(t)[11:19], "kind": kind,
                                "who": "Watch", "text": str(text)[:300], "words": "", "via": None,
                                "session": session or self.settings.get("session")})
        self.chat_notes = self.chat_notes[-50:]

    def stream(self, session: str | None) -> list:
        session = session or self.settings.get("session")
        if not session:
            return []
        docs = self.pull()
        me_id = (self._me or {}).get("id")
        rows = core.stream_rows(docs, session, me_id)
        rows += [dict(n) for n in self.chat_notes if n.get("session") == session]
        rows.sort(key=lambda r: r.get("ts") or "")
        if self.pending and self.pending.get("session") == session:
            w = core.wait_row(self.pending, rows, docs, time.time())
            if w:
                rows.append(w)
            else:
                self.pending = None
        return rows[-200:]

    def _end(self, sid: str, me: dict, why: str):
        h, t = self.hub(), core.utcnow()
        ts = core.iso(t)
        au = live_core.author(me)
        h.post({"ts": ts, "kind": "item.edit", "item": sid, "branch": "main", "author": au,
                "body": {"live": {"ended": ts}, "body": f"Live session ended {ts[:16].replace('T', ' ')} UTC {why}."}})
        h.post({"ts": ts, "kind": "status", "item": sid, "branch": "main", "author": au, "body": {"status": "open"}})

    def retire_if_idle(self, session: str, me: dict) -> str:
        """SC-golden-looksoff-1 #2: a session with no activity for idle_end_minutes (default 30) ends itself on the next
        send, and the line goes to a fresh session (owners). Returns the session to send to."""
        mins = core.idle_minutes(self.settings)
        docs = self.pull(force=True)
        rows = core.session_list(docs, me)
        st = next((r["state"] for r in rows if r["id"] == session), None)
        if st != "live" or not core.is_idle(docs, session, time.time(), mins):
            return session
        if not me.get("owner"):
            raise ApiError(f"This session has been quiet for {mins}+ minutes: ask the owner to start a new one", 409)
        self._end(session, me, f"after {mins} quiet minutes (Watch)")
        self.note("session", "ok", f"ended {session} after {mins} quiet minutes")
        new = self.start_session()["session"]
        self.chat_note(f"{session} had been quiet for {mins}+ minutes, so it ended; this is a new session.", new)
        return new

    # ------------------------------------------------------------ sign-in and sessions
    def signin(self) -> dict:
        ok = self.tokens.from_clipboard(self.hub_url())
        self._hub = None
        if not ok:
            raise ApiError("The clipboard doesn't hold a nodach_session value (it looks like name.numbers.long-code)")
        self.me()
        self.note("sign-in", "ok", f"signed in on {self.settings['hub']}")
        return {"ok": True}

    def set_session(self, sid: str) -> dict:
        self.settings["session"] = sid
        self.save_settings()
        return {"session": sid}

    def start_session(self) -> dict:
        me = self.me()
        if not me.get("owner"):
            raise ApiError("Only an owner can start a session", 403)
        ev = live_core.session_event(me, core.utcnow(), title="")
        ev["body"]["live"]["via"] = "watch"
        self.hub().post(ev)
        self.settings["session"] = ev["body"]["id"]
        self.save_settings()
        self.pull(force=True)
        self.note("session", "ok", f"started {ev['body']['id']}")
        return {"session": ev["body"]["id"]}

    # ------------------------------------------------------------ captures
    def find_event(self, eid: str) -> dict | None:
        try:
            for line in (self.home / "events.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("id") == eid:
                    return e
        except OSError:
            return None
        return None

    def shots(self, n: int = 20) -> list:
        out = []
        try:
            lines = (self.home / "events.jsonl").read_text(encoding="utf-8").splitlines()[-200:]
        except OSError:
            lines = []
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("screenshot") and not e.get("kept_out"):
                out.append({"id": e["id"], "kind": e.get("kind"), "at": e.get("at"), "words": core.point_words(e)})
            if len(out) >= n:
                break
        return out

    def _hidden(self, fn):
        hide, show = self.hooks.get("hide"), self.hooks.get("show")
        self.capturing = True
        try:
            if hide:
                hide()
                time.sleep(0.25)
            try:
                return fn()
            finally:
                if show:
                    show()
        finally:
            self.capturing = False

    def capture(self, mode: str, preset: str | None = None) -> dict:
        if mode not in ("point", "area", "markup", "pick"):
            raise ApiError("mode must be point, area, markup or pick")
        cap = self.capture_fn or _win_capture
        r = self._hidden(lambda: cap(mode, self.zones(), preset))
        if r.get("error"):
            raise ApiError(r["error"])
        if r.get("cancelled"):
            return {"cancelled": True}
        if "event" in r:
            e = r["event"]
            self.note("capture", "ok", f"{mode}: {core.point_words(e)}")
            return {"event": {"id": e["id"], "kind": e["kind"], "words": core.point_words(e), "kept_out": e.get("kept_out"),
                              "picture": bool(e.get("screenshot")), "preset": e.get("preset")}}
        return r

    # ------------------------------------------------------------ Claude's test hook (decision 77a b)
    def window_open(self) -> bool:
        fn = self.hooks.get("visible")
        if fn is None:
            return True          # browser mode: no window to ask
        try:
            return bool(fn())
        except Exception:
            return False

    def test_public(self):
        t = self.test_last
        if not t:
            return None
        return dict(t, age_s=round(time.time() - t["t"], 1))

    def test_input(self, action: str, args: dict | None = None) -> dict:
        """Run a test input exactly as a finished overlay drag/click would (crop, UI Automation elements inside,
        kept-out redaction, attach to the next line); only the overlay is skipped. 'state' reads the UI state."""
        if action not in core.TEST_ACTIONS:
            raise ApiError(f"action must be one of {', '.join(core.TEST_ACTIONS)}")
        if not self.gate_state().get("watch"):
            raise ApiError("Watch is off: Nowed turns it on in Nodach Desktop", 409)
        if not self.window_open():
            raise ApiError("The Watch window isn't open (it's hidden or closed)", 409)
        if action == "state":
            return self.ui_state()
        try:
            mode, got = core.test_target(action, args or {})
        except ValueError as e:
            raise ApiError(str(e)) from None
        if self.capturing:
            raise ApiError("A capture is already running in the Watch window", 409)
        zones = self.zones()
        why = core.test_refusal(mode, got, self._test_windows(), zones)
        if why:
            self.note("test-input", "refused", why)
            raise ApiError(f"Refused: {why}", 403)
        cap = self.test_capture_fn or _win_test_capture
        r = self._hidden(lambda: cap(mode, zones, got))
        if r.get("error"):
            raise ApiError(r["error"])
        if r.get("cancelled") or "event" not in r:
            raise ApiError("The capture didn't finish")
        e = r["event"]
        ev = {"id": e["id"], "kind": e["kind"], "words": core.point_words(e), "kept_out": e.get("kept_out"),
              "picture": bool(e.get("screenshot")), "preset": e.get("preset")}
        note = core.test_note(action, got)
        self.test_seq += 1
        self.test_last = {"seq": self.test_seq, "action": action, "note": note, "event": ev, "at": core.iso(core.utcnow()), "t": time.time()}
        self.note("test-input", "ok", f"{note}: {ev['words']}")
        self.chat_note(note[:1].upper() + note[1:])
        return {"event": ev, "seq": self.test_seq, "note": note,
                "elements": [x.get("name") for x in (e.get("elements") or [])][:40] if mode == "area" else None}

    def _test_windows(self):
        fn = self.hooks.get("windows")
        if fn:
            return fn()
        try:
            import watch_win
            return watch_win.windows()
        except Exception:
            return []

    def report_ui(self, body: dict) -> dict:
        """The page tells the server what it shows, so Claude's 'state' can read it (small and capped)."""
        ui = {}
        for k in ("chip", "compare", "attach", "picture", "text", "controls", "more", "panels", "error", "session", "test_seq"):
            if k in body:
                ui[k] = body[k]
        raw = json.dumps(ui, ensure_ascii=False)
        if len(raw) > 20000:
            raise ApiError("ui state too large")
        self.ui, self.ui_t = ui, time.time()
        return {"ok": True}

    def ui_state(self) -> dict:
        rows = []
        try:
            rows = self.stream(self.settings.get("session"))[-5:]
        except Exception as e:
            rows = [{"error": f"stream: {type(e).__name__}"}]
        chat = [{"time": r.get("time"), "kind": r.get("kind"), "who": r.get("who"), "text": str(r.get("text") or "")[:300],
                 "words": r.get("words") or ""} for r in rows]
        return {"ui": self.ui, "ui_age_s": round(time.time() - self.ui_t, 1) if self.ui_t else None,
                "session": self.settings.get("session"), "chat_last5": chat, "window_open": self.window_open(),
                "capturing": self.capturing, "last_test": self.test_public(), "version": core.VERSION}

    def reference(self, path: str | None = None) -> dict:
        """'Looks off' > compare with a reference or design image: kept on this PC, only its name and hash go out."""
        path = path or _ask_file()
        if not path:
            return {"cancelled": True}
        p = Path(path)
        if core.SECRET_DIR in str(p).lower() or core.never_reason(self.zones(), "", str(p)):
            raise ApiError("That file is in a kept-out or secret place: Watch won't use it")
        data = p.read_bytes()
        ref = {"kind": "file", "name": p.name[:120], "sha256": hashlib.sha256(data).hexdigest(), "at": core.iso(core.utcnow())}
        refs = read_json(self.home / "references.json", []) or []
        refs.append(dict(ref, path=str(p)))         # the path stays local
        write_json(self.home / "references.json", refs[-50:])
        ref["id"] = "REF-" + ref["sha256"][:10]
        return {"reference": ref}

    def _card(self, carousel: str, card_id: str) -> dict:
        for d in self.pull(force=True):
            if d.get("doc_id") == carousel:
                c = core.carousel_from(((d.get("event") or {}).get("body") or {}).get("carousel"), carousel)
                for k in (c or {}).get("cards") or []:
                    if k["id"] == card_id:
                        return k
        raise ApiError("That card isn't in the session any more", 404)

    def card_markup(self, carousel: str, card_id: str, marks, size=None) -> dict:
        """U9: mark up on a carousel card; saved like a capture, attaches to the next line."""
        card = self._card(carousel, card_id)
        try:
            e = core.card_markup_event(core.utcnow(), carousel=carousel, card=card, marks=marks, size=size)
        except (ValueError, KeyError, TypeError) as err:
            raise ApiError(f"mark-up not understood ({err})") from None
        with open(self.home / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return {"event": {"id": e["id"], "kind": e["kind"], "words": core.point_words(e), "picture": False, "preset": None}}

    def route(self, carousel: str, route: str, card: str | None = None, text: str = "", attach: str | None = None) -> dict:
        """U10: post the chosen follow-on as a [for-claude] line (execution is a TODO in v0)."""
        session = self.settings.get("session")
        if not session:
            raise ApiError("No session: pick one or click Start session")
        try:
            line, fields = core.route_line(route, carousel, card, text)
        except ValueError as e:
            raise ApiError(str(e)) from None
        point = core.shareable(self.find_event(attach)) if attach else None
        ev = core.line_event(session, self.me(), line, core.utcnow(), point=point, watch=fields)
        did = self.hub().post(ev)
        self.pull(force=True)
        self.pending = {"session": session, "line": did, "ts": ev["ts"], "t": time.time()}
        self.note("send", "ok", f"route {route} for {carousel}")
        return {"sent": did, "session": session}

    # ------------------------------------------------------------ keep-out
    def keepout_list(self) -> list:
        return core.keep_out_list(self.zones_path())

    def keepout_add(self, entry: dict) -> dict:
        kind = entry.get("kind", "window")
        e = gate_core.keep_out_entry(kind, process=entry.get("process", ""), title=entry.get("title", ""),
                                     path=entry.get("path", ""), words=entry.get("title_words"))
        added, changed = core.keep_out_add(self.zones_path(), e)
        self.note("keep-out", "ok", f"added {gate_core._entry_words(e)}" if changed else "already kept out")
        return {"entry": added, "changed": changed, "list": self.keepout_list()}

    def keepout_remove(self, eid: str) -> dict:
        gone, changed = core.keep_out_remove(self.zones_path(), eid)
        if not gone:
            raise ApiError("No keep-out entry with that id", 404)
        self.note("keep-out", "ok", f"removed {eid}")
        return {"removed": gone, "list": self.keepout_list()}

    def windows(self) -> list:
        try:
            import watch_win
            ws = watch_win.windows()
        except Exception:
            ws = []
        return core.window_list(ws, self.zones())

    # ------------------------------------------------------------ sending
    def upload_picture(self, path: str) -> dict:
        """The picture into the owner-only Private tier (40 KB chunks, like Gate); returns the reference."""
        p = Path(path)
        me = self.me()
        if not me.get("owner"):
            return {"name": p.name, "local": True}
        try:
            data = p.read_bytes()
        except OSError:
            return {"name": p.name, "local": True}
        if len(data) > PICTURE_MAX:
            return {"name": p.name, "local": True}
        sha = hashlib.sha256(data).hexdigest()
        ppath = gate_core.private_path(me.get("login", ""), "watch/files")
        parts = gate_core.file_chunks(data)
        t = core.utcnow()
        for i, b64 in enumerate(parts):
            ev = gate_core.chunk_event(p.name, sha, i, len(parts), b64, t)
            ev["kind"] = "watch.file"
            self.hub()._req("POST", "/studio/api/private", {"path": ppath, "doc_id": "wf-" + sha[:40] + f"-{i:04d}", "event": ev})
        return {"name": p.name, "bytes": len(data), "sha256": sha, "private_path": ppath, "chunks": len(parts)}

    def send(self, text: str = "", chip: str | None = None, opts: dict | None = None, attach: str | None = None,
             picture: bool = False, via: str = "watch") -> dict:
        session = self.settings.get("session")
        if not session:
            raise ApiError("No session: pick one or click Start session")
        opts = dict(opts or {})
        if chip == "explain":           # U3b: from the signed-in profile, not a button
            opts["audience"] = core.audience_for(self.me())
        try:
            line, fields = core.compose_line(text, chip, opts)
        except ValueError as e:
            raise ApiError(str(e)) from None
        point = None
        if attach:
            e = self.find_event(attach)
            if not e:
                raise ApiError("That capture isn't on this PC any more")
            pic = None
            if picture and e.get("screenshot") and not e.get("kept_out"):
                try:
                    pic = self.upload_picture(e["screenshot"])
                except Exception as err:
                    pic = {"name": Path(e["screenshot"]).name, "local": True}
                    self.note("send", "failed", f"picture kept on this PC ({type(err).__name__})")
            point = core.shareable(e, pic)
        if not line.strip() and not point:
            raise ApiError("Nothing to send: type a line or add a point")
        me = self.me()
        session = self.retire_if_idle(session, me)
        rows = core.session_list(self.pull(force=True), me)
        tgt = live_core.send_target(rows, session)
        if tgt["action"] == "switch":
            self.settings["session"] = session = tgt["to"]
            self.save_settings()
        elif tgt["action"] == "ask":
            raise ApiError("This session has ended: pick or start a live session", 409)
        if chip == "report":            # U5: reproduce or not, and the incident template when it can't be undone
            fields["reproduce_check"] = core.may_reproduce(fields, self.zones(), point, line)
            if not fields["reproduce_check"]["allowed"]:
                fields["reproduce"] = "never"
            if fields.get("irreversible"):
                line = (line + "\n" + core.incident_text(fields)).strip()[:2000]
        ev = core.line_event(session, me, line, core.utcnow(), point=point, watch=fields or None, via=via)
        did = self.hub().post(ev)
        task = live_core.parse_task(line)
        if task and me.get("owner"):
            self.hub().post(live_core.task_event(session, did, task, me, core.utcnow()))
        self.pull(force=True)
        self.pending = {"session": session, "line": did, "ts": ev["ts"], "t": time.time()}
        self.note("send", "ok", f"{len(line)} chars" + (" + point" if point else "") + (f" [{chip}]" if chip else ""))
        with open(self.home / "lines.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ev["ts"], "session": session, "doc_id": did, "text": line, "chip": chip,
                                "attach": attach, "picture": bool(point and point.get("picture"))}, ensure_ascii=False) + "\n")
        return {"sent": did, "session": session, "switched": tgt["action"] == "switch"}

    # ------------------------------------------------------------ Gate controls
    def keep_clip(self) -> dict:
        st = self.gate_state()
        st["keep_clip_req"] = int(st.get("keep_clip_req") or 0) + 1
        write_json(self.gate_home / "state.json", st)
        self.note("clip", "ok", "asked Gate to keep the last 10 s")
        return {"ok": True, "ref": {"kind": "clip", "id": f"CLIP-{st['keep_clip_req']}", "at": core.iso(core.utcnow())}}

    def stop(self) -> dict:
        try:
            import desktop_core
            desktop_core.set_gate_paused(True, self.gate_home)
        except Exception:
            st = self.gate_state()
            st.update(paused=True, paused_changed=core.iso(core.utcnow()))
            write_json(self.gate_home / "state.json", st)
        self.note("stop", "ok", "Pause all: every Gate action is refused until Resume")
        return {"paused": True}

    def on_top(self, on: bool) -> dict:
        self.settings["on_top"] = bool(on)
        self.save_settings()
        fn = self.hooks.get("on_top")
        if fn:
            fn(bool(on))
        return {"on_top": bool(on)}

    # ------------------------------------------------------------ voice
    def voice_status(self) -> str:
        if self.voice is None:
            self.voice = _Voice()
        return self.voice.status()

    def mic(self, action: str, **send_fields) -> dict:
        if self.voice is None:
            self.voice = _Voice()
        if action == "start":
            self.voice.start()
            return {"listening": True}
        text = self.voice.stop()
        if not text:
            self.note("record", "empty speech", "nothing heard")
            return {"listening": False, "text": ""}
        if send_fields.pop("send", True):
            r = self.send(text=(send_fields.pop("text", "") + " " + text).strip(), via="voice", **send_fields)
            return {"listening": False, "text": text, **r}
        return {"listening": False, "text": text}


# ---------------------------------------------------------------- real-world pieces (swapped in tests)
def _live_hub(url, token):
    import live_client
    return live_client.Hub(url, token)


class _LiveTokens:
    """Live's saved sign-in (%USERPROFILE%\\nodach-live\\session-<hub>.txt): shared with the Live window."""

    def get(self, url):
        import live_client
        return live_client.stored_token(url)

    def from_clipboard(self, url) -> bool:
        import live_client
        t = live_core.clean_token(live_client._clipboard())
        if not t:
            return False
        live_client.save_token(url, t)
        return True


def _win_capture(mode, zones, preset):
    import watch_win
    return watch_win.capture(mode, zones, preset)


def _win_test_capture(mode, zones, got):
    import watch_win
    return watch_win.capture(mode, zones, None, overlay=lambda *a, **k: dict(got))


def _ask_file() -> str:
    code = ("import tkinter as t,tkinter.filedialog as f;r=t.Tk();r.withdraw();r.attributes('-topmost',True);"
            "print(f.askopenfilename(title='Reference or design image',filetypes=[('Images','*.png *.jpg *.jpeg *.gif *.bmp *.webp'),('All','*.*')]))")
    try:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600)
        return (out.stdout or "").strip()
    except Exception:
        return ""


class _Voice:
    """Click to talk, click to send: the microphone and Live's local speech model (faster-whisper on this PC)."""
    RATE = 16000

    def __init__(self):
        self.model, self.stream, self.buf, self.err = None, None, [], ""

    def status(self) -> str:
        try:
            import sounddevice  # noqa: F401
            import faster_whisper  # noqa: F401
        except Exception:
            return "not available (Live's voice packages aren't installed): type instead"
        return "listening" if self.stream else "ready"

    def start(self):
        import numpy as np  # noqa: F401
        import sounddevice as sd
        self.buf = []
        self.stream = sd.InputStream(samplerate=self.RATE, channels=1, dtype="float32",
                                     callback=lambda d, f, t, s: self.buf.append(d[:, 0].copy()))
        self.stream.start()

    def stop(self) -> str:
        import numpy as np
        import live_client
        if not self.stream:
            return ""
        self.stream.stop()
        self.stream.close()
        self.stream = None
        if not self.buf:
            return ""
        audio = np.concatenate(self.buf)
        if len(audio) < self.RATE * 0.3:
            return ""
        if self.model is None:
            self.model, _ = live_client.load_model(os.environ.get("NODACH_LIVE_MODEL", "base"), say=lambda *_: None)
        return live_client.transcribe(self.model, audio)


# ---------------------------------------------------------------- HTTP
ROUTES_GET = {"/api/state", "/api/stream", "/api/keepout", "/api/windows", "/api/shots"}


def dispatch(w: Watch, method: str, path: str, query: dict, body: dict):
    q = {k: v[0] for k, v in query.items()}
    if method == "GET":
        if path == "/api/state":
            return w.state()
        if path == "/api/stream":
            return {"rows": w.stream(q.get("session"))}
        if path == "/api/keepout":
            return {"list": w.keepout_list()}
        if path == "/api/windows":
            return {"windows": w.windows()}
        if path == "/api/shots":
            return {"shots": w.shots()}
        if path == "/api/plain":
            return w.plain(q.get("id", ""))
    if method == "POST":
        if path == "/api/signin":
            return w.signin()
        if path == "/api/session":
            return w.set_session(str(body.get("id") or ""))
        if path == "/api/session/start":
            return w.start_session()
        if path == "/api/send":
            return w.send(text=body.get("text", ""), chip=body.get("chip"), opts=body.get("opts"),
                          attach=body.get("attach"), picture=bool(body.get("picture")))
        if path == "/api/capture":
            return w.capture(str(body.get("mode") or ""), body.get("preset"))
        if path == "/api/keepout/pick":
            return w.capture("pick")
        if path == "/api/keepout/add":
            try:
                return w.keepout_add(body.get("entry") or {})
            except ValueError as e:
                raise ApiError(str(e)) from None
        if path == "/api/keepout/remove":
            return w.keepout_remove(str(body.get("id") or ""))
        if path == "/api/reference":
            return w.reference(body.get("path"))
        if path == "/api/session/end":
            return w.end_session(bool(body.get("lesson")))
        if path == "/api/card-markup":
            return w.card_markup(str(body.get("carousel") or ""), str(body.get("card") or ""), body.get("marks") or [], body.get("size"))
        if path == "/api/route":
            return w.route(str(body.get("carousel") or ""), str(body.get("route") or ""), body.get("card"), body.get("text") or "",
                           body.get("attach"))
        if path == "/api/settings":
            return w.set_settings(body)
        if path == "/api/export":
            return w.export(str(body.get("id") or ""), str(body.get("note") or ""))
        if path == "/api/clip":
            return w.keep_clip()
        if path == "/api/stop":
            return w.stop()
        if path == "/api/ontop":
            return w.on_top(bool(body.get("on")))
        if path == "/api/ui":
            return w.report_ui(body)
        if path.startswith("/api/test/"):
            return w.test_input(path[len("/api/test/"):], body)
        if path == "/api/mic":
            b = dict(body)
            return w.mic(str(b.pop("action", "stop")), **{k: b[k] for k in ("text", "chip", "opts", "attach", "picture", "send") if k in b})
    raise ApiError("not found", 404)


def make_handler(w: Watch, key: str, port_ref: dict):
    class H(BaseHTTPRequestHandler):
        server_version = "nodach-watch"

        def log_message(self, *a):   # no request log on stderr (it could hold session ids)
            pass

        def _send(self, code, data: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; frame-src 'self'")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _ok_host(self) -> bool:
            return self.headers.get("Host") in (f"127.0.0.1:{port_ref['port']}", f"localhost:{port_ref['port']}")

        def _api(self, method):
            u = urllib.parse.urlparse(self.path)
            if not self._ok_host() or not secrets.compare_digest(self.headers.get("X-Watch-Key", ""), key):
                return self._send(403, b'{"error":"forbidden"}')
            body = {}
            if method == "POST":
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    return self._send(415, b'{"error":"json only"}')
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(min(n, 1_000_000)) or b"{}")
                except ValueError:
                    return self._send(400, b'{"error":"bad json"}')
            if u.path == "/api/shot" and method == "GET":     # the picture itself, for Enlarge (U15); stays local
                try:
                    return self._send(200, w.shot_bytes(urllib.parse.parse_qs(u.query).get("id", [""])[0]), "image/png")
                except ApiError as e:
                    return self._send(e.code, json.dumps({"error": str(e)}).encode())
            try:
                out = dispatch(w, method, u.path, urllib.parse.parse_qs(u.query), body)
                code = 200
            except ApiError as e:
                out, code = {"error": str(e)}, e.code
            except Exception as e:   # never leave the UI without an answer
                out, code = {"error": f"{type(e).__name__}: {gate_core.scrub(str(e))[:200]}"}, 500
            self._send(code, json.dumps(out, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path.startswith("/api/"):
                return self._api("GET")
            if not self._ok_host():
                return self._send(403, b"forbidden", "text/plain")
            name = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            p = (WEB / name).resolve()
            if WEB.resolve() not in p.parents or not p.is_file():
                return self._send(404, b"not found", "text/plain")
            self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path.startswith("/api/"):
                return self._api("POST")
            self._send(404, b"not found", "text/plain")
    return H


def serve(w: Watch, port: int = 0):
    """Start the server on 127.0.0.1 (a free port unless given). Returns (server, url with the key)."""
    key = secrets.token_urlsafe(24)
    ref = {"port": port}
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(w, key, ref))
    ref["port"] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{ref['port']}/#key={key}", key
