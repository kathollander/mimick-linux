# Roadmap

Where Mimick is, and where it's going.

## 29 September 2026 — sticky notes, and the quick switches

Kat's ask, planned with her the same day (both apps). **Sticky notes**
(`0a6ad4c`, `f4328b8`, `4f3ce5b`): a note of your own anywhere on a page, saved
as a PDF FreeText annotation with rich text -- Acrobat's text box -- so Okular,
Firefox, Chrome and Acrobat show it with its formatting, and opening the notes
PDF again gives it back to edit. + Add sticky and a formatting row (size, bold,
italic, underline, strikeout, list, colour) on the Highlight / Add note bar;
Ctrl+Alt+M; drag, resize, fold, delete, undo; cards in the panel; Find, Export
notes, the notes PDF and Read this sticky note all take them in. The shared
part is `annotations.py` (`Sticky`, `clean_rich`, `sticky_height`,
`sticky_sentences`, `with_sticky_matches`) and `notes_export.py`; the window's
is `mimick/ui/sticky_note.py`. Checks: `tools/check_sticky.py`,
`tools/check_sticky_window.py`.

**The quick switches** (`f4328b8`): the browser version's strip under the top
bar, each switch the same QAction as its menu entry; the toggle is at the top
bar's right end, or Display → Quick switches. Night/Day and the timer are left
out until the desktop has a light theme and a sleep timer (the *Then* list).

The browser version's write-up, with the traps found: `../Mimick/docs/HANDOFF.md`,
*Latest: sticky notes*. **Nothing is pushed**, and this repo still must not be
pushed before Kat runs `../mimick-linux-squash-and-push.sh`.

## 25 September 2026

**OCR for scans** (`c9c83d6`): a scan's text is recognised as it opens, with
the Tesseract built into MuPDF -- only `tesseract-ocr-eng` is needed, and
`install.sh` installs it. It works like the browser's: up to 20 pages at once
with a bar and Stop, more asks first; the words go into a copy under the cache
(`mimick/ocr.py`), found again on reopening with its notes; Reading →
Recognise the text in this scan does it later. `tools/check_ocr.py`.

**The *Then* list below is the desktop's only.** The browser already has a
light theme (Display ▾ → Theme) and voice credits in About; the desktop has
neither yet. What is left here: sleep timer, pronunciation, light theme, media
keys, voice credits, the MP3 licence rule.

## Since then — 24 September 2026

`c3a5b09`: three-column pages are read down each column (a governance
guide of Kat's, kept outside the repos). `layout.py` only; ported to the browser
(`7df1b5a`), so the shared files match again. The full write-up is in
`../Mimick/docs/HANDOFF.md`, *Latest: three-column pages*.

**`check_caret` and `check_find` pass** (24 September, later) when run as their
headers say, with `QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=<an empty
folder>`. They failed earlier the same day (word steps one short; Ctrl+F focus,
Shift+Enter, F3) -- most likely run against the real settings folder, which was
not re-run to prove it, so as not to touch Kat's settings.

`c4c8774`: **Export notes writes Word, OpenDocument, PDF or Markdown**, the
notes document Kat asked for on 23 September -- see `../Mimick/docs/HANDOFF.md`,
*Kat's list of 23 September*. `notes_export.py` is now shared with the browser
through `tools/port.sh`.

## Where this was left — 19 September 2026

A session that started with "Mimick won't open" and ended with the desktop app
having caught up with the browser version. Thirteen commits, `2909eba` to
`1f95c77`. Every check in `tools/` passes in this repo, and all 26 of the
browser's pass in `../Mimick`.

**Three things need a person, in this order.**

1. **35 commits sit on `reader-and-voice-list` and have never been pushed.**
   That branch is the only copy of all of today's work, on one machine.
   `main` has none of it. The browser repo is in sync with its origin, so it
   is safe; this one is not. Decide where this lands — the two apps are
   properly in step now, which makes it a natural moment to merge.
2. **`mimick/engines/piper.py` is still uncommitted**, from a session on
   17 September that left a note saying to ask Kat first. It withholds the
   Lessac voice, whose recordings are licensed for research only. Kat's
   instruction on 19 September was to hold it until the two repos' batches
   line up. They now do.
3. **`docs/HANDOFF.md` is also uncommitted**, from that same session, and was
   deliberately left untouched today so this session's work would not commit
   somebody else's. Read it before committing it; it carries the voice-licence
   findings and the launch checklist.

**What was done.** The launcher, broken by the repository rename (it and the
venv's `.pth` both still named the old path, and the applications menu runs
with `Terminal=false`, so nothing was said). Then the three features that
changed what this app can do — Find, the contents panel, and opening `.txt`,
`.docx`, `.odt` and `.epub` — plus Export notes, the Reading menu, `Ctrl`+`Y`,
and drag and drop. See *Catching up with the browser version* below.

**Two bugs found on the way, both shipped, both fixed in both apps.** The voice
said "nonstatus" for "non-status", because every line-break hyphen before a
lower-case letter was closed up (`ed8c125`). And the browser's contents panel
sent people to the wrong section of real journal PDFs, because a bookmark's
destination point is measured from the bottom of the page and `pages.outline`
read it as from the top — the sample document this project generates happens to
store it from the top, which is why nothing caught it (`../Mimick`, `7acfab8`).

**What is left** is the middle list below, *Then*: the sleep timer,
pronunciation, a light theme, OCR (done 25 September), media keys, voice
credits in About, and the MP3 licence rule. The rest are not started. *Back 10 seconds* is written up where it
sits, with why it is not a menu entry.

**A note for whoever works in the browser repo next.** Another session
(`mimick-web-f4`) was working there on start-up progress and Firefox
performance on 19 September, and had uncommitted work in `js/reader.js`,
`js/document-worker.js` and `js/page-worker.js`. It found that a fresh Firefox
downloads the 18 MB PyMuPDF wheel four times in parallel — one per worker — so
72 MB instead of 18, and 137 s to *Ready* against Chrome's 50. Check whether
that landed. The browser checks share one Chrome debugging port (9333) and one
served copy of the files, so agree who owns them before running a suite.

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

The first four of these are committed on `main`. Everything from **Footnotes**
down is uncommitted, sitting in the working tree until it has been used on a
real reading — see the handoff for the file-by-file state.

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

**Footnotes, and a switch for them.** A numbered block, low on the page, set
smaller than the body type is labelled a footnote; the numbers then have to
climb through the document, restarting at 1 per page allowed, and there have to
be at least two of them. All three signals must agree, because a false positive
silences real text. **Display → Read footnotes** turns them off, and is greyed
out where there are none. They are still read *after* the page rather than
where they are referred to -- nothing can move them without cutting the body
text mid-sentence -- so the choice offered is whether to hear them at all.
A footnote keeps its label either way, so the switch never renumbers regions
and annotations keep pointing at the same words.

**A sidebar and the text beside it, as one block.** MuPDF hands back a page's
text in blocks, and it sometimes puts a narrow label column and the paragraph
next to it in one -- their lines alternating, so a keyword list reads a word at
a time into the abstract. The XY cut cannot undo that: by then the two columns
are one rectangle. So before the cut, a block whose own lines fall into columns
-- separated by a gap no line crosses, and standing side by side rather than
one after the other -- is split into one block per column. Everything else is
passed through as MuPDF gave it. See `layout._text_blocks`.

**A text cursor, for selecting without the mouse.** Highlighting meant dragging
across the page. There is now a cursor that follows the read-along point, so
pausing leaves it where you stopped listening; the arrow keys move it by word,
line and sentence, and Shift selects as it goes. It moves a word at a time
rather than a letter, because a highlight is stored as a run of whole words --
a letter-wise cursor could show a selection it could not save. While the voice
is reading the arrows keep their old jobs, so nothing you use while listening
was taken away.

The keys are `QShortcut`s in `MainWindow._build_shortcuts`, not a
`keyPressEvent` on the page view, and should stay there: a window shortcut
beats a focused widget's key handler, and `tools/check_shortcuts.py` can only
see keys bound that way. Left and right are window-wide, as they always were;
up, down, Home and End are scoped to the page view with
`WidgetWithChildrenShortcut`, because otherwise the page number box loses its
own arrows -- a worse trade than the cursor is worth. `tools/check_caret.py`
drives the whole thing with real key events, and checks both halves of that.

**A footer too far from the foot of the page.** Furniture was found in a band
8.5% deep at the top and bottom. A journal that sets its footer 85pt clear of
the page edge puts it above that band, so `VOLUME 19, ISSUE 1, 2024 ·3` was
read out at the end of every page. The lowest block on a page, if nothing else
comes within 30pt of it, is now treated as being in the band -- and then still
has to repeat across pages, or be a scrap, before it is called furniture. See
`layout._strand_footer`.

**Citations with more shapes.** Initials, corporate and legal names, and an
acronym given in brackets are recognised, so `R. v. Marshall 1999` and
`Royal Commission on Aboriginal Peoples [RCAP] 1996` are passed over rather
than read out mid-sentence.

**The voice list keeps your place, and takes your names.** Previewing a voice
refilled the list, and the refill threw the selection back to the suggested
voice — so every voice you listened to lost you the one you were on, in a list
of 176. The refill now holds the selection, the scroll position and the status
line it used to wipe. Beside that, a voice can be given a nickname: typed into
the box under the list, stored against the voice's key in `voice_nicknames`,
shown in italics in the list and plainly in the voice box in the main window,
searchable, and off again when the box is emptied. `tools/check_voices.py`
covers both.

**Offline word timings are exact.** A Piper model decides how long each phoneme
lasts; `mimick/engines/timing.py` exposes that and matches it to the words, the
same way the browser version does. The letter-count estimate was up to 300 ms
out after a pause. Kokoro still estimates. `tools/check_timing.py` covers it.

## Testing notes

`MIMICK_CONFIG_DIR` and `MIMICK_CACHE_DIR` redirect settings and downloads to
throwaway directories. **Always set `MIMICK_CONFIG_DIR` when running the app
under test**, or the test overwrites the settings you actually use — including
the notes-panel filters, which makes the notes column look broken.

`tools/check_caret.py` opens a document offscreen, sends real key events, and
checks where the cursor and the selection end up. It found the end-of-line case
the first time it ran -- see `PageView.caret_trailing`.

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
      of hand-correction is a bug worth reporting. The first scan tried, a
      598-page book, took three minutes to open until 16 September (HANDOFF,
      trap 18); it reads now, but its reading order has not been judged.
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
      venv; both installers write a `.pth` file naming the project folder
      instead, so everything still breaks if that folder moves. Installing it
      properly would fix that. (`install.sh` moved from a `PYTHONPATH`
      launcher to the `.pth` file on 16 September, tested from a scratch home
      folder; the applications-menu entry has not been clicked since.)
- [x] Tag `v0.1.0`, and `v0.2.0`.

Already in place: `LICENSE` (AGPL-3.0, required by MuPDF), `.gitignore`,
`install.sh` / `uninstall.sh`, and the README.

## Small known bugs

Found by use and left alone, deliberately — each is cosmetic or rare, and
listed so the next session does not have to rediscover it.

- **A page printed sideways is highlighted across its lines, not along
  them.** Seen on a scanned book in the browser version, which uses this
  repo's rectangles, so it happens here too. The sentence tint is joined line
  by line on the assumption that lines run left to right.

## Catching up with the browser version

The browser version shipped on 17 September and overtook this one. Each item
below names the browser file that already solved the hard part, so none of it
started from nothing. The three that changed what the app can do are done, as
are the small ones; what is left is the middle list, *Then*. The full register,
with the desktop features the browser is still missing, is
[`../Mimick/docs/PARITY.md`](../Mimick/docs/PARITY.md) — that file is the
register, this section is the order to work in. Checked against this repo's
code on 18 September.

**Note the two repos swapped names on 17 September.** The desktop is
`Mimick-linux`; `Mimick` is now the browser version. Anything still saying
`../mimick-web` means `../Mimick`.

Shared code — `layout.py`, `citations.py`, `speech.py`, `document.py`,
`annotations.py` and, since 18 September, `convert.py` — flows one way, this
repo to the browser, via that repo's `tools/port.sh`. So anything below that
needs a change in those files has to be done **here first**.

⚠️ **Adding a file to `port.sh` is two edits, not one.** The browser also lists
the package's files in `js/python.js` (`PACKAGE`), and a file added to one and
not the other leaves its workers unable to import it — the page never gets past
"Starting Mimick", and every browser check times out waiting for *Ready*. That
happened with `convert.py`.

✅ **Ported on 18 September**, three times as the shared code changed; the
browser is on this repo's `b48c5bc`. It has the hyphen fix, its `reader.py`
calls `Document.find` instead of keeping a second copy of the search, and the
document conversion it used to own now comes back to it from `convert.py`. The
`check_reading` baselines did not need regenerating — the sample is *The
Raven*, whose two broken words are followed by capitals, so the hyphen fix does
not change them, which was checked rather than assumed.

### The three that change what the app can do — all done, 18 September

Each added something a reader could not get here at all, and each had its hard
part already written in the browser version.

1. ✅ **Find in document** (`Ctrl`+`F`) — done 18 September. `mimick/ui/find_bar.py`,
   `Document.find` in `document.py` (so the browser gets it through `port.sh`),
   `tools/check_find.py`. Every match lit in violet, the current one strongly;
   Enter / Shift+Enter / F3 between them, Match case, Esc leaving the match
   selected. Two traps are written up in the commit: the window's own
   `QShortcut`s swallowed keys typed into the box, and amber matches were
   indistinguishable from yellow highlights.
2. ✅ **Contents panel** (`F9`) — done 18 September. `mimick/ui/contents_panel.py`,
   `Document.outline` / `word_of_heading` / `first_sentence_from`,
   `tools/check_contents.py`. Nested, the section on screen lit, click to go,
   right-click to read from there, a tab on the page's edge when hidden.
   **A bookmark's destination point is not usable**: the PDF specification
   measures it from the bottom of the page, `Testing/Big Ideas…` stores it that
   way, and `sample/test-paper.pdf` measures from the top, so no single reading
   is right for both. Headings are found by their own title instead.
   The browser had the same bug and had shipped with it: on *Big Ideas* six of
   its twelve entries went to the wrong section. Fixed the same day in
   `../Mimick`, `7acfab8`, with `tools/check_outline.py` as the guard.
3. ✅ **Open `.txt`, `.docx`, `.odt` and `.epub`** — done 18 September.
   `mimick/convert.py` (moved out of the browser's `reader.py`, so both versions
   now run one copy), `tools/check_convert.py`. Laid out as PDFs and then read
   as PDFs, notes and all. The converted PDF is kept under the cache directory,
   named for the source and a hash of its contents, which is what brings
   highlights back on a second opening. Opening works from the Open dialog, the
   command line, the applications menu, Open Recent, and **dropping a file on
   the window** — which this app never supported at all, for any file type.

### Then

- **Export notes as Markdown** — page, section, passage, heading, note. The one
  way notes leave the app for Word or Docs. Browser: `notesText` in `js/notes.js`.
- **Reading time in the bottom bar** — how long the document takes at the speed
  in the Speed box, changing whenever it changes; while reading, what is left.
  `export.py` already holds the measured rate (15.1 characters a second at 1×).
  Browser: `showReadingTime` in `js/reader.js`.
- **Sleep timer** — Display → Stop reading: 15/30/60 minutes, end of page, end
  of section, pausing between sentences rather than mid-word. Browser:
  `sleepDue` in `js/reader.js`.
- **A pronunciation list** — a word as printed and a sound-alike, applied before
  the phonemizer, with the timings put back under the printed word so
  highlighting is unchanged. Already wanted here under *Further out*. Browser:
  `js/pronounce.js`.
- **Media keys** — play/pause, next and previous sentence, stop, from a
  keyboard's media keys. On Linux that is MPRIS over D-Bus; there is none here.
- **Voice credits in About** — dataset, licence, link and the voice each was
  trained on, as CC BY, BY-SA and BY-NC-SA ask. `about_dialog.py` has the AGPL
  blurb and nothing per voice.
- **MP3 in licence-clean voices only** — half done. The uncommitted `piper.py`
  withholds Lessac from the catalogue, but `export_dialog.py:72-77` still offers
  every voice for conversion, with no note saying why any is absent.
- **A light theme** following the system, and Display → Theme (Night / Day /
  Match the system). `ui/theme.py` is one fixed dark palette. Browser: the token
  sets at the top of `reader.html`.
- **OCR for scans** — the only mention of OCR here is an error string telling
  the reader their scan needs it (`main_window.py:846`). PyMuPDF can do it
  natively through `get_textpage_ocr`, which is a shorter road than the
  browser's Tesseract build.
- **A guided tour** — **Show me around**, fourteen steps on a sample document,
  each finished by the reader doing it with the app's own keys. Browser:
  `js/tour.js`.

### Small

- ✅ **`Ctrl`+`Y` as a second redo**, beside `Ctrl`+`Shift`+`Z` — done 18 September.
- ✅ **Reading ▾ → Read from the top of this page**, and **Go to where the voice
  is** — done 18 September. The switches the browser also keeps under Reading
  stay in Display here; rearranging menus people know is Kat's call.
- **Back 10 seconds.** Not done with the two above, because it is not a menu
  entry: `player.py` writes whole sentences to the audio device
  (`Player._speak`) and cannot seek inside one. It needs a frame offset the
  playback loop honours, and `←` already goes back a whole sentence, so the
  gap this fills is small.
- **A progress bar while a document opens**, so a long book does not look hung.
  The only progress bar here is the voice downloader's, and it is a busy stripe
  (`voices_dialog.py:215`, "since size is not reported").
- **Keep the floating markup bar inside the window** while it is dragged and
  when the window shrinks — the browser's can be lost that way; check whether
  `markup_bar.py` can too.
- **Draw scanned pages ahead and keep them**, only if slow pages actually bite
  here (a page of the 598-page scan takes 0.6 s).
- **The same moved-folder trap on Windows.** `install.sh` now generates a
  launcher that checks its own path and says so in a window (18 September,
  after the rename made Mimick stop opening with no message at all).
  `install.ps1` has the identical weakness and no such guard: the Start Menu
  `.lnk` points straight at `\.venv\Scripts\pythonw.exe`, and `pythonw` has no
  console, so a stale `mimick.pth` fails with nothing shown. There is no shell
  script to guard there, so it needs another shape — a small check inside
  `__main__.py`, or a `.cmd` shim between the shortcut and Python.

### A bug found on the way

✅ **A real hyphen was lost when it fell at a line end** — fixed 18 September,
`ed8c125`, `tools/check_hyphens.py`. `_join_words` treated every break before a
lower-case letter as the typesetter's and closed it up, and compound words are
overwhelmingly lower-lower, so the voice said "nonstatus", "secondgeneration"
and "selfgovernment", and `Ctrl`+`C` copied those. The document is now its own
evidence: both spellings are counted across the whole document and the commoner
one wins, with a figure before the hyphen and the prefix "self" as the two rules
for a compound the document only writes once.

**This is shared code, so the browser version needs `tools/port.sh`** — see
below.

### Kat's call, not a session's

- **Highlight colours for colour-blind readers.** Simulated over white at the
  drawn opacity, Blue and Pink are close for protanopia (ΔE 6.8) and Green and
  Blue for tritanopia (6.4); every other pair is 12 or more. `annotations.COLOURS`
  is shared code, so changing it changes both apps *and* recolours notes already
  saved. Change them in both or neither.

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

## In progress — opening more kinds of file

Asked for by Kat on 19 September: `.txt`, `.html`, `.md` and other simple
files, and importing a PowerPoint or Impress presentation as a PDF that can be
saved — in both apps. **As of 21 September the shared conversion is done and
the browser app has all of it**: Markdown, HTML, RTF, FictionBook and
presentations (one page per slide) all open there, with a bar that counts a
deck's slides. **This app's own wiring is what is left** — the Open dialog and
drag and drop follow `CONVERTIBLE` for free, but converting off the UI thread,
the LibreOffice path and `tools/check_convert.py` are not done. The design,
what is left, the LibreOffice question and the limitations are in
[`MORE-FILE-KINDS.md`](MORE-FILE-KINDS.md), which is the file to start from.

## Further out

- ~~**Mimick in a browser**~~ — **done, and shipped 17 September**, in
  `../Mimick`. The open question is answered: Piper's voices do carry the whole
  app on their own, and the browser version uses no Microsoft voice at all.
  [`FUTURE-FEATURES.md`](FUTURE-FEATURES.md) is now a record of the plan rather
  than a plan.
- ~~**EPUB support**~~ and ~~**Pronunciation dictionary**~~ — both exist in the
  browser version; see *Catching up with the browser version* above, which is
  where they are tracked now.
- **Bookmarks** within a document.
- **Per-document voice memory.**
