# Handoff

Everything a fresh session needs to pick Mimick up. Written 11 September 2026,
the evening the project was built; updated 12 September, the day it was
published and v0.2.0 released, and again on 15 September after four changes to
the reader itself.

## What Mimick is

A PDF reader that reads aloud in natural voices, highlighting each word as it
speaks it. It exists because Linux had no equivalent of Edge's Read Aloud; it
runs on Windows as well as of v0.2.0. Written by Claude Code, arranged by Kat Hollander
([github.com/kathollander](https://github.com/kathollander)). AGPL-3.0, because
MuPDF is.

Read [`../README.md`](../README.md) first — it is the user-facing description
and is kept accurate. Then [`ROADMAP.md`](ROADMAP.md) for what is planned and
the traps in this codebase.

## Running it

```bash
./install.sh                 # venv + deps + desktop entry; safe to re-run
.venv/bin/python -m mimick "Testing/Big Ideas from Atleo and Boron 2022.pdf"
```

A fresh clone's `Testing/` has only that one document in it; the two-column
paper most of the reading work was done against is not ours to redistribute.
Any two-column PDF will do, and it is worth having one — a single-column
document exercises none of that code.

That second line only works **from the project folder** -- see trap 10. To
exercise what a user actually gets, run the installed launcher from somewhere
else:

```bash
cd ~ && ~/.local/bin/mimick
```

**Always set `MIMICK_CONFIG_DIR` when testing**, or the test overwrites the
settings actually in use:

```bash
QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \
    .venv/bin/python tools/check_shortcuts.py
.venv/bin/python tools/check_reading.py Testing/
```

## How it fits together

| File | Holds |
| --- | --- |
| `mimick/system.py` | Every platform difference: folder locations, ffmpeg, console-window suppression. |
| `mimick/document.py` | PDF → words → sentences. Word order, hyphen rejoining, run breaking. |
| `mimick/layout.py` | Recursive XY-cut. Decides which regions are body, aside or furniture. |
| `mimick/citations.py` | Regexes for in-text citations, so `[51]` is not read aloud. |
| `mimick/speech.py` | Cleanup before the voice: ligatures, stranded accents, masthead and declarations. |
| `mimick/player.py` | Playback: prefetch queue, transport, word-timing alignment. |
| `mimick/engines/` | `edge.py` (online, word timings), `piper.py` (offline), `kokoro.py`. |
| `mimick/export.py` | MP3 conversion; streams PCM to a temp file, two workers. |
| `mimick/annotations.py` | Highlights and notes as real PDF annotations. Also where a document's notes get written, and how. |
| `mimick/ui/page_view.py` | The canvas: its own scroll area, page cache, notes panel, plan overlay. The panel scrolls separately from the page. |
| `mimick/ui/markup_bar.py` | Highlight and Add note, and the four places they can be dragged to. |
| `mimick/ui/main_window.py` | Everything else. The big one. |
| `tools/` | `check_shortcuts.py`, `check_reading.py`. Run both after changes. |

**The reading pipeline**, in order: `layout.analyse` cuts each page into regions
and labels them, then marks the reference list and everything after it →
`Document._build_sentences` walks regions in reading order, taking words from
readable ones and passing each through `speech.normalise` → runs break at region
boundaries, except where one region stops mid-sentence and the next starts
mid-sentence, which is a column or a page carrying on → a run that is labelled
boilerplate is dropped whole → `chunk_into_sentences` splits on punctuation, but
never while a bracket is open, and drops runs that are not language →
`citations.mark_words` plus a strip of the assembled text removes in-text
citations.

**Region order is the cut's order.** `layout.analyse` must not sort its regions
by position afterwards — see trap 12. Word order follows region order, which is
why `set_region_reads` can rebuild safely (trap 9).

**There is one text pipeline, not two.** Live reading and MP3 conversion both
consume `Document.sentences`; the export dialog filters that list by page range,
and, when its cleanup checkbox disagrees with the open document, takes the list
from a second `Document` opened the other way and closed again by
`ExportDialog.release()` (a `Sentence` holds only strings and rectangles, so it
outlives the PDF it came from). Anything done to the spoken text therefore has to be done in
`document.py` or below, never in `export.py`, or the two paths drift. The
`clean_text` setting (**Display → Clean up text for reading**) and
`skip_citations` both gate behaviour inside `Document` for exactly that reason.
Reading a *selection* goes through `Document.sentences_from_range`, which is
easy to forget — it silently ignored citation skipping until it was fixed.

**Notes are never written into the document you opened.** They go to a
companion file, `<name> (notes).pdf`, beside it -- or, if that folder is
read-only, to `~/.config/mimick/notes/`. Opening the original opens the
companion when one exists, so `Document.path` is usually the companion and
`companion_for` returns itself for it. `MainWindow._notes_path` is where this
document's notes go; a debounced `QTimer` writes them a moment after each
change, and `_update_enabled` is the single place that notices there is
something to write. `AnnotationStore.save_as` is the only writer: whole PDF to a
temporary file, verified, then `os.replace`. Never reintroduce `saveIncr` --
trap 11 explains what it costs.

## Traps that cost real time tonight

**1. PySide6 delivers worker signals on the worker thread.** A plain function, a
bound method, and a `@Slot`-decorated method with `Qt.QueuedConnection` all ran
inside the worker. Calling `QThread.wait()` from such a handler deadlocks
outright — the app froze mid-conversion. The export uses
`QCoreApplication.postEvent` with a custom `ExportEvent`, which Qt *does*
guarantee lands in the receiving object's thread. **Reuse that pattern for any
new worker.**

**2. `QDialog.close()` routes through `reject()`.** `ExportProgressDialog`
overrode `reject()` to mean *cancel*, so closing it on completion only asked it
to stop and left it on screen saying "Stopping…". Every exit now goes through
`finish()`, which sets a flag first.

**3. String literals are inconsistent about escapes.** Some hold `…`
literally, others the character `…`. Pattern-matching on those fails *silently*
— three separate edits tonight appeared to succeed and did nothing, once
leaving a method with a line deleted and its replacement never written.
**Read the actual bytes first, assert that the pattern matched, and prefer
line-anchored edits.**

**4. Do not size a widget to the whole document.** Sixty pages is ~64,000px,
past where Qt coordinates behave. `PageView` is a `QAbstractScrollArea` that
paints only the visible band.

**5. `_ends_sentence` must strip punctuation from both ends.** It only stripped
trailing punctuation, so `"(p."` did not match the abbreviation `p` and the
splitter cut `(p. 21)` in half — 45 times in a 12-page paper. The voice said
"pee" and the page number was lost. Relatedly, `citations.mark_words` matches a
word that *begins* inside a citation rather than one wholly contained by it,
because `"21)."` reaches a character past the closing bracket.

**6. A dead playback thread is silent, not loud.** `align_marks` used `spoken`
as both the list of words and the loop variable over `clip.marks`, so
`spoken[offset][1]` indexed a single character and raised `IndexError` on the
first word of the first sentence. That killed the `mimick-play` thread before a
sample reached the speakers: no sound, no dialog, no clue. `Player._run`
swallows nothing, but nothing watches the thread either. **When playback does
nothing, drive `Player` directly from a script** — the traceback prints there,
where it never reaches the interface.

**7. `Player.configure` must clamp the playhead.** It replaces the sentence list
without touching `_index`, and a rebuild can shrink that list by a quarter.
`_run`'s `while self._index < len(self._sentences)` then exits at once — silent
again. It now clamps; callers that rebuild should still hold the reader's place
by *word* index, as `_toggle_clean_text` does, because sentence numbers mean
nothing across a rebuild.

**8. `VoiceLoader` is deleted out from under its own attribute.**
`loader.finished.connect(loader.deleteLater)` leaves `self._voice_loader`
pointing at a wrapper whose C++ object is gone, and any call on it raises
`RuntimeError: Internal C++ object already deleted`. The reference is cleared on
`finished` now, and `closeEvent` guards anyway.

**9. Word indices must stay stable.** Annotations store `first_word`/`last_word`.
Word order comes from region order, which does not change when a region is
included or excluded — that is why `set_region_reads` can rebuild safely. The
same rule is why `speech.normalise` may rewrite a word but must never drop one:
`clean_text` would otherwise shift every index after the first word it removed,
and the export dialog could not reuse a selection made against the open
document. Both builds give 8,395 words with identical rectangles.

**10. The applications-menu launcher is not the terminal launcher.**
`python -m mimick` resolves the package through the *working directory*. In a
terminal that is the project folder, so it works; from the menu it is `$HOME`,
so it died instantly with `No module named mimick` and no window -- the app
simply did not open. The package is not installed into the venv (there is no
`pyproject.toml`), so `install.sh` writes a launcher that sets `PYTHONPATH`.
Setting the path rather than `cd`-ing keeps a relative filename argument
resolving against wherever the user actually is. **Test the installed launcher
from `$HOME`, not from the project folder** -- from the project folder the bug
is invisible.

**11. Never save a PDF incrementally on a timer.** `saveIncr` appends a
revision to whatever is on disk and is silently wrong if that file is not
byte-for-byte what the document was opened from. The result points its `/Prev`
at itself, so the chain never reaches the original objects: Mimick refuses the
file outright, Okular repairs it and shows the first revision only, and every
note after the first save looks lost. It is not lost -- patch `/Prev` to the
previous xref offset and it all comes back -- but nobody knows that at the
time. Saves now write the whole PDF to a temporary file, check it opens with
the right pages and highlights, and `os.replace` it into place. Documents are
opened from bytes, not a path, so that replace is safe even when the file being
replaced is the one being read.

**12. Region order is not the order regions are in.** `layout.analyse` ran the
XY-cut, which produces regions in reading order, and then sorted them by top
edge -- which on a two-column page reads across instead of down, because the
foot of the left column is below the head of the right one. If you touch the
layout, keep the cut's order. The same rule is why `_pages_on_screen` exists in
`page_view`: the render margin draws a page either side of the visible band,
which is right for pixmaps and wrong for anything that must match what the
reader is looking at.

**13. No voice engine speaks much faster than 2×, and none of them say so.**
Edge's service clamps `prosody rate` at +100%: ask for 2×, 3× or 6× and the
audio that comes back is byte-identical. Kokoro clamps its `speed` outright.
Piper's `length_scale` compresses phonemes but not the pauses between them, so
6× asked for yields about 2.6× heard. None of this raises anything — the speed
box said 3× and gave 2× for a year. Anything above `Engine.max_native_rate` is
now taken out of the rendered audio by ffmpeg `atempo` in `Engine.render`, with
`Clip.marks` divided by the same factor. **Call `render`, never `synthesize`**,
or that sentence comes out at the engine's own pace while every other sentence
is at the reader's.

**14. A widget cannot be taken out of a layout by re-parenting it.** The markup
bar moves between four hosts, and `setParent` alone leaves the old layout still
holding it: it reappears where it was the next time anything re-lays out.
`_place_markup_bar` calls `removeWidget` on every host it might be in first.
The matching trap is on the other side — a `QLayout` cannot be swapped while it
is installed, so `MarkupBar._rebuild_layout` hands the old one to a throwaway
`QWidget` to be destroyed with it rather than emptying it in place.

## Windows

Added on 12 September 2026 and **not yet run on a real Windows machine** — it
was written and reasoned through on Linux. Treat every claim below as designed
rather than observed.

`mimick/system.py` holds every platform difference; nothing else in the
codebase should learn what operating system it is on. Three things differ:

- **Folders.** `%APPDATA%\Mimick` for settings, `%LOCALAPPDATA%\Mimick\Cache`
  for voices — 60 MB downloads have no business in a roaming profile.
- **ffmpeg.** No system copy exists, so `install.ps1` downloads a static build
  into the cache folder and `ffmpeg_command()` looks there as well as on `PATH`.
- **Console windows.** Windows opens one for every child process of a windowed
  app. `decode_audio` runs *once per sentence* during playback, so every ffmpeg
  call passes `no_window_kwargs()` or a black box blinks on screen throughout
  the reading. **Any new subprocess must pass it too.**

**`install.ps1` avoids trap 10 differently from `install.sh`.** Instead of a
`PYTHONPATH` shim it writes a `.pth` file into the venv's site-packages naming
the project folder, which makes `python -m mimick` resolve from any working
directory. That is strictly better — it covers the Start Menu shortcut, the
terminal command and the "Open with" entry at once, with no wrapper — and
`install.sh` should probably adopt it, but the Linux launcher is tested and was
left alone. See the roadmap.

Two Windows traps worth knowing before debugging an install:

- **The Microsoft Store Python is a trap.** A zero-byte `python.exe` sits on
  `PATH` and opens the Store instead of running. The installer tries the `py`
  launcher first and ignores anything under `WindowsApps` for this reason.
- **`pythonw.exe`, not `python.exe`,** for the shortcut and the file
  association, or a console window sits behind Mimick the whole time it is open.

The PowerShell can at least be checked from Linux, which caught two real
problems. Download the PowerShell tarball, then:

```bash
pwsh -NoProfile -Command 'Invoke-ScriptAnalyzer -Path ./install.ps1 -Severity Error,Warning -ExcludeRule PSAvoidUsingWriteHost'
```

`[Parser]::ParseFile(...)` catches syntax errors, and much of the script's
logic — the version gate, the here-strings, the uninstaller's `PATH` surgery —
runs on Linux unchanged. Only the registry, `WScript.Shell` and the download
genuinely need Windows.

The dependencies are the one part that is not guesswork. Every requirement
resolves to a Windows binary wheel, with no compiler needed, on Python 3.10
through 3.14; 3.15 has no PySide6 yet. `piper-tts` 1.8 bundles `espeakbridge`
and its espeak-ng data inside the wheel, so offline voices need nothing from
the system. To re-check after a dependency bump:

```bash
.venv/bin/python -m pip install --dry-run --ignore-installed \
    --only-binary=:all: --platform win_amd64 --python-version 3.13 \
    --target /tmp/x -r requirements.txt
```

What is genuinely untested: the PowerShell itself beyond parsing and
PSScriptAnalyzer, the ffmpeg download, the Start Menu shortcut, the registry
entries, `asyncio.run` per sentence on a Proactor event loop in the Edge
engine, and **audio latency**. That last one is the real risk — word-sync
highlighting assumes the playhead matches what is audible, and if WASAPI buffers
more deeply than ALSA the highlight will lag the voice. Only an ear can tell,
and `sd.OutputStream` takes a latency hint if it turns out to.

The branch has been sent to one Windows user. The two things worth asking
anyone who runs it: **does the highlight keep up with the voice**, and **is
there a console window** behind the app or flashing between sentences. Neither
shows up in a check tool.

## State on disk

Paths below are Linux; on Windows `~/.config/mimick` is `%APPDATA%\Mimick` and
`~/.cache/mimick` is `%LOCALAPPDATA%\Mimick\Cache`. `MIMICK_CONFIG_DIR` and
`MIMICK_CACHE_DIR` override both on either platform.

- `~/.config/mimick/settings.json` — voice, speed, zoom, reading positions,
  per-document reading-order corrections, preview phrases.
- `~/.cache/mimick/piper/` — downloaded voices (~60 MB each).
- `~/.cache/mimick/piper-samples/` — preview clips (~90 KB each).
- `~/.cache/mimick/ffmpeg/` — Windows only; the copy `install.ps1` downloads.
- `~/.config/mimick/notes/` — annotated copies for documents whose own folder
  cannot be written to. Everything else gets its copy beside the original.

## Where it stands

Working and tested: reading with online and offline voices, word-sync
highlighting, speed to 5×, selection reading, highlights and margin notes saved
as PDF annotations, MP3 conversion with estimates and working cancellation,
layout analysis with a visible editable reading order, citation skipping, and
the reading cleanup — reference lists, masthead and declarations left out,
ligatures and stranded accents repaired — switchable in **Display** and
overridable for a single conversion in the Convert to MP3 window.

Fixed on the 12th, all found by using the app rather than by reading it: read
aloud produced no sound at all (trap 6), the applications-menu entry did not
start (trap 10), citations split across a sentence boundary were half-spoken
(trap 5), and the reference list was read out in full.

Later on the 12th, again all found by use: two-column pages were read across
rather than down (trap 12); citations naming several works, or with a comma
tight against the name, were spoken; a sentence mentioning a website was
dropped whole; `Ctrl`+`C` did nothing because it had never been written; note
titles were cut off rather than wrapped; the notes panel stacked every visible
page's cards into one list; there was no way to say "read from here" with
click-to-read switched off. Notes now save themselves to a companion file --
see trap 11 for the bug that found, and `annotations.save_as` for the shape a
safe save has to take.

**v0.2.0 is released.** Merged to `main`, tagged `v0.2.0`, and published at
<https://github.com/kathollander/mimick/releases/tag/v0.2.0> on 12 September
2026. `main` is now what anyone arriving at the repo gets, and it was checked
by exporting the tag to a clean folder and running it from there rather than
from the working tree. The release notes draft has been deleted, as planned.

**Done on 14–15 September, unreleased.** Four pieces of work on the reader
itself, all driven by using it rather than reading it:

- **Speed goes to 5×, and now means it.** The old 3× was a fiction — see trap
  13. Anything above an engine's honest ceiling is taken out of the rendered
  audio by ffmpeg, in `Engine.render`.
- **`Ctrl`+`Z` takes back a highlight or a note**, `Ctrl`+`Shift`+`Z` puts it
  back. Steps find their annotation by PDF object, then by exact word span,
  then by position — in that order, because undoing a deletion builds a new
  annotation, and because two highlights can overlap.
- **Highlight and Add note are one movable strip** (`mimick/ui/markup_bar.py`),
  which can sit in the notes panel, across the top or bottom, or loose over the
  page. This closed a real defect: Add note used to live inside the notes panel
  header, so switching the notes column off took away the only way to write one.
- **A highlight can be copied, read and removed directly.** `Ctrl`+`C` with
  nothing selected copies the picked-out highlight and its note; right-click on
  the page or on a card offers copy, read and delete; and a picked-out highlight
  carries a small × in the page margin that removes it in one click.

**What has not been checked by hand.** Everything above was tested offscreen,
with synthesized mouse events for the dragging and the ×. **Nobody has yet
dragged the markup bar with a real mouse, or listened to 5×.** The two
questions worth answering first: is the top of the speed range actually
comprehensible, and does the word highlight still keep up with the voice at
4–5×? Neither is visible to a check tool. There are five throwaway test
scripts for this work, none of them kept — `tools/` still holds only the two
check tools, and anything worth keeping should be written up there properly.

**Windows remains the single biggest untested surface in the project** — see
the Windows section above; nothing in it has met the platform it targets. The
release went out anyway, because the reading and notes fixes mattered to the
people already using it on Linux, and the README now says so plainly in the
heads-up box at the top rather than burying it in known issues.

Not done: see [`ROADMAP.md`](ROADMAP.md). The release checklist there is the
next thing to work through. The three most valuable tasks are **using the four
changes above on a real reading**, which is the only way the speed range and
the markup bar get judged; **trying it on more real documents** —
`tools/check_reading.py` makes that quick — and **hearing back from the first
Windows run**, which is the only part of the install path still unverified on
either platform.

Published at **<https://github.com/kathollander/mimick>** (public, AGPL-3.0),
pushed on 12 September 2026. Commit as `kathollander <kathoacct@pm.me>`, which
is what the initial LICENSE commit used.

Git-ignored in `Testing/`: `*.mp3` (conversions run to 26 MB and regenerate in
seconds), `* (notes).pdf` (the annotated copies Mimick now writes as you work),
and the *For the Learning of Mathematics* paper, which unlike the MDPI sample is
not openly licensed. The MDPI article is kept — CC BY 4.0, and the docs and both
check tools point at it.
