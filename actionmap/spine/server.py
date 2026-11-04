"""The hub: one small HTTP + WebSocket service every component talks to.

Run:  python -m spine.server            (reads config.yaml)
Then open http://127.0.0.1:8765

Capture, voice, agents, executors, outside AIs and other hubs are all clients.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse

from . import context, control, mapper, privacy
from .store import EventStore, ValidationError

ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.2.0"


def load_config() -> dict:
    p = Path(os.environ.get("ACTIONMAP_CONFIG", ROOT / "config.yaml"))
    return (yaml.safe_load(p.read_text()) if p.exists() else {}) or {}


def create_app(store: EventStore, cfg: dict | None = None) -> FastAPI:
    cfg = cfg or {}
    hub = cfg.get("hub", {})
    token = hub.get("token") or os.environ.get("ACTIONMAP_TOKEN") or None
    hub_node = store.origin
    app = FastAPI(title="ActionMap hub", version=VERSION)
    clients: set[WebSocket] = set()
    state = control.empty_state()

    def auth(x_actionmap_token: str | None = Header(default=None),
             token_q: str | None = Query(default=None, alias="token")):
        if token and token not in (x_actionmap_token, token_q):
            raise HTTPException(401, "bad or missing X-ActionMap-Token")

    def apply_safe(ev: dict):
        try:
            control.apply(state, ev)
        except Exception as e:      # a malformed event must never take the hub down
            print(f"[state] could not apply #{ev.get('seq')} {ev.get('kind')}/{ev.get('action')}: {e!r}")

    async def broadcast(ev: dict):
        msg = json.dumps({"type": "event", "event": ev, "paused": state["paused"]})
        for ws in list(clients):
            try:
                await ws.send_text(msg)
            except Exception:
                clients.discard(ws)

    def sys_event(kind, action, payload, session="control", causes=None, actor="system:hub"):
        return {"session_id": session, "node_id": hub_node, "actor": {"kind": "system", "id": actor},
                "kind": kind, "action": action, "payload": payload, "causes": causes or []}

    async def commit(ev: dict, filtered: bool = True) -> dict:
        asked = None
        if filtered:
            ev, asked = privacy.filter_event(state, ev)
            if ev is None:
                return {"dropped": True, "reason": "private"}
        saved = store.append(ev)
        apply_safe(saved)
        await broadcast(saved)
        if asked:
            await commit(sys_event("interaction", "privacy_question",
                                   {"app": asked, "question": f"New app '{asked}': private or allowed?"},
                                   causes=[saved["id"]]), filtered=False)
        if saved["kind"] == "proposal":
            verdict = control.policy_for_proposal(state, saved)
            if verdict:
                act, note = verdict
                await commit(sys_event("decision", act, {"proposal_id": saved["id"], "note": note},
                                       session=saved["session_id"], causes=[saved["id"]],
                                       actor="system:policy"), filtered=False)
        return saved

    def seed_privacy():
        if any(e["kind"] == "control" and e["action"] == "set_privacy" for e in store.read()):
            return []
        pv = cfg.get("privacy", {})
        evs = [sys_event("control", "set_privacy", {"app": a, "rule": "private"}, actor="system:seed")
               for a in pv.get("private_apps", [])]
        evs += [sys_event("control", "set_privacy", {"pattern": p, "rule": "private"}, actor="system:seed")
                for p in pv.get("private_title_patterns", [])]
        for e in evs:
            apply_safe(store.append(e))
        return evs

    for _ev in store.read():
        apply_safe(_ev)
    seed_privacy()

    # ---------------------------------------------------------------- write
    @app.post("/events", dependencies=[Depends(auth)])
    async def post_event(ev: dict):
        node = state["nodes"].get(ev.get("node_id"), {})
        if ev.get("kind") in ("action", "observation") and node.get("capture") is False \
                and ev.get("actor", {}).get("kind") == "human":
            return {"dropped": True, "reason": "capture disabled for this node"}
        try:
            return await commit(ev)
        except ValidationError as e:
            raise HTTPException(422, str(e))

    CONTROL = {"pause_all", "resume_all", "set_mode", "set_capture", "delegate", "revoke",
               "set_privacy", "set_listening"}

    @app.post("/control/{action}", dependencies=[Depends(auth)])
    async def post_control(action: str, body: dict | None = None):
        body = dict(body or {})
        if action not in CONTROL:
            raise HTTPException(404, f"control actions: {sorted(CONTROL)}")
        actor_id = body.pop("actor_id", "human:local")
        kind = "agent" if actor_id.startswith(("agent:", "ext:")) else "human"
        if kind == "agent" and action not in ("pause_all",):
            raise HTTPException(403, "agents may only press the kill switch")
        causes = body.pop("causes", [])
        node = hub_node if action in ("set_capture", "set_listening") else body.pop("node_id", hub_node)
        return await commit({"session_id": body.pop("session_id", "control"), "node_id": node,
                             "actor": {"kind": kind, "id": actor_id},
                             "kind": "control", "action": action, "payload": body, "causes": causes}, filtered=False)

    @app.post("/decide", dependencies=[Depends(auth)])
    async def decide(body: dict):
        pid = body.get("proposal_id")
        pr = state["proposals"].get(pid)
        if not pr:
            raise HTTPException(404, "unknown proposal")
        if pr["status"] != "pending":
            raise HTTPException(409, f"proposal already {pr['status']}")
        actor_id = body.get("actor_id", "human:local")
        if not actor_id.startswith("human:"):
            raise HTTPException(403, "only humans decide pending proposals")
        return await commit({"session_id": body.get("session_id", "control"), "node_id": hub_node,
                             "actor": {"kind": "human", "id": actor_id}, "kind": "decision",
                             "action": "approve" if body.get("approve") else "reject",
                             "payload": {"proposal_id": pid, "note": body.get("note"),
                                         "via": body.get("via", "ui")},
                             "causes": [pid] + body.get("causes", [])}, filtered=False)

    def template_for(step_key: str) -> dict:
        g = mapper.build(store.read(), state)
        node = next((n for n in g["nodes"] if n["id"] == step_key), None)
        if not node:
            raise HTTPException(404, f"unknown step_key {step_key!r}")
        t = store.get(node["last_event_id"])
        payload = {k: v for k, v in (t.get("payload") or {}).items()
                   if k not in ("x", "y", "result", "executed_on", "backend")}
        return {"action": t["action"], "target": t["target"], "payload": payload,
                "surface_id": t.get("surface_id"), "session_id": t["session_id"]}

    @app.post("/propose", dependencies=[Depends(auth)])
    async def propose(body: dict):
        """Propose a known step by its step_key (used by outside AIs and voice)."""
        actor_id = body.get("actor_id", "")
        if not actor_id.startswith(("agent:", "ext:")):
            raise HTTPException(403, "proposals come from agent:* or ext:* actors")
        t = template_for(body["step_key"])
        if body.get("text") and t["action"] == "type_text":
            t["payload"]["text"] = body["text"]
        return await commit({"session_id": body.get("session_id") or t["session_id"], "node_id": hub_node,
                             "surface_id": body.get("surface_id") or t["surface_id"],
                             "actor": {"kind": "agent", "id": actor_id}, "kind": "proposal",
                             "action": "propose_step",
                             "payload": {"step": {k: t[k] for k in ("action", "target", "payload")},
                                         "step_key": body["step_key"], "reason": body.get("reason", ""),
                                         "via": body.get("via", "api")},
                             "causes": body.get("causes", [])}, filtered=False)

    @app.post("/annotate", dependencies=[Depends(auth)])
    async def annotate(body: dict):
        actor_id = body.get("actor_id", "human:local")
        kind = "agent" if actor_id.startswith(("agent:", "ext:")) else "human"
        return await commit({"session_id": body.get("session_id", "control"), "node_id": hub_node,
                             "actor": {"kind": kind, "id": actor_id}, "kind": "annotation", "action": "label",
                             "payload": {"step_key": body.get("step_key"), "text": body.get("text", "")}},
                            filtered=False)

    @app.post("/interaction", dependencies=[Depends(auth)])
    async def interaction(body: dict):
        action = body.get("action")
        if action not in ("map_focus", "screen_focus"):
            raise HTTPException(422, "action: map_focus | screen_focus")
        return await commit({"session_id": "control", "node_id": body.get("node_id", hub_node),
                             "actor": {"kind": "human", "id": body.get("actor_id", "human:local")},
                             "kind": "interaction", "action": action,
                             "payload": {"step_key": body.get("step_key")}, "causes": body.get("causes", [])}, filtered=False)

    @app.post("/say", dependencies=[Depends(auth)])
    async def say(body: dict):
        """Text or transcribed speech into the conversation."""
        actor_id = body.get("actor_id", "human:local")
        kind = "human" if actor_id.startswith("human:") else "agent"
        return await commit({"session_id": body.get("session_id", "conversation"),
                             "node_id": body.get("node_id", hub_node),
                             "actor": {"kind": kind, "id": actor_id}, "kind": "utterance",
                             "action": "speak",
                             "payload": {"text": body.get("text", ""), "via": body.get("via", "text"),
                                         "intent": body.get("intent"), "speak": body.get("speak", kind != "human")},
                             "causes": body.get("causes", [])},
                            filtered=False)

    @app.post("/memory", dependencies=[Depends(auth)])
    async def memory(body: dict):
        action = body.get("action")
        if action not in ("profile_set", "profile_retract"):
            raise HTTPException(422, "action: profile_set | profile_retract")
        actor_id = body.get("actor_id", "human:local")
        kind = "human" if actor_id.startswith("human:") else "agent"
        if kind == "agent" and body.get("share") == "api":
            raise HTTPException(403, "only a human can mark a profile item shareable")
        p = {k: body[k] for k in ("key", "value", "share", "source") if k in body}
        if action == "profile_set" and "share" not in p:   # an update never silently changes who can see it
            prev = state["profile"].get(p.get("key"))
            p["share"] = prev["share"] if prev else cfg.get("profile", {}).get("default_share", "local")
        return await commit({"session_id": "profile", "node_id": hub_node,
                             "actor": {"kind": kind, "id": actor_id}, "kind": "memory",
                             "action": action, "payload": p, "causes": body.get("causes", [])}, filtered=False)

    @app.post("/routing", dependencies=[Depends(auth)])
    async def routing(body: dict):
        """Brain router logs its choices here (no prompt content)."""
        return await commit({"session_id": body.pop("session_id", "conversation"), "node_id": body.pop("node_id", hub_node),
                             "actor": {"kind": "system", "id": "system:router"}, "kind": "routing",
                             "action": "route", "payload": body}, filtered=False)

    # ---------------------------------------------------------------- import (chat-only AIs)
    @app.post("/import", dependencies=[Depends(auth)])
    async def import_reply(body: dict):
        platform = (body.get("platform") or "unknown").lower().replace(" ", "-")
        actor_id = f"ext:{platform}"
        results = []
        for blk in context.parse_reply(body.get("text", "")):
            if "error" in blk:
                results.append(blk); continue
            for pr in blk.get("proposals", []):
                try:
                    results.append(await propose({"actor_id": actor_id, "step_key": pr["step_key"],
                                                  "reason": pr.get("reason", ""), "via": "import"}))
                except HTTPException as e:
                    results.append({"error": e.detail, "step_key": pr.get("step_key")})
            for n in blk.get("notes", []):
                results.append(await annotate({"actor_id": actor_id, "step_key": n.get("step_key"), "text": n.get("text", "")}))
            if blk.get("say"):
                results.append(await say({"actor_id": actor_id, "text": blk["say"], "via": "import"}))
        if not results:
            raise HTTPException(422, "no ```actionmap {...}``` block found")
        return {"actor": actor_id, "results": [{"seq": r.get("seq"), "kind": r.get("kind"), "error": r.get("error")} for r in results]}

    # ---------------------------------------------------------------- replication (D-016)
    @app.get("/replicate/heads", dependencies=[Depends(auth)])
    def rep_heads():
        return {"origin": store.origin, "heads": store.heads()}

    @app.get("/replicate/pull", dependencies=[Depends(auth)])
    def rep_pull(origin: str, after: int = 0, limit: int = Query(default=500, le=2000)):
        return store.read_origin(origin, after, limit)

    @app.post("/replicate/push", dependencies=[Depends(auth)])
    async def rep_push(events: list[dict]):
        added, err = 0, None
        for ev in events:
            try:
                saved = store.ingest(ev)
            except ValidationError as e:
                err = str(e); break
            if saved:
                apply_safe(saved)
                await broadcast(saved)
                added += 1
        return {"added": added, "error": err, "heads": store.heads()}

    # ----------------------------------------------------------------- read
    @app.get("/events", dependencies=[Depends(auth)])
    def get_events(session: str | None = None, upto: int | None = None,
                   after: int = 0, limit: int | None = Query(default=500, le=5000)):
        return store.read(session, upto, after, limit)

    @app.get("/events/{event_id}", dependencies=[Depends(auth)])
    def get_event(event_id: str):
        ev = store.get(event_id)
        if not ev:
            raise HTTPException(404, "unknown event")
        return ev

    @app.get("/state", dependencies=[Depends(auth)])
    def get_state(upto: int | None = None):
        return state if upto is None else control.fold(store.read(upto=upto))

    @app.get("/overview", dependencies=[Depends(auth)])
    def get_overview():
        return context.overview(store, state)

    @app.get("/profile", dependencies=[Depends(auth)])
    def get_profile(scope: str = "local"):
        return context.profile_view(state, allow_local=(scope == "local"))

    @app.get("/listening", dependencies=[Depends(auth)])
    def get_listening(node_id: str, app_name: str | None = None):
        return control.listening_for(state, node_id, app_name)

    @app.get("/map", dependencies=[Depends(auth)])
    def get_map(session: str | None = None, upto: int | None = None, fmt: str = "json", talk: bool = False):
        evs = store.read(session, upto)
        st = control.fold(store.read(upto=upto)) if upto else state
        g = mapper.build(evs, st, talk=talk)
        if fmt == "mermaid":
            return PlainTextResponse(mapper.to_mermaid(g))
        g["head"] = store.head()
        g["annotations"] = [{**e["payload"], "by": e["actor"]["id"]} for e in store.read(upto=upto) if e["kind"] == "annotation"]
        return g

    @app.get("/sessions", dependencies=[Depends(auth)])
    def sessions():
        return {"sessions": store.sessions(), "head": store.head(), "origin": store.origin}

    @app.get("/verify", dependencies=[Depends(auth)])
    def verify():
        return store.verify()

    @app.get("/route", dependencies=[Depends(auth)])
    def route(capability: str):
        return {"capability": capability,
                "nodes": [nid for nid, n in state["nodes"].items() if capability in n["capabilities"]]}

    @app.get("/export/context-pack", dependencies=[Depends(auth)])
    def export_pack(for_actor: str = Query(default="ext:any", alias="for")):
        return PlainTextResponse(context.build_pack(store, state, for_actor, ROOT / "HANDOFF.md"),
                                 media_type="text/markdown")

    @app.get("/export/pm4py", dependencies=[Depends(auth)])
    def export_pm4py(session: str | None = None):
        out = ROOT / "data" / "exports" / f"pm4py_{session or 'all'}_{store.head()}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        n = mapper.to_pm4py_csv(store.read(session), out)
        return FileResponse(out, filename=out.name, headers={"X-Rows": str(n)})

    @app.get("/export/jsonl", dependencies=[Depends(auth)])
    def export_jsonl():
        out = ROOT / "data" / "exports" / f"events_{store.origin}_{store.head()}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        store.export_jsonl(out)
        return FileResponse(out, filename=out.name)

    # ------------------------------------------------------------- realtime
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        if token and sock.query_params.get("token") != token:
            await sock.close(code=4401)
            return
        await sock.accept()
        clients.add(sock)
        await sock.send_text(json.dumps({"type": "hello", "head": store.head(), "origin": store.origin,
                                         "paused": state["paused"]}))
        try:
            while True:
                await sock.receive_text()
        except WebSocketDisconnect:
            clients.discard(sock)

    @app.get("/")
    def ui():
        return FileResponse(ROOT / "ui" / "index.html")

    app.state.store, app.state.hub_state = store, state
    return app


def main():
    import uvicorn
    cfg = load_config()
    h = cfg.get("hub", {})
    store = EventStore(ROOT / h.get("db", "data/actionmap.db"), origin=h.get("origin", "hub"))
    app = create_app(store, cfg)
    print(f"ActionMap hub {VERSION} origin={store.origin} on http://{h.get('host','127.0.0.1')}:{h.get('port',8765)}")
    uvicorn.run(app, host=h.get("host", "127.0.0.1"), port=int(h.get("port", 8765)), log_level="warning")


if __name__ == "__main__":
    main()
