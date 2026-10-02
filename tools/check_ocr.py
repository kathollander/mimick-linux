#!/usr/bin/env python3
"""Check that a scanned PDF has its text recognised and can then be read.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        MIMICK_CACHE_DIR=/tmp/mimick-cache .venv/bin/python tools/check_ocr.py

Needs Tesseract's English data (``sudo apt install tesseract-ocr-eng``, or
``TESSDATA_PREFIX`` pointing at a folder holding ``eng.traineddata``). The
scan is made here, by drawing the browser version's ``sample/test-paper.pdf``
as pictures, so what the recognised text should say is known.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf                                             # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox    # noqa: E402

from mimick import ocr                                     # noqa: E402
from mimick.config import CACHE_DIR, Settings              # noqa: E402
from mimick.ui import theme                                # noqa: E402
from mimick.ui.main_window import MainWindow               # noqa: E402

PAPER = Path(__file__).resolve().parent.parent.parent / "Mimick" / "sample" / "test-paper.pdf"

failures: list[str] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {claim}{'' if ok else f'  -- {detail}'}")
    if not ok:
        failures.append(f"{claim}: {detail}")


def make_scan(out: Path) -> None:
    """``test-paper.pdf`` with every page a picture and no words."""
    with pymupdf.open(PAPER) as source, pymupdf.open() as scan:
        for page in source:
            picture = page.get_pixmap(dpi=150)
            scan.new_page(width=page.rect.width, height=page.rect.height).insert_image(
                page.rect, pixmap=picture)
        scan.save(out)


def main() -> int:
    if not ocr.available():
        print("Tesseract's English data is not installed: sudo apt install tesseract-ocr-eng")
        return 1
    app = QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    with tempfile.TemporaryDirectory() as folder:
        scan = Path(folder) / "scanned paper.pdf"
        make_scan(scan)
        with pymupdf.open(scan) as doc:
            textless = ocr.pages_without_text(doc)
        check("the scan made here has no words on any page", len(textless) == 3, f"{textless}")

        window = MainWindow(Settings())
        window.show()
        said: list[str] = []
        window._warn = lambda title, body: said.append(f"{title}: {body}")

        # More pages than are recognised by themselves: the reader is asked,
        # and saying no leaves the scan unopened, with the reason given.
        automatic, ocr.AUTOMATIC_PAGES = ocr.AUTOMATIC_PAGES, 1
        asked: list[str] = []
        question = QMessageBox.question
        QMessageBox.question = lambda *args, **kw: (asked.append(args[2]), QMessageBox.StandardButton.No)[1]
        window.load_document(scan)
        app.processEvents()
        QMessageBox.question = question
        ocr.AUTOMATIC_PAGES = automatic
        check("a long scan asks before recognising, with how long it takes",
              bool(asked) and "minute" in asked[0], f"{asked}")
        check("...and saying no opens nothing, and says why",
              window.document is None and bool(said) and "No readable text" in said[0], f"{said}")

        # A short one is recognised as it opens.
        started = time.monotonic()
        window.load_document(scan)
        app.processEvents()
        took = time.monotonic() - started
        text = " ".join(" ".join(w.text for w in s.words) for s in window.document.sentences) \
            if window.document else ""
        check("a short scan is recognised as it opens, and can be read",
              "Listening to the Page" in text and "students" in text, text[:120])
        check("...from a copy in the cache, not by writing to the scan",
              window.document is not None and ocr.is_recognised(window.document.path, CACHE_DIR), "")
        with pymupdf.open(scan) as doc:
            check("...and the scan itself is untouched", len(ocr.pages_without_text(doc)) == 3, "")
        check("...and Recognise the text is not offered again",
              not window.act_recognise.isEnabled(), "")
        check("...and Recent lists the scan the reader chose",
              Path((window.settings.get("recent") or [""])[0]).name == scan.name,
              f"{window.settings.get('recent')}")

        # A highlight on it comes back when the scan is opened again, which
        # finds the recognised copy at once instead of recognising again.
        window.page_view.select_range(0, 4)
        window.highlight_selection()
        window.save_annotations()
        passage = window.store.items[0].text if window.store.items else ""
        window.load_document(PAPER)
        app.processEvents()
        started = time.monotonic()
        window.load_document(scan)
        app.processEvents()
        again = time.monotonic() - started
        check("opening the scan again finds the recognised copy, not recognising again",
              again < took / 2, f"{again:.1f} s against {took:.1f} s")
        back = [item.text for item in window.store.items]
        check("...and the highlight made on it is there", bool(passage) and back[:1] == [passage],
              f"{passage!r} {back}")
        check("no warnings along the way besides the one said no to", len(said) == 1, f"{said}")

        window.player.stop()
        window.player.shutdown()
        window.close()
        app.processEvents()

    print("\nall passed" if not failures else f"\n{len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
