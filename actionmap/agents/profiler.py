"""Working-habits profile (D-014 'C', D-019).

Derives a small, readable profile from the event log: the apps you spend steps
in, your most common transitions, when you work, and how much you hand to agents.
Every update is a versioned `memory` event (so you can see what it believed and
when). Items are LOCAL by default; only you can mark one shareable, on the map.

    python -m agents.profiler            # refreshes every profile.refresh_s
    python -m agents.profiler --once
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clients.common import Spine, config  # noqa: E402

ME = "agent:profiler"


def derive(events: list[dict], graph: dict) -> dict:
    acts = [e for e in events if e["kind"] == "action"]
    human = [e for e in acts if e["actor"]["kind"] == "human"]
    apps = Counter((e.get("target") or {}).get("app") for e in human)
    apps.pop(None, None); apps.pop("[private]", None)
    hours = Counter(datetime.fromisoformat(e["ts"]).hour for e in human)
    top_edges = sorted(graph["edges"], key=lambda x: -x["count"])[:5]
    by_kind = Counter(e["actor"]["kind"] for e in acts)
    out = {}
    if apps:
        out["habits.top_apps"] = ", ".join(f"{a} ({n})" for a, n in apps.most_common(5))
    if top_edges:
        out["habits.frequent_transitions"] = "; ".join(
            f"{e['source'].split('|')[2] or e['source']} → {e['target'].split('|')[2] or e['target']} ×{e['count']}"
            for e in top_edges)
    if hours:
        out["habits.active_hours_utc"] = ", ".join(f"{h:02d}h" for h, _ in sorted(hours.most_common(4)))
    if acts:
        share = by_kind.get("agent", 0) / len(acts)
        out["habits.agent_share"] = f"{share:.0%} of recorded actions were done by agents ({by_kind.get('agent', 0)}/{len(acts)})"
    return out


def run_once(sp: Spine) -> int:
    head = sp.get("/sessions")["head"]
    events = sp.get("/events", after=max(0, head - 5000), limit=5000)
    graph = sp.get("/map")
    current = sp.get("/state")["profile"]
    changed = 0
    for k, v in derive(events, graph).items():
        if current.get(k, {}).get("value") != v:
            sp.post("/memory", {"action": "profile_set", "key": k, "value": v, "source": "derived", "actor_id": ME})
            changed += 1
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    sp = Spine(node_id="agents")
    sp.emit("agent", ME, "registration", "register_actor", payload={"capabilities": ["profile.derive"]}, session_id="registry")
    every = config().get("profile", {}).get("refresh_s", 300)
    while True:
        try:
            print(f"[profiler] {run_once(sp)} item(s) updated")
        except Exception as e:
            print("[profiler]", repr(e))
        if a.once:
            return
        time.sleep(every)


if __name__ == "__main__":
    main()
