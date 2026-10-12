@echo off
REM ============================================================
REM Offline end-to-end smoke test (no FL / MCP / VB-Cable needed)
REM Runs the full 30-iteration optimization loop on a synthetic lead.
REM ============================================================
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
    echo [ERROR] .venv not found. Run install.bat first.
    pause
    exit /b 1
)

.venv\Scripts\python.exe scripts/run_agent.py --simulate --instruction "make this lead brighter"
echo.
pause
