"""Trajectory visualization (v4.3): parameter scatter + convergence curve."""
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_trajectory(trajectory, bounds, out_path):
    """Parameter trajectory. For 2D (single_band): freq (log x) vs gain (y).
    For ND (multi-band): one subplot per band with gain+freq, or gain-only
    bands plotted as gain vs iteration."""
    import re
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    feas = [c for c in trajectory if c["score"]["feasible"]]
    if not feas:
        return None
    # Group params by band: gain_bN <-> freq_bN, or legacy gain/log_freq.
    sample = feas[0]["params"]
    bands = {}  # band_id -> {"gain": key, "freq": key or None}
    for k in sample:
        m = re.match(r"^(gain|freq)_b(\d+)$", k)
        if m:
            kind, bid = m.group(1), m.group(2)
            bands.setdefault(bid, {})[kind] = k
        elif k in ("gain", "log_freq", "gain_db", "freq_hz"):
            # Legacy 2-param format
            bands.setdefault("2", {})["gain" if "gain" in k else "freq"] = k
    if not bands:
        return None
    n = len(bands)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 4.5), squeeze=False)
    axes = axes[0]
    order = list(range(len(feas)))
    for ax, (bid, keys) in zip(axes, sorted(bands.items())):
        gkey, fkey = keys.get("gain"), keys.get("freq")
        if gkey and fkey:
            # freq values are already in Hz (human units)
            xs = [c["params"][fkey] for c in feas]
            ys = [c["params"][gkey] for c in feas]
            sc = ax.scatter(xs, ys, c=order, cmap="viridis", s=40, alpha=0.8)
            best = max(feas, key=lambda c: c["score"]["final_score"])
            ax.scatter([best["params"][fkey]], [best["params"][gkey]],
                       marker="*", s=220, c="red", label="best")
            ax.set_xscale("log")
            ax.set_xlabel("Freq (Hz, log)")
            ax.set_ylabel("Gain (dB)")
            ax.set_title("Band %s" % bid)
            ax.legend()
        elif gkey:
            ys = [c["params"][gkey] for c in feas]
            ax.plot(order, ys, ".", alpha=0.6)
            ax.set_xlabel("iteration")
            ax.set_ylabel("Gain (dB)")
            ax.set_title("Band %s gain" % bid)
    fig.suptitle("Parameter trajectory")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def plot_convergence(trajectory, out_path):
    """Convergence curve over feasible candidates only."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    feas = [c for c in trajectory if c["score"]["feasible"]]
    if not feas:
        return None
    ys = [c["score"]["final_score"] for c in feas]
    best_so_far, curve = float("-inf"), []
    for y in ys:
        best_so_far = max(best_so_far, y)
        curve.append(best_so_far)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(range(len(ys)), ys, ".", alpha=0.5, label="per-iteration")
    ax.plot(range(len(curve)), curve, "-", label="best so far")
    ax.axhline(0.0, ls="--", c="gray", label="target interval reached")
    ax.set_xlabel("iteration")
    ax.set_ylabel("DSP score (0 = in interval)")
    ax.set_title("Convergence")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path
