"""
Nodach Desktop worker: the MCP server the shell (shell_mcp.py) runs as its child. This is the part that changes;
the shell restarts it when files under app\\ change, so Claude never needs a restart for a new Gate or Pointer.

Serves, in one tool list:
- Gate's tools (gate_mcp.Gate: the same zones, popup, logging and reports as nodach-gate; data stays in
  %USERPROFILE%\\nodach-gate). Gate's own log window is not auto-opened: the Desktop window is the entry point.
- The Pointer's three tools (get_pointed_elements, get_pointer_screenshot, mark_pointed), from pointer_mcp.py
  (data stays in %USERPROFILE%\\nodach-pointer).
- watch_test (decision 77a b, 21 Nov): Claude's test hook into the Watch window, for inputs Windows-MCP's synthetic
  drags can't make (the Select-area overlay ignores them). Gate decides it like a screen tool (Watch on, not paused,
  no privacy moment: auto); every call is logged in Gate's log as kind "test-input"; the Watch app (run\\watch.json:
  port + per-start key) runs it and shows a grey 'test input from Claude' note in its chat.
If Windows-MCP can't start, the Pointer tools and Gate's own two tools still work and the error is in
%USERPROFILE%\\nodach\\run\\worker-status.json (desktop_status shows it).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
import sys
import time
import traceback
from pathlib import Path

WORKER_VERSION = "0.1.1"
HERE = Path(__file__).resolve().parent
APP = Path(os.environ.get("NODACH_DESKTOP_APP") or HERE.parent)
ROOT = Path(os.environ.get("NODACH_DESKTOP_HOME") or (Path.home() / "nodach"))
for sub in ("gate", "pointer"):
    sys.path.insert(0, str(APP / sub))

POINTER_TOOL_DEFS = [
    {"name": "get_pointed_elements", "description": "Nodach Pointer: latest elements Nowed pointed at on his Windows desktop "
     "(newest first). status: new | seen | done | deferred | any. Each event has the app, window, element type/name/"
     "AutomationId, ancestor path, screen rectangle, his note, batch refs and a screenshot path (fetch it with "
     "get_pointer_screenshot).",
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
         "status": {"type": "string", "default": "new", "enum": ["new", "seen", "done", "deferred", "any"]}}}},
    {"name": "get_pointer_screenshot", "description": "Nodach Pointer: the cropped screenshot saved for one pointer event.",
     "inputSchema": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]}},
    {"name": "mark_pointed", "description": "Nodach Pointer: record a status for pointer events: new | seen | done | deferred "
     "(append-only, earlier states stay visible).",
     "inputSchema": {"type": "object", "properties": {
         "event_ids": {"type": "array", "items": {"type": "string"}},
         "status": {"type": "string", "enum": ["new", "seen", "done", "deferred"]}}, "required": ["event_ids", "status"]}},
]
POINTER_NAMES = {t["name"] for t in POINTER_TOOL_DEFS}
WATCH_TEST_DEF = {
    "name": "watch_test",
    "description": "Nodach Watch test hook (for testing the Watch window only). action 'select_area' with args "
    "{x1, y1, x2, y2} runs exactly what a finished Select-area drag runs (crop, UI Automation elements inside, kept-out "
    "redaction, attached to the next line); 'point' with {x, y} does the same for Point; 'state' returns what the Watch "
    "window shows (chip, attachment words, picture on/off, session, last 5 chat rows, visible controls). Coordinates "
    "are screen pixels as Snapshot reports them. Needs Watch on and the Watch window open; refused if the area touches "
    "a kept-out window. Each input is logged in Gate's log and shown in the Watch chat as 'test input from Claude'. "
    "Type and Send with the normal Click/Type tools.",
    "inputSchema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["select_area", "point", "state"]},
        "args": {"type": "object", "description": "select_area: {x1, y1, x2, y2}; point: {x, y}; state: {}",
                 "properties": {"x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"},
                                "y2": {"type": "number"}, "x": {"type": "number"}, "y": {"type": "number"}}}},
        "required": ["action"]}}
INSTRUCTIONS_POINTER = ("Nodach Pointer: when Nowed says he pointed at something (Ctrl+Alt+M on his PC), call "
                        "get_pointed_elements, then mark_pointed with seen/done once handled.")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Worker:
    def __init__(self):
        self.gate = None
        self.gate_error = None
        self.pointer = None
        self.pointer_error = None
        self.started = now_iso()
        try:
            import gate_mcp
            self.gate_mod = gate_mcp
            gate_mcp.ensure_home()
            self.gate = gate_mcp.Gate(autostart_gui=False)
        except Exception as e:
            self.gate_mod, self.gate_error = None, f"Gate didn't load: {type(e).__name__}: {e}"
        try:
            import pointer_mcp
            self.pointer = pointer_mcp
        except Exception as e:
            self.pointer_error = f"Pointer tools didn't load: {type(e).__name__}: {e}"
        self.gate_connected = False

    async def connect(self, stack):
        if not self.gate:
            return
        try:
            async with asyncio.timeout(float(os.environ.get("NODACH_DESKTOP_WMCP_TIMEOUT", "30"))):
                await self.gate.connect(stack)
            self.gate_connected = True
        except BaseException as e:   # noqa: BLE001 - a missing Windows-MCP must not take the Pointer down
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            self.gate_error = f"Windows-MCP didn't start through Gate: {type(e).__name__}: {e}"
        with contextlib.suppress(Exception):
            self.gate.start_threads()

    def tool_defs(self):
        gate_defs = self.gate.tool_defs() + [WATCH_TEST_DEF] if self.gate else []
        return gate_defs + (POINTER_TOOL_DEFS if self.pointer else [])

    def versions(self):
        out = {"worker": WORKER_VERSION}
        with contextlib.suppress(Exception):
            import gate_core
            out["gate"] = gate_core.VERSION
        with contextlib.suppress(Exception):
            import pointer_core
            out["pointer"] = pointer_core.VERSION
        return out

    def write_status(self):
        body = {"pid": os.getpid(), "started": self.started, "versions": self.versions(),
                "gate": {"loaded": bool(self.gate), "windows_mcp_connected": self.gate_connected, "error": self.gate_error,
                         "hidden_tools": getattr(self.gate, "hidden", None)},
                "pointer": {"loaded": bool(self.pointer), "error": self.pointer_error},
                "tools": [t["name"] for t in self.tool_defs()]}
        p = ROOT / "run" / "worker-status.json"
        with contextlib.suppress(Exception):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.with_suffix(".tmp").write_text(json.dumps(body, indent=1), encoding="utf-8")
            os.replace(p.with_suffix(".tmp"), p)

    async def call(self, name: str, args: dict) -> dict:
        if name in POINTER_NAMES:
            if not self.pointer:
                return _err(self.pointer_error or "Pointer tools aren't available.")
            try:
                return await asyncio.to_thread(self._pointer_call, name, args)
            except Exception as e:
                return _err(f"Nodach Pointer: {e}")
        if not self.gate:
            return _err(self.gate_error or "Gate isn't available.")
        if name == "watch_test":
            self.acting(name, True)
            try:
                return await asyncio.to_thread(self.watch_test, str(args.get("action") or ""), dict(args.get("args") or {}))
            finally:
                self.acting(name, False)
        if not self.gate_connected and name not in ("gate_status", "capture_view"):
            return _err(f"Nodach Gate can't reach Windows-MCP: {self.gate_error}. Ask Nowed to check Nodach Desktop's window.")
        if name == "gate_status":
            return await self.gate.call(name, args)
        self.acting(name, True)
        try:
            return await self.gate.call(name, args)
        finally:
            self.acting(name, False)

    # ------------------------------------------------------------ watch_test (decision 77a b)
    def watch_test(self, action: str, args: dict, post=None) -> dict:
        g, core = self.gate, self.gate_mod.core
        t0 = time.time()
        g.reload_zones()
        st = g.state()
        ctx = {"watch": bool(st.get("watch")), "paused": bool(st.get("paused")), "fg_title": ""}
        with contextlib.suppress(Exception):
            import gate_win
            if gate_win.AVAILABLE:
                ctx["fg_title"] = gate_win.foreground().get("title") or ""
        zone, reason = core.decide({"tool": "watch_test", "args": args}, ctx, g.zones)
        log = {"action": action, "args": {k: args[k] for k in ("x1", "y1", "x2", "y2", "x", "y") if k in args},
               "zone": zone, "reason": reason}
        if zone != "auto":
            g.log.add(core.note_entry(t0, "test-input", g.session_id, decision="refused", ok=False, **log))
            extra = " Ask Nowed to turn Watch on if he wants you to test it." if reason == core.WATCH_OFF else " Tell Nowed."
            return _err(f"Nodach Gate refused watch_test: {reason}.{extra}")
        g.last_action_t = time.time()           # the capture hides/shows Watch: not a glitch
        ok, out, err = False, None, ""
        try:
            out = (post or watch_post)(ROOT, f"/api/test/{action}", args)
            ok = True
        except WatchTestError as e:
            err = str(e)
        g.last_action_t = time.time()
        summary = {}
        if ok and isinstance(out, dict):
            ev = out.get("event") or {}
            summary = {"event": ev.get("id"), "words": ev.get("words")} if ev else {"state": True}
        g.log.add(core.note_entry(t0, "test-input", g.session_id, decision="allowed", ok=ok, error=err[:300],
                                  duration_ms=int((time.time() - t0) * 1000), **log, **summary))
        if not ok:
            return _err(f"Nodach Watch: {err}")
        return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}], "is_error": False}

    def acting(self, name: str, on: bool):
        """run\\acting.json: what the Desktop window shows as 'Claude is acting' (Windows-MCP's own overlay is off since
        Gate 0.1.5, so this is the on-screen sign that Claude is driving the PC)."""
        self.active = getattr(self, "active", 0) + (1 if on else -1)
        body = {"active": self.active > 0, "tool": name, "at": now_iso(), "t": time.time(), "pid": os.getpid()}
        p = ROOT / "run" / "acting.json"
        with contextlib.suppress(Exception):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.with_suffix(".tmp").write_text(json.dumps(body), encoding="utf-8")
            os.replace(p.with_suffix(".tmp"), p)

    def _pointer_call(self, name, args):
        p = self.pointer
        if name == "get_pointed_elements":
            text = p.get_pointed_elements(int(args.get("limit", 5)), str(args.get("status", "new")))
            return {"content": [{"type": "text", "text": text}], "is_error": False}
        if name == "mark_pointed":
            text = p.mark_pointed(list(args.get("event_ids") or []), str(args.get("status") or ""))
            return {"content": [{"type": "text", "text": text}], "is_error": False}
        img = p.get_pointer_screenshot(str(args.get("event_id") or ""))
        return {"content": [img.to_image_content()], "is_error": False}

    def close(self):
        with contextlib.suppress(Exception):
            if getattr(self, "active", 0) > 0:
                self.active = 1
                self.acting("", False)
        if self.gate:
            with contextlib.suppress(Exception):
                self.gate.close()


class WatchTestError(Exception):
    pass


def watch_post(root: Path, path: str, body: dict, timeout: float = 120) -> dict:
    """POST to the Watch app's local server with its per-start key (run\\watch.json, written by watch_app.py)."""
    import urllib.error
    import urllib.request
    try:
        info = json.loads((Path(root) / "run" / "watch.json").read_text(encoding="utf-8-sig"))
        port, key = int(info["port"]), str(info["key"])
    except (OSError, ValueError, KeyError, TypeError):
        raise WatchTestError("the Watch window isn't open (no run\\watch.json: Nowed opens it from Nodach Desktop)") from None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body or {}).encode("utf-8"), method="POST",
                                 headers={"X-Watch-Key": key, "Content-Type": "application/json", "Host": f"127.0.0.1:{port}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error") or f"HTTP {e.code}"
        except ValueError:
            msg = f"HTTP {e.code}"
        raise WatchTestError(msg) from None
    except (urllib.error.URLError, OSError) as e:
        raise WatchTestError(f"the Watch window isn't answering ({type(e).__name__}): it may be closed or restarting") from None


def _err(text):
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def build_server(w: Worker):
    import mcp.types as types
    from mcp.server.lowlevel import Server

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[types.Tool.model_validate(d) for d in w.tool_defs()])

    async def call_tool(ctx, params):
        try:
            r = await w.call(params.name, params.arguments or {})
        except Exception as e:
            traceback.print_exc()
            r = _err(f"Nodach Desktop worker error in {params.name}: {type(e).__name__}: {e}")
        content = [types.TextContent(type="text", text=c["text"]) if isinstance(c, dict) else c for c in r["content"]]
        return types.CallToolResult(content=content, is_error=r["is_error"])

    instructions = "\n\n".join(x for x in ((w.gate_mod.INSTRUCTIONS if w.gate_mod else ""), INSTRUCTIONS_POINTER if w.pointer else "") if x)
    return Server("nodach-desktop-worker", version=WORKER_VERSION, instructions=instructions,
                  on_list_tools=list_tools, on_call_tool=call_tool)


async def serve():
    from mcp.server.stdio import stdio_server
    w = Worker()
    async with contextlib.AsyncExitStack() as stack:
        await w.connect(stack)
        w.write_status()
        server = build_server(w)
        try:
            async with stdio_server() as (r, wr):
                await server.run(r, wr, server.create_initialization_options())
        finally:
            w.close()


if __name__ == "__main__":
    asyncio.run(serve())
