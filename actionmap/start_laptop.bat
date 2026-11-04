@echo off
REM Laptop hub + capture + voice + agents. Executor is DRY-RUN (touches nothing).
cd /d %~dp0
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
start "hub" cmd /k python -m spine.server
timeout /t 3 >nul
start "capture" cmd /k python -m clients.capture_windows
start "voice" cmd /k python -m clients.voice
start "conversation" cmd /k python -m agents.conversation
start "next-step agent" cmd /k python -m agents.next_step
start "executor (dry)" cmd /k python -m clients.executor --backend dry
start "sync" cmd /k python -m clients.sync
start http://127.0.0.1:8765
