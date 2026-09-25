"""Finding in-text citations, so they are not read out mid-sentence.

"The deal included CAD 92 million [51]" should be heard without the fifty-one.
The same goes for "(Smith et al., 2020, p. 45)" and a bare "(p. 293)".

Only the common shapes are matched, and each needs a positive signal -- a
bracketed number, a year, a page marker, "et al." -- so ordinary parentheses
survive. "(and this matters)" is left alone.
"""

from __future__ import annotations

import re

# A name as it appears in a citation: Smith, O'Brien, van der Berg, Wet'suwet'en.
_NAME = r"[A-ZÀ-Ü][\w'’‐-―-]*"
# The comma may follow the name with no space -- "Moreau, Mendick & Epstein" --
# so it cannot be lumped in with the words, which do need one.
_JOIN = r"(?:\s*,\s*|\s+(?:et\s+al\.|and|&)\s*)"
_NAMES = rf"{_NAME}(?:{_JOIN}{_NAME}?)*"
# A reprint carries both dates: Piaget's (2008/1972).
_ONE_YEAR = r"(?:1[5-9]|20)\d{2}[a-z]?"
_YEAR = rf"{_ONE_YEAR}(?:\s*/\s*{_ONE_YEAR})?"
_PAGES = r"p{1,2}\.\s*\d+(?:\s*[‐-―-]\s*\d+)?"
_LEAD = r"(?:see\s+|cf\.\s+|e\.g\.,?\s+)?"

# One work inside a citation. Several may be listed, separated by semicolons:
# "(Egan, 2002; Walkerdine, 1984)" is one citation naming two of them, and
# matching only the first left the rest to be read aloud.
_WORK = rf"{_LEAD}{_NAMES},?\s*{_YEAR}(?:\s*[,;]\s*{_PAGES})?"
_WORK_NO_COMMA = (rf"{_LEAD}{_NAMES}\s+(?:{_YEAR}|\d{{1,4}})"
                  rf"(?:\s*[,:]\s*\d+(?:\s*[‐-―-]\s*\d+)?)?")


def _listed(work: str) -> str:
    """One work, or several of them separated by semicolons, in brackets."""
    return rf"\(\s*{work}(?:\s*;\s*{work})*\s*\)"


PATTERNS = [
    # Vancouver, IEEE, Nature: [12]  [1,2]  [3-5]  [12], [13]
    re.compile(r"\[\s*\d+(?:\s*[,;]\s*\d+|\s*[‐-―-]\s*\d+)*\s*\]"),
    # APA with "et al." and no year: (Smith et al.)
    re.compile(rf"\(\s*{_NAME}\s+et\s+al\.?,?\s*{_YEAR}?"
               rf"(?:\s*[,;]\s*{_PAGES})?\s*\)"),
    # APA, Harvard, Chicago author-date: (Smith, 2020)  (Smith & Jones, 2020, p. 45)
    re.compile(_listed(_WORK)),
    # Chicago and MLA without a comma: (Smith 2020, 45)  (Smith 45)
    re.compile(_listed(_WORK_NO_COMMA)),
    # A reference with the author already named in the sentence, so only the
    # date and page are bracketed: (p. 293)  (pp. 12-15)  (2020)  (1992, p. 33)
    re.compile(_listed(rf"(?:{_YEAR}(?:\s*,\s*{_PAGES})?|{_PAGES})")),
    # ibid., op. cit., and friends
    re.compile(r"\(\s*(?:ibid\.?|op\.\s*cit\.?|loc\.\s*cit\.?)[^)]{0,20}\)", re.IGNORECASE),
]


def spans(text: str) -> list[tuple[int, int]]:
    """Character ranges of every citation in a piece of text."""
    found: list[tuple[int, int]] = []
    for pattern in PATTERNS:
        for match in pattern.finditer(text):
            found.append((match.start(), match.end()))
    if not found:
        return []
    found.sort()
    merged = [list(found[0])]
    for start, end in found[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def strip(text: str) -> str:
    """The same text with its citations removed and spacing tidied."""
    for start, end in reversed(spans(text)):
        text = text[:start] + text[end:]
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def mark_words(words) -> None:
    """Flag the words of a run that belong to a citation, so they aren't spoken."""
    if not words:
        return
    pieces, offsets, cursor = [], [], 0
    for word in words:
        offsets.append((cursor, cursor + len(word.text)))
        pieces.append(word.text)
        cursor += len(word.text) + 1
    text = " ".join(pieces)

    ranges = spans(text)
    if not ranges:
        return
    for word, (start, end) in zip(words, offsets):
        for low, high in ranges:
            # A word belongs to the citation if it begins inside the match.
            # Containment is not enough: "(p. 21)." is extracted as the words
            # "(p." and "21).", and the second reaches one character past the
            # closing bracket, so requiring the whole word to fit left a bare
            # "21)." to be read aloud.
            if low <= start < high:
                word.spoken = False
                break
