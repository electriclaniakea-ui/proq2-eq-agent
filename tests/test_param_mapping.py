"""Unit tests: param_mapping (piecewise-linear + scale fallback)."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.param_mapping import ParamMapping


def _write_tmp(data):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path


def test_linear_roundtrip():
    p = _write_tmp({"params": {
        "G": {"kind": "gain", "unit": "dB", "min": -18, "max": 18,
              "scale": "linear", "calibration": None}}})
    m = ParamMapping(p)
    assert m.to_human(0.0, "G") == -18
    assert m.to_human(1.0, "G") == 18
    assert abs(m.to_norm(0.0, "G") - 0.5) < 1e-9


def test_log_roundtrip():
    p = _write_tmp({"params": {
        "F": {"kind": "freq", "unit": "Hz", "min": 20, "max": 20000,
              "scale": "log", "calibration": None}}})
    m = ParamMapping(p)
    assert abs(m.to_human(0.0, "F") - 20) < 1e-9
    assert abs(m.to_human(1.0, "F") - 20000) < 1e-6
    mid = m.to_human(0.5, "F")
    assert 500 < mid < 700  # geometric mean ~632
    assert abs(m.to_norm(mid, "F") - 0.5) < 1e-9


def test_piecewise_calibration():
    p = _write_tmp({"params": {
        "F": {"kind": "freq", "unit": "Hz", "min": 20, "max": 20000,
              "scale": "log",
              "calibration": [[0.0, 20], [0.5, 1000], [1.0, 20000]]}}})
    m = ParamMapping(p)
    assert m.to_human(0.5, "F") == 1000
    assert m.to_human(0.25, "F") == 510.0
    assert abs(m.to_norm(1000, "F") - 0.5) < 1e-9
    assert m.to_human(-0.5, "F") == 20  # clamped
    assert m.to_human(2.0, "F") == 20000
