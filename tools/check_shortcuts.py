#!/usr/bin/env python3
"""Check that every key listed in the shortcuts window is really bound.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        .venv/bin/python tools/check_shortcuts.py

Exits non-zero and lists anything the window claims but the app does not do.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QKeySequence, QShortcut          # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

from mimick.config import Settings                         # noqa: E402
from mimick.ui.main_window import MainWindow               # noqa: E402
from mimick.ui.shortcuts_dialog import GROUPS              # noqa: E402

ARROWS = {"↑": "Up", "↓": "Down", "←": "Left", "→": "Right"}
# Entries describing the mouse rather than a key.
MOUSE = re.compile(r"click|drag", re.IGNORECASE)


def bound_keys(window: MainWindow) -> set[str]:
    keys = {shortcut.key().toString() for shortcut in window.findChildren(QShortcut)}

    def walk(menu) -> None:
        for action in menu.actions():
            if action.shortcut().toString():
                keys.add(action.shortcut().toString())
            if action.menu():
                walk(action.menu())

    for entry in window.menuBar().actions():
        if entry.menu():
            walk(entry.menu())
    return keys


def normalise(key: str) -> str:
    for arrow, name in ARROWS.items():
        key = key.replace(arrow, name)
    return QKeySequence(key.strip()).toString()


def main() -> int:
    app = QApplication([])
    window = MainWindow(Settings())
    window.show()
    app.processEvents()

    keys = bound_keys(window)
    # Closing the window shuts its worker threads down; without this the
    # process aborts at exit and the exit code says nothing about the check.
    window.close()
    app.processEvents()
    missing, checked = [], 0
    for heading, rows in GROUPS:
        for listed, _description in rows:
            if MOUSE.search(listed):
                continue
            for part in re.split(r"\s*/\s*|\s{2,}", listed):
                part = part.strip()
                if not part:
                    continue
                checked += 1
                if normalise(part) not in keys:
                    missing.append(f"{heading}: {listed!r} -> {part!r}")

    print(f"{checked} keys listed, {len(keys)} bound in the app")
    if missing:
        print("\nListed but not bound:")
        for line in missing:
            print(f"  {line}")
        return 1
    print("every listed key is bound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
