#!/usr/bin/env python3
"""Check formatted notes, sticky-note titles and links to highlights.

    .venv/bin/python tools/check_links.py

Needs no window. Kat asked for these on 15 October 2026: bold and italics in
a highlight's note, a title on a sticky note as a highlight's note has, and a
way to tie a sticky note to the highlight it is about. All three are kept in
the PDF (``annotations.py``), so all of it can be checked on a PDF made here:
what is written, that a save and reopen gives it back, what other readers are
left with, and Export notes.

**The browser version runs this same code**, brought over by tools/port.sh.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf                                                     # noqa: E402

from mimick.annotations import AnnotationStore, note_from_rich    # noqa: E402
from mimick.document import Word                                   # noqa: E402
from mimick.notes_export import notes_file                         # noqa: E402

failures: list[str] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {claim}{'' if ok else f'  -- {detail}'}")
    if not ok:
        failures.append(f"{claim}: {detail}")


WORDS = "Some words of the document itself, to highlight".split()


class Doc:
    """As much of mimick.document.Document as AnnotationStore needs, with
    words to highlight."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.doc = pymupdf.open(path)
        self.words = []
        for page in range(self.doc.page_count):
            for n, text in enumerate(WORDS):
                self.words.append(Word(text=text, rect=(72 + n * 50, 90, 72 + n * 50 + 45, 104), page=page,
                                       index=len(self.words)))
        self.page_words = {}
        for word in self.words:
            self.page_words.setdefault(word.page, []).append(word)

    def selection_text(self, first: int, last: int) -> str:
        return " ".join(w.text for w in self.words[first: last + 1])


def blank_pdf(folder: Path) -> Path:
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_text((72, 100), " ".join(WORDS), fontsize=12)
    path = folder / "blank.pdf"
    doc.save(path)
    return path


def raw(store, xref: int, key: str) -> tuple[str, str]:
    return store._document.doc.xref_get_key(xref, key)


print("A note's formatting, kept or not")
check("no formatting is kept as no rich text", note_from_rich("<p>just words</p>") == ("just words", ""),
      repr(note_from_rich("<p>just words</p>")))
check("two plain lines are still plain", note_from_rich("a<div>b</div>") == ("a\nb", ""),
      repr(note_from_rich("a<div>b</div>")))
plain, rich = note_from_rich("Read <b>this</b> twice<div><i>slowly</i></div>")
check("bold and italics are kept, with a plain copy", (plain, rich) == ("Read this twice\nslowly",
      "<p>Read <b>this</b> twice</p><p><i>slowly</i></p>"), repr((plain, rich)))
check("a list is formatting", note_from_rich("<ul><li>one</li><li>two</li></ul>")[1] != "",
      repr(note_from_rich("<ul><li>one</li><li>two</li></ul>")))

with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder)
    store = AnnotationStore(Doc(blank_pdf(folder)), author="Tester")

    print("Formatted notes on highlights")
    mark = store.add(0, 2, note="", title="Key point", rich="Read <b>this</b> twice")
    check("the note is the plain words", mark.note == "Read this twice", repr(mark.note))
    check("and the formatting is kept", mark.rich == "<p>Read <b>this</b> twice</p>", repr(mark.rich))
    kind, rc = raw(store, mark.xref, "RC")
    check("as the PDF's rich text (RC), which Acrobat shows", kind == "string" and "<b>this</b>" in rc, rc)
    check("and the plain Contents every reader shows", raw(store, mark.xref, "Contents")[1] == "Read this twice",
          raw(store, mark.xref, "Contents"))
    check("it is given a name of Mimick's own", mark.name.startswith("mimick-")
          and raw(store, mark.xref, "NM")[1] == mark.name, mark.name)

    store.set_note(mark, "Read this twice", "Key point")
    check("an edit without formatting (the desktop) that keeps the words keeps the formatting",
          mark.rich == "<p>Read <b>this</b> twice</p>" and "<b>" in raw(store, mark.xref, "RC")[1], mark.rich)
    store.set_note(mark, "Read this three times", "Key point")
    check("one that changes the words drops it", mark.rich == "" and raw(store, mark.xref, "RC")[0] == "null",
          (mark.rich, raw(store, mark.xref, "RC")))
    store.set_note(mark, "", "Key point", rich="<p><i>Now</i> in italics</p>")
    check("formatting given again is written again", mark.rich == "<p><i>Now</i> in italics</p>"
          and mark.note == "Now in italics", (mark.note, mark.rich))
    plain_mark = store.add(4, 5, note="plain words only")
    check("a plain note writes no rich text", plain_mark.rich == "" and raw(store, plain_mark.xref, "RC")[0] == "null",
          raw(store, plain_mark.xref, "RC"))

    print("Sticky notes with titles, linked to highlights")
    stuck = store.add_sticky(0, 300, 200, "<p>About that passage</p>", title="  Question ")
    check("a sticky keeps its title, trimmed", stuck.title == "Question", repr(stuck.title))
    check("as the PDF's Subject", raw(store, stuck.xref, "Subj")[1] == "Question", raw(store, stuck.xref, "Subj"))
    check("and has a name of its own", stuck.name.startswith("mimick-") and stuck.name != mark.name, stuck.name)
    store.link_sticky(stuck, mark)
    check("linked, it names the highlight", stuck.link == mark.name
          and raw(store, stuck.xref, "MimickLink")[1] == mark.name, (stuck.link, raw(store, stuck.xref, "MimickLink")))
    check("and each finds the other", store.linked_to(stuck) is mark and store.stickies_of(mark) == [stuck])
    check("the link does not touch the words", stuck.rich == "<p>About that passage</p>", stuck.rich)

    # A highlight MuPDF named, as Mimick's did before 15 October: "fitz-A0"
    # comes again in the next session, so it gets a name of its own first.
    old = store.add(6, 6)
    store._document.doc.xref_set_key(old.xref, "NM", "(fitz-A0)")
    old.name = "fitz-A0"
    other = store.add_sticky(1, 100, 300, "<p>On the other</p>")
    store.link_sticky(other, old)
    check("a highlight with MuPDF's own name is renamed before linking", old.name.startswith("mimick-")
          and other.link == old.name and raw(store, old.xref, "NM")[1] == old.name, (old.name, other.link))
    store.set_sticky(stuck, title="Question, again")
    check("retitling keeps the link", stuck.link == mark.name and stuck.title == "Question, again")

    saved = folder / "saved.pdf"
    store.save_as(saved)
    again = AnnotationStore(Doc(saved))
    back = {s.title: s for s in again.stickies}
    print("Saved, and opened again")
    check("the title comes back", "Question, again" in back, list(back))
    s2 = back.get("Question, again")
    m2 = again.linked_to(s2) if s2 else None
    check("the link comes back, to the same highlight", m2 is not None and m2.title == "Key point", m2)
    check("the formatted note comes back", m2 is not None and m2.rich == "<p><i>Now</i> in italics</p>"
          and m2.note == "Now in italics", m2 and (m2.note, m2.rich))
    check("the renamed highlight's link comes back", any(again.linked_to(s) is not None
          and again.linked_to(s).first_word == 6 for s in again.stickies))

    print("Undo puts a deleted highlight back under its old name")
    name = m2.name
    again.remove(m2)
    check("deleted, the sticky's link finds nothing", again.linked_to(s2) is None)
    put_back = again.add(m2.first_word, m2.last_word, title=m2.title, rich=m2.rich, name=name)
    check("put back with its name, the link holds again", again.linked_to(s2) is put_back, put_back.name)
    clash = again.add(0, 0, name=name)
    check("a name already taken is never given twice", clash.name != name, clash.name)

    print("Unlinking")
    again.link_sticky(s2, None)
    check("an unlinked sticky names nothing", s2.link == "" and raw(again, s2.xref, "MimickLink")[0] == "null",
          raw(again, s2.xref, "MimickLink"))

    print("What other readers do")
    # Okular edits only the plain Contents and leaves the rich copy as it was.
    doc = again._document.doc
    doc.xref_set_key(put_back.xref, "Contents", "(Retyped elsewhere)")
    again.reload()
    edited = next(m for m in again.items if m.xref == put_back.xref)
    check("a note retyped elsewhere is the retyped words, unformatted", edited.note == "Retyped elsewhere"
          and edited.rich == "", (edited.note, edited.rich))

    print("Export notes")
    s2 = next(s for s in again.stickies if s.xref == s2.xref)
    m3 = again.add(2, 3, rich="<p>A <b>bold</b> claim</p><ul><li>first</li></ul>", title="Claims")
    md = notes_file("md", "T", "t.pdf", [m3, s2]).decode()
    check("Markdown keeps a note's bold", "- A **bold** claim" in md and "- first" in md, md)
    check("and heads a sticky with its title", "Sticky note: Question, again" in md, md)
    for kind in ("docx", "odt", "pdf"):
        try:
            data = notes_file(kind, "T", "t.pdf", [m3, s2])
            check(f"a {kind} is made", len(data) > 500, str(len(data)))
        except Exception as exc:                                      # noqa: BLE001
            check(f"a {kind} is made", False, repr(exc))
    text = pymupdf.open(stream=notes_file("pdf", "T", "t.pdf", [m3, s2]), filetype="pdf")[0].get_text()
    check("the PDF has the note's words and the sticky's title", "bold claim" in " ".join(text.split())
          and "Question, again" in text, text)

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("All passed")
