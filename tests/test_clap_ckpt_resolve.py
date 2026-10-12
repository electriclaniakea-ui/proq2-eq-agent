"""Unit tests: CLAP checkpoint resolution (no network, no weights)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import core.clap_critic as cc
from core.clap_critic import CLAPCritic, resolve_ckpt_path


def test_local_pt_path_passthrough(tmp_path, monkeypatch):
    p = tmp_path / "my_music.pt"
    p.write_bytes(b"fake")
    got = resolve_ckpt_path(str(p))
    assert got == os.path.abspath(str(p))


def test_known_music_name_uses_cached_file(tmp_path, monkeypatch):
    # pre-seed the cache: no download must be attempted
    monkeypatch.setattr(cc, "_cache_dir", lambda: str(tmp_path))
    (tmp_path / cc._MUSIC_CKPT["filename"]).write_bytes(b"fake")
    def _boom(url, path):
        raise AssertionError("download should not run on cache hit")
    monkeypatch.setattr(cc, "_download", _boom)
    got = resolve_ckpt_path("laion/larger_clap_music")
    assert got == os.path.join(str(tmp_path), cc._MUSIC_CKPT["filename"])


def test_unknown_model_name_raises():
    with pytest.raises(ValueError):
        resolve_ckpt_path("laion/some-other-model")


def test_require_model_passes_resolved_ckpt(tmp_path, monkeypatch):
    calls = {}

    class FakeModule:
        def __init__(self, enable_fusion=False, amodel=None, **kw):
            self.enable_fusion = enable_fusion
            self.amodel = amodel
        def load_ckpt(self, ckpt=None, **kw):
            calls["ckpt"] = ckpt

    fake_pkg = type(sys)("laion_clap")
    fake_pkg.CLAP_Module = FakeModule
    monkeypatch.setitem(sys.modules, "laion_clap", fake_pkg)
    monkeypatch.setattr(cc, "resolve_ckpt_path", lambda name: "/tmp/x.pt")

    critic = CLAPCritic(model_name="laion/larger_clap_music", enabled=True)
    critic._require_model()
    assert calls["ckpt"] == "/tmp/x.pt"
