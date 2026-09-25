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

## Before tagging v0.1.0

Published on 12 September 2026 at <https://github.com/kathollander/mimick>.
What is still outstanding before it is worth calling a release:

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
- [ ] **Merge and tag v0.2.0** once that comes back. The branch is pushed but
      not merged; `main` is still v0.1.0. Notes are drafted in
      `docs/release-v0.2.0.md`; tick GitHub's pre-release box, and delete the
      draft afterwards.
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
- [ ] Tag `v0.1.0` once the above is done.

Already in place: `LICENSE` (AGPL-3.0, required by MuPDF), `.gitignore`,
`install.sh` / `uninstall.sh`, and the README.

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

*Recorded here so it isn't lost; not started.*

A background service that reads **any** selected text, in any application — a
web page in Firefox, a PDF already open in Okular, a paragraph in LibreOffice,
a message in a chat window. Select the text, press a hotkey, hear it.

**How it would work**

1. A small tray application starts with the session.
2. A global hotkey (say `Super`+`R`) registered through GNOME's custom
   keybindings, which is the approach that works under Wayland.
3. On the hotkey, read the primary selection with `wl-paste --primary`
   (Wayland) or `xclip -o` (X11).
4. Feed that text into the same player Mimick already uses — the engines,
   prefetch queue and transport all get reused unchanged.
5. Tray icon offers pause, stop and speed.

**Why it's worth doing:** it covers every case the PDF reader doesn't — EPUBs,
websites, emails, anything on screen. It's the piece that makes the whole thing
feel like a system service rather than a single app.

**Known difficulties**

- Wayland deliberately prevents applications from grabbing global hotkeys, so
  the binding has to be registered with the desktop environment instead. That
  means GNOME-specific setup, with a different path for KDE.
- The primary selection behaves inconsistently across toolkits; Electron apps
  are the usual offenders.
- Reading a whole page *without* a selection would need AT-SPI, the
  accessibility layer screen readers use. It's fragile on Wayland and broken in
  many Electron apps, so selection-based reading should stay the primary path.

## Further out

- **EPUB support** — many university readings arrive as EPUB.
- **Pronunciation dictionary** — for names and technical terms the voice
  mangles. Especially useful for academic reading.
- **Bookmarks** within a document.
- **Per-document voice memory.**
