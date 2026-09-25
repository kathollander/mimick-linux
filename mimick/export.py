"""Convert a document to an MP3 you can listen to away from the computer.

Audio is streamed to a temporary raw file as it is produced rather than held in
memory, so a long book does not grow the process without bound.

The timing constants are measured on this codebase's voice pipeline rather than
guessed -- see ``docs/ROADMAP.md`` for how to re-measure them.
"""

from __future__ import annotations

import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .document import Sentence
from .engines import Engine, EngineError
from .system import ffmpeg_command, ffmpeg_missing_message, no_window_kwargs

# Measured: 15.1 characters of source text per second of speech at 1x.
CHARS_PER_SECOND_SPEECH = 15.1
# Measured end to end on a full document: ~190 characters of source text per
# second with two workers. Held slightly pessimistic so the estimate tends to
# run long rather than short; the progress dialog refines it from real timings
# once a few sentences are done.
CHARS_PER_SECOND_CONVERT = 175.0
# Silence inserted between sentences.
SENTENCE_GAP = 0.18
CONVERT_WORKERS = 2


def total_chars(sentences: list[Sentence]) -> int:
    return sum(len(sentence.text) for sentence in sentences)


def estimate_listen_seconds(sentences: list[Sentence], speed: float) -> float:
    """Roughly how long the finished audio will run for."""
    speed = max(speed, 0.1)
    return total_chars(sentences) / (CHARS_PER_SECOND_SPEECH * speed) + SENTENCE_GAP * len(sentences)


def estimate_convert_seconds(sentences: list[Sentence]) -> float:
    """Roughly how long the conversion itself will take."""
    return total_chars(sentences) / CHARS_PER_SECOND_CONVERT


def describe_duration(seconds: float) -> str:
    """A human phrase for a length of time."""
    seconds = max(seconds, 0)
    if seconds < 45:
        return "under a minute"
    minutes = seconds / 60
    if minutes < 90:
        return f"about {round(minutes)} minute{'s' if round(minutes) != 1 else ''}"
    hours, rest = divmod(round(minutes), 60)
    if rest == 0:
        return f"about {hours} hour{'s' if hours != 1 else ''}"
    return f"about {hours} h {rest} min"


class ExportWorker(QObject):
    """Speaks every sentence and stitches the result into one audio file."""

    progress = Signal(int, int)   # sentences done, total
    done = Signal(str)            # output path
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, sentences: list[Sentence], engine: Engine, voice: str,
                 rate: float, destination: Path) -> None:
        super().__init__()
        self._sentences = sentences
        self._engine = engine
        self._voice = voice
        self._rate = rate
        self._destination = Path(destination)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    # -- the job -----------------------------------------------------------

    def run(self) -> None:
        if ffmpeg_command() is None:
            self.failed.emit(ffmpeg_missing_message("save audio files"))
            return
        total = len(self._sentences)
        if not total:
            self.failed.emit("There is no readable text to convert.")
            return

        raw_path: Path | None = None
        try:
            raw_path, sample_rate, wrote_any = self._render_to_raw()
        except EngineError as exc:
            self._discard(raw_path)
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self._discard(raw_path)
            self.failed.emit(f"Something went wrong while converting: {exc}")
            return

        if self._cancelled:
            self._discard(raw_path)
            self.cancelled.emit()
            return
        if not wrote_any:
            self._discard(raw_path)
            self.failed.emit("No audio was produced for this document.")
            return

        try:
            self._encode(raw_path, sample_rate)
        except Exception as exc:
            self._discard(raw_path)
            # A half-written MP3 is worse than none at all.
            self._destination.unlink(missing_ok=True)
            self.failed.emit(f"Could not save the audio file: {exc}")
            return
        self._discard(raw_path)
        self.done.emit(str(self._destination))

    def _render_to_raw(self) -> tuple[Path, int, bool]:
        """Synthesize every sentence in order, streaming PCM to a temp file."""
        import numpy as np

        handle = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
        raw_path = Path(handle.name)
        sample_rate = 24_000
        wrote_any = False

        # Two workers roughly halves the wait; results are consumed in order so
        # the audio stays in sequence.
        pool = ThreadPoolExecutor(max_workers=CONVERT_WORKERS, thread_name_prefix="mimick-export")
        try:
            futures = [
                pool.submit(self._engine.synthesize, sentence.text, self._voice, self._rate)
                for sentence in self._sentences
            ]
            with handle:
                for position, future in enumerate(futures, start=1):
                    if self._cancelled:
                        break
                    clip = future.result()
                    if clip.pcm.size:
                        sample_rate = clip.sample_rate
                        handle.write(clip.pcm.tobytes())
                        handle.write(np.zeros(int(sample_rate * SENTENCE_GAP), dtype=np.int16).tobytes())
                        wrote_any = True
                    self.progress.emit(position, len(futures))
        finally:
            # Do not wait on queued work when the user has cancelled.
            pool.shutdown(wait=not self._cancelled, cancel_futures=self._cancelled)
        return raw_path, sample_rate, wrote_any

    def _encode(self, raw_path: Path, sample_rate: int) -> None:
        self._destination.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = ffmpeg_command()
        if ffmpeg is None:
            raise RuntimeError(ffmpeg_missing_message("save audio files"))
        result = subprocess.run(
            [
                ffmpeg, "-y", "-v", "error",
                "-f", "s16le", "-ar", str(sample_rate), "-ac", "1", "-i", str(raw_path),
                "-codec:a", "libmp3lame", "-q:a", "4",
                str(self._destination),
            ],
            capture_output=True,
            check=False,
            **no_window_kwargs(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())

    @staticmethod
    def _discard(raw_path: Path | None) -> None:
        if raw_path is not None:
            raw_path.unlink(missing_ok=True)
