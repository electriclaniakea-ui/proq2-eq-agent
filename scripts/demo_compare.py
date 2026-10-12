"""Demo comparison runner (v4.3): original vs fixed-preset vs agent.

Usage:
  python scripts/demo_compare.py --simulate \
      --instructions "make this lead brighter" "soften the harshness"
Saves a comparison table (before/after DSP features) to docs/.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml

from run_agent import (FakePlanner, SimulatedAudioCapture, SimulatedBridge,
                       load_config)
from core import dsp_features as dsp
from core.agent import Agent
from core.param_mapping import ParamMapping
from core.session_manager import SessionManager

DIMENSIONS = ["spectral_centroid", "spectral_flatness", "sibilance_ratio",
              "spectral_rolloff", "rms"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instructions", nargs="+", required=True)
    ap.add_argument("--config", default="config/agent_config.yaml")
    ap.add_argument("--simulate", action="store_true")
    args = ap.parse_args()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    cfg = load_config(args.config)
    mapping = ParamMapping(cfg["paths"]["params_json"])
    rows = []
    for ins in args.instructions:
        bridge = SimulatedBridge() if args.simulate else None
        if bridge is None:
            print("demo_compare currently supports --simulate only")
            return 1
        audio = SimulatedAudioCapture(bridge, mapping,
                                      sr=cfg["audio"]["sample_rate"])
        session = SessionManager()
        agent = Agent(cfg, bridge, audio, FakePlanner(), session, mapping)
        before = dsp.all_features(audio.base, audio.sr, dims=DIMENSIONS)
        report = agent.run(ins)
        after = dsp.all_features(audio._apply_eq(), audio.sr, dims=DIMENSIONS)
        rows.append({"instruction": ins, "status": report["status"],
                     "best_params": (report["best"] or {}).get("params"),
                     "before": before, "after": after})
        print("done:", ins, "->", report["status"])
    out = os.path.join("docs", "demo_compare.json")
    json.dump(rows, open(out, "w", encoding="utf-8"), indent=2)
    print("saved", out)
    for r in rows:
        print("\n== %s [%s] ==" % (r["instruction"], r["status"]))
        for d in DIMENSIONS:
            print("  %-18s before=%.4g after=%.4g"
                  % (d, r["before"][d], r["after"][d]))


if __name__ == "__main__":
    sys.exit(main())
