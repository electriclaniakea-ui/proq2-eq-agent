"""Config-driven DSP critic (v4.3).

- selects dimensions per LLM config (honoring failure conditions is the
  planner's job; the critic trusts but verifies ranges)
- scores by distance to TARGET INTERVALS (inside interval = perfect,
  no extra reward beyond it -> optimizer cannot game the metric)
- hard constraints first: infeasible candidates never enter ranking
- minimal-intervention selection among qualified candidates
"""
import math
import numpy as np
from . import dsp_features as dsp


def _any_nan_inf(a):
    return bool(np.isnan(a).any() or np.isinf(a).any())


class Critic:
    def __init__(self, config, baseline_bands=None):
        """config: dict with target_intervals {dim: [lo, hi]},
        dsp_scores {dim: 0-10} (preferred) or dsp_weights {dim: w} (legacy),
        hard_constraints {peak_ceiling, min_rms},
        band_targets [{label, hz: [lo, hi], delta_db, tolerance_db}] (optional).

        baseline_bands: dict {label: energy_db} from baseline audio, used
        to compute deltas for band_targets scoring.
        """
        self.target_intervals = dict(config.get("target_intervals", {}))
        # Prefer dsp_scores (0-10 relevance); fall back to legacy dsp_weights
        scores = config.get("dsp_scores")
        if scores:
            self.weights = self._scores_to_weights(scores)
        else:
            self.weights = dict(config.get("dsp_weights", {}))
        hc = config.get("hard_constraints", {})
        self.peak_ceiling = float(hc.get("peak_ceiling", 0.999))
        self.min_rms = float(hc.get("min_rms", 1e-6))
        # Band targets: primary optimization goals (delta dB from baseline)
        self.band_targets = list(config.get("band_targets", []))
        self.baseline_bands = dict(baseline_bands or {})
        # Band target weights: each band target has equal weight by default,
        # or use "weight" key if provided
        self.band_weights = {}
        for bt in self.band_targets:
            label = bt["label"]
            self.band_weights[label] = float(bt.get("weight", 1.0))
        # Normalize band weights
        bw_total = sum(self.band_weights.values())
        if bw_total > 0:
            self.band_weights = {k: v / bw_total
                                 for k, v in self.band_weights.items()}
        if not self.target_intervals and not self.band_targets:
            raise ValueError("critic needs at least one target interval or band target")
        # normalize weights (for guardrail dims)
        total = sum(self.weights.get(d, 0.0) for d in self.target_intervals)
        if self.target_intervals and total <= 0:
            raise ValueError("dsp weights must be positive")
        if total > 0:
            self.weights = {d: self.weights.get(d, 0.0) / total
                            for d in self.target_intervals}

    @staticmethod
    def _scores_to_weights(scores, threshold=3.0):
        """Convert 0-10 relevance scores to normalized weights.
        Scores < threshold are zeroed; rest are L1-normalized."""
        filtered = {d: max(0.0, float(s)) for d, s in scores.items()
                    if float(s) >= threshold}
        total = sum(filtered.values())
        if total <= 0:
            # All scores below threshold: fall back to uniform over
            # the highest-scored dimension(s) to avoid crash
            if not scores:
                raise ValueError("dsp_scores is empty")
            max_s = max(float(s) for s in scores.values())
            top = [d for d, s in scores.items() if float(s) == max_s]
            return {d: 1.0 / len(top) for d in top}
        return {d: s / total for d, s in filtered.items()}

    def _interval_distance(self, dim, value):
        lo, hi = self.target_intervals[dim]
        _, (tlo, thi) = dsp.FEATURE_INFO[dim][:2]
        width = max(thi - tlo, 1e-12)
        if value < lo:
            return (lo - value) / width
        if value > hi:
            return (value - hi) / width
        return 0.0

    def check_hard_constraints(self, audio, expected_samples=None):
        """Return list of violated constraint names (empty = feasible)."""
        a = dsp._to_mono(audio)
        bad = []
        if a.size == 0 or _any_nan_inf(a):
            bad.append("invalid_audio")
        elif float((a ** 2).mean()) < self.min_rms ** 2:
            bad.append("silent")
        if float(np.abs(a).max(initial=0.0)) >= self.peak_ceiling:
            bad.append("clipping")
        if expected_samples and abs(a.size - expected_samples) > 64:
            bad.append("length_mismatch")
        return bad

    def score(self, audio, sr, expected_samples=None, clap_score=None,
              clap_weight=0.0):
        """Return dict(final_score, feasible, details, violations).

        final_score is maximized by the optimizer: 0.0 = perfect
        (all dims inside their intervals), negative otherwise.

        clap_score: cosine similarity (0-1) from CLAP, or None if unavailable.
        clap_weight: 0.0-1.0, blend ratio. final = (1-w)*dsp + w*clap_dist
        where clap_dist = -(1 - cosine) so both terms are <= 0.
        """
        violations = self.check_hard_constraints(audio, expected_samples)
        details = {}
        band_details = {}
        if not violations:
            # Guardrail dims (global intervals)
            if self.target_intervals:
                feats = dsp.all_features(audio, sr, dims=self.target_intervals)
                for dim, v in feats.items():
                    d = self._interval_distance(dim, v)
                    details[dim] = {"value": v, "distance": d,
                                    "weight": self.weights[dim]}
            # Band targets (primary goals): delta dB from baseline
            if self.band_targets:
                band_energies = dsp.band_energies(audio, sr)
                for bt in self.band_targets:
                    label = bt["label"]
                    target_delta = float(bt["delta_db"])
                    tolerance = float(bt.get("tolerance_db", 1.5))
                    base_energy = self.baseline_bands.get(label, 0.0)
                    curr_energy = band_energies.get(label, -120.0)
                    actual_delta = curr_energy - base_energy
                    # Distance: 0 if within tolerance, else excess / range
                    excess = abs(actual_delta - target_delta) - tolerance
                    dist = max(0.0, excess) / 12.0  # normalize by 12dB range
                    band_details[label] = {
                        "target_delta_db": target_delta,
                        "actual_delta_db": actual_delta,
                        "distance": dist,
                        "weight": self.band_weights[label],
                    }
        # Combined penalty: band targets (primary) + guardrails
        dsp_penalty = sum(details[d]["distance"] * details[d]["weight"]
                          for d in details)
        band_penalty = sum(band_details[b]["distance"] * band_details[b]["weight"]
                           for b in band_details)
        # Band targets get 70% weight, guardrails 30% (if both present)
        if band_details and details:
            total_penalty = 0.7 * band_penalty + 0.3 * dsp_penalty
        elif band_details:
            total_penalty = band_penalty
        else:
            total_penalty = dsp_penalty
        dsp_score = -total_penalty if not violations else float("-inf")
        # Blend with CLAP if available and weighted
        final_score = dsp_score
        clap_dist = None
        effective_w = 0.0
        if clap_score is not None and clap_weight > 0 and not violations:
            # cosine [0,1] -> distance (-1,0]: 0 = perfect match
            clap_dist = -(1.0 - max(0.0, min(1.0, float(clap_score))))
            effective_w = float(clap_weight)
            final_score = (1.0 - effective_w) * dsp_score + \
                          effective_w * clap_dist
        in_interval = all(details[d]["distance"] == 0.0 for d in details)
        in_band_target = all(band_details[b]["distance"] == 0.0
                             for b in band_details)
        return {
            "final_score": final_score,
            "feasible": not violations,
            "in_interval": in_interval and not violations,
            "in_band_target": in_band_target and not violations,
            "details": details,
            "band_details": band_details,
            "violations": violations,
            "dsp_score": dsp_score,
            "clap_score": clap_score,
            "clap_weight": effective_w,
            "clap_dist": clap_dist,
        }

    @staticmethod
    def param_change(p_new, p_base):
        """Sum of |dGain| + |d log freq| over all control params —
        minimal-intervention metric. Freq keys (freq_bN, freq_hz) are
        compared in log space."""
        total = 0.0
        for k in p_new:
            if k not in p_base:
                continue
            v_new, v_base = p_new[k], p_base[k]
            # Freq params: compare in log space
            if k.startswith("freq"):
                total += abs(math.log(max(v_new, 1e-6))
                             - math.log(max(v_base, 1e-6)))
            else:
                total += abs(v_new - v_base)
        return total

    def select_best(self, candidates, base_params):
        """candidates: list of dicts with keys params, score (from .score()),
        candidate_id. Returns the best candidate dict or None.

        Rule: feasible first, then in-interval preferred, then minimal
        total distance, then minimal param change (v4.2 minimal intervention).
        """
        feas = [c for c in candidates if c["score"]["feasible"]]
        if not feas:
            return None
        in_iv = [c for c in feas if c["score"]["in_interval"]] or feas
        def key(c):
            dist = -c["score"]["final_score"]  # >= 0
            chg = self.param_change(c["params"], base_params)
            return (dist, chg)
        return min(in_iv, key=key)
