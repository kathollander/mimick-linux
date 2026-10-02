#!/usr/bin/env python3
"""Is each word highlighted when it is actually spoken, with an offline voice?

    .venv/bin/python tools/check_timing.py

Word timings for Piper voices come from the model's own phoneme durations
(mimick/engines/timing.py). This holds them to the audio, not to themselves:

  1. The patch exposes durations without changing a single sample, and the
     durations add up to the length of the sentence.
  2. Words land on the right spoken groups, including the awkward cases:
     "1,204" spoken as four groups, "of the" run together as one.
  3. After a comma the voice pauses, so the sound's return can be found in the
     audio. When it returns, the word highlighted must be the word being heard:
     the sound comes back after that word's mark and before the next one's. Not
     "exactly on the mark" -- a word opening on /b/ begins with a silent closure
     and one on /h/ with breath too quiet to measure. The offsets are printed,
     and ``estimate_marks`` is held to the same test.
  4. At 4x, through ``Engine.render`` as the reader uses it, the marks are
     the engine's own, divided by exactly what ffmpeg took out.

A timing path that dies is silent (trap 6): the reader falls back to estimates
and nothing says so. This is what notices. Needs en_US-lessac-low downloaded;
the browser version's tools/check_timing.mjs makes the same checks there.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np                                                 # noqa: E402

from mimick.engines import piper, timing                           # noqa: E402
from mimick.engines.base import estimate_marks                     # noqa: E402

KEY = "en_US-lessac-low"
failures: list[str] = []


def check(what: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}{'  — ' + detail if detail else ''}")
    if not ok:
        failures.append(what)


if not piper.is_installed(KEY):
    print(f"no voice {KEY} in {piper.voice_dir()}; download it in Mimick first")
    sys.exit(1)

from piper import PiperVoice, SynthesisConfig                      # noqa: E402

path = piper.voice_dir() / f"{KEY}.onnx"
plain = PiperVoice.load(path)
voice = piper._load_with_timing(path)
rate = voice.config.sample_rate
# No randomness, so two runs of a sentence give the same samples.
STEADY = SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0)


def speak(model, text: str):
    chunks = list(model.synthesize(text, STEADY, include_alignments=True))
    samples = np.concatenate([c.audio_float_array for c in chunks])
    return chunks, samples


# 1. The patch ------------------------------------------------------------------
probe = "Nothing about the method is new; what is new is taking the correction as the result."
_, before = speak(plain, probe)
chunks, after = speak(voice, probe)
check("the model's phoneme durations can be exposed",
      all(c.phoneme_id_samples is not None for c in chunks))
check("exposing them changes not one sample of the audio",
      before.shape == after.shape and np.array_equal(before, after),
      f"{len(before)} vs {len(after)} samples")
summed = sum(int(n) for c in chunks for n in c.phoneme_id_samples)
check("the durations add up to the sentence", summed == len(after),
      f"{summed} vs {len(after)} samples")
check("and the timings are exact, not estimated",
      piper._exact_marks(voice, probe, chunks, rate) is not None)


# 2. Words onto groups ----------------------------------------------------------
def groups_of(text: str):
    chunks, samples = speak(voice, text)
    groups, offset = [], 0
    for c in chunks:
        groups += timing.spoken_groups(list(c.phoneme_ids), c.phonemes,
                                       [int(n) for n in c.phoneme_id_samples],
                                       voice.config.phoneme_id_map, offset)
        offset += len(c.audio_float_array)
    marks = piper._exact_marks(voice, text, chunks, rate)
    return marks, groups, samples


marks, groups, _ = groups_of("The survey reached 1,204 households last spring.")
starts = [g.start / rate for g in groups]
at = {word: starts.index(when) if when in starts else -1 for when, word in marks}
check('"1,204" takes the four groups it is spoken as',
      at["1,204"] == 3 and at["households"] == 7 and len(groups) == 10,
      f"1,204 → group {at['1,204']}, households → group {at['households']}, {len(groups)} groups")

marks, groups, _ = groups_of("She spoke to one of the elders at length.")
when = {word: t for t, word in marks}
shared = [g for g in groups if g.start / rate <= when["of"] < g.end / rate]
check('"of the", run together, share one group in order',
      bool(shared) and shared[0].start / rate == when["of"]
      and when["of"] < when["the"] < shared[0].end / rate,
      f"of at {when['of'] * 1000:.0f} ms, the at {when['the'] * 1000:.0f} ms")

text = "Self-determination isn't co-operation — it's something else, Dr. Osei said."
marks, _, samples = groups_of(text)
times = [t for t, _ in marks] if marks else []
check("a mark for every word, in order, inside the sentence",
      marks is not None and len(marks) == len(text.split())
      and times == sorted(times) and all(0 <= t <= len(samples) / rate for t in times),
      f"{len(marks or [])} marks for {len(text.split())} words")


# 3. Marks against the sound itself ---------------------------------------------
def rms(samples: np.ndarray, from_ms: float, to_ms: float) -> float:
    a = max(0, round(from_ms * rate / 1000))
    b = min(len(samples), round(to_ms * rate / 1000))
    return float(np.sqrt(np.mean(samples[a:b].astype(np.float64) ** 2))) if b > a else 0.0


def sound_returns(samples: np.ndarray, ms: float) -> float:
    """Where sound returns after the quietest moment near ``ms``, in ms."""
    quietest, level = ms, float("inf")
    for t in np.arange(ms - 150, ms + 150, 5):
        v = rms(samples, t, t + 20)
        if v < level:
            level, quietest = v, t
    for t in np.arange(quietest, ms + 400, 1):
        if rms(samples, t, t + 5) > 0.02:
            return float(t)
    return float("inf")


pauses = [
    "Most of them had never been asked, in any formal way, how the land should be used.",
    "The second round took longer, but the answers changed, and the notes were rewritten.",
    "Listen twice, write down the second answer, then read it back aloud.",
]
after_comma = exact_right = estimate_right = 0
offsets, guessed = [], []
for text in pauses:
    chunks, samples = speak(voice, text)
    words = text.split()
    exact = [t * 1000 for t, _ in piper._exact_marks(voice, text, chunks, rate)]
    estimate = [t * 1000 for t, _ in estimate_marks(text, len(samples) / rate)]
    for i in range(1, len(words)):
        if not words[i - 1].endswith(","):
            continue
        after_comma += 1
        returns = sound_returns(samples, exact[i])

        def heard_here(marks: list[float]) -> bool:
            following = marks[i + 1] if i + 1 < len(marks) else float("inf")
            return marks[i] - 10 <= returns < following

        offsets.append(f"{words[i]} {returns - exact[i]:+.0f}")
        guessed.append(f"{returns - estimate[i]:+.0f}")
        exact_right += heard_here(exact)
        estimate_right += heard_here(estimate)
check("after every comma, the word highlighted is the word heard",
      exact_right == after_comma,
      f"{exact_right} of {after_comma}; the estimate manages {estimate_right}")
print(f"          sound returns, ms after the mark:  {', '.join(offsets)}")
print(f"          and after the estimate:            {', '.join(guessed)}")


# 4. At speed, the way the reader asks for it -----------------------------------
engine = piper.PiperEngine()
engine._loaded[KEY] = voice
text = pauses[0]
# Piper varies its pacing from run to run, so compare the clip render actually
# sped up, not a second synthesis of the same text.
rendered = []
synthesize = engine.synthesize
engine.synthesize = lambda *args: rendered.append(synthesize(*args)) or rendered[-1]
fast = engine.render(text, KEY, 4.0)
engine.synthesize = synthesize
native = rendered[0]
factor = 4.0 / engine.max_native_rate
check("at 4× the marks are exactly the engine's own marks, divided",
      len(fast.marks) == len(native.marks) == len(text.split())
      and all(abs(f - n / factor) < 1e-9 for (f, _), (n, _) in zip(fast.marks, native.marks)),
      f"engine at {engine.max_native_rate}×, the rest by {factor:.2f}")
# The native part of the speed-up is length_scale, so its marks must be exact
# too, not an estimate quietly standing in.
check("and exact, not estimated, at the engine's own top speed",
      piper._exact_marks(voice, text, list(voice.synthesize(
          text, SynthesisConfig(length_scale=1 / engine.max_native_rate), include_alignments=True)),
          rate) is not None)


def seconds(run) -> float:
    run()                                   # once to warm up
    start = time.perf_counter()
    for _ in range(3):
        run()
    return (time.perf_counter() - start) / 3


with_timing = seconds(lambda: [engine.synthesize(t, KEY, 1.0) for t in pauses])
without = seconds(lambda: [list(plain.synthesize(t)) for t in pauses])
print(f"          cost: {(with_timing - without) / len(pauses) * 1000:.0f} ms a sentence "
      f"({with_timing:.2f}s with timing, {without:.2f}s without, for {len(pauses)} sentences)")

print()
if failures:
    print(f"{len(failures)} check(s) failed:")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)
print("Words are marked where they are spoken.")
