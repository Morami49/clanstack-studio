"""Tests for the chat index (D-117). Run: python3 scripts/test_chat_index.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from chat_index import build, shared_view  # noqa: E402


def row(uuid, parent, typ, ts, text, **kw):
    return {"uuid": uuid, "parentUuid": parent, "type": typ, "timestamp": ts,
            "message": {"content": [{"type": "text", "text": text}]}, **kw}


def transcript():
    # m1 → reply R-1; then message 2 is edited twice: e1 answered, e2 interrupted, e3 live
    return [
        row("u1", None, "user", "2026-11-07T10:00:00Z", "<system-reminder>x</system-reminder>q1) A"),
        row("a1", "u1", "assistant", "2026-11-07T10:01:00Z", "**R-261107-1**\n1.1 ok"),
        row("u2", "a1", "user", "2026-11-07T11:00:00Z", "Q67 B, see R-261107-1"),
        row("a2", "u2", "assistant", "2026-11-07T11:01:00Z", "**R-261107-2**"),
        row("u3", "a1", "user", "2026-11-07T11:10:00Z", "Q67 C"),
        row("i3", "u3", "user", "2026-11-07T11:10:30Z", "[Request interrupted by user]"),
        row("u4", "a1", "user", "2026-11-07T11:20:00Z", "Q67 B and W4.1 ok"),
        row("t4", "u4", "user", "2026-11-07T11:20:10Z", "",
            message={"content": [{"type": "tool_result", "content": "x"}]}),
        row("a4", "t4", "assistant", "2026-11-07T11:21:00Z", "**R-261107-3**"),
        row("n5", "a4", "user", "2026-11-07T11:30:00Z", "<task-notification>done</task-notification>"),
    ]


def test_ids_edits_and_branches():
    idx = build(transcript())
    ids = [p["id"] for p in idx["prompts"]]
    assert ids == ["M-261107-1-e1", "M-261107-2-e1", "M-261107-2-e2", "M-261107-2-e3"], ids
    live = {p["id"]: p["live"] for p in idx["prompts"]}
    assert live == {"M-261107-1-e1": True, "M-261107-2-e1": False, "M-261107-2-e2": False, "M-261107-2-e3": True}
    assert idx["messages"] == 2 and idx["edited_messages"] == 1 and idx["superseded"] == 2


def test_replies_interruptions_mentions():
    p = {x["id"]: x for x in build(transcript())["prompts"]}
    assert p["M-261107-1-e1"]["reply_code"] == "R-261107-1"
    assert p["M-261107-2-e1"]["reply_code"] == "R-261107-2"
    assert p["M-261107-2-e2"]["interrupted"] and p["M-261107-2-e2"]["reply_code"] is None
    assert p["M-261107-2-e3"]["reply_code"] == "R-261107-3"   # found past the tool result
    assert p["M-261107-2-e1"]["mentions"] == ["Q67", "R-261107-1"]
    assert p["M-261107-2-e3"]["mentions"] == ["Q67", "W4.1"]
    assert p["M-261107-1-e1"]["text"] == "q1) A"               # reminders stripped


def test_shared_view_has_no_texts():
    s = shared_view(build(transcript()))
    assert all("text" not in p and len(p["sha256"]) == 64 for p in s["prompts"])


def test_compaction_keeps_prior_and_recovers_last_prompt():
    # F-56: after compaction only a summary and a last-prompt row remain
    prior = build(transcript())
    after = [
        row("s1", None, "user", "2026-11-07T12:00:00Z", "summary", isCompactSummary=True,
            summarizedTurnPromptUuids=["u9"]),
        {"type": "last-prompt", "lastPrompt": "Q93 depends", "leafUuid": "x"},
    ]
    idx = build(after, prior)
    ids = [p["id"] for p in idx["prompts"]]
    assert ids[:4] == [p["id"] for p in prior["prompts"]], ids        # nothing lost
    last = idx["prompts"][-1]
    assert last["id"] == "M-261107-3-e1" and last["uuid"] == "u9" and last["from"] == "last-prompt" and last["live"]
    assert last["mentions"] == ["Q93"] and idx["messages"] == 3
    assert build(after, idx)["prompts"] == idx["prompts"]               # re-running adds nothing


def test_edit_after_carry_keeps_message_number():
    # F-59: message 2's first version was indexed alone; an edit arrives later in the same transcript
    rows = transcript()[:2] + [row("v1", "a1", "user", "2026-11-07T12:00:00Z", "Q94 A")]
    first = build(rows)
    assert [p["id"] for p in first["prompts"]] == ["M-261107-1-e1", "M-261107-2-e1"]
    rows.append(row("v2", "a1", "user", "2026-11-07T12:10:00Z", "Q94 A, reproducible"))
    idx = build(rows, first)
    got = {p["id"]: p["live"] for p in idx["prompts"]}
    assert got == {"M-261107-1-e1": True, "M-261107-2-e1": False, "M-261107-2-e2": True}, got
    assert idx["messages"] == 2 and idx["edited_messages"] == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
