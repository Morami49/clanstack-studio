"""
Nodach Watch (Driver's Watch v0): pure logic, no Windows, no network, so every rule is tested on any OS.

The Watch window (web UI in web/, served by watch_server.py, shown by watch_app.py) calls these to:
  - build what you point at, select or mark up as pointer.v1 events      point_event / area_event / markup_event
  - keep never-zone and kept-out windows out of every crop and list       redact_rects / filter_elements
  - say what may go into the shared record                                 shareable / point_words
  - turn the chips (Looks off, Mark up, Explain this) into line fields     chip_fields / compose_line
  - read the session stream the way Studio's Live panel does               stream_rows / session_list
  - edit the user keep-out list in zones.json (versioned)                  edit_zones / keep_out_add / keep_out_remove
  - build the status strip                                                 status_strip

Event kinds (all schema pointer.v1, mode "watch", ids PE-yymmdd-hhmmss-xxxx that never change):
  pointer.desktop  one element (Point): the same shape as the Nodach Pointer's events
  area             a rectangle (Select area): crop + the UI Automation elements inside it
  markup           ordered marks (Mark up): arrow, box, path, text, step, branch ('if…' / 'else…'), for any app:
                   where a thing should go, a task's steps with if/then branches, a design being changed, a plan
                   for a cross-app automation. 'Wrong place' is one preset (one arrow from the element to where it
                   should be: {from, to} rects).
Screenshots stay on this PC. Only names, rects and notes go into a shared line; a picture goes to the owner-only
Private tier, and only when the line is sent with 'attach picture' ticked.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import sys
from pathlib import Path

VERSION = "0.2.2"
SCHEMA = "pointer.v1"
TOOL = "nodach-watch"
HERE = Path(__file__).resolve().parent
APP = HERE.parent
# app\watch next to app\gate, app\live, app\shell (Nodach Desktop); in the repo shell is actionmap\desktop\shell
for _p in (APP / "gate", APP / "live", APP / "shell", APP / "desktop" / "shell"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import gate_core   # noqa: E402  (the zones and keep-out rules live in Gate: one place for every never rule)

MAX_ELEMENTS = 40
MAX_MARKS = 60
MAX_PATH_POINTS = 200
MARK_TYPES = ("arrow", "box", "path", "text", "step", "branch")
SECRET_DIR = "nodach_sec"          # never read or referenced (Nowed, 21 Nov)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(t: dt.datetime) -> str:
    return f"PE-{t.astimezone(dt.timezone.utc):%y%m%d-%H%M%S}-{secrets.token_hex(2)}"


# ---------------------------------------------------------------- geometry
def rect(l, t, r, b) -> dict:
    l, r = sorted((int(l), int(r)))
    t, b = sorted((int(t), int(b)))
    return {"left": l, "top": t, "right": r, "bottom": b}


def as_rect(x) -> dict | None:
    if not x:
        return None
    if isinstance(x, dict):
        return rect(x["left"], x["top"], x["right"], x["bottom"])
    return rect(*x)


def union(rects) -> dict | None:
    rs = [as_rect(r) for r in rects if r]
    if not rs:
        return None
    return {"left": min(r["left"] for r in rs), "top": min(r["top"] for r in rs),
            "right": max(r["right"] for r in rs), "bottom": max(r["bottom"] for r in rs)}


def inside(inner, outer) -> bool:
    i, o = as_rect(inner), as_rect(outer)
    return bool(i and o) and i["left"] >= o["left"] and i["top"] >= o["top"] and i["right"] <= o["right"] and i["bottom"] <= o["bottom"]


def overlaps(a, b) -> bool:
    a, b = as_rect(a), as_rect(b)
    return bool(a and b) and a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


def pad(r, n: int, screen=None) -> dict:
    r = as_rect(r)
    out = {"left": r["left"] - n, "top": r["top"] - n, "right": r["right"] + n, "bottom": r["bottom"] + n}
    if screen:
        s = as_rect(screen)
        out = {"left": max(out["left"], s["left"]), "top": max(out["top"], s["top"]),
               "right": min(out["right"], s["right"]), "bottom": min(out["bottom"], s["bottom"])}
    return out


def _pt(p) -> dict:
    if isinstance(p, dict):
        return {"x": int(p["x"]), "y": int(p["y"])}
    return {"x": int(p[0]), "y": int(p[1])}


# ---------------------------------------------------------------- never zones and keep-out
def never_reason(zones: dict, app: str, title: str) -> str | None:
    """Why a window must stay out of Watch (never group, user keep-out, a nodach_sec path), else None."""
    if SECRET_DIR in str(title or "").lower():
        return "secrets in files: nodach_sec"
    r = gate_core._never(zones, app or "", title or "", "", input_action=False)
    if r:
        return r
    pm = gate_core.privacy_moment(title or "") if zones.get("privacy_moments", True) else None
    return f"privacy moment: {pm}" if pm else None


def redact_rects(windows, zones: dict) -> list[dict]:
    """Screen rectangles to black out of any picture: every visible window in a never group or kept out.
    windows: [{app, title, rect}] (rect dict or (l, t, r, b)). Covers more than needed where windows overlap."""
    out = []
    for w in windows or []:
        if w.get("rect") and never_reason(zones, w.get("app"), w.get("title")):
            out.append(as_rect(w["rect"]))
    return out


def clean_element(e: dict) -> dict:
    return {"type": str(e.get("type") or "")[:40], "name": str(e.get("name") or "")[:200],
            "automation_id": str(e.get("automation_id") or "")[:80], "class_name": str(e.get("class_name") or "")[:80],
            "rect": as_rect(e.get("rect"))}


def filter_elements(elements, zones: dict):
    """(kept, dropped count): elements whose window is never/kept out are dropped, and so is any element whose name
    names a secret (the 'secrets in files' words, as Gate hides them in Snapshot text)."""
    words = [w for g in zones.get("never", []) if g.get("redact_elements") for w in (g.get("title_words") or [])]
    rx = gate_core._rx(words)
    kept, dropped = [], 0
    for e in elements or []:
        w = e.get("window") or {}
        if never_reason(zones, e.get("app") or w.get("app"), w.get("title") or e.get("window_title")) \
                or (rx and rx.search(str(e.get("name") or ""))) or SECRET_DIR in str(e.get("name") or "").lower():
            dropped += 1
            continue
        kept.append(clean_element(e))
    return kept[:MAX_ELEMENTS], dropped + max(0, len(kept) - MAX_ELEMENTS)


# ---------------------------------------------------------------- events
def _base(kind: str, t: dt.datetime, window: dict | None, process: dict | None, screenshot, shot_box, note=None) -> dict:
    return {"schema": SCHEMA, "tool": TOOL, "tool_version": VERSION, "id": new_id(t), "kind": kind, "mode": "watch",
            "at": iso(t), "window": {"title": str((window or {}).get("title") or "")[:200],
                                      "class_name": (window or {}).get("class_name") or ""},
            "process": {"name": (process or {}).get("name") or "", "pid": (process or {}).get("pid")},
            "shot_box": list(shot_box) if shot_box else None, "screenshot": screenshot, "note": note, "batch_refs": []}


def kept_out_event(kind: str, t: dt.datetime, reason: str) -> dict:
    """What is left of a point/area/markup that landed on a never or kept-out window: the reason, nothing else."""
    e = _base(kind, t, None, None, None, None)
    e.update(kept_out=reason.split(":")[0], element={"type": "", "name": "", "automation_id": "", "class_name": "", "rect": None})
    return e


def point_event(t: dt.datetime, *, cursor, element: dict, window: dict, process: dict, ancestors=(), screenshot=None,
                shot_box=None, opaque=False, zones: dict | None = None) -> dict:
    """One element (Point), the Nodach Pointer's shape (kind pointer.desktop), mode 'watch'."""
    if zones is not None:
        r = never_reason(zones, process.get("name"), window.get("title"))
        if r:
            return kept_out_event("pointer.desktop", t, r)
    e = _base("pointer.desktop", t, window, process, screenshot, shot_box)
    e.update(cursor=_pt(cursor), element=clean_element(element), opaque=bool(opaque),
             ancestors=[{"type": str(a.get("type") or "")[:40], "name": str(a.get("name") or "")[:80]} for a in list(ancestors)[:8]],
             screenshot_error=None)
    return e


def area_event(t: dt.datetime, *, area, elements, window: dict, process: dict, screenshot=None, zones: dict | None = None) -> dict:
    """A rectangle (Select area): the crop and the elements inside it (kind 'area')."""
    zones = zones or {}
    r = never_reason(zones, process.get("name"), window.get("title"))
    if r:
        return kept_out_event("area", t, r)
    a = as_rect(area)
    inner = [e for e in elements or [] if not e.get("rect") or inside(e["rect"], a) or overlaps(e["rect"], a)]
    kept, dropped = filter_elements(inner, zones)
    e = _base("area", t, window, process, screenshot, [a["left"], a["top"], a["right"], a["bottom"]])
    e.update(rect=a, elements=kept, elements_hidden=dropped,
             element={"type": "area", "name": f"{len(kept)} element(s)", "automation_id": "", "class_name": "", "rect": a})
    return e


def _mark(m: dict, zones: dict) -> dict:
    k = m.get("type")
    if k not in MARK_TYPES:
        raise ValueError(f"mark type must be one of {MARK_TYPES}")
    out = {"type": k}
    if k == "arrow":
        out["from"], out["to"] = _pt(m["from"]), _pt(m["to"])
        for end in ("from", "to"):
            el = m.get(end + "_element")
            if el:
                kept, _ = filter_elements([el], zones)
                if kept:
                    out[end + "_element"] = kept[0]
                    out[end + "_rect"] = kept[0]["rect"]
            elif m.get(end + "_rect"):
                out[end + "_rect"] = as_rect(m[end + "_rect"])
    elif k == "box":
        out["rect"] = as_rect(m["rect"])
        if m.get("elements"):
            out["elements"], _ = filter_elements(m["elements"], zones)
    elif k == "path":
        pts = [_pt(p) for p in m.get("points") or []]
        if len(pts) > MAX_PATH_POINTS:      # keep the shape, drop points evenly
            step = len(pts) / MAX_PATH_POINTS
            pts = [pts[int(i * step)] for i in range(MAX_PATH_POINTS - 1)] + [pts[-1]]
        out["points"] = pts
    else:
        out["at"] = _pt(m["at"])
    if k in ("text", "step", "branch") or m.get("text"):
        out["text"] = str(m.get("text") or "")[:300]
    if k == "branch":
        lab = str(m.get("label") or "if").strip().lower()
        out["label"] = lab if lab in ("if", "else if", "else", "then") else "if"
        if m.get("of_step"):
            out["of_step"] = int(m["of_step"])
    return out


def _mark_points(m: dict):
    if m["type"] == "arrow":
        return [m["from"], m["to"]]
    if m["type"] == "box":
        r = m["rect"]
        return [{"x": r["left"], "y": r["top"]}, {"x": r["right"], "y": r["bottom"]}]
    if m["type"] == "path":
        return m["points"]
    return [m["at"]]


PRESETS = {
    "wrong-place": {"label": "Wrong place", "tool": "arrow",
                    "hint": "Drag from the thing that's in the wrong place to where it should be."},
    "steps": {"label": "Steps", "tool": "step", "hint": "Click to number each step; add 'if…' / 'else…' labels for branches."},
    "design": {"label": "Design", "tool": "box", "hint": "Box the parts to change; arrows and notes say how."},
    "automation": {"label": "Automation plan", "tool": "step",
                   "hint": "Number the steps across apps; an arrow carries data from one app to the next."},
}


def markup_event(t: dt.datetime, *, marks, window: dict, process: dict, screenshot=None, preset: str | None = None,
                 zones: dict | None = None, screen=None) -> dict:
    """Ordered marks (Mark up), kind 'markup'. Steps get numbers in order when they have none; a branch without
    of_step belongs to the step before it."""
    zones = zones or {}
    r = never_reason(zones, process.get("name"), window.get("title"))
    if r:
        return kept_out_event("markup", t, r)
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"preset must be one of {sorted(PRESETS)}")
    raw_marks = list(marks or [])[:MAX_MARKS]
    ms = [_mark(m, zones) for m in raw_marks]
    if not ms:
        raise ValueError("a mark-up needs at least one mark")
    step_n = 0
    for i, m in enumerate(ms, 1):
        m["n"] = i
        if m["type"] == "step":
            step_n = int((raw_marks[i - 1] or {}).get("step") or step_n + 1)
            m["step"] = step_n
        if m["type"] == "branch" and "of_step" not in m and step_n:
            m["of_step"] = step_n
    pts = [p for m in ms for p in _mark_points(m)]
    box = rect(min(p["x"] for p in pts), min(p["y"] for p in pts), max(p["x"] for p in pts), max(p["y"] for p in pts))
    box = pad(box, 40, screen)
    e = _base("markup", t, window, process, screenshot, [box["left"], box["top"], box["right"], box["bottom"]])
    kinds = {}
    for m in ms:
        kinds[m["type"]] = kinds.get(m["type"], 0) + 1
    e.update(preset=preset, marks=ms, rect=box,
             element={"type": "markup", "name": ", ".join(f"{v} {k}{'s' if v > 1 else ''}" for k, v in kinds.items()),
                      "automation_id": "", "class_name": "", "rect": box})
    return e


def wrong_place(t: dt.datetime, *, from_pt, to_pt, from_element=None, to_element=None, window: dict, process: dict,
                screenshot=None, zones=None, note: str = "") -> dict:
    """The 'Wrong place' preset: one arrow from the element to where it should go, recorded as {from, to} rects."""
    m = {"type": "arrow", "from": from_pt, "to": to_pt, "from_element": from_element, "to_element": to_element}
    if note:
        m["text"] = note
    return markup_event(t, marks=[m], window=window, process=process, screenshot=screenshot, preset="wrong-place", zones=zones)


# ---------------------------------------------------------------- what may be shared
_OWN_PROCS = {"python", "pythonw", "python3", "pythonw3", "nodach-watch"}
_FRIENDLY = {"chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "brave": "Brave", "explorer": "File Explorer",
             "notepad": "Notepad", "code": "VS Code", "claude": "Claude", "winword": "Word", "excel": "Excel",
             "powerpnt": "PowerPoint", "outlook": "Outlook", "teams": "Teams", "ms-teams": "Teams", "slack": "Slack"}


def app_label(e: dict) -> str:
    """The app as a person names it (SC-golden-looksoff-1 #3, 21 Nov: 'pythonw.exe' was shown for Nodach Desktop).
    Nodach's own windows run in python(w).exe, so they go by their window title (it never holds personal text);
    every other app goes by a friendly name from its process, never its window title (titles can hold file names,
    subjects and so on: shareable() keeps them out of the shared record)."""
    e = e or {}
    proc = str((e.get("process") or {}).get("name") or e.get("app") or "").strip()
    stem = proc.lower().removesuffix(".exe")
    title = str((e.get("window") or {}).get("title") or "").strip()
    if stem in _OWN_PROCS or stem.startswith("nodach"):
        if title.lower().startswith("nodach"):
            return title[:40]
        return "Nodach"
    if not stem:
        return "desktop"
    return _FRIENDLY.get(stem) or proc.removesuffix(".exe").removesuffix(".EXE")[:40]


def named_elements(elements, n: int = 3) -> tuple[list[str], int]:
    """The first n distinct element names (unnamed elements are left out of the words), and how many others there are."""
    names = []
    for x in elements or []:
        nm = re.sub(r"\s+", " ", str((x or {}).get("name") or "")).strip()
        if nm and nm not in names:
            names.append(nm[:40])
    shown = names[:n]
    return shown, len(names) - len(shown)


def point_words(e: dict) -> str:
    """Short words for a point, as Studio's livePointWords shows them."""
    if not e:
        return ""
    if e.get("kept_out"):
        return f"⌖ (kept out: {e['kept_out']})"
    app = app_label(e)
    if e.get("kind") == "area":
        shown, more = named_elements(e.get("elements"))
        if not shown:
            return f"⌖ {app} › an area" + (f" ({len(e.get('elements') or [])} unnamed parts)" if e.get("elements") else "")
        return f"⌖ {app} › area: " + ", ".join(f"“{x}”" for x in shown) + (f" +{more} more" if more else "")
    if e.get("kind") == "markup":
        return f"⌖ {app} › mark-up{' (' + PRESETS[e['preset']]['label'] + ')' if e.get('preset') in PRESETS else ''}: {(e.get('element') or {}).get('name', '')}"
    el = e.get("element") or {}
    return f"⌖ {app} › {el.get('name') or el.get('type') or 'element'}"


def shareable(e: dict, picture: dict | None = None) -> dict | None:
    """The part of a Watch event that may ride on a shared live line: app, element names/types and rects, marks and
    notes. Never window titles, file paths, ancestors' text, screenshots or cursor history. picture: the Private-tier
    reference ({name, bytes, sha256, private_path, chunks}) when 'attach picture' was ticked and the upload worked."""
    if not isinstance(e, dict) or e.get("schema") != SCHEMA:
        return None
    if e.get("kept_out"):
        return {"schema": SCHEMA, "kind": e.get("kind"), "id": e.get("id"), "kept_out": e["kept_out"]}
    el = e.get("element") or {}
    out = {"schema": SCHEMA, "kind": e.get("kind") or "pointer.desktop", "id": e.get("id"), "via": "watch",
           "app": app_label(e)[:60],
           "element": {"type": str(el.get("type") or "")[:40], "name": str(el.get("name") or "")[:80], "rect": el.get("rect")}}
    if e.get("kind") == "area":
        out["rect"] = e.get("rect")
        out["elements"] = [{"type": x["type"], "name": x["name"][:80], "rect": x.get("rect")} for x in e.get("elements") or []]
    if e.get("kind") == "markup":
        out["preset"] = e.get("preset")
        out["rect"] = e.get("rect")
        marks = []
        for m in e.get("marks") or []:
            m2 = {k: v for k, v in m.items() if not k.endswith("_element")}
            for end in ("from", "to"):
                if m.get(end + "_element"):
                    x = m[end + "_element"]
                    m2[end + "_element"] = {"type": x["type"], "name": x["name"][:80]}
            if m.get("elements"):
                m2["elements"] = [{"type": x["type"], "name": x["name"][:80]} for x in m["elements"]]
            marks.append(m2)
        out["marks"] = marks
    if e.get("note"):
        out["note"] = str(e["note"])[:500]
    out["words"] = point_words(e)
    # Studio's livePointWords reads part/element for non-desktop kinds: give it words, not an object
    if out["kind"] in ("area", "markup"):
        out["part"] = out["app"] or "desktop"
        out["element_words"] = point_words(e)
    if picture:
        out["picture"] = {k: picture[k] for k in ("name", "bytes", "sha256", "private_path", "chunks", "local") if k in picture}
    return out


# ---------------------------------------------------------------- chips and lines
CHIPS = {
    "looks-off": {"label": "Looks off", "use": "U1", "bar": "select"},
    "mark-up": {"label": "Mark up", "use": "U2", "bar": "markup"},
    "explain": {"label": "Explain this", "use": "U3", "bar": "select"},
    "report": {"label": "Report problem", "use": "U5", "bar": "select"},
}
# U5: when something can't be undone, the report becomes an 'irreversible incident' and nothing is reproduced
INCIDENT_FIELDS = ("what_happened", "known", "unknown", "state_changed", "affected", "recovery")
INCIDENT_LABELS = {"what_happened": "What happened", "known": "What's known", "unknown": "What can't be known",
                   "state_changed": "What state changed", "affected": "Who or what else is affected",
                   "recovery": "Suggested recovery"}
COMPARE = ("none", "earlier", "reference", "design", "clip")      # U1: judged by eye unless he picks one
SAVE = ("none", "personal", "developer")                          # U3: asked each time, default none


MARKUP_AS = ("line", "report", "for-claude")    # U2b: a mark-up goes out as a plain line, a report, or to Claude
AUDIENCES = ("stakeholder", "developer")         # U3b: who an explanation is for


def audience_for(me: dict | None) -> str:
    """U3b: explanations adapt to who's asking, from the signed-in profile (no button in v0). A profile that says
    stakeholder or developer wins; otherwise an owner gets developer depth and anyone else the stakeholder view."""
    me = me or {}
    for v in ((me.get("profile") or {}).get("audience"), me.get("audience"), (me.get("profile") or {}).get("role")):
        if v in AUDIENCES:
            return v
    return "developer" if me.get("owner") else "stakeholder"


def chip_fields(chip: str | None, opts: dict | None = None) -> tuple[str, dict]:
    """(tag, body.watch fields) for a chip. Unknown chips are refused, so a tag never means two things."""
    opts = opts or {}
    if not chip:
        return "", {}
    if chip not in CHIPS:
        raise ValueError(f"chip must be one of {sorted(CHIPS)}")
    f = {"chip": chip, "use": CHIPS[chip]["use"]}
    tag = chip
    if chip == "looks-off":
        c = opts.get("compare") or "none"
        if c not in COMPARE:
            raise ValueError(f"compare must be one of {COMPARE}")
        f["compare"] = c
        if c != "none" and opts.get("compare_ref"):
            f["compare_ref"] = {k: v for k, v in dict(opts["compare_ref"]).items() if k in ("id", "kind", "name", "sha256", "at", "words")}
    elif chip == "mark-up":
        p = opts.get("preset")
        if p:
            if p not in PRESETS:
                raise ValueError(f"preset must be one of {sorted(PRESETS)}")
            f["preset"] = p
            if p == "wrong-place":
                tag = "wrong-place"
        how = opts.get("as") or "line"
        if how not in MARKUP_AS:
            raise ValueError(f"as must be one of {MARKUP_AS}")
        f["as"] = how
        if how == "report":
            f["report"] = True
        if how == "for-claude":           # U2b (2): Claude carries it out through Gate (Gate's rules still apply)
            return f"[for-claude] [{tag}]", f
    elif chip == "report":
        irr = bool(opts.get("irreversible"))
        f["irreversible"] = irr
        if irr:
            tag = "irreversible"
            inc = opts.get("incident") or {}
            f["incident"] = {k: str(inc.get(k) or "").strip()[:600] for k in INCIDENT_FIELDS}
            f["reproduce"] = "never"          # the user said it can't be undone: nothing is replayed
        else:
            f["reproduce"] = "claude-may-try"  # Claude tries it through Gate first; may ask him to replay his steps
    elif chip == "explain":
        s = opts.get("save") or "none"
        if s not in SAVE:
            raise ValueError(f"save must be one of {SAVE}")
        f["save"] = s
        a = opts.get("audience") or "stakeholder"
        f["audience"] = a if a in AUDIENCES else "stakeholder"
    return f"[{tag}]", f


def compose_line(text: str, chip: str | None = None, opts: dict | None = None) -> tuple[str, dict]:
    """The line text (the chip's tag in front, once) and the body.watch fields."""
    tag, f = chip_fields(chip, opts)
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if tag and not t.lower().startswith(tag.split(" ")[0]):
        t = (tag + " " + t).strip()
    return t[:2000], f


def line_event(session: str, me: dict, text: str, t: dt.datetime, *, point=None, watch: dict | None = None,
               via: str = "watch", branch: str = "main") -> dict:
    """A live.line exactly like Live's (live_core.line_event), plus body.watch when a chip was used."""
    import live_core
    ev = live_core.line_event(session, me, text, t, via, point, branch)
    # live_core.clean_text drops [..] as speech-model noise, which would eat the chip's tag: keep the composed text
    ev["body"]["text"] = re.sub(r"[ \t]+", " ", str(text or "")).strip()[:live_core.MAX_TEXT]
    if watch:
        ev["body"]["watch"] = watch
    return ev


# ---------------------------------------------------------------- the stream (as Studio's Live panel)
RESPONDER_ID = "agent:live-responder"
RESPONDER_LABEL = "Quick answer (Gemini)"


def _who(a: dict, via=None, me_id: str | None = None) -> str:
    """Who wrote a row, as the Watch chat names them (SC-golden-looksoff-1 #4: 'Morami49 via Claude' read as if
    Nowed wrote Claude's replies). Claude's replies through the connector are 'Claude'; the hub's quick answers
    say which model wrote them; the signed-in person is 'You'."""
    a = a or {}
    if a.get("id") == RESPONDER_ID or via == "live-responder":
        return RESPONDER_LABEL
    if via == "claude-connector" or a.get("id") == "claude":
        return "Claude"
    if a.get("role") == "agent":
        return a.get("label") or "Claude"
    if me_id and a.get("id") == me_id:
        return "You"
    return a.get("label") or a.get("role") or "someone"


def is_reply(e: dict) -> bool:
    a = e.get("author") or {}
    return a.get("id") == "claude" or a.get("role") == "agent" or a.get("role") != "owner" or e.get("via") == "claude-connector"


def step_words(st: dict) -> str:
    t = st.get("target") or {}
    what = f"“{str(t['text'])[:60]}”" if t.get("text") else (t.get("element") or "the page")
    part = f" ({t['part']})" if t.get("part") else ""
    k = st.get("kind")
    return "Note: " + (st.get("text") or "") if k == "note" else f"Drew around {what}{part}" if k == "stroke" else f"Pointed at {what}{part}"


def stream_rows(docs, session: str, me_id: str | None = None) -> list[dict]:
    """One session's stream from /studio/api/events rows ([{doc_id, event}]): its live.line events, comments
    (connector and responder replies included) and show steps, by time; taken-back entries left out.
    Rows: {id, ts, time, kind: line|reply|note|step, who, text, words (point), via, report}."""
    gone, rows = set(), []
    for d in docs or []:
        e = (d or {}).get("event") or {}
        if e.get("kind") == "retract" and e.get("item") == session:
            gone.add((e.get("body") or {}).get("of"))
    for d in docs or []:
        e = (d or {}).get("event") or {}
        if e.get("item") != session or d.get("doc_id") in gone:
            continue
        b = e.get("body") or {}
        base = {"id": d.get("doc_id"), "ts": e.get("ts") or "", "time": (e.get("ts") or "")[11:19], "via": b.get("via") or e.get("via")}
        if e.get("kind") == "live.line":
            p = b.get("point") or None
            words = (p.get("words") or p.get("element_words")) if isinstance(p, dict) else ""
            if isinstance(p, dict) and not words:
                el = p.get("element")
                words = f"⌖ {p.get('app') or p.get('part') or 'desktop'} › {(el.get('name') if isinstance(el, dict) else el) or ''}"
            rows.append(dict(base, kind="line", who=_who(e.get("author"), None, me_id) if me_id else (b.get("speaker") or _who(e.get("author"))), text=b.get("text") or "",
                             words=words or "", chip=(b.get("watch") or {}).get("chip")))
        elif e.get("kind") == "comment":
            if b.get("step"):
                rows.append(dict(base, kind="step", who=_who(e.get("author"), None, me_id), text=step_words(b["step"]), words=""))
            else:
                row = dict(base, kind="reply" if is_reply(e) else "note", who=_who(e.get("author"), b.get("via") if b.get("via") == "live-responder" else e.get("via"), me_id),
                           text=str(b.get("text") or "")[:4000], words="", report=bool(b.get("report")))
                car = carousel_from(b.get("carousel"), d.get("doc_id"))
                if car:
                    row["carousel"] = car
                rows.append(row)
    rows.sort(key=lambda r: r["ts"])
    return rows


def session_list(docs, me: dict) -> list[dict]:
    import live_core
    return live_core.session_list(docs, me.get("id", ""), bool(me.get("owner")))


# ---------------------------------------------------------------- zones.json (the user's copy), versioned
def read_raw(path: Path, default_path: Path = gate_core.DEFAULT_ZONES) -> dict:
    p = Path(path)
    src = p if p.exists() else Path(default_path)
    return json.loads(src.read_text(encoding="utf-8-sig"))


def edit_zones(path: Path, fn, *, now: dt.datetime | None = None, default_path: Path = gate_core.DEFAULT_ZONES):
    """Apply fn(raw) -> (new_raw, result) to the user's zones.json. The version before the edit is kept in
    zones-history\\ (no silent overwrites); the file is replaced in one step. Returns (result, changed)."""
    path = Path(path)
    raw = read_raw(path, default_path)
    new, result = fn(raw)
    if new is raw:
        return result, False
    now = now or dt.datetime.now()
    if path.exists():
        hist = path.parent / "zones-history"
        hist.mkdir(parents=True, exist_ok=True)
        dst = hist / f"zones-rev{raw.get('revision')}-{now:%y%m%d-%H%M%S}-before-keepout.json"
        if not dst.exists():
            dst.write_bytes(path.read_bytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return result, True


def keep_out_add(path: Path, entry: dict, by: str = "Nowed", now: dt.datetime | None = None):
    now = now or dt.datetime.now()
    return edit_zones(path, lambda raw: gate_core.keep_out_add(raw, entry, by=by, date=now.date().isoformat()), now=now)


def keep_out_remove(path: Path, entry_id: str, by: str = "Nowed", now: dt.datetime | None = None):
    now = now or dt.datetime.now()
    return edit_zones(path, lambda raw: gate_core.keep_out_remove(raw, entry_id, by=by, date=now.date().isoformat()), now=now)


def keep_out_list(path: Path) -> list[dict]:
    raw = read_raw(path)
    return [dict(e, words=gate_core._entry_words(e)) for e in gate_core.keep_out_entries(raw)]


def pick_choices(window: dict) -> list[dict]:
    """After 'Keep out a window' and a click: what can be kept out (this window, or the whole app)."""
    out = []
    if window.get("title") or window.get("app"):
        try:
            out.append({"label": "This window", "entry": gate_core.keep_out_entry("window", process=window.get("app", ""), title=window.get("title", ""))})
        except ValueError:
            pass
    if window.get("app"):
        out.append({"label": f"The whole app ({window['app']})", "entry": gate_core.keep_out_entry("app", process=window["app"])})
    return out


def window_list(windows, zones: dict) -> list[dict]:
    """Open windows for the 'pick from a list' choice. Windows already out (never or kept out) are listed as such,
    without their titles."""
    out, seen = [], set()
    for w in windows or []:
        r = never_reason(zones, w.get("app"), w.get("title"))
        key = (w.get("app"), w.get("title") if not r else r)
        if key in seen:
            continue
        seen.add(key)
        out.append({"app": w.get("app") or "", "title": "" if r else str(w.get("title") or "")[:120],
                    "out": r.split(":")[0] if r else None})
    out.sort(key=lambda x: (x["out"] is not None, x["app"].lower(), x["title"].lower()))
    return out


# ---------------------------------------------------------------- status strip
def status_strip(*, watch: bool, paused: bool, acting: dict, kept_out: int, signed_in: bool, session: str | None,
                 privacy: str | None = None) -> dict:
    watching = (f"Watching: all windows except {kept_out} kept out" if watch else "Watch is off: Claude can't see or act")
    if watch and privacy:
        watching = f"Watch paused itself: {privacy} in front"
    return {"watch": bool(watch), "privacy": privacy if watch else None,
            "watching": watching,
            "kept_out": kept_out,
            "gate": "paused" if paused else "ok",
            "acting": f"Claude is acting: {acting.get('tool')}" if acting.get("active") and not paused else "",
            "signed_in": bool(signed_in), "session": session}


# ---------------------------------------------------------------- U1b: 'looks like you're stuck' offers (off by default)
STUCK_DEFAULTS = {"on": False, "repeat_n": 3, "repeat_window_s": 90, "pause_s": 120, "active_s": 900}


def stuck_offer(entries, now: float, settings: dict | None = None, last_offer: float | None = None) -> dict | None:
    """An offer to help ({reason, detail}) from the Gate log, or None. Off unless the Settings toggle is on.
    Triggers: the same action repeated (repeat_n times within repeat_window_s), an error showing (the last action
    failed), a long pause (no action for pause_s after actions in the last active_s). One offer per stretch:
    nothing new after last_offer, nothing again. v0 reads Gate's log; watching the user's own input is a TODO."""
    s = dict(STUCK_DEFAULTS, **(settings or {}))
    if not s["on"]:
        return None
    acts = [e for e in entries or [] if e.get("kind", "action") == "action" and e.get("_t") is not None]
    if not acts:
        return None
    acts.sort(key=lambda e: e["_t"])
    last = acts[-1]
    if last_offer is not None and last_offer >= last["_t"]:
        return None
    if not last.get("ok", True) and last.get("decision") == "allowed":
        return {"reason": "error", "detail": f"{last.get('tool')} failed"}
    sig = gate_core.action_sig(last)
    same = [e for e in acts if now - e["_t"] <= s["repeat_window_s"] and gate_core.action_sig(e) == sig]
    if len(same) >= s["repeat_n"]:
        return {"reason": "repeat", "detail": f"{last.get('tool')} {len(same)} times"}
    if s["pause_s"] <= now - last["_t"] <= s["active_s"]:
        return {"reason": "pause", "detail": f"nothing for {int(now - last['_t'])} s"}
    return None


# ---------------------------------------------------------------- U2b (1): a mark-up as a report you keep or send
def _esc(t) -> str:
    return (str(t if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def mark_words(m: dict) -> str:
    k = m["type"]
    def el(end):
        x = m.get(end + "_element") or {}
        return f"{x.get('type', '')} “{x.get('name', '')}”".strip() if x else f"({m[end]['x']}, {m[end]['y']})"
    if k == "arrow":
        return f"Arrow from {el('from')} to {el('to')}" + (f": {m['text']}" if m.get("text") else "")
    if k == "box":
        names = ", ".join(f"“{x['name']}”" for x in (m.get("elements") or [])[:6] if x.get("name"))
        return "Box" + (f" around {names}" if names else "") + (f": {m['text']}" if m.get("text") else "")
    if k == "path":
        return f"Drawing ({len(m.get('points') or [])} points)" + (f": {m['text']}" if m.get("text") else "")
    if k == "step":
        return f"Step {m.get('step')}: {m.get('text') or ''}".rstrip(": ")
    if k == "branch":
        return f"{m.get('label', 'if').capitalize()} (step {m.get('of_step', '?')}): {m.get('text') or ''}".rstrip(": ")
    return f"Note: {m.get('text') or ''}"


def export_html(e: dict, png: bytes | None = None, title: str = "", note: str = "") -> str:
    """One self-contained HTML page for a mark-up (or area/point): the crop with the marks drawn over it as SVG, and
    the marks as a numbered list. For watching back, keeping as a guide, or sending to a vendor. No window titles,
    file paths or sign-in; the picture is inlined (it's his to send)."""
    import base64
    box = e.get("rect") or (e.get("element") or {}).get("rect") or {"left": 0, "top": 0, "right": 800, "bottom": 600}
    w, h = box["right"] - box["left"], box["bottom"] - box["top"]
    ox, oy = box["left"], box["top"]
    svg = []
    for m in e.get("marks") or []:
        if m["type"] == "arrow":
            svg.append(f'<line x1="{m["from"]["x"] - ox}" y1="{m["from"]["y"] - oy}" x2="{m["to"]["x"] - ox}" y2="{m["to"]["y"] - oy}" class="m" marker-end="url(#a)"/>')
        elif m["type"] == "box":
            r = m["rect"]
            svg.append(f'<rect x="{r["left"] - ox}" y="{r["top"] - oy}" width="{r["right"] - r["left"]}" height="{r["bottom"] - r["top"]}" class="m"/>')
        elif m["type"] == "path":
            svg.append('<polyline class="m" points="' + " ".join(f'{p["x"] - ox},{p["y"] - oy}' for p in m["points"]) + '"/>')
        else:
            x, y = m["at"]["x"] - ox, m["at"]["y"] - oy
            lab = str(m.get("step") or m.get("label") or "•")
            svg.append(f'<circle cx="{x}" cy="{y}" r="13" class="dot"/><text x="{x}" y="{y + 4}" class="lab">{_esc(lab[:6])}</text>')
        svg.append(f'<text x="{(m.get("from") or m.get("at") or {"x": ox})["x"] - ox + 16}" '
                   f'y="{(m.get("from") or m.get("at") or {"y": oy})["y"] - oy - 10}" class="n">{m["n"]}</text>')
    img = f'<image href="data:image/png;base64,{base64.b64encode(png).decode()}" width="{w}" height="{h}"/>' if png else \
        f'<rect width="{w}" height="{h}" fill="#222"/>'
    items = "".join(f"<li>{_esc(mark_words(m))}</li>" for m in e.get("marks") or [])
    if not items and e.get("elements"):
        items = "".join(f"<li>{_esc(x['type'])} “{_esc(x['name'])}”</li>" for x in e["elements"])
    head = title or f"Nodach Watch {('mark-up · ' + PRESETS[e['preset']]['label']) if e.get('preset') in PRESETS else e.get('kind', '')}"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{_esc(head)}</title>
<style>body{{font:15px/1.45 system-ui,Segoe UI,sans-serif;margin:24px;color:#18201f;max-width:1100px}}
svg{{max-width:100%;height:auto;border:1px solid #ccc}} .m{{fill:none;stroke:#f60;stroke-width:4}} .dot{{fill:#f60;stroke:#fff}}
.lab{{fill:#fff;font:bold 12px sans-serif;text-anchor:middle}} .n{{fill:#f60;font:bold 15px sans-serif;paint-order:stroke;stroke:#fff;stroke-width:3}}
.meta{{color:#666;font-size:13px}}</style></head><body>
<h1>{_esc(head)}</h1><p class="meta">{_esc(e.get('id'))} · {_esc(e.get('at'))} · app {_esc((e.get('process') or {}).get('name') or '-')}</p>
{f'<p>{_esc(note)}</p>' if note else ''}
<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg"><defs><marker id="a" viewBox="0 0 10 10" refX="8" refY="5"
markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#f60"/></marker></defs>{img}{''.join(svg)}</svg>
<ol>{items}</ol><p class="meta">Made with Nodach Watch {VERSION}. Marks are numbered in the order they were drawn.</p></body></html>
"""


def export_bundle(e: dict, png: bytes | None, folder: Path, note: str = "") -> dict:
    """{html, zip}: the page and a zip with the page, the crop and the event (pointer.v1, without window title)."""
    import zipfile
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    page = export_html(e, png, note=note)
    hp = folder / f"{e['id']}.html"
    hp.write_text(page, encoding="utf-8")
    clean = dict(e, window={"title": "", "class_name": ""}, screenshot=Path(e["screenshot"]).name if e.get("screenshot") else None)
    zp = folder / f"{e['id']}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{e['id']}.html", page)
        z.writestr(f"{e['id']}.json", json.dumps(clean, ensure_ascii=False, indent=1))
        if png:
            z.writestr(f"{e['id']}.png", png)
    return {"html": str(hp), "zip": str(zp)}


# ---------------------------------------------------------------- U5: may Claude reproduce a reported problem?
def may_reproduce(fields: dict, zones: dict, point: dict | None = None, text: str = "") -> dict:
    """{allowed, reason}. Never when he ticked 'Something can't be undone', or when the problem involves an action whose
    effect is irreversible: the confirm-zone kinds (send, delete, pay, publish, …: zones.json confirm.element_words)
    named in the line or on the elements he pointed at. Otherwise Claude may try it through Gate (Gate's rules still
    apply) and may ask him to replay his steps."""
    if fields.get("irreversible"):
        return {"allowed": False, "reason": "marked 'can't be undone'"}
    words = (zones.get("confirm") or {}).get("element_words") or []
    names = [text]
    p = point or {}
    names.append(((p.get("element") or {}).get("name")) or "")
    for m in p.get("marks") or []:
        for end in ("from_element", "to_element"):
            names.append((m.get(end) or {}).get("name") or "")
        names += [x.get("name") or "" for x in m.get("elements") or []]
        names.append(m.get("text") or "")
    names += [x.get("name") or "" for x in p.get("elements") or []]
    w = gate_core._hit(words, *names)
    if w:
        return {"allowed": False, "reason": f"involves '{w.lower()}', which may not be reversible"}
    return {"allowed": True, "reason": "Claude may try it through Gate first"}


def incident_text(fields: dict) -> str:
    """The irreversible-incident template as text, for the line (empty answers say so, they're questions to ask)."""
    inc = fields.get("incident") or {}
    return "\n".join(f"{INCIDENT_LABELS[k]}: {inc.get(k) or '(not known yet: ask)'}" for k in INCIDENT_FIELDS)


# ---------------------------------------------------------------- U4: a glitch (screen changed, nothing done)
GLITCH_ASK_EVERY_S = 3600


GLITCH_GRACE_S = 10     # a clip kept just before the Watch window first looked still counts


def glitch_offer(entries, asked: dict, now: float, every_s: int = GLITCH_ASK_EVERY_S, since: float | None = None) -> dict | None:
    """Gate keeps a clip when the screen changes with no action (trigger 'glitch'). Ask 'report it?' for the newest
    one not asked about yet, at most once per app per hour. asked: {app: last asked time, '_seen': [clip paths]},
    updated in place. The app is the one the last action before the clip ran in (Gate's clip entry has none)."""
    seen = set(asked.get("_seen") or [])
    last_app = ""
    found = None
    for e in sorted(entries or [], key=lambda x: x.get("_t") or 0):
        if e.get("kind", "action") == "action" and e.get("app"):
            last_app = e["app"]
        elif e.get("kind") == "clip" and e.get("trigger") == "glitch" and e.get("path") not in seen:
            # SC-golden-looksoff-1 #5: a clip from before Watch was turned on, or one from Nodach's own windows,
            # is never offered (an old clip came back as a fresh 'report it?')
            if since is not None and float(e.get("_t") or 0) < since - GLITCH_GRACE_S:
                seen.add(e.get("path"))
                continue
            if app_label({"app": last_app}).startswith("Nodach"):
                seen.add(e.get("path"))
                continue
            found = (e, last_app)
    if not found:
        return None
    e, app = found
    asked["_seen"] = sorted(seen | {e.get("path")})[-200:]
    key = gate_core._proc(app) or "?"
    if now - float(asked.get(key) or -1e18) < every_s:
        return None
    asked[key] = now
    return {"reason": "glitch", "app": app, "clip": e.get("path"), "at": e.get("ts"),
            "detail": f"the screen changed in {app or 'a window'} with nothing done: report it?"}


# ---------------------------------------------------------------- U9/U10: drafts as a carousel in the chat
CARD_KINDS = ("text", "image", "html", "video", "link")
ROUTES = {"drafts": "Create drafts in the app", "gate": "Do it through Gate", "automation": "Build an automation, then run it"}
MAX_CARDS = 12


def carousel_from(c, row_id: str | None = None) -> dict | None:
    """A comment's body.carousel ({title, cards: [{id, kind, title, text, src, html}]}) made safe to show:
    image only as data:image/… (other image addresses become links, so nothing is fetched by itself), video and links
    as https addresses opened in the browser, html as a snippet shown sandboxed (no scripts) and capped at 20 KB."""
    if not isinstance(c, dict) or not isinstance(c.get("cards"), list):
        return None
    cards = []
    for i, k in enumerate(c["cards"][:MAX_CARDS], 1):
        if not isinstance(k, dict):
            continue
        kind = k.get("kind") if k.get("kind") in CARD_KINDS else "text"
        card = {"id": re.sub(r"[^A-Za-z0-9_-]", "", str(k.get("id") or f"c{i}"))[:40] or f"c{i}", "kind": kind,
                "title": str(k.get("title") or "")[:120], "text": str(k.get("text") or "")[:2000]}
        src = str(k.get("src") or "")
        if kind == "image":
            if src.startswith("data:image/") and len(src) <= 2_000_000:
                card["src"] = src
            elif src.startswith("https://"):
                card.update(kind="link", url=src[:500])
            else:
                card["kind"] = "text"
        elif kind in ("video", "link"):
            if src.startswith("https://"):
                card["url"] = src[:500]
            else:
                card["kind"] = "text"
        elif kind == "html":
            card["html"] = str(k.get("html") or "")[:20000]
        cards.append(card)
    if not cards:
        return None
    return {"id": str(c.get("id") or row_id or "")[:60], "title": str(c.get("title") or "Drafts")[:120], "cards": cards}


def card_markup_event(t: dt.datetime, *, carousel: str, card: dict, marks, size=None) -> dict:
    """Mark up drawn on a carousel card in the Watch window (the same marks as on screen, in the card's own
    pixels): kind 'markup', target the card. Attaches to the next line like any capture."""
    w, h = size or (360, 240)
    e = markup_event(t, marks=marks, window={"title": ""}, process={"name": "nodach-watch"}, zones={},
                     screen=(0, 0, int(w), int(h)))
    e["target"] = {"carousel": str(carousel)[:60], "card": str(card.get("id"))[:40], "card_title": str(card.get("title") or "")[:120],
                   "card_kind": card.get("kind")}
    e["element"]["name"] = f"card “{card.get('title') or card.get('id')}”: " + e["element"]["name"]
    return e


def route_line(route: str, carousel: str, card: str | None = None, text: str = "") -> tuple[str, dict]:
    """The follow-on after the drafts: [for-claude] with the chosen route. Claude lists the constraints and risks he
    may not have considered before acting (execution is not built in v0)."""
    if route not in ROUTES:
        raise ValueError(f"route must be one of {sorted(ROUTES)}")
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    line = f"[for-claude] [route:{route}] {ROUTES[route]}" + (f": {t}" if t else "")
    return line[:2000], {"chip": "route", "use": "U10", "route": route, "carousel": str(carousel)[:60],
                         "card": card, "risks_first": True}


# ---------------------------------------------------------------- U11-U13: replaying a learned map (check only)
def _norm_text(t) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip().lower()


def expected_matches(step: dict, live: dict | None) -> dict:
    """Before a step of a learned map runs, the element now at that spot must match what the step recorded:
    name, type, window (app and title words) and nearby text. {ok, changed: [what differs]}. Map runs aren't built in
    v0; this is the check they will use (a run stops and shows `changed` instead of acting).
    step: {"expect": {name, type, app, window_words: [...], nearby: [...]}} (or the expectation itself)."""
    exp = step.get("expect", step) if isinstance(step, dict) else {}
    live = live or {}
    changed = []
    if not live or not (live.get("name") or live.get("type")):
        return {"ok": False, "changed": ["nothing found at that spot"]}
    if exp.get("name") is not None and _norm_text(exp["name"]) != _norm_text(live.get("name")):
        changed.append(f"name: expected “{exp['name']}”, found “{live.get('name') or ''}”")
    def _t(x):
        x = str(x or "").lower()
        x = x[:-7] if x.endswith("control") else x
        return x
    if exp.get("type") and _t(exp["type"]) != _t(live.get("type")):
        changed.append(f"type: expected {exp['type']}, found {live.get('type') or '?'}")
    if exp.get("app") and gate_core._proc(exp["app"]) != gate_core._proc(live.get("app") or (live.get("window") or {}).get("app")):
        changed.append(f"app: expected {exp['app']}, found {live.get('app') or (live.get('window') or {}).get('app') or '?'}")
    title = _norm_text(live.get("window_title") or (live.get("window") or {}).get("title"))
    for w in exp.get("window_words") or []:
        if _norm_text(w) not in title:
            changed.append(f"window: “{w}” isn't in the title any more")
    near = _norm_text(" ".join(str(x) for x in live.get("nearby") or []))
    for w in exp.get("nearby") or []:
        if _norm_text(w) not in near:
            changed.append(f"nearby text: “{w}” is gone")
    return {"ok": not changed, "changed": changed}



# ---------------------------------------------------------------- U15: accessibility (same window for everyone)
VERBS = {"button": "Press", "splitbutton": "Press", "edit": "Type into", "checkbox": "Tick", "radiobutton": "Choose",
         "hyperlink": "Open", "menuitem": "Choose", "listitem": "Pick", "treeitem": "Open", "tabitem": "Switch to",
         "combobox": "Choose from", "slider": "Move", "dataitem": "Pick", "document": "Read", "text": "Read"}


def plain_actions(e: dict) -> list[str]:
    """'Simplify': a window or area as a plain numbered list of what can be done there ("Press “Save”")."""
    els = list(e.get("elements") or [])
    for m in e.get("marks") or []:
        els += [x for x in (m.get("from_element"), m.get("to_element")) if x] + list(m.get("elements") or [])
    if not els and (e.get("element") or {}).get("name") and e.get("kind") == "pointer.desktop":
        els = [e["element"]]
    out, seen = [], set()
    for x in els:
        t = re.sub(r"control$", "", str(x.get("type") or "").lower())
        name = str(x.get("name") or "").strip()
        if not name or (t, name) in seen:
            continue
        seen.add((t, name))
        out.append(f"{VERBS.get(t, 'Look at')} “{name[:80]}”" + ("" if t in VERBS else f" ({t or 'item'})"))
    return out


# ---------------------------------------------------------------- U14: a session kept as a lesson (if he chooses)
def lesson_event(session: str, me: dict, t: dt.datetime, rows, title: str = "") -> dict:
    """At the end of a session, if he says yes: a Studio item that keeps the session as a replayable lesson (the
    stream stays on the session item; this links it and lists its steps). Replay itself is a TODO."""
    import live_core
    lines = [r for r in rows or [] if r.get("kind") in ("line", "reply", "step")]
    steps = [f"{i}. {r['who']}: {r['text'][:160]}" + (f" {r['words']}" if r.get("words") else "") for i, r in enumerate(lines, 1)]
    body = {"id": live_core.stamp("LS", t), "type": "idea", "title": ("Lesson: " + (title or session))[:96],
            "body": "A session kept as a lesson to replay.\n\n" + "\n".join(steps[:200]), "refs": [session], "status": "open",
            "source": "watch", "meta": {"kind": "lesson", "from_session": session, "steps": len(lines), "schema": "watch.lesson.v1"}}
    return {"ts": iso(t), "kind": "item.create", "item": None, "branch": "main", "body": body, "author": live_core.author(me)}


# ---------------------------------------------------------------- Claude's test hook (decision 77a b, 21 Nov)
TEST_ACTIONS = ("select_area", "point", "state")
MIN_DRAG_PX = 6          # the overlay ignores a drag shorter than this (|dx| + |dy|)


def test_target(action: str, args: dict) -> tuple[str, dict]:
    """(capture mode, what the overlay would have returned) for a test input, in physical screen pixels as Snapshot
    reports them. Raises ValueError for anything a real drag/click couldn't have produced."""
    args = args or {}
    try:
        if action == "select_area":
            x1, y1, x2, y2 = (int(round(float(args[k]))) for k in ("x1", "y1", "x2", "y2"))
            if abs(x2 - x1) + abs(y2 - y1) < MIN_DRAG_PX:
                raise ValueError(f"the area is too small (a drag under {MIN_DRAG_PX} px is ignored, like the overlay)")
            if x1 == x2 or y1 == y2:
                raise ValueError("the area has no width or no height")
            return "area", {"rect": [x1, y1, x2, y2]}
        if action == "point":
            return "point", {"x": int(round(float(args["x"]))), "y": int(round(float(args["y"])))}
    except (KeyError, TypeError) as e:
        raise ValueError(f"{action} needs " + ("x1, y1, x2, y2" if action == "select_area" else "x, y") + f" ({e})") from None
    raise ValueError(f"action must be one of {', '.join(TEST_ACTIONS)}")


def test_refusal(mode: str, got: dict, windows, zones: dict) -> str | None:
    """Same rule as a real drag: any part of a never-zone or kept-out window is blacked out of every picture, so a
    test area that overlaps one (or a point inside one) is refused. Returns the reason, or None."""
    for w in windows or []:
        if not w.get("rect"):
            continue
        why = never_reason(zones, w.get("app"), w.get("title"))
        if not why:
            continue
        r = as_rect(w["rect"])
        if mode == "area":
            a = rect(*got["rect"])
            if overlaps(a, r) or inside(a, r):
                return f"the area overlaps a kept-out window ({why.split(':')[0]})"
        elif r["left"] <= got["x"] < r["right"] and r["top"] <= got["y"] < r["bottom"]:
            return f"that point is on a kept-out window ({why.split(':')[0]})"
    return None


def test_note(action: str, got: dict) -> str:
    if action == "select_area":
        l, t, r, b = got["rect"]
        return f"test input from Claude: Select area ({l}, {t}) to ({r}, {b})"
    if action == "point":
        return f"test input from Claude: Point at ({got['x']}, {got['y']})"
    return "test input from Claude: read the Watch state"


# ---------------------------------------------------------------- window placement (21 Nov: 125 % scaling)
def place(work_area_px, dpi_scale: float, size=(400, 820), margin: int = 20, min_size=(340, 560)) -> dict:
    """Where the Watch window goes, in physical pixels: right side of the primary monitor's work area, `margin` px
    clear of its top, right and bottom, never outside it. size and min_size are in CSS/logical px (scaled here).
    work_area_px: (left, top, right, bottom) in physical pixels. Returns {x, y, width, height} (physical) and the
    same in logical units ({lx, ly, lwidth, lheight}) for toolkits that scale for themselves."""
    l, t, r, b = (int(v) for v in work_area_px)
    s = float(dpi_scale) if dpi_scale and dpi_scale > 0 else 1.0
    m = int(margin)                     # physical px, as Snapshot measures
    avail_w, avail_h = max(1, r - l - 2 * m), max(1, b - t - 2 * m)
    w = min(int(round(size[0] * s)), avail_w)
    h = min(int(round(size[1] * s)), avail_h)
    w = max(w, min(int(round(min_size[0] * s)), r - l))
    h = max(h, min(int(round(min_size[1] * s)), b - t))
    w, h = min(w, r - l), min(h, b - t)
    x = min(max(l, r - m - w), r - w)
    y = max(t, min(t + m, b - h))
    return {"x": x, "y": y, "width": w, "height": h,
            "lx": int(x / s), "ly": int(y / s), "lwidth": int(round(w / s)), "lheight": int(round(h / s)), "scale": s}


# ---------------------------------------------------------------- reload on change (21 Nov: closing only hid it)
def files_signature(folder: Path) -> dict:
    """{"py": ((name, size, mtime_ns), ...), "web": (...)} for the Watch app's own .py files and its web/ files."""
    folder = Path(folder)
    out = {"py": [], "web": []}
    for p in sorted(folder.glob("*.py")):
        try:
            st = p.stat()
            out["py"].append((p.name, st.st_size, st.st_mtime_ns))
        except OSError:
            pass
    web = folder / "web"
    if web.is_dir():
        for p in sorted(web.rglob("*")):
            try:
                if p.is_file():
                    st = p.stat()
                    out["web"].append((p.relative_to(web).as_posix(), st.st_size, st.st_mtime_ns))
            except OSError:
                pass
    return {k: tuple(v) for k, v in out.items()}


def reload_decision(prev: dict | None, cur: dict | None, capturing: bool) -> str | None:
    """'restart' (re-exec the app: a .py changed), 'reload' (reload the page: only web/ changed) or None.
    Never mid-capture: the caller keeps prev and asks again on the next poll."""
    if not prev or not cur or capturing:
        return None
    if prev.get("py") != cur.get("py") and cur.get("py"):
        return "restart"
    if prev.get("web") != cur.get("web"):
        return "reload"
    return None


# ---------------------------------------------------------------- sessions end after a quiet spell (SC-golden-looksoff-1 #2)
IDLE_END_MIN = 30


def _ts(s) -> float:
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def last_activity(docs, session: str) -> float:
    """When anything last happened in a session (its start, a line, a reply, an edit): epoch seconds, 0 if unknown."""
    best = 0.0
    for d in docs or []:
        e = (d or {}).get("event") or {}
        b = e.get("body") or {}
        if e.get("item") == session or (e.get("kind") == "item.create" and b.get("id") == session):
            best = max(best, _ts(e.get("ts")))
    return best


def idle_minutes(settings: dict | None) -> int:
    """settings.json 'idle_end_minutes' (0 turns ending off); default 30."""
    try:
        v = int((settings or {}).get("idle_end_minutes", IDLE_END_MIN))
    except (TypeError, ValueError):
        v = IDLE_END_MIN
    return max(0, v)


def is_idle(docs, session: str, now: float, minutes: int) -> bool:
    if not minutes:
        return False
    last = last_activity(docs, session)
    return bool(last) and now - last >= minutes * 60


def responder_on(docs, session: str) -> bool | None:
    """The session's live.responder switch (item.create, then item.edit in order; the latest wins); None if never set."""
    on = None
    for d in docs or []:
        e = (d or {}).get("event") or {}
        b = e.get("body") or {}
        if (e.get("kind") == "item.create" and b.get("id") == session) or (e.get("kind") == "item.edit" and e.get("item") == session):
            lv = b.get("live") if isinstance(b.get("live"), dict) else {}
            if "responder" in lv:
                on = bool(lv["responder"])
    return on


WAIT_S = 45


def wait_row(pending: dict | None, rows, docs, now: float) -> dict | None:
    """After a send: a 'waiting for a quick answer' row until a reply newer than the line arrives, never silence.
    pending: {session, line, ts (iso), t (epoch)}. Returns the row to show, or None once answered."""
    if not pending:
        return None
    if any(r.get("kind") == "reply" and str(r.get("ts") or "") > str(pending.get("ts") or "") for r in rows or []):
        return None
    on = responder_on(docs, pending.get("session"))
    age = now - float(pending.get("t") or now)
    if on is False:
        text = "Quick answers are off for this session. Claude answers when you next message the chat."
    elif age < WAIT_S:
        text = "Waiting for a quick answer…"
    else:
        text = ("No quick answer came (the hub's AI may be busy or not set up). "
                "Claude answers when you next message the chat.")
    return {"id": "wait-" + str(pending.get("line") or ""), "ts": pending.get("ts") or "", "time": str(pending.get("ts") or "")[11:19],
            "kind": "wait", "who": "Watch", "text": text, "words": "", "via": None}
