# Stories (v1, 2026-11-02)

Each story is a promise the system keeps. Status: **tested** = an automated test proves it
(`crates/foundation-core/tests/stories.rs`) and the Version Tree Lab page shows it;
**planned** = agreed, not built. Add stories as S7, S8…; never renumber.

| # | Story | Status |
|---|---|---|
| S0 | **Keys and limits.** My identity grants my laptop, my VM and ChatGPT different powers. A device can't merge unless granted; ChatGPT can't record facts; nobody can grant more than they hold; a revoked key can't write. | tested |
| S1 | **Resume Tuesday.** I open the tree at Tuesday's point, start a branch there with its own lane, and see Tuesday's settings and Tuesday's facts, while main keeps going in another lane. | tested |
| S2 | **An outside AI edits from chat.** ChatGPT's changes land on its own branch. On the merge desk, settings both sides changed come back as questions; notes merge by themselves. ChatGPT can't merge into main itself. | tested |
| S2b | **Merge rules are mine to set.** I switch a type (e.g. `mode`) between "ask me" and "merges by itself", per branch, and that change is versioned too. | tested |
| S3 | **Offline device.** The VM keeps working while the laptop is offline. On reconnect they swap events in any order and end up identical; both still verify. | tested |
| S4 | **Rehearse before acting.** An agent runs a workflow as simulated facts on a rehearsal branch; main never sees them. | tested (facts); planned (virtual-screen runner) |
| S5 | **Any browser.** The core runs as WebAssembly in a page, with no server. | tested (Version Tree Lab); planned (offline storage + sync over the network) |
| S6 | **Prove it.** Export a session with a proof that it hasn't changed since a given time (optional public anchor). | planned |
| S7 | **Devices and flows on the map.** Under each identity I add devices and sub-identities, set their keys, capabilities and approval flows from the map, and revoke them there. | partly (grants/revoke in the Lab); flows planned |
| S8 | **Multi-person (D).** Several identities share a ledger; each signs their own facts; consent and speaker identity decide what's shared. | planned |

## Proposed (2026-11-03, awaiting confirmation)
| # | Story | Stakeholder | Status |
|---|---|---|---|
| S9 | **Lose a device, keep my identity.** My laptop is stolen. From my VM or phone I revoke its key; anything it signs after its last accepted event is refused everywhere; I recover with other devices or a backup phrase. | Owner | proposed (Q32, Q33) |
| S10 | **Rules about rules.** Changing a merge rule, a flow or a grant on main needs the approval the charter requires; for a group, a threshold of members. | Owner, groups | proposed (Q34) |
| S11 | **Scoped sharing.** A co-founder joins my NXK group. They sync and decrypt only the group's scope; my private scope never reaches their devices. | Collaborators | proposed (Q35) |
| S12 | **Leave cleanly.** A member leaves. Their grants end, new group facts are encrypted with a key they don't have, and what they already had stays theirs. | Groups | proposed |
| S13 | **Consented audit.** A client's staff are recorded only after each consents, in a scope the client owns; a bystander can ask what was recorded about them. | Clients, bystanders | proposed |
| S14 | **Build on it.** genjob, NXK or Clanstack use the same identities, ledger, tree and charters as a library, without ActionMap. | Builders | proposed |
| S15 | **Route work by capability.** A job needing speech-to-text, a model or a screen runs on whichever authorised peer has it, and the routing is logged. | Devices | proposed |
| S16 | **Agents stay inside their grant.** An agent can't act outside its scope, steps, time window or the private list, on any peer. | Agents | proposed (Q38) |
| S17 | **Safe port.** The same events give the same views in Python v0.2 and in Rust, checked by the conformance suite. | Builders, owner | proposed |

## Proposed (2026-11-03, round 2)
| # | Story | Stakeholder |
|---|---|---|
| S18 | **Stolen laptop.** Its later writes land in quarantine; nothing is silently deleted. | Owner |
| S19 | **AI loosens a charter rule.** The change needs two-device confirmation before it counts. | Owner, outside AIs |
| S20 | **A delegation expires.** "Act on Save Excel until Friday" stops on its own on Friday. | Agents |
| S21 | **Continuity.** I start on the laptop and carry on from the phone or any browser where I left off. | Owner, devices |
| S22 | **Add a provider.** I connect a new free tier or device; the pool gains its capacity with no other setup. | Owner, providers |
| S23 | **A provider vanishes.** A free VM is reclaimed; nothing is lost, because of the replication minimum. | Owner, providers |
| S24 | **Re-template safely.** I (or any user) change a template on a branch, preview it, merge or undo. | Owner, users, groups |
| S25 | **Cascade.** My phone's layout differs from my account's, which differs from my group's; the cascade and locks decide, visibly. | Owner, groups |
| S26 | **Quiet security.** A normal day needs no extra confirmations; an unusual action from a new network asks for two-device confirm, with the reason shown. | Owner |
| S27 | **Private stays home.** Private-scope data is only processed on my own devices, never on a provider. | Owner, bystanders |
