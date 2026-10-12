"""CLAP slow-loop scoring (v4.4+).

Runs in a background thread, evaluates COMPLETED candidates by
candidate_id, and writes results into the shared trajectory store.
CLAP scores ARE blended into the optimizer objective via clap_weight
(see planner_system.md "CLAP weight" section).

Enable only if event rules allow third-party models.
Heavy dependency (laion-clap) is imported lazily.

API follows laion-clap: audio must be 48kHz float, shaped (1, T);
get_text_embedding([...]) / get_audio_embedding_from_data(x=..., use_tensor=False)
return numpy arrays. Cosine similarity is computed in numpy (no torch needed).
"""
import queue
import os
import shutil
import threading

import numpy as np
from scipy import signal as _sig

CLAP_SR = 48000
MAX_SECONDS = 20  # bound per-inference compute

# laion-clap<=1.1.7 (what `pip install laion-clap` gives) only accepts an INT
# model_id (0-3) pointing at general-audio checkpoints; passing the HF repo id
# "laion/larger_clap_music" raises TypeError. Map the design-doc name to the
# real music checkpoint .pt so config `clap.model: "laion/larger_clap_music"`
# loads MUSIC weights instead of silently falling back to general audio.
_MUSIC_CKPT = {
    "url": "https://huggingface.co/lukewys/laion_clap/resolve/main/"
           "music_audioset_epoch_15_esc_90.14.pt",
    "mirror_url": "https://hf-mirror.com/lukewys/laion_clap/resolve/main/"
                  "music_audioset_epoch_15_esc_90.14.pt",
    "filename": "music_audioset_epoch_15_esc_90.14.pt",
}
_KNOWN_MODELS = {"laion/larger_clap_music", "larger_clap_music", "music"}


def _cache_dir():
    d = os.path.join(os.path.expanduser("~"), ".cache", "proq2-eq-agent")
    os.makedirs(d, exist_ok=True)
    return d


def _download(url, path):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "proq2-eq-agent"})
    with urllib.request.urlopen(req, timeout=120) as r, \
            open(path, "wb") as f:
        shutil.copyfileobj(r, f)


def resolve_ckpt_path(model_name):
    """Return a local .pt path for `model_name`.

    - existing file path -> used as-is (manual pre-download supported)
    - "laion/larger_clap_music" (design-doc name) -> music checkpoint,
      downloaded once to ~/.cache/proq2-eq-agent
      (official URL first, hf-mirror fallback for slow networks)
    - anything else -> ValueError (never silently load the wrong model)
    """
    name = (model_name or "").strip()
    if os.path.isfile(name):
        return os.path.abspath(name)
    if name in _KNOWN_MODELS:
        path = os.path.join(_cache_dir(), _MUSIC_CKPT["filename"])
        if not os.path.exists(path):
            try:
                _download(_MUSIC_CKPT["url"], path)
            except Exception:
                _download(_MUSIC_CKPT["mirror_url"], path)
        return path
    raise ValueError(
        "Unknown CLAP model %r. Use a local .pt path or one of %s."
        % (model_name, sorted(_KNOWN_MODELS)))


def _resample_to_48k(audio, sr):
    if sr == CLAP_SR:
        return np.asarray(audio, dtype=np.float32)
    gcd = np.gcd(int(sr), CLAP_SR)
    up, down = CLAP_SR // gcd, int(sr) // gcd
    return _sig.resample_poly(np.asarray(audio, dtype=np.float32), up, down)


def _cosine(a, b):
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    denom = np.linalg.norm(a) * np.linalg.norm(b) + 1e-12
    return float(np.dot(a, b) / denom)


class CLAPCritic:
    def __init__(self, model_name="laion/larger_clap_music",
                 enabled=False, sample_rate=48000):
        self.model_name = model_name
        self.enabled = enabled
        self.sr = sample_rate
        self._model = None
        self._text_cache = {}
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self._results = {}  # candidate_id -> score or None
        self._worker = None

    def _require_model(self):
        if self._model is not None:
            return self._model
        try:
            import laion_clap
        except ImportError as e:
            # Show the real missing module (e.g. librosa), not just
            # "not installed" — the package may be present but broken.
            raise RuntimeError(
                "cannot import laion_clap: %s. "
                "Try: pip install --force-reinstall laion-clap "
                "and its deps (librosa, transformers, torch). "
                "CLAP is optional and OFF by default." % e) from e
        model = laion_clap.CLAP_Module(enable_fusion=False,
                                           amodel='HTSAT-base')
        # NOTE: music_audioset_epoch_15_esc_90.14.pt uses the larger
        # HTSAT-base audio encoder (128-dim). The default HTSAT-tiny
        # (96-dim) causes state_dict size mismatch.
        # resolve_ckpt_path maps the design-doc name to the real music .pt;
        # unknown names raise instead of silently loading the wrong checkpoint.
        # Suppress laion-clap's per-parameter "Loaded" spam; on failure,
        # re-raise with the captured output for diagnosis.
        import io
        import contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                model.load_ckpt(ckpt=resolve_ckpt_path(self.model_name))
        except Exception as e:
            out = buf.getvalue()
            raise RuntimeError(
                "CLAP checkpoint load failed: %s\n--- loader output ---\n%s"
                % (e, out[-2000:])) from e
        self._model = model
        return model

    def start(self):
        """Start the background worker. No-op when disabled or started."""
        if not self.enabled or self._worker is not None:
            return
        self._worker = threading.Thread(target=self._loop, daemon=True,
                                        name="clap-slow-loop")
        self._worker.start()

    def submit(self, candidate_id, audio, text_prompt):
        """Queue a completed candidate for async evaluation. No-op when off."""
        if not self.enabled:
            return
        self.start()  # ensure the worker runs even if start() was forgotten
        self._queue.put((candidate_id, np.asarray(audio, dtype=np.float32),
                         text_prompt))

    def _score_one(self, model, audio, text_prompt):
        a = _resample_to_48k(audio, self.sr)[:CLAP_SR * MAX_SECONDS]
        if a.size == 0:
            raise ValueError("empty audio for CLAP")
        with self._lock:
            if text_prompt not in self._text_cache:
                t = model.get_text_embedding([text_prompt])
                self._text_cache[text_prompt] = np.asarray(t).ravel()
            t_emb = self._text_cache[text_prompt]
        a_emb = np.asarray(model.get_audio_embedding_from_data(
            x=a.reshape(1, -1), use_tensor=False)).ravel()
        return _cosine(a_emb, t_emb)

    def _loop(self):
        try:
            model = self._require_model()
        except Exception as e:  # noqa: BLE001 - don't kill the main loop
            import sys
            print("[clap] model failed to load: %s. "
                  "All CLAP scores will be None." % e, file=sys.stderr)
            model = None  # every submit resolves to None below
        while True:
            candidate_id, audio, text_prompt = self._queue.get()
            try:
                score = self._score_one(model, audio, text_prompt) \
                    if model is not None else None
            except Exception:
                score = None
            with self._lock:
                self._results[candidate_id] = score
            self._queue.task_done()

    def result(self, candidate_id, default=None):
        """Latest finished score for a candidate (None = pending/failed)."""
        with self._lock:
            return self._results.get(candidate_id, default)

    def pending(self):
        return self._queue.qsize()
