#!/usr/bin/env python3
"""Check Reading → What repeats: the terms a document keeps coming back to.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        .venv/bin/python tools/check_themes.py

The counting (mimick/themes.py) against sentences made up here, so the awkward
cases are pinned; then the window's dialog on the test paper, and that choosing
a term finds it. themes.py is shared with the browser through tools/port.sh.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget    # noqa: E402

from mimick.config import Settings                         # noqa: E402
from mimick.themes import page_ranges, repeats             # noqa: E402
from mimick.ui import theme                                # noqa: E402
from mimick.ui.main_window import MainWindow               # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent.parent / "Mimick" / "sample"
failures: list[str] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {claim}{'' if ok else f'  -- {detail}'}")
    if not ok:
        failures.append(f"{claim}: {detail}")


@dataclass
class S:
    text: str
    page: int


def check_counting() -> None:
    print("counting")
    sentences = [
        S("Residential schools were run by the churches.", 0),
        S("The residential school system lasted a century.", 1),
        S("Survivors of residential schools spoke to the commission.", 1),
        S("Students' language was forbidden at the schools.", 4),
        S("A student's language is part of who they are; language matters.", 5),
        S("Every student deserves that.", 5),
        S("See www.example.gov.on.ca and www.example.gov.on.ca again, www.example.gov.on.ca.", 6),
        S("The the the and and of of of.", 7),
    ]
    found = repeats(sentences)
    phrases = {e["term"]: e for e in found["phrases"]}
    words = {e["term"]: e for e in found["words"]}
    check("a phrase used three times is listed, singular and plural as one",
          "residential schools" in phrases and phrases["residential schools"]["count"] == 3, found["phrases"])
    check("...in the spelling the document uses most", "residential school" not in phrases, list(phrases))
    check("...with the pages it is on", phrases.get("residential schools", {}).get("pages") == [0, 1],
          phrases.get("residential schools"))
    check("a word that is only ever half of a listed phrase is not listed again",
          "residential" not in words, list(words))
    check("a word used on its own often enough is", "language" in words and words["language"]["count"] == 3, words)
    check("words that say nothing about the text never count", not ({"the", "and", "of"} & set(words)), list(words))
    check("nor do web addresses", not ({"example", "gov", "www"} & set(words)), list(words))
    check("a possessive counts as its word, and the plural with it",
          words.get("students", words.get("student", {})).get("count") == 3, words)
    check("page ranges are written as a reader would", page_ranges([0, 1, 2, 6, 8, 9]) == "1–3, 7, 9–10",
          page_ranges([0, 1, 2, 6, 8, 9]))
    empty = repeats([])
    check("an empty document lists nothing, without failing", empty == {"phrases": [], "words": []}, empty)


def check_window() -> None:
    print("\nthe window")
    app = QApplication.instance()
    window = MainWindow(Settings())
    window.show()
    window.load_document(SAMPLES / "test-paper.pdf")
    app.processEvents()
    check("Reading offers What repeats", window.act_repeats.isEnabled())

    seen: dict = {}

    def look() -> None:
        dialog = getattr(window, "_repeats_dialog", None)
        if dialog is None or not dialog.isVisible():
            QTimer.singleShot(100, look)
            return

        listing = dialog.findChild(QListWidget)
        rows = [listing.item(n) for n in range(listing.count())]
        terms = [row.data(Qt.ItemDataRole.UserRole) for row in rows if row.data(Qt.ItemDataRole.UserRole)]
        seen["rows"] = [row.text() for row in rows]
        seen["term"] = terms[0] if terms else None
        if terms:
            listing.setCurrentItem(next(row for row in rows if row.data(Qt.ItemDataRole.UserRole) == terms[0]))
            listing.itemActivated.emit(listing.currentItem())
        else:
            dialog.reject()

    QTimer.singleShot(100, look)
    window.show_repeats()
    app.processEvents()
    rows = seen.get("rows", [])
    check("it lists what the test paper repeats, with counts and pages",
          bool(seen.get("term")) and any("times, p. " in row for row in rows), rows[:5])
    check("choosing one opens Find with it", window.find_bar.isVisible()
          and window.find_bar.box.text() == seen.get("term"), window.find_bar.box.text())

    window.player.stop()
    window.player.shutdown()
    window.close()
    app.processEvents()


def main() -> int:
    app = QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    check_counting()
    check_window()
    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for line in failures:
            print(f"  {line}")
        return 1
    print("What repeats counts what it should.")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)          # see check_convert.py: the voice-list thread outlives the window
