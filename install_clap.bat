@echo off
chcp 65001 >nul
REM ============================================================
REM CLAP 一键安装 / One-click CLAP installer
REM 模型 / Model: laion/larger_clap_music
REM
REM 幂等设计 / Idempotent: 可从零开始运行，可在任意中断点重跑。
REM Safe to run from scratch or re-run after interruption.
REM ============================================================
cd /d %~dp0

echo ============================================
echo  CLAP 一键安装 / One-click CLAP installer
echo  模型 / Model: laion/larger_clap_music
echo ============================================
echo.

REM ---- 0. 确保基础环境存在 / Ensure base venv exists ----
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 系统 python 未找到，请先安装 Python 3.10+ 并勾选 "Add to PATH"。
    echo [ERROR] python not found on PATH. Install Python 3.10+ first.
    pause
    exit /b 1
)

if not exist .venv\Scripts\python.exe (
    echo [*] 未检测到虚拟环境，正在创建... / Creating venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] venv 创建失败 / venv creation failed.
        pause
        exit /b 1
    )
    echo [*] 正在安装基础依赖... / Installing base requirements...
    .venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
) else (
    .venv\Scripts\python.exe --version >nul 2>nul
    if errorlevel 1 (
        echo [*] 检测到损坏的 venv，正在重建... / Recreating broken venv...
        rmdir /s /q .venv
        python -m venv .venv
        if errorlevel 1 (
            echo [ERROR] venv 重建失败 / venv recreation failed.
            pause
            exit /b 1
        )
        .venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
    ) else (
        echo [*] 虚拟环境正常 / venv OK.
    )
)

set PY=.venv\Scripts\python.exe
set PIP=%PY% -m pip
set MIRROR=-i https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo [1/4] 正在安装 numpy（Python 3.14 需要 2.x 预编译包）...
echo        Installing numpy (prebuilt wheel for Python 3.14)...
%PIP% install "numpy>=2.0" --only-binary=:all: %MIRROR%
if errorlevel 1 (
    echo [ERROR] numpy 安装失败 / numpy install FAILED.
    pause
    exit /b 1
)

echo.
echo [2/4] 正在安装 laion-clap（跳过依赖检查，后续批量补装）...
echo        Installing laion-clap (--no-deps, deps installed in step 3)...
%PIP% install --force-reinstall --no-deps "laion-clap>=1.1.6" %MIRROR%
if errorlevel 1 (
    echo [ERROR] laion-clap 安装失败 / laion-clap install FAILED.
    pause
    exit /b 1
)

echo.
echo [3/4] 批量安装 laion-clap 运行依赖...
echo        Batch-installing laion-clap runtime dependencies...
%PIP% install torch torchaudio librosa transformers %MIRROR%
if errorlevel 1 (
    echo [WARN] 部分依赖安装失败，bench 脚本会自动补装缺失项。
    echo [WARN] Some deps failed; bench_clap.py will auto-install missing ones.
)

echo.
echo [4/4] 运行延迟基准（首次自动下载约1GB权重，缺失依赖自动补装）...
echo        Running benchmark (downloads ~1GB weights on first run)...
%PY% scripts\bench_clap.py
if errorlevel 1 (
    echo.
    echo [ERROR] 基准测试失败 / Benchmark FAILED.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  [OK] 完成 / Done!
echo  如需启用 CLAP，编辑 config\agent_config.yaml:
echo  To enable CLAP, edit config\agent_config.yaml:
echo    clap.enabled: true
echo ============================================
pause
