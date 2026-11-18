# Clanstack Studio

Licensed under the [GNU AGPL v3.0](LICENSE). "Nodach" and "Nodach Studio" are trademarks; see [TRADEMARKS.md](TRADEMARKS.md).

The platform for building and running Clanstack (D-056, D-065).

| Folder | Layer | What it is |
|---|---|---|
| `studio/` | L2 Clanstack Studio | The live workspace (published as a private claude.ai artifact) + `tests/scenarios.py` |
| `actionmap/` | L3 ActionMap | Desktop capture, maps as controls, voice, agents (Python v0.2, reference implementation) |
| `engine/` | L7 Engine | Rust core: signed fact ledger, version tree, identities, grants, sync; compiles to WASM |

Decision and state log: `actionmap/HANDOFF.md` (D-001…). Every push runs the engine tests, ActionMap's core tests and Studio's scenarios (D-061).

## Guards on main (free plan)
GitHub won't enforce branch rules on a private free repo, so main is protected in layers (D-087, D-090):
1. Working rule: every change goes to a branch; main fast-forwards only after `ci` is green.
2. `scripts/hooks/pre-push` refuses a push to main without a green branch run (`git config core.hooksPath scripts/hooks`).
3. `guards` workflow: `main-guard` fails and opens an issue if main ever moves to an untested commit; `secrets` scans history with gitleaks on every push and weekly.
4. Dependabot keeps actions and dependencies current.
5. `mirror` workflow copies each green main to a protected GitLab project (no force pushes), using a deploy key owned by the GitLab project (`GITLAB_DEPLOY_KEY` secret, `GITLAB_REPO` variable), with GitLab's host key pinned.
