# Clanstack clusters — read this first (D-154)

A compressed map of everything built, recorded and discussed, so any agent (builder, auditor, commander) can
start from ~2 pages instead of the whole history. Each cluster names its IDs; open HANDOFF.md or Studio only
for the IDs a task touches. Update the cluster a change belongs to in the same commit.

## C1 Vision and principles
- Clanstack: a constitutional network and multi-capital economy; Clanstack Studio is the whole platform (VISION-0, L1 purposes).
- Principles P-01…P-13. Most used: P-10 approvals count people, not profiles; P-12 only reversible actions run on their own;
  P-13 automate the doing, never the knowing (every run readable and replayable).
- Neutral infrastructure, not "plausible deniability" (D-125). Third parties' data stays private (D-145).

## C2 Studio Web (the interface) — studio/index.html, artifact 4hTHTKeonKNHhjRY2iChni
- Append-only events folded into items (D-101 order: ts, then doc id). Private area: data/users/<id>/vault/events.
- Tabs: Map, Command, List, Ask, Capture, Tree, Pack, Money, Hub, Runs, Builders, Studio.
- v1.1 Command map (D-157): voice (browser speech) or text → command nodes; suggest/act/observe; private CMD-log.
- v1.0: Studio develops Studio (D-152/D-153): look (SET-ui-theme), item types (SCHEMA-types) live; code changes as
  change requests (type `change`) → change intake → GitHub issue → builder.
- Tests: studio/tests/scenarios.py (Playwright, 33 scenarios). Harness store delivers one write at a time (F-64).

## C3 Hub (always-on record) — hub/ (Cloudflare Worker + Durable Object), engine/crates/hub-core
- Signed hash chain; Studio events imported with original authors (Q99 A); writes via the Claude connector.
- MCP tools: hub_status, read_events, hub_log, import_studio_events, write_event (idempotency_key F-48; unknown-item warnings F-47).
- OAuth 2.1 for claude.ai (D-128). Request log: never contents (D-130). /health shows the build.

## C4 Executors and policies (D-133, D-136, D-139, D-143)
- Policies live in Studio (SET-policy-*); executors read them via scripts/policy.py, fall back to GitHub variables, record drift (D-141).
- Executors: branch-cleanup (auto), hub-deploy (auto; rollback by dispatch with sha), gitlab-mirror, change-intake (every 6 h),
  Studio↔hub sync (read on open; push after 5 clean runs, D-140). Each writes RUNS-<name> records (scripts/run_record.py).
- Repo flow: b-* branch → CI → fast-forward main (pre-push hook + main-guard). Never force-push.

## C5 AI roles (D-149)
- Builder: Claude (code, Studio). Auditor: any other AI with actionmap/AUDITOR.md. Commander: GitHub Actions, no tokens.
- Now: self-hosted free models for the cheap-agent and auditor roles (D-158); premium agents later. Small CRs → cheap agent (D-156).
- Builder's usage is scarce: auditor carries the standing open-ended enquiry; builder answers specific questions.
- **Reply format (never drop, F-66):** every line indexed (1, 1.1, 1.1.1) so it can be quoted; questions as scoreboards
  (option, score, evidence, trade-off) answerable in one line; complete walkthroughs in the reply; state stamp at the end.
  Shorter replies mean fewer lines, never losing the index or the scores.

## C0 The core the build drifted from (re-read before any interface work, D-155)
- ActionMap: maps are the controls. Voice for controls, narration and full conversation (push-to-talk, wake word,
  always-on). Observe / suggest / act modes, combinable, human↔agent and agent↔agent. Live and replayable maps of
  human, screen and agent actions (whole Windows desktop capture, eye tracking dropped). Visual version tree with
  parallel sessions resumable from any point. Rust/WASM foundation (own DAG, iroh, Leptos), laptop + VM hubs in sync.
- **Already built and easy to forget (F-69): ActionMap v0.2 in actionmap/ (Python)**: Windows capture with privacy defaults,
  voice (right-Ctrl push-to-talk, wake word, always-on presets, local transcription), map UI at 127.0.0.1:8765, agents
  (next-step, profiler, conversation), model router (Groq, Gemini, Ollama), laptop↔VM hash-verified sync, MCP connector.
  Field-test it and bridge into the hub before rewriting (D-160).
- Live mixed-media canvases (sketch, map, voice, text) commanding digital, physical, community, publishing and IoT systems;
  anyone can design and share experiences across canvases; change and re-template anything safely at any scope.

## C6 Builder interviews and content (D-069, D-145…D-148)
- Private pipeline: found → contacted → agreed → interviewed → drafted → published → followed up; release-gated (T-release, formats).
- Kit: KIT-builder-interview. Pieces per format/channel/cycle; measures user-chosen (D-147); raw files encrypted in browser (D-148).

## C7 Security and privacy
- Compartments with per-compartment keys (D-119, D-124); first piece: encrypted files (D-148); recovery key only in particular flows (D-151).
- Control + public-safe profiles, duress decoy (D-127). OSA risk assessment before first outside user (D-125).
- Secrets only in GitHub/Cloudflare secrets; actions pinned to SHAs (F-34).

## C8 Linked chats and side ventures
- CHAT-952fc20c: Utopia Index analysis → sustainable-strategy guide → employment-placement venture (East London + GLA; Lift excluded).
- CHAT-6186e508: merged method: claims with confidence/velocity, decisions flagged when claims move, findings as a regression suite, gate rule.

## C9 Open (next builds, by recorded choice)
- Next: Studio Web in any browser via the hub (D-161); ActionMap v0.2 field test + hub bridge (D-160); Oracle stack (D-159, W16).
- Q115 (pending): merged method into Studio / dashboards (D-150) / placement venture.
- D-151 recovery key; D-131 sealed capture; D-123 Master Reference v2.0 merge; F-65 flaky s16.
