"""Offline end-to-end test (no FL): full agent loop in simulation.

SimulatedBridge + SimulatedAudioCapture + FakePlanner exercise
phase1 -> phase2 -> phase3, three-state session, and trajectory logging.
Slow on purpose (15 DSP evaluations); run explicitly.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import yaml
from core.agent import Agent
from core.param_mapping import ParamMapping
from core.session_manager import SessionManager
from run_agent import FakePlanner, SimulatedAudioCapture, SimulatedBridge

ROOT = os.path.join(os.path.dirname(__file__), "..")


@pytest.mark.slow
def test_offline_full_loop_brighter(tmp_path):
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config/agent_config.yaml"), encoding="utf-8"))
    cfg["audio"]["sample_rate"] = 16000  # speed up the test
    mapping = ParamMapping(os.path.join(ROOT, "assets/eq2_params.json"))
    eq = cfg["eq"]
    bridge = SimulatedBridge((eq["gain_param"], eq["freq_param"]))
    audio = SimulatedAudioCapture(bridge, mapping, sr=16000,
                                      gain_param=eq["gain_param"],
                                      freq_param=eq["freq_param"])
    session = SessionManager()
    agent = Agent(cfg, bridge, audio, FakePlanner(str(tmp_path)), session,
                  mapping)
    report = agent.run("make this lead brighter", objective_id="t-bright")
    assert report["status"] in ("success", "target_missed"), report["status"]
    assert report["n_evaluations"] == 30
    assert len(report["trajectory"]) == 30
    c0 = report["trajectory"][0]
    assert set(["candidate_id", "iteration", "audio_sha256", "sample_rate",
                "n_samples", "score"]).issubset(c0)
    assert c0["candidate_id"].startswith("t-bright")
    assert c0["iteration"] == 0
    if report["status"] == "success":
        # success now strictly means: best candidate is inside the interval
        assert report["best"] is not None
        b = report["best"]
        match = [c for c in report["trajectory"]
                 if c["candidate_id"] == b["candidate_id"]]
        assert match and match[0]["score"]["in_interval"]
        p = b["params"]
        assert -12 - 1e-6 <= p["gain_db"] <= 12 + 1e-6
        assert 200 - 1e-6 <= p["freq_hz"] <= 12000 + 1e-6


class FlakyAudio(SimulatedAudioCapture):
    """Fails the first capture to exercise exception bookkeeping."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._failed = False

    def capture_stable_loop(self, n, *a, **k):
        if not self._failed:
            self._failed = True
            raise RuntimeError("simulated capture glitch")
        return super().capture_stable_loop(n, *a, **k)


@pytest.mark.slow
def test_exception_recorded_not_dropped(tmp_path):
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config/agent_config.yaml"), encoding="utf-8"))
    cfg["audio"]["sample_rate"] = 16000
    mapping = ParamMapping(os.path.join(ROOT, "assets/eq2_params.json"))
    eq = cfg["eq"]
    bridge = SimulatedBridge((eq["gain_param"], eq["freq_param"]))
    audio = FlakyAudio(bridge, mapping, sr=16000,
                       gain_param=eq["gain_param"],
                       freq_param=eq["freq_param"])
    session = SessionManager()
    agent = Agent(cfg, bridge, audio, FakePlanner(str(tmp_path)), session,
                  mapping)
    report = agent.run("make this lead brighter", objective_id="t-flaky",
                       max_replans=0)
    # the glitch must appear as a recorded infeasible entry, not a crash
    assert report["n_evaluations"] == 30
    bad = [c for c in report["trajectory"] if not c["score"]["feasible"]]
    assert len(bad) == 1
    assert bad[0]["stable"] is False
    assert any("exception" in v for v in bad[0]["score"]["violations"])
    assert report["status"] in ("success", "target_missed")


class UnreachablePlanner(FakePlanner):
    """Returns target intervals no audio can reach."""

    def plan(self, instruction, baseline_features, objective_id, mode="full",
             history=None, accepted_params=None, plugin_limits=None):
        cfg = super().plan(instruction, baseline_features, objective_id,
                           mode, history, accepted_params, plugin_limits)
        cfg["target_intervals"] = {"spectral_centroid": [20000.0, 21000.0]}
        cfg["dsp_weights"] = {"spectral_centroid": 1.0}
        return cfg


@pytest.mark.slow
def test_replan_on_target_missed(tmp_path):
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config/agent_config.yaml"), encoding="utf-8"))
    cfg["audio"]["sample_rate"] = 16000
    mapping = ParamMapping(os.path.join(ROOT, "assets/eq2_params.json"))
    eq = cfg["eq"]
    bridge = SimulatedBridge((eq["gain_param"], eq["freq_param"]))
    audio = SimulatedAudioCapture(bridge, mapping, sr=16000,
                                      gain_param=eq["gain_param"],
                                      freq_param=eq["freq_param"])
    session = SessionManager()
    agent = Agent(cfg, bridge, audio, UnreachablePlanner(str(tmp_path)),
                  session, mapping)
    report = agent.run("make this lead brighter", objective_id="t-replan",
                       max_replans=1)
    assert report["status"] == "target_missed"
    assert report["n_rounds"] == 2
    # objective ids differ per round; scores never mixed
    assert report["objective_id"] == "t-replan-r2"
    assert all(c["candidate_id"].startswith("t-replan-r2#")
               for c in report["trajectory"])


class BadConfigPlanner(FakePlanner):
    """Returns an invalid config (empty intervals) to exercise tool_error."""

    def plan(self, instruction, baseline_features, objective_id, mode="full",
             history=None, accepted_params=None, plugin_limits=None):
        cfg = super().plan(instruction, baseline_features, objective_id,
                           mode, history, accepted_params, plugin_limits)
        cfg["target_intervals"] = {}
        cfg["dsp_weights"] = {}
        return cfg


@pytest.mark.slow
def test_invalid_planner_config_is_tool_error(tmp_path):
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config/agent_config.yaml"),
                              encoding="utf-8"))
    cfg["audio"]["sample_rate"] = 16000
    mapping = ParamMapping(os.path.join(ROOT, "assets/eq2_params.json"))
    eq = cfg["eq"]
    bridge = SimulatedBridge((eq["gain_param"], eq["freq_param"]))
    audio = SimulatedAudioCapture(bridge, mapping, sr=16000,
                                      gain_param=eq["gain_param"],
                                      freq_param=eq["freq_param"])
    session = SessionManager()
    agent = Agent(cfg, bridge, audio, BadConfigPlanner(str(tmp_path)),
                  session, mapping)
    report = agent.run("make this lead brighter", objective_id="t-badcfg",
                       max_replans=0)
    # must map to the five-state machine, never raise raw
    assert report["status"] == "tool_error"
    assert "planning failed" in report["reason"]
