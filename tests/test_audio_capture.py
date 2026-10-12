"""Unit tests: audio_capture pure logic (no hardware)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.audio_capture import RingBuffer, cosine_distance_percentile
from core import dsp_features as dsp

SR = 48000


def test_ring_buffer_wraparound():
    rb = RingBuffer(10)
    rb.write(np.arange(6))
    rb.write(np.arange(6, 14))  # wraps
    out = rb.read_latest(10)
    assert list(out) == list(range(4, 14))
    assert len(rb.read_latest(100)) == 10  # clamped to filled


def test_ring_buffer_partial():
    rb = RingBuffer(100)
    rb.write(np.ones(30))
    assert len(rb.read_latest(50)) == 30


def test_cosine_distance_identical_is_zero():
    rng = np.random.RandomState(0)
    a = rng.randn(SR)
    f = dsp.frame_features(a, SR)
    d = cosine_distance_percentile(f, f)
    assert d < 1e-6, d


def test_cosine_distance_different_is_large():
    t = np.arange(SR) / SR
    sine = np.sin(2 * np.pi * 440 * t)
    noise = np.random.RandomState(1).randn(SR) * 0.3
    d = cosine_distance_percentile(dsp.frame_features(sine, SR),
                                   dsp.frame_features(noise, SR))
    assert d > 0.05, d


def test_identical_silence_is_stable():
    silence = np.zeros(SR)
    d = cosine_distance_percentile(dsp.frame_features(silence, SR),
                                   dsp.frame_features(silence, SR))
    assert d == 0.0, d


def test_identical_signal_is_stable():
    t = np.arange(SR) / SR
    sine = np.sin(2 * np.pi * 440 * t)
    d = cosine_distance_percentile(dsp.frame_features(sine, SR),
                                   dsp.frame_features(sine, SR))
    assert d < 0.05, d
