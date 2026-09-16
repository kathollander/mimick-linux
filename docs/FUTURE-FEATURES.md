# Future features

Things considered but not started, with enough of the reasoning kept that the
next session does not re-derive it. Smaller ideas live at the foot of
[`ROADMAP.md`](ROADMAP.md); this file is for the ones big enough to need a
decision before any code is written.

---

## Mimick in a browser

**Status: undecided, blocked on one test Kat is running.** Written 16 September
2026 from a research conversation. Nothing is built.

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

### The decision, and what decides it

Everything turns on **whether Piper's voices are good enough to carry the whole
app on their own**, including at 4–5× speed.

This is because the browser cannot reach Microsoft's neural voices the way
`edge-tts` does. `edge-tts` works by presenting itself as Microsoft's own Read
Aloud extension — an `Origin` header naming that extension, a matching
`User-Agent`, and a signed token. A web page cannot set those headers; the
browser writes `Origin` itself and refuses to let script touch it, which is the
entire reason the header exists. Getting around it needs a relay server, which
is the hosting we do not have and do not want.

There is a loophole: the Edge *browser* exposes those same voices through the
standard Web Speech API, on Windows and macOS alike. But taking it means
telling every user to switch browsers, and it costs real features — see
**If Piper is not enough** below. So the loophole is a fallback, not a plan.

**If Piper holds up, none of that matters.** One engine, every browser, nothing
sent to Microsoft, and the feature set stays nearly intact.

### The test

Kat is running this on the **current desktop app**, which is the right place —
it is the same Piper, the same models, and the same `Engine.render` speed path
the browser version would reuse. No browser work is needed to answer it.

What to listen for, in order of how much it decides:

1. **Is Piper comprehensible at 4× and 5×?** Above `Engine.max_native_rate` the
   speed comes from ffmpeg `atempo`, not the voice, so this is really a question
   about `atempo` on Piper audio rather than about Piper.
2. **Is it pleasant enough for a long reading?** Twenty minutes, not twenty
   seconds. Edge's voices set the bar and Piper has to be close enough that
   losing them is not a downgrade.
3. **Do the estimated word timings hold at speed?** Piper has no real word
   marks; `piper.py` estimates them from word length. Any drift between the
   highlight and the voice gets multiplied by the rate.
4. **How do several voices compare?** If only one or two are good enough, that
   is still a yes, but it changes what the voice picker offers.

A no on (1) or (2) means the browser port is not worth it on these terms, and
the effort goes back into the desktop app.

### Scope, decided up front

**Laptop and desktop only.** Tablets and phones are out of scope. Pyodide plus
MuPDF plus a loaded voice model plus rendered pages is a heavy tab, and
designing for a constrained device would compromise the one that matters. We
are allowed limitations.

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

### Build order, if it goes ahead

1. **Spike.** Load `pymupdf` in Pyodide in a tab, open the MDPI sample, run
   `layout.analyse` unmodified, print the regions. If that reads sensibly, the
   foundation is proven for a couple of hours' work rather than a couple of
   weeks'.
2. **Piper in a worker**, one sentence, audible, at 1× and at 5×.
3. **Word timing plus a check tool**, before any interface exists.
4. **The reader** — page rendering, scrolling, the highlight.
5. **Annotations**, then MP3 export.

Steps 1–3 answer every open question. Step 4 is where the months are.

### If Piper is not enough

The fallback is the Edge-browser route: Microsoft's cloud voices through the
Web Speech API, on Windows and macOS both. It is not a free win, and the costs
are what make it the fallback rather than the plan:

- **No MP3 export.** The Web Speech API plays audio and gives no access to it.
  It cannot be recorded, saved or processed. `export.py` and everything around
  it exists only on the Piper path.
- **No speed past the engine's clamp.** This is trap 13 again and worse: the
  `atempo` fix needs the audio, and there is none. 5× is Piper-only.
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
