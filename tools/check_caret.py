#!/usr/bin/env python3
"""Check that the text cursor moves and selects the way it is meant to.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        .venv/bin/python tools/check_caret.py [somewhere/paper.pdf]

The cursor is driven by real key events rather than by calling the handlers, so
this also checks that the keys are bound and that nothing else swallows them.
Exits non-zero and says what went wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt                               # noqa: E402
from PySide6.QtTest import QTest                            # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

from mimick.config import Settings                          # noqa: E402
from mimick.ui.main_window import MainWindow                # noqa: E402

SAMPLE = Path("Testing/Big Ideas from Atleo and Boron 2022.pdf")

SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL = Qt.KeyboardModifier.ControlModifier
NONE = Qt.KeyboardModifier.NoModifier


class Check:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def that(self, description: str, got, expected) -> None:
        if got != expected:
            self.failures.append(f"{description}: expected {expected}, got {got}")

    def report(self) -> int:
        if self.failures:
            print("\nThe cursor did not behave:")
            for line in self.failures:
                print(f"  {line}")
            return 1
        print("the cursor moves and selects as it should")
        return 0


def press(target, key, modifier=NONE) -> None:
    """Send a key to a widget, the way a keyboard would.

    QTest delivers to the widget named rather than to whatever holds focus, so
    the target matters: the window for a key meant for the document, the
    control itself when the point is that the control still gets it.
    """
    QTest.keyEvent(QTest.KeyAction.Click, target, key, modifier)
    QApplication.processEvents()


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SAMPLE
    if not path.exists():
        print(f"No document to check against: {path}")
        print("Pass one as an argument, or put the MDPI sample back in Testing/.")
        return 2

    app = QApplication([])
    window = MainWindow(Settings())
    window.show()
    app.processEvents()
    window.load_document(path)
    app.processEvents()

    check = Check()
    view, document = window.page_view, window.document

    # Somewhere in the middle of the first page, well clear of both ends.
    start = document.page_words[0][20].index
    view.set_caret(start)

    press(window, Qt.Key.Key_Right)
    check.that("Right moves on a word", view.caret, start + 1)
    press(window, Qt.Key.Key_Left)
    check.that("Left moves back a word", view.caret, start)
    check.that("moving plainly leaves nothing selected", view.selection, None)

    # Three words to the right, held with Shift. The cursor sits in front of a
    # word, so a cursor three on from the anchor covers three words, ending one
    # short of where it now is.
    for _ in range(3):
        press(window, Qt.Key.Key_Right, SHIFT)
    check.that("Shift+Right selects what it passed", view.selection, (start, start + 2))
    check.that("and leaves the cursor past them", view.caret, start + 3)

    press(window, Qt.Key.Key_Left, SHIFT)
    check.that("Shift+Left gives one back", view.selection, (start, start + 1))

    press(window, Qt.Key.Key_Right)
    check.that("a plain arrow drops the selection", view.selection, None)

    # Home and End work on the line the cursor is on, which is geometry rather
    # than word order, so they are checked against the rectangles.
    view.set_caret(start)
    press(window, Qt.Key.Key_Home)
    first, last = document.line_ends(start)
    check.that("Home goes to the start of the line", view.caret, first)
    press(window, Qt.Key.Key_End)
    check.that("End goes past the end of it", view.caret, last + 1)

    # End leaves the cursor where a line ends and the next begins. Home has to
    # come back to the line you were on, not the one that starts there.
    press(window, Qt.Key.Key_Home)
    check.that("Home after End stays on the same line", view.caret, first)

    press(window, Qt.Key.Key_End)
    press(window, Qt.Key.Key_Home, SHIFT)
    check.that("Shift+Home takes the whole line", view.selection, (first, last))

    # Down and up land on the nearest word across, which is not always the
    # one you left -- words are different widths -- so what is checked is the
    # line, not the word.
    view.set_caret(start)
    line = document.line_ends(start)
    press(window, Qt.Key.Key_Down)
    below = view.caret
    check.that("Down lands on a lower line",
               document.words[below].rect[1] > document.words[start].rect[1], True)
    press(window, Qt.Key.Key_Up)
    check.that("and Up comes back to the line it left",
               document.line_ends(view.caret), line)

    view.set_caret(start)
    sentence = document.words[start].sentence
    press(window, Qt.Key.Key_Left, CTRL)
    check.that("Ctrl+Left goes to the start of the sentence",
               view.caret, document.sentences[sentence].words[0].index)
    press(window, Qt.Key.Key_Right, CTRL)
    check.that("Ctrl+Right goes on to the next one",
               view.caret, document.sentences[sentence + 1].words[0].index)

    # Both ends of the document are places the cursor can reach but not pass.
    view.set_caret(0)
    press(window, Qt.Key.Key_Left)
    check.that("the cursor stops at the beginning", view.caret, 0)
    view.set_caret(len(document.words))
    press(window, Qt.Key.Key_Right)
    check.that("and at the end", view.caret, len(document.words))

    # While the voice is reading, the same keys do what they always did. The
    # voice is not actually started -- that needs a connection and would put
    # sound out of a test -- so ``is_playing`` is stood in for on the class
    # (it is a read-only property, so there is nothing to set) and ``skip`` is
    # replaced by something that only writes down that it was asked.
    view.set_caret(start)
    player = type(window.player)
    playing, skip = player.is_playing, window.player.skip
    asked: list[int] = []
    player.is_playing = property(lambda _self: True)
    window.player.skip = asked.append
    try:
        press(window, Qt.Key.Key_Right)
        check.that("Right skips a sentence while reading, not a word",
                   view.caret, start)
        check.that("and the skip went to the player", asked, [1])
        scroll = view.verticalScrollBar()
        scroll.setValue(0)
        press(window, Qt.Key.Key_Down)
        check.that("Down still scrolls while reading", scroll.value() > 0, True)
    finally:
        player.is_playing = playing
        window.player.skip = skip

    # The cursor keys are bound on the window, so they fire before a focused
    # control ever sees them. Anything that wants the arrows for itself has to
    # be handed them back -- the page number box most of all.
    view.set_caret(start)
    window.page_spin.setFocus()
    app.processEvents()
    page = window.page_spin.value()
    press(window.page_spin, Qt.Key.Key_Up)
    check.that("the page box keeps its own arrows",
               window.page_spin.value(), page + 1)
    check.that("and the cursor stayed where it was", view.caret, start)
    press(window, Qt.Key.Key_Down)
    check.that("nor does the page take Down from it while it is focused",
               view.caret, start)
    view.setFocus()
    app.processEvents()

    window.close()
    app.processEvents()
    return check.report()


if __name__ == "__main__":
    raise SystemExit(main())
