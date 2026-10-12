"""Unit tests: clap_critic with a stub model (no weights download)."""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.clap_critic import CLAPCritic, _cosine, _resample_to_48k


class StubCLAP:
    """Mimics laion-clap's numpy API."""

    def __init__(self, audio_vec=(1.0, 0.0)):
        self.audio_vec = np.array([audio_vec])

    def get_text_embedding(self, texts):
        assert isinstance(texts, list) and len(texts) == 1
        return np.array([[1.0, 0.0]])

    def get_audio_embedding_from_data(self, x, use_tensor=False):
        assert x.ndim == 2 and x.shape[0] == 1, x.shape  # (1, T)
        assert use_tensor is False
        return self.audio_vec


def _with_stub(critic, stub):
    critic._require_model = lambda: stub
    return critic


def _wait_result(critic, cid, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = critic.result(cid, default="pending")
        if r != "pending":
            return r
        time.sleep(0.05)
    raise TimeoutError("no CLAP result for " + cid)


def test_cosine_math():
    assert abs(_cosine([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(_cosine([1, 0], [0, 1]) - 0.0) < 1e-9
    assert abs(_cosine([1, 1], [1, 1]) - 1.0) < 1e-9


def test_resample_to_48k():
    sr = 16000
    t = np.arange(sr) / sr
    a = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    b = _resample_to_48k(a, sr)
    assert len(b) == 48000
    # 48kHz in -> unchanged
    c = _resample_to_48k(a, 48000)
    assert len(c) == len(a)


def test_submit_result_roundtrip():
    c = _with_stub(CLAPCritic(enabled=True), StubCLAP())
    c.start()
    audio = np.random.RandomState(0).randn(48000).astype(np.float32)
    c.submit("cid-1", audio, "a bright lead synth")
    assert abs(_wait_result(c, "cid-1") - 1.0) < 1e-6
    assert c.pending() == 0


def test_orthogonal_scores_zero():
    c = _with_stub(CLAPCritic(enabled=True), StubCLAP(audio_vec=(0.0, 1.0)))
    c.start()
    c.submit("cid-2", np.zeros(48000, dtype=np.float32), "a bright lead synth")
    assert abs(_wait_result(c, "cid-2") - 0.0) < 1e-6


def test_disabled_is_noop():
    c = CLAPCritic(enabled=False)
    c.start()
    c.submit("cid-3", np.zeros(100, dtype=np.float32), "x")
    assert c.result("cid-3") is None
    assert c.pending() == 0


def test_text_embedding_cached():
    stub = StubCLAP()
    calls = []
    orig = stub.get_text_embedding
    stub.get_text_embedding = lambda texts: calls.append(texts) or orig(texts)
    c = _with_stub(CLAPCritic(enabled=True), stub)
    c.start()
    a = np.zeros(48000, dtype=np.float32)
    c.submit("c1", a, "same prompt")
    c.submit("c2", a, "same prompt")
    _wait_result(c, "c1")
    _wait_result(c, "c2")
    assert len(calls) == 1  # text embedding computed once
