"""Wiggle calibration: normalized 0..1 <-> human Hz/dB (v4.3).

For each EQ param, sets 5 normalized values [0, .25, .5, .75, 1.0] and asks
YOU to read the human-readable value shown in the FL plugin UI, then builds
the piecewise-linear mapping saved to assets/eq2_params.json.

Requires: FL Studio + EQ loaded + MCP. Takes ~2 minutes of your time.
Usage: python scripts/calibrate_param_mapping.py [--simulate]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml

from core.fl_bridge import SimulatedBridge, make_bridge
from core.param_mapping import ParamMapping

WIGGLE = [0.0, 0.25, 0.5, 0.75, 1.0]


def _parse_human_value(raw):
    """Extract the first number (+unit) from user input.

    Accepts: '-18.0 dB', '440 Hz', '1.5 kHz'. If the user pastes extra
    text (e.g. '-18.0 dB 136 Hz'), the first number wins.
    """
    m = re.search(r"([-+]?\d*\.?\d+)\s*(kHz|Hz|dB)?", raw, re.IGNORECASE)
    if not m:
        raise ValueError("no number found in %r" % raw)
    val = float(m.group(1))
    if (m.group(2) or "").lower() == "khz":
        val *= 1000.0
    return val


def main():
    # Windows console defaults to GBK; param names may be Chinese.
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/agent_config.yaml")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--params", nargs="*", default=None,
                    help="default: cfg eq.gain_param + eq.freq_param")
    args = ap.parse_args()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    if args.params is None:
        args.params = [cfg["eq"]["gain_param"], cfg["eq"]["freq_param"]]
    out_path = cfg["paths"]["params_json"]

    if args.simulate:
        bridge = SimulatedBridge(args.params)
    else:
        bridge = make_bridge(cfg)
        print("标定：我会把每个参数推到 5 个位置 (0%, 25%, 50%, 75%, 100%)。")
        print("每次推完后，请把 FL 插件窗口里显示的数值告诉我。")
        print("(Calibration: I'll move each parameter to 5 positions.")
        print(" After each move, type in the value shown in FL.)")
        print("这用来建立 0-1 数值和真实单位的映射。/ This builds the")
        print("mapping between normalized values and real units.")
    try:
        data = json.load(open(out_path, encoding="utf-8")) \
            if os.path.exists(out_path) else {"params": {}}
        for name in args.params:
            print("\n=== %s ===" % name)
            pts = []
            for v in WIGGLE:
                bridge.set_param_verified(name, v)
                if args.simulate:
                    gp, fp = cfg["eq"]["gain_param"], cfg["eq"]["freq_param"]
                    human = {gp: v * 36 - 18,
                             fp: 20 * (1000 ** v)}[name]
                    print("  norm %.2f -> (simulated) %.2f" % (v, human))
                else:
                    print("  norm %.2f 已写入 FL / written to FL." % v)
                    print("  在 FL 插件窗口找到 '%s'，把显示的数值照抄下来"
                          % name)
                    print("  (Find '%s' in the FL plugin window and copy the"
                          " value it shows.)" % name)
                    print("  例如增益填 +6.0 dB，频率填 440 Hz 或 1.5 kHz；"
                          "只填一个数。")
                    print("  (e.g. '+6.0 dB' for gain, '440 Hz'/'1.5 kHz' for "
                          "frequency; just one number.)")
                    while True:
                        raw = input("  数值 / value: ").strip()
                        try:
                            human = _parse_human_value(raw)
                        except ValueError:
                            print("  没读到数字，请只输入数字 "
                                  "(no number found, try again):")
                            continue
                        print("  -> 记为 %.4g / recorded as %.4g"
                              % (human, human))
                        break
                pts.append([v, human])
            e = data["params"].setdefault(name, {})
            e.update({"calibration": pts})
            if "Gain" in name:
                e.update({"kind": "gain", "unit": "dB", "min": -18,
                          "max": 18, "scale": "linear"})
            else:
                e.update({"kind": "freq", "unit": "Hz", "min": 20,
                          "max": 20000, "scale": "log"})
        json.dump(data, open(out_path, "w", encoding="utf-8"), indent=2)
        print("\nsaved to", out_path)
        # sanity round-trip
        m = ParamMapping(out_path)
        for name in args.params:
            for v in WIGGLE:
                h = m.to_human(v, name)
                back = m.to_norm(h, name)
                assert abs(back - v) < 1e-6, (name, v, h, back)
        print("round-trip check passed")
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
