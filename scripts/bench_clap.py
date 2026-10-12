"""Standalone CLAP latency probe (D2 diagnostic, Windows).

Measures on the real machine WITHOUT needing the FL/MCP/audio chain:
  1. checkpoint resolve + download time (music_audioset_epoch_15_esc_90.14.pt,
     ~0.8GB, official URL first, hf-mirror fallback)
  2. model load time (one-time cost)
  3. per-inference latency on synthetic 48kHz audio (3x 5s runs + 1x 20s run)

Uses the exact same code path as the agent
(core.clap_critic.CLAPCritic._score_one), so the number matches what the
real loop would see.

Usage (from project root):
    pip install laion-clap
    python scripts/bench_clap.py [--model laion/larger_clap_music]

Decision thresholds (docs/D2_CHECKLIST.md item 8):
    mean <= 1.5s -> synchronous CLAP is viable
    mean >  3.0s -> keep the async dual-loop (design: CLAP never enters
                    the optimizer objective, diagnostics only)
"""
import argparse
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.clap_critic import CLAPCritic, resolve_ckpt_path  # noqa: E402


def synth_audio(seconds, sr=48000, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr), dtype=np.float64) / sr
    tone = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    tone += 0.2 * np.sin(2 * np.pi * 880.0 * t)
    noise = 0.05 * rng.standard_normal(t.shape)
    return (tone + noise).astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description="CLAP latency probe")
    ap.add_argument("--model", default="laion/larger_clap_music")
    args = ap.parse_args()

    # 0. laion-clap must import. If dependencies are missing, install them
    # all at once from the package metadata (not one-by-one guessing).
    import subprocess
    import importlib
    from importlib.metadata import requires
    try:
        import laion_clap  # noqa: F401
    except ModuleNotFoundError:
        # Get the full dependency list from package metadata
        deps = []
        for req in (requires("laion-clap") or []):
            # Skip numpy (we need 2.x for Python 3.14, not the pinned <2.0)
            # Skip environment markers by taking the part before ';'
            pkg = req.split(";")[0].strip()
            if not pkg or pkg.lower().startswith("numpy"):
                continue
            # Strip version specifiers, keep just the name
            name = pkg.split("<")[0].split(">")[0].split("=")[0].split("!")[0].strip()
            if name:
                deps.append(name)
        # torch/torchvision are already installed by install_clap.bat
        deps = [d for d in deps if d.lower() not in ("torch", "torchvision")]
        if deps:
            print("缺少依赖，正在批量安装... / Missing deps, batch installing...")
            print("  " + ", ".join(deps))
            pip_cmd = [sys.executable, "-m", "pip", "install"] + deps + \
                      ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
            r = subprocess.run(pip_cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print("自动安装失败，请手动运行：")
                print("Auto-install failed, run manually:")
                print("  %s" % " ".join(pip_cmd))
                print(r.stderr[-1000:])
                return 3
            print("安装成功，重试导入... / Installed, retrying import...")
            importlib.invalidate_caches()
        import laion_clap  # noqa: F401  (let it raise if still broken)

    # 1. checkpoint resolve / download
    print("[1/3] resolving checkpoint ...", flush=True)
    t0 = time.perf_counter()
    ckpt = resolve_ckpt_path(args.model)
    dt = time.perf_counter() - t0
    size_mb = os.path.getsize(ckpt) / 1e6
    print("      ckpt : %s" % ckpt)
    print("      size : %.0f MB, resolve+download took %.1fs" % (size_mb, dt),
          flush=True)

    # 2. model load (one-time)
    print("[2/3] loading model ...", flush=True)
    critic = CLAPCritic(args.model, enabled=True)
    t0 = time.perf_counter()
    model = critic._require_model()
    dt = time.perf_counter() - t0
    print("      load took %.1fs" % dt, flush=True)

    # 3. per-inference latency (same path as the agent loop)
    print("[3/3] timing inference ...", flush=True)
    prompt = "a warm lead synth"
    lat_5s = []
    for i in range(3):
        audio = synth_audio(5.0, seed=i)
        t0 = time.perf_counter()
        score = critic._score_one(model, audio, prompt)
        dt = time.perf_counter() - t0
        lat_5s.append(dt)
        print("      5s run %d: %.2fs (score %.3f)" % (i + 1, dt, score),
              flush=True)
    audio = synth_audio(20.0, seed=99)
    t0 = time.perf_counter()
    score = critic._score_one(model, audio, prompt)
    dt20 = time.perf_counter() - t0
    print("      20s run: %.2fs (score %.3f)" % (dt20, score), flush=True)

    mean5 = sum(lat_5s) / len(lat_5s)
    print("mean 5s-inference latency: %.2fs" % mean5)
    if mean5 <= 1.5:
        print("verdict: SYNC viable (<=1.5s) - CLAP could run in the main loop")
    elif mean5 > 3.0:
        print("verdict: keep ASYNC dual-loop (>3s) - CLAP stays diagnostics-only")
    else:
        print("verdict: borderline (1.5-3s) - your call; async is the safe default")
    return 0


if __name__ == "__main__":
    sys.exit(main())
