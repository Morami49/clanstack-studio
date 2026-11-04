"""Reference agent: learns 'what usually comes next' from the map and offers to do it.

It is deliberately simple (no LLM) so the control rails can be tested first.
Swap the `choose()` function for an LLM/local model later - the rails
(proposal -> policy/human decision -> executor -> logged action) stay the same.

Several instances with different --id values can run at once; each only acts
on steps delegated to it (or everywhere if its general mode allows), and they
see each other's actions on the shared log - that is agent-to-agent chaining.

    python -m agents.next_step --id agent:next-step
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clients.common import Spine          # noqa: E402
from spine.control import effective_mode  # noqa: E402
from spine.steps import step_key          # noqa: E402

TRIGGER_KINDS = {"action", "observation"}


def choose(graph: dict, key: str, min_support: int, min_conf: float, allowed=lambda k: True):
    """Most frequent next step among those this agent is allowed to propose.
    Confidence is still measured against ALL observed next steps."""
    outs = [e for e in graph["edges"] if e["source"] == key]
    total = sum(e["count"] for e in outs)
    cands = [e for e in outs if allowed(e["target"])]
    if not cands or total == 0:
        return None
    best = max(cands, key=lambda e: e["count"])
    conf = best["count"] / total
    if best["count"] < min_support or conf < min_conf:
        return None
    return best["target"], conf, best["count"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="agent:next-step")
    ap.add_argument("--min-support", type=int, default=2)
    ap.add_argument("--min-confidence", type=float, default=0.5)
    ap.add_argument("--max-chain", type=int, default=15, help="max agent actions in a row without a human action")
    a = ap.parse_args()

    sp = Spine(node_id="agents")
    sp.emit("agent", a.id, "registration", "register_actor",
            payload={"capabilities": ["propose.next_step"]}, session_id="registry")
    chain = {"n": 0}
    recent: dict[str, float] = {}
    print(f"{a.id} listening on {sp.url}")

    def handle(ev: dict):
        if ev["kind"] not in TRIGGER_KINDS:
            return
        if ev["actor"]["kind"] == "human":
            chain["n"] = 0
        elif ev["actor"]["kind"] == "agent":
            chain["n"] += 1
            if chain["n"] >= a.max_chain:
                return
        key = step_key(ev)
        if not key:
            return
        graph = sp.get("/map")
        state = sp.get("/state")
        pick = choose(graph, key, a.min_support, a.min_confidence,
                      allowed=lambda k: effective_mode(state, a.id, k) != "observe")
        if not pick:
            return
        nxt, conf, support = pick
        if time.time() - recent.get(nxt, 0) < 3:     # don't spam the same suggestion
            return
        recent[nxt] = time.time()
        node = next(n for n in graph["nodes"] if n["id"] == nxt)
        template = sp.get(f"/events/{node['last_event_id']}")
        payload = {k: v for k, v in (template.get("payload") or {}).items()
                   if k not in ("x", "y", "result", "executed_on", "backend")}
        surface = ev.get("surface_id")
        for d in state["delegations"].values():
            if d["active"] and d["agent_id"] == a.id and d["step_key"] == nxt and d.get("surface_id"):
                surface = d["surface_id"]
        sp.emit("agent", a.id, "proposal", "propose_step",
                payload={"step": {"action": template["action"], "target": template["target"],
                                  "payload": payload},
                         "step_key": nxt, "confidence": round(conf, 2), "support": support,
                         "reason": f"after '{key}' this came next {support}× ({conf:.0%})"},
                causes=[ev["id"]], surface_id=surface, session_id=ev["session_id"])

    sp.listen(handle)


if __name__ == "__main__":
    main()
