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

    # The fastest this engine will really speak. Asking for more than this is
    # not refused -- it is simply ignored, silently, which is why anything
    # above it has to be taken out of the audio afterwards. See ``render``.
    max_native_rate = 2.0

    def list_voices(self) -> list[Voice]:
        raise NotImplementedError

    def synthesize(self, text: str, voice: str, rate: float) -> Clip:
        raise NotImplementedError

    def render(self, text: str, voice: str, rate: float) -> Clip:
        """Speak ``text`` at ``rate``, however fast that is.

        **Call this, not ``synthesize``.** No engine will speak faster than
        about twice normal: Edge's service clamps its ``prosody rate`` at
        +100% and returns byte-identical audio for 2x, 3x and 6x alike, Kokoro
        clamps its ``speed`` outright, and Piper's ``length_scale`` compresses
        phonemes but not the pauses between them, so 6x asked for yields
        roughly 2.6x heard. Mimick offered 2.5x and 3x for a year and gave 2x.

        So the rate is split in two: as much as the engine will honestly do,
        and the rest taken out of the rendered audio by ``speed_up``. Live
        reading and MP3 conversion both come through here, for the same reason
        the text pipeline has only one path -- split it in two places and the
        two drift.
        """
        native = min(max(rate, 0.1), self.max_native_rate)
        clip = self.synthesize(text, voice, native)
        remainder = rate / native if native > 0 else 1.0
        if remainder > 1.001:
            clip = speed_up(clip, remainder)
        return clip

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


def _atempo_chain(factor: float) -> str:
    """An ``atempo`` filter for ``factor``, split up if it has to be.

    Current ffmpeg takes any factor in one filter, but builds older than 2.4
    cap a single ``atempo`` at 2.0 -- including, potentially, whatever static
    copy ``install.ps1`` pulls down on Windows. Chaining is exact and costs
    nothing, so it is not worth finding out the hard way.
    """
    steps: list[float] = []
    remaining = factor
    while remaining > 2.0:
        steps.append(2.0)
        remaining /= 2.0
    steps.append(remaining)
    return ",".join(f"atempo={step:.6f}" for step in steps)


def speed_up(clip: Clip, factor: float) -> Clip:
    """Play a clip ``factor`` times faster, keeping the pitch where it was.

    ``atempo`` stretches time without transposing, so a voice sped up this way
    still sounds like itself rather than like a chipmunk. Word timings are
    exact multiples of the old ones, so the follow-along highlight stays
    locked to the voice rather than drifting.
    """
    if factor <= 1.001 or clip.pcm.size == 0:
        return clip
    ffmpeg = ffmpeg_command()
    if ffmpeg is None:
        raise EngineError(ffmpeg_missing_message("read this quickly"))
    # Once per sentence during playback, so windowless -- see mimick/system.py.
    result = subprocess.run(
        [
            ffmpeg, "-v", "error",
            "-f", "s16le", "-ar", str(clip.sample_rate), "-ac", "1", "-i", "pipe:0",
            "-filter:a", _atempo_chain(factor),
            "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "pipe:1",
        ],
        input=clip.pcm.tobytes(),
        capture_output=True,
        check=False,
        **no_window_kwargs(),
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise EngineError(f"Could not speed up the voice: {message}")
    return Clip(
        pcm=np.frombuffer(result.stdout, dtype=np.int16),
        sample_rate=clip.sample_rate,
        marks=[(when / factor, word) for when, word in clip.marks],
    )
