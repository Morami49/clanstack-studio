#!/usr/bin/env bash
# Oracle VM hub: always-on copy of the log, profiler, and the connector for outside AIs.
# Run inside tmux/screen, or turn each line into a systemd service.
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate
python3 -m spine.server &      sleep 3
python3 -m agents.profiler &
python3 -m spine.mcp_server &
python3 -m clients.sync &
wait
