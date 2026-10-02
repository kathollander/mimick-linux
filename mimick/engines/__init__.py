"""Voice engines available to Mimick."""

from __future__ import annotations

from .base import Clip, Engine, EngineError, Voice
from .edge import EdgeEngine


def build_engine(engine_id: str) -> Engine:
    """Create an engine by id, falling back to the Edge voices."""
    if engine_id == "piper":
        from .piper import PiperEngine

        return PiperEngine()
    if engine_id == "kokoro":
        from .kokoro import KokoroEngine

        return KokoroEngine()
    return EdgeEngine()


__all__ = ["Clip", "Engine", "EngineError", "Voice", "EdgeEngine", "build_engine"]
