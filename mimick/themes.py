"""What a document keeps coming back to: the words and phrases it repeats.

Kat asked (23 September) for "what repeats constantly?" -- the big themes of a
reading, and where each is found. This is the first, plain answer: the terms a
document uses again and again, counted over the sentences it would read aloud
(so running headers, reference lists and skipped regions do not count), each
with the pages it is on. Two-word phrases come first, since "residential
schools" says more than "schools"; a single word is listed only where it is
not just the half of one of those phrases.

It counts; it does not understand. A summary that says what the themes *mean*
would need a language model, which Mimick does not have and would not send a
reading to. Shared with the browser version through tools/port.sh.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

# Words that repeat in every text and say nothing about this one.
_STOP = set("""
a about above across after again against all almost also although always am among an and another any anyone
anything are around as at away back be became because become becomes been before being below between both
but by came can cannot could did do does doing done down during each either else enough even ever every few
first for from further get gets getting give given go goes going got had has have having he her here hers
herself him himself his how however i if in into is it its itself just last least less let like made make
makes making many may me might more most much must my myself near need needs neither never new next no nor
not now of off often on once one only onto or other others otherwise our ours ourselves out over own per
perhaps put rather really said same say says see seem seems several shall she should since so some something
sometimes still such take taken than that the their theirs them themselves then there therefore these they
thing things this those though three through thus to together too took toward towards two under until up
upon us use used uses using very via was way ways we well were what whatever when where whether which while
who whom whose why will with within without would yet you your yours yourself yourselves
also e.g i.e et al etc p pp ibid fig figure table chapter page pages vol eds ed
author authors retrieved available accessed doi http https www html time times
""".split())

# A web address is not a theme, however often a guide prints its own.
_ADDRESS = re.compile(r"\S*(?:www\.|https?://|\.(?:ca|com|org|net|gov|edu)\b)\S*", re.I)
_WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|['’-](?=[^\W\d_]))*", re.UNICODE)

WORDS_LISTED = 20
PHRASES_LISTED = 12
MIN_COUNT = 3                 # fewer than this is not "constantly"


def _words(text: str) -> list[str]:
    return [w.lower().replace("’", "'") for w in _WORD.findall(text)]


def _key(word: str) -> str:
    """One key for a word and its plural: "students" and "student" are one theme."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def repeats(sentences) -> dict:
    """``sentences`` are the document's (each with ``.text`` and ``.page``).

    Answers ``{"phrases": [...], "words": [...]}``, most repeated first, each
    ``{"term", "count", "pages"}`` -- ``term`` in the spelling the document
    uses most, which is also what Find will look for, and ``pages`` 0-based.
    """
    word_count: Counter = Counter()
    phrase_count: Counter = Counter()
    word_pages: dict[str, set] = defaultdict(set)
    phrase_pages: dict[str, set] = defaultdict(set)
    spelled: dict[str, Counter] = defaultdict(Counter)

    for sentence in sentences:
        words = _words(_ADDRESS.sub(" ", sentence.text))
        previous = None
        for word in words:
            if word.endswith("'s"):
                word = word[:-2]                  # "Canada's" counts as "Canada"
            if len(word) < 3 or word in _STOP:
                previous = None                   # a phrase does not run across one
                continue
            key = _key(word)
            word_count[key] += 1
            word_pages[key].add(sentence.page)
            spelled[key][word] += 1
            if previous is not None:
                pair = (previous[0], key)
                phrase_count[pair] += 1
                phrase_pages[pair].add(sentence.page)
                spelled[pair][f"{previous[1]} {word}"] += 1
            previous = (key, word)

    def entry(key, counter, pages):
        return {"term": spelled[key].most_common(1)[0][0], "count": counter[key], "pages": sorted(pages[key])}

    phrases = [key for key, n in phrase_count.most_common() if n >= MIN_COUNT][:PHRASES_LISTED]
    # A word that is almost always half of a listed phrase adds nothing to it.
    inside = Counter()
    for pair in phrases:
        for half in pair:
            inside[half] += phrase_count[pair]
    words = [key for key, n in word_count.most_common()
             if n >= MIN_COUNT and inside[key] < n * 0.8][:WORDS_LISTED]
    return {"phrases": [entry(k, phrase_count, phrase_pages) for k in phrases],
            "words": [entry(k, word_count, word_pages) for k in words]}


def page_ranges(pages: list[int]) -> str:
    """0-based pages as a reader writes them, 1-based: "1–3, 7, 9–10"."""
    out, start, last = [], None, None
    for page in sorted(set(pages)):
        if start is None:
            start = last = page
        elif page == last + 1:
            last = page
        else:
            out.append(f"{start + 1}" if start == last else f"{start + 1}–{last + 1}")
            start = last = page
    if start is not None:
        out.append(f"{start + 1}" if start == last else f"{start + 1}–{last + 1}")
    return ", ".join(out)
