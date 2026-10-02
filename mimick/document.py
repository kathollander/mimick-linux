"""Turn a PDF into a stream of sentences that each know where they sit on the page.

The unit of playback is a Sentence. Every sentence carries the words it is made
of, and every word carries its rectangle on the page, which is what lets the UI
highlight along with the voice.
"""

from __future__ import annotations

import re
from collections import Counter
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
    keeps_hyphen: bool = False # ...and that hyphen is the word's own, not the typesetter's
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
        assembled = _join_words([word for word in self.words if word.spoken])
        if self.strip_citations:
            # A second pass over the finished text, because a citation with a
            # full stop stuck to it -- "[53]." -- is not a whole word.
            assembled = citations.strip(assembled)
        return assembled

    def rects_for(self, first: int, last: int) -> list[tuple[float, float, float, float]]:
        """Merge the rectangles of words[first:last+1] into per-line boxes."""
        chosen = self.words[max(first, 0) : last + 1]
        return _merge_rects([word.rect for word in chosen])


_HEADING_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+")


def _heading_key(text: str) -> str:
    """A heading reduced to what two spellings of it would have in common.

    A bookmark and the heading printed on the page rarely match character for
    character: one says "2. What Students Chose to Hear" and the other "What
    Students Chose to Hear", and either may carry trailing punctuation or
    stray spacing.
    """
    text = _HEADING_NUMBER.sub("", " ".join(str(text).split()))
    return text.casefold().strip(" .:;–—-")


def _bare(text: str) -> str:
    """A word with its surrounding punctuation and case taken off.

    Quotes, brackets and the full stop go; an internal hyphen stays, because
    that hyphen is the whole point of looking.
    """
    return text.strip("‘’“”\"'()[]{}.,;:!?—–").casefold()


def _join_words(words: list[Word]) -> str:
    """Words as one string, with a word broken across a line put back together.

    Whether the hyphen survives depends on whose it was. Three things are asked,
    in order:

    The document's own usage, decided in ``_mark_hyphenation`` and carried on
    ``keeps_hyphen``: if it writes "non-status" anywhere it did not have to
    break, the hyphen is the word's own and stays here too.

    Failing that, a break before a capital is a real hyphen that fell at the end
    of a line -- "Piatek- Jimenez" is "Piatek-Jimenez" -- so the hyphen stays
    and only the space goes, or the voice pauses in the middle of a name.

    Otherwise it was the typesetter's: "creat- ing" is "creating".

    The first test earns its keep. Compound words are overwhelmingly
    lower-lower, so the capital rule alone closed up every one that happened to
    land at a line end, and the voice said "nonstatus" and "secondgeneration".
    """
    parts: list[str] = []
    for word, following in zip(words, words[1:] + [None]):
        if word.joins_next and word.text.endswith("-"):
            real = word.keeps_hyphen or (
                following is not None and following.text[:1].isupper())
            parts.append(word.text if real else word.text[:-1])
        else:
            parts.append(word.text + " ")
    return "".join(parts).strip()


def align_marks(sentence: Sentence, marks: list[tuple[float, str]]) -> list[tuple[float, int]]:
    """Map the engine's spoken-word timings onto indices into ``sentence.words``.

    The engine may split, merge or skip words relative to the page, so we walk
    both sequences forward and match on a normalised form, tolerating gaps.
    ``marks`` are (seconds, spoken word) pairs, as ``Clip.marks`` holds them.

    Lives here rather than in ``player.py`` because it needs nothing but a
    sentence, so the browser version runs this same copy.
    """
    if not marks:
        return []
    # Only the spoken words can be matched: citations are passed over.
    spoken = [(position, word.key) for position, word in enumerate(sentence.words)
              if word.spoken]
    aligned: list[tuple[float, int]] = []
    cursor = 0
    # ``mark`` must not be called ``spoken``: rebinding the list above to the
    # mark's own text made ``spoken[offset][1]`` index a single character, which
    # raised IndexError on the very first word and killed the playback thread
    # before a sample reached the speakers.
    for when, mark in marks:
        target = _WORD_CHARS.sub("", mark).lower()
        if not target:
            continue
        found = None
        for offset in range(cursor, min(cursor + 8, len(spoken))):
            key = spoken[offset][1]
            if key and (key == target or key.startswith(target) or target.startswith(key)):
                found = offset
                break
        if found is None:
            continue
        aligned.append((when, spoken[found][0]))
        cursor = found + 1
    return aligned


# Characters folded together before searching, so what is typed on a keyboard
# finds what a typesetter put on the page: curly quotes and primes become
# straight ones, the several dashes become a hyphen, a soft hyphen disappears
# and a non-breaking space becomes a space. NFKC first, which is what turns the
# "fi" and "fl" ligatures into their letters.
_FOLD = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "−": "-", "­": None, " ": " ",
})

# A search stops after this many matches. A one-letter query on a long book
# otherwise builds a list nobody can use, and stepping through it is hopeless
# anyway; the find bar says the count was cut short.
FIND_LIMIT = 20000


def _fold(text: str, match_case: bool) -> str:
    """Text as it should be compared: ligatures, quotes and dashes regularised."""
    import unicodedata

    text = unicodedata.normalize("NFKC", text).translate(_FOLD)
    return text if match_case else text.casefold()


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
                 clean_text: bool = True, read_footnotes: bool = True) -> None:
        self.path = Path(path)
        self.skip_citations = skip_citations
        # Whether the notes at the foot of each page are spoken. They are read
        # after the page they hang off, not where they are referred to, so a
        # long apparatus interrupts the argument every page; this is the switch
        # that turns them off. Kept separate from ``clean_text`` because a
        # footnote is the author's own writing, not the paperwork around it.
        self.read_footnotes = read_footnotes
        # Words grouped into visual lines, per page, for moving a cursor up and
        # down. Filled in on demand; see ``_lines_on``.
        self._lines: dict[int, list[list[Word]]] = {}
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
        # Every build renumbers the words, so anything keyed off word indices --
        # the search index below, and the window's list of matches -- is stale
        # from here on. Counting builds is what tells them apart: a rebuild can
        # easily end with the same number of words it started with.
        self._build_id = getattr(self, "_build_id", 0) + 1
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
                                index=len(self.words),
                                readable=self._region_reads(region),
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
        """Flag words broken by a hyphen at the end of a line.

        Also work out, for each break, whether the hyphen belongs to the word or
        to the typesetter -- see ``_join_words`` for why that matters and what
        is done with the answer.
        """
        # How often the document writes each word, punctuation and case aside.
        # A compound it sets with a hyphen somewhere it did not have to break --
        # "non-status" in the middle of a line -- is the document telling us, in
        # its own words, that the hyphen is real.
        written = Counter(_bare(word.text) for word in self.words)
        for word, following in zip(self.words, self.words[1:]):
            if not word.text.endswith("-") or len(word.text) < 2:
                continue
            if word.region != following.region:
                continue
            # The next word has to sit on a later line for this to be a break,
            # and start with a letter; _join_words decides what the hyphen was.
            if following.rect[1] > word.rect[1] + 1.0 and following.text[:1].isalpha():
                word.joins_next = True
                # The two candidate spellings of this one broken word.
                hyphenated = _bare(word.text) + _bare(following.text)
                closed = _bare(word.text)[:-1] + _bare(following.text)
                # Whichever the document writes more often wins, and a tie goes
                # to the hyphen, since the break in front of us is one vote for
                # it already. Counting rather than merely looking matters: a
                # document that says "Indigenous" forty times and "In-digenous"
                # once, where a line broke and the extraction ran the halves
                # together, should not have that one accident outvote the forty.
                word.keeps_hyphen = (
                    written[hyphenated] >= max(1, written[closed])
                    # A hyphen after a figure is the word's own -- "113-year",
                    # "20-minute". A typesetter never breaks there, and the
                    # document rarely repeats the phrase to prove it.
                    or word.text[-2:-1].isdigit()
                    # "self-" is the one prefix safe to assume, for a document
                    # that never writes the compound anywhere else to prove it:
                    # English closes up only "selfish", "selfless" and
                    # "selfhood", none of which a typesetter would break after
                    # "self". The other candidates are not safe -- "non-" would
                    # wreck a broken "nonsense", "anti-" a broken "anticipate",
                    # "inter-" a broken "interpretation" -- so they are left to
                    # the counting above.
                    or _bare(word.text) == "self-"
                )

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

    def _region_reads(self, region) -> bool:
        """Whether a region's words are spoken, footnotes included or not.

        A footnote keeps its own label whichever way the switch is set, so the
        reading plan can still say what it is and the setting can be changed
        without analysing the page again -- which matters, because region order
        is what word indices are keyed to and an annotation must keep pointing
        at the same words.
        """
        if region.kind == layout.FOOTNOTE:
            return self.read_footnotes
        return region.reads

    @property
    def has_footnotes(self) -> bool:
        """Whether this document has footnotes worth offering to skip."""
        return any(region.kind == layout.FOOTNOTE
                   for regions in self.regions.values() for region in regions)

    def set_read_footnotes(self, read: bool) -> None:
        """Start or stop reading the notes at the foot of each page."""
        if read == self.read_footnotes:
            return
        self.read_footnotes = read
        self.rebuild()

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
        self._lines = {}
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
        return _join_words(self.words[first : last + 1])

    # -- searching ---------------------------------------------------------
    #
    # Find works over the words as they are written, not the text the voice is
    # given: a reader searching for a name wants it found inside a citation the
    # voice passes over, and wants what is printed on the page, not the cleaned
    # up version. A match is a run of whole words -- (first, last, page) -- so
    # it can be lit, selected and read exactly like a selection dragged out by
    # hand.

    def _searchable(self, match_case: bool) -> tuple[str, "array.array"]:
        """The document's words as one string, and where each word starts in it.

        Built once per case setting and kept, because a reader types a query one
        letter at a time and every letter searches the whole document again.
        """
        from array import array

        key = (self._build_id, match_case)
        if getattr(self, "_find_key", None) != key:
            parts: list[str] = []
            starts = array("l")
            at = 0
            words = self.words
            for word, following in zip(words, words[1:] + [None]):
                text = _fold(word.text, match_case)
                # The same rule as _join_words, and it has to stay the same rule:
                # what is searched must be what is read and what is copied, or a
                # word is findable in one and not the others.
                if word.joins_next and text.endswith("-"):
                    real = word.keeps_hyphen or (
                        following is not None and following.text[:1].isupper())
                    piece = text if real else text[:-1]
                else:
                    piece = text + " "
                starts.append(at)
                parts.append(piece)
                at += len(piece)
            self._find_key = key
            self._find_text = "".join(parts)
            self._find_starts = starts
        return self._find_text, self._find_starts

    def find(self, query: str, match_case: bool = False,
             limit: int = FIND_LIMIT) -> tuple[list[tuple[int, int, int]], bool]:
        """Every place ``query`` is written, in document order.

        Returns the matches as ``(first word, last word, page)``, and whether
        ``limit`` cut the list short. Spaces in the query match any spacing on
        the page, so a phrase broken across two lines is still found.
        """
        from bisect import bisect_right

        needle = " ".join(_fold(query or "", match_case).split())
        if not needle:
            return [], False
        text, starts = self._searchable(match_case)
        words = self.words
        found: list[tuple[int, int, int]] = []
        at = text.find(needle)
        while at >= 0:
            first = bisect_right(starts, at) - 1
            last = bisect_right(starts, at + len(needle) - 1) - 1
            found.append((first, last, words[first].page))
            if len(found) >= limit:
                return found, text.find(needle, at + 1) >= 0
            at = text.find(needle, at + 1)
        return found, False

    # -- moving a cursor through the text ----------------------------------
    #
    # Left and right are just index steps: word order is region order, which is
    # reading order, so stepping the index walks the text the way the voice
    # does -- down a column and on to the next, never across a two-column page.
    # Up, down, Home and End are the other thing entirely. They are about where
    # the words sit on the paper, so they work from the rectangles.

    def _lines_on(self, page: int) -> list[list[Word]]:
        """The page's words grouped into visual lines, each ordered across.

        Two words are on the same line when their rectangles overlap vertically
        by more than half the shorter one -- which tolerates the way a capital,
        a descender and a superscript all sit at slightly different heights.
        Built on demand and cached; ``rebuild`` empties the cache, so the
        footnote and citation switches cannot leave it describing words that
        are no longer there.
        """
        cached = self._lines.get(page)
        if cached is not None:
            return cached
        lines: list[list[Word]] = []
        for word in sorted(self.page_words.get(page, ()), key=lambda w: w.rect[1]):
            _, top, _, bottom = word.rect
            for line in lines:
                _, line_top, _, line_bottom = line[-1].rect
                overlap = min(bottom, line_bottom) - max(top, line_top)
                shorter = min(bottom - top, line_bottom - line_top)
                if shorter > 0 and overlap > shorter / 2:
                    line.append(word)
                    break
            else:
                lines.append([word])
        for line in lines:
            line.sort(key=lambda w: w.rect[0])
        lines.sort(key=lambda line: line[0].rect[1])
        self._lines[page] = lines
        return lines

    def _line_of(self, index: int) -> tuple[list[list[Word]], int]:
        """The lines of a word's page, and which of them the word is on."""
        word = self.words[index]
        lines = self._lines_on(word.page)
        for position, line in enumerate(lines):
            if any(other.index == index for other in line):
                return lines, position
        return lines, -1

    def line_ends(self, index: int) -> tuple[int, int]:
        """The first and last word of the line this word is on."""
        if not (0 <= index < len(self.words)):
            return index, index
        lines, position = self._line_of(index)
        if position < 0:
            return index, index
        line = lines[position]
        return line[0].index, line[-1].index

    def word_on_next_line(self, index: int, direction: int) -> int:
        """The word directly above or below this one, by horizontal position.

        At the top or bottom of a page it carries on to the neighbouring page,
        so holding an arrow key walks the whole document rather than stopping
        at a page edge.
        """
        if not (0 <= index < len(self.words)):
            return index
        word = self.words[index]
        centre = (word.rect[0] + word.rect[2]) / 2
        lines, position = self._line_of(index)
        if position < 0:
            return index
        target = position + direction
        if not 0 <= target < len(lines):
            page = word.page + direction
            if not 0 <= page < self.page_count:
                return index
            neighbour = self._lines_on(page)
            if not neighbour:
                return index
            lines, target = neighbour, 0 if direction > 0 else len(neighbour) - 1
        return min(lines[target],
                   key=lambda w: abs((w.rect[0] + w.rect[2]) / 2 - centre)).index

    def sentence_step(self, index: int, direction: int) -> int:
        """The first word of the previous or next sentence.

        Stepping back from inside a sentence goes to its own start first, the
        way a word processor does, so the key is useful for getting to the head
        of the line you just heard.
        """
        if not self.sentences or not (0 <= index < len(self.words)):
            return index
        here = self.words[index].sentence
        if here < 0:
            return index
        first = self.sentences[here].words[0].index
        if direction < 0 and index > first:
            return first
        target = here + direction
        if not 0 <= target < len(self.sentences):
            return first if direction < 0 else self.sentences[here].words[-1].index
        return self.sentences[target].words[0].index

    # -- lookups used by the UI -------------------------------------------

    def first_sentence_on_page(self, page: int) -> int:
        for sentence in self.sentences:
            if sentence.page >= page:
                return sentence.index
        return max(len(self.sentences) - 1, 0)

    def outline(self) -> list[tuple[int, str, int, bool]]:
        """The PDF's own table of contents, if it has one.

        Each entry is ``(level, title, page, open)``. ``page`` counts from zero,
        or is -1 where the entry goes nowhere in this file -- a web link, or a
        bookmark left pointing at a page that is not here. ``open`` is whether
        the file asks for the entry's children to be shown.

        Deliberately no y. A bookmark's destination carries one, but it cannot
        be trusted: the PDF specification puts it in user space, measured from
        the bottom of the page, and real files disagree. *Big Ideas from Atleo
        and Boron* stores it that way, and sample/test-paper.pdf stores it
        measured from the top, so no single reading of it is right for both. A
        heading is found by its own title instead -- see
        ``first_sentence_from`` -- which needs no coordinates and cannot be
        wrong in that particular way.

        A damaged outline gives none rather than stopping the document opening:
        a table of contents is a convenience, and nobody should be unable to
        open a paper because its bookmarks are malformed.
        """
        try:
            toc = self.doc.get_toc(simple=False)
        except Exception:
            return []
        entries = []
        for level, title, number, destination in toc:
            page = number - 1 if 0 < number <= self.doc.page_count else -1
            shown = not (isinstance(destination, dict) and destination.get("collapse"))
            entries.append((int(level), " ".join(str(title).split()), page, shown))
        return entries

    def first_sentence_from(self, page: int, title: str = "") -> int:
        """The sentence a contents entry means, found by its own heading.

        Looks for the heading's words on the page the bookmark names, so that
        several sections on one page each go to the right place. Falls back to
        the top of that page when the heading cannot be found there, which is
        the worst this can do and is still the right page.
        """
        if not self.sentences:
            return 0
        at = self.word_of_heading(page, title)
        if at is not None:
            # Matched against the words on the page rather than the sentences,
            # because a heading is not always a sentence: "References" heads a
            # list the cleanup does not read, so there is no sentence to match,
            # and matching sentences alone sent it backwards to whatever else
            # began that page.
            for sentence in self.sentences:
                if sentence.words and sentence.words[0].index >= at:
                    return sentence.index
            return len(self.sentences) - 1
        return self.first_sentence_on_page(page)

    def word_of_heading(self, page: int, title: str) -> int | None:
        """Where a contents entry's heading is printed, as a word index.

        Only the named page and the one after it: a bookmark is sometimes a
        page out, but the same words matched much further off are a different
        occurrence -- a running header, or the phrase turning up in the body.
        """
        wanted = _heading_key(title)
        if not wanted:
            return None
        here = [word for word in self.words if page <= word.page <= page + 1]
        for start in range(len(here)):
            if here[start].page > page + 1:
                break
            # Grow a run of words from this one until it is as long as the
            # heading, then see whether it says the same thing.
            grown = ""
            for offset, word in enumerate(here[start:start + 24]):
                grown = f"{grown} {word.text}".strip()
                key = _heading_key(grown)
                if key == wanted:
                    # The first word with a letter in it, not the run's first
                    # word: _heading_key drops leading numbering, so a run can
                    # legitimately start on a bare "1" -- a section number, or
                    # the page number ending the running header above it.
                    for candidate in here[start:start + offset + 1]:
                        if any(character.isalpha() for character in candidate.text):
                            return candidate.index
                    return here[start].index
                if len(key) >= len(wanted):
                    break
        return None

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
