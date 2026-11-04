# Clanstack Studio

The platform for building and running Clanstack (D-056, D-065).

| Folder | Layer | What it is |
|---|---|---|
| `studio/` | L2 Clanstack Studio | The live workspace (published as a private claude.ai artifact) + `tests/scenarios.py` |
| `actionmap/` | L3 ActionMap | Desktop capture, maps as controls, voice, agents (Python v0.2, reference implementation) |
| `engine/` | L7 Engine | Rust core: signed fact ledger, version tree, identities, grants, sync; compiles to WASM |

Decision and state log: `actionmap/HANDOFF.md` (D-001…). Every push runs the engine tests, ActionMap's core tests and Studio's scenarios (D-061).
