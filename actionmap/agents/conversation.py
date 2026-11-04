"""The conversation agent (D-007): talks with you 'like we do', and turns what you
say into controls on the same rails as the map.

Input: any human utterance on the hub (from the voice client, the map's talk box,
or an outside AI relaying). Output: agent utterances (spoken by the voice client)
plus control / decision / memory / note events, each pointing back at the
utterance that caused it.

'this' / 'that' = the step you last clicked on the map (within 2 minutes), else
the last thing you did on screen. Anything that isn't a command goes to the
brain router as conversation, with the map as context.

    python -m agents.conversation
"""
from __future__ import annotations

import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain.router import ProviderError, Router  # noqa: E402
from clients.common import Spine, config         # noqa: E402
from spine.steps import step_key, step_label     # noqa: E402

AGENT = "agent:voice"
SYSTEM = """You are the voice of ActionMap, Nowed's desktop process-mapping and agent-control system.
Speak briefly and naturally (1-3 sentences unless asked for more): your words are read aloud.
You can see the live state, the focused step and recent steps below. You cannot press buttons yourself;
if Nowed wants something done, tell him the exact phrase to say (e.g. "hand this to the agent in suggest mode",
"approve", "pause everything", "remember that ...", "mark Notion private").
Never invent steps that are not in the map. Private apps are not recorded at all; don't speculate about them."""

HELP = ("You can say: pause everything, resume, approve, reject, hand this to the agent in suggest or act mode, "
        "set an agent to observe, suggest or act, what's this, note followed by text, remember that something, "
        "forget something, private or allow when I ask about a new app, and turn always listening, wake word or "
        "push to talk on or off. Anything else, I'll just talk with you about it.")


def resolve_app(spoken: str, state: dict) -> str:
    """'notion' -> 'notion.exe' if that app has been seen; otherwise keep what was said."""
    spoken = spoken.lower().strip()
    known = set(state["privacy"]["apps"]) | set(state["privacy"]["asked"])
    exact = sorted((a for a in known if a in (spoken, spoken + ".exe")), key=lambda a: not a.endswith(".exe"))
    if exact:
        return exact[0]
    partial = sorted((a for a in known if spoken.replace(" ", "") in a.replace(" ", "")), key=len)
    return partial[0] if partial else (spoken if "." in spoken else spoken + ".exe")


class Conversation:
    def __init__(self, sp: Spine, router: Router, human_id: str):
        self.sp, self.router, self.human = sp, router, human_id

    # ------------------------------------------------------------ helpers
    def reply(self, text: str, cause: dict, intent: str):
        self.sp.post("/say", {"actor_id": AGENT, "text": text, "intent": intent, "speak": True,
                              "session_id": cause["session_id"], "node_id": cause.get("node_id"),
                              "causes": [cause["id"]]})

    def focus(self, state: dict) -> str | None:
        f = state.get("focus")
        if f and f.get("step_key"):
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(f["ts"])).total_seconds()
            if age < 120:
                return f["step_key"]
        head = self.sp.get("/sessions")["head"]
        for ev in reversed(self.sp.get("/events", after=max(0, head - 200), limit=200)):
            if ev["kind"] == "action" and ev["actor"]["kind"] == "human":
                return step_key(ev)
        return None

    def history(self, session: str, n: int = 10) -> list[dict]:
        evs = [e for e in self.sp.get("/events", session=session, limit=5000) if e["kind"] == "utterance"][-n:]
        return [{"role": "user" if e["actor"]["kind"] == "human" else "assistant",
                 "content": (e.get("payload") or {}).get("text", "")} for e in evs]

    # ------------------------------------------------------------ commands
    def handle(self, ev: dict):
        text = ((ev.get("payload") or {}).get("text") or "").strip()
        if not text:
            return
        t = text.lower().strip(" .!?")
        t = re.sub(r"^(hey |ok |okay )?(action ?map|jarvis)[, ]*", "", t)
        state = self.sp.get("/state")
        c = [ev["id"]]
        me = self.human

        def ctl(action, **kw):
            return self.sp.post(f"/control/{action}", {"actor_id": me, "causes": c, "via": "voice", **kw})

        if re.match(r"^(help|what can (i|you) (say|do))", t):
            return self.reply(HELP, ev, "help")
        if re.match(r"^(pause|stop)( everything| all| agents| it all)?$|^kill switch", t):
            ctl("pause_all"); return self.reply("Paused. No agent can act until you say resume.", ev, "pause")
        if re.match(r"^(resume|unpause|carry on|continue)( everything| agents)?$", t):
            ctl("resume_all"); return self.reply("Resumed.", ev, "resume")

        m = re.match(r"^(approve|accept|yes do it|go ahead|reject|deny|no don'?t)( all| everything| it| that)?$", t)
        if m:
            pend = sorted(((pid, p) for pid, p in state["proposals"].items() if p["status"] == "pending"),
                          key=lambda x: x[1]["seq"])
            if not pend:
                return self.reply("There's nothing waiting for approval.", ev, "decide")
            ok = m.group(1) in ("approve", "accept", "yes do it", "go ahead")
            chosen = pend if (m.group(2) or "").strip() in ("all", "everything") else pend[-1:]
            for pid, _ in chosen:
                self.sp.post("/decide", {"proposal_id": pid, "approve": ok, "actor_id": me,
                                         "via": "voice", "causes": c})
            what = chosen[-1][1].get("step_key") or "the step"
            return self.reply(f"{'Approved' if ok else 'Rejected'} {len(chosen)}: {step_label(what).splitlines()[0]}.", ev, "decide")

        m = re.match(r"^(hand|give|pass)( this| that| it)?( step)? (over )?to (the )?(?P<agent>[\w:.-]+?)?( agent)?"
                     r"( in (?P<mode>act|suggest|observe)( mode)?)?$", t)
        if m:
            key = self.focus(state)
            if not key:
                return self.reply("I'm not sure which step you mean. Click it on the map, then say it again.", ev, "delegate")
            agents = [a for a, v in state["actors"].items() if v["kind"] == "agent" and a != AGENT]
            want = m.group("agent")
            agent = next((a for a in agents if want and want in a), None) or \
                    ("agent:next-step" if "agent:next-step" in agents else (agents[0] if agents else None))
            if not agent:
                return self.reply("No agent is registered yet. Start one, then ask again.", ev, "delegate")
            mode = m.group("mode") or "suggest"
            ctl("delegate", step_key=key, agent_id=agent, mode=mode)
            return self.reply(f"Handed {step_label(key).splitlines()[0]} to {agent} in {mode} mode.", ev, "delegate")

        m = re.match(r"^(set|put|switch) (?P<agent>[\w:.-]+)( agent)? (to|in|into) (?P<mode>observe|suggest|act)( mode)?$", t)
        if m:
            agent = next((a for a, v in state["actors"].items() if v["kind"] == "agent" and m.group("agent") in a), None)
            if not agent:
                return self.reply(f"I don't know an agent called {m.group('agent')}.", ev, "set_mode")
            ctl("set_mode", agent_id=agent, mode=m.group("mode"))
            return self.reply(f"{agent} is now in {m.group('mode')} mode everywhere it hasn't been given a step.", ev, "set_mode")

        m = re.match(r"^(mark |make |keep )?(?P<app>[\w .-]+?)?( as)? (?P<rule>private|allowed|allow(ed)? it|fine)$", t) \
            or re.match(r"^(?P<rule>private|allow|allowed|it'?s fine|keep it private)$", t)
        if m:
            rule = "private" if "private" in m.group("rule") else "allowed"
            app = (m.groupdict().get("app") or "").strip()
            if app in ("", "it", "that", "this"):
                answered = set(state["privacy"]["apps"])
                waiting = [a for a, s in sorted(state["privacy"]["asked"].items(), key=lambda x: -x[1]) if a not in answered]
                if not waiting:
                    return self.reply("There's no app waiting for a privacy answer.", ev, "privacy")
                app = waiting[0]
            app = resolve_app(app, state)
            ctl("set_privacy", app=app, rule=rule)
            return self.reply(f"{app} is now {rule}." + (" Nothing from it will be recorded." if rule == "private" else ""), ev, "privacy")

        m = re.match(r"^(turn |switch )?(?P<what>always listening|always on|wake word|push to talk)( is)? (?P<on>on|off)$", t) \
            or re.match(r"^(turn |switch )(?P<on>on|off) (?P<what>always listening|always on|wake word|push to talk)$", t)
        if m:
            field = {"always listening": "always", "always on": "always", "wake word": "wake", "push to talk": "ptt"}[m.group("what")]
            ctl("set_listening", node_id=ev.get("node_id"), **{field: m.group("on") == "on"})
            return self.reply(f"{m.group('what').capitalize()} {m.group('on')}.", ev, "listening")

        m = re.match(r"^remember( that)? (?P<fact>.+)$", text, re.I)
        if m:
            fact = m.group("fact").strip()
            key = "stated." + re.sub(r"[^a-z0-9]+", "-", fact.lower())[:48].strip("-")
            self.sp.post("/memory", {"action": "profile_set", "key": key, "value": fact, "source": "stated",
                                     "actor_id": me, "causes": c})
            return self.reply("Noted. It stays on your machines unless you mark it shareable on the map.", ev, "remember")
        m = re.match(r"^forget( that)? (?P<fact>.+)$", t)
        if m:
            words = set(re.findall(r"[a-z0-9]+", m.group("fact")))
            hits = [k for k, v in state["profile"].items()
                    if words and len(words & set(re.findall(r"[a-z0-9]+", f"{k} {v['value']}".lower()))) >= max(1, len(words) // 2)]
            for k in hits:
                self.sp.post("/memory", {"action": "profile_retract", "key": k, "actor_id": me, "causes": c})
            return self.reply(f"Forgot {len(hits)} item{'s' if len(hits) != 1 else ''}." if hits
                              else "I couldn't find that in your profile.", ev, "forget")

        m = re.match(r"^note[:,]? (?P<text>.+)$", text, re.I)
        if m:
            key = self.focus(state)
            self.sp.post("/annotate", {"actor_id": me, "step_key": key, "text": m.group("text")})
            return self.reply("Note added" + (f" to {step_label(key).splitlines()[0]}." if key else "."), ev, "note")

        if re.match(r"^what('?s| is) (this|that)( step)?$", t):
            key = self.focus(state)
            if not key:
                return self.reply("Nothing is selected and I haven't seen you do anything yet.", ev, "describe")
            n = next((x for x in self.sp.get("/map")["nodes"] if x["id"] == key), None)
            if not n:
                return self.reply(f"That's {step_label(key).splitlines()[0]}, seen once so far.", ev, "describe")
            who = ", ".join(f"{k} {v}" for k, v in n["by_kind"].items())
            hand = f" It's handed to {n['delegations'][0]['agent_id']} in {n['delegations'][0]['mode']} mode." if n["delegations"] else ""
            return self.reply(f"{step_label(key).replace(chr(10), ' ')}. Seen {n['count']} times ({who}).{hand}", ev, "describe")

        return self.chat(ev, text, state)

    # ------------------------------------------------------------ chat
    def chat(self, ev: dict, text: str, state: dict):
        ov = self.sp.get("/overview")
        key = self.focus(state)
        g = self.sp.get("/map")
        top = sorted(g["nodes"], key=lambda n: -n["count"])[:20]
        recent = [step_key(e) for e in self.sp.get("/events", after=max(0, ov["head_seq"] - 150), limit=150)
                  if e["kind"] == "action"][-12:]
        profile_all = self.sp.get("/profile", scope="local")
        profile_api = self.sp.get("/profile", scope="api")
        hist = self.history(ev["session_id"])[:-1]

        def build(local: bool) -> list[dict]:
            prof = profile_all if local else profile_api
            ctx = (f"LIVE STATE: {ov}\nFOCUSED STEP: {key}\nTOP STEPS: "
                   + "; ".join(f"{n['id']} x{n['count']} {n['by_kind']}" for n in top)
                   + f"\nRECENT STEPS: {recent}\nPROFILE: {prof}")
            return [{"role": "system", "content": SYSTEM + "\n\n" + ctx}] + hist + [{"role": "user", "content": text}]

        try:
            answer, _ = self.router.complete("chat", build, session_id=ev["session_id"])
        except ProviderError:
            answer = "I can't reach any AI model right now, but voice commands still work. Say help to hear them."
        self.reply(answer, ev, "chat")


def main():
    cfg = config()
    sp = Spine(node_id="agents")
    sp.emit("agent", AGENT, "registration", "register_actor",
            payload={"capabilities": ["converse", "voice.commands"]}, session_id="registry")
    router = Router(cfg, log=lambda meta: sp.post("/routing", dict(meta)))
    human = "human:" + cfg.get("client", {}).get("human_id", "local")
    conv = Conversation(sp, router, human)
    print(f"{AGENT} listening on {sp.url}")

    def on_event(ev):
        if ev["kind"] == "utterance" and ev["actor"]["kind"] == "human":
            threading.Thread(target=_safe, args=(conv, ev), daemon=True).start()

    sp.listen(on_event)


def _safe(conv: Conversation, ev: dict):
    try:
        conv.handle(ev)
    except Exception as e:
        print("[conversation]", repr(e))
        try:
            conv.reply("Something went wrong handling that. It's in the log.", ev, "error")
        except Exception:
            pass


if __name__ == "__main__":
    main()
