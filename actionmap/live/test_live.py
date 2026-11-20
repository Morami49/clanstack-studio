"""Tests for the Nodach Live client's pure logic (no microphone, keyboard or network).

Run: python -m pytest actionmap/live/test_live.py   (or python actionmap/live/test_live.py)
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import live_core as core  # noqa: E402

T = dt.datetime(2026, 11, 19, 12, 30, 45, 123000, tzinfo=dt.timezone.utc)
OWNER = {"login": "Morami49", "id": "github:Morami49", "owner": True}
MEMBER = {"login": "email:0123456789abcdef", "id": "email:email:0123456789abcdef", "owner": False}
STUDIO_HTML = HERE.parent.parent / "studio" / "index.html"


def test_task_lines():
    assert core.parse_task("task: add a count badge") == {"kind": "task", "title": "add a count badge"}
    assert core.parse_task("  Build: the supplier page.") == {"kind": "build", "title": "the supplier page"}
    assert core.parse_task("Task, fix the login") == {"kind": "task", "title": "fix the login"}   # spoken colon written as a comma
    assert core.parse_task("TASK — rename the tab") == {"kind": "task", "title": "rename the tab"}
    assert core.parse_task("task:") is None
    assert core.parse_task("the task: is this") is None
    assert core.parse_task("taskbar is hidden") is None
    assert core.parse_task("building things") is None
    assert core.parse_task(None) is None


def test_task_rule_matches_studio():
    """The client and the Studio panel must agree on what a task line is."""
    html = STUDIO_HTML.read_text(encoding="utf-8")
    m = re.search(r"const LIVE_TASK = /(.+?)/i;", html)
    assert m, "Studio's LIVE_TASK not found"
    js = m.group(1).replace("\\u2013", "\u2013").replace("\\u2014", "\u2014").replace("[\\s\\S]", ".")
    py = re.compile(js, re.I | re.S)
    for s in ["task: a", "Build. b", "taskbar", "x task: y", "Task,c", "build —d"]:
        assert bool(py.match(s)) == bool(core.TASK_RE.match(s)), s


def test_clean_text_drops_whisper_noise():
    assert core.clean_text("  [BLANK_AUDIO]  hello   (music) there *coughs* ") == "hello there"
    assert core.clean_text("x" * 5000) == "x" * core.MAX_TEXT
    assert core.clean_text(None) == ""


def test_ids_and_time():
    assert core.iso(T) == "2026-11-19T12:30:45.123Z"
    assert re.fullmatch(r"LV-261119-123045-[0-9a-f]{4}", core.stamp("LV", T))
    d = core.doc_id()
    assert re.fullmatch(r"[a-z0-9]+", d) and not d.startswith("hub-") and len(d) <= 100
    assert core.doc_id() != d


def test_line_event_shape():
    p = {"schema": "pointer.v1", "kind": "pointer.desktop", "id": "PE-1", "app": "EXCEL.EXE", "element": {"type": "ButtonControl", "name": "Sort"}}
    e = core.line_event("LV-261119-123045-abcd", OWNER, " hello  there ", T, "voice", p)
    assert e["kind"] == "live.line" and e["item"] == "LV-261119-123045-abcd" and e["ts"] == "2026-11-19T12:30:45.123Z" and e["branch"] == "main"
    assert e["body"] == {"session": "LV-261119-123045-abcd", "speaker": "Nowed", "text": "hello there", "ts": e["ts"], "via": "voice", "point": p}
    assert e["author"] == {"id": "github:Morami49", "role": "owner", "label": "Nowed"}
    m = core.line_event("LV-x", MEMBER, "hi", T)
    assert m["body"]["speaker"] == "Member" and "point" not in m["body"] and m["author"]["role"] == "member"
    assert "@" not in json.dumps(m)   # never an address


def test_task_and_session_events():
    t = core.task_event("LV-x", "lvabc", {"kind": "build", "title": "a supplier page"}, OWNER, T)
    b = t["body"]
    assert t["kind"] == "item.create" and t["item"] is None
    assert b["type"] == "change" and b["status"] == "draft" and b["refs"] == ["LV-x"] and b["title"] == "Build: a supplier page"
    assert b["meta"] == {"kind": "build", "from_session": "LV-x", "from_line": "lvabc"} and b["id"].startswith("TK-261119-")
    s = core.session_event(OWNER, T)
    assert s["body"]["status"] == "live" and s["body"]["source"] == "live" and s["body"]["live"]["schema"] == "live.v1"
    assert s["body"]["id"].startswith("LV-261119-123045-")


def pe(pid, at, mode="point", **over):
    e = {"schema": "pointer.v1", "id": pid, "kind": "pointer.desktop", "at": at.isoformat(), "mode": mode,
         "element": {"type": "ButtonControl", "name": "Send", "automation_id": "x", "class_name": "Button", "rect": {}},
         "window": {"title": "Inbox - private subject", "class_name": "W"}, "process": {"pid": 9, "name": "claude.exe"},
         "screenshot": "C:\\Users\\me\\nodach-pointer\\shots\\x.png", "cursor": {"x": 1, "y": 2}, "note": "make it blue"}
    e.update(over)
    return json.dumps(e)


def test_latest_point_is_fresh_unused_and_a_point():
    lines = [pe("PE-old", T - dt.timedelta(minutes=5)), pe("PE-a", T - dt.timedelta(seconds=30)),
             pe("PE-batch", T - dt.timedelta(seconds=5), mode="batch-item"), "{half-written", pe("PE-b", T - dt.timedelta(seconds=10))]
    assert core.latest_point(lines, T)["id"] == "PE-b"
    assert core.latest_point(lines, T, used={"PE-b"})["id"] == "PE-a"
    assert core.latest_point(lines, T, used={"PE-a", "PE-b"}) is None
    assert core.latest_point([], T) is None


def test_shareable_point_keeps_private_things_on_the_pc():
    p = core.shareable_point(json.loads(pe("PE-a", T)))
    assert p == {"schema": "pointer.v1", "kind": "pointer.desktop", "id": "PE-a", "app": "claude.exe",
                 "element": {"type": "ButtonControl", "name": "Send"}, "note": "make it blue"}
    text = json.dumps(p)
    for leak in ("private subject", "shots", "cursor", "automation_id", "class_name"):
        assert leak not in text
    assert core.shareable_point({"schema": "other"}) is None and core.shareable_point(None) is None


def test_latest_live_session():
    def row(kind, item, body, who="github:Morami49", ts="2026-11-19T10:00:00.000Z"):
        return {"doc_id": "d" + ts + kind, "event": {"kind": kind, "item": item, "body": body, "ts": ts, "author": {"id": who}}}
    docs = [row("item.create", None, {"id": "LV-1", "source": "live", "status": "live"}, ts="2026-11-19T09:00:00.000Z"),
            row("item.create", None, {"id": "LV-2", "source": "live", "status": "live"}, ts="2026-11-19T10:00:00.000Z"),
            row("status", "LV-2", {"status": "open"}, ts="2026-11-19T11:00:00.000Z"),
            row("item.create", None, {"id": "LV-3", "source": "live", "status": "live"}, who="github:someone", ts="2026-11-19T12:00:00.000Z"),
            row("item.create", None, {"id": "SH-1", "source": "show", "status": "live"}, ts="2026-11-19T12:00:00.000Z")]
    assert core.latest_live_session(docs, "github:Morami49") == "LV-1"
    assert core.latest_live_session(docs[:1] + [row("status", "LV-1", {"status": "open"})], "github:Morami49") is None
    assert core.latest_live_session([], "github:Morami49") is None


def test_segments_cut_phrases_on_pauses():
    loud, quiet = 0.1, 0.0
    f = 30
    levels = [quiet] * 5 + [loud] * 20 + [quiet] * 30 + [loud] * 3 + [quiet] * 30 + [loud] * 15
    segs = core.segments(levels, 0.05, f, silence_ms=600, min_ms=300)
    assert segs == [(5, 25), (88, 103)]   # the 3-frame click (90 ms) is dropped; the open phrase at the end is kept
    assert core.segments([quiet] * 50, 0.05, f) == []


def test_client_imports_without_audio_packages():
    import live_client  # noqa: F401  (optional packages are guarded)
    assert live_client.core.VERSION == core.VERSION


def test_client_posts_line_then_draft_to_the_studio_api(tmp_path, monkeypatch, capsys):
    """Against a stand-in hub: the sign-in goes as the session cookie with the Studio header, a task line is posted
    as live.line and then a draft that points at that line's doc id, and the token is never printed."""
    import http.server
    import threading
    import live_client
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("content-length", 0))
            got.append({"path": self.path, "cookie": self.headers.get("cookie"), "csrf": self.headers.get("x-nodach-studio"),
                        "body": json.loads(self.rfile.read(n))})
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
            self.wfile.write(b'{"imported":1}')

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(live_client, "HOME", tmp_path)
    monkeypatch.setattr(live_client, "POINTER_EVENTS", tmp_path / "none.jsonl")
    hub = live_client.Hub(f"http://127.0.0.1:{srv.server_address[1]}", "SECRET-TOKEN-123")
    live = live_client.Live(hub, OWNER, "LV-x")
    live.say("task: add the badge", "voice")
    live.out.join()
    srv.shutdown()
    assert [g["path"] for g in got] == ["/studio/api/events", "/studio/api/events"]
    assert all(g["cookie"] == "nodach_session=SECRET-TOKEN-123" and g["csrf"] == "1" for g in got)
    line, draft = got[0]["body"], got[1]["body"]
    assert line["event"]["kind"] == "live.line" and line["event"]["body"]["text"] == "task: add the badge"
    assert draft["event"]["body"]["meta"]["from_line"] == line["doc_id"] and draft["event"]["body"]["status"] == "draft"
    out = capsys.readouterr().out + (tmp_path / "lines.jsonl").read_text()
    assert "SECRET-TOKEN-123" not in out and "→ draft TK-" in out


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__code__.co_argcount == 0:
            fn(); n += 1; print("ok", name)
    print(f"{n} passed")


def test_clean_token_accepts_real_shapes_and_rejects_bad_pastes():
    sig = "a" * 64
    good = f"Morami49.1795000000000.{sig}"
    assert core.clean_token(good) == good
    assert core.clean_token(f'  "{good}"  ') == good
    assert core.clean_token(f"nodach_session={good};") == good
    assert core.clean_token("\x16") is None          # Ctrl+V in a Windows console
    assert core.clean_token("") is None
    assert core.clean_token(f"Morami49.17950.{sig}") is None
    assert core.clean_token(None) is None
