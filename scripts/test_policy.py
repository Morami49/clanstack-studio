"""Tests for policy resolution (Q101 A). Run: python3 scripts/test_policy.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from policy import drift_writes, fold, resolve  # noqa: E402

K = "SET-policy-branch-cleanup"


def d(doc, ts, kind, item=None, **body):
    return {"doc_id": doc, "event": {"ts": ts, "kind": kind, "item": item, "body": body}}


def test_fold_create_edit_and_duplicate():
    docs = [d("b", "2026-11-08T10:01:00Z", "item.edit", K, value="off"),
            d("a", "2026-11-08T10:00:00Z", "item.create", None, id=K, value="ask"),
            d("c", "2026-11-08T10:02:00Z", "item.create", None, id=K, value="auto"),   # duplicate create: ignored
            d("e", "2026-11-08T10:03:00Z", "comment", K, text="x")]
    assert fold(docs, K) == "off"
    assert fold(docs + [d("f", "2026-11-08T10:04:00Z", "item.edit", K, value="auto")], K) == "auto"
    assert fold([], K) is None


def test_resolve_studio_wins_and_flags_drift():
    assert resolve("auto", "auto", "ask") == {"effective": "auto", "studio": "auto", "platform": "auto", "drift": "no"}
    assert resolve("off", "auto", "ask")["effective"] == "off" and resolve("off", "auto", "ask")["drift"] == "yes"
    assert resolve(None, "auto", "ask") == {"effective": "auto", "studio": "unknown", "platform": "auto", "drift": "no"}
    assert resolve(None, "", "ask")["effective"] == "ask"
    assert resolve("auto", "", "ask")["drift"] == "yes"


def test_drift_writes_once_per_drift():
    first = drift_writes(K, "auto", "ask", set())
    assert [w["kind"] for w in first] == ["item.create", "comment"]
    assert first[0]["body"]["id"] == "DRIFT-" + K and first[0]["body"]["type"] == "finding"
    later = drift_writes(K, "auto", "ask", {"DRIFT-" + K})
    assert [w["kind"] for w in later] == ["comment"] and later[0]["idempotency_key"] == first[1]["idempotency_key"]
    assert drift_writes(K, "off", "ask", {"DRIFT-" + K})[0]["idempotency_key"] != first[1]["idempotency_key"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
