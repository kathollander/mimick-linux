#!/usr/bin/env python3
"""Check that every key listed in the shortcuts window is really bound, and
that none of them is one a web browser keeps for itself.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        .venv/bin/python tools/check_shortcuts.py

Exits non-zero and lists anything the window claims but the app does not do,
and any key the browser version could not have.
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
from mimick.ui.sticky_note import LISTED_KEYS             # noqa: E402

ARROWS = {"↑": "Up", "↓": "Down", "←": "Left", "→": "Right"}
# Keys a browser acts on before the page hears them, so the browser version
# of Mimick can never have them. The two versions share one set of shortcuts,
# so this app does not use them either. Chrome and Edge refuse to hand these to
# a page at all; Firefox keeps the same tab and window keys. See "Shortcuts"
# in docs/FUTURE-FEATURES.md.
BROWSER_RESERVED = {
    "Ctrl+N", "Ctrl+Shift+N", "Ctrl+T", "Ctrl+Shift+T", "Ctrl+W", "Ctrl+Shift+W",
    "Ctrl+Tab", "Ctrl+Shift+Tab", "Ctrl+PgUp", "Ctrl+PgDown", "Ctrl+Shift+Q",
    "F11", "F12", "Ctrl+Shift+I", "Ctrl+Shift+J", "Ctrl+Shift+C",
}
# Menu items that exist only on the desktop; the browser version has no Quit.
DESKTOP_ONLY = {"Ctrl+Q"}

# Entries describing the mouse rather than a key.
MOUSE = re.compile(r"click|drag", re.IGNORECASE)


def bound_keys(window: MainWindow) -> set[str]:
    keys = {shortcut.key().toString() for shortcut in window.findChildren(QShortcut)}

    def walk(menu) -> None:
        for action in menu.actions():
            # shortcuts(), not shortcut(): one action can answer to more than
            # one key -- Redo takes Ctrl+Shift+Z and Ctrl+Y -- and shortcut()
            # returns only the first, so the rest would look unbound.
            for sequence in action.shortcuts():
                if sequence.toString():
                    keys.add(sequence.toString())
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
                # A sticky's keys are its editor's own, not the window's.
                answered = keys | ({normalise(k) for k in LISTED_KEYS} if heading == "Sticky notes" else set())
                if normalise(part) not in answered:
                    missing.append(f"{heading}: {listed!r} -> {part!r}")

    reserved = sorted(k for k in keys - DESKTOP_ONLY
                      if k in {QKeySequence(r).toString() for r in BROWSER_RESERVED})

    print(f"{checked} keys listed, {len(keys)} bound in the app")
    if missing:
        print("\nListed but not bound:")
        for line in missing:
            print(f"  {line}")
    if reserved:
        print("\nBound, but a browser keeps these for itself:")
        for key in reserved:
            print(f"  {key}")
    if missing or reserved:
        return 1
    print("every listed key is bound, and none is one a browser keeps")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # os._exit, not SystemExit: MainWindow fetches the voice list on a QThread,
    # and with no network to answer it that request outlives the bounded wait in
    # closeEvent. Qt then aborts the process as it tears down and the shell sees
    # 134, whether every check passed or none did -- which had these checks
    # reading as failures at random. Everything is finished and printed by this
    # point, so skipping the long way out costs nothing.
    import os

    os._exit(code)
