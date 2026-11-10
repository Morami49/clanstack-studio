#!/usr/bin/env python3
"""Change intake (D-153): approved change requests in Studio become GitHub issues for the builder.

Reads Studio's shared record from the hub, finds items of type "change" whose latest status is "approved"
and that were approved by the owner, opens one GitHub issue each (body: the request, its story, its test, and
the builder brief), then writes the issue link back to Studio and moves the request to "building".
Idempotency keys (F-48) make a re-run harmless. Needs HUB_URL, HUB_TOKEN and GH_TOKEN (for `gh`).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from policy import call_tool, read_hub  # noqa: E402


def approved_changes(docs: list[dict]) -> list[dict]:
    """Change requests whose latest status is 'approved' by an owner and that have no issue yet."""
    items: dict[str, dict] = {}
    for d in sorted(docs, key=lambda d: ((d.get("event") or {}).get("ts") or "", d.get("doc_id") or "")):
        e = d.get("event") or {}
        b = e.get("body") or {}
        kind, target = e.get("kind"), e.get("item")
        if kind == "item.create" and b.get("type") == "change" and b.get("id") not in items:
            items[b["id"]] = {"id": b["id"], "title": b.get("title", ""), "why": b.get("body", ""), "meta": b.get("meta") or {},
                              "status": b.get("status", "proposed"), "approved_by_owner": False, "issue": None}
        elif target in items and kind == "status":
            it = items[target]
            it["status"] = b.get("status")
            it["approved_by_owner"] = b.get("status") == "approved" and (e.get("author") or {}).get("role") == "owner"
        elif target in items and kind == "comment" and b.get("issue_url"):
            items[target]["issue"] = b["issue_url"]
    return [i for i in items.values() if i["status"] == "approved" and i["approved_by_owner"] and not i["issue"]]


def issue_body(c: dict) -> str:
    m = c["meta"]
    return (f"**Studio change request {c['id']}** ({m.get('kind', 'code')}, {m.get('size', '?')})\n\n"
            f"### What\n{c['title']}\n\n### Why, for whom\n{c['why'] or '(not given)'}\n\n"
            f"### Done when (test to pass)\n{m.get('test') or '(not given)'}\n\n"
            "### For the builder\n- Context: `actionmap/HANDOFF.md` and `actionmap/CLUSTERS.md`.\n"
            "- Work on a `b-` branch; CI must pass; main is fast-forwarded only after green CI.\n"
            "- Add or update a Studio scenario test that proves the 'Done when' line.\n"
            f"- Mention `{c['id']}` in the commit so the run records link back.\n")


def main() -> int:
    url, token = os.environ.get("HUB_URL"), os.environ.get("HUB_TOKEN")
    if not (url and token):
        print("no hub credentials"); return 0
    todo = approved_changes(read_hub(url, token))
    print(f"{len(todo)} approved change request(s) waiting")
    made = []
    for c in todo:
        out = subprocess.run(["gh", "issue", "create", "--title", f"[{c['id']}] {c['title']}"[:250], "--body", issue_body(c)],
                             capture_output=True, text=True, check=True).stdout.strip()
        link = out.splitlines()[-1]
        for w in ({"kind": "comment", "item": c["id"], "idempotency_key": f"intake/{c['id']}/issue",
                   "body": {"text": f"Sent to the builder as {link}", "issue_url": link}},
                  {"kind": "status", "item": c["id"], "idempotency_key": f"intake/{c['id']}/building", "body": {"status": "building"}}):
            call_tool(url, token, "write_event", w)
        made.append(f"{c['id']} → {link}")
        print("opened", made[-1])
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"count={len(made)}\nlist={'; '.join(made)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
