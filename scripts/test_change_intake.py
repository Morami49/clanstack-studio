"""Tests for change intake (D-153). Run: python3 scripts/test_change_intake.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from change_intake import approved_changes, issue_body  # noqa: E402


def d(doc, ts, kind, item=None, role="owner", **body):
    return {"doc_id": doc, "event": {"ts": ts, "kind": kind, "item": item, "body": body, "author": {"role": role}}}


def test_only_owner_approved_without_issue():
    docs = [d("a", "1", "item.create", None, id="CR-1", type="change", title="Digest", meta={"test": "lists decisions"}),
            d("b", "2", "status", "CR-1", status="approved"),
            d("c", "1", "item.create", None, id="CR-2", type="change", title="Other"),
            d("e", "2", "status", "CR-2", role="member", status="approved"),          # not the owner
            d("f", "1", "item.create", None, id="CR-3", type="change", title="Done"),
            d("g", "2", "status", "CR-3", status="approved"),
            d("h", "3", "comment", "CR-3", text="sent", issue_url="https://github.com/x/y/issues/1"),
            d("i", "1", "item.create", None, id="Q-1", type="question", title="not a change")]
    got = approved_changes(docs)
    assert [c["id"] for c in got] == ["CR-1"], got
    assert "lists decisions" in issue_body(got[0]) and "CR-1" in issue_body(got[0])


def test_later_status_wins():
    docs = [d("a", "1", "item.create", None, id="CR-1", type="change", title="x"),
            d("b", "2", "status", "CR-1", status="approved"), d("c", "3", "status", "CR-1", status="declined")]
    assert approved_changes(docs) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
