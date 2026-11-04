# ActionMap v0.2

A free, local-first system that records what happens on your desktop (you, the screen, agents),
turns it into a live process map, lets you **talk to it like a chat**, and lets you and outside
AIs (Claude, ChatGPT, Gemini, Groq…) **control agents from the map or by voice**.

```
 laptop                                         Oracle VM (always on)
 ┌───────────────────────────────┐   sync    ┌──────────────────────────────┐
 │ hub (hub-laptop)  ◄───────────┼──────────►│ hub (hub-vm)                 │
 │  ▲ capture  ▲ voice  ▲ agents │ hash-     │  ▲ profiler                  │
 │  │ executor │ map UI │ router │ verified  │  ▲ connector (MCP) ◄─ tunnel ─┼─ Claude / ChatGPT
 └───────────────────────────────┘           └──────────────────────────────┘
                     context pack ⇄ paste ⇄ any chat-only AI
```

**Ground rules (all enforced in code):** nothing is ever edited or deleted, every hub keeps its own
hash chain, and everything (controls, privacy rules, profile, model routing) can be viewed as of
any past moment.

## 1. Laptop setup (Windows, ~15 min)

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements-windows.txt -r requirements-voice.txt
```
Free AI keys (optional, recommended): get them from Groq (console.groq.com) and Google AI Studio,
then `setx GROQ_API_KEY ...` and `setx GEMINI_API_KEY ...`. Without keys, commands still work and chat
says it's offline. For fully local chat, install Ollama and `ollama pull qwen2.5:3b`.

Double-click **start_laptop.bat** and open http://127.0.0.1:8765.
Hold **right Ctrl** and speak, or type in the Talk box. Say **"help"** to hear the commands.

Try it without touching your desktop: start only the hub, then `python -m clients.simulate --runs 6`
and `python -m clients.voice --text`.

## 2. Oracle VM (always-on second hub + connector)

1. Install Tailscale (free personal plan) on the laptop and the VM so they reach each other privately.
2. Copy this folder to the VM. In its `config.yaml`: `hub.origin: hub-vm`, `hub.host: 0.0.0.0`, a long
   `hub.token`, and `sync.peers: [{url: http://<laptop-tailscale-ip>:8765, token: ...}]`.
   Set the same token on the laptop (`hub.token`, `client.token`) and point its `sync.peers` at the VM.
3. `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
4. `./start_vm.sh`

Either hub can go offline; sync carries on from the last verified link when it's back.

## 3. Outside AIs

**Connector (Claude, ChatGPT, anything with MCP).** On the VM, add one long random secret per AI:
```yaml
external:
  allowed_hosts: ["<vm-name>.<tailnet>.ts.net"]
  ais: { "<32+ random chars>": ext:claude, "<another>": ext:chatgpt }
```
Expose port 8766 with `tailscale funnel 8766`. Add `https://<vm-name>.<tailnet>.ts.net/<secret>/mcp` as a custom
connector in Claude or ChatGPT (whether this is available depends on your plan). Tools: overview,
get_map, get_events, list_sessions, get_profile, get_context_pack, propose_step, proposal_status,
add_note, say (spoken on your laptop), pause_everything.

**Any other chat AI.** On the map: *Outside AIs → Context pack*. Paste it into the chat, paste the
reply back into *Import*. Its proposals, notes and words are logged under `ext:<name>`.

Outside AIs start in **suggest** mode: they read and propose, and you approve. Hand one a step in
**act** mode on the map to let it run that step.

## Controls

| Control | Map | Voice |
|---|---|---|
| Kill switch | Pause everything | "pause everything" / "resume" |
| Approve or reject | Proposals panel | "approve", "approve all", "reject" |
| Hand a step to an agent or AI | click step → Hand to agent | click step, "hand this to the agent in act mode" |
| Agent's general mode | Agents panel | "set next-step to suggest" |
| Describe a step | click step | "what's this" |
| Note on a step | click step → note | "note: check the PO number" |
| Privacy | New apps / Private list | "private" / "allow", "mark Notion private" |
| Listening presets | Listening panel (per machine) | "turn wake word on", "always listening off" |
| Profile | Your profile: local / shareable / Forget | "remember that…", "forget…" |
| History | Time slider | n/a |

## Privacy defaults (D-010, D-020)

- Password managers, email, messaging and banking (apps and browser tabs), plus anything with
  private / incognito in the title, are **never recorded**. One `[private]` step keeps the map continuous.
- A new app is recorded with its name only (window and element names masked) until you choose
  Private or Allow.
- Typed text is not recorded, only its length. Audio never leaves the laptop; speech is transcribed locally.
- Profile items stay **local** until you mark them shareable. Local-only material only goes to local models.
- Every model call is logged (provider, model, local or cloud, what was skipped) without the content.
- Free cloud tiers may use what you send to improve their products. Keep sensitive apps on the private list.

## Endpoints

Writes: `POST /events /say /propose /decide /annotate /memory /interaction /import /control/{pause_all,resume_all,set_mode,set_capture,delegate,revoke,set_privacy,set_listening} /replicate/push`
Reads: `GET /events /events/{id} /state?upto /overview /map?session&upto&talk&fmt /sessions /profile?scope /listening /verify /route /replicate/heads /replicate/pull /export/{jsonl,pm4py,context-pack}` · `WS /ws`

## Tests

`python -m tests.test_core` covers: append-only, as-of state, kill switch, hand-off mapping, privacy filtering,
versioned profile, two-hub replication with forged and gapped events refused, tamper detection, and import parsing.

To resume this build from any AI tool, see `HANDOFF.md`.
