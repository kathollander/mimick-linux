#!/usr/bin/env python3
"""Check that every kind of file Mimick opens besides a PDF opens and reads like one.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        MIMICK_CACHE_DIR=/tmp/mimick-cache .venv/bin/python tools/check_convert.py

Uses the sample documents in ../Mimick/sample, which the browser version keeps:
one document in seven formats (.docx, .odt, .epub, .html, .md, .rtf, .fb2),
which say the same thing and so can be compared with each other, and one deck
as .pptx and .odp. The window is checked opening a Word file and a deck, whose
conversion runs off the UI thread with a bar.

The conversion is shared with the browser through tools/port.sh, so this covers
both. What it does not cover is how the layout *looks*: that is MuPDF's doing
and a check cannot read a page.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer                          # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

from mimick import convert                                 # noqa: E402
from mimick.config import Settings                         # noqa: E402
from mimick.document import Document                       # noqa: E402
from mimick.ui import theme                                # noqa: E402
from mimick.ui.main_window import MainWindow               # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent.parent / "Mimick" / "sample"
POEM = """The Quiet Hour

A poem about waiting.
Each line kept as written.
  Indented, even.

A second paragraph follows the blank line.
"""

failures: list[str] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {claim}{'' if ok else f'  -- {detail}'}")
    if not ok:
        failures.append(f"{claim}: {detail}")


def check_conversion(work: Path) -> dict[str, Document]:
    """Convert one of each kind and open it; hand back the opened documents."""
    opened: dict[str, Document] = {}

    text_file = work / "poem.txt"
    text_file.write_text(POEM, encoding="utf-8")
    sources = [text_file] + [SAMPLES / f"test-document.{kind}"
                             for kind in ("docx", "odt", "epub", "html", "md", "rtf", "fb2")] \
        + [SAMPLES / f"test-slides.{kind}" for kind in ("pptx", "odp")]

    for source in sources:
        kind = source.suffix.lstrip(".")
        print(f"\n{source.name}")
        if not source.exists():
            check(f"{source.name} is there to convert", False, f"missing: {source}")
            continue
        pdf = convert.converted_pdf(source, work / "cache")
        check("it becomes a PDF", pdf.exists() and pdf.suffix == ".pdf", str(pdf))
        # Converting again must reuse the file, not lay the document out twice:
        # it is what makes the highlights come back on a second opening.
        check("converting it again reuses the same file",
              convert.converted_pdf(source, work / "cache") == pdf)

        document = Document(pdf)
        opened[kind] = document
        check("it has words to read", bool(document.sentences),
              f"{len(document.words)} words, {len(document.sentences)} sentences")
        check("every word knows where it is on the page",
              all(len(word.rect) == 4 and word.rect[3] > word.rect[1]
                  for word in document.words[:200]))
        check("it is titled, so the window and Save a copy have a name",
              bool(document.title.strip()), repr(document.title))

    # A text file keeps its line breaks, which is the whole point for a poem.
    if "txt" in opened:
        lines = [sentence.text for sentence in opened["txt"].sentences]
        joined = " ".join(lines)
        check("the text file's own words all survive",
              "Indented, even." in joined and "The Quiet Hour" in joined, joined[:80])

    # The three formats say the same thing, so they should read the same way.
    shapes = {kind: len(document.words) for kind, document in opened.items()
              if kind in ("docx", "odt", "epub")}
    if len(shapes) == 3:
        spread = max(shapes.values()) - min(shapes.values())
        check("Word, OpenDocument and EPUB find about the same words",
              spread <= max(shapes.values()) * 0.1, f"{shapes}")

    # The simpler kinds say the same words too, near enough: each within a
    # tenth of the Word file's count.
    if "docx" in opened:
        base = len(opened["docx"].words)
        others = {kind: len(opened[kind].words) for kind in ("html", "md", "rtf", "fb2") if kind in opened}
        check("web page, Markdown, Rich Text and FictionBook find about the same words as Word",
              others and all(abs(n - base) <= base * 0.1 for n in others.values()), f"docx {base}, {others}")

    # A deck is a page per slide, each slide's title a contents entry.
    for kind in ("pptx", "odp"):
        if kind in opened:
            deck = opened[kind]
            titles = [title for _l, title, _p, _s in deck.outline()]
            check(f"the .{kind} deck is a page per slide, titled in the contents",
                  deck.page_count >= 2 and len(titles) == deck.page_count, f"{deck.page_count} pages, {titles}")
    moves: list[tuple[int, int]] = []
    convert.converted_pdf(SAMPLES / "test-slides.pptx", work / "fresh", progress=lambda d, t: moves.append((d, t)))
    check("converting a deck says how far it has got, slide by slide",
          bool(moves) and moves[-1][0] == moves[-1][1] and moves[-1][1] >= 2, f"{moves}")

    # Headings become the contents panel's entries.
    for kind in ("docx", "odt"):
        if kind in opened:
            entries = opened[kind].outline()
            check(f"the {kind}'s headings become contents entries", len(entries) >= 2,
                  f"{[title for _l, title, _p, _s in entries]}")
    return opened


def check_window(work: Path) -> None:
    print("\nopening them in the window")
    app = QApplication.instance()
    window = MainWindow(Settings())
    window.show()

    source = SAMPLES / "test-document.docx"
    if not source.exists():
        check("the Word sample is there", False, str(source))
        return

    window.load_document(source)
    app.processEvents()
    check("a Word file opens", window.document is not None
          and bool(window.document.sentences))
    check("...and the window is named after the document, not the PDF made of it",
          "test-document-" not in window.windowTitle(), window.windowTitle())
    recent = [Path(entry).name for entry in (window.settings.get("recent") or [])]
    check("...and Recent lists the file the reader chose, not Mimick's copy",
          recent and recent[0] == source.name, f"{recent[:2]}")

    # Highlights have to survive being reopened: they hang off the converted
    # PDF, so this is really a check that the same PDF is found again.
    window.page_view.select_range(3, 9)
    window.highlight_selection()
    window.save_annotations()
    app.processEvents()
    passage = window.store.items[0].text if window.store.items else ""
    check("a highlight can be made on it", bool(passage), f"{len(window.store.items)}")

    # A deck takes seconds, so it is laid out off the UI thread: the window
    # keeps drawing meanwhile, and a bar comes up if it takes long enough.
    deck = SAMPLES / "test-slides.pptx"
    ticks = []
    beat = QTimer()
    beat.timeout.connect(lambda: ticks.append(1))
    beat.start(20)
    window.load_document(deck)
    beat.stop()
    app.processEvents()
    check("a slide deck opens in the window", window.document is not None and window.document.page_count >= 2
          and bool(window.document.sentences), window.windowTitle())
    check("...laid out off the UI thread, which went on answering meanwhile", len(ticks) >= 1, f"{len(ticks)} ticks")
    window.load_document(source)
    app.processEvents()

    other = work / "poem.txt"
    other.write_text(POEM, encoding="utf-8")
    window.load_document(other)
    app.processEvents()
    window.load_document(source)
    app.processEvents()
    back = [item.text for item in window.store.items]
    check("...and is still there when the file is opened again",
          bool(back) and back[0] == passage, f"{len(back)} found")

    # Something that is not really a Word file must be refused, not crash.
    # _warn puts up a modal box and waits for a click, which never comes with
    # no one at the screen, so it is caught here instead of shown.
    said: list[str] = []
    window._warn = lambda title, body: said.append(f"{title}: {body}")
    broken = work / "not-really.docx"
    broken.write_bytes(b"this is not a zip of any kind")
    before = window.document
    window.load_document(broken)
    app.processEvents()
    check("a file that is not what its name says is refused, and the open one kept",
          window.document is before and bool(said), f"said {said}")
    check("...and the reader is told which file, and what Mimick thought it was",
          bool(said) and broken.name in said[0], f"{said}")

    # The voice's own thread outlives the window, and a Qt process that exits
    # with one still running aborts -- which would make the exit code say
    # nothing about whether these checks passed.
    window.player.stop()
    window.player.shutdown()
    window.close()
    app.processEvents()


def main() -> int:
    app = QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        opened = check_conversion(work)
        for document in opened.values():
            document.close()
        check_window(work)

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for line in failures:
            print(f"  {line}")
        return 1
    print("Every kind of file besides a PDF opens and reads like one.")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # os._exit, not SystemExit: MainWindow fetches the voice list on a QThread,
    # and with no network to answer it that request outlives the bounded wait in
    # closeEvent. Qt then aborts the process as it tears down, and the shell
    # sees 134 whether every check passed or none did. The checks are finished
    # and printed by this point, so leaving the long way round costs nothing
    # and is what makes the exit code mean what it says.
    import os

    os._exit(code)
