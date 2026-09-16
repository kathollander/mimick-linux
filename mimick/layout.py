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
# A page with a generous bottom margin puts its footer above the band -- one
# sample journal sets it 85pt clear of the foot of the page, well inside where
# body text could be. So a last line left stranded this far below everything
# else on its page is treated as sitting in the band, and then has to earn the
# label the ordinary way: by repeating across pages, or by being a scrap.
FURNITURE_STRANDED = 30.0

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
FOOTNOTE = "footnote"        # the notes at the foot of a page

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

# A footnote opens with its number, then a space, then the note itself:
# "1 The terminology I use to refer to Indigenous peoples...". The number is
# the only marker Mimick looks for -- a footnote marked with * or a dagger is
# not found, and the document simply reads as it did before.
_FOOTNOTE_MARKER = re.compile(r"^(\d{1,3})\s+(?=\S)")
# Footnotes sit in the bottom of the page. This is deliberately generous: a
# page can be half footnotes, and the band only has to exclude the body text
# above them -- the marker and the smaller type do the real work.
FOOTNOTE_FROM_SHARE = 0.55
# Set smaller than the body, which is what makes a footnote a footnote. A
# region in ordinary body type that merely starts with a number is a numbered
# list or a heading, and is left alone.
FOOTNOTE_SMALLER = 0.5       # points below the document's usual size
# One numbered block low on one page is not a footnote apparatus.
FOOTNOTE_MIN = 2


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
            REFERENCES: "reference list", FOOTNOTE: "footnote",
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


def _strand_footer(blocks: list) -> list:
    """Move a footer stranded above the band into it, if the page has one.

    The lowest block on the page, if nothing else comes within
    ``FURNITURE_STRANDED`` of it, is where a footer sits whatever the margin.
    It is only moved to the edge band, not declared furniture outright: the
    repetition and scrap tests still have to agree, so a short closing line of
    text is safe.
    """
    if len(blocks) < 2:
        return blocks
    lowest = max(range(len(blocks)), key=lambda i: blocks[i][3])
    above = max(block[3] for index, block in enumerate(blocks)
                if index != lowest)
    block = blocks[lowest]
    if block[6] == BAND_MIDDLE and block[1] - above >= FURNITURE_STRANDED:
        blocks[lowest] = block[:6] + (BAND_EDGE,)
    return blocks


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


def _span_sizes(page) -> list[tuple[float, float, float, int]]:
    """Every run of text on a page as (centre x, centre y, type size, length).

    Region rectangles come from the block extraction, which does not carry a
    font size, so the sizes are matched back to regions by position. The extra
    pass costs a few hundredths of a second on a long document.
    """
    spans: list[tuple[float, float, float, int]] = []
    for block in page.get_text("dict").get("blocks", ()):
        for line in block.get("lines", ()):
            for span in line.get("spans", ()):
                text = span.get("text") or ""
                if not text.strip():
                    continue
                x0, y0, x1, y1 = span["bbox"]
                spans.append(((x0 + x1) / 2, (y0 + y1) / 2,
                              float(span.get("size") or 0.0), len(text)))
    return spans


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if not ordered:
        return 0.0
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _mark_footnotes(result: dict[int, list[Region]],
                    sizes: dict[int, list], heights: dict[int, float]) -> None:
    """Label the notes at the foot of each page, so the reader can skip them.

    Footnotes are read *after* the page they hang off, because they are their
    own regions at the bottom of it and reading order is region order. That is
    right for the page and wrong for the sentence: the voice finishes a
    paragraph, then reads a note belonging to something said two paragraphs
    ago. Nothing can put them back where they are referred to without cutting
    the body text mid-sentence, so the choice offered is whether to hear them
    at all.

    Three signals have to agree, because a false positive silences real text:
    the region begins with a number, it sits in the bottom of the page, and it
    is set smaller than the document's usual type. The numbers then have to run
    upwards through the document -- restarting at 1 on a page is allowed, as
    some journals number per page -- and there have to be at least two.
    """
    weighted: list[float] = []
    for page_spans in sizes.values():
        for _cx, _cy, size, length in page_spans:
            weighted.extend([size] * max(length, 1))
    body_size = _median(weighted)
    if body_size <= 0:
        return

    candidates: list[tuple[Region, int]] = []
    for number in sorted(result):
        height = heights.get(number) or 0.0
        page_spans = sizes.get(number) or []
        for region in result[number]:
            if region.kind != BODY:
                continue
            marker = _FOOTNOTE_MARKER.match(region.text)
            if marker is None:
                continue
            if not height or region.rect[1] < height * FOOTNOTE_FROM_SHARE:
                continue
            inside = [(size, length) for cx, cy, size, length in page_spans
                      if region.contains(cx, cy, pad=2.0)]
            if not inside:
                continue
            spread: list[float] = []
            for size, length in inside:
                spread.extend([size] * max(length, 1))
            if _median(spread) > body_size - FOOTNOTE_SMALLER:
                continue
            candidates.append((region, int(marker.group(1))))

    if len(candidates) < FOOTNOTE_MIN:
        return
    previous = 0
    for _region, marker in candidates:
        if marker <= previous and marker != 1:
            return
        previous = marker

    for region, _marker in candidates:
        region.kind = FOOTNOTE
        region.reason = "a footnote at the bottom of the page"


def _text_blocks(page) -> list[tuple[float, float, float, float, str]]:
    """The page's text blocks, with side-by-side ones pulled apart.

    MuPDF sometimes hands back a sidebar and the text beside it as a single
    block -- on the sample article the keyword list and the abstract come back
    together, and their lines alternate, so the page reads "Keywords The
    purpose of this article", then the second keyword, then the second line of
    the abstract. The XY cut cannot fix that, because by the time it sees the
    page the two columns are one rectangle.

    So before the cut, a block whose own lines fall into columns -- separated
    by a clear vertical gap that no line crosses, and standing side by side
    rather than one after the other -- is handed back as one block per column.
    Everything else comes back exactly as MuPDF gave it.
    """
    blocks: list[tuple[float, float, float, float, str]] = []
    for block in page.get_text("dict").get("blocks", ()):
        if block.get("type") != 0:
            continue
        lines = []
        for line in block.get("lines", ()):
            text = "".join(span.get("text") or "" for span in line.get("spans", ()))
            if text.strip():
                lines.append((line["bbox"], text))
        if not lines:
            continue
        for column in _columns(lines):
            x0 = min(bbox[0] for bbox, _t in column)
            y0 = min(bbox[1] for bbox, _t in column)
            x1 = max(bbox[2] for bbox, _t in column)
            y1 = max(bbox[3] for bbox, _t in column)
            text = "\n".join(t for _bbox, t in
                             sorted(column, key=lambda line: line[0][1]))
            blocks.append((x0, y0, x1, y1, text))
    blocks.sort(key=lambda block: (block[1], block[0]))
    return blocks


def _columns(lines: list) -> list[list]:
    """Split a block's lines into columns, or hand back the one block of them.

    Lines of an ordinary paragraph share a left margin, so they overlap and
    fall into a single column. Two columns are only accepted when they also
    overlap vertically: otherwise a heading above a short indented line would
    be split from the text it belongs to.
    """
    ordered = sorted(lines, key=lambda line: line[0][0])
    columns: list[list] = [[ordered[0]]]
    reach = ordered[0][0][2]
    for line in ordered[1:]:
        if line[0][0] - reach >= MIN_GAP_X:
            columns.append([])
        columns[-1].append(line)
        reach = max(reach, line[0][2])
    if len(columns) < 2:
        return [lines]
    spans = [(min(bbox[1] for bbox, _t in column),
              max(bbox[3] for bbox, _t in column)) for column in columns]
    for (top, bottom), (next_top, next_bottom) in zip(spans, spans[1:]):
        if min(bottom, next_bottom) - max(top, next_top) <= 0:
            return [lines]
    return columns


def analyse(document, skip_references: bool = True) -> dict[int, list[Region]]:
    """Group every page of a document into regions, in reading order."""
    pages: dict[int, list] = {}
    sizes: dict[int, list] = {}
    heights: dict[int, float] = {}
    for number in range(document.page_count):
        page = document.doc.load_page(number)
        height = page.rect.height
        heights[number] = height
        sizes[number] = _span_sizes(page)
        blocks = []
        for x0, y0, x1, y1, text in _text_blocks(page):
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
        pages[number] = _strand_footer(blocks)

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

    _mark_footnotes(result, sizes, heights)
    if skip_references:
        _mark_references(result, document.page_count)
    return result
