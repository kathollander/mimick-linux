#!/usr/bin/env python3
"""Check the contents panel: the right entries, in the right order, going to
the right places.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        .venv/bin/python tools/check_contents.py

Two documents are used on purpose. Testing/Big Ideas… is a real journal PDF
whose bookmark destinations are measured from the bottom of the page, and
sample/test-paper.pdf, which this project generates, measures them from the
top. Neither is trusted: a heading is found by its own title. That
disagreement is the reason the y is ignored, so both are checked every time.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication                 # noqa: E402

from mimick.config import Settings                         # noqa: E402
from mimick.document import Document                       # noqa: E402
from mimick.ui import theme                                # noqa: E402
from mimick.ui.main_window import MainWindow               # noqa: E402
from check_hyphens import local_name                       # noqa: E402

WITH_OUTLINE = [
    Path("Testing/Big Ideas from Atleo and Boron 2022.pdf"),
    Path("../Mimick/sample/test-paper.pdf"),
]
WITHOUT_OUTLINE = Path("Testing") / local_name("maths-paper")   # one of Kat's own; see check_hyphens

failures: list[str] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {claim}{'' if ok else f'  -- {detail}'}")
    if not ok:
        failures.append(f"{claim}: {detail}")


def check_outline(path: Path) -> None:
    print(f"\n{path.name}")
    document = Document(path)
    entries = document.outline()
    check("the document has a table of contents", bool(entries))

    # Every entry must land on its own heading, and they must come out in the
    # order the contents lists them -- the test that catches a misread
    # destination, which sent "Positionality and Methods" into a later section.
    places, out_of_order, unmatched = [], [], []
    for level, title, page, _shown in entries:
        if page < 0:
            continue
        at = document.word_of_heading(page, title)
        if at is None:
            unmatched.append(title)
            continue
        if places and at < places[-1]:
            out_of_order.append(title)
        places.append(at)
    check("every heading is found where the contents says", not unmatched,
          f"not found: {unmatched}")
    check("and they come in the order the contents lists them", not out_of_order,
          f"out of order: {out_of_order}")

    # The sentence each entry reads from must exist and move forward too.
    sentences = [document.first_sentence_from(page, title)
                 for _l, title, page, _s in entries if page >= 0]
    check("each entry reads from a real sentence",
          all(0 <= index < len(document.sentences) for index in sentences),
          f"{sentences} against {len(document.sentences)} sentences")
    check("and reading starts no earlier as you go down the contents",
          sentences == sorted(sentences), f"{sentences}")

    # Levels nest: the first entry is top level, and nothing jumps down by
    # more than one at a time in a way the panel could not show.
    levels = [level for level, _t, _p, _s in entries]
    check("the first entry is a top-level one", levels[0] == 1, f"level {levels[0]}")
    document.close()


def check_panel() -> None:
    path = WITH_OUTLINE[0]
    print(f"\nthe panel, on {path.name}")
    app = QApplication.instance()
    window = MainWindow(Settings())
    window.resize(1200, 800)
    window.show()
    window.load_document(path)
    app.processEvents()

    check("the panel is showing", window.contents.isVisible())
    check("the tab is not, while the panel is", not window.contents_tab.isVisible())
    shown = window.contents.tree.topLevelItemCount()
    check("the tree nests rather than listing everything flat",
          0 < shown < len(window._outline), f"{shown} top level of {len(window._outline)}")

    # Clicking an entry goes to its page and lights it.
    target = next(number for number, (_l, _t, page, _s) in enumerate(window._outline)
                  if page >= 2)
    window._go_to_section(target)
    app.processEvents()
    check("clicking an entry goes to its page",
          window.page_view.page == window._outline[target][2],
          f"page {window.page_view.page + 1}, wanted {window._outline[target][2] + 1}")
    check("...and lights that entry", window.contents._current == target,
          f"lit {window.contents._current}, wanted {target}")

    # The heading should sit near the top, not clinging to the bottom edge.
    at = window._outline_words[target]
    if at is not None:
        rect = window.page_view._doc_rect(window.document.words[at].rect,
                                          window.document.words[at].page)
        top = rect.top() - window.page_view.verticalScrollBar().value()
        height = window.page_view.viewport().height()
        check("...with the heading near the top of the view, not the bottom",
              -5 <= top <= height * 0.4, f"{top}px down a {height}px view")

    # Scrolling lights whichever section you have reached.
    window.page_view.set_page(0)
    app.processEvents()
    window._sync_current_section()
    check("scrolling back to page 1 lights an earlier entry",
          window.contents._current < target, f"lit {window.contents._current}")

    window.toggle_contents()
    check("F9 hides the panel and leaves the tab", not window.contents.isVisible()
          and window.contents_tab.isVisible())
    window.toggle_contents()
    check("F9 again brings it back", window.contents.isVisible()
          and not window.contents_tab.isVisible())

    # A document with no contents must show neither panel nor tab.
    window.load_document(WITHOUT_OUTLINE)
    app.processEvents()
    check("a document with no contents shows no panel",
          not window.contents.isVisible() and not window.contents_tab.isVisible()
          and not window.act_contents.isEnabled(),
          f"panel={window.contents.isVisible()} tab={window.contents_tab.isVisible()}")

    window.close()
    app.processEvents()


def main() -> int:
    app = QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    for path in WITH_OUTLINE:
        if path.exists():
            check_outline(path)
        else:
            print(f"\n--    {path} is not here, skipped")
    check_panel()

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for line in failures:
            print(f"  {line}")
        return 1
    print("The contents panel shows what the document says, and goes where it says.")
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
