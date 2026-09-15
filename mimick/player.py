"""Playback: keeps the voice a few sentences ahead of the speakers.

A worker thread renders upcoming sentences in the background while the current
one plays, so there is no gap between sentences. Word timings reported by the
engine are matched back onto the words on the page, which is what the view
highlights.
"""

from __future__ import annotations

import bisect
import re
import threading
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

from .document import Sentence
from .engines import Clip, Engine, EngineError

# Sentences rendered ahead of the one playing. Three was ample at 1x, where a
# sentence takes several seconds to speak and Edge's round trip fits inside it
# comfortably. At 5x a sentence is gone in well under a second while the round
# trip has not moved, so the queue has to be deeper or the reading stutters
# between sentences -- which is exactly where it is least wanted.
PREFETCH = 5
BLOCK_FRAMES = 1024   # write size; small enough that pause feels instant
_NORMALISE = re.compile(r"[^\w']+", re.UNICODE)


def align_marks(sentence: Sentence, clip: Clip) -> list[tuple[float, int]]:
    """Map the engine's spoken-word timings onto indices into ``sentence.words``.

    The engine may split, merge or skip words relative to the page, so we walk
    both sequences forward and match on a normalised form, tolerating gaps.
    """
    if not clip.marks:
        return []
    # Only the spoken words can be matched: citations are passed over.
    spoken = [(position, word.key) for position, word in enumerate(sentence.words)
              if word.spoken]
    aligned: list[tuple[float, int]] = []
    cursor = 0
    # ``mark`` must not be called ``spoken``: rebinding the list above to the
    # mark's own text made ``spoken[offset][1]`` index a single character, which
    # raised IndexError on the very first word and killed the playback thread
    # before a sample reached the speakers.
    for when, mark in clip.marks:
        target = _NORMALISE.sub("", mark).lower()
        if not target:
            continue
        found = None
        for offset in range(cursor, min(cursor + 8, len(spoken))):
            key = spoken[offset][1]
            if key and (key == target or key.startswith(target) or target.startswith(key)):
                found = offset
                break
        if found is None:
            continue
        aligned.append((when, spoken[found][0]))
        cursor = found + 1
    return aligned


class Player(QObject):
    """Reads a list of sentences aloud, one after another."""

    sentence_changed = Signal(int)          # index of the sentence now playing
    word_changed = Signal(int, int)         # sentence index, word index within it
    state_changed = Signal(str)             # "playing" | "paused" | "stopped" | "buffering"
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sentences: list[Sentence] = []
        self._engine: Engine | None = None
        self._voice = ""
        self._rate = 1.0

        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="mimick-tts")
        self._clips: dict[int, Future[Clip]] = {}
        self._lock = threading.Lock()

        self._thread: threading.Thread | None = None
        self._resume = threading.Event()     # set while playing, cleared while paused
        self._stopping = threading.Event()
        self._index = 0
        self._stream: sd.OutputStream | None = None
        self._stream_rate = 0

    # -- configuration -----------------------------------------------------

    def configure(self, sentences: list[Sentence], engine: Engine, voice: str, rate: float) -> None:
        self.stop()
        self._sentences = sentences
        self._engine = engine
        self._voice = voice
        self._rate = rate
        self._discard_cache()
        # A rebuild can leave fewer sentences than before -- skipping the
        # reference list drops a quarter of them -- and the playhead would then
        # sit past the end. ``_run`` exits immediately in that case, so playback
        # fails silently rather than complaining. Clamp instead.
        limit = max(len(self._sentences) - 1, 0)
        if self._index > limit:
            self._index = limit
            self.sentence_changed.emit(self._index)

    def set_voice(self, voice: str, engine: Engine | None = None) -> None:
        """Change voice mid-document; already-rendered audio is dropped."""
        was_playing = self.is_playing
        self.stop()
        if engine is not None:
            self._engine = engine
        self._voice = voice
        self._discard_cache()
        if was_playing:
            self.play(self._index)

    def set_rate(self, rate: float) -> None:
        if abs(rate - self._rate) < 1e-6:
            return
        was_playing = self.is_playing
        self.stop()
        self._rate = rate
        self._discard_cache()
        if was_playing:
            self.play(self._index)

    def _discard_cache(self) -> None:
        with self._lock:
            for future in self._clips.values():
                future.cancel()
            self._clips.clear()

    # -- state -------------------------------------------------------------

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._resume.is_set()

    @property
    def is_active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def index(self) -> int:
        return self._index

    # -- transport ---------------------------------------------------------

    def play(self, index: int | None = None) -> None:
        if index is not None:
            index = max(0, min(index, len(self._sentences) - 1))
            if index != self._index:
                self.stop()
                self._index = index
        if not self._sentences or self._engine is None:
            return
        if self.is_active:
            self._resume.set()
            self.state_changed.emit("playing")
            return
        self._stopping.clear()
        self._resume.set()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mimick-play")
        self._thread.start()

    def pause(self) -> None:
        if self.is_active:
            self._resume.clear()
            self.state_changed.emit("paused")

    def toggle(self) -> None:
        self.pause() if self.is_playing else self.play()

    def stop(self) -> None:
        self._stopping.set()
        self._resume.set()          # release a paused thread so it can exit
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._close_stream()
        self.state_changed.emit("stopped")

    def skip(self, delta: int) -> None:
        target = max(0, min(self._index + delta, len(self._sentences) - 1))
        playing = self.is_playing
        self.stop()
        self._index = target
        self.sentence_changed.emit(target)
        if playing:
            self.play()

    def seek(self, index: int, autoplay: bool = True) -> None:
        playing = self.is_playing or autoplay
        self.stop()
        self._index = max(0, min(index, len(self._sentences) - 1))
        self.sentence_changed.emit(self._index)
        if playing:
            self.play()

    # -- rendering ---------------------------------------------------------

    def _clip_future(self, index: int) -> Future[Clip] | None:
        if not (0 <= index < len(self._sentences)) or self._engine is None:
            return None
        with self._lock:
            future = self._clips.get(index)
            if future is None:
                sentence = self._sentences[index]
                engine, voice, rate = self._engine, self._voice, self._rate
                future = self._pool.submit(engine.render, sentence.text, voice, rate)
                self._clips[index] = future
        return future

    def _prefetch_from(self, index: int) -> None:
        for ahead in range(1, PREFETCH + 1):
            self._clip_future(index + ahead)

    def _trim_cache(self, playhead: int) -> None:
        """Drop clips far from the playhead so memory stays flat.

        This is deliberately keyed off the sentence being played rather than the
        one being fetched -- trimming around a prefetch target would cancel the
        clip currently on the speakers.
        """
        with self._lock:
            stale = [i for i in self._clips
                     if i < playhead - 1 or i > playhead + PREFETCH + 2]
            for index in stale:
                self._clips.pop(index).cancel()

    # -- the playback loop -------------------------------------------------

    def _run(self) -> None:
        try:
            while not self._stopping.is_set() and self._index < len(self._sentences):
                index = self._index
                self.sentence_changed.emit(index)

                future = self._clip_future(index)
                if future is None:
                    break
                self._trim_cache(index)
                self._prefetch_from(index)

                if not future.done():
                    self.state_changed.emit("buffering")
                try:
                    clip = future.result()
                except CancelledError:
                    return          # a deliberate stop, voice change or seek
                except EngineError as exc:
                    self.failed.emit(str(exc))
                    return
                except Exception as exc:
                    self.failed.emit(f"Unexpected problem while speaking: {exc}")
                    return

                if self._stopping.is_set():
                    return
                self.state_changed.emit("playing")
                if not self._speak(index, clip):
                    return
                self._index = index + 1
            if not self._stopping.is_set():
                self.finished.emit()
                self.state_changed.emit("stopped")
        finally:
            self._close_stream()

    def _speak(self, index: int, clip: Clip) -> bool:
        """Push one clip to the speakers. Returns False if playback was stopped."""
        if clip.pcm.size == 0:
            return True
        sentence = self._sentences[index]
        aligned = align_marks(sentence, clip)
        times = [when for when, _ in aligned]
        last_word = -1

        stream = self._ensure_stream(clip.sample_rate)
        if stream is None:
            return False

        position = 0
        total = len(clip.pcm)
        while position < total:
            if self._stopping.is_set():
                return False
            if not self._resume.is_set():
                stream.stop()
                self._resume.wait()
                if self._stopping.is_set():
                    return False
                stream.start()

            block = clip.pcm[position : position + BLOCK_FRAMES]
            try:
                stream.write(np.ascontiguousarray(block))
            except sd.PortAudioError as exc:
                self.failed.emit(f"Audio device problem: {exc}")
                return False
            position += len(block)

            if times:
                elapsed = position / clip.sample_rate
                slot = bisect.bisect_right(times, elapsed) - 1
                if slot >= 0 and aligned[slot][1] != last_word:
                    last_word = aligned[slot][1]
                    self.word_changed.emit(index, last_word)
        return True

    # -- audio device ------------------------------------------------------

    def _ensure_stream(self, sample_rate: int) -> sd.OutputStream | None:
        if self._stream is not None and self._stream_rate == sample_rate:
            if not self._stream.active:
                self._stream.start()
            return self._stream
        self._close_stream()
        try:
            self._stream = sd.OutputStream(
                samplerate=sample_rate, channels=1, dtype="int16", blocksize=BLOCK_FRAMES
            )
            self._stream.start()
            self._stream_rate = sample_rate
        except Exception as exc:
            self.failed.emit(
                "Could not open an audio output device.\n\n"
                f"({exc})"
            )
            self._stream = None
            return None
        return self._stream

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            self._stream_rate = 0

    def shutdown(self) -> None:
        self.stop()
        self._discard_cache()
        self._pool.shutdown(wait=False, cancel_futures=True)
