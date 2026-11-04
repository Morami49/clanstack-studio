"""Shared client plumbing: config, posting events, listening to the spine."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent


def config() -> dict:
    p = Path(os.environ.get("ACTIONMAP_CONFIG", ROOT / "config.yaml"))
    return (yaml.safe_load(p.read_text()) if p.exists() else {}) or {}


class Spine:
    def __init__(self, url: str | None = None, token: str | None = None,
                 node_id: str | None = None, session_id: str | None = None):
        c = config().get("client", {})
        self.url = (url or os.environ.get("ACTIONMAP_URL") or c.get("hub_url") or c.get("spine_url") or "http://127.0.0.1:8765").rstrip("/")
        self.token = token or os.environ.get("ACTIONMAP_TOKEN") or c.get("token") or ""
        self.node_id = node_id or c.get("node_id") or "node"
        sid = session_id or c.get("session_id") or "auto"
        self.session_id = datetime.now().strftime("s-%Y%m%d-%H%M%S") if sid == "auto" else sid
        self.http = httpx.Client(base_url=self.url, timeout=10,
                                 headers={"X-ActionMap-Token": self.token} if self.token else {})

    # -- events ------------------------------------------------------------
    def emit(self, actor_kind: str, actor_id: str, kind: str, action: str,
             target: dict | None = None, payload: dict | None = None,
             causes: list[str] | None = None, surface_id: str | None = None,
             session_id: str | None = None) -> dict:
        ev = {"schema_version": 1, "session_id": session_id or self.session_id,
              "node_id": self.node_id, "surface_id": surface_id or f"{self.node_id}:display0",
              "actor": {"kind": actor_kind, "id": actor_id}, "kind": kind, "action": action,
              "target": target or {}, "payload": payload or {}, "causes": causes or []}
        r = self.http.post("/events", json=ev)
        r.raise_for_status()
        return r.json()

    def register_node(self, capabilities: list[str], surfaces: list[str] | None = None):
        return self.emit("system", f"system:{self.node_id}", "registration", "register_node",
                         payload={"capabilities": capabilities,
                                  "surfaces": surfaces or [f"{self.node_id}:display0"]},
                         session_id="registry")

    def get(self, path: str, **params):
        r = self.http.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict):
        r = self.http.post(path, json=body)
        r.raise_for_status()
        return r.json()

    def control(self, action: str, **body):
        return self.post(f"/control/{action}", body)

    def say(self, actor_id: str, text: str, **kw):
        return self.post("/say", {"actor_id": actor_id, "text": text, "node_id": self.node_id, **kw})

    # -- realtime ----------------------------------------------------------
    def listen(self, on_event: Callable[[dict], None], stop: Callable[[], bool] = lambda: False):
        """Blocking listener with auto-reconnect. Calls on_event(event) for each new event."""
        from websockets.sync.client import connect
        ws_url = self.url.replace("http", "ws", 1) + "/ws" + (f"?token={self.token}" if self.token else "")
        while not stop():
            try:
                with connect(ws_url, open_timeout=5) as ws:
                    for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") == "event":
                            on_event(msg["event"])
                        if stop():
                            return
            except Exception as e:  # spine restarting, network blip...
                print(f"[listen] {e!r}; reconnecting in 2s")
                time.sleep(2)
