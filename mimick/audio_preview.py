"""A small player for one-off clips, with real pause and resume.

``sounddevice.play`` can only start and stop, so previews use their own output
stream and feed it from a buffer that a pause flag can hold back.
"""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd


class ClipPlayer:
    """Plays a single clip, pausable, with a callback when it ends."""

    def __init__(self) -> None:
        self._stream: sd.OutputStream | None = None
        self._pcm: np.ndarray | None = None
        self._position = 0
        self._paused = False
        self._lock = threading.Lock()
        self.on_finished = None       # called from the audio thread

    # -- state -------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._stream is not None and self._pcm is not None

    @property
    def playing(self) -> bool:
        return self.active and not self._paused

    @property
    def paused(self) -> bool:
        return self.active and self._paused

    # -- transport ---------------------------------------------------------

    def play(self, pcm: np.ndarray, sample_rate: int) -> None:
        self.stop()
        if pcm is None or len(pcm) == 0:
            return
        with self._lock:
            self._pcm = np.asarray(pcm).reshape(-1)
            self._position = 0
            self._paused = False
        try:
            self._stream = sd.OutputStream(
                samplerate=sample_rate, channels=1, dtype="int16",
                blocksize=1024, callback=self._feed, finished_callback=self._ended,
            )
            self._stream.start()
        except Exception:
            self._stream = None
            self._pcm = None
            raise

    def toggle(self) -> None:
        if self.active:
            self._paused = not self._paused

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        with self._lock:
            self._pcm = None
            self._position = 0
            self._paused = False
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:
                pass

    # -- the audio thread --------------------------------------------------

    def _feed(self, outdata, frames, _time, _status) -> None:
        with self._lock:
            pcm, position, paused = self._pcm, self._position, self._paused
            if pcm is None:
                outdata[:] = 0
                raise sd.CallbackStop
            if paused:
                outdata[:] = 0
                return
            chunk = pcm[position : position + frames]
            self._position = position + len(chunk)

        outdata[: len(chunk), 0] = chunk
        if len(chunk) < frames:
            outdata[len(chunk):] = 0
            raise sd.CallbackStop

    def _ended(self) -> None:
        callback = self.on_finished
        if callback is not None:
            callback()
