"""Unit tests: session_manager three-state transitions."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.session_manager import SessionManager


def test_full_lifecycle():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    sm = SessionManager(path)
    sm.begin_task({"gain_db": 0, "freq_hz": 1000}, objective_id="o1")
    assert sm.accepted["params"]["gain_db"] == 0
    sm.propose_candidate({"gain_db": 4, "freq_hz": 3000}, "o1#7",
                         {"final_score": 0.0})
    assert sm.candidate["candidate_id"] == "o1#7"
    # rollback returns ACCEPTED, not candidate
    rb = sm.rollback()
    assert rb == {"gain_db": 0, "freq_hz": 1000}
    assert sm.candidate is None
    # propose again + confirm
    sm.propose_candidate({"gain_db": 4, "freq_hz": 3000}, "o1#9",
                         {"final_score": 0.0})
    sm.confirm_candidate()
    assert sm.accepted["params"]["gain_db"] == 4
    # persistence round-trip
    sm2 = SessionManager(path).load()
    assert sm2.accepted["params"]["freq_hz"] == 3000
    assert sm2.original["objective_id"] == "o1"
