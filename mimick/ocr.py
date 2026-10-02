"""Recognise the text in a scanned PDF, so it can be read aloud.

A scan is pictures of pages and no words. MuPDF has Tesseract built in, so
PyMuPDF reads the words off each picture itself; all it needs from the system
is Tesseract's English data (``tesseract-ocr-eng``, which ``install.sh``
installs). The words are then written back into a copy of the PDF as
invisible text, each stretched over the box it was found in -- the same way
the browser version does it (``add_text_layer`` in its ``reader.py``) -- so
reading, highlights, Find and Save a copy all see an ordinary PDF, and other
PDF readers can search the copy too.

The copy is kept under the cache directory, named for the scan and its
content like ``convert.converted_pdf``'s, so opening the same scan again finds
it without recognising anything, and brings its highlights and notes with it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf

# Tesseract reads small print far better at 300 dpi than at a scan's usual 150
# or 200; much above it only costs time. About 2 s a page on a laptop.
DPI = 300
SECONDS_PER_PAGE = 2.5
# Up to this many pages are recognised as a scan opens, as in the browser;
# more, and the reader is asked first, since it can take minutes.
AUTOMATIC_PAGES = 20


class Stopped(Exception):
    """The reader stopped recognition part-way."""


def available() -> bool:
    """Whether Tesseract's language data is installed, which is all PyMuPDF needs."""
    try:
        return bool(pymupdf.get_tessdata())
    except Exception:
        return False


def pages_without_text(doc: pymupdf.Document) -> list[int]:
    """Pages that are a picture and no words: scanned, and worth recognising."""
    return [page.number for page in doc
            if not page.get_text("text").strip() and page.get_images()]


def recognised_path(source, cache_dir) -> Path:
    """Where the recognised copy of ``source`` is, or would be, kept."""
    source = Path(source)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    return Path(cache_dir) / "recognised" / f"{source.stem[:60]}-{stamp}.pdf"


def is_recognised(path, cache_dir) -> bool:
    """Whether ``path`` is a copy this module made -- whose wordless pages, if
    it has any, were tried and are pictures, not text."""
    return Path(path).resolve().parent == (Path(cache_dir) / "recognised").resolve()


def add_text_layer(doc: pymupdf.Document, number: int, words) -> None:
    """Write ``words`` -- ``(x0, y0, x1, y1, text, ...)`` in PDF points -- into
    page ``number`` as invisible text, each word stretched to fill its box."""
    page = doc[number]
    font = pymupdf.Font("helv")
    height_per_size = font.ascender - font.descender
    derotate = page.derotation_matrix
    for x0, y0, x1, y1, text, *_ in words:
        text = str(text).strip()
        if not text or x1 <= x0 or y1 <= y0:
            continue
        size = (y1 - y0) / height_per_size
        width = font.text_length(text, size)
        if size <= 0 or width <= 0:
            continue
        start = pymupdf.Point(x0, y1 + font.descender * size) * derotate
        page.insert_text(start, text, fontsize=size, fontname="helv", render_mode=3,
                         rotate=page.rotation,
                         morph=(start, pymupdf.Matrix((x1 - x0) / width, 1)))


def recognise(source, out, pages=None, progress=None, stopped=None) -> Path:
    """A copy of ``source`` with the words on its textless pages written in,
    saved to ``out``. ``progress(done, total)`` is called after each page;
    ``stopped()`` answering true abandons it, raising ``Stopped`` and leaving
    nothing behind."""
    out = Path(out)
    doc = pymupdf.open(source)
    try:
        todo = pages_without_text(doc) if pages is None else list(pages)
        for done, number in enumerate(todo):
            if stopped is not None and stopped():
                raise Stopped()
            page = doc[number]
            textpage = page.get_textpage_ocr(dpi=DPI, full=True, language="eng")
            # The words come back in the page's unrotated space, which is what
            # add_text_layer's derotation expects.
            add_text_layer(doc, number, page.get_text("words", textpage=textpage))
            if progress is not None:
                progress(done + 1, len(todo))
        out.parent.mkdir(parents=True, exist_ok=True)
        # Written beside and moved into place, so a half-written PDF is never
        # left for the next open to find and trust.
        partial = out.with_suffix(".part")
        doc.save(partial, garbage=3, deflate=True)
        partial.replace(out)
    finally:
        doc.close()
    return out
