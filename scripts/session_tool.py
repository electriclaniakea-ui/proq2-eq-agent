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
from core.param_mapping import ParamMapping, build_control_params
from core.session_manager import SessionManager


def _fail(msg):
    # Always emit machine-readable JSON on stdout (the AGH JS plugin parses
    # it via extractJson); exit 0 so the JSON reaches the LLM instead of
    # being swallowed by a non-zero-exit rejection.
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    return 0


def _write_back_params(bridge, mapping, eq_cfg, params):
    """Write stored human-unit params back to FL.

    Stored snapshots use two key conventions (both carry dB / Hz values,
    so mapping.to_norm() applies directly):
      - begin_task() baseline: control keys as-is, e.g. "gain_b1",
        "log_freq_b1" (from Agent._read_eq_human)
      - confirmed candidate: human keys, e.g. "gain_b1", "freq_b1"
        (from the optimizer loop in Agent.run)
    """
    for cp in build_control_params(eq_cfg):
        ckey = cp["key"]
        hkey = (ckey.replace("log_freq_", "freq_")
                if ckey.startswith("log_") else ckey)
        if hkey in params:
            human_val = params[hkey]
        elif ckey in params:
            human_val = params[ckey]
        else:
            continue
        bridge.set_param_verified(
            cp["name"], mapping.to_norm(human_val, cp["name"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["confirm", "rollback"])
    ap.add_argument("--config", default="config/agent_config.yaml")
    args = ap.parse_args()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    try:
        cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
        try:
            sm = SessionManager(cfg["paths"]["session_file"]).load()
        except FileNotFoundError:
            return _fail("no session state yet — run eq_optimize first")

        if args.command == "confirm":
            try:
                acc = sm.confirm_candidate()
            except RuntimeError as e:
                return _fail(str(e))
            print(json.dumps({"ok": True, "accepted": acc},
                             ensure_ascii=False))
            return 0

        fell_back = sm.accepted is None
        try:
            params = sm.rollback()
        except RuntimeError as e:
            return _fail(str(e))

        bridge = make_bridge(cfg)
        try:
            mapping = ParamMapping(cfg["paths"]["params_json"])
            _write_back_params(bridge, mapping, cfg["eq"], params)
        finally:
            bridge.close()
    except Exception as e:  # noqa: BLE001 — never leak a traceback to AGH
        return _fail("%s: %s" % (type(e).__name__, e))

    out = {"ok": True, "rolled_back_to": params}
    if fell_back:
        out["note"] = ("nothing was confirmed; rolled back to the "
                       "pre-optimization snapshot")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
