"""Event log -> process map (directly-follows graph), plus exports.

Built-in so it needs nothing installed. For heavier process mining, export
with `to_pm4py_csv` and load in PM4Py (inductive miner, BPMN, conformance).
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from .steps import step_key, step_label


def build(events: list[dict], state: dict | None = None, talk: bool = False) -> dict:
    """talk=False leaves conversation (utterances) off the workflow map."""
    if not talk:
        events = [e for e in events if e.get("kind") != "utterance"]
    nodes: dict[str, dict] = {}
    edges: Counter = Counter()
    edge_actors: dict[tuple, Counter] = defaultdict(Counter)
    last_by_session: dict[str, tuple[str, str]] = {}

    for ev in events:
        key = step_key(ev)
        if not key:
            continue
        n = nodes.setdefault(key, {"id": key, "label": step_label(key), "count": 0,
                                   "by_kind": Counter(), "by_actor": Counter(),
                                   "first_seq": ev["seq"], "last_seq": ev["seq"],
                                   "surfaces": set(), "last_event_id": None})
        n["count"] += 1
        n["by_kind"][ev["actor"]["kind"]] += 1
        n["by_actor"][ev["actor"]["id"]] += 1
        n["last_seq"] = ev["seq"]
        n["last_event_id"] = ev["id"]
        n["surfaces"].add(ev.get("surface_id") or ev.get("node_id"))

        sid = ev["session_id"]
        prev = last_by_session.get(sid)
        if prev:
            edges[(prev[0], key)] += 1
            edge_actors[(prev[0], key)][f"{prev[1]}→{ev['actor']['kind']}"] += 1
        last_by_session[sid] = (key, ev["actor"]["kind"])

    delegated = defaultdict(list)
    if state:
        for did, d in state["delegations"].items():
            if d["active"]:
                delegated[d["step_key"]].append({"delegation_id": did, **d})

    out_nodes = []
    for n in nodes.values():
        kinds = n["by_kind"]
        dominant = kinds.most_common(1)[0][0]
        out_nodes.append({**n, "by_kind": dict(kinds), "by_actor": dict(n["by_actor"]),
                          "surfaces": sorted(s for s in n["surfaces"] if s),
                          "dominant": dominant if len(kinds) == 1 else "mixed",
                          "delegations": delegated.get(n["id"], [])})
    out_edges = [{"source": a, "target": b, "count": c,
                  "handoffs": dict(edge_actors[(a, b)])} for (a, b), c in edges.items()]
    return {"nodes": out_nodes, "edges": out_edges,
            "events_considered": len(events),
            "upto_seq": events[-1]["seq"] if events else 0}


def to_mermaid(graph: dict) -> str:
    ids = {n["id"]: f"s{i}" for i, n in enumerate(graph["nodes"])}
    lines = ["flowchart TD"]
    for n in graph["nodes"]:
        label = n["label"].replace('"', "'").replace("\n", "<br/>")
        lines.append(f'  {ids[n["id"]]}["{label}<br/>×{n["count"]} {n["dominant"]}"]')
    for e in graph["edges"]:
        lines.append(f'  {ids[e["source"]]} -->|{e["count"]}| {ids[e["target"]]}')
    return "\n".join(lines)


def to_pm4py_csv(events: list[dict], out: Path) -> int:
    """Columns follow PM4Py / XES naming so `pm4py.read_csv`-style loading is direct."""
    n = 0
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case:concept:name", "concept:name", "time:timestamp",
                    "org:resource", "org:role", "surface", "seq"])
        for ev in events:
            key = step_key(ev)
            if not key:
                continue
            w.writerow([ev["session_id"], key, ev["ts"], ev["actor"]["id"],
                        ev["actor"]["kind"], ev.get("surface_id", ""), ev["seq"]])
            n += 1
    return n
