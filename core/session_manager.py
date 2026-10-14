"""Three-state session management: original / accepted / candidate (v4.3).

- original: snapshot at task start (params + reference features), never overwritten
- accepted: user-confirmed params, the live state; rollback target
- candidate: best candidate of the current round, awaiting user confirmation
"""
import json
import os
import time


class SessionManager:
    def __init__(self, path=None):
        self.path = path
        self.original = None
        self.accepted = None
        self.candidate = None

    # ---- state transitions -------------------------------------------------
    def begin_task(self, params, reference_features=None, objective_id=None):
        snap = {"params": dict(params),
                # NOTE: reference_features may be a numpy array (raw baseline
                # audio) — `or` would raise "truth value of an array is
                # ambiguous", so test for None explicitly.
                "reference_features": (reference_features
                                       if reference_features is not None else {}),
                "objective_id": objective_id,
                "timestamp": time.time()}
        self.original = dict(snap)
        self.accepted = dict(snap)
        self.candidate = None
        self._save()

    def propose_candidate(self, params, candidate_id, score_summary):
        self.candidate = {"params": dict(params),
                          "candidate_id": candidate_id,
                          "score_summary": score_summary,
                          "timestamp": time.time()}
        self._save()
        return self.candidate

    def confirm_candidate(self):
        """User accepted the candidate after listening."""
        if self.candidate is None:
            raise RuntimeError("no candidate to confirm")
        self.accepted = {"params": dict(self.candidate["params"]),
                         "candidate_id": self.candidate["candidate_id"],
                         "timestamp": time.time()}
        self.candidate = None
        self._save()
        return self.accepted

    def discard_candidate(self):
        self.candidate = None
        self._save()

    def rollback(self):
        """Return params to roll the plugin back to.

        Prefers the accepted (user-confirmed) state; falls back to the
        original pre-optimization snapshot recorded by begin_task() when
        nothing was ever confirmed (e.g. rollback right after optimize
        without confirm). Only raises when no state was recorded at all.
        """
        self.candidate = None
        self._save()
        target = self.accepted if self.accepted is not None else self.original
        if target is None:
            raise RuntimeError(
                "no recorded state to roll back to "
                "(no optimize has run in this session)")
        return dict(target["params"])

    # ---- persistence --------------------------------------------------------
    def _save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"original": self.original,
                       "accepted": self.accepted,
                       "candidate": self.candidate}, f, indent=2)

    def load(self):
        with open(self.path, "r", encoding="utf-8") as f:
            d = json.load(f)
        self.original, self.accepted, self.candidate = \
            d.get("original"), d.get("accepted"), d.get("candidate")
        return self
