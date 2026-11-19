# Nodach Live client (v0.1.0)

Talk into a Nodach Studio **live session** from your Windows PC while Claude and builders reply in the same
stream (Studio → **◉ Live**). Speech is turned into text **on your PC** (faster-whisper on the CPU); the audio
never leaves it. Only the text of each line goes to the hub, signed in as you.

| Key | What it does |
|---|---|
| **Ctrl+Alt+Space** | push to talk: press, speak, press again to send |
| **Ctrl+Alt+A** | always-on: toggle; each phrase (a pause ends it) becomes a line |
| **Ctrl+Alt+L** | send the Nodach pointer's latest point on its own |
| type + **Enter** | send a typed line (works with or without a microphone) |
| `/point` `/always` `/end` `/quit` | the same from the keyboard; `/end` ends the session (owners) |

- A line starting **`task:`** or **`build:`** also creates a **draft** change item linked to the session (status
  `draft`; nothing is built until an owner approves it). Speech often writes the colon as a comma or full stop;
  those count too.
- If you pointed with the Nodach Desktop Pointer (**Ctrl+Alt+M**) in the last 2 minutes, that point rides on your
  next line: app name, element type and name, and your note. Window titles, screenshots and file paths stay on the PC.
  `--no-point` turns this off.
- Keys don't clash with the pointer (Ctrl+Alt+M/B/Q) or ActionMap capture (Ctrl+Alt+P).

## First-time setup (Windows)

1. Python on PATH: <https://www.python.org/downloads/windows/> (tick **Add python.exe to PATH**).
2. Get the folder: download the branch zip <https://github.com/Morami49/nodach-studio/archive/refs/heads/b-live-session-v1.zip>,
   extract it, and open `nodach-studio-b-live-session-v1\actionmap\live` in File Explorer. Right-click an empty
   spot → **Open in Terminal**, then run:
   ```
   pip install -r requirements.txt
   ```
   (Typed-only works without this.)
3. Copy your Studio sign-in (once every 30 days): in Chrome or Edge open <https://staging.nodach.com/studio> and sign
   in. Press **F12** → **Application** tab → **Cookies** → `https://staging.nodach.com` → click `nodach_session` →
   copy its **Cookie Value**. Close DevTools.
4. Double-click `start-live.bat`. Paste the value when asked (it isn't shown; it's kept in
   `%USERPROFILE%\nodach-live\session-staging.nodach.com.txt`). The first voice run downloads the `base` model once.
5. If none of your sessions is live it offers to start one (or start it in Studio first: **◉ Live → Start a session**).

Options: `--hub https://studio.nodach.com` (production, once merged), `--session LV-…`, `--start`, `--typed`,
`--model tiny|base|small` (small is more accurate, slower), `--no-point`. `NODACH_LIVE_LEVEL` (default `0.015`)
sets how loud counts as speech in always-on mode.

## Files and data

| File | What it is |
|---|---|
| `live_client.py` | the client: microphone, hotkeys, local transcription, posting to the hub |
| `live_core.py` | pure logic: task lines, event shapes, pointer point, phrase cutting |
| `test_live.py` | tests that run anywhere, no microphone: `python -m pytest actionmap/live/test_live.py` |
| `start-live.bat` | starts the client |

`%USERPROFILE%\nodach-live\lines.jsonl` is an append-only log of every line sent or not sent (text only). Events
go to `POST /studio/api/events` with your `nodach_session` cookie and the `x-nodach-studio` header, exactly like
Studio's own writes, so the hub's access rules apply: owners can write anywhere, members only into a session they
were given.
