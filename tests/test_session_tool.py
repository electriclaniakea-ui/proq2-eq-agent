"""Unit tests: session_tool rollback write-back key formats.

Regression test for KeyError: 'gain_db' — session_tool.rollback() assumed
params keys "gain_db"/"freq_hz", which exist nowhere. Real snapshots use:
  - baseline (begin_task <- _read_eq_human): "gain_b1", "log_freq_b1"
  - candidate (optimizer):                    "gain_b1", "freq_b1"
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# session_tool imports yaml + core.fl_bridge at module level; stub the parts
# this test doesn't exercise so it stays a pure unit test.
_yaml_stub = types.ModuleType("yaml")
_yaml_stub.safe_load = lambda *a, **k: {}
sys.modules.setdefault("yaml", _yaml_stub)
_fl_stub = types.ModuleType("core.fl_bridge")
_fl_stub.make_bridge = lambda cfg: None
sys.modules.setdefault("core.fl_bridge", _fl_stub)

import session_tool  # noqa: E402


class _FakeBridge:
    def __init__(self):
        self.written = {}

    def set_param_verified(self, name, norm):
        self.written[name] = norm


class _FakeMapping:
    def to_norm(self, human, name):
        return (human, name)


EQ_CFG = {
    "search_mode": "three_band",
    "three_band_ids": [1],
    "band_gain_pattern": "Band {n} Gain",
    "band_freq_pattern": "Band {n} Freq",
    "freq_bounds": [40, 12000],
    "gain_bounds": [-12, 12],
}


def test_write_back_baseline_format():
    # keys as stored by begin_task() <- Agent._read_eq_human
    b = _FakeBridge()
    session_tool._write_back_params(
        b, _FakeMapping(), EQ_CFG,
        {"gain_b1": -3.0, "log_freq_b1": 800.0})
    assert b.written == {"Band 1 Gain": (-3.0, "Band 1 Gain"),
                         "Band 1 Freq": (800.0, "Band 1 Freq")}


def test_write_back_candidate_format():
    # keys as stored by propose_candidate() <- optimizer loop
    b = _FakeBridge()
    session_tool._write_back_params(
        b, _FakeMapping(), EQ_CFG,
        {"gain_b1": 2.0, "freq_b1": 1200.0})
    assert b.written == {"Band 1 Gain": (2.0, "Band 1 Gain"),
                         "Band 1 Freq": (1200.0, "Band 1 Freq")}


def test_write_back_skips_missing_keys():
    b = _FakeBridge()
    session_tool._write_back_params(b, _FakeMapping(), EQ_CFG, {})
    assert b.written == {}
