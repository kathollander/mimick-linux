"""Working out what on a page is worth reading aloud, and in what order.

Sorting words by position works for a plain single-column document and falls
apart on anything laid out like a journal article: a narrow sidebar of citation
and licence boilerplate interleaves line by line with the article text, and a
running header gets read on every page.

This module cuts each page into regions using recursive XY-cut -- split on the
widest band of whitespace, alternating horizontal and vertical -- then sorts
those regions into reading order and labels the ones that are not body text.

The result is deliberately inspectable: every region carries why it was
classified as it was, so the interface can show the reader what will be read
and let them disagree.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field

# Whitespace narrower than this is not a column or paragraph break. Journal
# sidebars sit closer to the text than you would guess -- the gap in the sample
# article is 12.7pt -- so this has to stay fairly tight.
MIN_GAP_X = 10.0
MIN_GAP_Y = 5.0
MAX_DEPTH = 8

# Bands at the very top and bottom of a page where furniture lives.
FURNITURE_BAND = 0.085
# A repeated line has to appear on at least this share of pages to count.
FURNITURE_SHARE = 0.4
FURNITURE_MIN_PAGES = 3
# A stray scrap in the header or footer band, like a journal's logo, is
# furniture even if it only appears once.
FURNITURE_SCRAP_CHARS = 25

# A region off to one side, narrower than this share of the main column, is
# treated as marginalia rather than part of the text.
ASIDE_WIDTH_SHARE = 0.62

BAND_MIDDLE = 0
BAND_EDGE = 1            # touches the header or footer band
BAND_BOTTOM_INSIDE = 2   # sits wholly in the footer band

BODY = "body"
ASIDE = "aside"
FURNITURE = "furniture"
SKIPPED = "skipped"          # the reader excluded it by hand
REFERENCES = "references"    # the bibliography, and whatever follows it

# The heading that opens a reference list. It has to be the whole of the first
# line of a region -- possibly numbered, possibly in capitals -- so a sentence
# that mentions references in passing does not end the document early.
_REFERENCE_HEADING = re.compile(
    r"^\s*(?:\d+\.?\s*)?(?:references|bibliography|works\s+cited|"
    r"literature\s+cited|notes\s+and\s+references|reference\s+list)"
    r"\s*[:.]?\s*$",
    re.IGNORECASE,
)
# A reference list lives at the end. Requiring it in the back of the document
# stops a "References" line in a table of contents from silencing everything.
REFERENCES_FROM_SHARE = 0.5


@dataclass
class Region:
    """A rectangle of a page, and what Mimick makes of it."""

    page: int
    rect: tuple[float, float, float, float]
    kind: str = BODY
    reason: str = ""
    order: int = 0
    chars: int = 0
    text: str = ""

    @property
    def reads(self) -> bool:
        return self.kind == BODY

    @property
    def label(self) -> str:
        return {
            BODY: "read", ASIDE: "side note",
            FURNITURE: "header or footer", SKIPPED: "skipped",
            REFERENCES: "reference list",
        }.get(self.kind, self.kind)

    def contains(self, x: float, y: float, pad: float = 1.0) -> bool:
        x0, y0, x1, y1 = self.rect
        return x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad


# -- recursive XY-cut ---------------------------------------------------------

def _gaps(blocks: list, axis: int, minimum: float):
    """Split blocks either side of the widest whitespace gap along an axis."""
    if len(blocks) < 2:
        return None
    low, high = (0, 2) if axis == 0 else (1, 3)
    spans = sorted((block[low], block[high]) for block in blocks)

    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1] + 0.1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    if len(merged) < 2:
        return None

    widest, index = max(
        (merged[i + 1][0] - merged[i][1], i) for i in range(len(merged) - 1)
    )
    if widest < minimum:
        return None

    boundary = (merged[index][1] + merged[index + 1][0]) / 2
    before = [b for b in blocks if (b[low] + b[high]) / 2 < boundary]
    after = [b for b in blocks if (b[low] + b[high]) / 2 >= boundary]
    if not before or not after:
        return None
    return widest, before, after


def _cut(blocks: list, prefer_rows: bool, depth: int = 0) -> list[list]:
    """Cut a page into leaf groups, in reading order.

    Rows are cut first, then columns within each row, so a full-width title
    above two columns does not merge them.
    """
    if len(blocks) <= 1 or depth >= MAX_DEPTH:
        return [blocks]

    first = _gaps(blocks, 1 if prefer_rows else 0, MIN_GAP_Y if prefer_rows else MIN_GAP_X)
    if first is None:
        second = _gaps(blocks, 0 if prefer_rows else 1, MIN_GAP_X if prefer_rows else MIN_GAP_Y)
        if second is None:
            return [blocks]
        _width, before, after = second
        return _cut(before, prefer_rows, depth + 1) + _cut(after, prefer_rows, depth + 1)

    _width, before, after = first
    return (_cut(before, not prefer_rows, depth + 1)
            + _cut(after, not prefer_rows, depth + 1))


# -- page furniture -----------------------------------------------------------

def _normalise(text: str) -> str:
    return re.sub(r"\d+", "#", " ".join(text.split()))[:60]


def _furniture_keys(pages: dict[int, list]) -> set[str]:
    """Lines that repeat near the top or bottom of many pages."""
    counts: collections.Counter = collections.Counter()
    for blocks in pages.values():
        for block in blocks:
            if block[6]:
                counts[_normalise(block[4])] += 1
    threshold = max(FURNITURE_MIN_PAGES, int(len(pages) * FURNITURE_SHARE))
    return {key for key, count in counts.items() if count >= threshold and key}


# -- the analysis ------------------------------------------------------------

def _mark_references(result: dict[int, list[Region]], page_count: int) -> None:
    """Label the reference list, and everything after it, as not worth reading.

    A bibliography is the largest thing in an academic PDF that nobody wants
    read aloud: the entries are abbreviation-dense, so they shatter into
    fragments -- "Soc.", "Chron.", "[CrossRef] 40." -- and in the sample
    article they are a quarter of the sentences. Once the heading is found,
    everything after it in reading order goes with it, because appendices and
    author biographies follow the same rule.

    Page furniture is left as it is, and so is a region the reader has already
    ruled on by hand, so this can be overruled one region at a time.
    """
    earliest = int(page_count * REFERENCES_FROM_SHARE)
    found = False
    for number in sorted(result):
        for region in result[number]:
            if region.kind in (FURNITURE, SKIPPED):
                continue
            if not found:
                if number < earliest:
                    continue
                if not _REFERENCE_HEADING.match(" ".join(region.text.split())):
                    continue
                found = True
            region.kind = REFERENCES
            region.reason = "the reference list, and what follows it"


def analyse(document, skip_references: bool = True) -> dict[int, list[Region]]:
    """Group every page of a document into regions, in reading order."""
    pages: dict[int, list] = {}
    for number in range(document.page_count):
        page = document.doc.load_page(number)
        height = page.rect.height
        blocks = []
        for x0, y0, x1, y1, text, _no, kind in page.get_text("blocks", sort=True):
            if kind != 0 or not text.strip():
                continue
            top, bottom = height * FURNITURE_BAND, height * (1 - FURNITURE_BAND)
            # A title and a running header sit at the same height, so the top of
            # the page needs a second signal -- repetition across pages, or being
            # a scrap. The very bottom of a page is safe to treat as furniture on
            # position alone: body text does not end up down there.
            if y0 >= bottom:
                band = BAND_BOTTOM_INSIDE
            elif y1 > bottom:
                band = BAND_EDGE
            elif y1 <= top or y0 < top:
                band = BAND_EDGE
            else:
                band = BAND_MIDDLE
            blocks.append((x0, y0, x1, y1, text, number, band))
        pages[number] = blocks

    repeated = _furniture_keys(pages)
    result: dict[int, list[Region]] = {}

    for number, blocks in pages.items():
        body_regions: list[Region] = []
        furniture_regions: list[Region] = []
        furniture, body = [], []
        for block in blocks:
            scrap = len(" ".join(block[4].split())) <= FURNITURE_SCRAP_CHARS
            band = block[6]
            if band == BAND_BOTTOM_INSIDE or (
                band == BAND_EDGE and (_normalise(block[4]) in repeated or scrap)
            ):
                furniture.append(block)
            else:
                body.append(block)

        for block in furniture:
            furniture_regions.append(Region(
                page=number,
                rect=(block[0], block[1], block[2], block[3]),
                kind=FURNITURE,
                reason=(
                    "a running header or footer, repeated across the document"
                    if _normalise(block[4]) in repeated
                    else "sits in the page's header or footer band"
                ),
                chars=len(block[4]),
                text=" ".join(block[4].split()),
            ))

        groups = [group for group in _cut(body, prefer_rows=True) if group]
        laid_out = []
        for group in groups:
            x0 = min(b[0] for b in group)
            y0 = min(b[1] for b in group)
            x1 = max(b[2] for b in group)
            y1 = max(b[3] for b in group)
            chars = sum(len(b[4]) for b in group)
            laid_out.append({
                "rect": (x0, y0, x1, y1), "chars": chars, "blocks": group,
                "text": " ".join(" ".join(b[4].split()) for b in group),
            })

        main = max(laid_out, key=lambda g: g["chars"], default=None)
        for group in laid_out:
            kind, reason = BODY, ""
            if main is not None and group is not main:
                width = group["rect"][2] - group["rect"][0]
                main_width = main["rect"][2] - main["rect"][0]
                mx0, _my0, mx1, _my1 = main["rect"]
                beside = group["rect"][2] <= mx0 + 2 or group["rect"][0] >= mx1 - 2
                if beside and width < main_width * ASIDE_WIDTH_SHARE:
                    kind = ASIDE
                    reason = ("a narrow column beside the text, usually citation "
                              "or licence boilerplate")
            body_regions.append(Region(
                page=number, rect=group["rect"], kind=kind, reason=reason,
                chars=group["chars"], text=group["text"],
            ))

        # Reading order is the order the cut produced, not the order the
        # regions happen to sit in. Sorting by top edge reads a two-column
        # page across rather than down: the bottom of the left column is
        # below the top of the right one, so the reader left the column
        # mid-sentence and came back to it a section later.
        furniture_regions.sort(key=lambda r: (r.rect[1], r.rect[0]))
        regions = body_regions + furniture_regions
        for position, region in enumerate(regions):
            region.order = position
        result[number] = regions

    if skip_references:
        _mark_references(result, document.page_count)
    return result
