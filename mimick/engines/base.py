"""Common shape for every voice engine."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import numpy as np

from ..system import ffmpeg_command, ffmpeg_missing_message, no_window_kwargs


@dataclass
class Voice:
    """One selectable voice."""

    id: str
    name: str
    locale: str
    gender: str = ""
    engine: str = ""

    @property
    def label(self) -> str:
        bits = [self.name, self.locale]
        if self.gender:
            bits.append(self.gender)
        return " · ".join(bits)


@dataclass
class Clip:
    """Rendered audio for one sentence, plus when each word is spoken.

    ``marks`` holds (seconds_from_clip_start, spoken_word) pairs. Engines that
    cannot report timings leave it empty and the UI falls back to highlighting
    the whole sentence.
    """

    pcm: np.ndarray
    sample_rate: int
    marks: list[tuple[float, str]] = field(default_factory=list)

    @property
    def duration(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return len(self.pcm) / self.sample_rate


def estimate_marks(text: str, duration: float) -> list[tuple[float, str]]:
    """Spread word timings across a clip in proportion to word length.

    Used by engines that synthesise locally and cannot report when each word is
    spoken. The highlight then tracks the voice closely enough to follow.
    """
    words = text.split()
    if not words or duration <= 0:
        return []
    weights = [len(word) + 1 for word in words]
    total = sum(weights)
    marks, elapsed = [], 0.0
    for word, weight in zip(words, weights):
        marks.append((elapsed, word))
        elapsed += duration * weight / total
    return marks


class EngineError(RuntimeError):
    """Raised when a voice engine cannot produce audio."""


class Engine:
    """Base class for voice engines."""

    id = "base"
    name = "Base"
    needs_network = False

    def list_voices(self) -> list[Voice]:
        raise NotImplementedError

    def synthesize(self, text: str, voice: str, rate: float) -> Clip:
        raise NotImplementedError

    def close(self) -> None:
        """Release any resources. Safe to call more than once."""


def decode_audio(data: bytes, sample_rate: int) -> np.ndarray:
    """Decode compressed audio to mono int16 at ``sample_rate`` using ffmpeg."""
    if not data:
        return np.zeros(0, dtype=np.int16)
    ffmpeg = ffmpeg_command()
    if ffmpeg is None:
        raise EngineError(ffmpeg_missing_message("play this voice"))
    # This runs once per sentence while reading aloud, so it must stay silent
    # and windowless -- see mimick/system.py.
    result = subprocess.run(
        [
            ffmpeg, "-v", "error", "-i", "pipe:0",
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ar", str(sample_rate), "-ac", "1", "pipe:1",
        ],
        input=data,
        capture_output=True,
        check=False,
        **no_window_kwargs(),
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise EngineError(f"Could not decode audio: {message}")
    return np.frombuffer(result.stdout, dtype=np.int16)
