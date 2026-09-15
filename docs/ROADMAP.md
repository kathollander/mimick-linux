# Roadmap

Where Mimick is, and where it's going.

## Done — v0.1

**Reading**
- PDF viewing with continuous scrolling, rendered at 180 DPI or higher
- Layout analysis (recursive XY-cut) so sidebars, running headers and footers
  are not read aloud, with a visible, editable reading order (`Ctrl`+`R`),
  remembered per document
- In-text citations passed over: numeric, APA, Harvard, Chicago and MLA
- Reference lists, the masthead and the author declarations left out, with one
  switch (**Display → Clean up text for reading**) that turns the whole idea off
  for live reading and MP3 conversion alike
- Ligatures expanded and stranded accents repaired before the voice sees them
- Hyphenation rejoined across line breaks; web addresses and page numbers never
  read
- Read aloud with Microsoft's online neural voices (322, 47 English)
- **Word-by-word highlighting** synchronised to the voice, auto-scrolling
- Click a sentence to read from there, or select a passage and press Enter
- Speed 0.75× to 3×
- Remembers your position in every document
- Offline voices via Piper, with a download manager and previews
- Automatic fallback to an offline voice if the connection drops mid-document
- Kokoro as a higher-quality, much larger offline alternative

**Annotating**
- Highlights in four colours, saved as real PDF annotations
- Notes in a panel beside the page, connected to their passage, stacked so they
  never overlap, scaling with the zoom
- Optional heading per note, and your name saved as the annotation author
- Filter the panel by highlights or notes, with counts
- Configurable note typeface and size, previewed live
- Save into the PDF, or Save As a separate annotated copy

**Audio**
- Convert a document, page range or selection to MP3
- Measured time estimates for the conversion and the finished audio
- Cancellation that actually stops and leaves no partial file
- Open the location, or open straight into a chosen player, when finished

**Getting it running**
- One-command installer, applications-menu entry, uninstaller
- README written for people who don't use a terminal

## Done — v0.2

**Windows**
- Every platform assumption moved into `mimick/system.py`
- Settings in `%APPDATA%\Mimick`, voices and ffmpeg in `%LOCALAPPDATA%\Mimick`
- `install.ps1` / `uninstall.ps1`: venv, dependencies, an ffmpeg download,
  Start Menu shortcut, `mimick` on `PATH`, and an "Open with" entry for PDFs
- No console window behind the app, and none flashing per sentence while reading
- A multi-size `assets/mimick.ico`

Written on Linux and **not yet run on Windows** — see the release checklist.

**Reading**
- Two-column pages read down each column rather than across the page
- A sentence that runs from the foot of one column into the head of the next is
  spoken as one
- Citations listing several works, names with a tight comma, reprint dates and
  bracketed date-with-page are all passed over
- A sentence is never cut inside a bracket, so a citation cannot be half-spoken
- A sentence that mentions a website is read; only runs that are mostly link
  are skipped

**Notes**
- Notes save themselves to a copy beside the document; the original is never
  written to, and reopening it opens the copy
- Saves are whole-file, verified, and moved into place atomically
- `Ctrl`+`C` copies the selection, rejoining words broken across a line
- The notes panel is a page-at-a-time column that scrolls on its own
- Note titles wrap instead of being cut off
- Right-click for *Start reading from here*, which works with click-to-read off

Released 12 September 2026:
<https://github.com/kathollander/mimick/releases/tag/v0.2.0>

## In hand — not released yet

**Speed past 3×, and the 3× that was not.** Neither voice engine will speak
much faster than twice normal: Edge's service clamps its `prosody rate` at
+100% and returns byte-identical audio for 2×, 3× and 6× alike, so the 2.5×
and 3× the speed box offered had been giving 2× all along. The rate is now
split — as much as the engine will honestly do, the rest taken out of the
rendered audio by ffmpeg's `atempo`, which keeps the pitch where it was and
costs about 70 ms a sentence. Word timings are divided by the same factor, so
the highlight stays locked to the voice. The list goes to 5×, and the prefetch
queue is deeper because at that speed a sentence is gone before the next one
has been fetched. `Engine.render` is the one place this happens, for the same
reason the text pipeline has one path.

**Ctrl+Z for highlights and notes.** Adding a highlight, editing a note and
deleting one are all undoable, with Ctrl+Shift+Z to put them back. Edits are
recorded by word index rather than by object, because undoing a deletion has to
build a new annotation with a new xref. Nothing else is undoable, deliberately.

**Highlight and Add note come unclipped.** They are one strip now, and it can
be dragged to the notes panel, the top or bottom of the reading area, or left
loose over the page. This fixes a real defect as well as adding the arrangement:
Add note used to live inside the notes panel header, which is hand-positioned
inside the page view, so turning the notes column off took the only way of
writing a note with it. See `mimick/ui/markup_bar.py`, including why Qt's own
QToolBar could not do this.

**Copying a highlight or a note, and removing one.** Copy only ever worked on
a drag selection, and clicking a highlight deliberately *clears* the selection,
so Ctrl+C on a highlight did nothing at all. Right-clicking the notes column
did nothing either -- the handler said so in as many words. Now: Ctrl+C with no
selection copies the picked-out highlight and its note; right-click, on the
page or on the card, offers to copy the passage, the note or both, read the
passage, or delete it; and a picked-out highlight carries a small x -- in the
page's margin, level with its last line, so it never sits on a word -- that
removes it in one click. Every removal is undoable.

## Testing notes

`MIMICK_CONFIG_DIR` and `MIMICK_CACHE_DIR` redirect settings and downloads to
throwaway directories. **Always set `MIMICK_CONFIG_DIR` when running the app
under test**, or the test overwrites the settings you actually use — including
the notes-panel filters, which makes the notes column look broken.

`tools/check_reading.py` runs the layout analysis over a PDF or a folder and
reports the share of words it would read plus any sentences that look stitched
together. It found two real defects the first time it ran — unrejoined
hyphenation and adjacent regions bleeding into one another — so point it at new
documents before trusting them.

**A fresh clone's `Testing/` holds only the MDPI sample.** The two-column paper
that found most of the reading bugs is a *For the Learning of Mathematics*
article, which is not ours to redistribute, so it is git-ignored. Any
two-column PDF will do to retest that work, and it is worth having one:
single-column documents exercise none of it.

**Notes are written as you work**, so a test that makes a highlight leaves a
`(notes).pdf` behind next to whatever it opened. Those are git-ignored too, but
copy the PDF somewhere throwaway rather than annotating the samples in place.

`tools/check_shortcuts.py` verifies every key the shortcuts window lists is
really bound, so that window cannot drift from the app. Run it after touching
either:

```
QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \
    .venv/bin/python tools/check_shortcuts.py
```

**Worker threads and PySide6.** A worker's signal connected to a plain
function, a bound method, or even a `@Slot`-decorated method is delivered
*inside the worker thread* — passing `Qt.QueuedConnection` explicitly does not
change it. Anything that touches widgets, or that shuts the worker thread down,
must therefore not run in a signal handler: `QThread.wait()` called from a
handler waits on the thread it is running in and deadlocks outright. The export
uses `QCoreApplication.postEvent` with a custom `ExportEvent`, which Qt does
guarantee is handled in the receiving object's own thread. Reuse that pattern
for any new worker that reports back.

A note on editing this codebase: some string literals hold escape sequences
(`…`, `—`) while others hold the character itself. Pattern-matching on
those characters fails silently. Read the actual text first, and prefer edits
anchored to line numbers or to plain-ASCII substrings.

## Before the next release

v0.1.0 and v0.2.0 are both out; `main` is v0.2.0. What is still outstanding:

- [ ] **Try it on more real documents.** Scans, books with footnotes, slide
      decks, anything with tables or captions. The MDPI article in `Testing/`
      now reads correctly, and a synthetic two-column paper reads column by
      column, but layout analysis is heuristic and will meet documents it
      mishandles. `Ctrl`+`R` is the escape hatch; a document that needs a lot
      of hand-correction is a bug worth reporting.
- [ ] **A screenshot or short clip in the README.** The word-level highlighting
      is the thing people need to see to understand what this is.
- [ ] **Test the installer on a clean machine.** Ideally a fresh Ubuntu VM, and
      at least one non-Ubuntu distro, so the apt-specific parts are known
      rather than assumed. This is now the largest untested surface: the
      launcher and the repository contents are verified from a fresh clone,
      but the apt and pip steps have only ever run on the machine that built
      the project.
- [x] **Decide the repository name** — `mimick`, and the project keeps the name.
- [x] Issue templates (`.github/ISSUE_TEMPLATE/`).
- [x] Publish to `github.com/kathollander/mimick` (public).
- [ ] **Run `install.ps1` on a real Windows machine.** Nothing in the Windows
      support has met the platform it targets. In rough order of risk: does the
      installer complete; does the Start Menu shortcut open a window; is there
      a console window behind the app or flashing between sentences; does the
      ffmpeg download land somewhere `ffmpeg_command()` finds it; does MP3
      conversion work; does "Open with" appear for PDFs.
      *In progress* — the `windows` branch is with one Windows user.
- [x] **Merge and tag v0.2.0.** Done on 12 September 2026 without waiting for
      the Windows report, because the reading and notes fixes mattered to the
      people already using it on Linux. The README now warns about Windows in
      the heads-up box at the top rather than in known issues.
- [ ] **Listen for highlight drift on Windows.** The word-sync highlight assumes
      the playhead matches what is audible. If WASAPI buffers more deeply than
      ALSA, the highlight will lag the voice — audible, but invisible to any
      check tool. `sd.OutputStream` takes a latency hint if it does.
- [ ] Add `CONTRIBUTING.md`.
- [ ] **Consider a `pyproject.toml`.** The package is not installed into the
      venv, so the launcher has to set `PYTHONPATH` and everything breaks if
      the project folder moves. Installing it properly would fix both.
      `install.ps1` already sidesteps this with a `.pth` file in site-packages,
      which works from any directory and needs no wrapper; `install.sh` could
      do the same in one line, and should, once someone can retest the Linux
      launcher and the applications-menu entry against it.
- [x] Tag `v0.1.0`, and `v0.2.0`.

Already in place: `LICENSE` (AGPL-3.0, required by MuPDF), `.gitignore`,
`install.sh` / `uninstall.sh`, and the README.

## Small known bugs

Found by use and left alone, deliberately — each is cosmetic or rare, and
listed so the next session does not have to rediscover it.

- **A hyphenated surname broken across lines keeps its space.** "Piatek-
  Jimenez" is spoken with a pause. `_mark_hyphenation` only rejoins when the
  following word is lower-case, which is what stops it eating genuine
  hyphenated compounds; telling the two apart needs more than case.
  `check_reading.py` flags it.
- **Save As on an already-annotated copy suggests `X (notes) (notes).pdf`.**
  The suggestion is built from the open document's name, which is by then the
  companion. `annotations.companion_for` already handles this correctly and
  should be what builds the suggestion.

## Next up

### A notes index
The panel shows notes next to their page. A searchable panel listing every note
in the document would help when reviewing a long reading.

### Standalone sticky notes
Every note currently belongs to a highlight, because a note is stored in the
highlight's `Contents` field. A note pinned to a point without highlighting
anything is a separate PDF annotation type (`add_text_annot`) and would suit
margin remarks that aren't about a particular phrase.

### Footnote markers
Superscript reference numbers arrive attached to words and are not yet detected.
They would need font size from `get_text("dict")` rather than `"words"`.

### Underline and strikeout
Only highlighting exists so far. PyMuPDF supports both
(`add_underline_annot`, `add_strikeout_annot`).

### Exact word timings offline
Piper reports phoneme alignments in some builds
(`piper.patch_voice_with_alignment`). Wiring those in would give offline reading
the same exact highlighting the Edge voices get, instead of timings estimated
from word length.

### Re-measuring the conversion estimates
`mimick/export.py` carries two measured constants: characters of source text per
second of speech, and per second of conversion. They were measured on a home
connection; if estimates drift, time a known document and adjust.

---

## Planned — "Anywhere mode"

Reading selected text from any application with a hotkey, not just PDFs open
in Mimick. Still not started, but now designed: see
[`ANYWHERE-MODE.md`](ANYWHERE-MODE.md) for the reuse surface, the two
verified facts about the hotkey, why there can be no true overlay on
GNOME/Wayland, and the build order.

The short version: `Player` never knew what a PDF was, so the engines,
prefetch queue and transport all reuse unchanged. The new code is one small
text-to-`Sentence` adapter plus a reading window that does the word
highlighting, since Mimick cannot highlight inside someone else's browser.

## Further out

- **EPUB support** — many university readings arrive as EPUB.
- **Pronunciation dictionary** — for names and technical terms the voice
  mangles. Especially useful for academic reading.
- **Bookmarks** within a document.
- **Per-document voice memory.**
