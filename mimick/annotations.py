"""Highlights and margin notes, stored as real PDF annotations.

Everything written here is standard PDF markup, so notes made in Mimick open
correctly in Okular, Acrobat, Zotero or anything else, and notes made in those
programs show up here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# Highlight colours, as (name, r, g, b) with components from 0 to 1.
COLOURS: list[tuple[str, tuple[float, float, float]]] = [
    ("Yellow", (1.00, 0.87, 0.35)),
    ("Green", (0.62, 0.90, 0.60)),
    ("Blue", (0.55, 0.80, 1.00)),
    ("Pink", (1.00, 0.65, 0.80)),
]
DEFAULT_COLOUR = COLOURS[0][1]

# Mimick records the word range it highlighted in a private key on the
# annotation, so the PDF's own Subject field stays free for the reader's own
# heading. Other programs ignore keys they do not know.
_RANGE_KEY = "MimickRange"
_RANGE_PREFIX = "mimick-range:"      # how older files stored it

# Mimick never writes into the PDF you opened. Highlights and notes go to a
# companion file beside it, named the same way the Save a copy dialog has
# always suggested, so a document you were given back is still the document you
# were given. The companion is an ordinary PDF: the notes in it are real PDF
# annotations, and any reader can open it.
NOTES_SUFFIX = " (notes)"


def is_companion(path) -> bool:
    """Whether a path is itself one of Mimick's annotated copies."""
    return Path(path).stem.endswith(NOTES_SUFFIX)


def companion_for(path) -> Path:
    """The annotated copy belonging to a document, beside the original.

    Opening a companion returns itself, so a second round of notes is written
    back to the same file rather than to "X (notes) (notes).pdf".
    """
    path = Path(path)
    if is_companion(path):
        return path
    return path.with_name(path.stem + NOTES_SUFFIX + (path.suffix or ".pdf"))


def fallback_companion_for(path, notes_dir) -> Path:
    """Where the copy goes when the original's own folder cannot be written to.

    A PDF opened from a read-only place -- a mounted share, a downloads folder
    on a locked-down machine, the sample documents inside an installed copy --
    still has to be annotatable.
    """
    return Path(notes_dir) / companion_for(path).name


def existing_companion(path, notes_dir) -> Path | None:
    """An annotated copy already written for this document, if there is one."""
    path = Path(path)
    if is_companion(path):
        return None
    for candidate in (companion_for(path), fallback_companion_for(path, notes_dir)):
        if candidate.exists() and candidate != path:
            return candidate
    return None


@dataclass
class Annotation:
    """One highlight, optionally with a note attached."""

    page: int
    rects: list[tuple[float, float, float, float]]
    text: str = ""                     # the highlighted words
    title: str = ""                    # optional heading, shown by other readers
    note: str = ""                     # the reader's own comment
    colour: tuple[float, float, float] = DEFAULT_COLOUR
    first_word: int = -1
    last_word: int = -1
    xref: int = 0                      # the PDF object, 0 until saved
    _top: float = field(default=0.0, repr=False)

    @property
    def top(self) -> float:
        """Vertical position on the page, used to lay notes out in the margin."""
        return min((rect[1] for rect in self.rects), default=self._top)

    @property
    def preview(self) -> str:
        flat = " ".join(self.text.split())
        return flat if len(flat) <= 90 else flat[:87] + "…"

    @property
    def heading(self) -> str:
        """What to show at the top of the card, if anything."""
        return (self.title or "").strip()


def _parse_range(raw: str) -> tuple[int, int]:
    try:
        first, last = raw.split("-")
        return int(first), int(last)
    except (ValueError, AttributeError):
        return -1, -1


def _read_range(document, annot, subject: str) -> tuple[int, int]:
    """The word range, from our private key or from an older file's Subject."""
    try:
        kind, value = document.doc.xref_get_key(annot.xref, _RANGE_KEY)
        if kind and value:
            return _parse_range(str(value).strip("()"))
    except Exception:
        pass
    if subject.startswith(_RANGE_PREFIX):
        return _parse_range(subject[len(_RANGE_PREFIX):])
    return -1, -1


def _write_range(document, xref: int, first: int, last: int) -> None:
    try:
        document.doc.xref_set_key(xref, _RANGE_KEY, f"({first}-{last})")
    except Exception:
        pass          # the highlight still works, it just cannot be re-linked


def _verify(path: Path, pages: int, notes: int) -> None:
    """Check a just-written PDF before it is allowed to replace a good one."""
    try:
        with pymupdf.open(path) as written:
            found_pages = written.page_count
            found_notes = sum(
                len(list(written.load_page(number).annots(
                    types=(pymupdf.PDF_ANNOT_HIGHLIGHT,))))
                for number in range(found_pages)
            )
    except Exception as exc:
        raise OSError(f"the PDF Mimick just wrote will not open again ({exc})") from exc
    if found_pages != pages or found_notes != notes:
        raise OSError(
            f"the PDF Mimick just wrote came back with {found_pages} pages and "
            f"{found_notes} highlights, not {pages} and {notes}"
        )


class AnnotationStore:
    """Reads and writes the annotations of one open document."""

    def __init__(self, document, author: str = "") -> None:
        self._document = document
        self.author = author or "Mimick"
        self.items: list[Annotation] = []
        self.dirty = False
        self.reload()

    # -- reading -----------------------------------------------------------

    def reload(self) -> None:
        """Load highlights already present in the file."""
        self.items = []
        doc = self._document.doc
        for number in range(doc.page_count):
            page = doc.load_page(number)
            for annot in page.annots(types=(pymupdf.PDF_ANNOT_HIGHLIGHT,)):
                info = annot.info or {}
                subject = (info.get("subject") or "").strip()
                first, last = _read_range(self._document, annot, subject)
                # An older file kept our bookkeeping in Subject; do not show it.
                heading = "" if subject.startswith(_RANGE_PREFIX) else subject
                rects = _quad_rects(annot)
                item = Annotation(
                    page=number,
                    rects=rects,
                    title=heading,
                    note=(info.get("content") or "").strip(),
                    colour=_annot_colour(annot),
                    first_word=first,
                    last_word=last,
                    xref=annot.xref,
                )
                if first >= 0 and last >= first:
                    item.text = self._document.selection_text(first, last)
                elif rects:
                    item.text = self._text_in(number, rects)
                self.items.append(item)
        self.items.sort(key=lambda a: (a.page, a.top))

    def _text_in(self, page_number: int, rects: list) -> str:
        """Recover the highlighted words for annotations made elsewhere."""
        words = self._document.page_words.get(page_number, [])
        found = []
        for word in words:
            wx0, wy0, wx1, wy1 = word.rect
            cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
            if any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in rects):
                found.append(word.text)
        return " ".join(found)

    # -- writing -----------------------------------------------------------

    def add(self, first_word: int, last_word: int,
            colour: tuple[float, float, float] = DEFAULT_COLOUR,
            note: str = "", title: str = "", author: str = "") -> Annotation | None:
        """Highlight a range of words."""
        words = self._document.words[first_word : last_word + 1]
        if not words:
            return None
        page_number = words[0].page
        # A highlight lives on one page; keep only the words on the first one.
        on_page = [w for w in words if w.page == page_number]
        from .document import _merge_rects

        rects = _merge_rects([w.rect for w in on_page])
        page = self._document.doc.load_page(page_number)
        annot = page.add_highlight_annot(quads=[pymupdf.Rect(*r).quad for r in rects])
        annot.set_colors(stroke=colour)
        annot.set_info(content=note, title=author or self.author, subject=title)
        annot.update()
        _write_range(self._document, annot.xref, on_page[0].index, on_page[-1].index)

        item = Annotation(
            page=page_number,
            rects=rects,
            text=" ".join(w.text for w in on_page),
            title=title,
            note=note,
            colour=colour,
            first_word=on_page[0].index,
            last_word=on_page[-1].index,
            xref=annot.xref,
        )
        self.items.append(item)
        self.items.sort(key=lambda a: (a.page, a.top))
        self.dirty = True
        return item

    def set_note(self, item: Annotation, note: str, title: str | None = None) -> None:
        # The page must stay referenced: if it is collected, MuPDF unbinds the
        # annotation and every call on it fails.
        page, annot = self._find(item)
        if annot is None:
            return
        info = annot.info or {}
        heading = item.title if title is None else title
        annot.set_info(
            content=note,
            title=info.get("title") or self.author,
            subject=heading,
        )
        annot.update()
        _write_range(self._document, annot.xref, item.first_word, item.last_word)
        item.note = note
        item.title = heading
        self.dirty = True

    def set_colour(self, item: Annotation, colour: tuple[float, float, float]) -> None:
        page, annot = self._find(item)
        if annot is None:
            return
        annot.set_colors(stroke=colour)
        annot.update()
        item.colour = colour
        self.dirty = True

    def remove(self, item: Annotation) -> None:
        page, annot = self._find(item)
        if annot is not None:
            page.delete_annot(annot)
        if item in self.items:
            self.items.remove(item)
        self.dirty = True

    def _find(self, item: Annotation):
        """Return the page and the annotation on it, keeping both alive."""
        page = self._document.doc.load_page(item.page)
        for annot in page.annots():
            if annot.xref == item.xref:
                return page, annot
        return page, None

    # -- persistence -------------------------------------------------------

    # There is deliberately no save-in-place. Notes go to the companion file;
    # ``save_as`` writes incrementally when that companion is what is open.

    def save_as(self, path) -> bool:
        """Write the document to ``path``. True if that is a file of its own.

        **Incremental saving is deliberately not used.** ``saveIncr`` appends a
        revision to whatever happens to be on disk, and is silently wrong if
        that file is not byte-for-byte what this document was opened from -- a
        second copy of Mimick writing the same notes file, a write cut short,
        anything that rewrote it in between. What comes out is a PDF whose new
        revision points its ``/Prev`` at itself, so the chain never reaches the
        original objects: readers that repair it show the first revision only,
        and every note added after the first save silently disappears. That is
        not a risk worth running on a file written every few seconds.

        Instead the whole PDF is written beside the target, checked that it
        opens and still has its pages and annotations, and only then moved into
        place. The move is atomic, so an interruption leaves the previous good
        file exactly as it was rather than a half-written one.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".mimick-part")
        doc = self._document.doc
        expected_pages = doc.page_count
        expected_notes = sum(
            len(list(doc.load_page(number).annots(types=(pymupdf.PDF_ANNOT_HIGHLIGHT,))))
            for number in range(expected_pages)
        )
        try:
            doc.save(str(temporary), garbage=3, deflate=True)
            _verify(temporary, expected_pages, expected_notes)
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass
        self.dirty = False
        return not self._is_open_document(target)

    def _is_open_document(self, target: Path) -> bool:
        """Is ``target`` the very file this document was opened from?"""
        source = getattr(self._document, "path", None)
        if source is None:
            return False
        source = Path(source)
        try:
            if source.exists() and target.exists():
                return os.path.samefile(source, target)
        except OSError:
            pass
        # Falls back to a normalised comparison when one of them is missing,
        # which is the ordinary case: a new copy does not exist yet.
        return (os.path.normcase(os.path.abspath(source))
                == os.path.normcase(os.path.abspath(target)))

    # -- lookups -----------------------------------------------------------

    def for_page(self, page: int) -> list[Annotation]:
        return [item for item in self.items if item.page == page]

    def at_word(self, word_index: int) -> Annotation | None:
        for item in self.items:
            if item.first_word <= word_index <= item.last_word:
                return item
        return None


def _quad_rects(annot) -> list[tuple[float, float, float, float]]:
    """The rectangles a highlight covers."""
    vertices = annot.vertices or []
    rects: list[tuple[float, float, float, float]] = []
    # Highlight vertices come in groups of four corners per covered line.
    for start in range(0, len(vertices) - 3, 4):
        corners = vertices[start : start + 4]
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        rects.append((min(xs), min(ys), max(xs), max(ys)))
    if not rects:
        rect = annot.rect
        rects.append((rect.x0, rect.y0, rect.x1, rect.y1))
    return rects


def _annot_colour(annot) -> tuple[float, float, float]:
    colours = annot.colors or {}
    stroke = colours.get("stroke") or colours.get("fill")
    if stroke and len(stroke) >= 3:
        return (stroke[0], stroke[1], stroke[2])
    return DEFAULT_COLOUR
