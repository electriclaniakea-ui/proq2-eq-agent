"""DSP feature library (v4.3).

Pure numpy/scipy implementation - no librosa needed, so unit tests run anywhere.
All features operate on mono float64 numpy arrays.

Conventions (technical design 5.2):
- every dimension documents its failure condition in FEATURE_INFO
- features are PROXY metrics, not perceptions
"""
import numpy as np
from scipy import signal as _sig

N_FFT = 2048
HOP = 512

# Frequency bands for band_targets (Hz). These are the primary optimization
# targets; the 10 global dims are guardrails.
BANDS = {
    "sub": (30, 80),
    "low": (80, 200),
    "lowmid": (200, 600),
    "presence": (2000, 5000),
    "air": (6000, 12000),
}

# name -> (description, typical (lo, hi), fails_when)
FEATURE_INFO = {
    "spectral_centroid": ("spectral centroid (Hz)", (800.0, 6000.0),
        "transient-dominated or near-silent material; energy distribution only"),
    "spectral_bandwidth": ("spectral bandwidth (Hz)", (500.0, 8000.0),
        "ultra-narrowband material (pure sine): no discrimination"),
    "spectral_flatness": ("spectral flatness 0..1", (0.0, 0.6),
        "strong transient percussion is naturally high, not harshness"),
    "spectral_contrast": ("spectral contrast (dB)", (10.0, 60.0),
        "heavily reverberant material is naturally low"),
    "spectral_rolloff": ("spectral rolloff 85pct (Hz)", (2000.0, 16000.0),
        "low-passed or low-sample-rate material: meaningless"),
    "harmonic_ratio": ("harmonic energy ratio 0..1 (NOT harmonics-to-noise)", (0.0, 1.0),
        "non-harmonic instruments (drums, noise): meaningless"),
    "sibilance_ratio": ("5-10kHz energy ratio", (0.0, 0.4),
        "non-vocal material: meaningless; needs human-marked sibilance windows"),
    "zero_crossing_rate": ("zero-crossing rate", (0.01, 0.3),
        "strong low sine: naturally low"),
    "rms": ("RMS energy (reference only)", (0.0, 1.0),
        "reference only, never an optimization target"),
    "onset_density": ("onsets per second", (0.0, 8.0),
        "long pad-like material: naturally low"),
}


def _to_mono(audio):
    a = np.asarray(audio, dtype=np.float64)
    if a.ndim == 2:
        a = a.mean(axis=1)
    return a


def _stft_mag(audio, sr, n_fft=N_FFT, hop=HOP):
    a = _to_mono(audio)
    if a.size < n_fft:
        a = np.pad(a, (0, n_fft - a.size))
    _, _, Z = _sig.stft(a, fs=sr, window="hann", nperseg=n_fft,
                        noverlap=n_fft - hop, nfft=n_fft, boundary="zeros")
    return np.abs(Z)  # (freq_bins, frames)


def _freqs(n_fft, sr):
    return np.fft.rfftfreq(n_fft, d=1.0 / sr)


def spectral_centroid(audio, sr):
    S = _stft_mag(audio, sr)
    f = _freqs(N_FFT, sr)[:, None]
    c = (f * S).sum(axis=0) / (S.sum(axis=0) + 1e-12)
    w = S.sum(axis=0)
    return float(np.average(c, weights=w + 1e-12))


def spectral_bandwidth(audio, sr):
    S = _stft_mag(audio, sr)
    f = _freqs(N_FFT, sr)[:, None]
    c = spectral_centroid(audio, sr)
    b = np.sqrt((((f - c) ** 2) * S).sum(axis=0) / (S.sum(axis=0) + 1e-12))
    w = S.sum(axis=0)
    return float(np.average(b, weights=w + 1e-12))


def spectral_flatness(audio, sr):
    S = _stft_mag(audio, sr) + 1e-12
    gm = np.exp(np.log(S).mean(axis=0))
    am = S.mean(axis=0)
    flat = gm / (am + 1e-12)
    w = S.sum(axis=0)
    return float(np.average(flat, weights=w + 1e-12))


def spectral_contrast(audio, sr, n_bands=6):
    S = _stft_mag(audio, sr)
    f = _freqs(N_FFT, sr)
    edges = np.logspace(np.log10(100), np.log10(sr / 2), n_bands + 1)
    SdB = 20 * np.log10(S + 1e-10)
    vals = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (f >= lo) & (f < hi)
        if not m.any():
            continue
        band = SdB[m, :]
        vals.append(np.mean(np.percentile(band, 95, axis=0)
                            - np.percentile(band, 5, axis=0)))
    return float(np.mean(vals)) if vals else 0.0


def spectral_rolloff(audio, sr, roll=0.85):
    S = _stft_mag(audio, sr)
    f = _freqs(N_FFT, sr)
    cum = np.cumsum(S, axis=0)
    total = cum[-1, :] + 1e-12
    idx = np.argmax(cum >= roll * total[None, :], axis=0)
    r = f[np.clip(idx, 0, len(f) - 1)]
    w = S.sum(axis=0)
    return float(np.average(r, weights=w + 1e-12))


def harmonic_ratio(audio, sr, fmin=50.0, fmax=2000.0):
    a = _to_mono(audio) - _to_mono(audio).mean()
    if np.abs(a).max() < 1e-9:
        return 0.0
    n = min(len(a), sr * 2)
    a = a[:n]
    ac = np.correlate(a, a, mode="full")[n - 1:]
    ac = ac / (ac[0] + 1e-12)
    lo_lag = max(1, int(sr / fmax))
    hi_lag = min(len(ac) - 1, int(sr / fmin))
    if hi_lag <= lo_lag:
        return 0.0
    return float(np.clip(ac[lo_lag:hi_lag].max(), 0.0, 1.0))


def sibilance_ratio(audio, sr, lo=5000.0, hi=10000.0):
    S = _stft_mag(audio, sr)
    f = _freqs(N_FFT, sr)
    band = ((f >= lo) & (f < hi))[:, None]
    return float((S ** 2 * band).sum() / ((S ** 2).sum() + 1e-12))


def zero_crossing_rate(audio, sr=None):
    a = _to_mono(audio)
    if a.size < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(np.sign(a)))) / 2.0)


def rms(audio, sr=None):
    a = _to_mono(audio)
    return float(np.sqrt(np.mean(a ** 2) + 1e-18))


def onset_density(audio, sr, hop=HOP):
    S = _stft_mag(audio, sr, hop=hop)
    flux = np.clip(np.diff(S, axis=1), 0, None).sum(axis=0)
    if flux.size < 3:
        return 0.0
    med = np.median(flux)
    thr = med + 3.0 * (np.median(np.abs(flux - med)) + 1e-12)
    peaks = (flux[1:-1] > flux[:-2]) & (flux[1:-1] > flux[2:]) & (flux[1:-1] > thr)
    dur = len(_to_mono(audio)) / float(sr)
    return float(peaks.sum() / max(dur, 1e-6))


def frame_features(audio, sr, hop=HOP):
    S = _stft_mag(audio, sr, hop=hop)
    f = _freqs(N_FFT, sr)[:, None]
    e = (S ** 2).sum(axis=0) + 1e-12
    rms_f = np.sqrt(e / S.shape[0])
    cent = ((f * S).sum(axis=0) / (S.sum(axis=0) + 1e-12))
    bands = []
    for lo, hi in [(0, 200), (200, 1000), (1000, 3000), (3000, 8000), (8000, sr / 2)]:
        m = (f[:, 0] >= lo) & (f[:, 0] < hi)
        bands.append(np.log10((S[m, :] ** 2).sum(axis=0) + 1e-12))
    return np.vstack([rms_f[None, :], cent[None, :]] + [b[None, :] for b in bands])


def band_energies(audio, sr):
    """Compute energy per band in dB. Returns dict {band_label: energy_db}.

    Energy is 10*log10(mean(square(magnitude))) in the band, relative to
    full-scale. Silence gives -inf; we clip to -120 dB.
    """
    audio = np.asarray(audio, dtype=np.float64)
    if len(audio) < N_FFT:
        return {label: -120.0 for label in BANDS}
    # STFT magnitude
    freqs, _, Zxx = _sig.stft(audio, fs=sr, nperseg=N_FFT, noverlap=N_FFT - HOP)
    mag = np.abs(Zxx)
    out = {}
    for label, (lo, hi) in BANDS.items():
        mask = (freqs >= lo) & (freqs < hi)
        if not np.any(mask):
            out[label] = -120.0
            continue
        band_mag = mag[mask, :]
        energy = np.mean(band_mag ** 2)
        db = 10 * np.log10(energy + 1e-12)
        out[label] = float(np.clip(db, -120.0, 0.0))
    return out


_FEATURE_FNS = {
    "spectral_centroid": spectral_centroid,
    "spectral_bandwidth": spectral_bandwidth,
    "spectral_flatness": spectral_flatness,
    "spectral_contrast": spectral_contrast,
    "spectral_rolloff": spectral_rolloff,
    "harmonic_ratio": harmonic_ratio,
    "sibilance_ratio": sibilance_ratio,
    "zero_crossing_rate": zero_crossing_rate,
    "rms": rms,
    "onset_density": onset_density,
}


def all_features(audio, sr, dims=None):
    names = list(_FEATURE_FNS) if dims is None else list(dims)
    out = {}
    for n in names:
        fn = _FEATURE_FNS.get(n)
        if fn is None:
            raise KeyError("unknown DSP dimension: %s" % n)
        out[n] = fn(audio, sr)
    return out
