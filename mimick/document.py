"""Turn a PDF into a stream of sentences that each know where they sit on the page.

The unit of playback is a Sentence. Every sentence carries the words it is made
of, and every word carries its rectangle on the page, which is what lets the UI
highlight along with the voice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from . import citations, layout, speech

# A sentence ends at . ! ? but not after a common abbreviation or an initial.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "etc", "eg",
    "ie", "cf", "al", "ed", "eds", "vol", "no", "pp", "fig", "ch", "trans",
    "repr", "rev", "approx", "dept", "univ", "inc", "ltd", "co",
}
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*$")
_WORD_CHARS = re.compile(r"[^\w']+", re.UNICODE)

# Long sentences are split so playback starts sooner and stays responsive.
MAX_SENTENCE_CHARS = 320
_SOFT_BREAK = re.compile(r"[;:,][\"')\]]*$")
# A sentence is never cut while a bracket is open, because a citation is full of
# the punctuation the splitter breaks on: "(Moreau, Mendick & Epstein, 2010,
# p. 10)" was cut after "Epstein," and neither half then looked like a citation,
# so the voice read the names out. The ceiling is there so one stray unclosed
# bracket cannot swallow a whole page into a single sentence.
_OPENS, _CLOSES = "([{", ")]}"
MAX_HELD_OPEN_CHARS = MAX_SENTENCE_CHARS * 2


@dataclass
class Word:
    """A single word and the rectangle it occupies on its page."""

    text: str
    rect: tuple[float, float, float, float]
    page: int
    index: int = -1            # position in the document's flat word list
    sentence: int = -1         # which sentence this word belongs to
    readable: bool = True      # part of the body text, rather than furniture
    region: int = -1           # which layout region it came from
    joins_next: bool = False   # hyphenated across a line break
    spoken: bool = True        # read aloud, or passed over as a citation

    @property
    def key(self) -> str:
        """Normalised form used to line words up with the voice's timings."""
        return _WORD_CHARS.sub("", self.text).lower()


@dataclass
class Sentence:
    """A run of words spoken as one unit."""

    index: int
    page: int
    words: list[Word] = field(default_factory=list)
    strip_citations: bool = False

    @property
    def text(self) -> str:
        """The words as the voice should say them.

        A word hyphenated across a line break is rejoined, so "creat- ing"
        is spoken as "creating" rather than as two syllables.
        """
        parts: list[str] = []
        for word in self.words:
            if not word.spoken:
                continue
            if word.joins_next and word.text.endswith("-"):
                parts.append(word.text[:-1])
            else:
                parts.append(word.text + " ")
        assembled = "".join(parts).strip()
        if self.strip_citations:
            # A second pass over the finished text, because a citation with a
            # full stop stuck to it -- "[53]." -- is not a whole word.
            assembled = citations.strip(assembled)
        return assembled

    def rects_for(self, first: int, last: int) -> list[tuple[float, float, float, float]]:
        """Merge the rectangles of words[first:last+1] into per-line boxes."""
        chosen = self.words[max(first, 0) : last + 1]
        return _merge_rects([word.rect for word in chosen])


def _merge_rects(rects: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    """Join rectangles that share a text line, so highlights look continuous."""
    if not rects:
        return []
    merged: list[list[float]] = []
    for x0, y0, x1, y1 in rects:
        placed = False
        for box in merged:
            # Same line if the vertical centres overlap substantially.
            overlap = min(y1, box[3]) - max(y0, box[1])
            if overlap > 0.5 * min(y1 - y0, box[3] - box[1]):
                box[0], box[1] = min(box[0], x0), min(box[1], y0)
                box[2], box[3] = max(box[2], x1), max(box[3], y1)
                placed = True
                break
        if not placed:
            merged.append([x0, y0, x1, y1])
    return [tuple(box) for box in merged]


# Runs that are not language: web addresses, DOIs, bare page numbers, the
# fragments tables and figure axes leave behind. This catches them wherever they
# appear, whatever the layout analysis made of the region.
_WEB = re.compile(r"https?://|www\.|doi\.org|doi:\s*10\.", re.IGNORECASE)
# The address itself, so it can be taken out and what is left weighed up.
_ADDRESS = re.compile(
    r"(?:https?://|www\.)\S+|\bdoi:\s*10\.\S+|\bdoi\.org/\S+", re.IGNORECASE)
_LONG_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)

# A run carrying a web address is dropped only when the address is most of what
# it says. A sentence that happens to mention a site -- "Documentaries of this
# approach can be found at www.example.org, on such topics as..." -- is an
# ordinary sentence and was being thrown away whole; a reference-list line or a
# bare "Available online: https://... (accessed 3 May 2022)" is not.
LINK_SHARE = 0.35          # of the characters
LINK_MIN_WORDS = 5         # real words left once the address is removed


def is_readable_run(text: str, clean: bool = True) -> bool:
    """Whether a run of words is worth speaking aloud."""
    flat = " ".join(text.split())
    if not flat:
        return False
    if _WEB.search(flat) and _is_mostly_link(flat):
        return False
    if clean and speech.is_front_matter(flat):
        return False
    # Needs at least one real word; "11 of 12" and "(3.4)" have none.
    return bool(_LONG_WORD.search(flat))


def _is_mostly_link(flat: str) -> bool:
    """Whether a run is a link with trimmings, rather than a sentence with a link."""
    without = _ADDRESS.sub(" ", flat)
    removed = len(flat) - len(without.replace("  ", " "))
    if removed <= 0:
        # _WEB matched something _ADDRESS could not carve out -- a bare "doi.org"
        # with no path, say. Judge it on what is there, as before.
        return len(_LONG_WORD.findall(flat)) < LINK_MIN_WORDS
    return (removed / len(flat) >= LINK_SHARE
            or len(_LONG_WORD.findall(without)) < LINK_MIN_WORDS)


def chunk_into_sentences(words: list["Word"], clean: bool = True) -> list[list["Word"]]:
    """Cut a run of words into sentence-sized pieces."""
    chunks: list[list[Word]] = []
    pending: list[Word] = []
    depth = 0
    for word in words:
        pending.append(word)
        depth = max(0, depth + sum(c in _OPENS for c in word.text)
                    - sum(c in _CLOSES for c in word.text))
        length = len(" ".join(w.text for w in pending))
        if depth and length <= MAX_HELD_OPEN_CHARS:
            continue
        if _ends_sentence(word.text):
            chunks.append(pending)
            pending = []
            depth = 0
        elif length > MAX_SENTENCE_CHARS and _SOFT_BREAK.search(word.text):
            chunks.append(pending)
            pending = []
            depth = 0
    if pending:
        chunks.append(pending)
    return [
        chunk for chunk in chunks
        if any(w.key for w in chunk)
        and is_readable_run(" ".join(w.text for w in chunk), clean)
    ]


def _ends_sentence(token: str) -> bool:
    if not _SENTENCE_END.search(token):
        return False
    # Leading punctuation has to come off too, or "(p." is not recognised as
    # the abbreviation "p" and a citation gets cut in half -- which leaves the
    # voice saying "(p." and loses the page number into the next sentence.
    stem = token.strip("([{\u201c\u2018\"'").rstrip(".!?\"')]}\u201d\u2019").lower()
    if stem in _ABBREVIATIONS:
        return False
    # A single letter before a period is almost always an initial, as in "J. Smith".
    return not (len(stem) == 1 and stem.isalpha())


class Document:
    """A PDF opened for reading aloud."""

    def __init__(self, path: Path, skip_citations: bool = True,
                 clean_text: bool = True) -> None:
        self.path = Path(path)
        self.skip_citations = skip_citations
        # Tidying extracted text for the voice: ligatures, stranded diacritics,
        # masthead and declarations, and the reference list. One switch, because
        # it is one idea -- read the document, not the paperwork around it.
        self.clean_text = clean_text
        # Read into memory rather than leaving MuPDF holding the file open.
        # Notes are saved by writing a whole new PDF and moving it into place,
        # and that move has to be safe even when the file being replaced is the
        # one this document came from -- which it is, every time you reopen a
        # document you have already annotated.
        self.doc = pymupdf.open(stream=self.path.read_bytes(), filetype="pdf")
        self.sentences: list[Sentence] = []
        self.words: list[Word] = []                 # every word, in reading order
        self.page_words: dict[int, list[Word]] = {}
        # What each page is made of, and which parts are worth reading aloud.
        self.regions: dict[int, list] = layout.analyse(self, skip_references=clean_text)
        self._build_sentences()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self.doc.close()

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    @property
    def title(self) -> str:
        meta = (self.doc.metadata or {}).get("title") or ""
        return meta.strip() or self.path.stem

    # -- text --------------------------------------------------------------

    def _build_sentences(self) -> None:
        """Collect words region by region, then cut the readable run into sentences.

        Words are ordered by the regions the layout analysis found, so a journal
        sidebar no longer interleaves line by line with the article, and running
        headers are marked unreadable rather than spoken on every page.
        """
        for page_number in range(self.doc.page_count):
            page = self.doc.load_page(page_number)
            # sort=True gives words in reading order rather than PDF draw order.
            raw = []
            for x0, y0, x1, y1, text, *_ in page.get_text("words", sort=True):
                text = text.strip()
                if self.clean_text:
                    # Done per word, before anything else looks at the text, so
                    # the rest of the pipeline -- and Word.key, which lines the
                    # highlight up with the voice -- never sees a ligature.
                    # A word is never dropped, only rewritten: annotations store
                    # first_word/last_word, so the word list has to be the same
                    # length whichever way this setting is set.
                    text = speech.normalise(text).strip() or text
                if text:
                    raw.append((x0, y0, x1, y1, text))

            regions = self.regions.get(page_number) or []
            on_page: list[Word] = []
            claimed = set()
            for number, region in enumerate(regions):
                for position, (x0, y0, x1, y1, text) in enumerate(raw):
                    if position in claimed:
                        continue
                    if not region.contains((x0 + x1) / 2, (y0 + y1) / 2, pad=2.0):
                        continue
                    claimed.add(position)
                    word = Word(text, (x0, y0, x1, y1), page_number,
                                index=len(self.words), readable=region.reads,
                                region=(page_number, number))
                    self.words.append(word)
                    on_page.append(word)

            # Anything the analysis missed still belongs to the document.
            for position, (x0, y0, x1, y1, text) in enumerate(raw):
                if position in claimed:
                    continue
                word = Word(text, (x0, y0, x1, y1), page_number, index=len(self.words))
                self.words.append(word)
                on_page.append(word)

            self.page_words[page_number] = on_page

        self._mark_hyphenation()

        # Sentences come only from readable runs. A run also ends at a region
        # boundary, so an affiliation block cannot run into an abstract -- with
        # one exception: a paragraph carrying on to the next page.
        run: list[Word] = []
        previous: Word | None = None
        for word in self.words:
            if not word.readable:
                self._emit_run(run)
                run, previous = [], None
                continue
            if previous is not None and word.region != previous.region:
                # A region that stops mid-sentence is being continued by the
                # next one: the foot of a column carrying into the head of the
                # one beside it, or into the next page. Breaking the run there
                # splits the sentence and the voice pauses in the middle of it.
                # Within a page the next region also has to *start* mid
                # sentence, or a heading -- which ends without punctuation too
                # -- is glued onto the paragraph underneath it.
                carries_on = not _ends_sentence(previous.text) and (
                    word.page != previous.page or word.text[:1].islower()
                )
                if not carries_on:
                    self._emit_run(run)
                    run = []
            run.append(word)
            previous = word
        self._emit_run(run)

    def _mark_hyphenation(self) -> None:
        """Flag words broken by a hyphen at the end of a line."""
        for word, following in zip(self.words, self.words[1:]):
            if not word.text.endswith("-") or len(word.text) < 2:
                continue
            if word.region != following.region:
                continue
            # The next word has to sit on a later line for this to be a break.
            if following.rect[1] > word.rect[1] + 1.0 and following.text[:1].islower():
                word.joins_next = True

    def _emit_run(self, run: list[Word]) -> None:
        # A labelled block -- "Funding: ...", an address ending in an email --
        # is boilerplate as a whole, and its later sentences do not carry the
        # label that gives it away, so the run is judged before it is cut up.
        if self.clean_text and run and speech.is_front_matter(
                " ".join(word.text for word in run)):
            return
        for chunk in chunk_into_sentences(run, self.clean_text):
            if self.skip_citations:
                citations.mark_words(chunk)
            sentence = Sentence(index=len(self.sentences), page=chunk[0].page,
                                words=chunk, strip_citations=self.skip_citations)
            # A chunk that was nothing but a citation has nothing left to say.
            if not is_readable_run(sentence.text, self.clean_text):
                for word in chunk:
                    word.spoken = True
                continue
            for word in chunk:
                word.sentence = sentence.index
            self.sentences.append(sentence)

    def set_skip_citations(self, skip: bool) -> None:
        if skip == self.skip_citations:
            return
        self.skip_citations = skip
        self.rebuild()

    def set_clean_text(self, clean: bool) -> None:
        """Turn the cleanup on or off, for live reading and conversion alike.

        Unlike the other toggles this one changes how pages are carved up --
        the reference list stops being a region of its own -- so the layout is
        analysed again. Corrections the reader made by hand are keyed to region
        rectangles, which do not move, and the caller puts them back.
        """
        if clean == self.clean_text:
            return
        self.clean_text = clean
        self.regions = layout.analyse(self, skip_references=clean)
        self.rebuild()

    def region_at(self, page: int, x: float, y: float):
        """The layout region under a point, if any."""
        for region in self.regions.get(page) or []:
            if region.contains(x, y, pad=2.0):
                return region
        return None

    def set_region_reads(self, region, reads: bool) -> None:
        """Include or exclude a region, and rebuild the reading order.

        Word positions are keyed off region order, which does not change here,
        so existing highlights keep pointing at the same words.
        """
        region.kind = layout.BODY if reads else layout.SKIPPED
        if reads and not region.reason:
            region.reason = "you chose to read this"
        elif not reads:
            region.reason = "you chose to skip this"
        self.rebuild()

    def rebuild(self) -> None:
        for word in self.words:
            word.spoken = True
        self.words = []
        self.page_words = {}
        self.sentences = []
        self._build_sentences()

    def sentences_from_range(self, first: int, last: int) -> list[Sentence]:
        """Build throwaway sentences covering words[first..last], for reading a selection."""
        first, last = max(0, min(first, last)), min(max(first, last), len(self.words) - 1)
        if first > last:
            return []
        picked = self.words[first : last + 1]
        result: list[Sentence] = []
        for chunk in chunk_into_sentences(picked, self.clean_text):
            # A selection is read and converted by the same rules as the rest
            # of the document; without this, a citation in a selected passage
            # was spoken aloud even with citation skipping on. The words are
            # the document's own, already marked by the main build, so the
            # marking pass is deliberately not repeated here -- flipping
            # Word.spoken on a throwaway sentence would change the real one.
            result.append(Sentence(index=len(result), page=chunk[0].page, words=chunk,
                                   strip_citations=self.skip_citations))
        return result

    def selection_text(self, first: int, last: int) -> str:
        """The selected words as written, for the clipboard and for note quotes.

        Citations stay in -- this is a quotation from the document, not a
        transcript of the voice -- but a word the typesetter broke across a
        line is put back together, so "can- not" is copied as "cannot".
        """
        first, last = max(0, min(first, last)), min(max(first, last), len(self.words) - 1)
        if first > last:
            return ""
        parts: list[str] = []
        for word in self.words[first : last + 1]:
            if word.joins_next and word.text.endswith("-"):
                parts.append(word.text[:-1])
            else:
                parts.append(word.text + " ")
        return "".join(parts).strip()

    # -- lookups used by the UI -------------------------------------------

    def first_sentence_on_page(self, page: int) -> int:
        for sentence in self.sentences:
            if sentence.page >= page:
                return sentence.index
        return max(len(self.sentences) - 1, 0)

    def word_at_point(self, page: int, x: float, y: float, pad: float = 1.5) -> Word | None:
        """The word actually under a point, or None if the point is off the text.

        Only a small padding is allowed, so clicking a margin or the gap between
        paragraphs selects nothing rather than grabbing the nearest line.
        """
        for word in self.page_words.get(page, ()):
            wx0, wy0, wx1, wy1 = word.rect
            if wx0 - pad <= x <= wx1 + pad and wy0 - pad <= y <= wy1 + pad:
                return word
        return None

    def nearest_word_on_line(self, page: int, x: float, y: float) -> Word | None:
        """The closest word on the line under a point, used while dragging a selection."""
        best: tuple[float, Word] | None = None
        for word in self.page_words.get(page, ()):
            _, wy0, _, wy1 = word.rect
            if wy0 <= y <= wy1:
                distance = min(abs(x - word.rect[0]), abs(x - word.rect[2]))
                if best is None or distance < best[0]:
                    best = (distance, word)
        return best[1] if best else None

    def sentence_at_point(self, page: int, x: float, y: float) -> int | None:
        """The sentence under a click, or None when the click missed the text."""
        word = self.word_at_point(page, x, y)
        return word.sentence if word is not None and word.sentence >= 0 else None

    def page_size(self, page: int) -> tuple[float, float]:
        """Page width and height in PDF points."""
        rect = self.doc.load_page(page).rect
        return rect.width, rect.height

    def render_page(self, page: int, zoom: float) -> pymupdf.Pixmap:
        matrix = pymupdf.Matrix(zoom, zoom)
        return self.doc.load_page(page).get_pixmap(matrix=matrix, alpha=False)
