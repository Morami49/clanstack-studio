"""Private list (D-010, D-020).

Rules live in the event log as control events (set_privacy), so the list is
versioned like everything else. Classification order:
  1. title patterns marked private   (e.g. 'incognito', banking sites)
  2. per-app rule                    (private / allowed)
  3. title patterns marked allowed
  4. otherwise 'unreviewed'          -> you're asked once; until then window and
                                        element names are masked.

Private activity is never stored. Entering a private app leaves one
placeholder step '[private]' so maps stay continuous without saying what it was.
"""
from __future__ import annotations

import re

PRIVATE_TARGET = {"app": "[private]", "window": "[private]", "element": "[private]"}
MASK = "[unreviewed]"
FILTERED_KINDS = {"action", "observation"}
FILTERED_ACTORS = {"human", "screen", "agent"}


def classify(state: dict, target: dict) -> str:
    pv = state["privacy"]
    app = (target.get("app") or "").lower()
    title = target.get("window") or ""
    for p in pv["patterns"]:
        if p["rule"] == "private" and _match(p["pattern"], title):
            return "private"
    if app in pv["apps"]:
        return pv["apps"][app]
    for p in pv["patterns"]:
        if p["rule"] == "allowed" and _match(p["pattern"], title):
            return "allowed"
    return "unreviewed"


def _match(pattern: str, text: str) -> bool:
    try:
        return bool(re.search(pattern, text, re.I))
    except re.error:
        return pattern.lower() in text.lower()


def filter_event(state: dict, ev: dict) -> tuple[dict | None, str | None]:
    """Returns (event_to_store_or_None, unreviewed_app_or_None)."""
    if ev.get("kind") not in FILTERED_KINDS or ev.get("actor", {}).get("kind") not in FILTERED_ACTORS:
        return ev, None
    t = ev.get("target") or {}
    if not t.get("app") or t.get("app") == "[private]":
        return ev, None
    rule = classify(state, t)
    if rule == "allowed":
        return ev, None
    if rule == "private":
        node = ev.get("node_id")
        if state["privacy"]["in_private"].get(node):
            return None, None                      # already marked; drop silently
        ph = {k: v for k, v in ev.items() if k not in ("target", "payload")}
        ph.update(action="private_activity", target=dict(PRIVATE_TARGET), payload={})
        return ph, None
    # unreviewed: keep the app name only
    ev = dict(ev)
    ev["target"] = {"app": t["app"], "window": MASK, "element": MASK, "role": t.get("role", "")}
    ev["payload"] = {k: v for k, v in (ev.get("payload") or {}).items() if k in ("chars", "redacted", "button")}
    app = t["app"].lower()
    return ev, (app if app not in state["privacy"]["asked"] else None)


def is_private_target(state: dict, target: dict | None) -> bool:
    return bool(target) and (target.get("app") == "[private]" or classify(state, target) == "private")
