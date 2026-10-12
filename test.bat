@echo off
REM ============================================================
REM Run the full test suite (no FL / hardware needed)
REM Pass = the number pytest reports; no hardcoded count here on purpose
REM ============================================================
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
    echo [ERROR] .venv not found. Run install.bat first.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m pytest tests/ -q
echo.
echo If the line above says "N passed" with no failures, you're good.
pause
