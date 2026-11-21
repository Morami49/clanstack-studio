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
    assert sh["app"] == "Chrome" and sh["element"]["name"] == "Save" and sh["words"] == "⌖ Chrome › Save"
    a = core.shareable(core.area_event(T, area=(0, 0, 99, 99), elements=[el("Save", 1, 1, 9, 9)], window=WIN, process=PROC))
    assert a["part"] == "Chrome" and isinstance(a["element_words"], str) and a["elements"][0]["name"] == "Save"


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
    # SC-golden-looksoff-1 #4: Claude's connector replies say "Claude", never "Nowed via Claude"
    assert rows[0]["words"].startswith("⌖ chrome.exe") and rows[1]["who"] == "Claude" and rows[2]["who"] == "Claude"
    mine = core.stream_rows(docs(), "LV-1", me_id=docs()[0]["event"]["author"]["id"])
    assert mine[0]["who"] == "You"


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


def test_privacy_moments_pause_watch_in_strip_and_pictures():
    s = core.status_strip(watch=True, paused=False, acting={}, kept_out=1, signed_in=True, session="LV-1", privacy="sign-in page")
    assert s["watching"] == "Watch paused itself: sign-in page in front" and s["privacy"] == "sign-in page"
    assert core.status_strip(watch=False, paused=False, acting={}, kept_out=1, signed_in=True, session=None, privacy="payment form")["privacy"] is None
    ws = [{"app": "chrome.exe", "title": "Sign in - Google Accounts", "rect": (0, 0, 10, 10)},
          {"app": "chrome.exe", "title": "Basket - Checkout", "rect": (10, 0, 20, 10)},
          {"app": "notepad.exe", "title": "Untitled - Notepad", "rect": (20, 0, 30, 10)}]
    assert len(core.redact_rects(ws, Z)) == 2
    e = core.point_event(T, cursor=(1, 1), element=el("Email", 0, 0, 5, 5), window={"title": "Log in to Studio"}, process=PROC, zones=Z)
    assert e["kept_out"] == "privacy moment"


def test_plain_actions_and_lesson():
    a = core.area_event(T, area=(0, 0, 500, 500), window=WIN, process=PROC, zones=Z,
                        elements=[el("Save", 1, 1, 9, 9), el("Name", 10, 10, 90, 30, "EditControl"), el("Save", 1, 1, 9, 9),
                                  el("Terms", 5, 50, 20, 60, "CheckBoxControl"), el("", 1, 1, 2, 2), el("Logo", 1, 70, 9, 80, "ImageControl")])
    assert core.plain_actions(a) == ["Press “Save”", "Type into “Name”", "Tick “Terms”", "Look at “Logo” (image)"]
    p = core.point_event(T, cursor=(1, 1), element=el("Open", 0, 0, 5, 5, "HyperlinkControl"), window=WIN, process=PROC, zones=Z)
    assert core.plain_actions(p) == ["Open “Open”"]
    rows = core.stream_rows(docs(), "LV-1")
    ev = core.lesson_event("LV-1", {"id": "github:x", "owner": True}, T, rows, "Invoices")
    b = ev["body"]
    assert b["id"].startswith("LS-") and b["refs"] == ["LV-1"] and b["meta"]["kind"] == "lesson" and b["meta"]["steps"] == 4
    assert b["title"] == "Lesson: Invoices" and "1. Nowed: hello" in b["body"]


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


def fake_test_capture(tmp):
    """Stands in for watch_win.capture(mode, zones, None, overlay=<the test's result>) (the real one needs Windows)."""
    def cap(mode, zones, got):
        if mode == "area":
            e = core.area_event(T, area=core.rect(*got["rect"]), elements=[el("Save", 10, 10, 50, 30), el("Far", 900, 900, 950, 950)],
                                window=WIN, process=PROC, zones=zones)
        else:
            e = core.point_event(T, cursor=(got["x"], got["y"]), element=el("Save", 0, 0, 9, 9), window=WIN, process=PROC, zones=zones)
        shot = tmp / "shots" / f"{e['id']}-t.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.write_bytes(b"\x89PNG\r\n\x1a\n")
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
                     hooks={"hide": lambda: calls.append("hide"), "show": lambda: calls.append("show")},
                     test_capture=fake_test_capture(tmp_path))
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
    call.w = w
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
    assert code == 200 and cap["event"]["words"] == "⌖ Chrome › Save" and calls == ["hide", "show"]
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
    assert [x for x in rows if x["kind"] == "line"][-1]["text"] == "[looks-off] this button" and rows[-1]["kind"] == "wait"


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
    (tmp / "gate" / "state.json").write_text(json.dumps({"watch": True}))
    with open(tmp / "gate" / "actions.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "action", "ts": iso(now - dt.timedelta(hours=3)), "app": "notepad.exe", "tool": "Click"}) + "\n")
        f.write(json.dumps({"kind": "clip", "ts": iso(now - dt.timedelta(hours=3)), "trigger": "glitch", "path": "clips/old.gif"}) + "\n")
        f.write(json.dumps({"kind": "action", "ts": iso(now - dt.timedelta(seconds=30)), "app": "chrome.exe", "tool": "Click"}) + "\n")
        f.write(json.dumps({"kind": "clip", "ts": iso(now - dt.timedelta(seconds=5)), "trigger": "glitch", "path": "clips/x.gif"}) + "\n")
    o = call("/api/state")[1]["offer"]
    assert o["reason"] == "glitch" and o["clip"] == "clips/x.gif"        # SC-golden-looksoff-1 #5: the 3-hour-old clip is never offered
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


def test_api_end_with_lesson_shot_and_plain(api):
    call, hub, tokens, tmp, calls, base = api
    call("/api/signin", {})
    sid = call("/api/session/start", {})[1]["session"]
    cap = call("/api/capture", {"mode": "point"})[1]["event"]
    req = urllib.request.Request(base + "/api/shot?id=" + cap["id"], headers={"X-Watch-Key": call.key})
    with urllib.request.urlopen(req) as r:
        assert r.headers["Content-Type"] == "image/png" and r.read().startswith(b"\x89PNG")
    assert call("/api/plain?id=" + cap["id"])[1] == {"actions": ["Press “Save”"]}
    call("/api/send", {"text": "hello"})
    r = call("/api/session/end", {"lesson": True})[1]
    kinds = [(d["event"]["kind"], (d["event"]["body"] or {}).get("source")) for d in hub.docs[-3:]]
    assert r["ended"] == sid and r["lesson"].startswith("LS-") and kinds[0] == ("item.create", "watch")
    assert hub.docs[-1]["event"]["kind"] == "status" and hub.docs[-1]["event"]["body"]["status"] == "open"
    sid2 = call("/api/session/start", {})[1]["session"]
    n = len(hub.docs)
    assert "lesson" not in call("/api/session/end", {"lesson": False})[1] and len(hub.docs) == n + 2 and sid2


def test_api_privacy_moment_in_state(api):
    call, hub, tokens, tmp, calls, base = api
    st = json.loads((tmp / "gate" / "state.json").read_text()) if (tmp / "gate" / "state.json").exists() else {}
    (tmp / "gate" / "state.json").write_text(json.dumps(dict(st, watch=True)))
    import watch_server as ws
    w = ws.Watch(home=tmp / "w2", gate_home=tmp / "gate", root=tmp / "root", hub_factory=lambda u, t: hub, token_store=tokens,
                 voice=type("V", (), {"status": lambda s: "ready"})(), hooks={"foreground": lambda: {"title": "Sign in - Google Accounts"}})
    assert w.state()["strip"]["watching"] == "Watch paused itself: sign-in page in front"
    w.hooks["foreground"] = lambda: {"title": "Untitled - Notepad"}
    assert w.state()["strip"]["watching"].startswith("Watching: all windows except")


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
                 "send the picture", "Keep out a window", "Pick from open windows", "Keep out folder", "don't save"):
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
        # golden path first (21 Nov): advanced tools sit behind More; this test covers them all
        assert page.is_hidden("#point") and page.is_visible("#select") and page.is_visible("[data-chip=looks-off]")
        page.click("#moreBtn")
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
        page.click("#point")
        page.wait_for_selector("#attRow:not([hidden])")
        page.click("#accessBtn")
        page.click("#plainList")
        page.wait_for_selector("#accView ol li")
        assert page.inner_text("#accView ol") == "Press “Save”"
        page.click("#enlarge")
        page.wait_for_selector("#accView img")
        assert page.get_attribute("#accView img", "src").startswith("blob:")
        page.check("#bigText")
        assert "big" in (page.get_attribute("body", "class") or "")
        page.click("#accClose")
        page.wait_for_selector("#endSession:not([hidden])")
        page.click("#endSession")
        n = len(hub.docs)
        page.click("#endLesson")
        sent(n + 3)
        assert any(d["event"]["body"].get("meta", {}).get("kind") == "lesson" for d in hub.docs[n:] if d["event"]["kind"] == "item.create")
        page.click("#keepOutBtn")
        page.wait_for_selector("#koList li")
        assert "nodach_sec" in page.inner_text("#koList")
        # decision 77a b: a test input shows as a grey note and attaches, and the page reports what it shows
        page.click("#koClose")
        (tmp / "gate" / "state.json").write_text(json.dumps({"watch": True}))
        call("/api/session/start", {})
        assert call("/api/test/select_area", {"x1": 0, "y1": 0, "x2": 200, "y2": 200})[0] == 200
        page.wait_for_selector("#chat li.note")
        page.wait_for_selector("#attRow:not([hidden])")
        assert "Test input from Claude" in page.inner_text("#chat") and "Save" in page.inner_text("#attWords")
        for _ in range(60):
            st = call("/api/test/state", {})[1]
            if st["ui"].get("attach") and st["ui"]["attach"]["kind"] == "area":
                break
            page.wait_for_timeout(100)
        ids = {c["id"] for c in st["ui"]["controls"]}
        assert {"send", "select", "text", "chip:looks-off"} <= ids and st["ui"]["attach"]["kind"] == "area"
        b.close()
        assert errors == [], errors


# ------------------------------------------------------------------ decision 77a b: Claude's test hook
def test_test_target_and_refusal_follow_the_overlay_rules():
    assert core.test_target("select_area", {"x1": 300, "y1": 200.4, "x2": 100, "y2": 50}) == ("area", {"rect": [300, 200, 100, 50]})
    assert core.test_target("point", {"x": 5, "y": 6}) == ("point", {"x": 5, "y": 6})
    for bad in [("select_area", {"x1": 1, "y1": 1, "x2": 3, "y2": 3}), ("select_area", {"x1": 1, "y1": 1, "x2": 90, "y2": 1}),
                ("select_area", {"x1": 1}), ("point", {}), ("drag", {})]:
        with pytest.raises(ValueError):
            core.test_target(*bad)
    wins = [{"app": "Bitwarden.exe", "title": "Vault - Bitwarden", "rect": (500, 500, 900, 900)},
            {"app": "chrome.exe", "title": WIN["title"], "rect": (0, 0, 1920, 1040)}]
    assert core.test_refusal("area", {"rect": [0, 0, 400, 400]}, wins, Z) is None
    assert "kept-out" in core.test_refusal("area", {"rect": [450, 450, 520, 520]}, wins, Z)
    assert "kept-out" in core.test_refusal("area", {"rect": [600, 600, 700, 700]}, wins, Z)      # fully inside
    assert core.test_refusal("point", {"x": 499, "y": 600}, wins, Z) is None
    assert core.test_refusal("point", {"x": 500, "y": 600}, wins, Z)
    assert core.test_note("select_area", {"rect": [1, 2, 30, 40]}).startswith("test input from Claude")


def test_api_test_hook_select_area_attaches_notes_and_reports_state(api):
    call, hub, tokens, tmp, calls, base = api
    w = call.w
    call("/api/signin", {})
    call("/api/session/start", {})
    r = call("/api/test/select_area", {"x1": 0, "y1": 0, "x2": 200, "y2": 200})
    assert r[0] == 409 and "Watch is off" in r[1]["error"]
    (tmp / "gate" / "state.json").write_text(json.dumps({"watch": True}))
    w.hooks["visible"] = lambda: False
    r = call("/api/test/select_area", {"x1": 0, "y1": 0, "x2": 200, "y2": 200})
    assert r[0] == 409 and "isn't open" in r[1]["error"]
    w.hooks["visible"] = lambda: True
    w.hooks["windows"] = lambda: [{"app": "Bitwarden.exe", "title": "Vault - Bitwarden", "rect": (500, 500, 900, 900)}]
    r = call("/api/test/select_area", {"x1": 450, "y1": 450, "x2": 600, "y2": 600})
    assert r[0] == 403 and "kept-out" in r[1]["error"]
    assert call("/api/test/select_area", {"x1": 1, "y1": 1, "x2": 2, "y2": 2})[0] == 400
    assert call("/api/test/nope", {})[0] == 400
    calls.clear()
    code, out = call("/api/test/select_area", {"x1": 0, "y1": 0, "x2": 200, "y2": 200})
    assert code == 200 and out["event"]["kind"] == "area" and out["elements"] == ["Save"] and out["seq"] == 1
    assert calls == ["hide", "show"]                       # the same hide/capture/show as a real Select
    st = call("/api/state")[1]["test"]
    assert st["seq"] == 1 and st["event"]["id"] == out["event"]["id"] and st["note"].startswith("test input from Claude")
    # the page reports what it shows; Claude's 'state' reads it back with the last chat rows
    call("/api/ui", {"chip": "looks-off", "attach": {"id": out["event"]["id"], "words": out["event"]["words"]}, "picture": True,
                     "controls": [{"id": "send", "label": "Send"}], "junk": "dropped"})
    call("/api/send", {"text": "header too tall", "chip": "looks-off", "opts": {"compare": "none"}, "attach": out["event"]["id"]})
    code, s = call("/api/test/state", {})
    assert code == 200 and s["ui"]["chip"] == "looks-off" and "junk" not in s["ui"] and s["ui"]["controls"][0]["id"] == "send"
    assert [x for x in s["chat_last5"] if x["kind"] == "line"][-1]["text"] == "[looks-off] header too tall" and s["window_open"] and s["last_test"]["seq"] == 1
    assert hub.docs[-1]["event"]["body"]["point"]["kind"] == "area"
    code, out = call("/api/test/point", {"x": 5, "y": 5})
    assert code == 200 and out["event"]["kind"] == "pointer.desktop" and out["seq"] == 2


def test_real_capture_pipeline_runs_without_the_overlay(tmp_path, monkeypatch):
    """_win_test_capture goes through watch_win.capture with the overlay swapped for the test's result."""
    PIL = pytest.importorskip("PIL.Image")
    import watch_win
    monkeypatch.setattr(watch_win, "AVAILABLE", True)
    monkeypatch.setattr(watch_win, "HOME", tmp_path)
    monkeypatch.setattr(watch_win, "POINTER_EVENTS", tmp_path / "pointer.jsonl")
    img = PIL.new("RGB", (1000, 800), (200, 200, 200))
    monkeypatch.setattr(watch_win, "grab_redacted", lambda zones: (img, (0, 0), {"left": 0, "top": 0, "right": 1000, "bottom": 800}))
    monkeypatch.setattr(watch_win, "elements_in", lambda a: [el("Save", 10, 10, 50, 30)])
    monkeypatch.setattr(watch_win, "window_at", lambda x, y: {"app": "chrome.exe", "title": WIN["title"]})
    monkeypatch.setattr(watch_win, "run_overlay", lambda *a, **k: (_ for _ in ()).throw(AssertionError("overlay ran")))
    r = server._win_test_capture("area", Z, {"rect": [0, 0, 300, 200]})
    e = r["event"]
    assert e["kind"] == "area" and [x["name"] for x in e["elements"]] == ["Save"] and Path(e["screenshot"]).exists()
    assert PIL.open(e["screenshot"]).size == (300, 200)
    assert json.loads((tmp_path / "events.jsonl").read_text())["id"] == e["id"]


# ------------------------------------------------------------------ 21 Nov: placement at display scaling
@pytest.mark.parametrize("work,scale", [((0, 0, 1920, 1032), 1.25), ((0, 0, 1536, 824), 1.0), ((0, 0, 3840, 2088), 1.5),
                                        ((0, 0, 1366, 728), 1.25), ((-1920, 0, 0, 1040), 1.0), ((0, 48, 1280, 720), 2.0)])
def test_place_lands_inside_the_work_area_on_the_right(work, scale):
    r = core.place(work, scale, (400, 820))
    l, t, rr, b = work
    assert l <= r["x"] and r["x"] + r["width"] <= rr and t <= r["y"] and r["y"] + r["height"] <= b
    if rr - l >= r["width"] + 40 and b - t >= 600 * scale:
        assert r["x"] + r["width"] == rr - 20 and r["y"] == t + 20


def test_place_at_125_percent_on_1080p():
    r = core.place((0, 0, 1920, 1032), 1.25, (400, 820))
    assert (r["x"], r["y"], r["width"], r["height"]) == (1400, 20, 500, 992)
    assert (r["lx"], r["ly"], r["lwidth"], r["lheight"]) == (1120, 16, 400, 794)
    tiny = core.place((0, 0, 300, 400), 1.0, (400, 820))
    assert (tiny["x"], tiny["y"], tiny["width"], tiny["height"]) == (0, 0, 300, 400)    # clamped, never outside


# ------------------------------------------------------------------ 21 Nov: code changes load by themselves
def test_reload_decision_restarts_for_python_reloads_for_web_and_waits_for_captures(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "watch_app.py").write_text("a")
    (tmp_path / "web" / "watch.js").write_text("a")
    (tmp_path / "notes.txt").write_text("a")
    s0 = core.files_signature(tmp_path)
    assert [n for n, *_ in s0["py"]] == ["watch_app.py"] and [n for n, *_ in s0["web"]] == ["watch.js"]
    assert core.reload_decision(s0, core.files_signature(tmp_path), False) is None
    (tmp_path / "notes.txt").write_text("changed")
    assert core.reload_decision(s0, core.files_signature(tmp_path), False) is None    # not Watch's code
    (tmp_path / "web" / "watch.js").write_text("bb")
    s1 = core.files_signature(tmp_path)
    assert core.reload_decision(s0, s1, False) == "reload"
    assert core.reload_decision(s0, s1, True) is None                                  # mid-capture: later
    (tmp_path / "watch_app.py").write_text("bb")
    s2 = core.files_signature(tmp_path)
    assert core.reload_decision(s1, s2, False) == "restart"
    (tmp_path / "web" / "watch.css").write_text("x")
    assert core.reload_decision(s1, core.files_signature(tmp_path), False) == "restart"  # both: restart covers the page
    assert core.reload_decision(None, s2, False) is None


def test_watch_for_changes_waits_out_a_capture_then_restarts(tmp_path, monkeypatch):
    import threading
    import watch_app
    (tmp_path / "watch_app.py").write_text("a")
    monkeypatch.setattr(watch_app, "HERE", tmp_path)
    w = type("W", (), {"capturing": True, "notes": [], "note": lambda self, *a: self.notes.append(a)})()
    did, stop = [], threading.Event()
    t = threading.Thread(target=watch_app.watch_for_changes, args=(w, lambda: did.append("restart"), lambda: did.append("reload"), stop, 0.05))
    t.start()
    import time as _t
    _t.sleep(0.15)
    (tmp_path / "watch_app.py").write_text("changed")
    _t.sleep(0.3)
    assert did == []                         # mid-capture: nothing yet
    w.capturing = False
    t.join(3)
    stop.set()
    assert did == ["restart"] and w.notes[0][0] == "restart"


# ------------------------------------------------------------------ 0.2.2: SC-golden-looksoff-1 issues 2-6 and quick answers
def test_app_label_names_nodach_windows_by_title_and_others_by_app():
    own = {"process": {"name": "pythonw.exe"}, "window": {"title": "Nodach Desktop"}}
    assert core.app_label(own) == "Nodach Desktop"
    assert core.app_label({"process": {"name": "pythonw.exe"}, "window": {"title": "C:\\Users\\akabd\\notes.txt"}}) == "Nodach"
    assert core.app_label({"process": {"name": "chrome.exe"}, "window": {"title": "Payroll - Google Chrome"}}) == "Chrome"
    assert core.app_label({"process": {"name": "SomeTool.exe"}}) == "SomeTool"
    a = core.area_event(T, area=(0, 0, 99, 99), elements=[el("", 1, 1, 9, 9), el("Versions", 1, 1, 9, 9), el("", 2, 2, 8, 8),
                                                          el("shell 0.1.0", 1, 1, 9, 9), el("gate 0.2.0", 1, 1, 9, 9), el("live 0.2.2", 1, 1, 9, 9)],
                        window={"title": "Nodach Desktop"}, process={"name": "pythonw.exe"})
    w = core.point_words(a)
    assert w == "⌖ Nodach Desktop › area: “Versions”, “shell 0.1.0”, “gate 0.2.0” +1 more" and "pythonw" not in w
    blank = core.area_event(T, area=(0, 0, 99, 99), elements=[el("", 1, 1, 9, 9)], window=WIN, process=PROC)
    assert core.point_words(blank) == "⌖ Chrome › an area (1 unnamed parts)"
    sh = core.shareable(a)
    assert sh["app"] == "Nodach Desktop" and "pythonw" not in json.dumps(sh)


def test_reply_labels_claude_quick_answer_and_you():
    me = {"id": "github:x", "role": "owner", "label": "Morami49"}
    d = [{"doc_id": "a", "event": {"ts": "2026-11-21T13:00:01.000Z", "kind": "live.line", "item": "LV-9", "author": me, "body": {"speaker": "Morami49", "text": "looks off"}}},
         {"doc_id": "b", "event": {"ts": "2026-11-21T13:00:02.000Z", "kind": "comment", "item": "LV-9", "author": me, "via": "claude-connector", "body": {"text": "fix"}}},
         {"doc_id": "c", "event": {"ts": "2026-11-21T13:00:03.000Z", "kind": "comment", "item": "LV-9", "via": "live-responder",
                                   "author": {"id": "agent:live-responder", "label": "Live responder (Gemini)", "role": "agent"}, "body": {"text": "quick", "line": "a"}}}]
    rows = core.stream_rows(d, "LV-9", me_id="github:x")
    assert [r["who"] for r in rows] == ["You", "Claude", "Quick answer (Gemini)"] and [r["kind"] for r in rows] == ["line", "reply", "reply"]
    assert not any("via Claude" in r["who"] for r in rows)


def test_glitch_offer_skips_clips_before_watch_on_and_nodach_windows():
    old = [{"kind": "action", "_t": 10, "app": "chrome.exe"}, {"kind": "clip", "_t": 20, "trigger": "glitch", "path": "old.gif"}]
    assert core.glitch_offer(old, {}, 5000, since=4000) is None
    own = [{"kind": "action", "_t": 4100, "app": "pythonw.exe"}, {"kind": "clip", "_t": 4110, "trigger": "glitch", "path": "own.gif"}]
    assert core.glitch_offer(own, {}, 5000, since=4000) is None
    fresh = old + [{"kind": "action", "_t": 4100, "app": "chrome.exe"}, {"kind": "clip", "_t": 4120, "trigger": "glitch", "path": "new.gif"}]
    asked = {}
    assert core.glitch_offer(fresh, asked, 5000, since=4000)["clip"] == "new.gif"
    assert core.glitch_offer(fresh, asked, 5001, since=4000) is None       # dedupe: asked once


def test_idle_and_responder_helpers():
    d = [{"doc_id": "s", "event": {"ts": "2026-11-20T18:34:50.000Z", "kind": "item.create", "body": {"id": "LV-1", "live": {"responder": True}}}},
         {"doc_id": "l", "event": {"ts": "2026-11-20T18:40:00.000Z", "kind": "live.line", "item": "LV-1", "body": {"text": "x"}}},
         {"doc_id": "e", "event": {"ts": "2026-11-20T18:41:00.000Z", "kind": "item.edit", "item": "LV-1", "body": {"live": {"responder": False}}}}]
    last = core.last_activity(d, "LV-1")
    assert core.is_idle(d, "LV-1", last + 29 * 60, 30) is False and core.is_idle(d, "LV-1", last + 31 * 60, 30) is True
    assert core.is_idle(d, "LV-1", last + 10 ** 6, 0) is False                       # 0 turns ending off
    assert core.idle_minutes({}) == 30 and core.idle_minutes({"idle_end_minutes": "5"}) == 5
    assert core.responder_on(d, "LV-1") is False and core.responder_on(d[:2], "LV-1") is True and core.responder_on([], "LV-1") is None
    p = {"session": "LV-1", "line": "l", "ts": "2026-11-20T18:40:00.000Z", "t": 100.0}
    assert "off for this session" in core.wait_row(p, [], d, 101)["text"]
    assert core.wait_row(p, [], d[:2], 101)["text"].startswith("Waiting for a quick answer")
    assert "No quick answer came" in core.wait_row(p, [], d[:2], 100 + core.WAIT_S + 1)["text"]
    assert core.wait_row(p, [{"kind": "reply", "ts": "2026-11-20T18:40:05.000Z"}], d[:2], 101) is None


def test_api_quiet_session_ends_and_the_line_goes_to_a_new_one(api):
    call, hub, tokens, tmp, *_ = api
    call("/api/signin", {})
    sid = call("/api/session/start", {})[1]["session"]
    hub.docs[0]["event"]["ts"] = "2026-11-20T18:34:50.000Z"                      # started yesterday, never used since
    call.w.pull(force=True)
    code, r = call("/api/send", {"text": "the versions line is cramped"})
    assert code == 200 and r["session"] != sid
    ended = [d["event"] for d in hub.docs if d["event"].get("item") == sid and d["event"]["kind"] == "item.edit"]
    assert ended and "quiet minutes" in ended[0]["body"]["body"]
    line = next(d["event"] for d in hub.docs if d["event"]["kind"] == "live.line")
    assert line["item"] == r["session"]
    rows = call(f"/api/stream?session={r['session']}")[1]["rows"]
    assert any(x["kind"] == "note" and "quiet" in x["text"] for x in rows)
    assert rows[-1]["kind"] == "wait" and rows[-1]["text"].startswith("Waiting for a quick answer")
    assert [x["who"] for x in rows if x["kind"] == "line"] == ["You"]
    hub.post({"ts": "2099-01-01T00:00:00.000Z", "kind": "comment", "item": r["session"], "via": "live-responder",
              "author": {"id": "agent:live-responder", "label": "Live responder (Gemini)", "role": "agent"}, "body": {"text": "Try a wider box", "line": "x"}})
    call.w.pull(force=True)
    rows = call(f"/api/stream?session={r['session']}")[1]["rows"]
    assert rows[-1]["who"] == "Quick answer (Gemini)" and not any(x["kind"] == "wait" for x in rows)


def test_api_test_input_note_is_in_the_stream(api):
    call, hub, tokens, tmp, *_ = api
    (tmp / "gate" / "state.json").write_text(json.dumps({"watch": True}))
    call("/api/signin", {})
    sid = call("/api/session/start", {})[1]["session"]
    assert call("/api/test/select_area", {"x1": 0, "y1": 0, "x2": 200, "y2": 200})[0] == 200
    st = call("/api/test/state", {})[1]
    assert any(r["who"] == "Watch" and r["text"].startswith("Test input from Claude") for r in st["chat_last5"])


def test_ended_title_matches_studio():
    import watch_server as ws
    assert ws.ended_title("LV-261121-143725-eb46") == "Live session (ended) 2026-11-21 14:37"
    assert ws.ended_title("weird") == "Live session (ended)"
