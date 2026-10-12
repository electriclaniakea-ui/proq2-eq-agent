"""Agent orchestration: the single entry point (v4.3).

Phase 1 (LLM planning, once) -> Phase 2 (Bayesian loop, 15 iters, no LLM)
-> Phase 3 (LLM re-plan once if target missed, with a FRESH objective_id;
scores are never mixed across objective ids). Owns the three-state session
(original / accepted / candidate) and the four-state diagnostic report
(execution ok / optimization stable / target reached / user accepted).
"""
import hashlib
import math
import time

import numpy as np

from . import dsp_features as dsp
from .bayesian_optimizer import BayesianSearcher
from .critic import Critic


def _sha256(audio):
    return hashlib.sha256(np.ascontiguousarray(audio).tobytes()).hexdigest()


class Agent:
    def __init__(self, config, bridge, audio, planner, session,
                 param_mapping, clap=None, gain_param=None,
                 freq_param=None):
        self.cfg = config
        self.bridge = bridge
        self.audio = audio
        self.planner = planner
        self.session = session
        self.mapping = param_mapping
        self.clap = clap
        eq = config.get("eq", {})
        self.gain_param = gain_param or eq.get("gain_param", "Band 2 Gain")
        self.freq_param = freq_param or eq.get("freq_param",
                                               "Band 2 Frequency")
        # Multi-band: build the full control param list from search_mode.
        # Each entry: key, name, index, kind, human_bounds.
        from core.param_mapping import build_control_params
        self.control_params = build_control_params(eq)
        self.sr = config["audio"]["sample_rate"]
        self.beats = config["pattern"]["beats"]
        t = config["timing"]
        self.stab_thr = t["stability_threshold"]
        self.stab_pct = t["stability_percentile"]
        self.timeout_s = t["capture_timeout_s"]
        self.max_anom = t["max_consecutive_anomalies"]

    # ---- helpers ---------------------------------------------------------
    def _loop_samples(self):
        bpm = self.bridge.get_tempo()
        # Prefer actual pattern/song length from FL; fall back to config beats.
        beats = self.beats
        try:
            plen = self.bridge.get_song_length_beats()
            if plen and plen > 0:
                beats = float(plen)
        except Exception:
            pass
        return int(self.sr * 60.0 / bpm * beats)

    def _read_eq_human(self):
        # Read all control params, return {key: human_value}
        result = {}
        for cp in self.control_params:
            norm = self.bridge.get_param(cp["name"])
            human = self.mapping.to_human(norm, cp["name"])
            result[cp["key"]] = human
        return result

    def _write_eq_human(self, params):
        """Write human-unit params to FL. params: {human_key: human_value}.

        human_key is like "gain_b1" (dB) or "freq_b1" (Hz).
        """
        for cp in self.control_params:
            # Map control key (log_freq_b1) to human key (freq_b1)
            ckey = cp["key"]
            hkey = ckey.replace("log_freq_", "freq_") if ckey.startswith("log_") else ckey
            if hkey not in params:
                continue
            human_val = params[hkey]
            norm_val = self.mapping.to_norm(human_val, cp["name"])
            self.bridge.set_param_verified(cp["name"], norm_val)
        # Output-gain reset (experimental control, 5.5): ONLY when the
        # calibrated unity value is configured; never assume 0.5 == 0 dB.
        eq_cfg = self.cfg.get("eq", {})
        og_param = eq_cfg.get("output_gain_param")
        og_unity = eq_cfg.get("output_gain_unity_norm")
        if og_param and og_unity is not None:
            try:
                self.bridge.set_param_verified(og_param, float(og_unity))
            except Exception:
                pass

    def _plugin_limits(self):
        # {key: [min, max]} in human units, for all control params
        limits = {}
        for cp in self.control_params:
            e = self.mapping._entry(cp["name"])
            limits[cp["key"]] = [e["min"], e["max"]]
        return limits

    def _capture_baseline(self):
        """Capture stable baseline DSP features.

        Returns (features_dict, stable_bool). The features are averaged
        over the stable period (or timeout fallback). Silence is rejected
        inside capture_stable_loop.
        """
        n = self._loop_samples()
        features, stable = self.audio.capture_stable_loop(
            n, threshold=self.stab_thr, percentile=self.stab_pct,
            timeout_s=self.timeout_s,
            max_anomalies=self.cfg["timing"]["max_consecutive_anomalies"])
        return features, stable

    def _check_divergence(self, trajectory, clap_weight):
        """Detect DSP/CLAP divergence. Returns (effective_weight, diverged).

        Tracks Pearson correlation of (dsp_score, clap_dist) over recent
        candidates. If correlation < threshold, halves the weight (dampening).
        """
        if clap_weight <= 0:
            return clap_weight, False
        cfg = self.cfg.get("clap", {})
        window = cfg.get("divergence_window", 10)
        threshold = cfg.get("divergence_threshold", 0.3)
        min_w = cfg.get("divergence_min_weight", 0.05)
        # Collect recent pairs with both scores
        pairs = []
        for c in trajectory[-window:]:
            sc = c.get("score", {})
            dsp = sc.get("dsp_score")
            clap_d = sc.get("clap_dist")
            if dsp is not None and clap_d is not None and dsp > float("-inf"):
                pairs.append((dsp, clap_d))
        if len(pairs) < 4:  # need minimum samples
            return clap_weight, False
        # Pearson correlation
        import math
        n = len(pairs)
        sx = sum(p[0] for p in pairs)
        sy = sum(p[1] for p in pairs)
        sxx = sum(p[0] * p[0] for p in pairs)
        syy = sum(p[1] * p[1] for p in pairs)
        sxy = sum(p[0] * p[1] for p in pairs)
        denom = math.sqrt(max((n * sxx - sx * sx) * (n * syy - sy * sy), 0))
        if denom < 1e-9:
            return clap_weight, False  # no variance, can't tell
        corr = (n * sxy - sx * sy) / denom
        if corr < threshold:
            new_w = max(clap_weight * 0.5, min_w)
            return new_w, True
        return clap_weight, False

    def _make_searcher(self, cfg, bounds):
        s = self.cfg["search"]
        # Build ND pbounds from control_params. Freq dims are searched in
        # log space (key starts with "log_").
        pbounds = {}
        for cp in self.control_params:
            lo, hi = cp["human_bounds"]
            if cp["key"].startswith("log_"):
                pbounds[cp["key"]] = (math.log(lo), math.log(hi))
            else:
                pbounds[cp["key"]] = (lo, hi)
        return BayesianSearcher(pbounds, seed=cfg.get("seed", s["seed"]),
                                init_points=s["init_points"],
                                n_iter=s["n_iter"], kappa=s["kappa"],
                                kappa_decay=s["kappa_decay"])

    def _harvest_clap(self, trajectory):
        """Pull finished CLAP results into the trajectory (may lag/be None)."""
        if self.clap is None:
            return
        for c in trajectory:
            try:
                c["clap_score"] = self.clap.result(c["candidate_id"])
            except Exception:
                c["clap_score"] = None

    @staticmethod
    def _missed_summary(trajectory):
        feas = [c for c in trajectory if c["score"]["feasible"]]
        if not feas:
            return {"feasible": 0, "closest": None, "distances": {}}
        closest = max(feas, key=lambda c: c["score"]["final_score"])
        dists = {d: v["distance"] for d, v in
                 closest["score"]["details"].items() if v["distance"] > 0}
        return {"feasible": len(feas), "closest": closest["candidate_id"],
                "distances": dists}

    # ---- main ------------------------------------------------------------
    def run(self, instruction, history=None, mode="full", objective_id=None,
            max_replans=1):
        base_id = objective_id or ("obj-%s" % time.strftime("%Y%m%d-%H%M%S"))
        t0 = time.time()
        history = list(history or [])
        n_loop = self._loop_samples()
        # CLAP runtime event log (for error taxonomy + LLM replanning)
        # Events: clap_load_timeout, clap_score_missing, clap_divergence
        clap_events = []

        # ---- Phase 1 (once): snapshot + baseline -------------------------
        # A transient capture glitch is recorded as an infeasible
        # trajectory entry (same schema as the BO loop's exception
        # entries, so the exception is never silently dropped) and the
        # baseline is retried once. Only a persistent failure becomes
        # tool_error. The recorded entry counts toward the evaluation
        # budget so n_evaluations stays truthful.
        preface = []
        try:
            base_params = self._read_eq_human()
            baseline, stable = self._capture_baseline()
        except Exception as e:  # noqa: BLE001 -> record, then retry once
            preface.append({
                "candidate_id": "%s#baseline" % base_id, "iteration": 0,
                "params": {}, "audio_sha256": None,
                "sample_rate": self.sr, "n_samples": 0,
                "score": {"final_score": float("-inf"),
                          "feasible": False, "in_interval": False,
                          "details": {},
                          "violations": ["exception: %s" % e]},
                "clap_score": None, "stable": False,
            })
            try:
                base_params = self._read_eq_human()
                baseline, stable = self._capture_baseline()
            except Exception as e2:  # noqa: BLE001 -> tool_error state
                return self._report(base_id, "tool_error", instruction,
                                    "phase1 failed: %s" % e2, t0,
                                    trajectory=preface)
        self.session.begin_task(base_params, baseline, base_id)

        # CLAP startup is deferred until after planning (when we know the
        # weight). If weight is 0, CLAP is never loaded. See inside the
        # replan loop below.
        self._clap_started = False
        self._clap_load_ok = False

        last_report, n_rounds = None, 0
        for rnd in range(max_replans + 1):
            n_rounds = rnd + 1
            oid = base_id if rnd == 0 else "%s-r%d" % (base_id, rnd + 1)
            try:
                cfg = self.planner.plan(
                    instruction=instruction, baseline_features=baseline,
                    objective_id=oid, mode=mode, history=history,
                    accepted_params=self.session.accepted["params"],
                    plugin_limits=self._plugin_limits())
                critic = Critic(cfg, baseline_bands={
                    k.replace("band_", ""): v
                    for k, v in baseline.items()
                    if k.startswith("band_")
                })  # validates intervals/weights
                bounds = cfg.get("search_bounds")  # optional; from calibration if absent
                searcher = self._make_searcher(cfg, bounds)
                if rnd == 0 and preface:
                    # The recorded glitch consumed one evaluation slot.
                    searcher.n_iter = max(0, searcher.n_iter - len(preface))
                clap_prompt = cfg.get("clap_prompt") or instruction
                # Use a mutable container so divergence detection can dampen it
                clap_w = [float(cfg.get("clap_weight", 0.0))]
                # Clamp to [0, 1]
                clap_w[0] = max(0.0, min(1.0, clap_w[0]))
                # If CLAP is disabled, force weight to 0
                if self.clap is None or not getattr(self.clap, "enabled", False):
                    clap_w[0] = 0.0
                # Deferred CLAP startup: only load if weight > 0 and not yet started
                if clap_w[0] > 0 and not self._clap_started:
                    self._clap_started = True
                    self.clap.start()
                    timeout = self.cfg.get("clap", {}).get("load_timeout_s", 90)
                    t0_wait = time.time()
                    loaded = False
                    while time.time() - t0_wait < timeout:
                        try:
                            if getattr(self.clap, "_model", None) is not None:
                                loaded = True
                                break
                        except Exception:
                            pass
                        time.sleep(1.0)
                    if not loaded:
                        print("[clap] load timeout after %ds, "
                              "falling back to DSP-only." % timeout,
                              file=sys.stderr)
                        clap_events.append({
                            "type": "clap_load_timeout",
                            "timeout_s": timeout,
                            "action": "dsp_only_fallback",
                        })
                    self._clap_load_ok = loaded
                elif not self._clap_started:
                    # Weight is 0, CLAP never loaded; force weight to 0
                    # (already 0, but ensure _clap_load_ok is False)
                    self._clap_load_ok = False
                # If CLAP failed to load, force weight to 0
                if not getattr(self, "_clap_load_ok", False):
                    clap_w[0] = 0.0
            except Exception as e:
                self._rollback()
                return self._report(oid, "tool_error", instruction,
                                    "planning failed: %s" % e, t0,
                                    n_rounds=n_rounds)
            if cfg.get("status") == "unsupported":
                return self._report(oid, "unsupported", instruction,
                                    cfg.get("unsupported_reason", ""), t0,
                                    n_rounds=n_rounds)

            bp = base_params
            if mode == "delta" and cfg.get("base_params"):
                bp = cfg["base_params"]
            # Round 0 inherits the phase-1 preface (recorded glitch, if any);
            # later rounds start clean ("scores never mixed across ids").
            trajectory, exec_ok = (list(preface), True) if rnd == 0 \
                else ([], True)

            # ---- Phase 2: Bayesian loop (no LLM) -------------------------
            def objective(p, _traj=trajectory, _critic=critic, _oid=oid,
                          _prompt=clap_prompt):
                # Convert optimizer params to human units for trajectory.
                # Keys use human naming: gain_bN (dB), freq_bN (Hz).
                # (Optimizer uses log_ prefix internally for freq.)
                params = {}
                for cp in self.control_params:
                    key = cp["key"]
                    v = float(p[key])
                    if key.startswith("log_"):
                        v = BayesianSearcher.expand_log_freq(v)
                        # Store under human key: log_freq_b1 -> freq_b1
                        human_key = key.replace("log_freq_", "freq_")
                    else:
                        human_key = key
                    params[human_key] = v
                cid = "%s#%d" % (_oid, len(_traj))
                try:
                    self._write_eq_human(params)
                    # Fast audio capture for BO loop (no stability check;
                    # stability is only for the initial baseline).
                    # capture_two_loops returns (old, new); use the newer.
                    _, loop = self.audio.capture_two_loops(
                        n_loop, timeout_s=self.timeout_s)
                    stable = True
                    # Submit to CLAP for async scoring (no-op if disabled)
                    clap_score = None
                    # Check divergence before scoring; dampen if needed
                    _eff_w, _div = self._check_divergence(_traj, clap_w[0])
                    if _div:
                        print("[clap] divergence detected (corr < threshold), "
                              "dampening weight %.2f -> %.2f" % (clap_w[0], _eff_w))
                        clap_events.append({
                            "type": "clap_divergence",
                            "old_weight": clap_w[0],
                            "new_weight": _eff_w,
                            "iteration": len(_traj),
                        })
                        clap_w[0] = _eff_w
                    if self.clap is not None and clap_w[0] > 0:
                        self.clap.submit(cid, loop, clap_prompt)
                        # Wait briefly for CLAP score (non-blocking fallback
                        # to DSP-only if CLAP is slow for this candidate)
                        clap_timeout = self.cfg.get("clap", {}).get(
                            "score_timeout_s", 3.0)
                        t0_clap = time.time()
                        while time.time() - t0_clap < clap_timeout:
                            clap_score = self.clap.result(cid)
                            if clap_score is not None:
                                break
                            time.sleep(0.1)
                        if clap_score is None:
                            clap_events.append({
                                "type": "clap_score_missing",
                                "candidate_id": cid,
                                "timeout_s": clap_timeout,
                                "action": "dsp_only_for_candidate",
                            })
                    sc = _critic.score(loop, self.sr,
                                       expected_samples=n_loop,
                                       clap_score=clap_score,
                                       clap_weight=clap_w[0])
                    _traj.append({
                        "candidate_id": cid, "iteration": len(_traj),
                        "params": params, "audio_sha256": _sha256(loop),
                        "sample_rate": self.sr, "n_samples": len(loop),
                        "score": sc, "clap_score": clap_score,
                        "stable": stable,
                    })
                    return sc["final_score"] if sc["feasible"] \
                        else float("-inf")
                except Exception as e:  # record, don't silently drop
                    _traj.append({
                        "candidate_id": cid, "iteration": len(_traj),
                        "params": params, "audio_sha256": None,
                        "sample_rate": self.sr, "n_samples": 0,
                        "score": {"final_score": float("-inf"),
                                  "feasible": False, "in_interval": False,
                                  "details": {},
                                  "violations": ["exception: %s" % e]},
                        "clap_score": None, "stable": False,
                    })
                    return float("-inf")

            try:
                searcher.run(objective)
            except Exception as e:
                exec_ok = False
                self._rollback()
                return self._report(oid, "tool_error", instruction, str(e),
                                    t0, trajectory=trajectory,
                                    n_rounds=n_rounds)

            # ---- Phase 3: harvest CLAP, evaluate, maybe re-plan ----------
            self._harvest_clap(trajectory)
            in_iv = [c for c in trajectory
                     if c["score"]["feasible"] and c["score"]["in_interval"]]
            opt_stable = len(in_iv) > 0
            best = critic.select_best(trajectory, bp)
            reached = best is not None and best["score"]["in_interval"]

            if reached:
                self.session.propose_candidate(
                    best["params"], best["candidate_id"],
                    {"final_score": best["score"]["final_score"]})
                # NOTE: candidate awaits USER listening confirmation;
                # accepted state only updates via session.confirm_candidate().
                last_report = self._report(
                    oid, "success", instruction, "", t0,
                    trajectory=trajectory, exec_ok=exec_ok,
                    opt_stable=opt_stable, best=best, search_bounds=bounds,
                    n_rounds=n_rounds)
                break

            missed = self._missed_summary(trajectory)
            history.append({"round": oid, "result": "target_missed",
                            "missed": missed,
                            "clap_events": clap_events})
            last_report = self._report(
                oid, "target_missed", instruction,
                "no candidate reached the target interval: %s" % missed,
                t0, trajectory=trajectory, exec_ok=exec_ok,
                opt_stable=opt_stable, best=None, search_bounds=bounds,
                n_rounds=n_rounds)
            if rnd < max_replans:
                continue  # fresh objective_id; scores never mixed across ids
            self._rollback()
            break
        return last_report

    # ---- helpers (cont.) ---------------------------------------------------
    def _rollback(self):
        try:
            params = self.session.rollback()
            # params is {key: human_value} from session
            self._write_eq_human(params)
        except Exception:
            pass

    def _report(self, objective_id, status, instruction, reason, t0,
                trajectory=None, exec_ok=True, opt_stable=False, best=None,
                search_bounds=None, n_rounds=1):
        trajectory = trajectory or []
        return {
            "objective_id": objective_id,
            "status": status,  # success | target_missed | unsupported |
                               # tool_error  (v4.2 five-state machine)
            "reason": reason,
            "instruction": instruction,
            "elapsed_s": round(time.time() - t0, 1),
            "n_evaluations": len(trajectory),
            "n_rounds": n_rounds,
            "search_bounds": search_bounds,
            "diagnostic": {
                # four states, reported separately (v4.2 D)
                "execution_ok": exec_ok,
                "optimization_stable": opt_stable,
                "target_reached": best is not None,
                "user_accepted": False,  # set by UI after listening
            },
            "best": ({
                "candidate_id": best["candidate_id"],
                "params": best["params"],
                "final_score": best["score"]["final_score"],
                "details": best["score"]["details"],
            } if best else None),
            "trajectory": trajectory,
        }
