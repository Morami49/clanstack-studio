"""Core guarantees, no server needed:  python -m tests.test_core"""
import json
import os
import sqlite3
import tempfile

from spine import control, mapper, privacy
from spine.store import EventStore, ValidationError


def ev(kind, action, actor=("human", "human:t"), **kw):
    return {"session_id": kw.pop("session", "t"), "node_id": kw.pop("node", "n1"),
            "actor": {"kind": actor[0], "id": actor[1]}, "kind": kind, "action": action, **kw}


d = tempfile.mkdtemp()
st = EventStore(os.path.join(d, "a.db"), origin="hub-a")
a = st.append(ev("action", "click", target={"app": "X", "element": "A"}))
b = st.append(ev("action", "click", target={"app": "X", "element": "B"}))
assert st.verify()["ok"]

# 1. append-only enforced by the database
try:
    st._db.execute("UPDATE events SET hash='x' WHERE seq=1"); raise SystemExit("update allowed!")
except sqlite3.DatabaseError:
    pass

# 2. as-of state: a hand-off exists only after its seq
st.append(ev("control", "delegate", payload={"step_key": "click|X|B", "agent_id": "agent:a", "mode": "act"}))
assert control.fold(st.read(upto=b["seq"]))["delegations"] == {}
s = control.fold(st.read())
assert control.effective_mode(s, "agent:a", "click|X|B") == "act"
assert control.effective_mode(s, "agent:a", "click|X|A") == "observe"
assert control.effective_mode(s, "ext:claude", None) == "suggest"          # D-018 default

# 3. kill switch beats hand-offs
st.append(ev("control", "pause_all"))
prop = {"actor": {"kind": "agent", "id": "agent:a"}, "payload": {"step": {"action": "click", "target": {"app": "X", "element": "B"}}}}
assert control.policy_for_proposal(control.fold(st.read()), prop)[0] == "reject"
st.append(ev("control", "resume_all"))
assert control.policy_for_proposal(control.fold(st.read()), prop)[0] == "approve"

# 4. map merges human + agent on the same step and marks the hand-off
st.append(ev("action", "click", target={"app": "X", "element": "A"}))
st.append(ev("action", "click", actor=("agent", "agent:a"), target={"app": "X", "element": "B"}))
g = mapper.build(st.read(), control.fold(st.read()))
nB = next(n for n in g["nodes"] if n["id"] == "click|X|B")
assert nB["by_kind"] == {"human": 1, "agent": 1} and nB["dominant"] == "mixed"
assert any("human→agent" in e["handoffs"] for e in g["edges"])

# 5. privacy: private apps leave one placeholder, unreviewed are masked, agents can't act there
st.append(ev("control", "set_privacy", payload={"app": "Bank.exe", "rule": "private"}))
st.append(ev("control", "set_privacy", payload={"pattern": "incognito", "rule": "private"}))
s = control.fold(st.read())
e1, _ = privacy.filter_event(s, ev("action", "focus_window", target={"app": "Bank.exe", "window": "Balance"}))
assert e1["target"]["app"] == "[private]" and e1["payload"] == {}
control.apply(s, {**st.append(e1)})
e2, _ = privacy.filter_event(s, ev("action", "click", target={"app": "Bank.exe", "element": "Pay"}))
assert e2 is None                                                          # nothing more while inside
e3, asked = privacy.filter_event(s, ev("action", "click", target={"app": "New.exe", "window": "Secret", "element": "Btn"}))
assert e3["target"]["window"] == "[unreviewed]" and asked == "new.exe"
e4, _ = privacy.filter_event(s, ev("action", "click", node="n2", target={"app": "chrome.exe", "window": "Incognito - tab"}))
assert e4["target"]["app"] == "[private]"
bad = {"actor": {"kind": "agent", "id": "agent:a"}, "payload": {"step": {"action": "click", "target": {"app": "Bank.exe"}}}}
assert control.policy_for_proposal(s, bad)[0] == "reject"

# 6. profile: versioned, retract hides, history stays
st.append(ev("memory", "profile_set", payload={"key": "k", "value": "v1", "share": "local"}))
st.append(ev("memory", "profile_set", payload={"key": "k", "value": "v2", "share": "api"}))
mid = st.head()
st.append(ev("memory", "profile_retract", payload={"key": "k"}))
assert control.fold(st.read(upto=mid))["profile"]["k"]["value"] == "v2"
assert "k" not in control.fold(st.read())["profile"]

# 7. two hubs: replicate both ways, chains verify per origin, tamper/gaps refused
sb = EventStore(os.path.join(d, "b.db"), origin="hub-b")
sb.append(ev("annotation", "label", payload={"text": "from b"}))
for e in st.read_origin("hub-a"):
    sb.ingest(e)
for e in sb.read_origin("hub-b"):
    st.ingest(e)
assert st.heads() == sb.heads() and st.verify()["ok"] and sb.verify()["ok"]
assert sb.ingest(st.read_origin("hub-a")[0]) is None                       # duplicate ignored
forged = dict(st.append(ev("action", "click", target={"app": "X", "element": "C"})))
forged["target"] = {"app": "X", "element": "EVIL"}
try:
    sb.ingest(forged); raise SystemExit("forged event accepted!")
except ValidationError:
    pass
try:
    sb.ingest({**forged, "origin_seq": forged["origin_seq"] + 5}); raise SystemExit("gap accepted!")
except ValidationError:
    pass

# 8. tampering on disk is detected
raw = sqlite3.connect(os.path.join(d, "a.db")); raw.execute("DROP TRIGGER no_update")
body = json.loads(raw.execute("SELECT body FROM events WHERE seq=2").fetchone()[0]); body["target"]["element"] = "Z"
raw.execute("UPDATE events SET body=? WHERE seq=2", (json.dumps(body),)); raw.commit()
v = EventStore(os.path.join(d, "a.db"), origin="hub-a").verify()
assert not v["ok"] and v["broken_at_seq"] == 2 and v["reason"] == "hash mismatch"

# 9. outside-AI reply parsing
from spine.context import parse_reply
assert parse_reply('x ```actionmap {"say": "hi"} ``` y') == [{"say": "hi"}]
print("all core checks passed (9 groups)")
