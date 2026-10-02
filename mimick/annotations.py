"""Highlights, margin notes and sticky notes, stored as real PDF annotations.

Everything written here is standard PDF markup, so notes made in Mimick open
correctly in Okular, Acrobat, Zotero or anything else, and notes made in those
programs show up here.

A sticky note is a PDF *FreeText* annotation -- what Acrobat calls a text box
-- with rich text: bold, italic, underline, strikeout, sizes and bullet lists.
It sits at a place on a page, not on any words. Firefox, Chrome, Okular and
Acrobat all draw it from the appearance MuPDF makes, formatting included, and
it stays editable: Mimick reads the rich text back when the file is opened
again (Kat, 29 September 2026).
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
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


# -- sticky notes ---------------------------------------------------------------

# The sizes the size box offers, in points; a sticky's text is in points on the
# page, so it grows and shrinks with the zoom like the document's own words.
STICKY_SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36)
STICKY_SIZE = 11
STICKY_FONT = "Helvetica, Arial, sans-serif"
STICKY_COLOUR = COLOURS[0][1]
STICKY_WIDTH = 180.0                    # a new sticky, in points
STICKY_MIN = 36.0                       # the smallest a sticky can be made
STICKY_PAD = 4.0                        # the text sits this far inside the box
_FOLDED_KEY = "MimickFolded"
_RC_HEAD = ('<?xml version="1.0"?><body xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/" '
            'xfa:APIVersion="Acrobat:8.0.0" xfa:spec="2.4">')


@dataclass
class Sticky:
    """A sticky note: rich text in a box at a place on a page."""

    page: int
    rect: tuple[float, float, float, float]
    rich: str = ""                     # clean_rich's subset of HTML
    colour: tuple[float, float, float] = STICKY_COLOUR
    folded: bool = False
    author: str = ""
    xref: int = 0

    @property
    def top(self) -> float:
        return self.rect[1]

    @property
    def text(self) -> str:
        """The words alone, a line a paragraph, "• " before a list item."""
        return rich_to_plain(self.rich)

    @property
    def preview(self) -> str:
        flat = " ".join(self.text.split())
        return flat if len(flat) <= 90 else flat[:87] + "…"


@dataclass
class _Style:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    size: float | None = None           # None: the sticky's own size

    def key(self) -> tuple:
        return (self.bold, self.italic, self.underline, self.strike, self.size)


# A block is (is_list_item, [(text, style), ...]).
_BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"}
_SKIP_TAGS = {"head", "style", "script", "title"}
_SIZE = re.compile(r"^\s*([\d.]+)\s*(pt|px)?\s*$")
_FONT_TAG_SIZES = {1: 8, 2: 10, 3: 12, 4: 14, 5: 18, 6: 24, 7: 36}


def _css(style: str) -> dict[str, str]:
    out = {}
    for part in (style or "").split(";"):
        name, _, value = part.partition(":")
        if value:
            out[name.strip().lower()] = value.strip().lower()
    return out


def _size_of(value: str) -> float | None:
    found = _SIZE.match(value or "")
    if not found:
        return None
    size = float(found.group(1)) * (0.75 if found.group(2) == "px" else 1.0)
    return max(4.0, min(96.0, round(size * 2) / 2))


class _RichReader(HTMLParser):
    """Reads any of the HTML a sticky's text arrives as -- a page's editable
    box, Qt's ``toHtml``, an Acrobat or Okular rich-text string -- into lines
    of runs, keeping only what a sticky can hold.

    A ``<br>`` ends a line; a block (``<p>``, ``<div>``, ``<li>``) ends one too
    unless a ``<br>`` just did, so ``<p><br></p>`` is one empty line, as every
    browser shows it, and ``<li><p>x</p></li>`` is one list item."""

    def __init__(self, base: float) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.stack: list[tuple[str, _Style]] = [("", _Style())]
        self.blocks: list[tuple[bool, list[tuple[str, _Style]]]] = []
        self.current: dict | None = None      # {"item", "runs", "ended"}
        self.in_list = 0
        self.skipping = 0

    @property
    def style(self) -> _Style:
        return self.stack[-1][1]

    def _open(self, item: bool) -> None:
        if self.current is not None and not self.current["runs"] and not self.current["ended"]:
            self.current["item"] = self.current["item"] or item
            return
        self._close()
        self.current = {"item": item, "runs": [], "ended": False}

    def _close(self) -> None:
        if self.current is not None and self.current["runs"]:
            self.blocks.append((self.current["item"], self.current["runs"]))
        self.current = None

    def _break(self) -> None:
        if self.current is None:
            self.current = {"item": self.in_list > 0, "runs": [], "ended": False}
        self.blocks.append((self.current["item"], self.current["runs"]))
        self.current["runs"] = []
        self.current["ended"] = True

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self.skipping += 1
            return
        if tag == "br":
            self._break()
            return
        attrs = dict(attrs)
        style = _Style(**vars(self.style))
        if tag in ("b", "strong"):
            style.bold = True
        elif tag in ("i", "em", "cite", "var"):
            style.italic = True
        elif tag in ("u", "ins"):
            style.underline = True
        elif tag in ("s", "strike", "del"):
            style.strike = True
        elif tag == "font" and (attrs.get("size") or "").isdigit():
            style.size = _FONT_TAG_SIZES.get(int(attrs["size"]))
        elif tag in ("ul", "ol"):
            self._close()
            self.in_list += 1
        elif tag in ("h1", "h2", "h3"):
            style.bold = True
        css = _css(attrs.get("style") or "")
        weight = css.get("font-weight", "")
        if weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600):
            style.bold = True
        elif weight in ("normal", "lighter") or (weight.isdigit() and int(weight) < 600):
            style.bold = False
        if "font-style" in css:
            style.italic = css["font-style"] in ("italic", "oblique")
        decoration = css.get("text-decoration-line") or css.get("text-decoration")
        if decoration is not None:
            style.underline = "underline" in decoration
            style.strike = "line-through" in decoration
        if "font-size" in css:
            size = _size_of(css["font-size"])
            if size is not None:
                style.size = None if abs(size - self.base) < 0.25 else size
        if tag == "body":
            # Qt and Acrobat say the whole note's size on its body: that is the
            # sticky's own size, not a size on some of its words.
            style.size = None
        if tag in _BLOCK_TAGS:
            self._open(tag == "li")
        self.stack.append((tag, style))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self.skipping = max(0, self.skipping - 1)
            return
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth][0] == tag:
                del self.stack[depth:]
                break
        if tag in _BLOCK_TAGS:
            self._close()
        if tag in ("ul", "ol"):
            self._close()
            self.in_list = max(0, self.in_list - 1)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() != "br":
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.skipping:
            return
        if self.current is None:
            if not data.strip():
                return                  # layout whitespace between blocks
            self.current = {"item": self.in_list > 0, "runs": [], "ended": False}
        self.current["runs"].append((data, self.style))

    def close(self) -> None:
        super().close()
        self._close()


def _runs_tidied(runs: list[tuple[str, _Style]]) -> list[tuple[str, _Style]]:
    """Whitespace collapsed as HTML shows it, and neighbours of one style joined."""
    out: list[tuple[str, _Style]] = []
    for text, style in runs:
        text = re.sub(r"[ \t\r\n]+", " ", text).replace(" ", " ")
        if not text:
            continue
        if out and out[-1][1].key() == style.key():
            out[-1] = (out[-1][0] + text, style)
        else:
            out.append((text, style))
    if out:
        out[0] = (out[0][0].lstrip(" "), out[0][1])
        out[-1] = (out[-1][0].rstrip(" "), out[-1][1])
    return [(text, style) for text, style in out if text]


def rich_blocks(source: str, base: float = STICKY_SIZE) -> list[tuple[bool, list[tuple[str, _Style]]]]:
    """A sticky's text as ``(is_list_item, runs)`` blocks, each run ``(text, style)``."""
    reader = _RichReader(base)
    reader.feed(source or "")
    reader.close()
    blocks = [(item, _runs_tidied(runs)) for item, runs in reader.blocks]
    while blocks and not blocks[-1][1]:
        blocks.pop()
    while blocks and not blocks[0][1]:
        blocks.pop(0)
    return blocks


def _escape(text: str) -> str:
    # &#160; rather than &nbsp;: the PDF's copy is XML, which knows no &nbsp;.
    return html.escape(text, quote=False).replace("  ", " &#160;")


def _runs_html(runs, base: float = STICKY_SIZE) -> str:
    out = []
    for text, style in runs:
        words = _escape(text)
        for flag, tag in ((style.strike, "s"), (style.underline, "u"),
                          (style.italic, "i"), (style.bold, "b")):
            if flag:
                words = f"<{tag}>{words}</{tag}>"
        size = style.size if style.size is not None and abs(style.size - base) >= 0.25 else None
        # Neighbours of one size share one span.
        if out and out[-1][0] == size:
            out[-1][1].append(words)
        else:
            out.append((size, [words]))
    return "".join("".join(words) if size is None
                   else f'<span style="font-size:{size:g}pt">{"".join(words)}</span>'
                   for size, words in out) or "<br/>"


def clean_rich(source: str, base: float = STICKY_SIZE) -> str:
    """Any HTML a sticky's text comes as, in the one small form both apps and
    the PDF share: ``<p>`` and ``<ul><li>``, holding ``<b> <i> <u> <s>`` and a
    ``<span style="font-size:…pt">`` where words are not the sticky's size."""
    return _blocks_html(rich_blocks(source, base))


def _blocks_html(blocks, base: float = STICKY_SIZE) -> str:
    out, listing = [], False
    for item, runs in blocks:
        if item and not listing:
            out.append("<ul>")
        elif not item and listing:
            out.append("</ul>")
        listing = item
        words = _runs_html(runs, base)
        out.append(f"<li>{words}</li>" if item else f"<p>{words}</p>")
    if listing:
        out.append("</ul>")
    return "".join(out)


def plain_to_rich(text: str) -> str:
    """Plain text -- a note made where there is no rich text -- as a sticky's."""
    return "".join(f"<p>{_escape(line) or '<br/>'}</p>" for line in str(text or "").split("\n")).replace(
        "<p></p>", "<p><br/></p>") if (text or "").strip() else ""


def rich_to_plain(rich: str) -> str:
    return "\n".join(("• " if item else "") + "".join(text for text, _ in runs)
                     for item, runs in rich_blocks(rich))


def rich_to_markdown(rich: str) -> list[tuple[bool, str]]:
    """A sticky's text as ``(is_list_item, markdown)`` lines. Underline has no
    Markdown and is dropped; the words never are."""
    lines = []
    for item, runs in rich_blocks(rich):
        words = []
        for text, style in runs:
            core = text.strip()
            if not core:
                words.append(text)
                continue
            marked = core
            for flag, mark in ((style.strike, "~~"), (style.italic, "*"), (style.bold, "**")):
                if flag:
                    marked = f"{mark}{marked}{mark}"
            lead = text[: len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()):]
            words.append(lead + marked + trail)
        lines.append((item, "".join(words)))
    return lines


def sticky_sentences(item: Sticky) -> list:
    """A sticky note's words as sentences to read aloud, a line at a time, so
    a list is read an item at a time. Its words have no place of their own on
    the page -- each is a point at the note's corner -- so nothing lights up
    while it is read."""
    from .document import Sentence, Word, chunk_into_sentences

    x, y = item.rect[0], item.rect[1]
    out: list = []
    for line in item.text.split("\n"):
        words = [Word(text=token, rect=(x, y, x, y), page=item.page)
                 for token in line.removeprefix("• ").split()]
        for chunk in chunk_into_sentences(words, clean=False):
            out.append(Sentence(index=len(out), page=item.page, words=chunk))
    return out


def sticky_style(size: float = STICKY_SIZE) -> str:
    """The note's own font and size, as the PDF keeps it (its DS entry)."""
    return (f"font-family:{STICKY_FONT};font-size:{size:g}pt;color:#000000;"
            f"padding:{STICKY_PAD:g}pt")


def _rebased(source: str, size: float) -> str:
    """Rich text written with another size as its own (a text box made in
    Acrobat at 12pt), with that size put on its words so they keep it."""
    blocks = rich_blocks(source, size)
    for _, runs in blocks:
        for _, style in runs:
            if style.size is None:
                style.size = size
    return _blocks_html(blocks)


def sticky_height(rich: str, width: float) -> float:
    """How tall a sticky ``width`` points wide must be to show all its words,
    laid out by MuPDF -- the same engine that draws it into the PDF."""
    # Measured against the ink MuPDF draws (29 September): these rules come
    # out a few points below the last line for every kind of note, and a line
    # more after a list, never short.
    try:
        story = pymupdf.Story(html=rich or "<p><br/></p>",
                              user_css=f"body {{{sticky_style()}; margin: 0}} p {{margin: 0}}")
        _, filled = story.place(pymupdf.Rect(0, 0, max(8.0, width), 20000))
        used = pymupdf.Rect(filled).y1
    except Exception:
        used = STICKY_SIZE * 1.5 * max(1, rich.count("<p") + rich.count("<li")) + 2 * STICKY_PAD
    return max(STICKY_MIN, used + 2)


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


# What a saved copy is checked for: every highlight and every sticky note.
MARKS = (pymupdf.PDF_ANNOT_HIGHLIGHT, pymupdf.PDF_ANNOT_FREE_TEXT)


def _verify(path: Path, pages: int, notes: int) -> None:
    """Check a just-written PDF before it is allowed to replace a good one."""
    try:
        with pymupdf.open(path) as written:
            found_pages = written.page_count
            found_notes = sum(
                len(list(written.load_page(number).annots(types=MARKS)))
                for number in range(found_pages)
            )
    except Exception as exc:
        raise OSError(f"the PDF Mimick just wrote will not open again ({exc})") from exc
    if found_pages != pages or found_notes != notes:
        raise OSError(
            f"the PDF Mimick just wrote came back with {found_pages} pages and "
            f"{found_notes} highlights and sticky notes, not {pages} and {notes}"
        )


class AnnotationStore:
    """Reads and writes the annotations of one open document."""

    def __init__(self, document, author: str = "") -> None:
        self._document = document
        self.author = author or "Mimick"
        self.items: list[Annotation] = []
        self.stickies: list[Sticky] = []
        self.dirty = False
        self.reload()

    # -- reading -----------------------------------------------------------

    def reload(self) -> None:
        """Load highlights already present in the file."""
        self.items = []
        self.stickies = []
        doc = self._document.doc
        for number in range(doc.page_count):
            page = doc.load_page(number)
            for annot in page.annots(types=(pymupdf.PDF_ANNOT_FREE_TEXT,)):
                self.stickies.append(self._read_sticky(number, annot))
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
        self.stickies.sort(key=lambda s: (s.page, s.top))

    def _read_sticky(self, number: int, annot) -> Sticky:
        doc = self._document.doc
        mupdf = pymupdf.mupdf
        info = annot.info or {}
        source, size = "", STICKY_SIZE
        try:
            if mupdf.pdf_annot_has_rich_contents(annot.this):
                source = mupdf.pdf_annot_rich_contents(annot.this) or ""
            if mupdf.pdf_annot_has_rich_defaults(annot.this):
                size = _size_of(_css(mupdf.pdf_annot_rich_defaults(annot.this)).get("font-size", "")) or size
        except Exception:
            source = ""
        rich = _rebased(source, size) if source else ""
        if not rich:
            rich = plain_to_rich(info.get("content") or "")
        colours = annot.colors or {}
        colour = colours.get("stroke") or colours.get("fill")
        try:
            folded = doc.xref_get_key(annot.xref, _FOLDED_KEY)[1] == "true"
        except Exception:
            folded = False
        rect = annot.rect
        return Sticky(
            page=number,
            rect=(rect.x0, rect.y0, rect.x1, rect.y1),
            rich=rich,
            colour=tuple(colour[:3]) if colour and len(colour) >= 3 else STICKY_COLOUR,
            folded=folded,
            author=info.get("title") or "",
            xref=annot.xref,
        )

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

    # -- sticky notes -------------------------------------------------------

    def add_sticky(self, page_number: int, x: float, y: float, rich: str = "",
                   colour: tuple[float, float, float] = STICKY_COLOUR,
                   width: float = STICKY_WIDTH, author: str = "") -> Sticky:
        """A new sticky note with its top left corner at ``x``, ``y`` on a page,
        kept inside the page."""
        page = self._document.doc.load_page(page_number)
        bounds = page.rect
        width = max(STICKY_MIN, min(width, bounds.width))
        x = max(bounds.x0, min(x, bounds.x1 - width))
        y = max(bounds.y0, min(y, bounds.y1 - STICKY_MIN))
        annot = page.add_freetext_annot(
            pymupdf.Rect(x, y, x + width, y + STICKY_MIN), " ", fontsize=STICKY_SIZE,
            richtext=True, style=sticky_style(), fill_color=colour, border_width=0.5)
        item = Sticky(page=page_number, rect=(x, y, x + width, y + STICKY_MIN),
                      rich=clean_rich(rich), colour=tuple(colour),
                      author=author or self.author, xref=annot.xref)
        self._write_sticky(page, annot, item)
        self.stickies.append(item)
        self.stickies.sort(key=lambda s: (s.page, s.top))
        self.dirty = True
        return item

    def set_sticky(self, item: Sticky, rich: str | None = None, rect=None,
                   colour=None, folded: bool | None = None) -> None:
        """Change a sticky's words, place, size, colour or folding. Its height
        never drops below what its words need, so no reader cuts them off."""
        page, annot = self._find(item)
        if annot is None:
            return
        if rich is not None:
            item.rich = clean_rich(rich)
        if rect is not None:
            item.rect = tuple(float(v) for v in rect)
        if colour is not None:
            item.colour = tuple(colour)
        if folded is not None:
            item.folded = bool(folded)
        self._write_sticky(page, annot, item)
        self.stickies.sort(key=lambda s: (s.page, s.top))
        self.dirty = True

    def remove_sticky(self, item: Sticky) -> None:
        page, annot = self._find(item)
        if annot is not None:
            page.delete_annot(annot)
        if item in self.stickies:
            self.stickies.remove(item)
        self.dirty = True

    def with_sticky_matches(self, matches: list, query: str, match_case: bool = False) -> list:
        """Find's matches in the document, with the ones in sticky notes put
        after each page's own -- one ``(-1, -1, page, sticky)`` for each time
        the words are in a sticky. A match in the document stays ``(first
        word, last word, page)``, in the document's order: reading order, which
        down a two-column page is not top to bottom, so a sticky is not slotted
        in by its height. Spaces match any spacing, as Find's own do; a sticky
        is searched as its plain words."""
        from .document import _fold

        needle = " ".join(_fold(query or "", match_case).split())
        if not needle or not self.stickies:
            return list(matches)
        found = []
        for item in self.stickies:
            text = " ".join(_fold(item.text, match_case).split())
            at = text.find(needle)
            while at >= 0:
                found.append((-1, -1, item.page, item))
                at = text.find(needle, at + 1)
        if not found:
            return list(matches)
        ordered = [(match[2], 0, number, match) for number, match in enumerate(matches)]
        ordered += [(match[2], 1, match[3].top, match) for match in found]
        return [match for *_key, match in sorted(ordered, key=lambda entry: entry[:3])]

    def _write_sticky(self, page, annot, item: Sticky) -> None:
        bounds = page.rect
        x0, y0, x1, y1 = item.rect
        width = max(STICKY_MIN, min(x1 - x0, bounds.width))
        x0 = max(bounds.x0, min(x0, bounds.x1 - width))
        height = max(y1 - y0, sticky_height(item.rich, width))
        y0 = max(bounds.y0, min(y0, bounds.y1 - min(height, bounds.height)))
        item.rect = (x0, y0, x0 + width, y0 + height)
        doc = self._document.doc
        annot.set_rect(pymupdf.Rect(*item.rect))
        annot.set_info(title=item.author or self.author)
        # Set together, and after set_info: setting Contents alone throws the
        # rich text away. Contents is the plain copy other readers edit.
        pymupdf.mupdf.pdf_set_annot_rich_contents(
            annot.this, item.text, _RC_HEAD + (item.rich or "<p><br/></p>") + "</body>")
        pymupdf.mupdf.pdf_set_annot_rich_defaults(annot.this, sticky_style())
        # MuPDF gives every new text box a callout line from the page corner;
        # Acrobat draws it as an arrow across the page.
        doc.xref_set_key(annot.xref, "CL", "null")
        doc.xref_set_key(annot.xref, _FOLDED_KEY, "true" if item.folded else "false")
        edge = tuple(round(c * 0.72, 3) for c in item.colour)
        annot.update(fill_color=item.colour, border_color=edge, text_color=(0, 0, 0))

    def sticky_at(self, page: int, x: float, y: float) -> Sticky | None:
        for item in reversed(self.stickies):
            x0, y0, x1, y1 = item.rect
            if item.page == page and x0 <= x <= x1 and y0 <= y <= y1:
                return item
        return None

    def _find(self, item):
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
            len(list(doc.load_page(number).annots(types=MARKS)))
            for number in range(expected_pages)
        )
        try:
            # garbage=1, not 3: 2 and up compact the object numbers of the open
            # document as well as the file's, once anything has been deleted,
            # and every highlight and sticky is found again by its number --
            # after such a save, moving, editing or deleting one did nothing.
            # 1 still drops what nothing uses.
            doc.save(str(temporary), garbage=1, deflate=True)
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
