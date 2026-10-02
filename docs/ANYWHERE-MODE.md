# Anywhere mode — design notes

Reading selected text from **any** application with a hotkey, not just PDFs
open in Mimick. Planned, not started. Written 14 September 2026 from a design
conversation; supersedes the sketch at the foot of [`ROADMAP.md`](ROADMAP.md).

Nothing here is built. This exists so the next session does not re-derive the
findings, several of which took probing an actual machine to establish.

## The shape of it

Select text anywhere — a web page, an email, a chat window — press
`Ctrl`+`Alt`+`R`, and Mimick reads it aloud in a small window that highlights
each word as it speaks, exactly as the PDF view does.

**While Mimick is open, the hotkey works.** That is the whole v1: no tray
icon, no background daemon, no autostart. The main window hosts the listener.
Those three can come later and change nothing about the design.

## What gets reused

This is the good news, and the reason the feature is small. `Player`
(`mimick/player.py:62`) has never known what a PDF is. Its entire contract is:

```python
player.configure(sentences, engine, voice, rate)
player.play()
```

So everything below that line arrives free: all three engines
(`mimick/engines/`), the offline fallback, the prefetch queue, the transport,
speed 0.75×–3×, `speech.normalise`, `citations.strip`, and the sentence
splitter `document.chunk_into_sentences` (`mimick/document.py:159`) with its
never-cut-inside-a-bracket rule. Voice, engine and rate already persist in
`config.Settings`, so the feature inherits whatever was last chosen.

What does **not** carry over is the PDF half: layout analysis, the page view,
annotations. There is no page, so there is nothing there to want.

## The one new adapter

`Player` wants `Sentence` objects and `Sentence` wants `Word` objects with
rectangles on a page. Selected text has no rectangles — but nothing in the
playback path ever reads them. So the bridge is about thirty lines in a new
`mimick/selection.py`:

```
text → speech.normalise → Words with rect (0,0,0,0), page 0
     → chunk_into_sentences → list[Sentence]
```

That is the entire adapter. Build and test this first, before any hotkey or
window exists, via a plain `mimick --read-selection` run from a terminal.

## Getting the text

`wl-paste --primary`, falling back to `xclip -o -selection primary`.

**Verified on this machine:** both return the same text. Mutter bridges the
primary selection between Wayland and XWayland, so it does not matter whether
a browser runs natively or through XWayland — either reader sees the
selection. Snap confinement does not interfere, because the selection travels
through the compositor rather than the filesystem.

This was checked as a mechanism, not per-browser. Confirm Firefox, Brave,
Chromium and Edge individually once `--read-selection` runs; it is a
thirty-second check each and the assumption is load-bearing.

The unreliable cases are **not** browsers. Electron apps — Slack, Discord,
VS Code — are the usual offenders, along with some Java/Swing apps.

The primary selection persists, so pressing the hotkey without selecting
anything new re-reads the last selection. Treat that as a feature — press
again to hear a passage twice — but make it a decision rather than an
accident.

## The hotkey

Wayland forbids an application from grabbing a global key. It has to be
registered with the desktop instead: `gsettings` on GNOME, something different
on KDE and sway. That is GNOME-specific installer code, and there is no way
around it.

Registration and listening are separate. The binding is registered once; it
does nothing unless Mimick is running.

**Verified on this machine:** `Ctrl`+`Alt`+`R` is free — nothing in
`org.gnome.shell.keybindings`, `org.gnome.desktop.wm.keybindings` or
media-keys claims it.

Two traps:

- **GNOME's screen recorder is `Ctrl`+`Shift`+`Alt`+`R`** — one modifier away.
  A slip starts recording the screen.
- **A `custom0` binding already exists.** The installer must *append* to
  `custom-keybindings`, never overwrite it. Getting this wrong silently
  destroys a shortcut that is in use.

Because a keybinding spawns a fresh process on every press, and Python's cold
start is far too slow to feel instant, anything beyond v1 needs a resident
process and a thin client over a socket. That is the only real argument for
the tray app.

## The reading window

Mimick **cannot highlight text inside the browser.** It does not control the
browser. Instead: a small always-on-top Mimick window showing the captured
text, highlighting word by word off the same `align_marks` timings the page
view uses, scrolling to follow.

This window is also where voice, speed and click-to-read live — click a
sentence in it to read from there. The "widget with basic settings" and the
highlighting surface are one component, not two.

## Why there is no true overlay

Asked directly, and the answer is no — not on GNOME/Wayland. Two independent
blockers, both of which Wayland created deliberately:

**A window cannot position itself.** There is no global coordinate system for
clients. The protocol meant for exactly this, `wlr-layer-shell`, is a wlroots
protocol that **Mutter does not implement**; even `WindowStaysOnTop` is
ignored for ordinary Wayland clients. Running Mimick as an X11/XWayland client
is an escape hatch, but a fragile one.

**The selection carries no geometry.** This is the real blocker. The primary
selection hands over text and nothing else — no word positions, not even which
window it came from. The only sources of on-screen coordinates are:

- **AT-SPI.** Installed here, `pyatspi` imports, and it can report
  per-character extents. But accessibility is currently off
  (`toolkit-accessibility false`); enabling it makes Chromium build a full
  accessibility tree per page at real cost; D-Bus queries over a long page are
  slow; coordinates go stale the moment anything scrolls, which is precisely
  what happens while reading aloud; and screen coordinates are unreliable
  *specifically on Wayland*, for the same reason as the first blocker. This is
  a known sore point for Orca.
- **Screenshot and OCR.** A portal prompt per capture, to recover text already
  held perfectly. Not sane.

A browser extension gets all of this free — `range.getClientRects()` is exact,
instant and scroll-aware, because the browser already knows where every glyph
sits. The distinction worth remembering: **the extension's problem is plumbing
(native messaging, snap confinement) and the overlay's problem is that Wayland
deleted the capabilities it needs.** Plumbing can be ground through.

If in-page highlighting is ever wanted seriously, the extension is the route,
and it needs the same resident daemon as the tray — nothing built here is
wasted. Note that the browsers on this machine are all snaps, which is the
hard case for native messaging hosts; installing Brave or Firefox from an apt
repository instead would clear that.

## Where the settings go

**Mimick has no preferences dialog.** Settings live directly in the menu bar —
File, Display, Notes, Voice — and persist to `settings.json`. The only dialogs
are About, Notes appearance, Export and Voices. Any plan that assumes a tabbed
settings window is starting from a false premise.

So either a new **`Read anywhere`** menu in the menu bar, matching how
everything else works, or finally build a real Preferences dialog. The menu
ships with the feature; the dialog is its own task, and arguably overdue given
how crowded Display has become.

## Build order

1. **`mimick/selection.py`** — text to `Sentence` list.
2. **`mimick --read-selection`** — a plain terminal command, no window, no
   hotkey. Select text in each browser, run it, hear it. This proves the
   reading half and confirms the per-browser assumption above.
3. **The reading window** — highlighting, voice, speed, click-to-read.
4. **`Read anywhere` menu** and `gsettings` registration, appending safely.
5. *Optional, later:* tray icon; autostart via a `.desktop` file in
   `~/.config/autostart`, which is ten lines and touches nothing else.

Steps 1 and 2 are small and testable in isolation. Do not start at step 3.
