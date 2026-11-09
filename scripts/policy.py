#!/usr/bin/env python3
"""Resolve an approval policy for an executor (D-133, D-136, Q101 A).

Studio is the source of truth: the value of a Studio setting item (e.g. SET-policy-branch-cleanup) is read
from the hub's copy of Studio (read_events over MCP). The platform's own copy (a GitHub variable) is the
fallback when the hub can't answer or Studio has no value yet, and any difference is reported as drift.

    python3 scripts/policy.py SET-policy-branch-cleanup --platform "$POLICY_BRANCH_CLEANUP" --default ask

Needs HUB_URL and HUB_TOKEN in the environment for the hub read. Writes effective/studio/platform/drift
to $GITHUB_OUTPUT when set, and a line to $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


def fold(docs: list[dict], key: str):
    """The setting's current value from Studio events [{doc_id, event}], in Studio's order (ts, then doc id)."""
    value = None
    for d in sorted(docs, key=lambda d: ((d.get("event") or {}).get("ts") or "", d.get("doc_id") or "")):
        e = d.get("event") or {}
        body = e.get("body") or {}
        if e.get("kind") == "item.create" and body.get("id") == key and "value" in body:
            if value is None:          # a later duplicate create never wins (F-19)
                value = body["value"]
        elif e.get("kind") == "item.edit" and e.get("item") == key and body.get("value") is not None:
            value = body["value"]
    return value


def call_tool(url: str, token: str, name: str, args: dict, n: int = 1) -> dict:
    req = urllib.request.Request(url.rstrip("/") + "/mcp", method="POST", data=json.dumps(
        {"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode(),
        # Cloudflare refuses Python's default client name (F-63), so name the executor
        headers={"authorization": f"Bearer {token}", "content-type": "application/json",
                 "accept": "application/json", "user-agent": "clanstack-policy/1 (+github actions)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["result"]["structuredContent"]


def drift_writes(key: str, studio: str, platform: str, known_items: set) -> list[dict]:
    """Q103 A: Studio wins, the run warns, and Studio gets a finding to resolve. Idempotency keys (F-48) make
    every later run with the same drift a no-op, so the finding isn't repeated on each push."""
    item = f"DRIFT-{key}"
    text = (f"Drift: Studio says {studio}, the platform copy says {platform}. Studio wins. "
            f"Fix the platform setting, or change Studio's {key} if the platform was right.")
    out = []
    if item not in known_items:
        out.append({"kind": "item.create", "item": None, "idempotency_key": f"drift-item/{key}",
                    "body": {"id": item, "type": "finding", "title": f"Policy drift: {key}", "body": text,
                             "status": "open", "refs": [key, "D-139"]}})
    out.append({"kind": "comment", "item": item, "idempotency_key": f"drift/{key}/{studio}/{platform}", "body": {"text": text}})
    return out


def read_hub(url: str, token: str) -> list[dict]:
    docs, after = [], 0
    for i in range(1000):
        page = call_tool(url, token, "read_events", {"after": after, "limit": 200}, i + 1)
        docs += page.get("events") or []
        nxt, total = page.get("next"), page.get("total")
        if nxt is None or nxt <= after or nxt >= total:
            break
        after = nxt
    return docs


def resolve(studio, platform: str, default: str) -> dict:
    studio = None if studio is None else str(studio)
    platform = platform or None
    effective = studio or platform or default
    drift = bool(studio and platform and studio != platform) or bool(studio and not platform and studio != default)
    return {"effective": effective, "studio": studio or "unknown", "platform": platform or "unset", "drift": "yes" if drift else "no"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--platform", default="")
    ap.add_argument("--default", default="ask")
    a = ap.parse_args(argv)
    studio, note, docs = None, "", []
    url, token = os.environ.get("HUB_URL"), os.environ.get("HUB_TOKEN")
    if url and token:
        try:
            docs = read_hub(url, token)
            studio = fold(docs, a.key)
        except Exception as e:  # the hub being down must not stop the executor; the platform copy decides
            note = f" (hub unreadable: {type(e).__name__} {getattr(e, 'code', '')})".replace(" )", ")")
    r = resolve(studio, a.platform, a.default)
    line = (f"Policy {a.key}: **{r['effective']}** — Studio: {r['studio']}{note}, platform: {r['platform']}"
            + (" — ⚠ DRIFT: the platform setting differs from Studio; Studio wins." if r["drift"] == "yes" else ""))
    print(line)
    if r["drift"] == "yes":
        print(f"::warning title=Policy drift::{a.key}: Studio says {r['studio']}, platform says {r['platform']}. Studio wins.")
        known = {((d.get("event") or {}).get("body") or {}).get("id") for d in docs
                 if (d.get("event") or {}).get("kind") == "item.create"}
        try:
            for w in drift_writes(a.key, r["studio"], r["platform"], known):
                print("recorded in Studio:", json.dumps(call_tool(url, token, "write_event", w)))
        except Exception as e:  # recording is best effort; the warning above already stands
            print(f"could not record the drift finding: {type(e).__name__}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.writelines(f"{k}={v}\n" for k, v in r.items())
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(line + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
