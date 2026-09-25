# Mimick v0.2.0 — better reading, safer notes, and a Windows installer

The big ones: Mimick reads two-column papers properly now, and **it never
writes into your PDF any more** — your highlights and notes save themselves to
a copy beside it, on their own, as you work.

There's also a Windows installer. Please read the warning about it below before
you trust it.

## Your notes now save themselves, to a copy

Mimick no longer touches the PDF you opened. A second or so after each change,
your highlights and notes go to a companion file beside it:

```
Papers/
  Reading for Tuesday.pdf          ← never touched
  Reading for Tuesday (notes).pdf  ← this is where your notes go
```

Open the original again and Mimick opens that copy for you, so your notes are
waiting. The status bar in the corner tells you each time it saves, with the
time. `Ctrl`+`S` still saves immediately if you'd rather not wait, and **Save
As** still puts a copy wherever you like. Closing the window finishes saving
before it shuts.

If the document lives somewhere you can't write to, the copy goes in Mimick's
own notes folder instead, and it says so rather than failing quietly.

The copy is an ordinary PDF — the notes in it are real PDF annotations, so
Okular, Acrobat and Zotero read them.

## Reading

- **Two-column pages are read down each column**, not across the page. Mimick
  used to leave the left column mid-sentence, jump to the right, and come back
  to the rest of the section a paragraph later.
- **Citations naming several works are skipped**, so "(Egan, 2002; Walkerdine,
  1984)" is no longer read out. So are ones with the comma tight against the
  name, reprint dates like "(2008/1972)", and bracketed dates with a page,
  "(1992, p. 33)".
- **A sentence is no longer cut in half inside a citation**, which used to
  leave the voice reading a list of surnames.
- **A sentence that mentions a website is read.** Any sentence containing a web
  address used to be thrown away whole; now only the ones that are mostly link
  — reference lines, bare DOIs — are skipped.

## Notes and the window

- **`Ctrl`+`C` copies** the selected text. It never did before. Words broken
  across a line are put back together, so you get "cannot", not "can- not".
- **The notes panel is its own column.** It shows the page you're on, stacked
  from the top in the order the passages appear, and scrolls on its own — the
  wheel over the notes moves the notes, the wheel over the page moves the page.
  Before, every visible page's notes piled into one list and shoved each other
  around.
- **Note titles wrap** instead of being cut off at the edge of the card.
- **Right-click anywhere** for *Start reading from here*. With click-to-read
  switched off there was no way to say "carry on from this sentence" at all.
  The menu also offers Copy, Highlight and Read the selection.

## Windows: nobody has run this yet

There's a Windows installer, and **it has never been run on Windows.** It was
written and reasoned through on a Linux machine. That sounds daft, and it
partly is, but a fair amount could be checked properly: the installer is
linted, its logic was run, and every component was confirmed to have a
ready-made Windows build for Python 3.10 through 3.14, so nothing has to be
compiled on your machine.

What hasn't been tested is Windows itself. If you're installing this you may
genuinely be the first, and **the most likely thing to be subtly wrong is the
word highlighting drifting behind the voice** — Windows handles audio
differently and that timing has never been heard on it. If the highlight lags,
or a black console window appears behind Mimick, that's a real bug and worth
telling me about.

Linux is the version that gets used daily.

## Installing

You need Python 3.10 or newer. Either installer is safe to run again.

**Linux.**

```
./install.sh
```

**Windows.** Right-click the folder → **Open in Terminal**, then:

```
powershell -ExecutionPolicy Bypass -File install.ps1
```

(The `-ExecutionPolicy Bypass` is because Windows blocks downloaded scripts by
default. It applies to that one command.) Mimick lands in your Start Menu.

Settings, voices and ffmpeg go in the proper Windows places (`%APPDATA%\Mimick`
and `%LOCALAPPDATA%\Mimick`), Mimick appears under **Open with** for PDFs
without stealing the default, and there's an uninstaller (`uninstall.ps1`).

## Also fixed

**Save a copy could overwrite the document you had open.** If you picked the
original file's own name in the Save a copy box, Mimick would write over the
PDF it was still reading and truncate it. There was a guard, but it compared
filenames as text, so anything spelled slightly differently slipped past — and
on Windows, where `Paper.pdf` and `paper.pdf` are the same file, it'd be easy
to hit by accident.

Saving is now done by writing the whole PDF to a temporary file, checking it
opens with the pages and highlights it should have, and only then moving it
into place. An interrupted save leaves the previous file exactly as it was.

## Found a bug?

Very likely! Open an issue. What helps: what you did in order, the PDF if you
can share it, any error text, and whether you're on Windows or Linux.
