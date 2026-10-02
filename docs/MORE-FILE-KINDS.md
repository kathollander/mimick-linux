# Opening more kinds of file

Started 19 September 2026, at Kat's asking: *"can we make it so our reader is
able to open .txt, .html, .md and other simple files? Also, can we make it so
that importing a powerpoint presentation (Microsoft Office or OpenOffice)
converts the thing into a PDF that we can save? Do this for the web app AND the
Linux version."*

**Where it stands (21 September, end of day): the shared side is written, and
the browser app has all of it, including a bar that counts a deck's slides.** `convert.py` now opens `.md`, `.html`/`.htm`/`.xhtml`,
`.rtf` and `.fb2` as well as the slide decks `slides.py` draws (`849d778`,
`e43be34`), and the browser version is wired, checked and committed
(`../Mimick`, `ffc4db5`). **What is left is this app's own wiring** — the
LibreOffice path and converting off the UI thread, both below — and the three
decisions in *For Kat*. The rest of this file is the design, what remains, and
the limitations to tell Kat about.

Both apps already open `.txt`, `.docx`, `.odt` and `.epub` the same way: the
file is laid out as a PDF once, and from then on it *is* a PDF, so reading,
highlights, notes, Find, the contents panel and **Save a copy (PDF)** all work
with no other part of either app knowing where it came from. Everything here
follows that path, so "converts the thing into a PDF that we can save" is
already answered by Save a copy (browser: File ▾ → Save a copy; desktop:
File → Save As, `Ctrl`+`Shift`+`S`).

The conversion lives in `mimick/convert.py` (shared, copied to the browser by
`../Mimick/tools/port.sh`; never edit the browser's `py/convert.py`).

## Done: slides.py

`mimick/slides.py`, `slides_pdf(data, kind, title)` → PDF bytes. No new
dependency: PyMuPDF and the standard library only, so it runs in Pyodide too.

- One PDF page per slide, the slide's own size (16:9 decks come out 960×540pt).
- Text boxes are placed where the slide puts them, at the size the slide gives
  them, shrunk to fit the box as PowerPoint does. Bullets, numbering, bold,
  italic, underline, alignment, indent levels, and middle/bottom anchoring.
- Placeholder geometry and text styles are inherited slide → layout → master,
  which is what makes titles come out the right size when the slide itself
  says nothing about them.
- Pictures, tables, groups (with their transforms), and `mc:AlternateContent`
  wrappers. Hidden slides and the date/footer/slide-number furniture are left
  out, so they are not read aloud.
- Each slide's title becomes a contents-panel entry; a slide with no title is
  "Slide 7".
- Large pictures are scaled to 150 dpi at the size they are drawn and photos
  saved as JPEG, including PNGs whose transparency turns out to be unused.
  Without this a 56 MB deck made an 83 MB PDF; with it, 26 MB. A 9.7 MB deck
  makes a 2.7 MB PDF in 1.7 s.

Measured on 35 real decks (on this machine, 2–148 slides, and
one `.odp`): all 35 converted, 0.1 s to 8 s each. Rendered pages were compared
against LibreOffice's own PDF of the same deck: titles, bullet lists, photos
and tables land in the same places.

**24 September:** the desktop now lays a file out **off the UI thread**, with
a bar that counts a deck's slides (`ConvertWorker` and `_convert` in
`ui/main_window.py`; the window polls the worker, for the reason
`ExportEvent` gives), and **`tools/check_convert.py` covers all eleven kinds**
-- the seven documents, both decks, `.txt`, and a deck opened in the window.
`converted_pdf` takes `progress` through to `document_to_pdf`. What is left
is only the **LibreOffice path**, which waits on Kat's decision 1 below.

## Still to do

Items 1, 2, 4, 5 and the browser half of 6 are **done** (21 September); they
are kept here because they say *how* each kind is converted, which is worth
having when one of them comes out wrong. What is actually left is **3** (this
app's wiring, including the LibreOffice path) and the **desktop half of 6**
(`tools/check_convert.py`).

Two things were learned writing them, neither in the design below. A web page
may carry a picture as a `data:` URI, and when one of those is truncated MuPDF
refuses to draw *the whole page* — so a refusal now drops every picture and
keeps the words. And an `.rtf`'s `\info` group is skipped when the words are
gathered, but its `\title` is read separately, so the window names the document
rather than the file it arrived in.

1. ✅ **`.md`, `.html`/`.htm`/`.xhtml`, `.rtf`, `.fb2` in `convert.py`.**
   - **Markdown** — a small converter to HTML here (headings, lists, quotes,
     code, tables, emphasis, links kept as their text, images dropped, YAML
     front matter's `title:` used), then the existing `_story_pdf`. No new
     library, and both apps then agree exactly.
   - **HTML** — MuPDF opens `html`/`xhtml` natively and gives headings as an
     outline, so it joins the `.docx`/`.epub` path in `document_to_pdf`.
     Strip `<script>`, `<iframe>`, `<video>`, `<audio>` and any `<img>` whose
     `src` is not a `data:` URI **on the bytes, not decoded text** (a page
     declares its own encoding in a `<meta>`, and re-encoding it makes
     mojibake). Images that cannot be fetched otherwise come out as the literal
     word "[image]", which the voice would read aloud.
   - **RTF** — a control-word stripper (skip `fonttbl`, `colortbl`,
     `stylesheet`, `info`, `pict`, `\*` destinations; `\par`, `\line`, `\tab`,
     `\'hh` in the `\ansicpg` code page, `\uN` with `\ucN` skips) into plain
     text, then `text_to_pdf`. Formatting is lost; the words are not.
   - **FB2** — MuPDF opens it natively; one line to add.
2. ✅ **Wire the new kinds into `CONVERTIBLE` and `document_to_pdf`** in
   `convert.py`, with aliases (`markdown`→`md`, `htm`/`xhtml`→`html`,
   `ppsx`→`pptx`), and have `document_to_pdf` call `slides.slides_pdf`.
3. **Desktop**: `CONVERTIBLE` drives the Open dialog, drag and drop and
   `__main__.py` already, so those follow for free. What needs writing is the
   **LibreOffice path** (below) and converting **off the UI thread** — a deck
   takes seconds, and LibreOffice tens of seconds, which would freeze the
   window as `load_document` is written today (it only puts up a wait cursor).
   **A bar is half-built already:** `document_to_pdf` and `slides_pdf` take an
   optional `progress(done, total)`, called as each slide is drawn (`8c94f1b`).
   The browser uses it for a bar that counts the slides; the desktop passes
   nothing yet. Wire it from the worker thread to a `QProgressDialog` or the
   status bar. Only a deck reports progress — the other kinds are a second or
   two and MuPDF gives nothing to count — so they want an indeterminate bar.
   LibreOffice gives no progress either; for its ~30 s that matters more.
4. ✅ **Browser**: `js/reader.js` (`LAID_OUT`, `isText`, `OPEN_TYPES`, the "not a
   file Mimick can open" message), `reader.html` (the file input's `accept`,
   the drop line, About and the keys dialog), `manifest.json`
   (`file_handlers`), `js/python.js` (`PACKAGE` needs `"slides.py"`), `sw.js`
   (`py/slides.py` in the precache list), then `python3
   tools/stamp_offline.py`. All done 21 September in `../Mimick`'s `ffc4db5`.
   One trap worth keeping: the old `openFile` asked "is this text?" first, and
   a `.md` arrives as `text/plain` from most places, so it would have been laid
   out as plain text with every heading lost. The name decides now, and the
   type only answers for a file that has no useful name. `master` there is
   ahead of origin and unpushed as of the end of 21 September, still waiting
   on Kat; `../Mimick/docs/HANDOFF.md`, *Start here*, says by what.
5. ✅ **`tools/port.sh` in the browser repo** must copy `slides.py` as well as the
   other six shared files.
6. **Checks and samples.** ✅ The samples are made, in `../Mimick/sample/`
   and all in our own words, since the browser repo is public:
   `test-document.{docx,odt,epub,html,md,rtf,fb2}` — one document in seven
   formats, six of which say *exactly* the same words — and
   `test-slides.{pptx,odp}`. `tools/make_test_documents.sh` makes the
   LibreOffice ones and copies the page; the `.md` and `.fb2` are written by
   hand; `tools/make_test_slides.py` writes the deck as real OOXML, because
   LibreOffice asked for a `.pptx` turns every frame into a plain text box and
   a deck with no title placeholder would not test the one thing worth
   testing. ✅ `tools/check_documents.mjs` (browser) covers all nine.
   **Left: `tools/check_convert.py` (desktop)**, which still opens only the
   original four.

## The desktop's LibreOffice path

LibreOffice is the only way to open the old binary `.ppt`, and its own
conversion keeps backgrounds, colours and drawn shapes, which `slides.py` does
not. Measured here (snap LibreOffice 25.x, with Kat's own LibreOffice window
open at the time):

- `libreoffice --headless -env:UserInstallation=file://<dir> --convert-to pdf`
  — **8 s of start-up, then ~23 s for a 32-slide deck** (`slides.py`: 1.7 s).
- The separate `UserInstallation` profile is **required**: without it, a
  conversion started while the person has LibreOffice open silently does
  nothing.
- The **snap** cannot read or write dot-folders or `/tmp`, so the work folder
  cannot be `~/.cache/mimick`. Use `~/snap/libreoffice/common/…` when the
  binary resolves into `/snap`, and an ordinary temporary folder otherwise.

**Suggested shape:** a desktop-only `mimick/office.py` with
`libreoffice_pdf(path) -> bytes | None` (None when LibreOffice is not
installed), and `convert.converted_pdf(path, cache_dir, make=None)` gaining a
`make` hook it tries first — so the shared file stays free of `subprocess`,
which Pyodide does not have. Then `.ppt` is openable on the desktop only, and
the decision below is Kat's.

## For Kat — the decisions

1. **On the desktop, which converter wins for a deck when LibreOffice is
   installed?** Faithful and slow (~30 s, with backgrounds and shapes), or ours
   and quick (~2 s, text and pictures only)? A first thought: LibreOffice when
   it is there, since a saved PDF is likelier to be passed to someone else —
   but it makes the desktop's PDF of a deck different from the browser's, and
   30 s is a long wait with no progress bar yet.
2. **Speaker notes.** Lecture decks often carry the real content in the notes,
   and they are dropped by both converters. They could go under each slide on
   its page, as PowerPoint's "notes pages" print layout does. Wanted?
3. **`.doc` (old Word) and `.xls`/`.xlsx`?** The LibreOffice path would give
   `.doc` for free on the desktop. Spreadsheets are a different shape of
   problem and probably not wanted.

## Limitations to tell people about

**Slides, both apps** (`slides.py`): no theme backgrounds, background pictures
or colours — text is always dark on white, which is what reading wants; no
drawn shapes, arrows or their fills (the words written *in* them do come
through); no charts, no SmartArt (its text is in a separate diagram part that
is not read yet); no video, audio, animations, transitions or speaker notes.
EMF and WMF pictures are skipped, as MuPDF cannot draw them (Word-made decks
often use EMF for equations and clip art). Cropped pictures come out uncropped.
Rotated text boxes are placed but not rotated.

**Slides, browser only**: no `.ppt` at all (the old binary format, and
LibreOffice is not there to ask). A big deck is held in memory whole — a 56 MB
deck became a 26 MB PDF and took 8 s; on a phone that is a lot. Conversion
happens in the Python worker, so the page stays responsive, and since
`5e927d9` a bar counts the slides as they are drawn. It is still as slow as it
was; the bar only says so.
Measured in Chrome on 21 September, from choosing the file to the first page
drawn: Kat's 9.5 MB, 32-slide deck **5.3 s**, her 29 MB, 67-slide deck
**9.2 s**, neither with an error on the page.

**Simple files, both apps**: Markdown's raw HTML blocks, footnote definitions
and reference-style link *definitions* are dropped rather than rendered; images
are dropped in Markdown and in HTML (nothing can be fetched — the browser
version is offline-first and a converted PDF must not depend on the network).
An HTML page keeps its own CSS, so a page designed for dark backgrounds can
come out oddly; the page's navigation and footers are read as text like
everything else. A picture written into a page as a `data:` URI is kept, but
if any one of them is truncated or in a format MuPDF will not draw, *every*
picture on the page is dropped — MuPDF refuses the page as a whole, and the
words matter more. RTF keeps words and paragraph breaks only, so it makes no
contents entries at all; its Symbol-font bullets are dropped, since they are
private-use characters that draw as a box and say nothing. `.txt` and `.md`
are laid out on A4 at 11pt — a fixed page, not a reflowing one, so changing the
zoom does not re-wrap the text.

**FictionBook**: MuPDF lays out a `.fb2` table with the first row's cells run
together ("SpeedFeeling"), which the voice would read as one word. Its own
layout, not something `convert.py` reaches — worth knowing if a book turns up
with tables in it. Prose and chapters are fine.
