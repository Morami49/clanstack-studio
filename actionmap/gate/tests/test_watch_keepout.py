"""Watch v0 rules in Gate: the Watch-off refusal (DRV4) and the user keep-out list (DRV7b).
python -m pytest -q actionmap/gate/tests"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GATE))
import gate_core as core   # noqa: E402

RAW = json.loads((GATE / "zones.json").read_text(encoding="utf-8"))
Z = core.load_zones(None)


def d(tool, args=None, **ctx):
    return core.decide({"tool": tool, "args": args or {}}, ctx, Z)


# ------------------------------------------------------------------ Watch off
@pytest.mark.parametrize("tool", sorted(core.WATCH_TOOLS))
def test_watch_off_refuses_every_screen_tool(tool):
    args = {"loc": [1, 1], "text": "x", "shortcut": "ctrl+c", "mode": "switch", "name": "Notepad", "note": "n"}
    for ctx in ({}, {"watch": False}, {"watch": "false"}):           # missing counts as off
        z, r = d(tool, args, app="notepad.exe", title="Untitled - Notepad", **ctx)
        assert (z, r) == ("never", core.WATCH_OFF) == ("never", "Watch is off: turn it on in Nodach Desktop")


@pytest.mark.parametrize("tool", ["gate_status", "Wait", "ControlStatus"])
def test_watch_off_keeps_status_and_passive_tools(tool):
    assert d(tool, {}, app="notepad.exe")[0] == "auto"


def test_watch_on_goes_back_to_the_zones():
    assert d("Type", {"loc": [1, 1], "text": "x"}, app="notepad.exe", title="Untitled - Notepad", watch=True)[0] == "auto"
    assert d("capture_view", {"note": "x"}, watch=True)[0] == "auto"
    assert d("Click", {"loc": [1, 1]}, app="Bitwarden.exe", title="Bitwarden", watch=True)[0] == "never"   # never stays never
    assert d("Click", {"loc": [1, 1]}, app="notepad.exe", watch=True, paused=True)[1].startswith("Gate is paused")


def test_watch_off_refusals_are_not_auto_reported():
    e = {"kind": "action", "zone": "never", "decision": "refused", "reason": core.WATCH_OFF}
    assert core.auto_report_trigger(e, {"send_automatically": True, "never_block": True}) is None


def test_shipped_zones_have_the_keep_out_group_with_nodach_sec():
    assert RAW["revision"] >= 4 and RAW["_changes"][-1]["by"] == "Nowed"
    g = core.keep_out_group(RAW)
    assert g and g["applies_to"] == "all"
    assert any(e["kind"] == "folder" and e["path"].lower().endswith("nodach_sec") for e in g["entries"])
    assert any(gr["name"] == "secrets in files" for gr in RAW["never"])        # the secrets group stays active
    assert d("Snapshot", app="explorer.exe", title="nodach_sec - File Explorer", watch=True)[0] == "never"
    assert d("Click", {"loc": [1, 1]}, app="Code.exe", title="C:\\Users\\a\\Desktop\\Nodach\\nodach_sec\\x - VS Code", watch=True)[0] == "never"


# ------------------------------------------------------------------ keep-out entries
def test_keep_out_entry_from_a_window_title():
    e = core.keep_out_entry("window", process="chrome.exe", title="(3) Inbox - Mail - Google Chrome")
    assert e == {"kind": "window", "process": "chrome.exe", "title_words": ["Inbox - Mail"]}
    with pytest.raises(ValueError):
        core.keep_out_entry("window")
    with pytest.raises(ValueError):
        core.keep_out_entry("folder", path=" ")
    with pytest.raises(ValueError):
        core.keep_out_entry("thing", process="x")


def test_keep_out_matching():
    win = core.keep_out_entry("window", process="chrome.exe", title="Payroll sheet - Google Chrome")
    app = core.keep_out_entry("app", process="Signal.exe")
    fol = core.keep_out_entry("folder", path="C:/Users/a/Documents/Tax")
    es = [win, app, fol]
    assert core.keep_out_hit(es, "chrome.exe", "Payroll sheet - Google Chrome")
    assert not core.keep_out_hit(es, "msedge.exe", "Payroll sheet - Edge")          # other app, same words: in scope
    assert core.keep_out_hit(es, "", "Payroll sheet - Google Chrome")               # no process known: hide
    assert core.keep_out_hit(es, "signal", "anything")
    assert core.keep_out_hit(es, "explorer.exe", "C:\\Users\\a\\Documents\\Tax")
    assert core.keep_out_hit(es, "explorer.exe", "Tax - File Explorer")
    assert not core.keep_out_hit(es, "notepad.exe", "Tax - Notepad")
    assert not core.keep_out_hit(es, "notepad.exe", "Untitled - Notepad")


def test_keep_out_add_and_remove_are_versioned():
    rev = RAW["revision"]
    e = core.keep_out_entry("app", process="Signal.exe")
    z1, added = core.keep_out_add(RAW, e, by="Nowed", date="2026-11-22")
    assert z1 is not RAW and RAW["revision"] == rev                               # the input isn't changed
    assert z1["revision"] == rev + 1 and z1["_changes"][-1] == {
        "revision": rev + 1, "date": "2026-11-22", "by": "Nowed", "what": f"Nowed kept out app Signal.exe ({added['id']})"}
    assert added["id"].startswith("KO-") and added["by"] == "Nowed" and added["added"] == "2026-11-22"
    z2, again = core.keep_out_add(z1, core.keep_out_entry("app", process="signal"))   # same app: no new revision
    assert z2 is z1 and again["id"] == added["id"]
    zl = core.parse_zones(json.dumps(z1))
    assert core.decide({"tool": "Click", "args": {"loc": [1, 1]}}, {"app": "Signal.exe", "title": "Signal", "watch": True}, zl)[1] \
        == "user keep-out: kept-out app Signal.exe"
    z3, gone = core.keep_out_remove(z1, added["id"], date="2026-11-23")
    assert gone["id"] == added["id"] and z3["revision"] == rev + 2 and "removed" in z3["_changes"][-1]["what"]
    assert all(x["id"] != added["id"] for x in core.keep_out_entries(z3))
    assert core.keep_out_remove(z3, "KO-nothere")[1] is None


def test_keep_out_group_created_when_missing():
    raw = {"revision": 1, "never": [], "_changes": []}
    z, e = core.keep_out_add(raw, core.keep_out_entry("folder", path="D:\\Private"), date="2026-11-22")
    assert core.keep_out_group(z)["entries"][0]["path"] == "D:\\Private" and z["revision"] == 2


def test_upgrade_keeps_his_keep_out_entries():
    user, _ = core.keep_out_add(RAW, core.keep_out_entry("app", process="Signal"), date="2026-11-22")
    default = json.loads(json.dumps(RAW))
    default["revision"] = user["revision"] + 1
    merged, added = core.upgrade_zones(user, default)
    assert added == [] and len(core.keep_out_entries(merged)) == len(core.keep_out_entries(user))


# ------------------------------------------------------------------ redaction
SNAP = '''Focused Window:
Payroll sheet - Google Chrome
Opened Windows:
Signal
Untitled - Notepad
UI Tree:
desktop
├── window "Payroll sheet - Google Chrome"
│   └── (1,1) cell "Salary 50,000"  [action: click]
├── window "Signal"
│   └── (2,2) list item "Chat with Sam"  [action: click]
└── window "Untitled - Notepad"
    └── (3,3) edit "Text editor"  [action: type]'''


def test_keep_out_windows_are_redacted_from_snapshot_text():
    z1, _ = core.keep_out_add(RAW, core.keep_out_entry("window", process="chrome.exe", title="Payroll sheet - Google Chrome"))
    z2, _ = core.keep_out_add(z1, core.keep_out_entry("app", process="Signal.exe"))
    zl = core.parse_zones(json.dumps(z2))
    hide = core.keep_out_titles(zl, [{"app": "Signal.exe", "title": "Signal"}, {"app": "notepad.exe", "title": "Untitled - Notepad"}])
    assert hide == ["Signal"]
    out, n = core.redact_snapshot(SNAP, zl, hide)
    assert "Salary" not in out and "Chat with Sam" not in out and "Payroll" not in out and n == 2
    assert "Text editor" in out and "Untitled - Notepad" in out


# ------------------------------------------------------------------ through Gate (fake Windows-MCP)
def test_gate_refuses_while_watch_is_off_and_logs_it(tmp_path):
    pytest.importorskip("mcp")
    import gate_mcp
    import gate_win
    from test_gate import FakeStudio

    async def go(state):
        (tmp_path / "state.json").write_text(json.dumps(state))
        g = gate_mcp.Gate(ctxp=gate_win.NullContext(app="notepad.exe", title="Untitled - Notepad"), home=tmp_path,
                          popup=lambda r: "timeout", child_cmd=[sys.executable, str(GATE / "tests" / "fake_wmcp.py")],
                          studio_mod=FakeStudio(), autostart_gui=False)
        async with contextlib.AsyncExitStack() as stack:
            await g.connect(stack)
            return [await g.call(n, a) for n, a in (("Snapshot", {}), ("capture_view", {"note": "x"}), ("gate_status", {}), ("Wait", {"duration": 0}))]
    off = asyncio.run(go({}))
    txt = lambda r: " ".join(c["text"] if isinstance(c, dict) else c.text for c in r["content"])
    assert off[0]["is_error"] and txt(off[0]).startswith(core.WATCH_OFF)
    assert off[1]["is_error"] and txt(off[1]).startswith(core.WATCH_OFF)
    assert json.loads(txt(off[2]))["watch"] is False and not off[3]["is_error"]
    log = [json.loads(x) for x in (tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    refused = [e for e in log if e.get("kind") == "action" and e.get("reason") == core.WATCH_OFF]
    assert [e["tool"] for e in refused] == ["Snapshot", "capture_view"] and refused[0]["by"] == "watch"
    on = asyncio.run(go({"watch": True}))
    assert not on[0]["is_error"] and json.loads(txt(on[2]))["watch"] is True


# ------------------------------------------------------------------ U16: privacy moments
def test_privacy_moment_detection():
    assert core.privacy_moment("Sign in - Google Accounts - Google Chrome") == "sign-in page"
    assert core.privacy_moment("Shop", "Password", True) == "sign-in page"
    assert core.privacy_moment("Shop", elements=[{"name": "x", "password": True}]) == "sign-in page"
    assert core.privacy_moment("Basket", elements=["Card number", "Pay now"]) == "payment form"
    assert core.privacy_moment("Checkout - Shop") == "payment form"
    assert core.privacy_moment("Untitled - Notepad", "Text editor") is None
    assert core.privacy_moment("Blogging tips") is None and core.privacy_moment("Catalogue") is None   # whole words only


def test_watch_pauses_itself_on_sign_in_and_payment_and_resumes():
    z, r = d("Snapshot", app="chrome.exe", title="Log in to Studio", watch=True)
    assert z == "never" and r == "Watch paused itself: a sign-in page is in front (it resumes when it's gone)"
    assert d("Click", {"loc": [1, 1]}, app="notepad.exe", title="Untitled - Notepad", fg_title="Payment - Shop", watch=True)[1].startswith(core.PRIVACY_PAUSE)
    assert d("Snapshot", app="notepad.exe", title="Untitled - Notepad", fg_title="Untitled - Notepad", watch=True)[0] == "auto"
    assert d("gate_status", title="Log in", watch=True)[0] == "auto" and d("Wait", {}, title="Log in", watch=True)[0] == "auto"
    e = {"kind": "action", "zone": "never", "decision": "refused", "reason": r}
    assert core.auto_report_trigger(e, {"send_automatically": True, "never_block": True}) is None
