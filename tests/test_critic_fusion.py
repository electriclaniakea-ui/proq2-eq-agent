"""Unit tests: critic fusion, intervals, hard constraints, selection."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.critic import Critic
from core import dsp_features as dsp

SR = 48000


def _tone(freq=440, dur=1.0, amp=0.4):
    t = np.arange(int(SR * dur)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def _cfg():
    return {
        "target_intervals": {"spectral_centroid": [300.0, 600.0],
                             "spectral_flatness": [0.0, 0.2]},
        "dsp_weights": {"spectral_centroid": 0.7, "spectral_flatness": 0.3},
        "hard_constraints": {"peak_ceiling": 0.999, "min_rms": 1e-6},
    }


def test_in_interval_scores_zero():
    c = Critic(_cfg())
    sc = c.score(_tone(440), SR)
    assert sc["feasible"] and sc["in_interval"], sc
    assert sc["final_score"] == 0.0


def test_out_of_interval_negative():
    c = Critic(_cfg())
    sc = c.score(_tone(4000), SR)  # centroid way above interval
    assert sc["feasible"] and not sc["in_interval"]
    assert sc["final_score"] < 0.0


def test_clipping_infeasible():
    c = Critic(_cfg())
    sc = c.score(_tone(440, amp=1.5), SR)  # peak > ceiling
    assert not sc["feasible"] and "clipping" in sc["violations"]
    assert sc["final_score"] == float("-inf")


def test_silent_infeasible():
    c = Critic(_cfg())
    sc = c.score(np.zeros(SR), SR)
    assert not sc["feasible"] and "silent" in sc["violations"]


def test_length_mismatch_infeasible():
    c = Critic(_cfg())
    sc = c.score(_tone(440, dur=1.0), SR, expected_samples=SR // 2)
    assert not sc["feasible"] and "length_mismatch" in sc["violations"]
    sc2 = c.score(_tone(440, dur=1.0), SR, expected_samples=SR)
    assert sc2["feasible"]


def test_no_extra_reward_inside_interval():
    # deeper inside the interval must NOT score higher than just inside
    c = Critic(_cfg())
    s1 = c.score(_tone(440), SR)["final_score"]
    s2 = c.score(_tone(500), SR)["final_score"]
    assert s1 == s2 == 0.0


def test_minimal_intervention_selection():
    c = Critic(_cfg())
    base = {"gain_db": 0.0, "freq_hz": 1000.0}
    mk = lambda g, f, fs: {"params": {"gain_db": g, "freq_hz": f},
                           "score": {"feasible": True, "in_interval": True,
                                     "final_score": fs},
                           "candidate_id": "x"}
    # both perfect scores; smaller param change must win
    cands = [mk(10.0, 8000.0, 0.0), mk(2.0, 1200.0, 0.0)]
    best = c.select_best(cands, base)
    assert best["params"]["gain_db"] == 2.0
    # infeasible candidates never win
    cands2 = [{"params": {"gain_db": 0, "freq_hz": 1000},
               "score": {"feasible": False, "in_interval": False,
                         "final_score": float("-inf")},
               "candidate_id": "y"}]
    assert c.select_best(cands2, base) is None


def test_dsp_scores_to_weights():
    """LLM 0-10 scores -> threshold + L1 normalization."""
    from core.critic import Critic
    # 9, 7, 4 pass threshold; 2, 1 are zeroed
    w = Critic._scores_to_weights({
        "spectral_centroid": 9,
        "spectral_rolloff": 7,
        "spectral_flatness": 4,
        "spectral_bandwidth": 2,
        "harmonic_ratio": 1,
    })
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert "spectral_bandwidth" not in w
    assert "harmonic_ratio" not in w
    # 9+7+4=20 -> 0.45, 0.35, 0.20
    assert abs(w["spectral_centroid"] - 0.45) < 1e-9
    assert abs(w["spectral_rolloff"] - 0.35) < 1e-9
    assert abs(w["spectral_flatness"] - 0.20) < 1e-9


def test_dsp_scores_all_below_threshold():
    """All scores <3: fall back to top-scored dimension."""
    from core.critic import Critic
    w = Critic._scores_to_weights({
        "spectral_centroid": 2,
        "spectral_flatness": 2,
    })
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert len(w) == 2  # tie -> uniform


def test_critic_prefers_scores_over_weights():
    """Critic uses dsp_scores when present, ignores legacy dsp_weights."""
    from core.critic import Critic
    cfg = {
        "target_intervals": {
            "spectral_centroid": [2000, 4000],
            "spectral_flatness": [0.0, 0.3],
        },
        "dsp_scores": {"spectral_centroid": 9, "spectral_flatness": 3},
        "dsp_weights": {"spectral_centroid": 0.1, "spectral_flatness": 0.9},
        "hard_constraints": {},
    }
    c = Critic(cfg)
    # scores 9,3 -> 0.75, 0.25 (not the legacy 0.1, 0.9)
    assert abs(c.weights["spectral_centroid"] - 0.75) < 1e-9
    assert abs(c.weights["spectral_flatness"] - 0.25) < 1e-9
