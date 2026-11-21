# Nodach Watch 0.1.0 (the Driver's Watch, v0)

A phone-shaped window (400 x 820, optionally always on top) for talking with Claude about what's on the screen, and
the switch that decides whether Claude may look at all. Ships inside Nodach Desktop 0.2.0 as `app\watch`.

## Watch on / off (DRV4)

Watch is **off by default**. Turn it on with the big Watch button in the Nodach Desktop window (that also opens this
window). While it's off, Gate refuses every screen tool (Snapshot, Screenshot, Click, Type, Scroll, Move, Shortcut,
App, WaitFor, capture_view) with *Watch is off: turn it on in Nodach Desktop*. Wait, ControlStatus, gate_status,
desktop_status and the Pointer's read tools still work. The setting is `watch` in `%USERPROFILE%\nodach-gate\state.json`.

## Scope: everything except what you keep out (DRV7b)

Claude may read and act on any window except the ones you keep out (and Gate's never groups: password managers,
banking, Windows Security, secrets in files, …). **Keep out** (bottom bar, or tap *Watching: …* at the top):

- **Keep out a window**: click any window on screen, then choose *This window* or *The whole app*.
- **Pick from open windows**: the same from a list (windows already out show as such, without their titles).
- **Keep out folder**: a path; windows whose title contains it (or File Explorer showing it) are out.

Entries go into the `user keep-out` never group of your `zones.json`. Each add or remove bumps `revision`, adds a
`_changes` line (date, by Nowed, what), and keeps the file as it was in `zones-history\`. Kept-out windows are
refused like other never groups, cut out of Snapshot text, blacked out of every Watch picture, and left out of
element lists. `Desktop\Nodach\nodach_sec` is in the list from the start (zones revision 4).

## The window, top to bottom

| Part | What it does |
|---|---|
| Status strip | *Watching: all windows except N kept out* (tap for the list), Gate ok / paused, and the orange *Claude is acting: <tool>* banner. |
| Offers | *Gate kept a clip … report it?* when the screen changed with nothing done (at most once per app per hour). *Looks like Claude is stuck* (same action repeated, long pause, an error): Settings toggle, **off by default**. |
| Privacy moments | While a sign-in page or a payment form is in front, Watch **pauses itself**: Gate refuses screen tools, captures black that window out, the strip says *Watch paused itself: sign-in page in front* and the chat shows a line; it resumes when the window is gone. (Video calls showing other faces: not yet.) |
| Session | The live sessions (as Studio's Live panel), Start session (owners). Sign-in is Live's saved sign-in (Settings > Sign in). |
| Chat | The session stream from the hub: your lines, Claude's and builders' replies, connector and responder comments, show steps. Newest at the bottom. |
| Drafts carousel | When Claude replies with drafts (a comment with `carousel`: cards of text, pictures, sandboxed HTML snippets, video links), they show as cards you page through. **Mark up card** draws boxes, arrows and notes on the card itself; the mark-up rides on your next line. Three buttons send the follow-on to Claude as `[for-claude] [route:…]`: *Create drafts in the app*, *Do it through Gate*, *Build an automation, then run it* (Claude lists the constraints and risks first; carrying it out is not built in v0). |
| Chips | **Looks off** (U1): judged by eye, or *compare with* an earlier capture, a reference image, a design or the last 10 s. **Mark up** (U2): free mark-up or a preset (Wrong place, Steps with if/else, Design change, Automation plan); send as a line, a report, or *to Claude* (`[for-claude]`). **Explain this** (U3): save the answer to personal / developer / don't save (asked each time, default don't save); the depth follows your signed-in role. **Report problem** (U5): Claude tries to reproduce it through Gate first; tick *Something can't be undone* for the irreversible-incident template, and nothing is replayed. A chip puts its tag (`[looks-off]`, `[wrong-place]`, `[explain]`, `[irreversible]` …) in front of the next line and highlights the tool it needs. |
| Aa | **Read out** the last reply (the PC's own voices), **Enlarge** the current capture, **As a plain list** (what can be done in a selected window or area: *Press “Save”*, *Type into “Name”* …, which it can read out too), **Bigger text**. For Nowed and stakeholders alike. |
| End | Ending a session (owners) asks whether to keep it in Studio as a **replayable lesson** (an `LS-…` item linked to the session, with its steps). |
| Bar | **Mic** (click to talk, click to send: Live's speech model on this PC), **Point** (one element), **Select** (drag a rectangle: crop + the elements inside, `kind: area`), **Mark up** (arrows, boxes, pen, notes, numbered steps, if/else labels: one `kind: markup` event with ordered marks), **10 s** (Gate keeps its clip), **Keep out**, red **Stop** (= Pause all). |

Point, Select and Mark up draw on a frozen, already-redacted picture of the screen, like an image editor. The capture
rides on your next line (or goes alone) like Studio's point chip. **Screenshots stay on this PC** unless you tick
*attach picture*; then the picture goes to your owner-only Private tier in 40 KB chunks (as Gate does) and the shared
line carries only its reference. **Export** saves a capture as a self-contained page and zip in
`%USERPROFILE%\nodach-watch\exports` (to watch back, keep as a guide, or send to a vendor).

Captures are also appended to the Pointer's `events.jsonl` (mode `watch`), so Claude on this PC can open them with
`get_pointed_elements` / `get_pointer_screenshot`.

## How it's built

`web/` is plain HTML/CSS/JS served by `watch_server.py` on `127.0.0.1` (a fresh key per start, in the page address;
nothing inline, strict CSP), shown by `watch_app.py` with pywebview (WebView2). Without pywebview it opens in the
default browser (then the window can't hide itself while you capture, and *on top* does nothing). The later Rust
Driver (Tauri) can serve the same `web/` against the same API. `watch_core.py` is the pure logic; `watch_win.py` the
Windows side (screen grab, UI Automation, the overlay).

Tests (Linux): `python -m pytest -q actionmap/watch/tests` and `node actionmap/watch/tests/test_logic.js`.
