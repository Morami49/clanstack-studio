"""The agents' 'hands' on a surface.

Waits for APPROVED proposals aimed at this node's surfaces, re-checks the kill
switch, performs the step, then logs an action event whose `causes` point at
the proposal and the approval - so every agent action is traceable to who
allowed it.

    python -m clients.executor --backend dry       # any OS: logs, touches nothing
    python -m clients.executor --backend windows   # really clicks/types (config executor.enabled must be true)
"""
from __future__ import annotations

import argparse
import sys
import time

from .common import ROOT, Spine, config

BUSY = ROOT / "data" / "executor.busy"
ALIASES = {"click": "click_element"}


class DryBackend:
    name = "dry"

    def run(self, step: dict) -> str:
        return f"dry-run: would {step.get('action')} on {step.get('target')}"


class WindowsBackend:
    name = "windows"

    def __init__(self):
        import uiautomation as auto
        self.auto = auto

    def _window(self, title: str):
        w = self.auto.WindowControl(searchDepth=1, SubName=title[:40])
        if not w.Exists(3, 0.2):
            raise RuntimeError(f"window not found: {title!r}")
        w.SetActive()
        return w

    def run(self, step: dict) -> str:
        a = self.auto
        act = ALIASES.get(step["action"], step["action"])
        t = step.get("target") or {}
        p = step.get("payload") or {}
        if act == "focus_window":
            self._window(t.get("window", ""))
            return "focused"
        if act == "click_element":
            w = self._window(t.get("window", ""))
            c = a.Control(searchFromControl=w, Name=t.get("element"), searchDepth=15)
            if not c.Exists(3, 0.2):
                raise RuntimeError(f"element not found: {t.get('element')!r}")
            c.Click(simulateMove=False)
            return "clicked"
        if act == "type_text":
            text = p.get("text")
            if not text:
                raise RuntimeError("type_text needs payload.text (recorded text is redacted)")
            self._window(t.get("window", ""))
            a.SendKeys(text.replace("{", "{{").replace("}", "}}"), waitTime=0.01)
            return f"typed {len(text)} chars"
        if act == "hotkey":
            keys = p.get("keys") or t.get("element", "")
            parts = keys.split("+")
            mod = {"ctrl": "{Ctrl}", "alt": "{Alt}", "shift": "{Shift}", "cmd": "{Win}"}
            seq = "".join(mod.get(k, "") for k in parts[:-1])
            last = parts[-1]
            seq += f"{{{last.capitalize()}}}" if len(last) > 1 else last
            self._window(t.get("window", ""))
            a.SendKeys(seq)
            return f"sent {keys}"
        raise RuntimeError(f"unsupported action {act}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["dry", "windows"], default="dry")
    ap.add_argument("--node", default=None, help="node id (defaults to config client.node_id)")
    a = ap.parse_args()

    cfg = config().get("executor", {})
    allowed = {ALIASES.get(x, x) for x in cfg.get("allowed_actions", ["focus_window", "click_element", "type_text", "hotkey"])}
    if a.backend == "windows":
        if sys.platform != "win32":
            sys.exit("windows backend needs Windows")
        if not cfg.get("enabled"):
            sys.exit("executor.enabled is false in config.yaml - refusing to act on this machine")
        backend = WindowsBackend()
    else:
        backend = DryBackend()

    sp = Spine(node_id=a.node)
    sp.register_node([f"exec.desktop.{backend.name}"])
    print(f"executor[{backend.name}] node={sp.node_id} listening on {sp.url}")

    def handle(ev: dict):
        if ev["kind"] != "decision" or ev["action"] != "approve":
            return
        pid = ev["payload"].get("proposal_id")
        prop = sp.get(f"/events/{pid}")
        surface = prop.get("surface_id") or ""
        if not surface.startswith(sp.node_id):
            return                                     # meant for another machine / VM
        if sp.get("/state")["paused"]:
            print("paused - not executing", pid)
            return
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(prop["ts"])).total_seconds()
        ttl = float(cfg.get("proposal_ttl_s", 30))
        if age > ttl:   # the screen has moved on; acting now would be out of context
            sp.emit("system", f"system:{sp.node_id}", "observation", "execution_refused",
                    payload={"reason": f"stale proposal ({age:.0f}s > {ttl:.0f}s)", "proposal_id": pid},
                    causes=[pid, ev["id"]], surface_id=surface, session_id=prop["session_id"])
            return
        step = prop["payload"]["step"]
        act = ALIASES.get(step["action"], step["action"])
        agent = prop["actor"]["id"]
        base = dict(target=step.get("target"), causes=[pid, ev["id"]],
                    surface_id=surface, session_id=prop["session_id"])
        if act not in allowed:
            sp.emit("system", f"system:{sp.node_id}", "observation", "execution_refused",
                    payload={"reason": f"{act} not in allowed_actions"}, **base)
            return
        try:
            BUSY.parent.mkdir(parents=True, exist_ok=True)
            BUSY.touch()
            result = backend.run(step)
            sp.emit("agent", agent, "action", step["action"],
                    payload={**(step.get("payload") or {}), "result": result,
                             "executed_on": sp.node_id, "backend": backend.name}, **base)
            print("done", step["action"], result)
        except Exception as e:
            sp.emit("system", f"system:{sp.node_id}", "observation", "execution_failed",
                    payload={"error": str(e), "proposal_id": pid}, **base)
            print("failed", e)
        finally:
            BUSY.touch()

    sp.listen(handle)


if __name__ == "__main__":
    main()
