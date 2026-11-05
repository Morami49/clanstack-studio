# HANDOFF — ActionMap

Paste this file (or point any AI tool at this folder) to resume. It is the single source of truth
for decisions and state. **Append** to the logs below; never rewrite earlier entries.

## What this is
Free, local-first voice agent platform with process mapping and human / screen / agent action
modelling. Phase 1 (rails) is built; voice is next. Owner: Nowed.

## Decision log (append-only)

| ID | Date | Decision (owner's codes / words) | Consequence in the build |
|---|---|---|---|
| D-001 | 2026-11-01 | Purpose **A+D**: map own workflows AND produce agent-training data; build rails that extend to client audits (B) and product features (C). | One event schema for everything; PM4Py + JSONL exports; consent/redaction defaults on from day one. |
| D-002 | 2026-11-01 | Hardware **agnostic**, balance CPU-local and VM/cloud; minimise re-engineering as capacity grows. | Nodes self-register capabilities; `/route` placement; HTTP+JSON contract so parts are swappable. |
| D-003 | 2026-11-01 | Agent role: **combinable observe / suggest / act**, for human↔agent and agent↔agent, same screen or across virtual screens. | Per-actor general mode + per-step delegation (optional target surface); policy engine; executor per node; kill switch. |
| D-004 | 2026-11-01 | Eye tracking **dropped for now**. | `gaze` fields left out of schema v1; add as an `observation` with `action: gaze` later — no schema break. |
| D-005 | 2026-11-01 | Maps **live AND replay**, and **the maps are the controls**. | Time slider over event seq; control state is event-sourced so as-of views are exact; controls on map nodes. |
| D-006 | 2026-11-01 | Capture scope **whole Windows desktop**. | pynput + Windows UI Automation (element names, not pixels). |
| D-007 | 2026-11-01 | Voice does **all**: controls, narration, full conversation "like we do"; control via voice + multi-input/multi-media maps combined. | Voice is a client; utterances are events; deictic "this" resolves to map/screen selection. |
| D-008 | 2026-11-01 | Brain placement **per task** (local vs API routed). | Router with logged routing decisions. |
| D-009 | 2026-11-01 | Listening: **customisable presets**, any combination of push-to-talk / wake word / always-on. | Per-app/per-node listening policy, as control events. |
| D-010 | 2026-11-02 | Privacy rule **10C**: anything may go to API unless app is on a private list. | Private list is a control event set; redaction before routing. |
| D-011 | 2026-11-02 | Hardware now: **laptop without GPU + Oracle free VM**. | CPU STT/TTS locally; LLM mostly via API; VM for always-on services. |
| D-012 | 2026-11-02 | APIs: **Gemini + Groq, not limited to them**; Claude, ChatGPT and other platforms must operate it via API **or directly through chat conversations**. | Provider adapters + an external-AI access surface (method pending Q17). |
| D-013 | 2026-11-02 | Speech language: **English only**. | English-only Whisper models. |
| D-014 | 2026-11-02 | Memory **14C**: past sessions + summarised working-habit profile. | Profile stored as versioned events with review/delete controls. |
| D-015 | 2026-11-02 | Users: **just Nowed now**, with clear moulds/guardrails ready for multi-person (B). | Actor/consent/redaction templates defined, multi-user off. |
| D-016 | 2026-11-02 | Hub on **both laptop and Oracle VM, kept in sync** (16C). | Per-origin hash chains; link-by-link replication re-verified on arrival; `clients/sync.py`. |
| D-017 | 2026-11-02 | Outside AIs via **MCP connector + context pack for everything else** (17C). | `spine/mcp_server.py` (one secret URL per AI); `/export/context-pack` + `/import`. |
| D-018 | 2026-11-02 | Outside AI powers **read + propose by default, and agent-style modes when handed a step** (18B+C). | `ext:*` actors default to suggest; same hand-off/policy rails as agents; only humans decide pending proposals. |
| D-019 | 2026-11-02 | Profile **local by default, per-item opt-in to share** (19A+B). | `share: local|api` per item; only humans can mark shareable; router only sends local items to local models. |
| D-020 | 2026-11-02 | Private list day one: **passwords, banking, email, messaging + private/incognito titles; ask once for new apps** (20B + 20C minus "empty"). | Seeded as versioned control events; unreviewed apps masked until answered. |
| D-021 | 2026-11-02 | Phase 2 build: **minimal slice of voice + hub/connectors together** (21C). | v0.2 below. |
| D-022 | 2026-11-02 | "Forget" **hides but keeps history** for now (22A). Crypto-shredding left open. | No change. |
| D-023 | 2026-11-02 | Wake word: built-in **"hey jarvis"** for now (23A). | No change. |
| D-024 | 2026-11-02 | Next: **Windows field test → better voice → smarter agent**, laid out so multi-person (D) slots in later. | Roadmap order. |
| D-025 | 2026-11-02 | Everything may change (via outside AI chats or inside the system): needs a **visual version tree** with **parallel sessions resumable from any point**, for this system and as the foundation for what it builds. | Pending design: see open questions 25–31. |
| D-026 | 2026-11-02 | Direction: **Rust/WASM** so it runs, syncs and load-balances across any browser, network, device, instance, blockchain. | Foundation workspace (sibling folder). |
| D-027 | 2026-11-02 | Version tree covers **intents; facts on one trunk; rehearsal branches keep simulated facts separate** (25C). | `Layer::{Fact,Intent}`, `Realm::Rehearsal`. |
| D-028 | 2026-11-02 | Merge disagreements: **user controls between "always ask" and "rules per type"** (26 B↔C). | `policy/merge/<type>` = ask/auto, versioned per branch; defaults: notes/lists/profile auto, everything else ask. |
| D-029 | 2026-11-02 | Blockchain role: **free version of a shared multi-party ledger** (27C free). | Own signed, replicated ledger with no fees; public anchoring optional later. |
| D-030 | 2026-11-02 | **Full Rust rewrite now, then test** (28C). | Core done first (v0.3.0); hub, sync, UI, native edges next; field test after. |
| D-031 | 2026-11-02 | Stack: **own DAG + iroh + Leptos** (29A). | foundation-core is our own DAG; iroh and Leptos in the next steps. |
| D-032 | 2026-11-02 | Identity: **wallet-style keys; under each identity, users set keys, approvals and flows for devices and sub-identities on their maps** (30C+). | Grants/revocations as facts; flows as intents; managed from the map. |
| D-033 | 2026-11-02 | **Name the foundation separately** from ActionMap; name not chosen yet (31A). | Working name "foundation"; renaming is one find-and-replace. |
| D-034 | 2026-11-03 | **Scopes, each encrypted, built before any sharing** (35A). | Scope keys handed out by grants; required before shared ledger / multi-person. |
| D-035 | 2026-11-03 | **Chain-neutral keys; wallets linked by signed statement** (36A). | ed25519 stays; `chain link` facts later. |
| D-036 | 2026-11-03 | Foundation is **Clanstack's technical core** (37A); **name stays a placeholder** until a naming/domain/IP pass, as for every project. | Placeholder "foundation"; naming + domain + IP workstream to be scheduled. |
| D-037 | 2026-11-03 | Next build: **Rust hub in Axum, compatible with the ActionMap API** (39A). | Starts once Q32–34 and Q38 are settled (they shape identity and permissions). |
| D-038 | 2026-11-03 | Vision: **an Apple-style ecosystem**. Clanstack is reachable from any device; devices and cloud platforms pool compute and networking; data, actions and UI customisable at any scope (device, multi-device, account/sub-account, group/community, any mix). Every platform, upgrade or device added makes it stronger. | Pool + placement + settings cascade (pending Q41–Q46). |
| D-039 | 2026-11-03 | Users (Nowed included) must be able to **change and re-template** anything and feel safe doing so. | Templates are branches; preview + undo via the tree; charter protects. |
| D-040 | 2026-11-03 | Recovery: **spare devices (2 of N) + paper phrase** for now (R1 A+C). | Vouchers later with groups. |
| D-041 | 2026-11-03 | Revocation and rule changes: **adaptive, situation by situation**, combining cut-off, quarantine, witness and two-device confirm so actions stay verifiable without false positives stalling UX (R2, R3). | Risk-based assurance levels; every escalation logged for tuning. |
| D-042 | 2026-11-03 | **Modes become grants** (R4 A). | One permission model; map still shows observe/suggest/act. |
| D-043 | 2026-11-03 | Owner preference: **index every line** of responses so they can be quoted, reinforced or challenged. | Response format. |
| D-044 | 2026-11-04 | **Develop Clanstack from within Clanstack**, soon: a live canvas where Nowed and AIs work together with mixed inputs (sketch, map, voice, text) and precise commands, reaching digital, physical, community, publishing and IoT systems. Everything discussed, intended or built across chats is absorbed, modularised for reproducibility, and fed into pressure-testing and distribution/monetisation flows. Any individual or community designs experiences across canvases and shares them. | Clanstack Studio v0 (artifact) started as the first in-system workspace. |
| D-045 | 2026-11-04 | Nowed answers within his current bandwidth; **Claude must be proactive** in structuring, embedding and branching assets and enquiries, with defaults he can challenge. | Defaults-in-force for "?" answers, marked challengeable. |
| D-046 | 2026-11-04 | Licence: **nothing by default**; developer access levels later; apps inside Clanstack may be privately traded or open/exportable as their communities or organisations decide (4.1). | Licence becomes a per-app charter setting. |
| D-047 | 2026-11-04 | Settings cascade: **most specific wins, charter locks override**, plus protections for minority cases (4.3). | Rights floor proposed. |
| D-048 | 2026-11-04 | Placement: **anywhere if encrypted by default**, with own-devices-only available for private activities (4.4). | Storage/sync anywhere encrypted; processing follows placement (see objection). |
| D-049 | 2026-11-04 | Free tiers: **one account per provider**, and friends may pool their own free tiers (4.5). | Friends contribute under their own identity and keys. |
| D-050 | 2026-11-04 | Others may **run their own Clanstack for free** (5.1). | |
| D-051 | 2026-11-04 | Providers: **any, subject to guarantees** (5.3). | Provider guarantee profiles checked by placement. |
| D-052 | 2026-11-04 | Devices: **computer for deep work; phone for capturing, circulating, delegating, scheduling ideas and agent/community comms** (5.4). | Studio has a phone capture view. |
| D-053 | 2026-11-04 | **Develop Studio rigorously**: test with Nowed's answers (chat or Studio) and simulated users across personal, interpersonal and organisational states, so outcomes are ergonomically validated. | studio/tests/scenarios.py (18 scenarios) runs on every change; findings live in Studio as F-items. |
| D-054 | 2026-11-04 | **Keep asking the highest-priority questions in chat and mirror them into Studio at once.** Priority: less later security/CI/CD/overhaul debt; immediate utility across work, life, mind, body, spirit, connections, networking; onboarding that leads to a profitable network-effect economy. | Questions tagged [SEC] [CI] [USE] [NET]; Q11–Q17 written to Studio with the same codes. |
| D-055 | 2026-11-04 | Personal life items live in a **private area nobody else can read** (Q11 A). | Studio private store before life boards. |
| D-056 | 2026-11-04 | **Clanstack Studio is the whole platform; ActionMap is the interface style** and what it lets users/communities do. | Layers re-proposed (Studio Q18). |
| D-057 | 2026-11-04 | **Public web app before any outside pilot** (Q13 C). | Rust hub → public app → pilots. |
| D-058 | 2026-11-04 | Utility: **all areas, layered auditable roadmaps**; order income floor, people, daily rhythm, job search, NXK. | Boards in that order. |
| D-059 | 2026-11-04 | Cohorts (non-linear): own teams; job seekers; swinger/escorting communities, organisers, clients; organisers/seekers + event supply chain; family referrals; freelancers. | Adult/escorting gated on Studio Q19 (law, safety). |
| D-060 | 2026-11-04 | Economy: **pooled capacity; paid access/shareability of communities, events, initiatives; cuts from services sold between people/bodies**. | Money model pending Studio Q20. |
| D-061 | 2026-11-04 | **Releases gated by all scenarios passing**, versioned, changelog, rollback (Q17 A). | From Studio v0.2. |
| D-062 | 2026-11-04 | Scenario order (Claude's call): hostile/spam, bystanders/consent, leaving with data, crisis/burnout, community vote, plain language. | Next scenario batch. |
| D-063 | 2026-11-04 | **Clanstack never paywalls**; it takes a cut from those that do. Nowed's paid offerings use separate trading names. Studio's own account gives money/multi-capital, charging only for extra compute. | Supersedes "paid access" in D-060. |
| D-064 | 2026-11-04 | Automations, agents, adapters and implementation services are **sold by accounts and groups** (L5). | Marketplace categories. |
| D-065 | 2026-11-04 | **Layers accepted**: L1 Clanstack, L2 Studio, L3 ActionMap, L4 canvases/templates, L5 agents/adapters, L6 pool, L7 engine. | Glossary. |
| D-066 | 2026-11-04 | Adult cohorts: Nowed's intent is a full marketplace with cuts once a better-purpose case and backing exist. | **Blocked**: escort bookings/cuts not built (UK law); safety tools with sex-worker-led partners + adult-community organising tools possible after encryption and legal opinion. |
| D-067 | 2026-11-04 | Payments via a **regulated marketplace provider** now; may hold funds later with case and backing. | Swappable money layer. |
| D-068 | 2026-11-04 | (Private, in Studio's private area) income-floor rules. | Income board. |
| D-069 | 2026-11-04 | **Builder interviews → content → multi-capital**; Studio suggests who to contact next. | Interview pipeline (Studio Q24). |
| D-070 | 2026-11-04 | **Cut shown only to the selling side**; buyers see one all-in price. | Fee deducted from seller proceeds. |
| D-071 | 2026-11-04 | (Proposed) **Exchange Kit**: modular booking + money handling across person/group topologies, gated per jurisdiction pack. | Studio A-exchange-kit; first config pending Q31. |
| D-072 | 2026-11-04 | Interests register covers **ventures Clanstack features or promotes** (Q28 B). | Charter clause. |
| D-073 | 2026-11-04 | Community-builder default list kept **for now** (Q29 A). | Interview pipeline. |
| D-074 | 2026-11-04 | **Referencing system adopted**: space/item@version#line; R-YYMMDD-n on every Claude reply (Q30 A). | Replies stored in Studio. |
| D-075 | 2026-11-04 | First Exchange Kit configuration: **event supply chain** (Claude's call, Q31). | Studio A-exchange-event-chain; open Q32 crew engagement, Q33 simulated event type. |
| D-076 | 2026-11-04 | **Suppliers/agencies engage crew; Clanstack is their tool** (Q32 A); other models much later. | exchange-core enforces supplier right-to-work checks. |
| D-077 | 2026-11-04 | Simulated event: **a catered builder meetup** (Claude's call, Q33). | engine/crates/exchange-core (11 scenarios). Open: Q34 cut, Q35 deposit, Q36 provider. |
| D-078 | 2026-11-05 | **Tiered cut** 3% community / 5% small / 8% above threshold; algorithmic later (Q34 C). | CutPolicy::Tiered; threshold Q39. |
| D-079 | 2026-11-05 | **Suppliers set deposit + late window within limits** (0–50%, 0–30 days) (Q35 C). | set_supplier_terms. |
| D-080 | 2026-11-05 | Providers compared with **no fixed costs until Clanstack earns**; proposal Stripe Connect (Stripe-handled pricing). | Pending Q38. |
| D-081 | 2026-11-05 | **Default treasury 60/30/10** (growth/owner/tax) for every account, constant across stages, configurable. | Allocation with tax top-up. Open: Q37 giving, Q39 threshold, Q40 pre-revenue costs. |
| D-082 | 2026-11-05 | **Giving = a tenth of the growth bucket** (6% of net) for community seed grants and compute (Q37 A). | Allocation.giving_of_growth_bps. |
| D-083 | 2026-11-05 | **Stripe Connect, Stripe-handled pricing**, first provider (Q38 A). | Integration after the hub; no platform fees on that option. |
| D-084 | 2026-11-05 | **8% tier after £50,000 settled in the trailing 12 months** (Q39 A). | default_cut_policy(); sales_12m. |
| D-085 | 2026-11-05 | **No pre-revenue costs at all** (Q40 A). | Free hosting/subdomains; sole-trader HMRC registration (free) only when trading starts; company + domain deferred to first revenue. |
| D-086 | 2026-11-05 | **Build order B > A > D > C** (Q41): addresses + money settings, then the Rust hub, then builder interviews, then Stripe test mode. | B shipped as Studio v0.3. |
| D-087 | 2026-11-05 | **Main moves only after green CI**: Claude pushes to a branch, waits for CI, then fast-forwards main. GitHub can't enforce this on a private free repo (rulesets need Pro or a public repo). | Enforcement choice: Q43. |
| D-088 | 2026-11-05 | **Money rules are versioned Studio settings** (SET-*), editors only, undoable; the Money calculator uses exchange-core's integer maths. Engine defaults stay the source until the hub syncs settings. | Studio v0.3, scenarios s20–s21. |

## State log (append-only)

- **2026-11-01 — v0.1.0 (phase 1 rails).** Spine, Windows capture (written, not yet run on a real
  Windows machine), simulator, reference next-step agent, dry/Windows executor, live + as-of map UI with
  controls. Verified in a Linux sandbox: core tests pass; simulated sessions → map; act-mode delegation
  auto-approved and executed (dry); suggest-mode waited for human approval; hand-offs shown on map;
  history slider; hash chain verified.
  **Unverified:** `clients/capture_windows.py` and `--backend windows` on real Windows.

- **2026-11-02 — v0.2.0 (voice + multi-hub + outside AIs, minimal slice).** Added: per-origin chains and
  two-way sync; privacy filter with first-seen questions; versioned habits profile (profiler agent);
  per-task model router (Groq, Gemini, Ollama, Anthropic, OpenAI, offline echo) with logged routing;
  conversation agent (voice/text commands + chat with map context, "this" = map focus); voice client
  (push-to-talk / wake word / always-on presets per machine and app, local faster-whisper, SAPI speech
  with barge-in, text mode); MCP connector with one secret per AI; context pack + paste-back import;
  UI panels for talk, privacy, listening, profile and outside AIs.
  Verified in a Linux sandbox: core tests (9 groups); two hubs synced both ways and verified; private
  app leaves one placeholder, unreviewed masked; 12 spoken-style commands handled; router fell back
  to offline with every skip logged; MCP client listed tools, proposed, spoke, wrong secret refused;
  ChatGPT-style import logged as ext:chatgpt; UI renders with no errors.
  **Unverified (needs real hardware/keys):** microphone, speech-to-text, wake word and SAPI speech;
  Windows capture and the real executor; Groq/Gemini/Ollama calls; Tailscale Funnel with
  Claude/ChatGPT connectors. A v0.1 database isn't compatible; start fresh (data/ is per machine).

- **2026-11-02 — foundation v0.3.0 (Rust core).** New sibling workspace `foundation/`: signed fact ledger,
  branching intent tree with fork points, horizons and lanes, key identities with sub-identities, devices,
  capability grants and revocation, views at any point, merge preview/commit with per-type rules, any-order
  sync. 7 story tests pass (S0–S4, tamper/gap). Compiled to WASM; "Version Tree Lab" page runs it in the
  browser with two simulated devices (published as a private artifact). GLOSSARY.md and STORIES.md added.
  ActionMap v0.2 (Python) stays the working app until the Rust hub replaces it.

- **2026-11-03 — reconciliation.** Same answers to Q25–31 arrived again in a new session; already
  recorded as D-027…D-033 and built as foundation v0.3.0 (tests re-run: 7 pass). Proposed glossary
  additions and stories S9–S17 appended to foundation/GLOSSARY.md and STORIES.md; open questions Q32–Q39.

- **2026-11-04 — Clanstack Studio v0 (artifact).** https://claude.ai/artifact/4hTHTKeonKNHhjRY2iChni (private).
  First in-system workspace (D-044): map of all items, Ask (short-code answers), Capture (text, links,
  sketch), Tree (append-only events, branches, fork/merge, as-of), Pack (context pack for any AI).
  Data: `seed/genesis` (152 items: D-001–D-052, 56 terms, S0–S27, 6 assets, 9 questions) + `events`
  collection (append-only: answer, comment, status, item.create/edit, link, branch.create/merge).
  Any Claude session reads answers with the Artifact database tool on that URL. Source: studio/index.html.

- **2026-11-04 — Studio v0.1.** Read Nowed's first entries (a reason-less challenge he couldn't undo); reverted
  it as asked. Built tests/scenarios.py: 18 simulated people/situations against the real page with a shared
  in-memory store. Baseline v0: 1/15 passed. v0.1: 18/18. Fixes: undo + revert, reason before challenge,
  stable codes, read-only past, branch bar, view-only bar, names, newest-1,000 window, AI replies keyed by
  source with NEW lines, List view, device drafts, editor-only agree/merge, focused badge + agree-all,
  disagreement flag, monotonic timestamps. Findings F-01–F-15, D-053 and Q-scenarios (Q10) written to Studio.
  Open: checkpoints (F-07), store-level charter enforcement (F-11/F-16 → Core), causal clock (F-14), voice (F-15).

- **2026-11-04 — Studio v0.2.** Private area (per-person store, 🔒, out of the AI pack by default), Lead type,
  scenario s19; 19/19 passed before release (D-061). Income board + 6 leads + readiness check written to
  Nowed's private area; D-063…D-070, terms T57–T64, stories S32–S34, questions Q23–Q26 in Studio.

- **2026-11-04 — repo + reply archive.** Local git repo /home/claude/repo (commit c15fec6: actionmap/, engine/, studio/,
  CI workflow). Push to github.com/Morami49/clanstack-studio blocked until GitHub is linked to Claude.
  Claude replies now carry R-YYMMDD-n codes and are stored in Studio (first: R-261104-6). Open: Q27–Q31.

- **2026-11-05 — GitHub live.** Repo github.com/Morami49/clanstack-studio receives the local history (actionmap/, engine/,
  studio/, CI). exchange-core v0.3: trailing-12-month tiers, £50k default, giving share; 15 scenarios.

- **2026-11-05 — Studio v0.3 (Q41 B).** Go-to addresses (studio/ID@n, chat/R-…#line, repo/sha:path#L), copy address,
  numbered-line highlight, 10 SET-* money settings with a Money calculator; 21/21 scenarios; main 51225e7 after green CI.
  Next: Rust hub (Q42 hosting), then D, then C.

## File map
- `schema/event.schema.json` — the contract.
- `spine/store.py` append-only hashed log · `spine/control.py` event-sourced control state + policy ·
  `spine/steps.py` event→step key · `spine/mapper.py` process map + exports · `spine/server.py` API/WS.
- `clients/` capture_windows, simulate, executor, common (client SDK).
- `agents/next_step.py` reference agent · `agents/conversation.py` voice/text commands + chat ·
  `agents/profiler.py` habits profile.
- `brain/router.py` per-task model routing. `spine/privacy.py` private list. `spine/context.py` context pack/import.
- `spine/mcp_server.py` connector for outside AIs. `clients/sync.py` hub sync. `clients/voice.py` mic/speaker.
- `ui/index.html` map + controls. `tests/test_core.py`.

## Next phases (proposed, not yet decided — superseded items struck by later decisions)
1. **Field test on Windows** (dry executor) → fix capture edge cases (elevated apps, UAC, multi-monitor).
2. **Voice layer** as just another client: STT → `utterance` events with `intent`; intents call the same
   control endpoints (pause, hand off, approve); TTS reads proposals aloud; approve by voice.
   Free stack candidates: Pipecat or LiveKit Agents, Silero VAD, faster-whisper / whisper.cpp,
   Kokoro / Piper, local LLM via Ollama or a free API tier. Each registers `stt` / `tts` / `llm.*`.
3. **LLM agent** replacing the frequency heuristic, trained/evaluated on exported sessions (D-001 "D").
4. **Virtual screens** (VMs / Xvfb / Windows Sandbox) as surfaces for agent↔agent work.
5. Optional port of the spine to Rust/Axum + Postgres (owner's preferred platform stack).

## Open questions for the owner
Open questions now live in Clanstack Studio → Ask (Q1–Q9 plus proposed terms T1… and stories P1…).
Read `events` there for answers; new decisions continue at D-053.
