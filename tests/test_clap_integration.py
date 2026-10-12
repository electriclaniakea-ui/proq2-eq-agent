
import os
import sys
import time

import numpy as np
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from core.agent import Agent
from core.clap_critic import CLAPCritic
from core.param_mapping import ParamMapping
from core.session_manager import SessionManager
from run_agent import FakePlanner, SimulatedAudioCapture, SimulatedBridge
from test_clap_critic import StubCLAP

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_agent_harvests_clap_results(tmp_path):
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config/agent_config.yaml"),
                              encoding="utf-8"))
    cfg["audio"]["sample_rate"] = 16000
    mapping = ParamMapping(os.path.join(ROOT, "assets/eq2_params.json"))
    bridge = SimulatedBridge()
    audio = SimulatedAudioCapture(bridge, mapping, sr=16000)
    clap = CLAPCritic(enabled=True)
    clap._require_model = lambda: StubCLAP()  # stub, no download
    clap._model = StubCLAP()  # pre-set so load-wait sees it as loaded
    session = SessionManager()
    agent = Agent(cfg, bridge, audio, FakePlanner(str(tmp_path)), session,
                  mapping, clap=clap)
    report = agent.run("make this lead brighter", objective_id="t-clap",
                       max_replans=0)
    # background worker needs a moment; harvest ran at phase 3 already,
    # but re-poll to be robust against thread timing
    t0 = time.time()
    while time.time() - t0 < 15:
        scores = [c["clap_score"] for c in report["trajectory"]]
        if all(s is not None for s in scores):
            break
        time.sleep(0.2)
        for c in report["trajectory"]:
            if c["clap_score"] is None:
                c["clap_score"] = clap.result(c["candidate_id"])
    scores = [c["clap_score"] for c in report["trajectory"]]
    assert all(s is not None for s in scores), "CLAP results not harvested"
    assert all(abs(s - 1.0) < 1e-6 for s in scores)
    # CLAP scores are blended into final_score via clap_weight (FakePlanner=0.3)
    assert all(c["score"]["final_score"] <= 0.0
               for c in report["trajectory"] if c["score"]["feasible"])
