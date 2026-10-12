"""Bayesian optimization wrapper (v4.3).

Suggest/register loop so every evaluation can be logged with its
candidate_id. Frequency is searched in LOG space (equal sampling density
per octave); use log_freq bounds and convert back with expand_log_freq().

Requires bayesian-optimization >= 3.0 (3.x acquisition API).
"""
import math
import random

from bayes_opt import BayesianOptimization
from bayes_opt.acquisition import UpperConfidenceBound


class BayesianSearcher:
    def __init__(self, pbounds, seed=42, init_points=5, n_iter=10,
                 kappa=2.576, kappa_decay=0.95):
        """pbounds: {"gain": (lo, hi), "log_freq": (lo, hi)} (natural log)."""
        self.pbounds = dict(pbounds)
        self.seed = seed
        self.init_points = init_points
        self.n_iter = n_iter
        random.seed(seed)
        acq = UpperConfidenceBound(
            kappa=kappa, exploration_decay=kappa_decay,
            exploration_decay_delay=0)
        self.opt = BayesianOptimization(
            f=None, pbounds=self.pbounds, acquisition_function=acq,
            random_state=seed, verbose=0, allow_duplicate_points=True)
        self._random_done = 0

    @staticmethod
    def expand_log_freq(log_freq):
        return math.exp(log_freq)

    def run(self, objective):
        """objective(params_dict) -> float. Runs init_points random +
        n_iter optimization steps. Returns (best_params, trajectory)."""
        trajectory = []
        total = self.init_points + self.n_iter
        for i in range(total):
            if self._random_done < self.init_points:
                params = {k: random.uniform(lo, hi)
                          for k, (lo, hi) in self.pbounds.items()}
                self._random_done += 1
            else:
                params = self.opt.suggest()
            try:
                target = float(objective(dict(params)))
            except Exception:
                target = float("-inf")
            if not math.isfinite(target):
                target = -1e12  # GP cannot fit inf; use a large finite penalty
            self.opt.register(params=params, target=target)
            trajectory.append({"iteration": i, "params": dict(params),
                               "target": target})
        best = self.opt.max
        return (dict(best["params"]) if best else {}), trajectory
