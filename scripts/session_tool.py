"""Session CLI for AGH tools (v4.3).

Called by agh_plugin/index.mjs; not meant for interactive use.

  python scripts/session_tool.py confirm   # accept the proposed candidate
  python scripts/session_tool.py rollback  # roll FL back to accepted params

Prints a single JSON object to stdout.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml

from core.fl_bridge import make_bridge
from core.param_mapping import ParamMapping
from core.session_manager import SessionManager


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["confirm", "rollback"])
    ap.add_argument("--config", default="config/agent_config.yaml")
    args = ap.parse_args()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    sm = SessionManager(cfg["paths"]["session_file"]).load()
    GAIN_PARAM = cfg["eq"]["gain_param"]
    FREQ_PARAM = cfg["eq"]["freq_param"]

    if args.command == "confirm":
        acc = sm.confirm_candidate()
        print(json.dumps({"ok": True, "accepted": acc}, ensure_ascii=False))
        return 0

    params = sm.rollback()  # may raise if no accepted state
    bridge = make_bridge(cfg)
    try:
        mapping = ParamMapping(cfg["paths"]["params_json"])
        bridge.set_param_verified(
            GAIN_PARAM, mapping.to_norm(params["gain_db"], GAIN_PARAM))
        bridge.set_param_verified(
            FREQ_PARAM, mapping.to_norm(params["freq_hz"], FREQ_PARAM))
    finally:
        bridge.close()
    print(json.dumps({"ok": True, "rolled_back_to": params},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
