"""Local entry point (v4.3). Thin wrapper -> core.agent.

Usage:
  python scripts/run_agent.py --instruction "make this lead brighter"
  python scripts/run_agent.py --instruction "..." --simulate   # no FL needed
  python scripts/run_agent.py --instruction "..." --mode delta
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import yaml

from core.agent import Agent
from core.audio_capture import AudioCapture
from core.clap_critic import CLAPCritic
from core.fl_bridge import SimulatedBridge, make_bridge
from core.param_mapping import ParamMapping
from core.session_manager import SessionManager
from core import visualize as viz


class PrebuiltPlanner:
    """Uses a dsp_plan built by the AGH agent (LLM 1). No LLM call in Python."""

    def __init__(self, dsp_plan, log_dir="docs/planner_logs"):
        self.dsp_plan = dsp_plan
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def plan(self, instruction, baseline_features, objective_id, mode="full",
             history=None, accepted_params=None, plugin_limits=None):
        plan = dict(self.dsp_plan)
        plan["objective_id"] = objective_id
        plan["intent"] = instruction
        plan["mode"] = mode
        # Log for audit
        log_path = os.path.join(self.log_dir, objective_id + ".json")
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        return plan


# ---------------------------------------------------------------------------
# Offline simulation (no FL / MCP / VB-Cable). Applies a digital peaking EQ
# to a synthesized lead so the whole loop can be tested on any machine.
# ---------------------------------------------------------------------------
class SimulatedAudioCapture:
    def __init__(self, bridge, mapping, sr=48000, bpm=120.0, beats=8,
                 gain_param="Band 2 Gain", freq_param="Band 2 Frequency",
                 control_params=None):
        self.bridge = bridge
        self.mapping = mapping
        self.gain_param = gain_param
        self.freq_param = freq_param
        # For multi-band: list of (gain_name, freq_name_or_None) tuples.
        # If None, falls back to single (gain_param, freq_param).
        self.control_params = control_params
        self.sr = sr
        self.n_loop = int(sr * 60.0 / bpm * beats)
        t = np.arange(self.n_loop) / sr
        # synthetic "lead": saw-ish stack + slight noise.
        # Includes high harmonics so "brighter" targets are reachable
        # by boosting (not only by cutting lows).
        sig = (np.sin(2 * np.pi * 220 * t)
               + 0.5 * np.sin(2 * np.pi * 440 * t)
               + 0.25 * np.sin(2 * np.pi * 660 * t)
               + 0.12 * np.sin(2 * np.pi * 880 * t)
               + 0.06 * np.sin(2 * np.pi * 1760 * t)
               + 0.03 * np.sin(2 * np.pi * 3520 * t)
               + 0.015 * np.sin(2 * np.pi * 7040 * t)
               + 0.02 * np.random.RandomState(0).randn(self.n_loop))
        self.base = (sig / np.abs(sig).max() * 0.5).astype(np.float64)

    def _apply_eq(self):
        from scipy import signal as _sig
        # Build list of (gain_human, freq_human) to apply in series.
        # For multi-band, control_params is [(gain_name, freq_name|None)].
        bands = []
        if self.control_params:
            for gname, fname in self.control_params:
                g = self.mapping.to_human(
                    self.bridge.get_param(gname), gname)
                f = self.mapping.to_human(
                    self.bridge.get_param(fname), fname) if fname else 1000.0
                bands.append((g, f))
        else:
            g = self.mapping.to_human(
                self.bridge.get_param(self.gain_param), self.gain_param)
            f = self.mapping.to_human(
                self.bridge.get_param(self.freq_param), self.freq_param)
            bands.append((g, f))
        out = self.base.copy()
        for g, f in bands:
            if abs(g) < 0.05:
                continue
            w0 = min(f / (self.sr / 2), 0.99)
            b, a = _sig.iirpeak(w0, 1.0)
            wet = _sig.lfilter(b, a, out)
            k = min(abs(g) / 12.0, 1.0) * (1 if g > 0 else -1)
            out = out + k * (wet - out)
        return (out / max(np.abs(out).max(), 1e-9) * 0.5)

    def capture_two_loops(self, n_loop_samples, timeout_s=15):
        loop = self._apply_eq()
        return loop.copy(), loop.copy()

    def capture_stable_loop(self, n_loop_samples, *a, **k):
        # Contract (same as AudioCapture.capture_stable_loop): return
        # (features_dict, stable_bool). The raw loop is converted to DSP
        # features here so Agent._capture_baseline and planners can index
        # by feature name (e.g. baseline["spectral_centroid"]).
        from core import dsp_features as dsp
        loop = self._apply_eq()
        return dsp.all_features(loop, self.sr), True

    def start(self):
        pass

    def stop(self):
        pass


class FakePlanner:
    """Deterministic planner for offline testing (no LLM calls)."""

    def __init__(self, log_dir="docs/planner_logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def plan(self, instruction, baseline_features, objective_id, mode="full",
             history=None, accepted_params=None, plugin_limits=None):
        ins = instruction.lower()
        if any(w in ins for w in ["bright", "亮"]):
            dims = {"spectral_centroid": "maximize",
                    "spectral_flatness": "minimize"}
        elif any(w in ins for w in ["dark", "暗", "warm", "暖"]):
            dims = {"spectral_centroid": "minimize"}
        elif any(w in ins for w in ["harsh", "刺耳", "sibilance", "嘶"]):
            dims = {"sibilance_ratio": "minimize",
                    "spectral_centroid": "minimize"}
        else:
            dims = {"spectral_centroid": "maximize"}
        from core import dsp_features as dsp
        intervals, scores = {}, {}
        for i, (d, direction) in enumerate(dims.items()):
            tlo, thi = dsp.FEATURE_INFO[d][1]
            v0 = baseline_features[d]
            span = thi - tlo
            if direction == "maximize":
                intervals[d] = [v0 + 0.3 * span, v0 + 0.7 * span]
            else:
                intervals[d] = [v0 - 0.7 * span, v0 - 0.3 * span]
            intervals[d][0] = max(intervals[d][0], tlo)
            intervals[d][1] = min(intervals[d][1], thi)
            scores[d] = 9 if i == 0 else 6
        cfg = {"objective_id": objective_id, "status": "ok", "mode": mode,
               "intent": "offline-test intent for: " + instruction,
               "clap_prompt": "a lead synth, " + instruction,
               "clap_weight": 0.3,
               "search_bounds": {"gain_db": [-12, 12], "freq_hz": [200, 12000]},
               "target_intervals": intervals, "dsp_scores": scores,
               "hard_constraints": {"peak_ceiling": 0.999, "min_rms": 1e-6},
               "max_evaluations": 15, "seed": 42}
        with open(os.path.join(self.log_dir, objective_id + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump({"objective_id": objective_id, "raw_response": cfg,
                       "simulated": True}, f, indent=2)
        return cfg


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruction", required=True)
    ap.add_argument("--mode", default="full", choices=["full", "delta"])
    ap.add_argument("--dsp-plan", default=None,
                    help="JSON string with dsp_plan from AGH agent.")
    ap.add_argument("--analyze-only", action="store_true",
                    help="Only measure baseline DSP features and exit.")
    ap.add_argument("--config", default="config/agent_config.yaml")
    ap.add_argument("--simulate", action="store_true",
                    help="offline test: no FL/MCP/VB-Cable needed")
    ap.add_argument("--objective-id", default=None)
    ap.add_argument("--json-only", action="store_true",
                    help="print only the JSON report (for the AGH plugin)")
    args = ap.parse_args()

    root = os.path.join(os.path.dirname(__file__), "..")
    os.chdir(root)
    cfg = load_config(args.config)

    # PID lock file: kill stale optimize process from a previous disconnected session
    # Skip for --analyze-only (quick, no need to kill) and --simulate (testing)
    lock_path = os.path.join(cfg["paths"].get("session_dir", "."),
                              ".eq_optimize.lock")
    if not args.analyze_only and not args.simulate:
        import signal
        # Kill previous stale process if lock exists
        if os.path.exists(lock_path):
            try:
                with open(lock_path, "r", encoding="utf-8") as f:
                    old_pid = int(f.read().strip())
                # Check if process is still running, then kill it
                try:
                    if sys.platform == "win32":
                        # Windows: use taskkill
                        import subprocess
                        subprocess.run(["taskkill", "/F", "/PID", str(old_pid)],
                                       capture_output=True, timeout=5)
                    else:
                        os.kill(old_pid, signal.SIGTERM)
                    print("[lock] killed stale optimize process PID %d" % old_pid,
                          file=sys.stderr)
                except (ProcessLookupError, OSError, ValueError):
                    pass  # process already gone, or invalid PID
            except Exception:
                pass
        # Write our PID
        try:
            os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
            with open(lock_path, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            # Clean up lock on exit
            import atexit
            def _remove_lock():
                try:
                    # Only remove if it's our PID (avoid deleting a newer process's lock)
                    with open(lock_path, "r", encoding="utf-8") as f:
                        if f.read().strip() == str(os.getpid()):
                            os.remove(lock_path)
                except Exception:
                    pass
            atexit.register(_remove_lock)
        except Exception:
            pass

    mapping = ParamMapping(cfg["paths"]["params_json"])
    session = SessionManager(cfg["paths"]["session_file"])

    if args.simulate:
        from core.param_mapping import build_control_params
        eq = cfg["eq"]
        cps = build_control_params(eq)
        # Build (gain_name, freq_name|None) pairs for the simulator.
        # Pair up gain_bN with log_freq_bN; for seven_gain mode freq is None.
        pairs = []
        gains = {cp["key"]: cp for cp in cps if cp["kind"] == "gain"}
        freqs = {cp["key"]: cp for cp in cps if cp["kind"] == "freq"}
        for gkey, gcp in gains.items():
            # Find matching freq: replace "gain_" with "log_freq_"
            fkey = gkey.replace("gain_", "log_freq_")
            fcp = freqs.get(fkey)
            # For single_band mode, keys are "gain"/"log_freq" (no _bN)
            if fcp is None and gkey == "gain":
                fcp = freqs.get("log_freq")
            pairs.append((gcp["name"], fcp["name"] if fcp else None))
        all_names = [n for pair in pairs for n in pair if n]
        bridge = SimulatedBridge(tuple(all_names))
        audio = SimulatedAudioCapture(bridge, mapping,
                                      sr=cfg["audio"]["sample_rate"],
                                      gain_param=eq["gain_param"],
                                      freq_param=eq["freq_param"],
                                      control_params=pairs)
        planner = FakePlanner(cfg["paths"]["planner_logs"])
        clap = None
    else:
        bridge = make_bridge(cfg)
        au = cfg["audio"]
        audio = AudioCapture(au["input_device"], au["sample_rate"],
                             au["blocksize"], au["ring_seconds"])
        audio.start()
        # --analyze-only: measure baseline DSP features and exit (for eq_analyze tool)
        if args.analyze_only:
            agent_tmp = Agent(cfg, bridge, audio, None, session, mapping, None)
            features, stable = agent_tmp._capture_baseline()
            print(json.dumps({"status": "ok", "baseline": features,
                              "stable": stable}, ensure_ascii=False))
            return 0
        # DSP plan comes from AGH agent (LLM 1). Python never calls LLM directly.
        # --dsp-plan: JSON string with target_intervals, dsp_scores, clap_weight, clap_prompt.
        # If omitted, falls back to heuristic planner.
        if args.dsp_plan:
            try:
                dsp_plan = json.loads(args.dsp_plan)
            except json.JSONDecodeError as e:
                print("Invalid --dsp-plan JSON: %s" % e, file=sys.stderr)
                return 1
            planner = PrebuiltPlanner(dsp_plan, cfg["paths"]["planner_logs"])
        else:
            print("No --dsp-plan provided, using built-in heuristic planner.", file=sys.stderr)
            print("(AGH agent should provide dsp_plan for full LLM planning.)", file=sys.stderr)
            planner = FakePlanner(cfg["paths"]["planner_logs"])
        cc = cfg["clap"]
        clap = CLAPCritic(cc["model"], enabled=cc["enabled"],
                          sample_rate=au["sample_rate"])
        clap.start()

    agent = Agent(cfg, bridge, audio, planner, session, mapping, clap)
    try:
        if not args.simulate and not bridge.is_playing():
            print("[!] FL is not playing. Start pattern playback, then re-run.",
                  file=sys.stderr)
            return 1
        report = agent.run(args.instruction, mode=args.mode,
                           objective_id=args.objective_id)

    finally:
        audio.stop()
        bridge.close()

    summary = {k: v for k, v in report.items() if k != "trajectory"}
    if args.json_only:
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    traj = report["trajectory"]
    if traj:
        bounds = report.get("search_bounds") or \
            {"gain_db": [-18, 18], "freq_hz": [20, 20000]}
        pdir = cfg["paths"]["trajectory_plots"]
        viz.plot_trajectory(traj, bounds,
                            os.path.join(pdir, report["objective_id"] + ".png"))
        viz.plot_convergence(traj, os.path.join(
            pdir, report["objective_id"] + "_conv.png"))
        print("plots saved to", pdir, file=sys.stderr)
    if report["status"] == "success":
        print("\nCandidate proposed. Listen, then confirm via "
              "session.confirm_candidate() or scripts UI.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
