"""Unit tests: dsp_features (no FL, no audio hardware)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import dsp_features as dsp

SR = 48000


def sine(freq, dur=1.0, amp=0.5):
    t = np.arange(int(SR * dur)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def noise(dur=1.0, seed=1):
    return (0.3 * np.random.RandomState(seed).randn(int(SR * dur)))


def test_centroid_tracks_frequency():
    c_lo = dsp.spectral_centroid(sine(220), SR)
    c_hi = dsp.spectral_centroid(sine(2000), SR)
    assert 150 < c_lo < 400, c_lo
    assert 1500 < c_hi < 2800, c_hi


def test_flatness_noise_higher_than_sine():
    assert dsp.spectral_flatness(noise(), SR) > \
        dsp.spectral_flatness(sine(440), SR)


def test_sibilance_ratio_hf_content():
    hi = sine(7000) + sine(8000)
    lo = sine(200) + sine(300)
    assert dsp.sibilance_ratio(hi, SR) > dsp.sibilance_ratio(lo, SR)


def test_harmonic_ratio_sine_vs_noise():
    assert dsp.harmonic_ratio(sine(440), SR) > \
        dsp.harmonic_ratio(noise(), SR)


def test_rms_and_zcr_sanity():
    assert abs(dsp.rms(sine(440, amp=0.5), SR) - 0.5 / np.sqrt(2)) < 0.05
    assert dsp.zero_crossing_rate(sine(440), SR) > \
        dsp.zero_crossing_rate(sine(110), SR)


def test_all_features_keys():
    feats = dsp.all_features(sine(440, dur=0.5), SR)
    assert set(feats) == set(dsp.FEATURE_INFO)


def test_frame_features_shape():
    f = dsp.frame_features(sine(440, dur=0.5), SR)
    assert f.shape[0] == 7 and f.shape[1] > 5
