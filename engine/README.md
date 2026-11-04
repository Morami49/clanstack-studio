# Foundation (working name) v0.3.0

The Rust substrate under ActionMap and whatever it builds next (D-030, D-031, D-033):
a signed **fact ledger** that never branches, a **branching intent tree** you can resume
from any point in parallel lanes, **key-based identities** with sub-identities and devices,
and **merges** with per-type rules you control. Pure Rust with no I/O, clock or randomness,
so the same core runs natively and in any browser as WebAssembly.

```
crates/foundation-core   the core (event, identity, store, view/merge)
crates/foundation-wasm   browser binding (JSON in/out)
web/                     Version Tree Lab: the core running in a page
GLOSSARY.md  STORIES.md  shared vocabulary and the promises the tests keep
../actionmap/HANDOFF.md  the one decision + state log for both projects
```

## Run

```
cargo test -p foundation-core                     # stories S0–S4 as tests
cargo build -p foundation-wasm --target wasm32-unknown-unknown --release
wasm-bindgen --target web --out-dir web/pkg target/wasm32-unknown-unknown/release/foundation_wasm.wasm
python web/build.py                               # -> web/index.html, one file, opens from disk
```
wasm-bindgen CLI must match the crate (pinned to 0.2.100): `cargo install wasm-bindgen-cli --version 0.2.100`.

## Rules the code enforces
- Every event is content-addressed (blake3) and signed (ed25519); a change to any byte is refused.
- Facts: per-author chains with no gaps; real facts are never branched; rehearsal facts only show on their branch.
- Intents: a DAG ordered by a causal clock; every branch, lane, merge and answer is itself an intent.
- Authority: every event's key must hold the capability at that time, through a chain of grants to an identity.
- Sync: stores swap events in any order; anything early waits for its parents or its grant.

## Known limits (v0.3.0)
- A revocation applies from its own timestamp. A node that received a revoked key's later events before
  the revocation keeps them. Planned fix: revocations also list the last accepted event.
- Keys live in memory in the Lab page. Next: a device keystore (OS keychain natively, non-exportable WebCrypto in browsers).
- No persistence or network transport yet. Next: SQLite (native) / IndexedDB-OPFS (browser) and iroh for device-to-device sync.

## Build plan (D-030: full rewrite now, then test)
1. **Core** ✓ (this release).
2. **Hub** in Axum on the core: persistence, the ActionMap HTTP/WS API kept compatible so the Python edges keep working during the port.
3. **Sync over iroh** (device-to-device, NAT traversal) + hub-to-hub; browser nodes sync via the hub's WebSocket.
4. **Leptos UI**: the ActionMap map and this tree in one app, compiled to WASM.
5. **Native edges** in Rust: Windows capture (UI Automation), executor, voice I/O (whisper.cpp bindings).
6. **Then the Windows field test** (D-024 order resumes: voice upgrade, smarter agent; multi-person later).
