"""Dump Fruity Parametric EQ 2 parameter list via MCP (v4.3).

Usage:
  python scripts/dump_eq2_params.py --list-tools   # inspect MCP tool names
  python scripts/dump_eq2_params.py                # save param skeleton
Requires: FL Studio running with the EQ loaded + MCP server installed.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml

from core.fl_bridge import make_bridge


def main():
    # Windows console defaults to GBK; param names may be Chinese.
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/agent_config.yaml")
    ap.add_argument("--list-tools", action="store_true")
    ap.add_argument("--out", default="assets/eq2_params.json")
    args = ap.parse_args()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    b = make_bridge(cfg)
    try:
        if args.list_tools:
            for name, desc in b.list_tools():
                print("%s\n    %s" % (name, (desc or "")[:100]))
            return
        params = b.list_params()
        print("found %d params" % len(params))
        for p in params:
            if isinstance(p, dict):
                print(" -", p.get("name"), p.get("value_normalized"))
            else:
                print(" -", p)
        # merge names into skeleton without clobbering calibration
        out = {"params": {}}
        if os.path.exists(args.out):
            out = json.load(open(args.out, encoding="utf-8"))
        names = [p["name"] if isinstance(p, dict) else str(p) for p in params]
        for n in names:
            out["params"].setdefault(n, {"kind": "unknown", "unit": "?",
                                         "min": 0, "max": 1, "scale": "linear",
                                         "calibration": None})
        json.dump(out, open(args.out, "w", encoding="utf-8"), indent=2)
        print("skeleton saved to", args.out)
    finally:
        b.close()


if __name__ == "__main__":
    main()
