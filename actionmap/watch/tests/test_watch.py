"""Nodach Watch tests (no Windows, no hub, no microphone): event builders, keep-out versioning, chips, the stream,
the local API over HTTP with a fake hub, the static page, and the web UI's logic under node (if node is installed).
    python -m pytest -q actionmap/watch/tests"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import pytest

WATCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WATCH))
import watch_core as core     # noqa: E402
import watch_server as server  # noqa: E402
import gate_core               # noqa: E402

T = dt.datetime(2026, 11, 22, 10, 0, 0, tzinfo=dt.timezone.utc)
Z = gate_core.load_zones(None)
WIN = {"title": "Studio - Nodach - Google Chrome"}
PROC = {"name": "chrome.exe"}


def el(name, l, t, r, b, typ="ButtonControl", window=None):
    return {"type": typ, "name": name, "automation_id": "", "class_name": "", "rect": {"left": l, "top": t, "right": r, "bottom": b},
            "window": window or {"title": WIN["title"], "app": "chrome.exe"}, "app": "chrome.exe"}


# ------------------------------------------------------------------ events
def test_point_event_is_pointer_v1_and_never_windows_are_kept_out():
    e = core.point_event(T, cursor=(10, 20), element=el("Save", 0, 0, 50, 30), window=WIN, process=PROC, zones=Z)
    assert e["schema"] == "pointer.v1" and e["kind"] == "pointer.desktop" and e["mode"] == "watch" and e["id"].startswith("PE-261122-100000-")
    assert e["element"]["name"] == "Save" and e["cursor"] == {"x": 10, "y": 20}
    k = core.point_event(T, cursor=(1, 1), element=el("Copy password", 0, 0, 5, 5), window={"title": "Vault - Bitwarden"},
                         process={"name": "Bitwarden.exe"}, zones=Z)
    assert k["kept_out"] == "password manager" and k["element"]["name"] == "" and k["window"]["title"] == "" and not k["screenshot"]
    s = core.point_event(T, cursor=(1, 1), element=el("a.json", 0, 0, 5, 5), window={"title": "nodach_sec - File Explorer"},
                         process={"name": "explorer.exe"}, zones=Z)
    assert s["kept_out"] and "nodach_sec" not in json.dumps(core.shareable(s))


def test_area_event_keeps_elements_inside_and_drops_secrets():
    els = [el("Save", 10, 10, 50, 30), el("Far away", 900, 900, 950, 950),
           el("client_secret_1.json", 20, 20, 60, 40, "ListItemControl"),
           el("Card number", 30, 30, 70, 50, "EditControl", window={"title": "Barclays Online Banking", "app": "chrome.exe"})]
    e = core.area_event(T, area=(0, 0, 200, 200), elements=els, window=WIN, process=PROC, zones=Z)
    assert e["kind"] == "area" and [x["name"] for x in e["elements"]] == ["Save"] and e["elements_hidden"] == 2
    assert e["rect"] == {"left": 0, "top": 0, "right": 200, "bottom": 200} and e["shot_box"] == [0, 0, 200, 200]


def test_markup_event_orders_marks_numbers_steps_and_branches():
    marks = [{"type": "step", "at": [100, 100], "text": "Open the order"},
             {"type": "branch", "at": [120, 140], "label": "if", "text": "it's paid"},
             {"type": "arrow", "from": [100, 100], "to": [400, 300], "from_element": el("Export", 90, 90, 110, 110)},
             {"type": "branch", "at": [120, 180], "label": "ELSE", "text": "ask finance"},
             {"type": "step", "at": [300, 300], "text": "Send the invoice"},
             {"type": "box", "rect": {"left": 50, "top": 50, "right": 80, "bottom": 80}, "elements": [el("Logo", 55, 55, 70, 70)]},
             {"type": "path", "points": [[i, i] for i in range(500)]},
             {"type": "text", "at": [10, 10], "text": "header too tall"}]
    e = core.markup_event(T, marks=marks, window=WIN, process=PROC, preset="steps", zones=Z, screen=(0, 0, 1920, 1080))
    ms = e["marks"]
    assert e["kind"] == "markup" and [m["n"] for m in ms] == list(range(1, 9))
    assert [m.get("step") for m in ms if m["type"] == "step"] == [1, 2]
    assert [(m["label"], m["of_step"]) for m in ms if m["type"] == "branch"] == [("if", 1), ("else", 1)]
    assert ms[2]["from_rect"] == {"left": 90, "top": 90, "right": 110, "bottom": 110} and "to_rect" not in ms[2]
    assert len(ms[6]["points"]) == core.MAX_PATH_POINTS and ms[6]["points"][-1] == {"x": 499, "y": 499}
    assert e["rect"]["left"] == 0 and e["rect"]["right"] == 539                      # all marks + 40 px, inside the screen
    assert "step" in e["element"]["name"] and "branch" in e["element"]["name"]
    with pytest.raises(ValueError):
        core.markup_event(T, marks=[], window=WIN, process=PROC)
    with pytest.raises(ValueError):
        core.markup_event(T, marks=[{"type": "blob", "at": [1, 1]}], window=WIN, process=PROC)
    with pytest.raises(ValueError):
        core.markup_event(T, marks=marks, window=WIN, process=PROC, preset="nope")


def test_wrong_place_is_one_arrow_with_from_and_to_rects():
    e = core.wrong_place(T, from_pt=(20, 20), to_pt=(300, 40), from_element=el("Save", 0, 0, 40, 40),
                         to_element=el("Toolbar", 250, 0, 600, 80, "ToolBarControl"), window=WIN, process=PROC, zones=Z, note="belongs in the toolbar")
    m = e["marks"][0]
    assert e["preset"] == "wrong-place" and len(e["marks"]) == 1 and m["type"] == "arrow"
    assert m["from_rect"]["right"] == 40 and m["to_rect"]["left"] == 250 and m["text"] == "belongs in the toolbar"
    sh = core.shareable(e)
    assert sh["marks"][0]["from_element"] == {"type": "ButtonControl", "name": "Save"} and "Wrong place" in sh["words"]


def test_shareable_never_carries_titles_paths_or_cursor():
    e = core.point_event(T, cursor=(10, 20), element=el("Save", 0, 0, 50, 30), window=WIN, process=PROC,
                         ancestors=[{"type": "Pane", "name": "x"}], zones=Z)
    e["screenshot"] = "C:\\Users\\someone\\nodach-watch\\shots\\x.png"
    sh = core.shareable(e, {"name": "x.png", "bytes": 10, "sha256": "ab", "private_path": "data/users/u/watch/files", "chunks": 1, "extra": 1})
    blob = json.dumps(sh)
    assert "Studio - Nodach" not in blob and "Users" not in blob and "cursor" not in sh and "ancestors" not in sh
    assert sh["picture"] == {"name": "x.png", "bytes": 10, "sha256": "ab", "private_path": "data/users/u/watch/files", "chunks": 1}
    assert sh["app"] == "chrome.exe" and sh["element"]["name"] == "Save" and sh["words"] == "⌖ chrome.exe › Save"
    a = core.shareable(core.area_event(T, area=(0, 0, 99, 99), elements=[el("Save", 1, 1, 9, 9)], window=WIN, process=PROC))
    assert a["part"] == "chrome.exe" and isinstance(a["element_words"], str) and a["elements"][0]["name"] == "Save"


# ------------------------------------------------------------------ never zones in pictures
def test_redact_rects_cover_never_and_kept_out_windows():
    raw, _ = gate_core.keep_out_add(json.loads(gate_core.DEFAULT_ZONES.read_text(encoding="utf-8")),
                                    gate_core.keep_out_entry("app", process="Signal.exe"))
    z = gate_core.parse_zones(json.dumps(raw))
    ws = [{"app": "Bitwarden.exe", "title": "Bitwarden", "rect": (0, 0, 100, 100)},
          {"app": "Signal.exe", "title": "Signal", "rect": (100, 0, 200, 100)},
          {"app": "explorer.exe", "title": "nodach_sec - File Explorer", "rect": (0, 100, 50, 150)},
          {"app": "notepad.exe", "title": "Untitled - Notepad", "rect": (300, 300, 400, 400)}]
    assert [r["left"] for r in core.redact_rects(ws, z)] == [0, 100, 0]
    lst = core.window_list(ws, z)
    assert [w["out"] for w in lst] == [None, "password manager", "secrets in files", "user keep-out"]
    assert all(w["title"] == "" for w in lst if w["out"])                 # titles of out windows aren't listed


# ------------------------------------------------------------------ keep-out file
def test_keep_out_add_remove_write_versions_and_history(tmp_path):
    zp = tmp_path / "zones.json"
    shutil.copy(gate_core.DEFAULT_ZONES, zp)
    rev = json.loads(zp.read_text())["revision"]
    now = dt.datetime(2026, 11, 22, 9, 30)
    e = gate_core.keep_out_entry("window", process="chrome.exe", title="Payroll - Google Chrome")
    added, changed = core.keep_out_add(zp, e, now=now)
    raw = json.loads(zp.read_text())
    assert changed and raw["revision"] == rev + 1 and raw["_changes"][-1]["by"] == "Nowed" and raw["_changes"][-1]["date"] == "2026-11-22"
    hist = list((tmp_path / "zones-history").glob("*.json"))
    assert len(hist) == 1 and json.loads(hist[0].read_text())["revision"] == rev        # the version before is kept
    assert core.keep_out_add(zp, e, now=now)[1] is False                                 # same entry: no new revision
    lst = core.keep_out_list(zp)
    assert any(x["id"] == added["id"] and "Payroll" in x["words"] for x in lst)
    gone, changed = core.keep_out_remove(zp, added["id"], now=now + dt.timedelta(minutes=1))
    assert changed and json.loads(zp.read_text())["revision"] == rev + 2 and len(list((tmp_path / "zones-history").glob("*.json"))) == 2
    assert gate_core.load_zones(zp)["revision"] == rev + 2                                # Gate reads the edited file


def test_keep_out_starts_from_the_shipped_rules_when_he_has_no_zones_file(tmp_path):
    zp = tmp_path / "zones.json"
    core.keep_out_add(zp, gate_core.keep_out_entry("folder", path="D:\\Private"))
    raw = json.loads(zp.read_text())
    assert any(g["name"] == "secrets in files" for g in raw["never"]) and not (tmp_path / "zones-history").exists()


def test_pick_choices():
    c = core.pick_choices({"app": "chrome.exe", "title": "Payroll - Google Chrome"})
    assert [x["label"] for x in c] == ["This window", "The whole app (chrome.exe)"]
    assert c[0]["entry"]["title_words"] == ["Payroll"]


# ------------------------------------------------------------------ chips and lines
def test_chips_prefix_tags_and_fields():
    assert core.compose_line("the header", "looks-off") == ("[looks-off] the header", {"chip": "looks-off", "use": "U1", "compare": "none"})
    t, f = core.compose_line("x", "looks-off", {"compare": "earlier", "compare_ref": {"id": "PE-1", "path": "C:/x"}})
    assert f["compare"] == "earlier" and f["compare_ref"] == {"id": "PE-1"}             # no local path
    assert core.compose_line("[looks-off] already", "looks-off")[0] == "[looks-off] already"
    assert core.compose_line("move it", "mark-up", {"preset": "wrong-place"})[0] == "[wrong-place] move it"
    t, f = core.compose_line("do this", "mark-up", {"as": "for-claude"})
    assert t == "[for-claude] [mark-up] do this" and f["as"] == "for-claude"
    t, f = core.compose_line("", "mark-up", {"as": "report"})
    assert t == "[mark-up]" and f["report"] is True
    t, f = core.compose_line("why is this red", "explain")
    assert t == "[explain] why is this red" and f["save"] == "none" and f["audience"] == "stakeholder"   # default: don't save
    assert core.compose_line("x", "explain", {"save": "developer", "audience": "developer"})[1]["save"] == "developer"
    for bad in (("looks-off", {"compare": "x"}), ("explain", {"save": "cloud"}), ("mark-up", {"as": "email"}), ("nope", {})):
        with pytest.raises(ValueError):
            core.compose_line("x", *bad)
    assert core.compose_line("  plain   line ") == ("plain line", {})


def test_audience_from_profile_or_role():
    assert core.audience_for({"owner": True}) == "developer"
    assert core.audience_for({"owner": False}) == "stakeholder"
    assert core.audience_for({"owner": True, "profile": {"audience": "stakeholder"}}) == "stakeholder"
    assert core.audience_for(None) == "stakeholder"


def test_line_event_matches_live_and_adds_watch_fields():
    me = {"id": "github:x", "owner": True}
    ev = core.line_event("LV-1", me, "[looks-off] hi", T, point={"schema": "pointer.v1"}, watch={"chip": "looks-off"})
    assert ev["kind"] == "live.line" and ev["item"] == "LV-1" and ev["body"]["via"] == "watch"
    assert ev["body"]["watch"] == {"chip": "looks-off"} and ev["author"]["label"] == "Nowed"


# ------------------------------------------------------------------ the stream
def docs():
    a_owner = {"id": "github:x", "role": "owner", "label": "Nowed"}
    claude = {"id": "claude", "role": "agent", "label": "Claude"}
    return [
        {"doc_id": "d1", "event": {"ts": "2026-11-22T10:00:01.000Z", "kind": "live.line", "item": "LV-1", "author": a_owner,
                                   "body": {"speaker": "Nowed", "text": "hello", "via": "watch",
                                            "point": {"kind": "markup", "words": "⌖ chrome.exe › mark-up: 1 arrow"}}}},
        {"doc_id": "d2", "event": {"ts": "2026-11-22T10:00:03.000Z", "kind": "comment", "item": "LV-1", "author": claude, "body": {"text": "On it"}}},
        {"doc_id": "d3", "event": {"ts": "2026-11-22T10:00:02.000Z", "kind": "comment", "item": "LV-1", "author": a_owner,
                                   "via": "claude-connector", "body": {"text": "from the connector"}}},
        {"doc_id": "d4", "event": {"ts": "2026-11-22T10:00:04.000Z", "kind": "comment", "item": "LV-1", "author": a_owner,
                                   "body": {"step": {"kind": "point", "target": {"element": "Save", "part": "toolbar"}}}}},
        {"doc_id": "d5", "event": {"ts": "2026-11-22T10:00:05.000Z", "kind": "live.line", "item": "LV-1", "author": a_owner, "body": {"text": "oops"}}},
        {"doc_id": "d6", "event": {"ts": "2026-11-22T10:00:06.000Z", "kind": "retract", "item": "LV-1", "author": a_owner, "body": {"of": "d5"}}},
        {"doc_id": "d7", "event": {"ts": "2026-11-22T10:00:07.000Z", "kind": "live.line", "item": "LV-2", "author": a_owner, "body": {"text": "other"}}},
    ]


def test_stream_rows_like_the_live_panel():
    rows = core.stream_rows(docs(), "LV-1")
    assert [(r["kind"], r["text"]) for r in rows] == [("line", "hello"), ("reply", "from the connector"), ("reply", "On it"),
                                                      ("step", "Pointed at Save (toolbar)")]
    assert rows[0]["words"].startswith("⌖ chrome.exe") and rows[1]["who"] == "Nowed via Claude" and rows[2]["who"] == "Claude"


# ------------------------------------------------------------------ stuck offers and exports
def test_stuck_offer_is_off_by_default_and_fires_once():
    acts = [{"kind": "action", "_t": 100 + i, "tool": "Click", "args": {"loc": [1, 1]}, "ok": True, "decision": "allowed"} for i in range(3)]
    assert core.stuck_offer(acts, 110, None) is None                                      # off by default
    on = {"on": True}
    o = core.stuck_offer(acts, 110, on)
    assert o["reason"] == "repeat" and core.stuck_offer(acts, 111, on, last_offer=110) is None
    err = acts[:1] + [{"kind": "action", "_t": 105, "tool": "Type", "args": {}, "ok": False, "decision": "allowed"}]
    assert core.stuck_offer(err, 106, on)["reason"] == "error"
    one = acts[:1]
    assert core.stuck_offer(one, 150, on) is None and core.stuck_offer(one, 100 + 130, on)["reason"] == "pause"
    assert core.stuck_offer(one, 100 + 5000, on) is None                                  # long gone, not 'stuck'


def test_export_bundle_is_self_contained(tmp_path):
    e = core.wrong_place(T, from_pt=(20, 20), to_pt=(300, 40), from_element=el("Save", 0, 0, 40, 40), window=WIN, process=PROC, zones=Z)
    e["screenshot"] = str(tmp_path / "x.png")
    r = core.export_bundle(e, b"\x89PNG\r\n\x1a\nfake", tmp_path / "out", note="for the vendor <b>")
    page = Path(r["html"]).read_text(encoding="utf-8")
    assert "data:image/png;base64," in page and "<line" in page and "Arrow from ButtonControl “Save”" in page
    assert "&lt;b&gt;" in page and WIN["title"] not in page and "http" not in page.replace("http://www.w3.org/2000/svg", "")
    names = zipfile.ZipFile(r["zip"]).namelist()
    assert sorted(names) == sorted([f"{e['id']}.html", f"{e['id']}.json", f"{e['id']}.png"])
    inner = json.loads(zipfile.ZipFile(r["zip"]).read(f"{e['id']}.json"))
    assert inner["window"]["title"] == "" and inner["screenshot"] == "x.png"


def test_report_chip_reproduce_or_incident():
    t, f = core.compose_line("export fails", "report")
    assert t == "[report] export fails" and f["reproduce"] == "claude-may-try" and f["irreversible"] is False
    t, f = core.compose_line("sent the wrong invoice", "report", {"irreversible": True, "incident": {"what_happened": "sent", "junk": "x"}})
    assert t.startswith("[irreversible]") and f["reproduce"] == "never" and set(f["incident"]) == set(core.INCIDENT_FIELDS)
    txt = core.incident_text(f)
    assert "What happened: sent" in txt and "What can't be known: (not known yet: ask)" in txt


def test_may_reproduce_never_for_irreversible_kinds():
    assert core.may_reproduce({"irreversible": True}, Z)["allowed"] is False
    assert core.may_reproduce({}, Z, text="the export button greys out")["allowed"] is True
    r = core.may_reproduce({}, Z, text="I pressed Send and it went twice")
    assert not r["allowed"] and "send" in r["reason"]
    p = core.shareable(core.point_event(T, cursor=(1, 1), element=el("Delete account", 0, 0, 9, 9), window=WIN, process=PROC, zones=Z))
    assert core.may_reproduce({}, Z, p, "this broke")["allowed"] is False
    m = core.shareable(core.wrong_place(T, from_pt=(1, 1), to_pt=(5, 5), from_element=el("Pay now", 0, 0, 3, 3), window=WIN, process=PROC, zones=Z))
    assert core.may_reproduce({}, Z, m, "")["allowed"] is False


def test_glitch_offer_once_per_app_per_hour():
    log = [{"kind": "action", "_t": 10, "app": "chrome.exe"}, {"kind": "clip", "_t": 20, "trigger": "glitch", "path": "clips/a.gif", "ts": "t"}]
    asked = {}
    o = core.glitch_offer(log, asked, 30)
    assert o["app"] == "chrome.exe" and o["clip"] == "clips/a.gif" and "report it?" in o["detail"]
    assert core.glitch_offer(log, asked, 31) is None                                     # same clip: asked already
    log2 = log + [{"kind": "clip", "_t": 40, "trigger": "glitch", "path": "clips/b.gif"}]
    assert core.glitch_offer(log2, asked, 50) is None                                    # same app within the hour
    log3 = log2 + [{"kind": "clip", "_t": 4000, "trigger": "glitch", "path": "clips/c.gif"}]
    assert core.glitch_offer(log3, asked, 4000)["clip"] == "clips/c.gif"                 # an hour later: ask again
    log4 = log3 + [{"kind": "action", "_t": 4010, "app": "notepad.exe"}, {"kind": "clip", "_t": 4020, "trigger": "glitch", "path": "clips/d.gif"}]
    assert core.glitch_offer(log4, asked, 4030)["app"] == "notepad.exe"                  # another app: its own hour
    assert core.glitch_offer([{"kind": "clip", "_t": 1, "trigger": "user", "path": "x"}], {}, 2) is None   # only glitches


CAROUSEL = {"title": "Two drafts", "cards": [
    {"id": "c1", "kind": "text", "title": "Short reply", "text": "Thanks, booked for Monday."},
    {"id": "c2", "kind": "image", "title": "Banner", "src": "data:image/png;base64,iVBORw0KGgo="},
    {"id": "c3", "kind": "image", "title": "Remote", "src": "https://example.com/x.png"},
    {"id": "c4", "kind": "html", "title": "Form", "html": "<form><input></form><script>alert(1)</script>"},
    {"id": "c5", "kind": "video", "title": "Walkthrough", "src": "https://example.com/v.mp4"},
    {"id": "c6", "kind": "video", "title": "Local", "src": "file:///C:/x.mp4"},
    {"id": "bad id!", "kind": "weird", "title": "?"}]}


def test_carousel_is_made_safe_to_show():
    c = core.carousel_from(CAROUSEL, "d9")
    k = {x["id"]: x for x in c["cards"]}
    assert c["id"] == "d9" and len(c["cards"]) == 7
    assert k["c2"]["src"].startswith("data:image/") and k["c3"]["kind"] == "link" and "src" not in k["c3"]
    assert k["c4"]["html"].startswith("<form>") and k["c5"]["url"].startswith("https://") and k["c6"]["kind"] == "text"
    assert k["badid"]["kind"] == "text"
    assert core.carousel_from({"cards": "nope"}) is None and core.carousel_from(None) is None


def test_carousel_rows_card_markup_and_routes():
    rows = core.stream_rows([{"doc_id": "d9", "event": {"ts": "2026-11-22T10:00:00.000Z", "kind": "comment", "item": "LV-1",
                                                       "author": {"id": "claude", "role": "agent"}, "body": {"text": "Drafts", "carousel": CAROUSEL}}}], "LV-1")
    assert rows[0]["carousel"]["cards"][0]["title"] == "Short reply"
    card = rows[0]["carousel"]["cards"][0]
    e = core.card_markup_event(T, carousel="d9", card=card, marks=[{"type": "box", "rect": {"left": 5, "top": 5, "right": 50, "bottom": 30}},
                                                                   {"type": "text", "at": [60, 20], "text": "too formal"}], size=(360, 200))
    assert e["kind"] == "markup" and e["target"] == {"carousel": "d9", "card": "c1", "card_title": "Short reply", "card_kind": "text"}
    assert e["rect"]["right"] <= 360 and "card “Short reply”" in e["element"]["name"]
    line, f = core.route_line("automation", "d9", "c1", "weekly")
    assert line == "[for-claude] [route:automation] Build an automation, then run it: weekly"
    assert f == {"chip": "route", "use": "U10", "route": "automation", "carousel": "d9", "card": "c1", "risks_first": True}
    with pytest.raises(ValueError):
        core.route_line("rocket", "d9")


def test_expected_matches_before_a_map_step():
    step = {"expect": {"name": "Submit", "type": "ButtonControl", "app": "chrome.exe", "window_words": ["Order form"], "nearby": ["Total"]}}
    live = {"name": "Submit", "type": "Button", "app": "chrome.exe", "window_title": "Order form - Shop - Google Chrome", "nearby": ["Total £20"]}
    assert core.expected_matches(step, live) == {"ok": True, "changed": []}
    moved = dict(live, name="Delete")                        # 'Submit' moved and 'Delete' is now at that spot
    r = core.expected_matches(step, moved)
    assert not r["ok"] and r["changed"] == ["name: expected “Submit”, found “Delete”"]
    r = core.expected_matches(step, dict(live, window_title="Checkout - Shop", nearby=[], type="Hyperlink", app="msedge.exe"))
    assert not r["ok"] and len(r["changed"]) == 4
    assert core.expected_matches(step, None)["changed"] == ["nothing found at that spot"]


def test_status_strip():
    s = core.status_strip(watch=True, paused=False, acting={"active": True, "tool": "Click"}, kept_out=2, signed_in=True, session="LV-1")
    assert s["watching"] == "Watching: all windows except 2 kept out" and s["acting"] == "Claude is acting: Click" and s["gate"] == "ok"
    s = core.status_strip(watch=False, paused=True, acting={"active": True, "tool": "Click"}, kept_out=0, signed_in=False, session=None)
    assert s["watching"].startswith("Watch is off") and s["acting"] == "" and s["gate"] == "paused"


# ------------------------------------------------------------------ the local API (fake hub, fake capture)
class FakeHub:
    def __init__(self, owner=True):
        self.docs, self.private, self.n = [], [], 0
        self.owner = owner

    def me(self):
        return {"id": "github:x", "owner": self.owner, "login": "x"}

    def post(self, ev, did=None):
        self.n += 1
        did = did or f"doc{self.n}"
        self.docs.append({"doc_id": did, "event": ev})
        return did

    def _req(self, method, path, body=None):
        if method == "GET" and path.startswith("/studio/api/events"):
            after = int(re.search(r"after=(\d+)", path).group(1))
            return {"events": self.docs[after:], "next": len(self.docs), "total": len(self.docs)}
        if path == "/studio/api/private":
            self.private.append(body)
            return {}
        raise AssertionError(path)


class Tokens:
    def __init__(self):
        self.t = None

    def get(self, url):
        return self.t

    def from_clipboard(self, url):
        self.t = "x.1234567890.abc"
        return True


def fake_capture(tmp):
    def cap(mode, zones, preset):
        if mode == "pick":
            w = {"app": "chrome.exe", "title": "Payroll - Google Chrome"}
            return {"pick": w, "choices": core.pick_choices(w)}
        if mode == "markup":
            e = core.wrong_place(T, from_pt=(1, 1), to_pt=(50, 50), from_element=el("Save", 0, 0, 9, 9), window=WIN, process=PROC, zones=zones)
        else:
            e = core.point_event(T, cursor=(5, 5), element=el("Save", 0, 0, 9, 9), window=WIN, process=PROC, zones=zones)
        shot = tmp / "shots" / f"{e['id']}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 50000)          # two 40 KB chunks
        e["screenshot"] = str(shot)
        with open(tmp / "watch" / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(e) + "\n")
        return {"event": e}
    return cap


@pytest.fixture
def api(tmp_path):
    (tmp_path / "watch").mkdir()
    (tmp_path / "gate").mkdir()
    shutil.copy(gate_core.DEFAULT_ZONES, tmp_path / "gate" / "zones.json")
    hub, tokens, calls = FakeHub(), Tokens(), []
    w = server.Watch(home=tmp_path / "watch", gate_home=tmp_path / "gate", root=tmp_path / "root",
                     hub_factory=lambda url, tok: hub, capture=fake_capture(tmp_path), token_store=tokens,
                     voice=type("V", (), {"status": lambda s: "ready"})(),
                     hooks={"hide": lambda: calls.append("hide"), "show": lambda: calls.append("show")})
    srv, url, key = server.serve(w)
    base = url.split("/#")[0]

    def call(path, body=None, key_=key, host=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"X-Watch-Key": key_}
        if body is not None:
            h["Content-Type"] = "application/json"
        if host:
            h["Host"] = host
        req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    call.key = key
    yield call, hub, tokens, tmp_path, calls, base
    srv.shutdown()


def test_api_needs_the_key_and_the_local_host(api):
    call, *_ = api
    assert call("/api/state", key_="wrong")[0] == 403
    assert call("/api/state", host="evil.example:80")[0] == 403


def test_api_flow_sign_in_session_point_send_picture(api):
    call, hub, tokens, tmp, calls, _ = api
    code, s = call("/api/state")
    assert code == 200 and s["role"] is None and "Not signed in" in s["error"] and s["strip"]["watching"].startswith("Watch is off")
    assert call("/api/signin", {})[1] == {"ok": True}
    code, r = call("/api/session/start", {})
    sid = r["session"]
    assert code == 200 and sid.startswith("LV-") and hub.docs[0]["event"]["body"]["live"]["via"] == "watch"
    code, cap = call("/api/capture", {"mode": "point"})
    assert code == 200 and cap["event"]["words"] == "⌖ chrome.exe › Save" and calls == ["hide", "show"]
    code, sent = call("/api/send", {"text": "this button", "chip": "looks-off", "opts": {"compare": "none"},
                                    "attach": cap["event"]["id"], "picture": True})
    assert code == 200, sent
    line = hub.docs[-1]["event"]
    assert line["kind"] == "live.line" and line["body"]["text"] == "[looks-off] this button"
    pt = line["body"]["point"]
    assert pt["picture"]["chunks"] == 2 and pt["picture"]["private_path"] == "data/users/x/watch/files"
    assert len(hub.private) == 2 and all(p["path"] == "data/users/x/watch/files" for p in hub.private)
    assert "Users" not in json.dumps(line) and WIN["title"] not in json.dumps(line)
    rows = call(f"/api/stream?session={sid}")[1]["rows"]
    assert rows[-1]["text"] == "[looks-off] this button"


def test_api_no_picture_without_the_tick_and_explain_audience(api):
    call, hub, *_ = api
    call("/api/signin", {})
    call("/api/session/start", {})
    cap = call("/api/capture", {"mode": "point"})[1]["event"]
    call("/api/send", {"text": "what is this", "chip": "explain", "opts": {"save": "none"}, "attach": cap["id"]})
    line = hub.docs[-1]["event"]["body"]
    assert "picture" not in line["point"] and hub.private == []
    assert line["watch"] == {"chip": "explain", "use": "U3", "save": "none", "audience": "developer"}   # owner -> developer


def test_api_markup_hand_to_claude_report_and_export(api):
    call, hub, tokens, tmp, *_ = api
    call("/api/signin", {})
    call("/api/session/start", {})
    cap = call("/api/capture", {"mode": "markup", "preset": "wrong-place"})[1]["event"]
    assert cap["kind"] == "markup" and cap["preset"] == "wrong-place"
    call("/api/send", {"text": "move it", "chip": "mark-up", "opts": {"preset": "wrong-place", "as": "for-claude"}, "attach": cap["id"]})
    b = hub.docs[-1]["event"]["body"]
    assert b["text"] == "[for-claude] [wrong-place] move it" and b["point"]["marks"][0]["type"] == "arrow"
    code, ex = call("/api/export", {"id": cap["id"], "note": "for the vendor"})
    assert code == 200 and (tmp / "watch" / "exports" / ex["html"]).exists() and (tmp / "watch" / "exports" / ex["zip"]).exists()


def test_api_task_line_drafts_and_ended_session_switches(api):
    call, hub, *_ = api
    call("/api/signin", {})
    old = call("/api/session/start", {})[1]["session"]
    new = call("/api/session/start", {})[1]["session"]
    hub.post({"ts": "2026-11-22T11:00:00.000Z", "kind": "status", "item": old, "body": {"status": "open"}, "author": {}})
    call("/api/session", {"id": old})
    r = call("/api/send", {"text": "task: fix the header"})[1]
    assert r["switched"] and r["session"] == new
    kinds = [d["event"]["kind"] for d in hub.docs[-2:]]
    assert kinds == ["live.line", "item.create"] and hub.docs[-1]["event"]["body"]["status"] == "draft"


def test_api_report_irreversible_incident(api):
    call, hub, *_ = api
    call("/api/signin", {})
    call("/api/session/start", {})
    call("/api/send", {"text": "deleted the wrong folder", "chip": "report",
                       "opts": {"irreversible": True, "incident": {"what_happened": "deleted Projects", "recovery": "restore from backup"}}})
    b = hub.docs[-1]["event"]["body"]
    assert b["text"].startswith("[irreversible] deleted the wrong folder\nWhat happened: deleted Projects")
    assert b["watch"]["reproduce"] == "never" and b["watch"]["reproduce_check"]["allowed"] is False
    call("/api/send", {"text": "the save button does nothing", "chip": "report"})
    w = hub.docs[-1]["event"]["body"]["watch"]
    assert w["reproduce"] == "claude-may-try" and w["reproduce_check"]["allowed"] is True


def test_api_glitch_offer_from_gate_log(api):
    call, hub, tokens, tmp, *_ = api
    now = dt.datetime.now(dt.timezone.utc)
    iso = lambda d: d.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with open(tmp / "gate" / "actions.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "action", "ts": iso(now - dt.timedelta(seconds=30)), "app": "chrome.exe", "tool": "Click"}) + "\n")
        f.write(json.dumps({"kind": "clip", "ts": iso(now - dt.timedelta(seconds=10)), "trigger": "glitch", "path": "clips/x.gif"}) + "\n")
    assert call("/api/state")[1]["offer"]["reason"] == "glitch"
    assert call("/api/state")[1]["offer"] is None


def test_api_card_markup_and_route(api):
    call, hub, *_ = api
    call("/api/signin", {})
    sid = call("/api/session/start", {})[1]["session"]
    did = hub.post({"ts": "2026-11-22T10:00:09.000Z", "kind": "comment", "item": sid, "author": {"id": "claude", "role": "agent"},
                    "body": {"text": "Drafts", "carousel": CAROUSEL}})
    code, r = call("/api/card-markup", {"carousel": did, "card": "c1", "marks": [{"type": "arrow", "from": [1, 1], "to": [40, 40]}], "size": [360, 200]})
    assert code == 200 and "card" in r["event"]["words"]
    assert call("/api/card-markup", {"carousel": did, "card": "nope", "marks": []})[0] == 404
    code, r2 = call("/api/route", {"carousel": did, "route": "drafts", "card": "c1", "text": "in Outlook", "attach": r["event"]["id"]})
    b = hub.docs[-1]["event"]["body"]
    assert code == 200 and b["text"] == "[for-claude] [route:drafts] Create drafts in the app: in Outlook"
    assert b["watch"]["route"] == "drafts" and b["point"]["kind"] == "markup"
    assert call("/api/route", {"carousel": did, "route": "x"})[0] == 400


def test_api_keep_out_pick_add_remove(api):
    call, hub, tokens, tmp, *_ = api
    pick = call("/api/keepout/pick", {})[1]
    assert [c["label"] for c in pick["choices"]][0] == "This window"
    code, r = call("/api/keepout/add", {"entry": pick["choices"][0]["entry"]})
    assert code == 200 and r["changed"]
    raw = json.loads((tmp / "gate" / "zones.json").read_text())
    assert raw["_changes"][-1]["by"] == "Nowed" and "Payroll" in raw["_changes"][-1]["what"]
    assert call("/api/state")[1]["strip"]["kept_out"] == 2                    # nodach_sec + this window
    code, r = call("/api/keepout/add", {"entry": {"kind": "folder", "path": ""}})
    assert code == 400
    rid = next(e["id"] for e in call("/api/keepout")[1]["list"] if "Payroll" in e["words"])
    assert call("/api/keepout/remove", {"id": rid})[0] == 200
    assert call("/api/keepout/remove", {"id": rid})[0] == 404


def test_api_stop_clip_settings_reference(api, tmp_path):
    call, hub, tokens, tmp, *_ = api
    assert call("/api/stop", {})[1] == {"paused": True}
    assert json.loads((tmp / "gate" / "state.json").read_text())["paused"] is True
    call("/api/clip", {})
    assert json.loads((tmp / "gate" / "state.json").read_text())["keep_clip_req"] == 1
    assert call("/api/settings", {"stuck": True})[1] == {"stuck": {"on": True}}
    img = tmp_path / "design.png"
    img.write_bytes(b"png")
    ref = call("/api/reference", {"path": str(img)})[1]["reference"]
    assert ref["name"] == "design.png" and "path" not in ref
    sec = tmp_path / "nodach_sec"
    sec.mkdir()
    (sec / "k.png").write_bytes(b"x")
    assert call("/api/reference", {"path": str(sec / "k.png")})[0] == 400


def test_static_page_and_csp(api):
    *_, base = api
    with urllib.request.urlopen(base + "/") as r:
        html = r.read().decode()
        csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    for part in ("watch.frame", "watch.strip", "watch.bar", "watch.chips", 'id="chat"', 'id="mic"', 'id="point"', 'id="select"',
                 'id="markup"', 'id="clip"', 'id="keepOutBtn"', 'id="stop"', "Looks off", "Mark up", "Explain this",
                 "attach picture", "Keep out a window", "Pick from open windows", "Keep out folder", "don't save"):
        assert part in html, part
    assert "<script>" not in html and " style=" not in html          # nothing inline (the CSP would block it)
    for f in re.findall(r'(?:src|href)="([^"]+)"', html):
        with urllib.request.urlopen(base + "/" + f) as r:
            assert r.status == 200
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(base + "/../watch_server.py")


# ------------------------------------------------------------------ the web UI's logic (node)
NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node isn't installed")
def test_web_logic_under_node():
    r = subprocess.run([NODE, str(WATCH / "tests" / "test_logic.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(not NODE, reason="node isn't installed")
def test_js_and_python_put_the_same_tag_on_a_line():
    cases = [("x", None, {}), ("x", "looks-off", {}), ("[looks-off] y", "looks-off", {}), ("m", "mark-up", {"preset": "wrong-place"}),
             ("m", "mark-up", {"as": "for-claude"}), ("m", "mark-up", {"preset": "wrong-place", "as": "for-claude"}),
             ("e", "explain", {"save": "personal"}), ("  a   b ", "explain", {}), ("r", "report", {}),
             ("r", "report", {"irreversible": True})]
    js = ("const L=require(" + json.dumps(str(WATCH / "web" / "watch_logic.js")) + ");const c=" + json.dumps(cases) +
          ";console.log(JSON.stringify(c.map(([t,ch,o])=>L.lineText(t,ch,o))))")
    out = json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=60).stdout)
    assert out == [core.compose_line(t, ch, o)[0] for t, ch, o in cases]


# ------------------------------------------------------------------ the real page in a headless browser (if available)
def test_page_in_a_headless_browser(api):
    pw = pytest.importorskip("playwright.sync_api")
    call, hub, tokens, tmp, calls, base = api
    call("/api/signin", {})
    sid = call("/api/session/start", {})[1]["session"]
    hub.post({"ts": "2026-11-22T10:00:09.000Z", "kind": "comment", "item": sid, "author": {"id": "claude", "role": "agent", "label": "Claude"},
              "body": {"text": "<b>hi</b> from Claude"}})
    srv_key = call.key
    page = None

    def sent(n):          # the page's CSP forbids eval, so wait in Python rather than with wait_for_function
        for _ in range(100):
            if len(hub.docs) >= n:
                return
            page.wait_for_timeout(50)
        raise AssertionError("nothing sent")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"no browser: {type(e).__name__}")
        page = b.new_page(viewport={"width": 400, "height": 820})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/#key=" + srv_key)
        page.wait_for_selector("#chat li.reply")
        assert "<b>" not in page.inner_html("#chat") and "from Claude" in page.inner_text("#chat")
        assert page.inner_text("#watching").startswith("Watch is off")
        page.click("[data-chip=looks-off]")
        assert page.get_attribute("[data-chip=looks-off]", "aria-pressed") == "true"
        assert "hint" in page.get_attribute("#select", "class")
        page.click("#point")
        page.wait_for_selector("#attRow:not([hidden])")
        page.fill("#text", "this one")
        n = len(hub.docs)
        page.click("#send")
        sent(n + 1)
        assert hub.docs[-1]["event"]["body"]["text"] == "[looks-off] this one"
        page.click("[data-chip=report]")
        page.check("#irreversible")
        page.fill("[data-inc=what_happened]", "paid twice")
        page.fill("#text", "oops")
        n = len(hub.docs)
        page.click("#send")
        sent(n + 1)
        body = hub.docs[-1]["event"]["body"]
        assert body["text"].startswith("[irreversible] oops") and body["watch"]["incident"]["what_happened"] == "paid twice"
        page.click("#keepOutBtn")
        page.wait_for_selector("#koList li")
        assert "nodach_sec" in page.inner_text("#koList")
        b.close()
        assert errors == [], errors
