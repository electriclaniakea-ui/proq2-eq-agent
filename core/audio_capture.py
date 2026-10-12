"""Real-time audio capture via VB-Cable + sounddevice (v4.3).

FL Studio outputs to the "CABLE Input" device; Python records from
"CABLE Output". A lock-protected ring buffer holds ~10 s of audio.
sounddevice is imported LAZILY so the rest of the project (unit tests)
works without audio hardware or PortAudio installed.

Stability detection (7.4): capture two consecutive loops after
transport.setSongPos(0) alignment, compare per-frame features with
cosine distance, 95th percentile < threshold => stable.
"""
import threading
import time

import numpy as np

from . import dsp_features as dsp


class AudioCaptureError(RuntimeError):
    pass


def _require_sd():
    try:
        import sounddevice as sd
        return sd
    except (ImportError, OSError) as e:
        raise AudioCaptureError(
            "sounddevice/PortAudio not available (%s). On Windows: "
            "pip install sounddevice (wheels bundle PortAudio). "
            "Unit tests do not need it." % e)


class RingBuffer:
    def __init__(self, capacity_samples):
        self.buf = np.zeros(capacity_samples, dtype=np.float64)
        self.capacity = capacity_samples
        self.write_pos = 0
        self.filled = 0
        self.lock = threading.Lock()

    def write(self, data):
        d = np.asarray(data, dtype=np.float64).ravel()
        n = len(d)
        with self.lock:
            if n >= self.capacity:
                self.buf[:] = d[-self.capacity:]
                self.write_pos = 0
                self.filled = self.capacity
                return
            end = self.write_pos + n
            if end <= self.capacity:
                self.buf[self.write_pos:end] = d
            else:
                k = self.capacity - self.write_pos
                self.buf[self.write_pos:] = d[:k]
                self.buf[:end - self.capacity] = d[k:]
            self.write_pos = (self.write_pos + n) % self.capacity
            self.filled = min(self.capacity, self.filled + n)

    def read_latest(self, n):
        with self.lock:
            n = min(n, self.filled)
            if n <= 0:
                return np.zeros(0)
            start = (self.write_pos - n) % self.capacity
            if start + n <= self.capacity:
                return self.buf[start:start + n].copy()
            k = self.capacity - start
            return np.concatenate([self.buf[start:], self.buf[:n - k]]).copy()


def cosine_distance_percentile(feats_a, feats_b, percentile=95):
    """feats: (dim, frames). Standardize per-dim, then cosine distance
    per frame; return the given percentile across frames."""
    a = np.asarray(feats_a, dtype=np.float64)
    b = np.asarray(feats_b, dtype=np.float64)
    n = min(a.shape[1], b.shape[1])
    a, b = a[:, :n], b[:, :n]
    mu = (a.mean(axis=1, keepdims=True) + b.mean(axis=1, keepdims=True)) / 2
    sd = np.sqrt(((a - mu) ** 2).mean(axis=1, keepdims=True)
                 + ((b - mu) ** 2).mean(axis=1, keepdims=True) + 1e-12)
    az, bz = (a - mu) / sd, (b - mu) / sd
    num = (az * bz).sum(axis=0)
    den = np.sqrt((az ** 2).sum(axis=0) * (bz ** 2).sum(axis=0)) + 1e-12
    # identical (e.g. digital-silence) frames have ~zero norm: distance 0,
    # not 1. Silence itself is rejected later by the non_silent constraint.
    dist = np.where(den <= 2e-12, 0.0, 1.0 - num / den)
    return float(np.percentile(dist, percentile))


class AudioCapture:
    def __init__(self, device_name, sample_rate=48000, blocksize=1024,
                 ring_seconds=10):
        self.device_name = device_name
        self.sr = sample_rate
        self.blocksize = blocksize
        self.ring = RingBuffer(int(sample_rate * ring_seconds))
        self._stream = None
        self._sd = None

    def _callback(self, indata, frames, time_info, status):
        self.ring.write(indata[:, 0])

    def start(self):
        self._sd = _require_sd()
        try:
            self._stream = self._sd.InputStream(
                device=self.device_name, channels=1,
                samplerate=self.sr, blocksize=self.blocksize,
                callback=self._callback)
        except ValueError as e:
            if "Multiple" in str(e) and "devices found" in str(e):
                raise AudioCaptureError(
                    "多个音频设备同名，请在 config/agent_config.yaml 里用全名 "
                    "(含驱动类型，如 'CABLE Output (VB-Audio Virtual Cable), "
                    "Windows WASAPI')。\n"
                    "Multiple audio devices share the name %r; use the FULL "
                    "device name (with driver type) in config/agent_config.yaml. "
                    "List all: .venv\\Scripts\\python.exe -c "
                    "\"import sounddevice; print(sounddevice.query_devices())\""
                    % (self.device_name,))
            raise
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def capture_two_loops(self, n_loop_samples, timeout_s=15):
        """Block until 2 full loops are available in the ring buffer."""
        need = 2 * n_loop_samples
        t0 = time.time()
        while True:
            if self.ring.filled >= need:
                two = self.ring.read_latest(need)
                return two[:n_loop_samples], two[n_loop_samples:]
            if time.time() - t0 > timeout_s:
                raise AudioCaptureError(
                    "timeout waiting for 2 loops (%d samples)" % need)
            time.sleep(0.05)

    def capture_stable_loop(self, n_loop_samples, threshold=0.05,
                            percentile=95, timeout_s=15, max_anomalies=2):
        """Continuously sample DSP features; maintain x = stability metric.

        - x: real-time fluctuation level (EMA-smoothed max CV across dims).
          Updated with each new window. Lower x = more stable.
        - When x < threshold: average the stable period's features, check
          for silence, return (avg_features, True).
        - Silence check: if avg rms < min_rms, treat as invalid (not stable).
        - Timeout: return average of recent data with (avg_features, False).

        Returns (features_dict, stable_bool).
        """
        import numpy as np
        window_samples = max(n_loop_samples // 4, self.sr // 2)
        need_stable = 4
        ema_alpha = 0.4  # smoothing factor for x

        feat_history = []
        feat_keys = None
        x = None  # stability metric: EMA of max CV; None until first calc

        # Silence threshold from config (set by caller via threshold param
        # or use default)
        min_rms = 0.01

        def compute_cv_per_dim(feat_list):
            """Compute CV per dimension. Returns dict {dim: cv}."""
            mat = np.stack([
                np.array([f[k] for k in feat_keys], dtype=np.float64)
                for f in feat_list
            ])
            means = np.mean(mat, axis=0)
            stds = np.std(mat, axis=0)
            cv_arr = np.where(np.abs(means) > 1e-6,
                              stds / (np.abs(means) + 1e-9),
                              stds)
            return {k: float(cv_arr[i]) for i, k in enumerate(feat_keys)}

        def avg_features(feat_list):
            avg = {}
            for k in feat_keys:
                avg[k] = float(np.mean([f[k] for f in feat_list]))
            return avg

        t0 = time.time()
        deadline = timeout_s * 3
        while True:
            elapsed = time.time() - t0
            if elapsed > deadline:
                # Timeout fallback
                if feat_history:
                    return avg_features(feat_history), False
                raise AudioCaptureError("no audio data captured")

            while self.ring.filled < window_samples:
                if time.time() - t0 > deadline:
                    break
                time.sleep(0.05)
            else:
                window = self.ring.read_latest(window_samples)
                feats = dsp.all_features(window, self.sr)
                # Add band energies with prefixed keys
                band_e = dsp.band_energies(window, self.sr)
                for blabel, bval in band_e.items():
                    feats["band_" + blabel] = bval
                if feat_keys is None:
                    feat_keys = sorted(feats.keys())
                feat_history.append(feats)
                if len(feat_history) > need_stable + 2:
                    feat_history.pop(0)

                # Update x (per-dim EMA) when we have enough history
                if len(feat_history) >= need_stable:
                    raw_cv = compute_cv_per_dim(feat_history[-need_stable:])
                    if x is None:
                        x = dict(raw_cv)
                    else:
                        for k in feat_keys:
                            x[k] = ema_alpha * raw_cv[k] + (1 - ema_alpha) * x[k]
                    # Stability: mean of per-dim x < threshold
                    mean_x = sum(x.values()) / len(x)
                    if mean_x < threshold:
                        avg = avg_features(feat_history[-need_stable:])
                        # Silence check: reject all-zero "stable" silence
                        if avg.get("rms", 0) < min_rms:
                            # Silence is "stable" but useless; keep sampling
                            # (don't reset x, just don't return yet)
                            pass
                        else:
                            return avg, True
                time.sleep(0.05)
                continue

            # Inner while broke on timeout
            if feat_history:
                return avg_features(feat_history), False
            raise AudioCaptureError("no audio data captured")

