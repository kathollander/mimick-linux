"""Every highlight and note as a notes document, for reading outside Mimick.

A PDF full of highlights is only useful inside a PDF reader. This writes the
same marks as a document of their own -- Markdown, Word, OpenDocument or PDF --
keeping what a highlight is *for*: the passage, what you called it, and what
you said about it, under the page and section it came from. Kat asked for the
notes to stand on their own, apart from the lecture or book (23 September):

    "quoted passage" (p. 12)
    - the note

A passage that was a bulleted list in the document keeps one bullet a line
(``passage_lines``): the words a PDF gives for a highlight run the list's items
together into one paragraph, with the bullet glyphs left in the middle.

Sticky notes come in page order among the highlights, headed *Sticky note*,
with their bold, italics, underline, strikeout and sizes wherever the format
can hold them -- Markdown has no underline, and loses only that.

A notes document rather than a Word or OpenDocument copy of the document
itself: a highlight is an annotation on a rectangle of a page, and a flowing
document has no faithful place to put one. See PARITY.md, *Export notes*.

**Shared with the browser version** through tools/port.sh; its document worker
calls these same functions, so the same notes exported from either app are the
same file. tools/check_notes_export.py pins the format.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from xml.sax.saxutils import escape

from .annotations import COLOURS, _blocks_html, rich_blocks, rich_to_markdown

# How close two colours must be to count as the same one of Mimick's four.
# Matches _same_colour in ui/note_dialog.py.
_COLOUR_TOLERANCE = 0.02

# The formats Export notes offers: extension -> (description, media type).
FORMATS = {
    "docx": ("Word document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "odt": ("OpenDocument text", "application/vnd.oasis.opendocument.text"),
    "pdf": ("PDF document", "application/pdf"),
    "md": ("Markdown text", "text/markdown"),
}

# A bullet a PDF list was typeset with. The middle dot is not one -- it is
# what "Page 3 · Methods" is written with -- and neither is a hyphen, which
# means too many other things mid-line to cut at.
_BULLETS = "●•▪◦■□○◆◇►▸▹➢➤✓✔❖"
_BULLET_SPLIT = re.compile(r"\s+(?=[%s](?:\s|$))" % _BULLETS)
_BULLET_START = re.compile(r"^[%s]\s*" % _BULLETS)


def _flat(text: str) -> str:
    """One line, however the reader typed it -- notes.js's ``flat``."""
    return " ".join(str(text or "").split())


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _colour_name(colour) -> str | None:
    """Which of Mimick's four this is, or None for a colour from elsewhere."""
    for name, known in COLOURS:
        if all(abs(a - b) <= _COLOUR_TOLERANCE for a, b in zip(known, colour or ())):
            return name
    return None


def passage_lines(text: str) -> list[tuple[bool, str]]:
    """A highlighted passage as ``(is_bullet, words)`` lines.

    Its own line breaks are kept, so a poem keeps its shape, and a line is cut
    again before every bullet glyph, so a list that the PDF ran together into
    one paragraph comes out one item a line. The glyph itself is dropped: each
    format draws its own bullet.
    """
    out = []
    for line in str(text or "").split("\n"):
        for piece in _BULLET_SPLIT.split(line.strip()):
            bullet = bool(_BULLET_START.match(piece))
            words = _flat(_BULLET_START.sub("", piece))
            if words:
                out.append((bullet, words))
    return out


# -- what the document says, whatever it is written as -------------------------


@dataclass
class _Entry:
    page: int                                   # 1-based, as a reader counts
    lines: list[tuple[bool, str]]
    title: str = ""
    colour: str | None = None                   # named only when it tells you something
    notes: list[str] = field(default_factory=list)
    rich: str = ""                              # a sticky note's text; then lines is empty
    blocks: list = field(default_factory=list)  # ... as rich_blocks gives it


def _is_sticky(item) -> bool:
    return hasattr(item, "rich")


@dataclass
class _Notes:
    title: str
    summary: str
    groups: list[tuple[str, list[_Entry]]]


def _gather(title: str, name: str, items, section_for=None, today: date | None = None) -> _Notes:
    items = list(items)
    marks = [item for item in items if not _is_sticky(item)]
    stickies = [item for item in items if _is_sticky(item) and rich_blocks(item.rich)]
    items = [item for item in items if not _is_sticky(item) or item in stickies]
    written = sum(1 for item in marks if _flat(item.note))
    # Colours are named only where the reader used more than one of Mimick's
    # own: on a document highlighted all in yellow, saying "Yellow" under every
    # passage is noise that means nothing.
    colours = {found for found in (_colour_name(item.colour) for item in marks) if found}
    when = (today or date.today()).strftime("%-d %B %Y")
    counted = f"{_plural(len(marks), 'highlight')}, {written} with notes"
    if stickies:
        counted += f", {_plural(len(stickies), 'sticky note')}"
    summary = f"{name} · {counted} · exported from Mimick on {when}"
    groups: list[tuple[str, list[_Entry]]] = []
    for item in items:
        section = section_for(item) if section_for is not None else None
        heading = f"Page {item.page + 1}" + (f" · {section}" if section else "")
        if not groups or groups[-1][0] != heading:
            groups.append((heading, []))
        if _is_sticky(item):
            groups[-1][1].append(_Entry(page=item.page + 1, lines=[], title="Sticky note",
                                        rich=item.rich, blocks=rich_blocks(item.rich)))
            continue
        # Each line of a note is a point of its own, as it would be on paper.
        notes = [_flat(line) for line in (item.note or "").split("\n") if _flat(line)]
        groups[-1][1].append(_Entry(
            page=item.page + 1, lines=passage_lines(item.text), title=_flat(item.title),
            colour=_colour_name(item.colour) if len(colours) > 1 else None, notes=notes))
    return _Notes(f"Notes: {title}", summary, groups)


def _quoted(entry: _Entry) -> list[tuple[bool, str]]:
    """The passage in quotation marks with its page after it: “…” (p. 12)."""
    if entry.rich:
        return []
    lines = list(entry.lines) or [(False, "")]
    first_bullet, first = lines[0]
    lines[0] = (first_bullet, "“" + first)
    last_bullet, last = lines[-1]
    lines[-1] = (last_bullet, f"{last}” (p. {entry.page})")
    return lines


# -- Markdown -------------------------------------------------------------------


def notes_markdown(title: str, name: str, items, section_for=None,
                   today: date | None = None) -> str:
    """Highlights and notes as Markdown.

    ``items`` are ``Annotation``s in the order they should appear -- the store
    keeps them by page and then down the page, which is reading order.
    ``section_for(item)`` gives the heading an item sits under, or None; the
    caller works that out, since only it knows the document's outline.
    """
    notes = _gather(title, name, items, section_for, today)
    lines = [f"# {notes.title}", "", notes.summary]
    for heading, entries in notes.groups:
        lines += ["", f"## {heading}"]
        for entry in entries:
            if entry.title:
                lines += ["", f"**{entry.title}**"]
            # The passage as a block quote, one line per line of it, so a poem
            # keeps its shape; a list inside it is a Markdown list, set off by
            # a blank quote line so that it renders as one.
            if not entry.rich:
                lines.append("")
            was_bullet = False
            for bullet, words in _quoted(entry):
                if bullet and not was_bullet and lines[-1] != "":
                    lines.append(">")
                lines.append(f"> - {words}" if bullet else f"> {words}")
                was_bullet = bullet
            if entry.rich:
                was_item = None
                for item, words in rich_to_markdown(entry.rich):
                    if not item or was_item is not True:
                        lines.append("")
                    if words or item:
                        lines.append(f"- {words}" if item else words)
                    was_item = item
                continue
            if entry.colour:
                lines += ["", f"*{entry.colour}*"]
            if entry.notes:
                lines += [""] + [f"- {note}" for note in entry.notes]
    return "\n".join(lines) + "\n"


# -- HTML, which is how the PDF is made ------------------------------------------


_CSS = ("body { font-family: sans-serif; font-size: 11pt; line-height: 1.4; } "
        "h1 { font-size: 18pt; margin: 0 0 4pt 0; } "
        "h2 { font-size: 13pt; margin: 16pt 0 4pt 0; } "
        "p { margin: 0 0 6pt 0; } "
        ".summary { font-size: 9pt; color: #666666; margin-bottom: 10pt; } "
        ".title { font-weight: bold; margin: 10pt 0 2pt 0; } "
        ".first { margin-top: 10pt; } "
        ".quote { font-style: italic; margin: 0 0 2pt 18pt; } "
        "ul { margin: 0 0 6pt 0; } "
        "ul.inquote { margin-left: 18pt; font-style: italic; } "
        ".colour { font-size: 9pt; color: #666666; margin-left: 18pt; } "
        "ul.notes { margin-bottom: 8pt; } "
        ".sticky p { margin: 0 0 3pt 18pt; } .sticky ul { margin-left: 18pt; }")


def _html(notes: _Notes) -> str:
    out = [f"<h1>{html.escape(notes.title)}</h1>", f'<p class="summary">{html.escape(notes.summary)}</p>']
    for heading, entries in notes.groups:
        out.append(f"<h2>{html.escape(heading)}</h2>")
        for entry in entries:
            if entry.title:
                out.append(f'<p class="title">{html.escape(entry.title)}</p>')
            listing = False
            for number, (bullet, words) in enumerate(_quoted(entry)):
                opens = number == 0 and not entry.title
                if bullet and not listing:
                    out.append(f'<ul class="inquote{" first" if opens else ""}">')
                elif not bullet and listing:
                    out.append("</ul>")
                listing = bullet
                out.append(f"<li>{html.escape(words)}</li>" if bullet
                           else f'<p class="quote{" first" if opens else ""}">{html.escape(words)}</p>')
            if listing:
                out.append("</ul>")
            if entry.rich:
                out.append(f'<div class="sticky">{_blocks_html(entry.blocks)}</div>')
            if entry.colour:
                out.append(f'<p class="colour">{html.escape(entry.colour)}</p>')
            if entry.notes:
                out.append('<ul class="notes">' + "".join(f"<li>{html.escape(n)}</li>" for n in entry.notes) + "</ul>")
    return "".join(out)


def notes_pdf(title: str, name: str, items, section_for=None, today: date | None = None) -> bytes:
    from .convert import _story_pdf       # MuPDF; the other formats need nothing
    notes = _gather(title, name, items, section_for, today)
    return _story_pdf(_html(notes), _CSS, notes.title, "Mimick, Export notes")


# -- Word ---------------------------------------------------------------------------
# The fewest parts Word, LibreOffice and Google Docs all open: the document,
# its styles (so the headings are real headings, and show in a navigation
# pane), and two bullet lists. Written by hand rather than with a library,
# because the browser version runs this in Pyodide with no extras.

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _w_run(text: str, bold=False, italic=False, size=None, colour=None,
           underline=False, strike=False) -> str:
    props = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") \
        + ("<w:strike/>" if strike else "") \
        + (f'<w:color w:val="{colour}"/>' if colour else "") + (f'<w:sz w:val="{size}"/>' if size else "") \
        + ('<w:u w:val="single"/>' if underline else "")
    return (f"<w:r>{f'<w:rPr>{props}</w:rPr>' if props else ''}"
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def _w_para(text: str, style: str | None = None, bullets: int | None = None, first=False, **run) -> str:
    # `first` opens an entry: a gap above it, so one highlight's notes do not
    # run into the next one's quotation.
    props = (f'<w:pStyle w:val="{style}"/>' if style else "") \
        + (f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{bullets}"/></w:numPr>' if bullets else "") \
        + ('<w:spacing w:before="200"/>' if first else "")
    return f"<w:p>{f'<w:pPr>{props}</w:pPr>' if props else ''}{_w_run(text, **run)}</w:p>"


def _w_sticky(blocks) -> list[str]:
    """A sticky note's lines as Word paragraphs, a run per change of style."""
    out = []
    for item, runs in blocks:
        props = (f'<w:pStyle w:val="ListParagraph"/><w:numPr><w:ilvl w:val="0"/>'
                 f'<w:numId w:val="{_NOTE_LIST}"/></w:numPr>' if item else '<w:pStyle w:val="ListParagraph"/>')
        words = "".join(_w_run(text, bold=style.bold, italic=style.italic, underline=style.underline,
                               strike=style.strike, size=round(style.size * 2) if style.size else None)
                        for text, style in runs)
        out.append(f"<w:p><w:pPr>{props}</w:pPr>{words}</w:p>")
    return out


_DOCX_STYLES = _XML + f"""<w:styles {_W}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri" w:eastAsia="Calibri"/>
<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-CA"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="60"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="320" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="40"/><w:ind w:left="360"/></w:pPr><w:rPr><w:i/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="40"/></w:pPr></w:style>
</w:styles>"""

# A note's points, and the points of a list quoted from the document, which
# sit further in, under the quotation they belong to.
_NOTE_LIST, _QUOTE_LIST = 1, 2


def _w_bullets(num_id: int, left: int) -> tuple[str, str]:
    abstract = (f'<w:abstractNum w:abstractNumId="{num_id}"><w:multiLevelType w:val="singleLevel"/>'
                f'<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/>'
                f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{left}" w:hanging="300"/></w:pPr></w:lvl></w:abstractNum>')
    return abstract, f'<w:num w:numId="{num_id}"><w:abstractNumId w:val="{num_id}"/></w:num>'


_LISTS = [_w_bullets(_NOTE_LIST, 360), _w_bullets(_QUOTE_LIST, 720)]
# Every abstractNum has to come before any num, or Word calls the file corrupt.
_DOCX_NUMBERING = (_XML + f"<w:numbering {_W}>" + "".join(a for a, _ in _LISTS)
                   + "".join(n for _, n in _LISTS) + "</w:numbering>")

_DOCX_TYPES = _XML + """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_DOCX_RELS = _XML + """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOCX_DOC_RELS = _XML + """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>"""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _zip(parts: list[tuple[str, str]], stored_first: bool = False) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for number, (name, text) in enumerate(parts):
            # OpenDocument's mimetype must come first and uncompressed, so a
            # program can tell what the file is from its first bytes.
            kind = zipfile.ZIP_STORED if stored_first and number == 0 else zipfile.ZIP_DEFLATED
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), text.encode("utf-8"),
                       compress_type=kind)
    return out.getvalue()


def notes_docx(title: str, name: str, items, section_for=None, today: date | None = None) -> bytes:
    notes = _gather(title, name, items, section_for, today)
    body = [_w_para(notes.title, "Title"), _w_para(notes.summary, size=18, colour="666666")]
    for heading, entries in notes.groups:
        body.append(_w_para(heading, "Heading2"))
        for entry in entries:
            if entry.title:
                body.append(_w_para(entry.title, bold=True, first=True))
            body += _w_sticky(entry.blocks)
            for number, (bullet, words) in enumerate(_quoted(entry)):
                first = number == 0 and not entry.title
                body.append(_w_para(words, "ListParagraph", _QUOTE_LIST, first=first, italic=True) if bullet
                            else _w_para(words, "Quote", first=first))
            if entry.colour:
                body.append(_w_para(entry.colour, "Quote", size=18, colour="666666"))
            for note in entry.notes:
                body.append(_w_para(note, "ListParagraph", _NOTE_LIST))
    document = (_XML + f"<w:document {_W}><w:body>" + "".join(body)
                + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                  '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>'
                  "</w:sectPr></w:body></w:document>")
    core = (_XML + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{escape(notes.title)}</dc:title><dc:creator>Mimick</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{_stamp()}</dcterms:created></cp:coreProperties>')
    return _zip([("[Content_Types].xml", _DOCX_TYPES), ("_rels/.rels", _DOCX_RELS),
                 ("word/_rels/document.xml.rels", _DOCX_DOC_RELS), ("word/document.xml", document),
                 ("word/styles.xml", _DOCX_STYLES), ("word/numbering.xml", _DOCX_NUMBERING),
                 ("docProps/core.xml", core)])


# -- OpenDocument ---------------------------------------------------------------------

_ODF_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
           'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
           'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
           'xmlns:dc="http://purl.org/dc/elements/1.1/" '
           'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" office:version="1.3"')


def _odt_list(style: str, left: str) -> str:
    return (f'<text:list-style style:name="{style}"><text:list-level-style-bullet text:level="1" text:bullet-char="•">'
            f'<style:list-level-properties text:list-level-position-and-space-mode="label-alignment">'
            f'<style:list-level-label-alignment text:label-followed-by="listtab" text:list-tab-stop-position="{left}" '
            f'fo:text-indent="-0.2in" fo:margin-left="{left}"/>'
            f"</style:list-level-properties></text:list-level-style-bullet></text:list-style>")


_ODT_STYLES = _XML + f"""<office:document-styles {_ODF_NS}><office:styles>
<style:default-style style:family="paragraph"><style:paragraph-properties fo:margin-bottom="0.08in" fo:line-height="115%"/>
<style:text-properties fo:font-family="'Liberation Sans', Arial, sans-serif" fo:font-size="11pt" fo:language="en" fo:country="CA"/></style:default-style>
<style:style style:name="Standard" style:family="paragraph" style:class="text"/>
<style:style style:name="Title" style:family="paragraph" style:parent-style-name="Standard" style:class="chapter">
<style:paragraph-properties fo:margin-bottom="0.04in"/><style:text-properties fo:font-size="18pt" fo:font-weight="bold"/></style:style>
<style:style style:name="Heading_20_2" style:display-name="Heading 2" style:family="paragraph" style:parent-style-name="Standard"
 style:default-outline-level="2" style:class="text"><style:paragraph-properties fo:margin-top="0.22in" fo:margin-bottom="0.06in" fo:keep-with-next="always"/>
<style:text-properties fo:font-size="13pt" fo:font-weight="bold"/></style:style>
<style:style style:name="Summary" style:family="paragraph" style:parent-style-name="Standard">
<style:paragraph-properties fo:margin-bottom="0.14in"/><style:text-properties fo:font-size="9pt" fo:color="#666666"/></style:style>
<style:style style:name="Entry_20_Title" style:display-name="Entry Title" style:family="paragraph" style:parent-style-name="Standard">
<style:paragraph-properties fo:margin-top="0.1in" fo:margin-bottom="0.03in"/><style:text-properties fo:font-weight="bold"/></style:style>
<style:style style:name="Quotations" style:family="paragraph" style:parent-style-name="Standard" style:class="html">
<style:paragraph-properties fo:margin-left="0.25in" fo:margin-bottom="0.03in"/><style:text-properties fo:font-style="italic"/></style:style>
<style:style style:name="Quotations_20_First" style:display-name="Quotations First" style:family="paragraph" style:parent-style-name="Quotations">
<style:paragraph-properties fo:margin-top="0.14in"/></style:style>
<style:style style:name="Colour" style:family="paragraph" style:parent-style-name="Quotations">
<style:text-properties fo:font-size="9pt" fo:color="#666666"/></style:style>
<style:style style:name="List_20_Item" style:display-name="List Item" style:family="paragraph" style:parent-style-name="Standard">
<style:paragraph-properties fo:margin-bottom="0.03in"/></style:style>
<style:style style:name="Quoted_20_Item" style:display-name="Quoted Item" style:family="paragraph" style:parent-style-name="List_20_Item">
<style:text-properties fo:font-style="italic"/></style:style>
{_odt_list("Notes", "0.25in")}{_odt_list("Quoted", "0.5in")}
</office:styles><office:automatic-styles><style:page-layout style:name="A4">
<style:page-layout-properties fo:page-width="8.268in" fo:page-height="11.693in" fo:margin-top="1in" fo:margin-bottom="1in" fo:margin-left="1in" fo:margin-right="1in"/>
</style:page-layout></office:automatic-styles>
<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="A4"/></office:master-styles></office:document-styles>"""

_ODT_MANIFEST = _XML + """<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">
<manifest:file-entry manifest:full-path="/" manifest:version="1.3" manifest:media-type="application/vnd.oasis.opendocument.text"/>
<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>
</manifest:manifest>"""


def _odt_p(style: str, words: str) -> str:
    return f'<text:p text:style-name="{style}">{escape(words)}</text:p>'


def _odt_style_name(style) -> str:
    return "T_" + "".join("1" if flag else "0" for flag in (style.bold, style.italic, style.underline,
                                                            style.strike)) + (
        f"_{style.size:g}".replace(".", "p") if style.size else "")


def _odt_text_style(style) -> str:
    props = (' fo:font-weight="bold"' if style.bold else "") + (' fo:font-style="italic"' if style.italic else "") \
        + (' style:text-underline-style="solid" style:text-underline-width="auto" style:text-underline-color="font-color"'
           if style.underline else "") \
        + (' style:text-line-through-style="solid"' if style.strike else "") \
        + (f' fo:font-size="{style.size:g}pt"' if style.size else "")
    return (f'<style:style style:name="{_odt_style_name(style)}" style:family="text">'
            f"<style:text-properties{props}/></style:style>")


def _odt_sticky(blocks, used: dict) -> list[str]:
    """A sticky note's lines as paragraphs, and a list for its list items;
    each styled run a span whose style goes in ``used``."""
    out, listed = [], []

    def words(runs) -> str:
        spans = []
        for text, style in runs:
            if style.key() == (False, False, False, False, None):
                spans.append(escape(text))
            else:
                used.setdefault(_odt_style_name(style), _odt_text_style(style))
                spans.append(f'<text:span text:style-name="{_odt_style_name(style)}">{escape(text)}</text:span>')
        return "".join(spans)

    for item, runs in list(blocks) + [(False, None)]:
        if item:
            listed.append(f'<text:list-item><text:p text:style-name="List_20_Item">{words(runs)}</text:p></text:list-item>')
            continue
        if listed:
            out.append('<text:list text:style-name="Notes">' + "".join(listed) + "</text:list>")
            listed = []
        if runs is not None:
            out.append(f'<text:p text:style-name="List_20_Item">{words(runs)}</text:p>')
    return out


def _odt_items(style: str, paragraph: str, lines: list[str]) -> str:
    return (f'<text:list text:style-name="{style}">'
            + "".join(f"<text:list-item>{_odt_p(paragraph, words)}</text:list-item>" for words in lines)
            + "</text:list>")


def notes_odt(title: str, name: str, items, section_for=None, today: date | None = None) -> bytes:
    notes = _gather(title, name, items, section_for, today)
    body = [f'<text:h text:style-name="Title" text:outline-level="1">{escape(notes.title)}</text:h>',
            _odt_p("Summary", notes.summary)]
    spans: dict[str, str] = {}
    for heading, entries in notes.groups:
        body.append(f'<text:h text:style-name="Heading_20_2" text:outline-level="2">{escape(heading)}</text:h>')
        for entry in entries:
            if entry.title:
                body.append(_odt_p("Entry_20_Title", entry.title))
            body += _odt_sticky(entry.blocks, spans)
            # Quoted list items gather into one list; a plain line ends it.
            run: list[str] = []
            for number, (bullet, words) in enumerate(_quoted(entry) + [(False, None)]):
                if bullet:
                    run.append(words)
                    continue
                if run:
                    body.append(_odt_items("Quoted", "Quoted_20_Item", run))
                    run = []
                if words is not None:
                    opens = number == 0 and not entry.title
                    body.append(_odt_p("Quotations_20_First" if opens else "Quotations", words))
            if entry.colour:
                body.append(_odt_p("Colour", entry.colour))
            if entry.notes:
                body.append(_odt_items("Notes", "List_20_Item", entry.notes))
    content = (_XML + f"<office:document-content {_ODF_NS}>"
               + (f"<office:automatic-styles>{''.join(spans.values())}</office:automatic-styles>" if spans else "")
               + "<office:body><office:text>"
               + "".join(body) + "</office:text></office:body></office:document-content>")
    meta = (_XML + f"<office:document-meta {_ODF_NS}><office:meta><dc:title>{escape(notes.title)}</dc:title>"
            f"<meta:generator>Mimick</meta:generator><meta:creation-date>{_stamp()[:-1]}</meta:creation-date>"
            "</office:meta></office:document-meta>")
    return _zip([("mimetype", FORMATS["odt"][1]), ("META-INF/manifest.xml", _ODT_MANIFEST),
                 ("content.xml", content), ("styles.xml", _ODT_STYLES), ("meta.xml", meta)],
                stored_first=True)


def notes_file(kind: str, title: str, name: str, items, section_for=None,
               today: date | None = None) -> bytes:
    """The notes as a file of ``kind``, one of the keys of ``FORMATS``."""
    if kind == "md":
        return notes_markdown(title, name, items, section_for, today).encode("utf-8")
    make = {"docx": notes_docx, "odt": notes_odt, "pdf": notes_pdf}.get(kind)
    if make is None:
        raise ValueError(f"notes cannot be exported as .{kind}")
    return make(title, name, items, section_for, today)
