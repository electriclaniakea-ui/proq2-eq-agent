"""Unit tests: bayesian_optimizer finds the optimum of a synthetic fn."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.bayesian_optimizer import BayesianSearcher


def test_finds_maximum():
    # optimum at gain=6, log_freq=log(3000)
    target_logf = math.log(3000)
    def fn(p):
        return -((p["gain"] - 6) ** 2) - ((p["log_freq"] - target_logf) ** 2)
    s = BayesianSearcher({"gain": (-12, 12),
                          "log_freq": (math.log(200), math.log(12000))},
                         seed=42, init_points=5, n_iter=10)
    best, traj = s.run(fn)
    assert len(traj) == 15
    assert abs(best["gain"] - 6) < 2.5, best
    assert abs(BayesianSearcher.expand_log_freq(best["log_freq"]) - 3000) < 1500


def test_handles_inf_gracefully():
    def fn(p):
        return float("-inf") if p["gain"] > 0 else -p["gain"] ** 2
    s = BayesianSearcher({"gain": (-5, 5),
                          "log_freq": (math.log(200), math.log(1000))},
                         seed=7, init_points=3, n_iter=5)
    best, traj = s.run(fn)
    assert len(traj) == 8
    assert best["gain"] <= 0.5
