# Glossary (v1, 2026-11-02)

Shared vocabulary for Nowed, every AI tool, and the code. Change a term by adding a new dated
line under it; never rewrite one silently. "Foundation" is a working name until one is chosen (Q-31).

## The two layers
| Term | Meaning | In code |
|---|---|---|
| **Fact** | Something that happened: a click, a screen change, speech, a grant, a revocation. Never edited, never branched. | `Layer::Fact` |
| **Intent** | Something someone decided, set, planned, proposed or noted. Branchable and mergeable. | `Layer::Intent` |
| **Ledger** | All facts. Each author keeps its own hash chain; a store accepts a fact only as the next link. | `Store` (facts) |
| **Realm** | *Real* facts happened once, for everyone. *Rehearsal* facts were simulated on one branch and are only visible there. | `Realm` |

## The tree
| Term | Meaning | In code |
|---|---|---|
| **Tree** | All intents and the branches they sit on, drawn as a graph. | `tree()` |
| **Branch** | A line of intents. Starts from a **fork point** (any intent) on its parent. `main` is the root branch. | `branch.create` |
| **Head** | The latest intent(s) of a branch. Two heads = two lanes wrote at once; normal, not an error. | `heads()` |
| **Horizon** | The moment a branch's view of reality is pinned to. Real facts after it are hidden on that branch, except those recorded in its own lanes. None = live. | `Branch.horizon` |
| **Lane** | A live working session running on a branch. Several lanes can run in parallel on one or many branches. | `lane.open` / `lane.close` |
| **View** | The state of a branch, or of any single point, rebuilt from its intents plus the facts visible to it. | `view()`, `view_at()` |
| **Resume** | Start a new branch at a past point, with its own lane, and carry on from there. | Story S1 |
| **Merge** | Bring one branch's intents into another. Recorded as an intent, with every answer you gave. | `branch.merge` |
| **Key type** | The first segment of a setting's key (`mode/…`, `handoff/…`, `privacy/…`, `note/…`). It decides the merge rule. | `key_type()` |
| **Merge rule** | Per key type: *auto* (merges by itself, latest wins) or *ask* (you settle it). Stored as a setting, `policy/merge/<type>`, so it is versioned per branch. | `default_policy()` |
| **Conflict** | Both sides changed the same *ask* setting differently since they split. | `Conflict` |

## Who
| Term | Meaning | In code |
|---|---|---|
| **Identity** | A person or organisation: a signing key with a genesis fact. Needs no blockchain. | `identity.genesis` |
| **Sub-identity** | A key acting for an identity with limited powers (e.g. `ext:chatgpt`, a venture, a role). | `Role::SubIdentity` |
| **Device** | A machine or browser with its own key (laptop, Oracle VM, phone). | `Role::Device` |
| **Grant** | A fact by which a key gives another key some capabilities. You can't grant what you don't hold. | `grant` |
| **Capability** | `fact.write`, `intent.write`, `branch`, `merge`, `grant`, or `*`. | `cap_covers()` |
| **Revoke** | A fact ending a grant from that moment on. | `revoke` |
| **Flow** | Who must approve what, for which devices and sub-identities. Kept as intents (`flow/…`), so it can be branched and merged. | planned |
| **Actor** | Anyone or anything that produces events: human, agent, outside AI, screen, system. | ActionMap |
| **Mode** | observe / suggest / act, per actor and per handed-off step. | ActionMap |

## Where
| Term | Meaning |
|---|---|
| **Node** | Any running instance: a laptop app, a VM service, a browser tab. |
| **Hub** | A node that stores and serves the log for others. |
| **Origin** | The node or key that first wrote an event. |
| **Surface** | A screen or virtual screen where actions happen. |
| **Sync** | Swap missing events in any order; every one is re-checked on arrival. |
| **Anchor** | Publishing one fingerprint of the log somewhere public, with no data. Optional, later. |
| **Shared ledger** | The ledger replicated across several identities' hubs, signed by each, with no fees (D-029). |

## ActionMap terms (the first app on the foundation)
Step, Map, Hand-off, Proposal, Decision, Kill switch, Private list, Share level (local / shareable / public),
Context pack. See ActionMap's README.

## Proposed additions and redefinitions (2026-11-03, awaiting Nowed's codes Q32–Q39)
| Term | Proposed meaning | Why |
|---|---|---|
| **Scope** | Who a fact or intent is visible to and synced with: me, a device set, a group, public. Each scope has its own encryption key, handed out by grants. | A shared ledger (D-029) must not leak private facts. Q35. |
| **Charter** | The rules about changing rules: who may change grants, merge rules, scopes, membership, and with what approval (one owner, or a group threshold). Kept as `charter/…` intents. | Merge rules and flows are themselves changeable; something must govern those changes. Q34. |
| **Group / Community** | An identity whose members act together under a charter. | D-032 named groups; not yet defined. |
| **Flow** (redefined) | An approval route: which identities must approve which action, in what order. A charter is made of flows. | Was "planned" with no shape. |
| **Recovery** | How an identity gets back control after losing keys (other devices, trusted people, backup phrase). | Wallet-style keys (D-032) make key loss = lockout. Q32. |
| **Lane** (clarified) | Every ActionMap recording or conversation *session* runs in a lane. "Session" stays only as ActionMap's label for a recording run. | ActionMap "session" and Foundation "lane" overlapped. |
| **Author chain** (replaces Origin) | One key's own hash chain of facts. ActionMap's "origin" (a hub) becomes this when the Rust hub lands. | Two names for one idea. |
| **Peer** (replaces Node) | Any running copy of the core. A peer holds one or more device keys. | "Node" and "Device" were blurred. |
| **Adapter** | Native code at the edges a browser can't do: desktop capture, acting on screen, mic/speaker. | Rust/WASM can't reach these (D-026). |
| **Mode** (redefined) | Shorthand for a grant on steps: observe / suggest / act = which step capabilities an actor holds, in which scope, until when. | One permission model instead of two. Q38. |
| **Bystander** | A person who appears in recorded facts but isn't a user (a client's staff, someone on a call). Has consent rights, holds no keys. | Missing stakeholder; needed before B and D. |
| **Conformance suite** | Language-neutral test cases (events in, expected views out) that the Python v0.2 and the Rust port must both pass. | Rewrite safety (D-030). |
| **Chain link** | A signed statement tying an identity key to a blockchain wallet. Lets identities work with chains without depending on any one. | 27C/30C. Q36. |

## Proposed (2026-11-03, round 2; from D-038–D-042, awaiting Q41–Q46)
| Term | Proposed meaning |
|---|---|
| **Clanstack** | The whole ecosystem you reach from any device (D-038). Placeholder; naming/IP pass later. |
| **Core** | Clanstack's technical base (was "foundation"). Placeholder name. |
| **App** | Something built on the core. ActionMap is the first. |
| **Pool** | All compute, storage and network your authorised peers and providers offer, used as one. |
| **Provider** | An outside platform that adds capacity (Oracle, Groq, Gemini, GitHub…), on its own free or paid tier. |
| **Placement rule** | Where a piece of data or work may run, set by its scope (e.g. private → own devices only). |
| **Cascade** | The order that decides which setting wins when device, account, sub-account and group settings disagree. |
| **Lock** | A charter mark that stops a lower level overriding a setting. |
| **Template** | A reusable bundle of charter, flows, scopes, maps and layout. Re-templating = branching it, previewing, then merging. |
| **Continuity** | Carrying on the same work on another device (the Apple sense of "Handoff"). |
| **Delegation** | Proposed new name for ActionMap's "hand-off" (giving a step to an agent), to avoid clashing with continuity. |
| **Assurance level** | How much proof an action needs: silent, quarantine, witness, two-device confirm. |
| **Trust signal** | What sets the assurance level: known device, usual network, sensitivity of the action, anything unusual. |
| **Escalation** | Raising the assurance level for one action; always logged with its reason. |
| **Replication minimum** | The fewest peers that must hold a piece of data, so no single device or provider can lose it. |
