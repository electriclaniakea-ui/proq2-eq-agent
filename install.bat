@echo off
REM ============================================================
REM ProQ2-EQ-Agent one-click installer (Windows)
REM Creates .venv and installs all dependencies. Safe to re-run.
REM ============================================================
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found on PATH.
    echo         Install Python 3.10+ from python.org and check "Add to PATH".
    pause
    exit /b 1
)

if not exist .venv\Scripts\python.exe (
    echo [*] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] venv creation failed.
        pause
        exit /b 1
    )
) else (
    .venv\Scripts\python.exe --version >nul 2>nul
    if errorlevel 1 (
        echo [*] Existing venv python.exe is broken, recreating...
        rmdir /s /q .venv
        python -m venv .venv
        if errorlevel 1 (
            echo [ERROR] venv recreation failed.
            pause
            exit /b 1
        )
    ) else (
        echo [*] Virtual environment OK, skipping creation.
    )
)

echo [*] Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip

echo [*] Installing dependencies (this may take a few minutes)...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed. If downloads are slow, retry with the Tsinghua mirror:
    echo   .venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
    pause
    exit /b 1
)

echo.
echo [OK] Installation complete.
echo   Next: double-click test.bat to verify, simulate.bat for an offline smoke test.
echo   Then see docs\SETUP_AND_TRANSFER.md for VB-Cable / MIDI bridge setup.
pause
