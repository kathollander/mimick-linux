#!/usr/bin/env python3
"""Check the notes documents Export notes writes: Markdown, Word, OpenDocument, PDF.

    .venv/bin/python tools/check_notes_export.py

Needs no window and no document: the format is a function of the annotations,
so it is checked against annotations made up here, which is the only way to
pin the awkward cases (one highlight, no notes, colours used or not).

**The browser version writes the very same files**: its document worker calls
``notes_file`` from this module, brought over by ``tools/port.sh``. Print the
Markdown with `--show`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mimick.annotations import COLOURS                     # noqa: E402
import io                                                  # noqa: E402
import zipfile                                             # noqa: E402
import xml.dom.minidom                                     # noqa: E402

import pymupdf                                             # noqa: E402

from mimick.notes_export import notes_file, notes_markdown, passage_lines  # noqa: E402

YELLOW, GREEN = COLOURS[0][1], COLOURS[1][1]
WHEN = date(2026, 9, 19)

failures: list[str] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {claim}{'' if ok else f'  -- {detail}'}")
    if not ok:
        failures.append(f"{claim}: {detail}")


@dataclass
class FakeAnnotation:
    page: int
    text: str
    title: str = ""
    note: str = ""
    colour: tuple = field(default_factory=lambda: YELLOW)
    first_word: int = 0


def sample() -> list[FakeAnnotation]:
    return [
        FakeAnnotation(0, "The land is not a resource.", title="Key claim",
                       note="This is the bit that matters.", first_word=10),
        FakeAnnotation(0, "A second passage on the same page.", first_word=40),
        FakeAnnotation(4, "Something else entirely.", colour=GREEN, first_word=900),
    ]


def sections(item) -> str | None:
    return {0: "Introduction", 4: "Discussion"}.get(item.page)


def main() -> int:
    items = sample()
    text = notes_markdown("A Paper About Reading", "paper.pdf", items, sections, WHEN)
    lines = text.split("\n")

    check("it starts with the document's title as a heading",
          lines[0] == "# Notes: A Paper About Reading", lines[0])
    check("the summary line counts the highlights and the ones with notes",
          "3 highlights, 1 with notes" in text,
          next((l for l in lines if "highlight" in l), ""))
    check("...and says where they came from and when",
          "paper.pdf" in text and "19 September 2026" in text)
    check("each page is a heading, with its section",
          "## Page 1 · Introduction" in text and "## Page 5 · Discussion" in text)
    check("two highlights on one page share a single page heading",
          text.count("## Page 1 · Introduction") == 1)
    check("passages are block quotes, in quotation marks, with their page",
          "> “The land is not a resource.” (p. 1)" in text, text)
    check("a heading on a highlight is bold",
          "**Key claim**" in text)
    check("the note follows it as a point of its own",
          "- This is the bit that matters." in text)
    check("it ends with exactly one newline", text.endswith("\n")
          and not text.endswith("\n\n"), repr(text[-3:]))

    # Colours are named only when more than one of Mimick's own was used.
    check("two colours used, so both are named", "*Yellow*" in text and "*Green*" in text)
    one = notes_markdown("T", "p.pdf", [items[0], items[1]], sections, WHEN)
    check("one colour used, so none is named -- it would say nothing",
          "*Yellow*" not in one, one)

    # The awkward small cases.
    single = notes_markdown("T", "p.pdf", [items[1]], sections, WHEN)
    check("one highlight is '1 highlight', not '1 highlights'",
          "1 highlight," in single and "1 highlights" not in single, single.split("\n")[2])
    check("...and 0 with notes is said plainly", "0 with notes" in single)
    empty = notes_markdown("T", "p.pdf", [], sections, WHEN)
    check("no highlights at all still writes a valid file",
          empty.startswith("# Notes: T") and "0 highlights, 0 with notes" in empty, empty)

    # A mark made by another PDF reader has no word range of ours.
    stray = FakeAnnotation(4, "From Okular.", first_word=-1)
    check("an annotation from another reader does not break it",
          "> “From Okular.” (p. 5)" in notes_markdown("T", "p.pdf", [stray], sections, WHEN))

    # Whitespace the reader typed must not become blank lines in the quote.
    messy = FakeAnnotation(0, "  spaced   out\n\n  words  ", first_word=1)
    got = notes_markdown("T", "p.pdf", [messy], sections, WHEN)
    check("stray spacing in a passage is tidied, not passed through",
          "> “spaced out" in got and "> words” (p. 1)" in got and ">  " not in got, got)

    # A list the PDF ran into one paragraph (Kat's example, from a course guide).
    listed = FakeAnnotation(11, "it becomes important to consider: ● the learner’s development "
                                "● the connection between literacy and engagement ● the influence of technology")
    check("a bullet glyph starts a new line",
          [b for b, _ in passage_lines(listed.text)] == [False, True, True, True], passage_lines(listed.text))
    got = notes_markdown("T", "p.pdf", [listed], None, WHEN)
    check("...which Markdown writes as a list inside the quote",
          "> “it becomes important to consider:\n>\n> - the learner’s development\n> - the connection" in got, got)
    check("a middle dot is not a bullet", len(passage_lines("Page 3 · Methods")) == 1)
    two = FakeAnnotation(0, "x", note="first point\nsecond point")
    check("each line of a note is a point of its own",
          "- first point\n- second point" in notes_markdown("T", "p.pdf", [two], None, WHEN))

    # The other formats: each opens, and says the same things.
    everything = items + [listed]
    docx = zipfile.ZipFile(io.BytesIO(notes_file("docx", "A Paper", "paper.pdf", everything, sections, WHEN)))
    parts = {name: docx.read(name).decode() for name in docx.namelist()}
    for name, part in parts.items():
        xml.dom.minidom.parseString(part)                  # raises on anything malformed
    body = parts["word/document.xml"]
    check("Word: every part is well-formed XML, with styles and bullets",
          {"word/document.xml", "word/styles.xml", "word/numbering.xml", "[Content_Types].xml"} <= set(parts), sorted(parts))
    check("Word: page headings are real headings, and the list is a list",
          body.count('w:val="Heading2"') == 3 and body.count('w:numId w:val="2"') == 3, body[:300])
    odt_bytes = notes_file("odt", "A Paper", "paper.pdf", everything, sections, WHEN)
    odt = zipfile.ZipFile(io.BytesIO(odt_bytes))
    check("OpenDocument: mimetype first and uncompressed",
          odt.infolist()[0].filename == "mimetype" and odt.infolist()[0].compress_type == zipfile.ZIP_STORED
          and odt_bytes[38:77] == b"application/vnd.oasis.opendocument.text")
    for name in ("content.xml", "styles.xml", "meta.xml", "META-INF/manifest.xml"):
        xml.dom.minidom.parseString(odt.read(name))
    content = odt.read("content.xml").decode()
    check("OpenDocument: headings and lists", content.count('text:outline-level="2"') == 3
          and 'text:style-name="Quoted"' in content, content[:300])
    pdf = pymupdf.open(stream=notes_file("pdf", "A Paper", "paper.pdf", everything, sections, WHEN), filetype="pdf")
    words = " ".join(pdf[0].get_text().split())
    check("PDF: the passages, the notes and the pages are all there",
          "“The land is not a resource.” (p. 1)" in words and "This is the bit that matters." in words
          and "of technology” (p. 12)" in words, words[:400])
    check("PDF: its outline is the page headings", [t for _, t, _ in pdf.get_toc()][:2] == ["Notes: A Paper", "Page 1 · Introduction"],
          pdf.get_toc())

    if "--show" in sys.argv:
        print("\n" + "-" * 66)
        print(text, end="")
        print("-" * 66)

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for line in failures:
            print(f"  {line}")
        return 1
    print("Export notes writes what it should.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
