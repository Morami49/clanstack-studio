"""Context pack (D-017 'C'): one markdown file any AI can read, plus a reply format it
can write back. Used by chat-only AIs (paste in / paste out) and by the MCP tool
`get_context_pack`. Only profile items marked share=api are included.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import mapper

IMPORT_RE = re.compile(r"```actionmap\s*(\{.*?\})\s*```", re.S)


def profile_view(state: dict, allow_local: bool) -> dict:
    return {k: v["value"] for k, v in state["profile"].items()
            if allow_local or v.get("share") == "api"}


def overview(store, state: dict) -> dict:
    pend = [{"proposal_id": pid, "by": p["agent_id"], "step_key": p.get("step_key"),
             "reason": p.get("reason")} for pid, p in state["proposals"].items() if p["status"] == "pending"]
    return {
        "head_seq": store.head(),
        "paused": state["paused"],
        "agents": {a: v["mode"] for a, v in state["actors"].items() if v["kind"] == "agent"},
        "handoffs": [{"step_key": d["step_key"], "agent": d["agent_id"], "mode": d["mode"]}
                     for d in state["delegations"].values() if d["active"]],
        "pending_proposals": pend,
        "nodes": {n: v["capabilities"] for n, v in state["nodes"].items() if v["capabilities"]},
        "focus": state.get("focus"),
    }


def recent_steps(store, n: int = 40) -> list[str]:
    from .steps import step_key
    out = []
    for ev in store.read(after=max(0, store.head() - 600)):
        k = step_key(ev)
        if k and ev["kind"] != "utterance":
            out.append(f"#{ev['seq']} {ev['actor']['kind']}:{ev['actor']['id']} {k}")
    return out[-n:]


def build_pack(store, state: dict, for_actor: str, handoff: Path | None) -> str:
    g = mapper.build(store.read(after=max(0, store.head() - 5000)), state)
    top = sorted(g["nodes"], key=lambda n: -n["count"])[:40]
    parts = [
        f"# ActionMap context pack — for {for_actor} — as of seq {store.head()}",
        "You are connected to Nowed's ActionMap: an append-only event log of desktop work by a human, "
        "the screen, and agents, turned into a process map. You may READ this and PROPOSE; a human or the "
        "policy decides. Nothing you write is executed unless approved. Private apps are never recorded.",
        "## How to reply with actions",
        "Put any actions in ONE fenced block tagged `actionmap`, JSON exactly like:",
        "```\n```actionmap\n{\"proposals\": [{\"step_key\": \"<a step_key from the map>\", \"reason\": \"why\"}],\n"
        " \"notes\": [{\"step_key\": \"<step_key>\", \"text\": \"observation\"}],\n"
        " \"say\": \"optional sentence to be spoken aloud to Nowed\"}\n```\n```",
        "Nowed pastes your reply into ActionMap → Import. Everything is logged under your AI's name.",
        "## Live state",
        "```json\n" + json.dumps(overview(store, state), indent=1, default=str) + "\n```",
        "## Process map (top steps; step_key → count, who)",
        "\n".join(f"- `{n['id']}` ×{n['count']} {n['by_kind']}" for n in top) or "(empty)",
        "## Map edges (Mermaid)",
        "```mermaid\n" + mapper.to_mermaid({"nodes": top, "edges": [e for e in g["edges"]
                                           if e["source"] in {n['id'] for n in top}
                                           and e["target"] in {n['id'] for n in top}]}) + "\n```",
        "## Recent steps",
        "\n".join(recent_steps(store)) or "(none)",
        "## Profile (only items Nowed marked shareable)",
        "```json\n" + json.dumps(profile_view(state, allow_local=False), indent=1) + "\n```",
    ]
    if handoff and handoff.exists():
        parts += ["## Project decisions and state (HANDOFF.md)", handoff.read_text(encoding="utf-8")]
    return "\n\n".join(parts)


def parse_reply(text: str) -> list[dict]:
    blocks = []
    for m in IMPORT_RE.finditer(text or ""):
        try:
            blocks.append(json.loads(m.group(1)))
        except json.JSONDecodeError as e:
            blocks.append({"error": f"bad JSON: {e}"})
    return blocks
