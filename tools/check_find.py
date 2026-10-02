#!/usr/bin/env python3
"""Check that Find in document finds what is on the page, and only that.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        .venv/bin/python tools/check_find.py [document.pdf ...]

With no arguments it uses whatever is in Testing/. Exits non-zero on the first
failure, saying what was expected and what happened.

The searching itself lives in document.py, which the browser version runs too,
so this is the check for both.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt                              # noqa: E402
from PySide6.QtTest import QTest                           # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

from mimick.config import Settings                         # noqa: E402
from mimick.document import Document                       # noqa: E402
from mimick.ui import theme                                # noqa: E402
from mimick.ui.main_window import MainWindow               # noqa: E402

failures: list[str] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {claim}{'' if ok else f'  -- {detail}'}")
    if not ok:
        failures.append(f"{claim}: {detail}")


# -- the searching itself ----------------------------------------------------


def check_document(path: Path) -> None:
    print(f"\n{path.name}")
    document = Document(path)
    print(f"  {len(document.words)} words, {document.page_count} pages")

    # A word taken from the middle of the document must find itself, and the
    # match must be the word that was asked for.
    sample = next((w for w in document.words[50:] if len(w.text) > 6 and w.text.isalpha()), None)
    if sample is not None:
        found, _ = document.find(sample.text)
        check(f"{sample.text!r} finds itself",
              any(first <= sample.index <= last for first, last, _page in found),
              f"{len(found)} matches, none covering word {sample.index}")

    # Every match must really contain the query, read back off the page.
    found, _ = document.find("the")
    wrong = [(f, l) for f, l, _p in found[:200]
             if "the" not in document.selection_text(f, l).casefold()]
    check("every match for 'the' contains it", not wrong, f"{wrong[:3]}")

    # Case folding, both ways round.
    lower, _ = document.find("the", match_case=False)
    exact, _ = document.find("the", match_case=True)
    check("Match case narrows the result", len(exact) <= len(lower),
          f"{len(exact)} exact vs {len(lower)} folded")

    # Nonsense finds nothing, and an empty query is not a search.
    check("nonsense finds nothing", document.find("qxzjvwk")[0] == [])
    check("an empty query finds nothing", document.find("")[0] == [])
    check("spaces alone find nothing", document.find("   ")[0] == [])

    # Matches come back in document order, which is what stepping relies on.
    order = [first for first, _l, _p in document.find("a")[0]]
    check("matches are in document order", order == sorted(order))

    # A word the typesetter broke across a line must still be findable whole.
    broken = [(i, w) for i, w in enumerate(document.words)
              if w.joins_next and w.text.endswith("-")]
    if broken:
        index, word = broken[0]
        whole = document.selection_text(index, index + 1)
        found, _ = document.find(whole)
        check(f"the broken word {word.text!r}+{document.words[index + 1].text!r} "
              f"is found as {whole!r}",
              any(first <= index <= last for first, last, _p in found),
              f"{len(found)} matches, none covering word {index}")
    else:
        print("  --    no words broken across a line in this document")

    # A rebuild renumbers every word; a search afterwards must still be in range.
    document.set_clean_text(not document.clean_text)
    found, _ = document.find("the")
    check("after a rebuild the matches are in range",
          all(0 <= f <= l < len(document.words) for f, l, _p in found),
          f"{len(document.words)} words now")
    document.close()


# -- the bar ----------------------------------------------------------------


def check_bar(path: Path) -> None:
    print(f"\nthe find bar, on {path.name}")
    window = MainWindow(Settings())
    window.show()
    window.activateWindow()
    window.load_document(path)
    app = QApplication.instance()
    app.processEvents()

    check("the bar starts hidden", not window.find_bar.isVisible())
    window.open_find()
    app.processEvents()
    check("Ctrl+F shows it and takes the keyboard",
          window.find_bar.isVisible() and window.find_bar.box.hasFocus())

    # While the box has the focus the page's own keys must be off, or a space
    # typed into the box starts the voice.
    live = [s for s in window._page_shortcuts if s.isEnabled()]
    check("the page's keys are suspended while typing", not live,
          f"{len(live)} still live")

    window.find_bar.box.setText("the")
    app.processEvents()
    total = len(window._matches)
    check("typing searches", total > 0, "no matches for 'the'")
    check("the count says which match this is",
          window.find_bar.count.text() == f"1 of {total}"
          or " of " in window.find_bar.count.text(),
          repr(window.find_bar.count.text()))
    check("the match is selected, not just lit", window.page_view.selection is not None)

    at = window._current_match
    QTest.keyClick(window.find_bar.box, Qt.Key.Key_Return)
    check("Enter goes to the next match", window._current_match == at + 1)
    QTest.keyClick(window.find_bar.box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    check("Shift+Enter goes back", window._current_match == at)
    QTest.keyClick(window.find_bar.box, Qt.Key.Key_F3)
    check("F3 goes forward too", window._current_match == at + 1)

    # Stepping back off the front wraps to the end rather than stopping.
    window._show_match(0)
    window._step_match(-1)
    check("stepping back from the first wraps to the last",
          window._current_match == total - 1, f"landed on {window._current_match}")

    # A space belongs to the box, not to the player.
    QTest.keyClicks(window.find_bar.box, " ma")
    app.processEvents()
    check("a space typed into the box does not start the voice",
          not window.player.is_playing and " " in window.find_bar.box.text(),
          f"box={window.find_bar.box.text()!r} playing={window.player.is_playing}")

    window.find_bar.box.setText("qxzjvwk")
    app.processEvents()
    check("nothing found says so", window.find_bar.count.text() == "No matches",
          repr(window.find_bar.count.text()))
    check("the arrows are dead with nothing to step through",
          not window.find_bar.next_button.isEnabled())

    window.find_bar.box.setText("the")
    app.processEvents()
    kept = window.page_view.selection
    QTest.keyClick(window.find_bar.box, Qt.Key.Key_Escape)
    app.processEvents()
    check("Esc closes the bar", not window.find_bar.isVisible())
    check("Esc clears the tints", window.page_view._matches == [])
    check("Esc leaves the match selected", window.page_view.selection == kept,
          f"{window.page_view.selection} vs {kept}")
    back = [s for s in window._page_shortcuts if s.isEnabled()]
    check("the page gets its keys back",
          len(back) == len(window._page_shortcuts),
          f"{len(back)} of {len(window._page_shortcuts)}")

    window.close()
    app.processEvents()


def main() -> int:
    here = Path(__file__).resolve().parent.parent
    given = [Path(argument) for argument in sys.argv[1:]]
    documents = given or sorted((here / "Testing").glob("*.pdf"))
    if not documents:
        print("No documents to check. Put a PDF in Testing/ or name one.")
        return 2

    app = QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    for path in documents:
        check_document(path)
    # The bar is the same bar whatever is open, so one document is enough.
    check_bar(documents[0])

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for line in failures:
            print(f"  {line}")
        return 1
    print(f"Find works, over {len(documents)} document(s).")
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
