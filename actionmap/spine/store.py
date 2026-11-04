"""Append-only, hash-chained event store with multi-hub replication.

Nothing is updated or deleted. Every state the system has ever been in can be
rebuilt by replaying events up to a given seq ("as of" views).

Multi-hub (D-016): every hub has an `origin` id. Each origin keeps its OWN hash
chain (origin_seq 1..n, prev_hash -> hash). Hubs exchange events with
`ingest()`, which only accepts the next link of a foreign chain and re-checks
its hash, so a replicated event is provably the one its origin wrote.
`seq` is local arrival order on this hub and is NOT part of the hash.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64
REQUIRED = ("session_id", "node_id", "actor", "kind", "action")
KINDS = {"action", "observation", "utterance", "proposal", "decision", "control",
         "annotation", "registration", "memory", "routing", "interaction"}
ACTOR_KINDS = {"human", "agent", "system", "screen"}
ASSIGNED = ("seq", "id", "prev_hash", "hash", "origin", "origin_seq")


def canonical(ev: dict) -> str:
    body = {k: v for k, v in ev.items() if k not in ("hash", "seq")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def link_hash(prev: str, ev: dict) -> str:
    return hashlib.sha256((prev + canonical(ev)).encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ValidationError(ValueError):
    pass


def validate(ev: dict, client: bool = True) -> None:
    missing = [k for k in REQUIRED if k not in ev]
    if missing:
        raise ValidationError(f"missing fields: {missing}")
    a = ev["actor"]
    if not isinstance(a, dict) or a.get("kind") not in ACTOR_KINDS or not a.get("id"):
        raise ValidationError("actor must be {kind: human|agent|system|screen, id}")
    if ev["kind"] not in KINDS:
        raise ValidationError(f"kind must be one of {sorted(KINDS)}")
    if client:
        for f in ASSIGNED:
            if f in ev:
                raise ValidationError(f"'{f}' is assigned by the hub; do not send it")


class EventStore:
    def __init__(self, path: str | Path, origin: str = "hub"):
        self.path, self.origin = str(path), origin
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS events (
                   seq INTEGER PRIMARY KEY,
                   id TEXT UNIQUE NOT NULL,
                   ts TEXT NOT NULL,
                   origin TEXT NOT NULL,
                   origin_seq INTEGER NOT NULL,
                   session_id TEXT NOT NULL,
                   kind TEXT NOT NULL,
                   actor_kind TEXT NOT NULL,
                   body TEXT NOT NULL,
                   hash TEXT NOT NULL,
                   UNIQUE(origin, origin_seq))""")
        self._db.execute("CREATE INDEX IF NOT EXISTS ix_session ON events(session_id, seq)")
        self._db.executescript(
            """CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events
                 BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
               CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events
                 BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;""")
        self._db.commit()

    def _tip(self, origin: str) -> tuple[int, str]:
        r = self._db.execute("SELECT origin_seq, hash FROM events WHERE origin=? "
                             "ORDER BY origin_seq DESC LIMIT 1", (origin,)).fetchone()
        return (r[0], r[1]) if r else (0, GENESIS)

    def _insert(self, ev: dict) -> dict:
        r = self._db.execute("SELECT MAX(seq) FROM events").fetchone()
        ev["seq"] = (r[0] or 0) + 1
        self._db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ev["seq"], ev["id"], ev["ts"], ev["origin"], ev["origin_seq"], ev["session_id"],
             ev["kind"], ev["actor"]["kind"], json.dumps(ev, ensure_ascii=False), ev["hash"]))
        self._db.commit()
        return ev

    # -- write -------------------------------------------------------------
    def append(self, ev: dict) -> dict:
        validate(ev)
        ev = dict(ev)
        ev.setdefault("schema_version", 1)
        ev.setdefault("ts", now())
        ev.setdefault("surface_id", ev["node_id"])
        ev.setdefault("target", {})
        ev.setdefault("payload", {})
        ev.setdefault("causes", [])
        with self._lock:
            n, prev = self._tip(self.origin)
            ev.update(id=uuid.uuid4().hex, origin=self.origin, origin_seq=n + 1, prev_hash=prev)
            ev["hash"] = link_hash(prev, ev)
            return self._insert(ev)

    def ingest(self, ev: dict) -> dict | None:
        """Accept one event from another hub. Returns None if already held.
        Raises ValidationError on a gap or a bad hash (caller re-pulls)."""
        validate(ev, client=False)
        ev = {k: v for k, v in ev.items() if k != "seq"}
        o, n = ev.get("origin"), ev.get("origin_seq")
        if not o or not isinstance(n, int) or o == self.origin:
            raise ValidationError("ingest needs a foreign origin and origin_seq")
        with self._lock:
            have = self._db.execute("SELECT 1 FROM events WHERE origin=? AND origin_seq=?", (o, n)).fetchone()
            if have:
                return None
            tip_n, tip_h = self._tip(o)
            if n != tip_n + 1:
                raise ValidationError(f"gap for {o}: have {tip_n}, got {n}")
            if ev.get("prev_hash") != tip_h or link_hash(tip_h, ev) != ev.get("hash"):
                raise ValidationError(f"hash check failed for {o}#{n}")
            return self._insert(ev)

    # -- read --------------------------------------------------------------
    def read(self, session_id: str | None = None, upto: int | None = None,
             after: int = 0, limit: int | None = None) -> list[dict]:
        q, args = "SELECT body FROM events WHERE seq > ?", [after]
        if session_id:
            q += " AND session_id = ?"; args.append(session_id)
        if upto is not None:
            q += " AND seq <= ?"; args.append(upto)
        q += " ORDER BY seq"
        if limit:
            q += " LIMIT ?"; args.append(limit)
        with self._lock:
            return [json.loads(r[0]) for r in self._db.execute(q, args)]

    def read_origin(self, origin: str, after: int = 0, limit: int = 1000) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT body FROM events WHERE origin=? AND origin_seq>? "
                                    "ORDER BY origin_seq LIMIT ?", (origin, after, limit)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def heads(self) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT origin, MAX(origin_seq) FROM events GROUP BY origin").fetchall()
        return {o: n for o, n in rows}

    def get(self, event_id: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT body FROM events WHERE id = ?", (event_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def head(self) -> int:
        with self._lock:
            r = self._db.execute("SELECT MAX(seq) FROM events").fetchone()
        return r[0] or 0

    def sessions(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT session_id, MIN(seq), MAX(seq), COUNT(*), MIN(ts), MAX(ts) "
                "FROM events GROUP BY session_id ORDER BY MIN(seq)").fetchall()
        return [dict(session_id=r[0], first_seq=r[1], last_seq=r[2], events=r[3],
                     started=r[4], last=r[5]) for r in rows]

    def verify(self) -> dict:
        """Check every origin's chain independently."""
        out, total = {}, 0
        for origin in sorted(self.heads()):
            prev, n = GENESIS, 0
            for ev in self.read_origin(origin, 0, 10**9):
                n += 1
                if ev["origin_seq"] != n or ev["prev_hash"] != prev:
                    return {"ok": False, "origin": origin, "broken_at_origin_seq": ev["origin_seq"],
                            "broken_at_seq": ev["seq"], "reason": "link mismatch"}
                h = link_hash(prev, ev)
                if h != ev["hash"]:
                    return {"ok": False, "origin": origin, "broken_at_origin_seq": ev["origin_seq"],
                            "broken_at_seq": ev["seq"], "reason": "hash mismatch"}
                prev = h
            out[origin] = {"events": n, "head_hash": prev}
            total += n
        return {"ok": True, "events": total, "origins": out}

    def export_jsonl(self, out: Path) -> int:
        evs = self.read()
        with open(out, "w", encoding="utf-8") as f:
            for ev in evs:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return len(evs)
