"""Tidying text extracted from a PDF before a voice ever sees it.

A PDF stores glyphs, not words, and two artefacts of that reach the ear.
Typographic ligatures are single characters -- "conﬁguration" is spelled with
U+FB01, not with an f and an i -- and a voice asked to say that either spells
it out or swallows the syllable. Diacritics that failed to combine leave a
spacing macron stranded beside its letter, so "K̄ehaulani" arrives as
"K¯ehaulani".

Neither is visible on the page; both are audible. Everything here is
conservative: only characters that are always extraction damage are touched.
æ and œ are real letters in real words and are left alone.
"""

from __future__ import annotations

import re

# U+FB00..U+FB06. These exist only as typesetting glyphs -- no language spells
# a word with them -- so expanding them is always right.
LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
_LIGATURE_RE = re.compile("[" + "".join(LIGATURES) + "]")

# A spacing accent sitting between letters is a diacritic that did not combine
# with the letter it belongs to. Dropping it is closer to the word than reading
# it: "Sen 'ák¯w" should be heard as "ak w", not "ak macron w".
_STRANDED_ACCENT = re.compile(r"(?<=\w)[¯¨´ˆˇ˘˚˜](?=\w)")

# A soft hyphen is invisible on the page and meaningless to a voice.
_INVISIBLE = re.compile(r"[­​‌‍﻿]")


def normalise(text: str) -> str:
    """One word, or one run, as the voice should receive it."""
    if not text:
        return text
    if _LIGATURE_RE.search(text):
        text = _LIGATURE_RE.sub(lambda m: LIGATURES[m.group()], text)
    text = _STRANDED_ACCENT.sub("", text)
    return _INVISIBLE.sub("", text)


# -- front matter -------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Labelled metadata: the masthead at the top of a journal article and the
# declarations at the bottom. Each has to be the *start* of the run and carry
# its colon, so a sentence that merely mentions copyright, or funding, is not
# mistaken for the boilerplate.
#
# Acknowledgements are deliberately absent -- they are prose, and people read
# them.
_LABELLED = re.compile(
    r"^\s*(?:Received|Revised|Accepted|Published|Academic\s+Editor|Citation|"
    r"Copyright|Licensee|Correspondence|Author\s+Contributions|Funding|"
    r"Data\s+Availability(?:\s+Statement)?|Conflicts?\s+of\s+Interest|"
    r"Institutional\s+Review\s+Board(?:\s+Statement)?|"
    r"Informed\s+Consent(?:\s+Statement)?|Supplementary\s+Materials?)"
    r"\b\s*[:.]",
    re.IGNORECASE,
)

# A labelled block is a few lines. Anything longer that happens to open with one
# of those words is prose, and dropping it wholesale would be a real loss.
MAX_LABELLED_CHARS = 600


def is_front_matter(text: str) -> bool:
    """Whether a run is boilerplate rather than something to read aloud.

    An address block is caught by the email address in it, which is the one
    signal that never appears in body prose.
    """
    flat = " ".join(text.split())
    if _EMAIL.search(flat):
        return True
    return bool(_LABELLED.match(flat)) and len(flat) <= MAX_LABELLED_CHARS
