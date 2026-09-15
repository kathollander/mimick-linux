"""Piper - fast local voices that need no internet once downloaded.

Piper is the engine behind Pied, the usual answer for natural-sounding speech
on Linux. Each voice is a single file of roughly 60 MB and synthesises about
twenty times faster than real time, which makes it a practical fallback when
there is no connection.

Piper does not report when each word is spoken, so word timings are estimated
from word length. The highlight still follows the voice closely.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from ..config import CACHE_DIR
from .base import Clip, Engine, EngineError, Voice, estimate_marks

CATALOGUE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
CATALOGUE_CACHE = CACHE_DIR / "piper-voices.json"

# Quality levels, worst to best; higher quality means a larger download.
QUALITY_ORDER = {"x_low": 0, "low": 1, "medium": 2, "high": 3}

# A sensible starting voice: the one most guides recommend.
SUGGESTED = "en_GB-alan-medium"


def voice_dir() -> Path:
    return CACHE_DIR / "piper"


def installed_voices() -> list[str]:
    """Keys of voices already downloaded."""
    directory = voice_dir()
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.onnx")
                  if (directory / f"{path.stem}.onnx.json").exists())


def is_installed(key: str) -> bool:
    return (voice_dir() / f"{key}.onnx").exists()


def any_installed() -> bool:
    return bool(installed_voices())


# -- the catalogue of downloadable voices ------------------------------------

def load_catalogue(refresh: bool = False) -> dict:
    """The list of available voices, cached on disk so it works offline."""
    if not refresh and CATALOGUE_CACHE.exists():
        try:
            return json.loads(CATALOGUE_CACHE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    try:
        with urllib.request.urlopen(CATALOGUE_URL, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        if CATALOGUE_CACHE.exists():
            try:
                return json.loads(CATALOGUE_CACHE.read_text(encoding="utf-8"))
            except ValueError:
                pass
        raise EngineError(
            "Could not fetch the list of offline voices. An internet "
            f"connection is needed to download voices the first time.\n\n({exc})"
        ) from exc
    CATALOGUE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CATALOGUE_CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def describe(key: str, entry: dict | None = None) -> tuple[str, str, str]:
    """Turn a voice key into (person, language, quality) for display."""
    parts = key.split("-")
    locale = parts[0] if parts else key
    person = parts[1].replace("_", " ").title() if len(parts) > 1 else key
    quality = parts[2] if len(parts) > 2 else ""
    language = locale.replace("_", "-")
    if entry:
        info = entry.get("language") or {}
        name = info.get("name_english") or ""
        country = info.get("country_english") or ""
        if name:
            language = f"{name} ({country})" if country else name
    return person, language, quality


SAMPLE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def sample_url(entry: dict) -> str | None:
    """Where to hear a voice before downloading it.

    The Piper repository ships a short sample beside every voice, so a voice can
    be auditioned without pulling down the whole 60 MB model.
    """
    for name in (entry.get("files") or {}):
        if name.endswith(".onnx"):
            folder = name.rsplit("/", 1)[0]
            return f"{SAMPLE_BASE}/{folder}/samples/speaker_0.mp3"
    return None


def sample_cache_dir() -> Path:
    return CACHE_DIR / "piper-samples"


def cached_sample(key: str) -> Path:
    return sample_cache_dir() / f"{key}.mp3"


def has_sample(key: str) -> bool:
    path = cached_sample(key)
    return path.exists() and path.stat().st_size > 0


def cached_sample_count() -> tuple[int, int]:
    """How many samples are kept, and how much room they take."""
    directory = sample_cache_dir()
    if not directory.is_dir():
        return 0, 0
    files = list(directory.glob("*.mp3"))
    return len(files), sum(path.stat().st_size for path in files)


def fetch_sample(entry: dict, key: str = "", timeout: int = 30) -> bytes:
    """A voice's sample clip, kept on disk so it only downloads once.

    Samples are about 90 KB each, so keeping every English one costs a few
    megabytes -- far less than a single voice model.
    """
    if key and has_sample(key):
        try:
            return cached_sample(key).read_bytes()
        except OSError:
            pass
    url = sample_url(entry)
    if not url:
        raise EngineError("That voice has no sample to play.")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise EngineError(
            f"Could not fetch a sample of that voice.\n\n({exc})"
        ) from exc
    if key and data:
        try:
            sample_cache_dir().mkdir(parents=True, exist_ok=True)
            cached_sample(key).write_bytes(data)
        except OSError:
            pass          # a cache that cannot be written is not an error
    return data


def clear_samples() -> None:
    directory = sample_cache_dir()
    if not directory.is_dir():
        return
    for path in directory.glob("*.mp3"):
        path.unlink(missing_ok=True)


def download_size(entry: dict) -> int:
    return sum(info.get("size_bytes") or 0
               for name, info in (entry.get("files") or {}).items()
               if name.endswith(".onnx"))


def download(key: str, progress=None) -> None:
    """Fetch one voice into the cache."""
    target = voice_dir()
    target.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(0.0, key)
    try:
        from piper.download_voices import download_voice

        download_voice(key, target)
    except Exception as exc:
        raise EngineError(f"Could not download the voice {key}: {exc}") from exc
    if progress:
        progress(1.0, key)
    if not is_installed(key):
        raise EngineError(f"The voice {key} did not download correctly.")


def remove(key: str) -> None:
    for suffix in (".onnx", ".onnx.json"):
        (voice_dir() / f"{key}{suffix}").unlink(missing_ok=True)


# -- the engine ---------------------------------------------------------------

class PiperEngine(Engine):
    id = "piper"
    name = "Piper (offline)"
    needs_network = False

    # length_scale compresses each phoneme but not the pauses between them, so
    # what is asked for and what is heard part company as it rises: measured on
    # en_GB-alan-medium, 1.5 asked gives 1.44 heard, 2.0 gives 1.78 and 6.0
    # only 2.61. Up to 1.5 the compression still sounds like a person reading
    # faster, which beats ffmpeg, and is close enough to honest that the error
    # it carries into every higher speed stays small. Past it, ffmpeg is both
    # exact and cheaper.
    max_native_rate = 1.5

    def __init__(self) -> None:
        self._loaded: dict[str, object] = {}
        self._lock = threading.Lock()

    def list_voices(self) -> list[Voice]:
        keys = installed_voices()
        if not keys:
            raise EngineError(
                "No offline voices are installed yet.\n\n"
                "Use  Voice → Manage offline voices  to download one. "
                "They are about 60 MB each and work without internet afterwards."
            )
        catalogue: dict = {}
        try:
            catalogue = load_catalogue()
        except EngineError:
            pass          # names still work without the catalogue
        voices = []
        for key in keys:
            person, language, quality = describe(key, catalogue.get(key))
            voices.append(Voice(id=key, name=person, locale=language,
                                gender=quality, engine=self.id))
        voices.sort(key=lambda v: (v.locale, v.name))
        return voices

    def _voice(self, key: str):
        with self._lock:
            if key in self._loaded:
                return self._loaded[key]
        path = voice_dir() / f"{key}.onnx"
        if not path.exists():
            raise EngineError(
                f"The offline voice {key} is not installed.\n\n"
                "Use  Voice → Manage offline voices  to download it."
            )
        try:
            from piper import PiperVoice

            voice = PiperVoice.load(path)
        except Exception as exc:
            raise EngineError(f"Could not load the offline voice {key}: {exc}") from exc
        with self._lock:
            self._loaded[key] = voice
        return voice

    def synthesize(self, text: str, voice: str, rate: float) -> Clip:
        if not text.strip():
            return Clip(pcm=np.zeros(0, dtype=np.int16), sample_rate=22_050)
        model = self._voice(voice)
        try:
            from piper import SynthesisConfig

            # length_scale stretches each phoneme, so it is the inverse of speed.
            config = SynthesisConfig(length_scale=1.0 / max(rate, 0.1))
            chunks = list(model.synthesize(text, config))
        except Exception as exc:
            raise EngineError(f"Offline synthesis failed: {exc}") from exc

        if not chunks:
            return Clip(pcm=np.zeros(0, dtype=np.int16), sample_rate=model.config.sample_rate)
        pcm = np.concatenate(
            [np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16) for chunk in chunks]
        )
        sample_rate = chunks[0].sample_rate or model.config.sample_rate
        duration = len(pcm) / sample_rate if sample_rate else 0.0
        return Clip(pcm=pcm, sample_rate=int(sample_rate),
                    marks=estimate_marks(text, duration))

    def close(self) -> None:
        with self._lock:
            self._loaded.clear()
