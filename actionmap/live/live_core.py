"""
Nodach Live client: pure logic (no audio, keyboard or network), so it can be tested on any OS.

live_client.py does the Windows work (microphone, hotkeys, local transcription, HTTP) and calls these
functions to clean a transcript, spot "task:" / "build:" lines, shape the Studio events it posts, pick the
desktop pointer's latest point, and cut always-on audio into phrases.

Event shapes (the same as Studio's Live panel writes, studio/index.html "Live session"):
  live.line     {ts, kind:"live.line", item:<session>, branch, author, body:{session, speaker, text, ts, via, point?}}
  item.create   a session:  {id:"LV-...", type:"idea", status:"live", source:"live", live:{schema:"live.v1", ...}}
  item.create   a draft:    {id:"TK-...", type:"change", status:"draft", refs:[<session>], source:"live",
                             meta:{kind:"task"|"build", from_session, from_line:<doc id of the line>}}
Only text and a trimmed point leave the PC: never audio, screenshots, window titles or file paths.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets

VERSION = "0.1.0"
LINE_KIND = "live.line"
MAX_TEXT = 2000
POINT_MAX_AGE_S = 120          # a pointer point older than this isn't attached to a new line

# Same rule as Studio's LIVE_TASK: the first word is task or build, then a separator. Speech-to-text often writes
# the spoken colon as a comma or full stop, so those count too.
TASK_RE = re.compile(r"^\s*(task|build)\s*[:,.\-–—]\s*(\S.*)$", re.I | re.S)
# Whisper's non-speech captions, e.g. "[BLANK_AUDIO]", "(music)", "*coughs*"
NOISE_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    """Studio's timestamp form: UTC, milliseconds, Z."""
    return t.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp(prefix: str, t: dt.datetime) -> str:
    """Item ids like Studio's PTR.stamp: LV-yymmdd-hhmmss-xxxx. The prefix never changes when things are renamed."""
    t = t.astimezone(dt.timezone.utc)
    return f"{prefix}-{t:%y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def doc_id() -> str:
    """A shared-record document id the hub accepts (letters, digits, - and _; not hub-)."""
    return "lv" + secrets.token_hex(10)


def clean_text(text) -> str:
    t = NOISE_RE.sub(" ", str(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:MAX_TEXT]


def parse_task(text):
    """{"kind": "task"|"build", "title": ...} for a task line, else None."""
    m = TASK_RE.match(str(text or ""))
    if not m:
        return None
    title = re.sub(r"\s+", " ", m.group(2)).strip().rstrip(".")
    return {"kind": m.group(1).lower(), "title": title} if title else None


def author(me: dict) -> dict:
    """The author block Studio writes: the hub's id for you (github:<login>, or email:<hash> for email accounts;
    never an address), owner or member, and the same label the page uses."""
    owner = bool(me.get("owner"))
    return {"id": me["id"], "role": "owner" if owner else "member", "label": "Nowed" if owner else "Member"}


def shareable_point(p):
    """The part of a desktop pointer event (pointer.v1) that may go into a shared line: which app and element, and
    the note typed with it. Window titles, screenshots, file paths, cursor and ancestors stay on the PC."""
    if not isinstance(p, dict) or p.get("schema") != "pointer.v1":
        return None
    el = p.get("element") or {}
    out = {"schema": "pointer.v1", "kind": p.get("kind") or "pointer.desktop", "id": p.get("id"),
           "app": ((p.get("process") or {}).get("name") or "")[:60],
           "element": {"type": (el.get("type") or "")[:40], "name": (el.get("name") or "")[:80]}}
    if p.get("note"):
        out["note"] = str(p["note"])[:500]
    return out


def latest_point(jsonl_lines, now: dt.datetime, used=(), max_age_s: int = POINT_MAX_AGE_S):
    """The newest pointer point (mode "point") from the pointer's events.jsonl lines that is fresh and not used yet."""
    best = None
    for raw in jsonl_lines:
        try:
            e = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue   # a half-written line
        if not isinstance(e, dict) or e.get("schema") != "pointer.v1" or e.get("mode") not in ("point", None) or e.get("id") in used:
            continue
        try:
            at = dt.datetime.fromisoformat(str(e.get("at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt.timezone.utc)
        if (now - at).total_seconds() > max_age_s or at > now + dt.timedelta(seconds=5):
            continue
        if best is None or at >= best[0]:
            best = (at, e)
    return best[1] if best else None


def line_event(session: str, me: dict, text: str, t: dt.datetime, via: str = "voice", point=None, branch: str = "main") -> dict:
    ts = iso(t)
    body = {"session": session, "speaker": author(me)["label"], "text": clean_text(text), "ts": ts, "via": via}
    if point:
        body["point"] = point
    return {"ts": ts, "kind": LINE_KIND, "item": session, "branch": branch, "body": body, "author": author(me)}


def task_event(session: str, line_doc_id: str, task: dict, me: dict, t: dt.datetime, branch: str = "main") -> dict:
    ts = iso(t)
    word = "Build: " if task["kind"] == "build" else "Task: "
    body = {"id": stamp("TK", t), "type": "change", "title": (word + task["title"])[:96],
            "body": f"{task['title']}\n\nDrafted from a live line ({session}, {ts}). Draft only: nothing is built until an owner approves it.",
            "status": "draft", "refs": [session], "source": "live",
            "meta": {"kind": task["kind"], "from_session": session, "from_line": line_doc_id}}
    return {"ts": ts, "kind": "item.create", "item": None, "branch": branch, "body": body, "author": author(me)}


def session_event(me: dict, t: dt.datetime, title: str = "", branch: str = "main") -> dict:
    ts = iso(t)
    sid = stamp("LV", t)
    body = {"id": sid, "type": "idea", "title": (title or "Live session " + ts[:16].replace("T", " "))[:96],
            "body": "Live session in progress. Lines arrive as live.line events; replies as comments on this item.",
            "refs": [], "status": "live", "source": "live", "live": {"schema": "live.v1", "started": ts, "audience": [], "via": "desktop"}}
    return {"ts": ts, "kind": "item.create", "item": None, "branch": branch, "body": body, "author": author(me)}


def latest_live_session(docs, me_id: str):
    """The newest session you started that is still live, from /studio/api/events rows ([{doc_id, event}])."""
    started, status = {}, {}
    for d in docs:
        e = (d or {}).get("event") or {}
        b = e.get("body") or {}
        if e.get("kind") == "item.create" and b.get("source") == "live" and (e.get("author") or {}).get("id") == me_id and b.get("id") not in started:
            started[b["id"]] = e.get("ts") or ""
            status[b["id"]] = b.get("status", "open")
        elif e.get("kind") == "status" and e.get("item") in started:
            status[e["item"]] = b.get("status")
    live = [(ts, sid) for sid, ts in started.items() if status.get(sid) == "live"]
    return max(live)[1] if live else None


def segments(levels, threshold: float, frame_ms: int, silence_ms: int = 800, min_ms: int = 400):
    """Always-on mode: cut a stream of per-frame loudness (RMS) into phrases. Returns [(start, end)] frame indexes
    (end exclusive): a phrase starts at the first loud frame and ends after silence_ms of quiet; phrases shorter
    than min_ms of sound are dropped (clicks, coughs). A phrase still open at the end is returned too."""
    out, start, last_loud = [], None, None
    quiet_frames = max(1, silence_ms // frame_ms)
    for i, v in enumerate(levels):
        if v >= threshold:
            if start is None:
                start = i
            last_loud = i
        elif start is not None and i - last_loud >= quiet_frames:
            if (last_loud - start + 1) * frame_ms >= min_ms:
                out.append((start, last_loud + 1))
            start = last_loud = None
    if start is not None and (last_loud - start + 1) * frame_ms >= min_ms:
        out.append((start, last_loud + 1))
    return out
