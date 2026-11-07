#!/usr/bin/env python3
"""Chat index (D-117): a branch-aware index of prompts, replies and edits.

Reads a session transcript (JSON Lines, one event per line, each with uuid / parentUuid /
type / timestamp / message) and builds:

  * one entry per prompt the person typed, with a stable id  M-YYMMDD-n-eK
      - n   = the n-th message that day (all edits of one message share n)
      - K   = which edit of that message (e1 is the first version)
  * whether that prompt is on the live branch (what the chat now shows) or superseded
  * whether it was interrupted, the reply code it got (R-YYMMDD-n), and the question /
    reply codes it mentions, so every loop can be found from either end
  * a sha256 of the prompt text, so copies pasted into other chats or tools can be matched

The full prompt text is kept only in the private output; the shared index carries ids,
hashes, codes and branch facts. Usage:

    python3 scripts/chat_index.py TRANSCRIPT.jsonl --out index.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict

REPLY_CODE = re.compile(r"\*\*(R-\d{6}-\d+[a-z]?)\*\*")
MENTIONS = re.compile(r"\b(Q\d{1,3}|R-\d{6}-\d+[a-z]?|D-\d{3}|F-\d{2,3}|W\d(?:\.\d+)?)\b", re.I)
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def _text(row) -> str:
    c = (row.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _is_prompt(row) -> bool:
    if row.get("type") != "user" or row.get("isCompactSummary") or row.get("isMeta") or row.get("isSidechain"):
        return False
    c = (row.get("message") or {}).get("content")
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return False
    t = REMINDER.sub("", _text(row)).strip()
    if not t or t.startswith("<task-notification>") or t.startswith("[Request interrupted"):
        return False
    return True


def _is_interrupt(row) -> bool:
    return row.get("type") == "user" and _text(row).strip().startswith("[Request interrupted")


def build(rows: list[dict]) -> dict:
    rows = [r for r in rows if r.get("uuid")]
    by_id = {r["uuid"]: r for r in rows}
    kids = defaultdict(list)
    for r in rows:
        kids[r.get("parentUuid")].append(r)

    # live branch: walk up from the newest non-sidechain row
    main_rows = [r for r in rows if not r.get("isSidechain") and r.get("timestamp")]
    leaf = max(main_rows, key=lambda r: r["timestamp"]) if main_rows else None
    live = set()
    while leaf is not None:
        live.add(leaf["uuid"])
        leaf = by_id.get(leaf.get("parentUuid"))

    prompts = sorted((r for r in rows if _is_prompt(r)), key=lambda r: r.get("timestamp", ""))

    def turn(p):
        """Assistant text and interruption for the turn this prompt started (until the next prompt)."""
        texts, interrupted, stack = [], False, list(kids[p["uuid"]])
        while stack:
            r = stack.pop()
            if _is_prompt(r):
                continue
            if _is_interrupt(r):
                interrupted = True
            if r.get("type") == "assistant":
                t = _text(r)
                if t.strip():
                    texts.append((r.get("timestamp", ""), t))
            stack.extend(kids[r["uuid"]])
        texts.sort()
        return [t for _, t in texts], interrupted

    # edits = prompts that share a parent; number them in time order
    groups = defaultdict(list)
    for p in prompts:
        groups[p.get("parentUuid")].append(p)
    edit_of = {}
    for g in groups.values():
        for k, p in enumerate(sorted(g, key=lambda r: r.get("timestamp", "")), 1):
            edit_of[p["uuid"]] = (k, len(g), g[0]["uuid"])

    # message numbers per day, shared by all edits of one message
    day_count, msg_no, out = defaultdict(int), {}, []
    for p in prompts:
        k, n, first = edit_of[p["uuid"]]
        if first not in msg_no:
            day = by_id[first].get("timestamp", "")[:10].replace("-", "")[2:]
            day_count[day] += 1
            msg_no[first] = f"M-{day}-{day_count[day]}"
        texts, interrupted = turn(p)
        body = REMINDER.sub("", _text(p)).strip()
        reply_codes = [m for t in texts for m in REPLY_CODE.findall(t)]
        out.append({
            "id": f"{msg_no[first]}-e{k}",
            "message": msg_no[first],
            "edit": k,
            "edits": n,
            "uuid": p["uuid"],
            "ts": p.get("timestamp"),
            "live": p["uuid"] in live,
            "interrupted": interrupted,
            "reply_code": reply_codes[0] if reply_codes else None,
            "mentions": sorted({m.upper() for m in MENTIONS.findall(body)}),
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "chars": len(body),
            "text": body,
        })
    return {
        "prompts": out,
        "messages": len(msg_no),
        "edited_messages": sum(1 for g in groups.values() if len(g) > 1),
        "superseded": sum(1 for p in out if not p["live"]),
    }


def shared_view(index: dict) -> dict:
    """The index without prompt texts: safe for the shared record (P-07)."""
    return {**index, "prompts": [{k: v for k, v in p.items() if k != "text"} for p in index["prompts"]]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("transcript")
    ap.add_argument("--out", help="write the full index (with texts) here; omit to print the shared view")
    a = ap.parse_args(argv)
    rows = [json.loads(line) for line in open(a.transcript, encoding="utf-8") if line.strip()]
    idx = build(rows)
    if a.out:
        json.dump(idx, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    else:
        json.dump(shared_view(idx), sys.stdout, ensure_ascii=False, indent=1)
    print(f"\n{len(idx['prompts'])} prompts · {idx['messages']} messages · {idx['edited_messages']} edited · "
          f"{idx['superseded']} superseded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
