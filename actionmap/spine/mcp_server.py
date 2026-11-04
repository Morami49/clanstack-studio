"""Connector for outside AIs (D-017, D-018): Claude, ChatGPT, or anything that speaks MCP.

Each AI gets its own secret URL, so everything it reads or does is keyed to it
(ext:claude, ext:chatgpt, ...). It runs as a separate process and talks to the
hub like any other client, so only THIS port needs exposing through a tunnel.

    python -m spine.mcp_server
    -> http://127.0.0.1:8766/<secret>/mcp   (one per entry in external.ais)

Default powers (D-018 'B'): read everything recorded, propose steps, add notes,
speak through your speakers, press the kill switch. Approvals stay human unless
you hand a step to that AI in 'act' mode on the map (D-018 'C').
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

import httpx
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clients.common import config  # noqa: E402

INSTRUCTIONS = """ActionMap is Nowed's desktop process map: an append-only log of what a human, the screen and agents do,
turned into a map of steps (step_key = action|app|element). Start with `overview`, then `get_map`.
You may propose steps (a human or the policy decides), add notes, and speak to Nowed. Private apps are never recorded.
Everything you do is logged under your own name."""


def hub_client() -> httpx.Client:
    c = config().get("client", {})
    url = os.environ.get("ACTIONMAP_URL") or c.get("hub_url", "http://127.0.0.1:8765")
    tok = os.environ.get("ACTIONMAP_TOKEN") or c.get("token") or config().get("hub", {}).get("token", "")
    return httpx.Client(base_url=url.rstrip("/"), timeout=30, headers={"X-ActionMap-Token": tok} if tok else {})


def build_server(actor: str, hub: httpx.Client, security: TransportSecuritySettings) -> tuple[MCPServer, Starlette]:
    mcp = MCPServer(name="ActionMap", instructions=INSTRUCTIONS, version="0.2.0")

    def get(path, **params):
        r = hub.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json() if "json" in r.headers.get("content-type", "") else r.text

    def post(path, body):
        r = hub.post(path, json=body)
        if r.status_code >= 400:
            return {"error": r.text}
        return r.json()

    @mcp.tool(description="Live state: pause status, agents and their modes, hand-offs, pending proposals, focus.")
    def overview() -> str:
        return json.dumps(get("/overview"), default=str)

    @mcp.tool(description="Process map. Optional session id and 'upto' seq for a past view. Returns steps with counts and who did them, plus edges.")
    def get_map(session: str | None = None, upto: int | None = None) -> str:
        g = get("/map", session=session, upto=upto)
        nodes = [{"step_key": n["id"], "count": n["count"], "by_kind": n["by_kind"],
                  "handed_to": [(d["agent_id"], d["mode"]) for d in n["delegations"]]} for n in g["nodes"]]
        edges = [{"from": e["source"], "to": e["target"], "count": e["count"], "handoffs": e["handoffs"]} for e in g["edges"]]
        return json.dumps({"upto_seq": g["upto_seq"], "steps": nodes, "edges": edges, "notes": g.get("annotations", [])})

    @mcp.tool(description="Raw events after a given seq (max 300). Optional session filter.")
    def get_events(after: int = 0, session: str | None = None, limit: int = 100) -> str:
        evs = get("/events", after=after, session=session, limit=min(limit, 300))
        slim = [{k: e.get(k) for k in ("seq", "ts", "session_id", "actor", "kind", "action", "target", "payload")} for e in evs]
        return json.dumps(slim, default=str)

    @mcp.tool(description="List recording sessions.")
    def list_sessions() -> str:
        return json.dumps(get("/sessions"))

    @mcp.tool(description="Nowed's working-habits profile: only the items he has marked shareable.")
    def get_profile() -> str:
        return json.dumps(get("/profile", scope="api"))

    @mcp.tool(description="Full context pack (markdown): state, map, recent steps, shareable profile, project decisions.")
    def get_context_pack() -> str:
        return get("/export/context-pack", **{"for": actor})

    @mcp.tool(description="Propose doing a known step (use a step_key from get_map). Approval follows your mode: usually Nowed approves.")
    def propose_step(step_key: str, reason: str, text: str | None = None) -> str:
        r = post("/propose", {"actor_id": actor, "step_key": step_key, "reason": reason, "text": text, "via": "mcp"})
        if "error" in r:
            return json.dumps(r)
        st = get("/state")["proposals"].get(r["id"], {})
        return json.dumps({"proposal_id": r["id"], "status": st.get("status", "pending"), "note": st.get("decision_note")})

    @mcp.tool(description="Check what happened to a proposal.")
    def proposal_status(proposal_id: str) -> str:
        return json.dumps(get("/state")["proposals"].get(proposal_id, {"error": "unknown"}), default=str)

    @mcp.tool(description="Attach a note to a step on the map.")
    def add_note(step_key: str, text: str) -> str:
        return json.dumps(post("/annotate", {"actor_id": actor, "step_key": step_key, "text": text}).get("seq"))

    @mcp.tool(description="Say something to Nowed. It is spoken aloud by his voice client and shown on the map.")
    def say(text: str) -> str:
        r = post("/say", {"actor_id": actor, "text": text, "via": "mcp", "speak": True})
        return "said" if "seq" in r else json.dumps(r)

    @mcp.tool(description="Emergency stop: pause every agent. Only Nowed can resume.")
    def pause_everything(reason: str) -> str:
        r = post("/control/pause_all", {"actor_id": actor, "reason": reason})
        return "paused" if "seq" in r else json.dumps(r)

    app = mcp.streamable_http_app(streamable_http_path="/mcp", transport_security=security)
    return mcp, app


def create_app() -> Starlette:
    ext = config().get("external", {})
    ais = ext.get("ais") or {}
    if not ais:
        raise SystemExit("No outside AIs configured. Add `external.ais: {<long-random-secret>: ext:claude}` to config.yaml.")
    for secret in ais:
        if len(secret) < 24 or secret.startswith("change-me"):
            raise SystemExit(f"Secret for {ais[secret]} is too short or still a placeholder; use 24+ random characters.")
    port = int(ext.get("mcp_port", 8766))
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}"] + list(ext.get("allowed_hosts", []))
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                         allowed_origins=[f"https://{h}" for h in ext.get("allowed_hosts", [])]
                                         + [f"http://127.0.0.1:{port}", "https://claude.ai", "https://chatgpt.com"])
    hub = hub_client()
    servers, routes = [], []
    for secret, actor in ais.items():
        mcp, sub = build_server(actor, hub, security)
        servers.append(mcp)
        routes.append(Mount(f"/{secret}", app=sub))
    routes.append(Route("/", lambda r: PlainTextResponse("ActionMap connector. Use your personal URL.")))

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with contextlib.AsyncExitStack() as stack:
            for m in servers:
                await stack.enter_async_context(m.session_manager.run())
            yield

    return Starlette(routes=routes, lifespan=lifespan)


def main():
    ext = config().get("external", {})
    app = create_app()
    print(f"ActionMap connector on http://{ext.get('mcp_host','127.0.0.1')}:{ext.get('mcp_port',8766)}/<secret>/mcp "
          f"for {list((ext.get('ais') or {}).values())}")
    uvicorn.run(app, host=ext.get("mcp_host", "127.0.0.1"), port=int(ext.get("mcp_port", 8766)), log_level="warning")


if __name__ == "__main__":
    main()
