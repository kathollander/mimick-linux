"""Microsoft Edge's online neural voices - the ones Edge's Read Aloud uses.

These need an internet connection but sound markedly better than anything that
runs locally, and the service reports word timings, which is what drives the
follow-along highlighting.
"""

from __future__ import annotations

import asyncio

from .base import Clip, Engine, EngineError, Voice, decode_audio

SAMPLE_RATE = 24_000

# Shown at the top of the voice list: the most natural English voices.
PREFERRED = [
    "en-US-AvaNeural", "en-US-AndrewNeural", "en-US-EmmaNeural",
    "en-US-BrianNeural", "en-GB-SoniaNeural", "en-GB-RyanNeural",
    "en-US-JennyNeural", "en-US-GuyNeural", "en-AU-NatashaNeural",
]


def _rate_string(rate: float) -> str:
    """Turn a 1.0-style multiplier into the '+100%' form the service expects."""
    percent = int(round((max(rate, 0.1) - 1.0) * 100))
    return f"{percent:+d}%"


class EdgeEngine(Engine):
    id = "edge"
    name = "Edge Neural (online)"
    needs_network = True

    def __init__(self) -> None:
        self._voices: list[Voice] | None = None

    def list_voices(self) -> list[Voice]:
        if self._voices is not None:
            return self._voices
        try:
            import edge_tts

            raw = asyncio.run(edge_tts.list_voices())
        except Exception as exc:  # network, DNS, service change
            raise EngineError(
                "Could not reach the Edge voice service. Check your internet "
                f"connection.\n\n({exc})"
            ) from exc

        voices = [
            Voice(
                id=item["ShortName"],
                name=item["ShortName"].split("-")[-1].removesuffix("Neural"),
                locale=item["Locale"],
                gender=item.get("Gender", ""),
                engine=self.id,
            )
            for item in raw
        ]
        rank = {voice_id: position for position, voice_id in enumerate(PREFERRED)}
        voices.sort(key=lambda v: (rank.get(v.id, len(PREFERRED)), v.locale, v.name))
        self._voices = voices
        return voices

    def synthesize(self, text: str, voice: str, rate: float) -> Clip:
        if not text.strip():
            return Clip(pcm=decode_audio(b"", SAMPLE_RATE), sample_rate=SAMPLE_RATE)
        try:
            audio, marks = asyncio.run(self._stream(text, voice, rate))
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError(f"Edge voice service failed: {exc}") from exc
        return Clip(pcm=decode_audio(audio, SAMPLE_RATE), sample_rate=SAMPLE_RATE, marks=marks)

    async def _stream(self, text: str, voice: str, rate: float):
        import edge_tts

        audio = bytearray()
        marks: list[tuple[float, str]] = []
        speaker = edge_tts.Communicate(
            text,
            voice,
            rate=_rate_string(rate),
            boundary="WordBoundary",  # without this the service sends sentence marks only
        )
        async for chunk in speaker.stream():
            kind = chunk.get("type")
            if kind == "audio":
                audio += chunk["data"]
            elif kind == "WordBoundary":
                # Offsets arrive in 100-nanosecond ticks.
                marks.append((chunk["offset"] / 1e7, chunk.get("text", "")))
        if not audio:
            raise EngineError("The Edge voice service returned no audio.")
        return bytes(audio), marks
