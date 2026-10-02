# Future features

Things considered but not started, with enough of the reasoning kept that the
next session does not re-derive it. Smaller ideas live at the foot of
[`ROADMAP.md`](ROADMAP.md); this file is for the ones big enough to need a
decision before any code is written.

---

## Mimick in a browser

**Status: decided, and it goes ahead.** Written 16 September 2026 from a
research conversation; the decision below was taken the same day once the
voices had been listened to. Nothing is built yet.

### The idea

Mimick as a static web page instead of an installed desktop app. You open a
URL, it runs entirely in your own browser, and your PDF never leaves your
machine. Photopea's shape.

This solves distribution outright — one link, every operating system, nothing
to install, no Python, no Gatekeeper warning on macOS, no SmartScreen warning
on Windows, and no more per-platform install scripts to maintain.

**No hosting is needed.** GitHub Pages serves a static site from the existing
public repo for free. The AGPL obligation that comes with serving the software
over a network is satisfied by that repo being public, provided the page links
to its own source.

### The decision, and what it turned on

Everything turned on **whether Piper's voices are good enough to carry the whole
app on their own**. They are, and the browser port goes ahead on the Piper-only
plan: one engine, every browser, nothing sent to Microsoft, English only to
begin with.

This mattered because the browser cannot reach Microsoft's neural voices the
way `edge-tts` does. `edge-tts` works by presenting itself as Microsoft's own
Read Aloud extension — an `Origin` header naming that extension, a matching
`User-Agent`, and a signed token. A web page cannot set those headers; the
browser writes `Origin` itself and refuses to let script touch it, which is the
entire reason the header exists. Getting around it needs a relay server, which
is the hosting we do not have and do not want. The Edge-browser loophole — the
same voices through the Web Speech API — is written up under **If Piper is not
enough** and is now dead unless something changes, because it costs MP3 export
and the speed range both.

### The voices, and what quality actually means

Eight English voices carry the browser version, chosen by listening rather than
from a table. They are in `piper.RECOMMENDED`, fastest first, each with a note
on how it reads aloud, and `piper.SUGGESTED` is the first of them.

| Key | Synthesis speed | Speakers in the file |
| --- | --- | --- |
| `en_US-lessac-low` | ~18× real time | 1 |
| `en_US-kathleen-low` | ~18× | 1 |
| `en_GB-southern_english_female-low` | ~18× | 1 |
| `en_US-joe-medium` | ~13× | 1 |
| `en_US-norman-medium` | ~13× | 1 |
| `en_US-kusal-medium` | ~13× | 1 |
| `en_GB-vctk-medium` | ~13× | **109** |
| `en_US-libritts_r-medium` | ~13× | **904** |

Speeds are one sentence on one machine, native Piper, so they are a ratio to
compare by and not a promise.

**Quality is a sample rate, not a file size.** Every one of these models is
about 63 MB — `en_US-lessac-low` and `en_US-hfc_female-medium` are the same
63,201,294 bytes to the byte. A *low* voice is trained at 16 kHz and a *medium*
at 22.05 kHz, so what a lower quality buys is synthesis speed, which is the
only budget a browser is actually short of. The comment in `piper.py` used to
say higher quality meant a larger download; it was wrong and has been fixed.
Four of the eight being low is therefore a speed decision, not a compromise.

**Two of the files hold more than one voice.** `en_GB-vctk-medium` contains 109
speakers and `en_US-libritts_r-medium` contains 904, chosen by passing
`speaker_id` to `SynthesisConfig`. Nothing in Mimick passes one today, so both
speak as speaker 0 — which is the voice that was listened to and the voice the
published sample clip plays. Every speaker in a file costs the same to
synthesise and needs no further download, so one 78 MB fetch could offer
hundreds of voices in the browser. Worth doing *after* the reader works, not
before: the picker becomes a different and harder piece of interface, and a
nickname would have to store a speaker id alongside the key.

**Pre-installing all eight is not on.** They come to 535 MB. What ships in the
page is the eight *sample clips* — about 90 KB each, 720 KB in total — so every
voice can be auditioned the moment the page loads. The model itself is fetched
on first use and kept in IndexedDB, so it costs one download per browser rather
than one per visit. `en_US-lessac-low` is the one fetched without being asked
for, being the quickest of them.

### Speed, and the cap

Native Piper here runs 13–18× real time. ONNX Runtime Web with SIMD and threads
typically lands three to five times slower than native, so expect roughly
**3–6× real time in a tab**, and less on a laptop that is not this one.

Playback has to stay under that or the prefetch queue starves and the voice
stops between sentences. **The browser version caps at 4×**, not the desktop's
5×: four is as fast as most people find useful, and it leaves the queue some
headroom on the slow end of that range rather than none. The low-quality voices
are the ones that make the top of the range comfortable, which is the second
reason four of the eight are low.

This is also what makes roadblock 3 matter — without `SharedArrayBuffer` there
are no threads, and without threads the estimate sits at the bottom of that
band.

### Where the code lives, and which way it flows

**A second repository, `mimick-web`.** Not a branch of `mimick` and not a folder
inside it. A branch would mean one issue list, one release list and one front
page shared between two different programs, and you would have to remember
which one you were looking at every time. Separate repositories give the web
version its own front page, its own issues and its own Pages site, and leave
`mimick` exactly the thing it is today.

**Work happens on the Linux version first and is ported across afterwards.**
That is the rule that keeps the two from drifting: `layout.py`, `citations.py`
and `speech.py` have one home, this one, and the web copy is downstream of it.
Nothing is fixed in `mimick-web` and back-ported. The cost to accept is that a
fix lands in the browser version later than in the desktop one, which is the
right way round — the desktop app is where the reading gets judged.

### Scope, decided up front

**Laptop and desktop only.** Tablets and phones are out of scope. Pyodide plus
MuPDF plus a loaded voice model plus rendered pages is a heavy tab, and
designing for a constrained device would compromise the one that matters. We
are allowed limitations.

**English only to begin with.** Piper publishes voices in some fifty languages
and the catalogue code already handles them, but the eight that ship have been
listened to and the rest have not. Another language is a matter of adding keys
to `piper.RECOMMENDED` once somebody who reads that language has judged them —
no new code, and no reason to guess now.

**Playback caps at 4×**, where the desktop goes to 5×. See **Speed, and the
cap**.

### What survives the move

| Layer | Fate |
| --- | --- |
| `layout.py`, `citations.py`, `speech.py` (~700 lines) | **Untouched.** Pure stdlib, no PyMuPDF. The hardest-won logic in the project ports as-is. |
| `document.py`, `annotations.py` | **Port.** Both need PyMuPDF, which ships an official WebAssembly wheel as of 1.28 (`pymupdf-1.28.2-cp313-abi3-pyemscripten_2025_0_wasm32.whl` on PyPI). This was the make-or-break question and the answer is yes. |
| `player.py` | **Rewrite.** WebAudio replaces `sounddevice`. The prefetch queue and transport map over; the word-timing alignment needs care — see the roadblocks. |
| `export.py` | **Rewrite.** ffmpeg.wasm or lamejs. Survives only because Piper hands back real audio. |
| `engines/piper.py` | **Replace.** espeak-ng compiled to WASM for phonemisation, ONNX Runtime Web for inference, ~60 MB per voice. At least four independent projects already do this, so it is a known quantity rather than research. |
| `engines/edge.py` | **Gone**, on the Piper-only plan. |
| `mimick/ui/*` (~5,700 lines) | **Rewritten in HTML and JS.** The reader, notes panel, markup bar, caret and every dialog. This is the bulk of the work, not the PDF plumbing. |

Notes become *download a copy* rather than a companion file written beside the
original — a browser tab has no "beside". Accepted; most programs work that way.

### Roadblocks, worst first

**1. The interface is the project.** ~5,700 lines of Qt rebuilt from nothing.
None of the traps in the handoff help here and a new set replaces them. Every
estimate should start from this number, not from the PDF work.

**2. Word timing is where it will break silently.** Trap 6's lesson applies
directly: a dead alignment path is quiet, not loud, and in a browser there is
no terminal for the traceback to reach. Whatever replaces `align_marks` needs a
check tool written alongside it, not after.

**3. Threads, and the two headers GitHub Pages cannot set.** MuPDF parsing and
Piper inference must run in Web Workers or they freeze the page mid-read. ONNX
Runtime then wants several threads for decent speed, which needs
`SharedArrayBuffer`, which needs COOP and COEP response headers that Pages will
not send. The standard workaround is a service worker that injects them
(`coi-serviceworker`) — widely used and it works, but it is a moving part
underneath the performance story.

**4. Memory.** `page_view`'s "paint only the visible band" discipline (trap 4)
stops being a Qt coordinate problem and becomes a memory requirement.

**5. Safari needs a real click before any audio.** "Click a sentence to read
from here" already fits; anything that resumes automatically on load will not.

### Security and privacy

Two things genuinely improve. A static site means documents are opened by the
reader's own browser and never uploaded. And **running MuPDF as WebAssembly is
safer than what we ship today** — a malicious PDF that could corrupt memory in
native MuPDF is contained by the browser sandbox.

Three things need doing deliberately:

- **Vendor every dependency into the repo.** Loading Pyodide, ONNX Runtime or
  anything else from a public CDN means whoever controls that CDN can run code
  in a tab that has the reader's documents open. Serve them from Pages, and pin
  subresource integrity hashes on anything that must come from elsewhere. Do
  this from the first commit, not as a hardening pass.
- **Verify the voice model after download.** A 60 MB fetch from Hugging Face is
  a third party we are trusting and a URL that can move. Check a hash.
- **Offer to forget a document.** Anything cached in IndexedDB — reading
  position, annotations, the PDF itself — sits in the browser profile. On a
  shared or library machine that is someone's annotated reading left for the
  next person. A browser profile is a weaker boundary than a desktop account.

On the Piper-only plan the privacy story is simply "nothing leaves this
machine", which is stronger than the desktop app's, and worth saying plainly in
the interface.

### Shortcuts: one set for both versions

**Decided 16 September 2026.** The desktop app and the browser version share
one set of keyboard shortcuts, so nobody has to relearn them moving between
the two. A browser acts on some keys before the page ever hears them, so those
keys are out for both versions. `tools/check_shortcuts.py` fails if any of them
is bound.

**Changed in the desktop app to fit:**

| Was | Now | Does | Why it moved |
| --- | --- | --- | --- |
| `Ctrl`+`T` | `Ctrl`+`Shift`+`H` | Show or hide the highlight buttons | The browser opens a new tab |
| `Ctrl`+`Shift`+`N` | `Ctrl`+`B` | Show or hide the notes panel | The browser opens an incognito window |

**Kept, though the browser uses them too.** A page can take these over, and
Google Docs does the same with `Ctrl`+`H`, `Ctrl`+`J`, `Ctrl`+`R`, `Ctrl`+`B`,
`Ctrl`+`O` and `Ctrl`+`S`: `Ctrl`+`H`, `Ctrl`+`J`, `Ctrl`+`K`, `Ctrl`+`M`,
`Ctrl`+`R`, `Ctrl`+`O`, `Ctrl`+`S`, `Ctrl`+`0`, `Ctrl`+`+`, `Ctrl`+`-`. They only
work while the page has the keyboard. `Ctrl`+`R` is the risky one: pressed while
the address bar has focus it reloads the tab, so the browser version has to
keep the reader's place and notes somewhere that survives a reload.

**Never to be used, in either version:** `Ctrl`+`N`, `Ctrl`+`Shift`+`N`,
`Ctrl`+`T`, `Ctrl`+`Shift`+`T`, `Ctrl`+`W`, `Ctrl`+`Shift`+`W`, `Ctrl`+`Tab`,
`Ctrl`+`Shift`+`Tab`, `Ctrl`+`Page Up` and `Page Down`, `Ctrl`+`Shift`+`Q`, `F11`,
and the developer-tools keys (`F12`, `Ctrl`+`Shift`+`I`, `J`, `C`).

**Desktop only:** `Ctrl`+`Q` to quit. A tab has nothing to quit.

**Not settled: the Mac, which only the browser version reaches.** A Mac user
expects `Cmd` wherever Linux and Windows use `Ctrl`, and macOS keeps three of
ours before the browser sees them: `Cmd`+`H` hides the app, `Cmd`+`M` minimises
the window, and `Ctrl`+`↑`/`↓`/`←`/`→` switch desktops. So on a Mac, Highlight,
Add note, turning the page and moving by sentence all need other keys. Decide
this when the browser version's keys are built, not before.

### Build order

0. **Make the second repository.** `mimick-web`, public, AGPL-3.0, with a README
   that says what it is and links back to `mimick` — the link is what satisfies
   the AGPL for software served over a network. Empty but for that is fine; it
   exists so that none of the work below lands in the wrong place by default.
1. **Spike.** Load `pymupdf` in Pyodide in a tab, open the MDPI sample, run
   `layout.analyse` unmodified, print the regions. If that reads sensibly, the
   foundation is proven for a couple of hours' work rather than a couple of
   weeks'.
2. **Piper in a worker**, one sentence, audible, at 1× and at 4×. Print the
   ratio of synthesis time to audio length while it runs: that number, on a
   normal laptop rather than this one, is what says whether 4× holds. Do this
   with and without the `coi-serviceworker` shim, because the gap between those
   two *is* roadblock 3, measured instead of estimated.
3. **Word timing plus a check tool**, before any interface exists.
4. **The reader** — page rendering, scrolling, the highlight.
5. **Annotations**, then MP3 export.

Steps 1–3 answer every open question, and step 2 is the one that can still say
no. Step 4 is where the months are.

Not in this list, and deliberately after it: **the multi-speaker picker**, which
turns two of the eight into hundreds of voices for no extra download. It is a
reward for having a working reader, not a way to get one.

### If Piper is not enough

The fallback is the Edge-browser route: Microsoft's cloud voices through the
Web Speech API, on Windows and macOS both. It is not a free win, and the costs
are what make it the fallback rather than the plan:

- **No MP3 export.** The Web Speech API plays audio and gives no access to it.
  It cannot be recorded, saved or processed. `export.py` and everything around
  it exists only on the Piper path.
- **No speed past the engine's clamp.** This is trap 13 again and worse: the
  `atempo` fix needs the audio, and there is none. The 4× range is
  Piper-only.
- **"Best in Edge"** as an instruction to users, with Piper still needed
  underneath for everyone else — so the work is not avoided, only deferred.
- **Document text goes to Microsoft**, sentence by sentence, to Azure. The
  desktop app already does this through `edge-tts`, but in a browser it belongs
  next to the voice picker rather than in a README. People read medical, legal
  and ethics-bound material with this.
- **An undocumented surface.** Microsoft promises nobody that these voices stay
  visible to the Web Speech API.

Two findings worth keeping either way:

- **Edge on macOS does expose the natural voices**, contrary to the common
  impression, but with a bug: only 18 appear until one utterance has been
  spoken through the Web Speech API, after which 250+ appear. Speak a short
  utterance at startup, then re-read `getVoices()`.
- **What is Windows-only is the *offline* natural voices.** Windows 11 installs
  them on-device through Narrator's settings and Edge can then use them with no
  network. macOS has no equivalent, so Edge there is always streaming from
  Azure — which is why Read Aloud feels unreliable on a Mac, and why a VPN, DNS
  filter or privacy extension kills it outright. Irrelevant to us: a browser
  can only reach the cloud voices anyway.

### The open question nobody has answered

Whether Edge's online natural voices fire **per-word** boundary events through
the Web Speech API. Chromium fires per word, Safari per sentence, some voice
families not at all — and Chrome Desktop's own voices return none. Edge is
Chromium with a different voice engine, so none of that transfers. It is not
documented anywhere findable, including in a GitHub issue from this year asking
exactly this, still open.

Only relevant on the fallback path, and answerable with a throwaway page that
lists every voice, works around the 18-voice bug, speaks a sentence and prints
each boundary event with its offset — sent to a Mac user and a Windows user the
way the `windows` branch was. Not worth building unless Piper fails.

### Sources

- [PyMuPDF on PyPI](https://pypi.org/project/PyMuPDF/) — the WebAssembly wheel
- [Readium — SpeechSynthesis in browsers and OSes](https://readium.org/speech/docs/WebSpeech.html)
- [MDN — SpeechSynthesisUtterance: boundary event](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisUtterance/boundary_event)
- [piper-tts-web](https://github.com/Poket-Jony/piper-tts-web) and
  [piper-tts-web-demo](https://github.com/clowerweb/piper-tts-web-demo)
- [reader#4 — Web Speech boundary reliability](https://github.com/HyperToken9/reader/issues/4)
