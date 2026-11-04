"""Control state, rebuilt purely from events (event-sourced).

`fold(events)` up to any seq gives the exact state at that moment: modes,
hand-offs, pending approvals, privacy rules, profile, listening presets.

Modes (per actor, and per handed-off step):
  observe  - may watch, may not propose
  suggest  - may propose; a human must approve
  act      - may propose; policy auto-approves
Kill switch (pause_all) overrides everything. Agents may never act on private apps.
"""
from __future__ import annotations

from copy import deepcopy

MODES = ("observe", "suggest", "act")
DEFAULT_LISTENING = {"ptt": True, "wake": False, "always": False, "per_app": {}}


def empty_state() -> dict:
    return {
        "seq": 0,
        "paused": False,
        "nodes": {},          # node_id -> {capabilities, surfaces, capture, last_seen}
        "actors": {},         # actor_id -> {kind, mode, capabilities}
        "delegations": {},    # delegation_id -> {step_key, agent_id, mode, active, surface_id}
        "proposals": {},      # proposal_id -> {...status}
        "privacy": {"apps": {}, "patterns": [], "asked": {}, "in_private": {}},
        "profile": {},        # key -> {value, share, source, seq, by}
        "listening": {},      # node_id -> listening preset
        "focus": None,        # last map/screen focus {step_key, seq, ts, via}
    }


def default_mode(actor: dict) -> str:
    if actor["kind"] != "agent":
        return "act"
    return "suggest" if actor["id"].startswith("ext:") else "observe"   # D-018: outside AIs read + propose


def apply(state: dict, ev: dict) -> dict:
    s = state
    s["seq"] = ev["seq"]
    k, a, p = ev["kind"], ev["action"], ev.get("payload") or {}
    actor = ev["actor"]

    s["actors"].setdefault(actor["id"], {"kind": actor["kind"], "mode": default_mode(actor), "capabilities": []})
    nid = ev.get("node_id")
    if nid:
        s["nodes"].setdefault(nid, {"capabilities": [], "surfaces": [], "capture": True, "last_seen": None})
        s["nodes"][nid]["last_seen"] = ev["ts"]

    if k in ("action", "observation") and actor["kind"] in ("human", "screen", "agent"):
        s["privacy"]["in_private"][nid] = (ev.get("target") or {}).get("app") == "[private]"

    if k == "registration":
        if a == "register_node":
            n = s["nodes"][nid]
            n["capabilities"] = sorted(set(p.get("capabilities", [])))
            n["surfaces"] = sorted(set(p.get("surfaces", [ev.get("surface_id")])) - {None})
            n["origin"] = ev.get("origin")
        elif a == "register_actor":
            s["actors"][actor["id"]]["capabilities"] = p.get("capabilities", [])

    elif k == "control":
        if a == "pause_all":
            s["paused"] = True
        elif a == "resume_all":
            s["paused"] = False
        elif a == "set_mode" and p.get("mode") in MODES and p.get("agent_id"):
            s["actors"].setdefault(p["agent_id"], {"kind": "agent", "mode": "observe", "capabilities": []})
            s["actors"][p["agent_id"]]["mode"] = p["mode"]
        elif a == "set_capture" and p.get("node_id"):
            s["nodes"].setdefault(p["node_id"], {"capabilities": [], "surfaces": [], "capture": True, "last_seen": None})
            s["nodes"][p["node_id"]]["capture"] = bool(p.get("enabled", True))
        elif a == "delegate" and p.get("step_key") and p.get("agent_id"):
            s["delegations"][ev["id"]] = {"step_key": p["step_key"], "agent_id": p["agent_id"],
                                          "mode": p.get("mode", "suggest"), "active": True,
                                          "surface_id": p.get("surface_id"), "since_seq": ev["seq"]}
        elif a == "revoke":
            d = s["delegations"].get(p.get("delegation_id"))
            if d:
                d["active"] = False
                d["revoked_seq"] = ev["seq"]
        elif a == "set_privacy":
            pv = s["privacy"]
            rule = p.get("rule")
            if p.get("app") and rule in ("private", "allowed"):
                pv["apps"][p["app"].lower()] = rule
            elif p.get("app") and rule == "clear":
                pv["apps"].pop(p["app"].lower(), None)
            if p.get("pattern"):
                pv["patterns"] = [x for x in pv["patterns"] if x["pattern"] != p["pattern"]]
                if rule in ("private", "allowed"):
                    pv["patterns"].append({"pattern": p["pattern"], "rule": rule})
        elif a == "set_listening":
            node = p.get("node_id") or nid
            cur = s["listening"].setdefault(node, deepcopy(DEFAULT_LISTENING))
            for f in ("ptt", "wake", "always"):
                if f in p:
                    cur[f] = bool(p[f])
            if isinstance(p.get("per_app"), dict):
                cur["per_app"].update(p["per_app"])

    elif k == "interaction":
        if a == "privacy_question" and p.get("app"):
            s["privacy"]["asked"][p["app"].lower()] = ev["seq"]
        elif a in ("map_focus", "screen_focus"):
            s["focus"] = {"step_key": p.get("step_key"), "seq": ev["seq"], "ts": ev["ts"], "via": a}

    elif k == "memory":
        if a == "profile_set" and p.get("key"):
            s["profile"][p["key"]] = {"value": p.get("value"), "share": p.get("share", "local"),
                                      "source": p.get("source", "derived"), "seq": ev["seq"],
                                      "by": actor["id"]}
        elif a == "profile_retract":
            s["profile"].pop(p.get("key"), None)

    elif k == "proposal":
        s["proposals"][ev["id"]] = {"status": "pending", "agent_id": actor["id"],
                                    "step": p.get("step"), "step_key": p.get("step_key"),
                                    "surface_id": ev.get("surface_id"), "reason": p.get("reason"),
                                    "seq": ev["seq"], "origin": ev.get("origin")}
    elif k == "decision":
        pr = s["proposals"].get(p.get("proposal_id"))
        if pr and pr["status"] == "pending":
            pr["status"] = "approved" if a == "approve" else "rejected"
            pr["decided_by"] = actor["id"]
            pr["decision_id"] = ev["id"]
            pr["decision_note"] = p.get("note")
    elif k == "action":
        for c in ev.get("causes") or []:
            pr = s["proposals"].get(c)
            if pr and pr["status"] == "approved":
                pr["status"] = "executed"
                pr["executed_by"] = actor["id"]
                pr["action_id"] = ev["id"]
    return s


def fold(events) -> dict:
    s = empty_state()
    for ev in events:
        apply(s, ev)
    return s


def effective_mode(state: dict, agent_id: str, step_key: str | None) -> str:
    """A hand-off on a specific step overrides the agent's general mode."""
    if state["paused"]:
        return "observe"
    if step_key:
        for d in state["delegations"].values():
            if d["active"] and d["agent_id"] == agent_id and d["step_key"] == step_key:
                return d["mode"]
    a = state["actors"].get(agent_id)
    return a["mode"] if a else default_mode({"kind": "agent", "id": agent_id})


def policy_for_proposal(state: dict, proposal: dict) -> tuple[str, str] | None:
    """('approve'|'reject', note) for an automatic decision, or None = human decides."""
    from .privacy import is_private_target
    from .steps import step_key
    if state["paused"]:
        return ("reject", "system paused (kill switch)")
    agent = proposal["actor"]["id"]
    step = (proposal.get("payload") or {}).get("step") or {}
    if is_private_target(state, step.get("target")):
        return ("reject", "target is on the private list; agents may not act there")
    key = step_key({"kind": "action", **step}) if step else None
    mode = effective_mode(state, agent, key)
    if mode == "observe":
        return ("reject", f"{agent} is in observe mode for this step")
    if mode == "act":
        return ("approve", f"auto-approved: {agent} in act mode")
    return None


def listening_for(state: dict, node_id: str, app: str | None = None) -> dict:
    cur = deepcopy(state["listening"].get(node_id, DEFAULT_LISTENING))
    over = cur["per_app"].get((app or "").lower()) if app else None
    if over:
        cur.update({k: v for k, v in over.items() if k in ("ptt", "wake", "always")})
    return cur


def snapshot(state: dict) -> dict:
    return deepcopy(state)
