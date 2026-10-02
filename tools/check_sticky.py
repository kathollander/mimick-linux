#!/usr/bin/env python3
"""Check sticky notes: their rich text, and that they survive a save.

    .venv/bin/python tools/check_sticky.py

Needs no window. A sticky is a PDF FreeText annotation with rich text
(``annotations.py``), so everything that matters about it can be checked on a
PDF made here: the one small form of HTML both apps share, a save and reopen
that gives back the same words and styles, text boxes made by other programs,
a box always tall enough for its words, and Export notes.

**The browser version runs this same code**, brought over by tools/port.sh.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf                                                     # noqa: E402

from mimick.annotations import (                                   # noqa: E402
    STICKY_MIN, AnnotationStore, Sticky, clean_rich, plain_to_rich, rich_to_markdown, rich_to_plain)
from mimick.notes_export import notes_file                         # noqa: E402

failures: list[str] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {claim}{'' if ok else f'  -- {detail}'}")
    if not ok:
        failures.append(f"{claim}: {detail}")


class Doc:
    """As much of mimick.document.Document as AnnotationStore needs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.doc = pymupdf.open(path)
        self.words: list = []
        self.page_words: dict = {}

    def selection_text(self, first: int, last: int) -> str:
        return ""


def blank_pdf(folder: Path) -> Path:
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_text((72, 100), "Some words of the document itself.", fontsize=12)
    path = folder / "blank.pdf"
    doc.save(path)
    return path


def ink_bottom(page, rect) -> float:
    """How far down a box its lowest dark pixel is, in points."""
    # Inside the border, which is drawn too.
    pix = page.get_pixmap(clip=pymupdf.Rect(rect) + (2, 2, -2, -2), dpi=144, annots=True)
    last = -1
    for y in range(pix.height):
        row = pix.samples[y * pix.stride: y * pix.stride + pix.width * pix.n]
        if any(row[i] < 100 for i in range(0, len(row), pix.n)):
            last = y
    return last / 2 + 2


print("The shared form of rich text")
SHAPES = {
    "a page's editable box": (
        'hello <b>bold</b><div><i>it</i> and <strike>st</strike></div><div><br></div><div><u>u</u></div>',
        "<p>hello <b>bold</b></p><p><i>it</i> and <s>st</s></p><p><br/></p><p><u>u</u></p>"),
    "sizes as CSS and as <font>": (
        '<p>a <span style="font-size: 18pt;">big</span> <font size="7">huge</font> <span style="font-size:11pt">same</span></p>',
        '<p>a <span style="font-size:18pt">big</span> <span style="font-size:36pt">huge</span> same</p>'),
    "Qt's toHtml": (
        '<html><head><style type="text/css">p { white-space: pre-wrap; }</style></head>'
        '<body style=" font-size:11pt; font-weight:400;"><p><span style=" font-weight:700;">Exam!</span> '
        '<span style=" font-style:italic; text-decoration: underline line-through;">x</span></p>'
        '<p style="-qt-paragraph-type:empty;"><br /></p><ul><li><span style=" font-size:14pt;">one</span></li>'
        '<li>two</li></ul></body></html>',
        '<p><b>Exam!</b> <i><u><s>x</s></u></i></p><p><br/></p><ul><li><span style="font-size:14pt">one</span></li><li>two</li></ul>'),
    "Acrobat's rich text": (
        '<?xml version="1.0"?><body xmlns="http://www.w3.org/1999/xhtml"><p dir="ltr">'
        '<span style="font-weight:bold">B</span> &amp; &lt;x&gt;</p></body>',
        "<p><b>B</b> &amp; &lt;x&gt;</p>"),
    "two line breaks": ("a<br><br>b", "<p>a</p><p><br/></p><p>b</p>"),
    "paragraphs inside list items": ("<ul><li><p>x</p></li></ul><p>z</p>", "<ul><li>x</li></ul><p>z</p>"),
    "a script and an image": ('<p>ok<script>alert(1)</script><img src="x" onerror="y"></p>', "<p>ok</p>"),
}
for name, (given, wanted) in SHAPES.items():
    got = clean_rich(given)
    check(name, got == wanted, got)
    check(f"{name}, cleaned twice, is unchanged", clean_rich(got) == got, clean_rich(got))
rich = '<p><b>Exam!</b> <i>it</i> <u>u</u> <s>s</s></p><ul><li>one</li></ul>'
check("plain text: a line a paragraph, a bullet a list item", rich_to_plain(rich) == "Exam! it u s\n• one",
      repr(rich_to_plain(rich)))
check("Markdown keeps bold, italic and strikeout, drops underline",
      rich_to_markdown(rich) == [(False, "**Exam!** *it* u ~~s~~"), (True, "one")], repr(rich_to_markdown(rich)))
check("plain text comes in a paragraph a line", plain_to_rich("a\n\nb <3") == "<p>a</p><p><br/></p><p>b &lt;3</p>",
      plain_to_rich("a\n\nb <3"))

with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder)
    print("Saved, and opened again")
    store = AnnotationStore(Doc(blank_pdf(folder)), author="Tester")
    long_rich = ('<p><b>Exam!</b> Link to <i>self-efficacy</i>. <s>Ask</s> <u>Bring</u> '
                 '<span style="font-size:18pt">BIG</span></p><ul><li>one</li><li>two <b>b</b></li></ul>'
                 '<p>' + "word " * 40 + "</p>")
    gone = store.add_sticky(0, 40, 40, "<p>removed again</p>")   # numbered before the others
    first = store.add_sticky(0, 300, 120, long_rich)
    second = store.add_sticky(1, 590, 830, "<p>in the corner</p>", colour=(0.55, 0.80, 1.00))
    check("a sticky is kept inside its page",
          second.rect[2] <= 595.5 and second.rect[3] <= 842.5, str(second.rect))
    store.set_sticky(second, rich="<p>moved <u>and</u> changed</p>", rect=(50, 400, 250, 410), folded=True)
    check("a box made too short grows to fit its words", second.rect[3] - second.rect[1] >= STICKY_MIN,
          str(second.rect))
    store.remove_sticky(gone)               # frees a number below theirs, which a compacting save closes up
    saved = folder / "saved.pdf"
    store.save_as(saved)
    # Saving must not renumber the open document's objects: every sticky and
    # highlight is found again by its number, so after a renumbering save (the
    # desktop autosaves a second after each change) moving, editing or deleting
    # one silently did nothing until the file was opened again. Found 1 October.
    check("after saving, every sticky is still found in the open document",
          all(store._find(item)[1] is not None for item in store.stickies),
          [(item.xref, [a.xref for a in store._find(item)[0].annots()]) for item in store.stickies])
    again = AnnotationStore(Doc(saved))
    check("both stickies come back", len(again.stickies) == 2, str(len(again.stickies)))
    for before, after in zip(store.stickies, again.stickies):
        check(f"page {before.page + 1}: the same words and styles", before.rich == after.rich, after.rich)
        check(f"page {before.page + 1}: the same place",
              all(abs(a - b) < 0.05 for a, b in zip(before.rect, after.rect)), f"{before.rect} {after.rect}")
        check(f"page {before.page + 1}: the same colour, folding and author",
              all(abs(a - b) < 0.01 for a, b in zip(before.colour, after.colour))
              and before.folded == after.folded and after.author == "Tester",
              f"{after.colour} {after.folded} {after.author}")
    written = pymupdf.open(saved)
    first_page = written[0]                 # kept, or MuPDF frees the annotation under us
    annot = next(first_page.annots())
    check("its plain copy (Contents) is the words, for readers without rich text",
          (annot.info or {}).get("content", "").startswith("Exam! Link to self-efficacy."),
          (annot.info or {}).get("content", "")[:40])
    check("no callout line, which Acrobat would draw as an arrow",
          written.xref_get_key(annot.xref, "CL")[0] == "null", str(written.xref_get_key(annot.xref, "CL")))
    bottom = ink_bottom(first_page, annot.rect)
    height = annot.rect.height
    check("every line is drawn inside the box", 0 < bottom < height - 1, f"ink to {bottom}, box {height}")
    check("and the box is not much taller than its words", height - bottom < 26, f"ink to {bottom}, box {height}")

    print("Made by other programs")
    other = pymupdf.open(blank_pdf(folder))
    page = other[0]
    plain = page.add_freetext_annot(pymupdf.Rect(100, 200, 300, 260), "typed in Okular\nsecond line", fontsize=12)
    plain.update()
    boxed = page.add_freetext_annot(pymupdf.Rect(100, 300, 300, 360), " ", richtext=True,
                                    style="font-size:12pt")
    pymupdf.mupdf.pdf_set_annot_rich_contents(
        boxed.this, "Acrobat box",
        '<?xml version="1.0"?><body xmlns="http://www.w3.org/1999/xhtml"><p><span style="font-weight:bold">'
        'Acrobat</span> box</p></body>')
    boxed.update()
    other_path = folder / "other.pdf"
    other.save(other_path)
    found = AnnotationStore(Doc(other_path)).stickies
    check("a plain text box is read, a paragraph a line",
          len(found) == 2 and found[0].rich == "<p>typed in Okular</p><p>second line</p>",
          found[0].rich if found else "none")
    check("an Acrobat box keeps its bold and its 12pt",
          len(found) == 2 and found[1].rich == '<p><span style="font-size:12pt"><b>Acrobat</b> box</span></p>',
          found[1].rich if len(found) > 1 else "none")

    print("Export notes")

    @dataclass
    class Highlight:
        page: int
        text: str
        title: str = ""
        note: str = ""
        colour: tuple = (1.00, 0.87, 0.35)
        first_word: int = 0

    items = [Highlight(0, "The land is not a resource."),
             Sticky(0, (10, 300, 200, 340), '<p><b>Exam!</b> <u>seminar</u></p><ul><li>one</li></ul>'),
             Sticky(1, (10, 300, 200, 340), '<p><br/></p>')]
    markdown = notes_file("md", "Title", "doc.pdf", items).decode()
    check("Markdown: counted in the summary, and an empty one left out",
          "1 highlight, 0 with notes, 1 sticky note" in markdown, markdown.split("\n")[2])
    check("Markdown: under its page, bold kept", "**Sticky note**\n\n**Exam!** seminar\n\n- one" in markdown,
          markdown)
    for kind in ("docx", "odt", "pdf"):
        data = notes_file(kind, "Title", "doc.pdf", items)
        check(f"{kind}: written", len(data) > 1000, str(len(data)))
    words = pymupdf.open(stream=notes_file("pdf", "Title", "doc.pdf", items), filetype="pdf")[0].get_text()
    check("PDF: the sticky's words are there", "Exam!" in words and "seminar" in words, words[:200])

print()
if failures:
    print(f"{len(failures)} failed.")
    sys.exit(1)
print("Sticky notes are written and read as they should be.")
