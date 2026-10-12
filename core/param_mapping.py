"""dB/Hz <-> 0..1 normalized plugin parameter mapping (v4.3).

The mapping is NOT assumed linear: Fruity Parametric EQ 2 knobs may be
nonlinear. Mapping comes from assets/eq2_params.json, produced by
scripts/calibrate_param_mapping.py (wiggle calibration). Piecewise-linear
interpolation over calibration points; falls back to scale mapping.
"""
import json
import math


class ParamMapping:
    def __init__(self, json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.params = data.get("params", {})
        if not self.params:
            raise ValueError("no params in %s" % json_path)

    def _entry(self, name):
        e = self.params.get(name)
        if e is None:
            # Fallback for multi-band params not in the calibration file:
            # infer kind from name pattern.
            e = self._default_entry(name)
            if e is None:
                raise KeyError("unknown param: %s (available: %s)"
                               % (name, sorted(self.params)))
        return e

    @staticmethod
    def _default_entry(name):
        """Generate a default entry for band params not in the file."""
        n = name.lower()
        # Chinese: 增益/频率, English: gain/frequency
        if "增益" in name or "gain" in n:
            return {"kind": "gain", "unit": "dB", "min": -18, "max": 18,
                    "scale": "linear", "calibration": None}
        if "频率" in name or "freq" in n:
            return {"kind": "freq", "unit": "Hz", "min": 20, "max": 20000,
                    "scale": "log", "calibration": None}
        return None

    def to_human(self, norm, name):
        """0..1 -> human value (dB or Hz)."""
        e = self._entry(name)
        norm = min(1.0, max(0.0, float(norm)))
        cal = e.get("calibration")
        if cal:
            pts = sorted((float(n), float(h)) for n, h in cal)
            if norm <= pts[0][0]:
                return pts[0][1]
            for (n0, h0), (n1, h1) in zip(pts, pts[1:]):
                if norm <= n1:
                    t = (norm - n0) / max(n1 - n0, 1e-12)
                    return h0 + t * (h1 - h0)
            return pts[-1][1]
        lo, hi = float(e["min"]), float(e["max"])
        if e.get("scale") == "log":
            return math.exp(math.log(lo) + norm * (math.log(hi) - math.log(lo)))
        return lo + norm * (hi - lo)

    def to_norm(self, human, name):
        """human value (dB or Hz) -> 0..1."""
        e = self._entry(name)
        cal = e.get("calibration")
        if cal:
            pts = sorted((float(n), float(h)) for n, h in cal)
            hs = [h for _, h in pts]
            if human <= hs[0]:
                return pts[0][0]
            if human >= hs[-1]:
                return pts[-1][0]
            for (n0, h0), (n1, h1) in zip(pts, pts[1:]):
                if human <= h1:
                    t = (human - h0) / max(h1 - h0, 1e-12)
                    return n0 + t * (n1 - n0)
            return pts[-1][0]
        lo, hi = float(e["min"]), float(e["max"])
        if e.get("scale") == "log":
            return (math.log(max(human, 1e-9)) - math.log(lo)) / (math.log(hi) - math.log(lo))
        return (human - lo) / max(hi - lo, 1e-12)


def build_control_params(eq_cfg):
    """Build the list of controlled params from eq config.

    Returns list of dicts with keys: key, name, index, kind, human_bounds.
    Modes:
      single_band: one gain + one freq (2D)
      three_band: 3 bands × gain+freq (6D)
      seven_gain: 7 gains only (7D)
    """
    mode = eq_cfg.get("search_mode", "single_band")
    freq_bounds = tuple(eq_cfg.get("freq_bounds", [40, 12000]))
    gain_bounds = tuple(eq_cfg.get("gain_bounds", [-12, 12]))
    params = []
    if mode == "single_band":
        params.append({
            "key": "gain", "name": eq_cfg["gain_param"],
            "index": eq_cfg.get("gain_param_index"),
            "kind": "gain", "human_bounds": gain_bounds,
        })
        params.append({
            "key": "log_freq", "name": eq_cfg["freq_param"],
            "index": eq_cfg.get("freq_param_index"),
            "kind": "freq", "human_bounds": freq_bounds,
        })
    elif mode == "three_band":
        band_ids = eq_cfg.get("three_band_ids", [1, 4, 7])
        gain_pat = eq_cfg.get("band_gain_pattern", "频段 {n} 增益")
        freq_pat = eq_cfg.get("band_freq_pattern", "频段 {n} 频率")
        for n in band_ids:
            params.append({
                "key": "gain_b%d" % n,
                "name": gain_pat.format(n=n),
                "index": n - 1,  # 0-based: band 1 -> 0
                "kind": "gain", "human_bounds": gain_bounds,
            })
            params.append({
                "key": "log_freq_b%d" % n,
                "name": freq_pat.format(n=n),
                "index": 7 + (n - 1),  # freqs start at index 7
                "kind": "freq", "human_bounds": freq_bounds,
            })
    elif mode == "seven_gain":
        gain_pat = eq_cfg.get("band_gain_pattern", "频段 {n} 增益")
        for n in range(1, 8):
            params.append({
                "key": "gain_b%d" % n,
                "name": gain_pat.format(n=n),
                "index": n - 1,
                "kind": "gain", "human_bounds": gain_bounds,
            })
    else:
        raise ValueError("unknown search_mode: %r" % mode)
    return params
