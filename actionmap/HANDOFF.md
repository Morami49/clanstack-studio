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
| D-089 | 2026-11-05 | **Hub on a free ladder** (Q42 C): H1 Cloudflare Workers + Durable Objects (always-on, no card) → H2 PC node (offline, syncs) → H3 Oracle Always Free (2 OCPU/12 GB Arm since 15 Jun 2026; free-only, card check) → H4 friends' own nodes → H5 GitHub Actions. Links: Cloudflare Tunnel; Tailscale Personal dev-only (non-commercial). | Open: Q44 source of truth, Q45 friend nodes, Q46 Oracle timing. |
| D-090 | 2026-11-05 | **Main guarded by free layers** (Q43 A): rule, pre-push hook, main-guard workflow, gitleaks, Dependabot. | 6be13ae; optional GitLab mirror Q47. |
| D-091 | 2026-11-05 | **No free provider is load-bearing**: every node keeps the full chain (F-17: Oracle halved free Arm without notice). Friends' logins are never pooled (F-18); friends run their own nodes. | Claude's call. Q48 decision→commit links. |
| D-092 | 2026-11-05 | **Friends run their own nodes** (Q45 A): own accounts and keys; shared + encrypted private data; leave any time. | F-18. |
| D-093 | 2026-11-05 | **Decisions link to their code** (Q48 A): after every build Claude comments `repo/<sha>:<path>` on what it carried out. | FLOW-delivery agreed. |
| D-094 | 2026-11-05 | **The engine is the only source of rules**: Studio's JS copies (fold, money maths) get conformance tests now and are replaced by engine-wasm later. | Claude's call; S45. |
| D-095 | 2026-11-05 | **Original: Studio page now, then every node (A → C)**. Nowed: B and C feel the same online; the engine already syncs in any order, so B is skipped. | Agreed 2026-11-06 (Q44 A). |
| D-096 | 2026-11-05 | **GitLab mirror** (Q47 A): `mirror` workflow pushes each green main to a protected GitLab project, never force. Needs GITLAB_TOKEN secret + GITLAB_REPO variable (Nowed). | 4b923cd; Q54 username. |
| D-097 | 2026-11-05 | **In-house first**: contributions, CI/CD and distribution happen inside Clanstack Studio; outside services are adapters swapped rung by rung (read → write → run → optional). | Purpose from Nowed; F-22 sandbox objection, Q55. |
| D-098 | 2026-11-06 | **The claude.ai page is Studio Web** (Q49 A); Clanstack Studio is the platform. | T68 renamed. |
| D-099 | 2026-11-06 | **Key register in both places, names only** (Q52 C): Studio Web private area (KEY-register) + password manager for values. | |
| D-100 | 2026-11-06 | **Studio's sandbox runner first; GitHub Actions as backup + overflow** (Q55 B + A). No outside contributions until the sandbox runner passes security tests (F-22). | |
| D-101 | 2026-11-06 | **Two-way merge, no echoes, same order everywhere** (Q44 "C now", prompt edit 2): hub `studio.write` facts → Studio Web as `hub-<id>`; import skips them; all order by (ts, doc id). | df5127a; D-095 revised from A→C to C now. |
| D-102 | 2026-11-06 | **Prompt edits are branches**: answers/replies record their edit; latest edit wins for intents; earlier edits' work stays as facts and is reconciled (kept/revised/reverted). | Proposed, Q59. F-25. |
| D-103 | 2026-11-06 | **Hub re-checks Studio Web**; refusals return to Studio Web as visible notes. | Claude's call; build with export (Q56). |
| D-104 | 2026-11-06 | **Hub becomes a claude.ai connector** (Q56 B), signing in with OAuth built into the hub (Q62 A). | After the hub is live. |
| D-105 | 2026-11-06 | **Graded visibility** (Q58 B + nuance, Q61 A): 0 only me · 1 named people · 2 group/space · 3 link holders · 4 public listed; each can be partial. | Token holders only until built. |
| D-106 | 2026-11-06 | **Walkthroughs stand on their own**: links, exact buttons, checks, reply codes; never "see earlier". | F-26. |
| D-107 | 2026-11-06 | **Steps count as skipped until Nowed confirms** with a step code (W1.3); open steps are re-listed in full each reply. | SETUP-W1..W4. |
| D-108 | 2026-11-06 | **Claude detects prompt edits itself** via the state stamp ending each reply (reply · last Studio event · main). | T82. |
| D-109 | 2026-11-06 | **Real event times** in `recorded_at`; `ts` may be bumped for order. | F-27. |
| D-110 | 2026-11-07 | **Each venture's resources live in its own container** (Q66 C): GitHub org, GitLab group, Cloudflare account, Bitwarden collection. | Order Q70 A. |
| D-111 | 2026-11-07 | **No single person is load-bearing (stewardship)**: access moves to management/employee/partner profiles; founder cap on Nowed's *external* profile only. | Amended for prompt edit 2. |
| D-112 | 2026-11-07 | **Approvals count people, not profiles** (Q72 A; CASE-01 Barings). | P-10. |
| D-113 | 2026-11-07 | **Recovery**: personal email until Clanstack's domain; paper break-glass now, trusted contacts later. | Sheet done. |
| D-114 | 2026-11-07 | **Legal entity at first revenue or first partner** (Q69 A); containers GitLab → Cloudflare → GitHub (Q70 A). | Not legal advice. |
| D-115 | 2026-11-07 | **Index hierarchy L0–L6 adopted**; hierarchies and lenses themselves branch and merge (Q73 A). | VISION-0, P-01..P-10. |
| D-116 | 2026-11-07 | **Mirror uses a project deploy key** (Q67 B, CASE-02); GitLab host key pinned. | 64dcd51; W4.3+ pending. |
| D-117 | 2026-11-07 | **Chat index**: `scripts/chat_index.py` gives every prompt M-YYMMDD-n-eK with live/superseded, interruptions, reply code, mentions, sha256; texts private. Run each turn. | ca29a3b. |
| D-118 | 2026-11-07 | **Merge policy**: index all past chats now (CHAT-*), merge content chat by chat as sourced proposals; conflicts become questions; unrelated personal/third-party content never copied. | Q79–Q81. |
| D-119 | 2026-11-08 | **Nothing is off-limits inside compartments**: per-compartment keys, owner-approved bridges; sensitive material under Nowed's profiles. | F-40 GDPR controller, F-41 concentration. |
| D-120 | 2026-11-08 | **Studio embeds inside other AI tools**: funnel new users + capability capture (module, or docs when compute is short). | FLOW-capture. |
| D-121 | 2026-11-08 | **Next build: hub connector (OAuth), then builder interviews** (Q77 A). | Q86–Q87. |
| D-122 | 2026-11-08 | **Productise the Studio method** for competitive advantage once the Purpose tree exists (Q78 A). | |
| D-123 | 2026-11-08 | **Merge past chats one by one**, Master Reference v2.0 first (Q79–Q80 A); Kenzee profile later (Q81); exports/feeds later (Q82 B). | |
| D-124 | 2026-11-08 | **Profile model** (Q83 A+): per-compartment keys; every user gets a control profile (manages all profiles, contents, bridges) and a public-safe profile (full control, nothing sensitive shown); each profile has its own Studio surface (ActionMap). | Q88 duress option. |
| D-125 | 2026-11-08 | **Neutral infrastructure, not deniability** (Q84 A): content-neutral tools, OSA risk assessment before first outside user, valid-request process, transparency log, unreadable compartments. | CASE-06, CASE-07. |
| D-126 | 2026-11-08 | **Embed order**: Claude connector → cross-tool browser extension → the rest (Q85). | |
| D-127 | 2026-11-08 | **Duress code opens a decoy and locks compartments** (Q86 A); no wipe. | CASE-08. |
| D-128 | 2026-11-08 | **Claude connector all in Rust, GitHub sign-in** (Q87 B, Q88 A): hub is OAuth 2.1 + MCP server; owner-only allowlist. | aabfc71; F-44 risk; W5 done, W6 next. |
| D-129 | 2026-11-08 | **Next: Studio Web syncs with the hub through the connector** (Q89 A): one-time import, then both ways. | Closes F-45. |
| D-130 | 2026-11-08 | **Request log: time, route, tool, outcome, ms, who, build; never contents** (Q90 A). Newest 5000 rows. | 7de9622; hub_log tool. |
| D-131 | 2026-11-08 | **Sealed capture later**: contents captured only sealed to the caller's key, with compartment keys (Q91 A+C). Off for now. | Needs D-119 keys. |
| D-132 | 2026-11-08 | **Retention is per purpose** (Q93 "depends on auditing and analytics needs"): each log or record kind names the audit or analytics need that sets how long it stays; no single number. | Request log keeps 5000 rows until a purpose sets otherwise. |
| D-133 | 2026-11-08 | **Every action has an approval policy** (Q94 A): auto, ask a person, or off; approvals count people (P-10); every run leaves an audit record. Only reversible actions may run on auto (P-12). First instance: Branch cleanup workflow (person starts it; preview by default). | Claude's own branch deletes are refused (HTTP 403, F-53); not worked around. |
| D-134 | 2026-11-08 | **Build order** (Q95 A then B): D-129 Studio Web ↔ hub sync, then safe repeat writes (F-48) and unknown-item warnings (F-47). | |
| D-135 | 2026-11-08 | **Automate the doing, never the knowing** (Q94 edit 2, P-13): every automated run leaves a record a person can read and replay — what ran, why, which policy allowed it, inputs, result, undo — so manual work shrinks while understanding and reproducibility grow. | Applies to D-133 policies and every Studio flow. |
| D-136 | 2026-11-08 | **Executors, not borrowed hands** (answers "how can 1.3 be prevented for all connections"): Claude's sessions keep their own safety refusals; destructive or outside actions run in the platform that owns them (GitHub Actions, the hub, Cloudflare) under a person-set policy, with scoped credentials and a run record. Claude proposes and prepares; executors act. | Branch cleanup is the first executor. |
| D-137 | 2026-11-08 | **Policies are configurable presets** (Q97, Q98 "combination, configurable"): retention windows and approval defaults are settings per purpose or action type, with A/B/C as named presets that can be mixed; every change is versioned. | First: POLICY_BRANCH_CLEANUP (ask/auto/off). |
| D-138 | 2026-11-08 | **Studio ↔ hub sync built** (D-129, Q99 A): Studio Web's Hub view copies shared changes into the hub with their original authors (importer key vouches) and brings hub writes back; repeat-safe. | import_studio_events tool; Studio v0.4. |
| D-139 | 2026-11-08 | **Studio is the source of truth for policies** (Q101 A): settings SET-policy-*; executors read them from the hub (scripts/policy.py), fall back to the platform copy when the hub can't answer, and flag drift. Branch cleanup first. | Q100 A: cleanup auto (30 branches deleted 23:33). |
| D-140 | 2026-11-08 | **Sync on open** (Q102 A): Studio reads from the hub when it opens; copying up runs itself only after SET-policy-hub-push-clean-runs (default 5) clean recorded runs. Owner only. Every sync leaves a run record on RUNS-hub-sync (P-13). | Studio v0.5. |
| D-141 | 2026-11-09 | **Drift becomes a Studio finding** (Q103 A): Studio wins, the run warns, and the executor writes DRIFT-<setting> to Studio through the hub, once per distinct drift (idempotency keys). | scripts/policy.py. |
| D-142 | 2026-11-09 | **Hub writes are repeat-safe and checked** (Q104 A): write_event takes an idempotency_key (F-48) and warns when the target item is unknown or a create duplicates an id (F-47). Survives restarts. | Next: Q105. |
| D-143 | 2026-11-09 | **Every run readable, in order** (Q105 A): 1) executors write run records into Studio (scripts/run_record.py → RUNS-<executor>); 2) deploys are an executor under SET-policy-hub-deploy (auto/ask/off, dispatch with a sha to roll back); 3) Studio's Runs view lists all runs with outcome, policy and undo. | Studio v0.6. |
| D-144 | 2026-11-09 | **Undo: shown and linked now; one-click later only for reversible executors, behind the same policy** (Q106 A). | P-12. |
| D-145 | 2026-11-09 | **Builder-interview pipeline built** (Q107 B, D-069, Q24): Studio v0.7 Builders view; builders are private (third parties); stages found → contacted → agreed → interviewed → drafted → published → followed up; publishing needs a recorded, revocable release (T-release); Next up favours later stages, idle time and kinds not yet interviewed; interview kit is the shared item KIT-builder-interview. | |
| D-146 | 2026-11-09 | **Raw material → pieces in many formats → cycles and tests** (Q109): per builder, raw material (recordings, transcript, notes, photos: links only, private) and pieces (written, quotes, audio, video, photos, collage) per channel and monthly cycle; a piece can be published only in formats the guest's release covers; results per published piece feed Content tests by format, channel and cycle. Kit used as written (Q108 A). | Studio v0.8. |
| D-147 | 2026-11-09 | **Measures and dashboards are the user's design** (Q110 A+B): measures are a shared setting (default: each channel's own measure + replies); each person saves their own view (measure, total/average/count, grouped by format, channel, cycle, kind of builder or builder) as a private item. General dashboards for any personal, business or relational case come next (Q112). | Studio v0.9. |
| D-148 | 2026-11-09 | **Raw files: Studio's file store, encrypted in the browser** (Q111 B, A as fallback): AES-256-GCM with a key from the compartment passphrase (PBKDF2-SHA-256, 310k); the passphrase is never stored; files over 15 MB or when uploads are unavailable go to the person's own storage as links; a link can also back up an upload. First step of compartment keys (D-119). | Lost passphrase = lost files (Q113). |
| D-149 | 2026-11-10 | **Split the AI load by role** (Nowed near his weekly Claude limit): builder (Claude: code and Studio), auditor (any other AI with actionmap/AUDITOR.md: checks facts, code, principles, regression ledger, questions), commander (deterministic GitHub Actions and scheduled tasks: no AI tokens unless a step needs judgement). The standing "any traced/untraced… enquiries" prompt moves to the auditor. | Q114–Q116. |
| D-150 | 2026-11-10 | **Dashboards: one builder plus fixed area dashboards, all customisable inside Studio** (Q112 A+B). | Not yet built. |
| D-151 | 2026-11-10 | **Recovery key offered only in particular flows and security set-ups** (Q113 A, scoped): not pushed on every user; offered when a compartment holds files or a security initiative starts. | Not yet built. |
| D-152 | 2026-11-10 | **Studio develops Studio: config live, code by request** (from the Figma live-editing discussion): look (SET-ui-theme) and item types (SCHEMA-types) are edited in Studio's Studio tab and applied at runtime from the record, versioned; nothing edits history. | Studio v1.0. |
| D-153 | 2026-11-10 | **Change requests → change intake → builder** : type `change` items with a test; when the owner approves, the change-intake executor (every 6 h or by hand, policy SET-policy-change-intake) opens a GitHub issue and moves it to building; the builder ships through CI and deploy. | scripts/change_intake.py. |
| D-154 | 2026-11-10 | **Clusters for token efficiency**: actionmap/CLUSTERS.md is the 2-page map every agent reads first; updated in the same commit as the change. | |
| D-155 | 2026-11-10 | **Re-centre on ActionMap** (F-67): CLUSTERS.md C0 is read before interface work. | |
| D-156 | 2026-11-10 | **Change requests split by size** (Q117 C): small → cheap agent, medium/large → Claude, auditor reviews. | |
| D-157 | 2026-11-10 | **Both tracks** (Q119 C): Studio Web gets the command map now (v1.1: voice or text → nodes; suggest/act/observe; irreversible always asks; private log; replay via time slider); the local Rust ActionMap app resumes in parallel for desktop capture, wake word and always-on voice. | |
| D-158 | 2026-11-10 | **Self-hosted free models first** (Q120): premium agents and chatbots later; now free open models run on Nowed's own hardware (local runtime + an open coding model sized to it) for the cheap-agent and auditor roles. | Hardware: Q121. |
| D-159 | 2026-11-10 | **Three names** (Q123): **Clanstack Studio** = the web app in any browser, standalone; **Clanstack Studio for Claude** = the claude.ai artifact built so far, now the Claude bridge/extension; **Clanstack Studio Driver** = the desktop app (Rust), first pieces the recorder and the Leptos map interface (Q123 A + C). One record (the hub) under all three. | |
| D-160 | 2026-11-10 | **Free compute stack, pulled not pushed** (Q121 B): Oracle Always Free Ampere VM (now 2 OCPU / 12 GB on free-only accounts, mid-2026 cut) as the always-on model node; laptop as a temporary buffer; own hardware later; other free tiers stacked behind (Cloudflare Workers AI, free API tiers) via a model router in the hub. Nodes pull jobs from the hub over outbound connections only; no model port is exposed. | W16 first. |

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
- **2026-11-05 — guards + hub plan.** guards.yml (main-guard, gitleaks: no leaks), Dependabot, pre-push hook; main 6be13ae.
  Hub ladder D-089; terms T65–T68 (node, blind replica, free ladder, guard layer); stories S40–S42; FLOW-delivery; Q44–Q48 open.
- **2026-11-05 — updates + F-19.** 11 Dependabot updates applied (actions v7, gitleaks v3, ed25519-dalek 3, wasm-bindgen 0.2.130, pip bumps);
  Studio refuses duplicate ids (F-19, s22; 22/22); main f8d255f; Studio page v6. Corrected term codes: T65 blind replica, T66 free ladder,
  T67 guard layer, T68 Studio page, T69 original (T-node pre-existed). Open: Q44 (re-asked), Q47 (re-asked), Q49–Q52. Oracle account exists.
- **2026-11-05 — mirror + in-house vision.** mirror.yml live (skips until GitLab set up). Oracle locked out (F-21) → deferred to after H1 (Q50 C).
  "9.5) C" read as Q52 C (confirm). New: T70 mirror, T71 pipeline, T72 sandbox runner; S46–S47; FLOW-release; Q53–Q55. Next build: hub (H1) locally.
- **2026-11-06 — hub H1 built.** engine/crates/hub-core (7 tests) + hub/ (Cloudflare Workers + SQLite Durable Object), tested locally
  (24 Studio events → 25 signed facts; dedupe; 401; restart). Reads gated (F-23); workflows-parse guard (F-24); hub-deploy waits for
  Cloudflare secrets (Q57). GitLab = Morami49/clanstack-studio. Open: Q56 export route, Q57 Cloudflare setup, Q58 hub reads.
- **2026-11-06 — prompt edit 2 reconciled.** Edit 1 (R-261106-1) built hub H1 and recorded Q44 = A; edit 2 changed Q44 to "C now".
  Kept edit 1's work; added two-way merge (hub-core 8/8, Studio Web 23/23, s23). Mirror + hub deploy still skip (no secrets).
  Open: Q56 (revised), Q57, Q58, Q59, Q60. Terms T76 prompt edit, T77 reconcile, T78 echo; S50–S51; FLOW-merge.
- **2026-11-07 — setup progress.** Nowed confirmed W1 (Bitwarden) and W2 (HUB_WRITE_TOKEN; Cloudflare secrets in): this push is the hub's first real deploy.
  W3 (two-step sign-in) open; W4 (GitLab mirror) at W4.3. Open: Q60, Q64, Q65.
- **2026-11-07 — stewardship, index, chat merge.** W1–W3 + break-glass done; W4.1–W4.2 done (GitLab group); W4.3+ = deploy key.
  Actions pinned to SHAs (F-34). Chat index built and run: this chat = 20 prompts, 13 messages, 5 edited, 7 superseded;
  10 past chats registered (CHAT-*). F-37 earlier generations differ (Axum/Postgres/Leptos, six-node schema, CVU, n8n on OCI).
  Open: Q76 (OSA), Q77 (next build), Q78 (productise method), Q79–Q81 (merge).
- **2026-11-08 — W4 done by Nowed; first mirror run.** GitLab path clanstack-devs/Clanstack-studio (Ultimate trial: rely on nothing trial-only).
  Profile model, neutral infrastructure, embed order recorded. Next: hub connector (Q86 implementation, Q87 sign-in).
- **2026-11-08 — connector live.** /mcp answers 401 + discovery; GitHub OAuth App made (W5); this push loads GH_OAUTH_* into the hub.
  Mirror complete (W4.8). Next: W6 add connector in Claude, then D-129 sync.
- **2026-11-08 — connector tested (W6–W8).** F-46 overflow fixed (a881602) + deploy smoke test; build shown on /health (F-52);
  request log + hub_log (7de9622); read_events says what it skipped (F-55, 3e7e99c). W8: Claude caches a connector's tool list
  until Disconnect/Connect (F-54) — test rule: reconnect after any new tool. F-56: compaction rewrites the transcript, so the chat
  index is now cumulative (--prior) and recovers the newest prompt from `last-prompt`. hub_log now lists itself; probes for
  methods the hub lacks (server/discover) log as "not offered"; ms counts I/O waits only (Workers freeze the clock).
- **2026-11-08 — W9 passed.** hub_log lists itself, probes read "not offered", Settings shows 4 tools. No hub rows between
  18:12 and 18:29, so Claude's 18:17 connection attempt (F-58) never reached /mcp; sign-in and discovery routes are now logged
  too. Branch cleanup workflow added (D-133).
- **2026-11-08 — Q94 edited (M-261108-11-e2).** Edit 1's work stands (f565a43, Studio q01–q23); edit 2 adds P-13/D-135.
  F-59: the chat index numbered that edit as a new message after carrying the prior index forward; fixed, test added.
  F-60: edit 1's reply quoted an M-Trends 2026 median dwell time that could not be re-verified; withdrawn.
- **2026-11-08 — W10 ran three previews, deleted nothing (F-61).** The workflow's default was preview and the run looked green.
  Now runs are named by mode, preview warns loudly, and POLICY_BRANCH_CLEANUP=auto lets it run itself after each push to main.
  F-62: Studio Web only subscribed to its newest 1,000 changes (≈810 used); it now reads older pages once. D-129 sync built (D-138).
- **2026-11-11 — Nodach Studio served by the hub (D-171 S1, Q21 A, Q22 A).** Clanstack is now Nodach (D-161, D-169).
  `/studio` on the hub serves the Studio page with a host shim (`studio/standalone.js`) in place of claude.ai's, behind GitHub
  sign-in and a signed session cookie (`hub-core/src/session.rs`, tests in `tests/session.rs` incl. RFC 4231 vectors).
  Shared writes go through `/studio/api/events` (importer key, same as Studio Web's sync); private items stay in the browser.
  Checked locally with `wrangler dev`: redirects, 401s, forged cookie refused, missing header refused, write + dedupe + read-back.

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
