"""Settings and per-document reading positions.

Stored under ``~/.config/mimick`` on Linux and ``%APPDATA%\\Mimick`` on
Windows; :mod:`mimick.system` decides which.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .system import default_cache_dir, default_config_dir

# MIMICK_CONFIG_DIR / MIMICK_CACHE_DIR let a test run against throwaway
# directories instead of the settings and downloads you actually use.
CONFIG_DIR = Path(os.environ.get("MIMICK_CONFIG_DIR") or default_config_dir())
# Annotated copies for documents whose own folder cannot be written to.
NOTES_DIR = CONFIG_DIR / "notes"
CACHE_DIR = Path(os.environ.get("MIMICK_CACHE_DIR") or default_cache_dir())
SETTINGS_PATH = CONFIG_DIR / "settings.json"

DEFAULTS: dict[str, Any] = {
    "engine": "edge",
    "voice": "en-US-AvaNeural",
    "rate": 1.0,
    "zoom": 1.25,
    "click_mode": "click",
    "export_folder": "",
    "show_notes": True,
    "show_plan": False,
    "skip_citations": True,
    "clean_text": True,
    "panel_shows_quotes": True,
    "panel_shows_notes": True,
    "show_annotation_bar": True,
    "note_font": "",
    "note_size": 9.0,
    "author": "",
    "preview_phrase": "",
    "preview_phrases": [],
    "export_finish": {"reveal": True},
    "recent": [],
    "positions": {},
    "region_choices": {},
}


class Settings:
    """A small JSON-backed settings store, saved on every change."""

    def __init__(self) -> None:
        self._data = dict(DEFAULTS)
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key in DEFAULTS:
                    self._data[key] = value

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_PATH)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    # -- reading positions -------------------------------------------------

    def position_for(self, path: Path) -> int:
        return int(self._data["positions"].get(str(path), 0))

    def remember_position(self, path: Path, sentence_index: int) -> None:
        self._data["positions"][str(path)] = int(sentence_index)
        self.save()

    # -- reading-order corrections ----------------------------------------

    @staticmethod
    def _region_key(page: int, rect) -> str:
        """Identify a region by page and position, rounded so it survives reopening."""
        return f"{page}:" + ":".join(str(int(round(value))) for value in rect)

    def region_choices(self, path: Path) -> dict[str, bool]:
        stored = self._data["region_choices"].get(str(path)) or {}
        return {key: bool(value) for key, value in stored.items()}

    def remember_region(self, path: Path, page: int, rect, reads: bool) -> None:
        """Keep the reader's decision about one region of one document."""
        choices = self._data["region_choices"].setdefault(str(path), {})
        choices[self._region_key(page, rect)] = bool(reads)
        self.save()

    def forget_regions(self, path: Path) -> None:
        self._data["region_choices"].pop(str(path), None)
        self.save()

    def note_recent(self, path: Path) -> None:
        recent = [p for p in self._data["recent"] if p != str(path)]
        recent.insert(0, str(path))
        self._data["recent"] = recent[:12]
        self.save()
