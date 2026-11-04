"""How a raw event becomes a 'step' (a node on the process map).

Actor is deliberately NOT part of the key: when a human and an agent do the
same thing, it is the same step, and the map shows who did it how often.
That is what makes hand-over (human -> agent) visible and controllable.
"""
from __future__ import annotations

MAPPED_KINDS = {"action", "observation", "utterance"}


def _clean(s: str | None, n: int = 48) -> str:
    s = " ".join((s or "").split())
    return s[:n]


def step_key(ev: dict) -> str | None:
    if ev.get("kind") not in MAPPED_KINDS:
        return None
    t = ev.get("target") or {}
    app = _clean(t.get("app")) or "?"
    where = _clean(t.get("element")) or _clean(t.get("window")) or ""
    act = ev.get("action", "?")
    if ev["kind"] == "utterance":
        # Utterances map by intent if the voice layer supplies one, else just 'speak'.
        intent = (ev.get("payload") or {}).get("intent")
        return f"say|{intent or 'free'}|{ev['actor']['kind']}"
    return f"{act}|{app}|{where}"


def step_label(key: str) -> str:
    act, app, where = (key.split("|", 2) + ["", ""])[:3]
    if act == "say":
        return f"🗣 {app} ({where})"
    return f"{act} · {where or '—'}\n[{app}]"
