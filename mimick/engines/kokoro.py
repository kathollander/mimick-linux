"""Kokoro - a small local neural voice model, for reading without internet.

Model files are fetched once on first use (about 350 MB) into ~/.cache/mimick.
Kokoro reports no word timings, so we estimate them from word length, which is
close enough for the highlight to track sensibly.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

from ..config import CACHE_DIR
from .base import Clip, Engine, EngineError, Voice, estimate_marks

SAMPLE_RATE = 24_000
_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
MODEL_FILES = {
    "kokoro-v1.0.onnx": f"{_BASE}/kokoro-v1.0.onnx",
    "voices-v1.0.bin": f"{_BASE}/voices-v1.0.bin",
}

# Kokoro ships fixed voice names; these are the English ones.
VOICES = [
    ("af_heart", "Heart", "en-US", "Female"), ("af_bella", "Bella", "en-US", "Female"),
    ("af_nicole", "Nicole", "en-US", "Female"), ("af_sarah", "Sarah", "en-US", "Female"),
    ("af_sky", "Sky", "en-US", "Female"), ("am_adam", "Adam", "en-US", "Male"),
    ("am_michael", "Michael", "en-US", "Male"), ("am_puck", "Puck", "en-US", "Male"),
    ("bf_emma", "Emma", "en-GB", "Female"), ("bf_isabella", "Isabella", "en-GB", "Female"),
    ("bm_george", "George", "en-GB", "Male"), ("bm_lewis", "Lewis", "en-GB", "Male"),
]


def model_dir() -> Path:
    return CACHE_DIR / "kokoro"


def is_installed() -> bool:
    return all((model_dir() / name).exists() for name in MODEL_FILES)


def download_models(progress=None) -> None:
    """Fetch the model files, reporting progress as a 0.0-1.0 fraction."""
    target = model_dir()
    target.mkdir(parents=True, exist_ok=True)
    for position, (name, url) in enumerate(MODEL_FILES.items()):
        destination = target / name
        if destination.exists():
            continue
        partial = destination.with_suffix(destination.suffix + ".part")
        try:
            with urllib.request.urlopen(url) as response:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                with open(partial, "wb") as handle:
                    while True:
                        block = response.read(1 << 16)
                        if not block:
                            break
                        handle.write(block)
                        done += len(block)
                        if progress and total:
                            share = (position + done / total) / len(MODEL_FILES)
                            progress(share, name)
            partial.replace(destination)
        except (urllib.error.URLError, OSError) as exc:
            partial.unlink(missing_ok=True)
            raise EngineError(f"Could not download {name}: {exc}") from exc


class KokoroEngine(Engine):
    id = "kokoro"
    name = "Kokoro (offline)"
    needs_network = False

    def __init__(self) -> None:
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        if not is_installed():
            raise EngineError(
                "The offline voices are not downloaded yet.\n\n"
                "Use  Voice → Download offline voices  to fetch them (about 350 MB)."
            )
        try:
            from kokoro_onnx import Kokoro

            self._model = Kokoro(
                str(model_dir() / "kokoro-v1.0.onnx"),
                str(model_dir() / "voices-v1.0.bin"),
            )
        except Exception as exc:
            raise EngineError(f"Could not load the offline voice model: {exc}") from exc
        return self._model

    def list_voices(self) -> list[Voice]:
        return [
            Voice(id=vid, name=name, locale=locale, gender=gender, engine=self.id)
            for vid, name, locale, gender in VOICES
        ]

    def synthesize(self, text: str, voice: str, rate: float) -> Clip:
        import numpy as np

        if not text.strip():
            return Clip(pcm=np.zeros(0, dtype=np.int16), sample_rate=SAMPLE_RATE)
        model = self._ensure_model()
        try:
            samples, sample_rate = model.create(
                text, voice=voice, speed=max(0.5, min(rate, 3.0)), lang="en-us"
            )
        except Exception as exc:
            raise EngineError(f"Offline synthesis failed: {exc}") from exc
        pcm = np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0)
        pcm = (pcm * 32767).astype("int16")
        duration = len(pcm) / sample_rate if sample_rate else 0.0
        return Clip(pcm=pcm, sample_rate=int(sample_rate), marks=estimate_marks(text, duration))
