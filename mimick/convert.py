"""Open a document that is not a PDF by laying it out as one.

From then on each *is* a PDF, as far as the rest of Mimick is concerned: the
same reading, highlights, notes, Find, contents and Save a copy, with no other
part of the app needing to know where it came from. A ``.txt`` keeps its line
breaks as written, so a poem or a list reads as it looks, and a blank line
starts a paragraph. Word, EPUB, HTML and FictionBook are MuPDF's own doing --
it lays them out as it would a web page -- while ``.odt`` and ``.md`` are
turned into HTML here and set with a ``Story``, an ``.rtf`` is stripped back
to its words, and a slide deck is drawn a page per slide by ``slides.py``.
Headings become the contents panel's entries.

Images, footnotes and complicated tables come out rough. Lists lose their
bullets in Word files and tables lose their borders. This is a reader: none of
it is editable, and nothing is ever written back to the file you opened.

Shared with the browser version through tools/port.sh, so both lay a document
out the same way and a set of notes means the same thing in either.
"""

from __future__ import annotations

import hashlib
import html
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pymupdf

from . import slides

# What can be opened this way, and what to call one when something goes wrong.
# This is what fills the Open dialog and what drag and drop will accept, so a
# kind missing here cannot be opened however well the code below would cope.
CONVERTIBLE = {".txt": "a text file", ".md": "a Markdown file",
               ".html": "a web page", ".htm": "a web page",
               ".xhtml": "a web page", ".rtf": "a Rich Text file",
               ".fb2": "a FictionBook", ".docx": "a Word document",
               ".odt": "an OpenDocument text file", ".epub": "an EPUB book",
               ".pptx": "a PowerPoint presentation",
               ".ppsx": "a PowerPoint slide show",
               ".odp": "an Impress presentation"}

# Kinds that are another kind under a second name. Each is still named for
# itself when something goes wrong -- a person who opened a .ppsx should be
# told about a slide show, not a presentation -- but only the right-hand side
# is ever converted, so .htm and .html cannot drift apart.
ALIASES = {"markdown": "md", "htm": "html", "xhtml": "html", "ppsx": "pptx"}


def converted_pdf(path, cache_dir, progress=None) -> Path:
    """``path`` laid out as a PDF, kept under ``cache_dir`` and made only once.

    Named for the file it came from and the content it had, so opening the same
    document again finds the same PDF -- which is what brings its highlights and
    notes back with it, since those hang off the PDF's own path. Edit the
    original and you get a new PDF and a clean sheet, the old notes staying with
    the version they were made on. ``progress`` is handed to ``document_to_pdf``.
    """
    path = Path(path)
    kind = path.suffix.lower()
    if kind not in CONVERTIBLE:
        raise ValueError(f"Mimick cannot open {kind or 'that kind of'} files")
    data = path.read_bytes()
    stamp = hashlib.sha256(data).hexdigest()[:16]
    folder = Path(cache_dir) / "converted"
    folder.mkdir(parents=True, exist_ok=True)
    # The stem is kept readable so the folder can be understood by a person
    # looking into it, and the stamp makes it unique.
    out = folder / f"{path.stem[:60]}-{stamp}.pdf"
    if out.exists() and out.stat().st_size:
        return out
    title = path.stem
    if kind == ".txt":
        made = text_to_pdf(_read_text(data), title)
    else:
        made = document_to_pdf(data, kind.lstrip("."), title, progress)
    # Written beside and moved into place, so a half-written PDF is never left
    # behind for the next open to find and trust.
    partial = out.with_suffix(".part")
    partial.write_bytes(made)
    partial.replace(out)
    return out


def _read_text(data: bytes) -> str:
    """A text file's characters, whatever it was saved as.

    UTF-8 first, since that is what a text file is now; then UTF-16, which is
    what Windows Notepad used to write and still labels with a byte-order mark;
    then Latin-1, which cannot fail and leaves the odd wrong character rather
    than refusing to open a reading at all.
    """
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("latin-1", "replace")


def text_to_pdf(text: str, title: str, creator: str = "Mimick, from a text file") -> bytes:
    """``text`` set on A4 pages, one-inch margins, 11pt, titled ``title``."""
    paragraphs = [p for p in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n") if p.strip()]
    if not paragraphs:
        raise ValueError("the file has no text in it")
    body = "".join(f"<p>{html.escape(p.strip(chr(10)))}</p>" for p in paragraphs)
    css = ("body { font-family: sans-serif; font-size: 11pt; line-height: 1.45; } "
           "p { white-space: pre-wrap; margin: 0 0 9pt 0; }")
    return _story_pdf(body, css, title, creator)


def _page_limit(body: str) -> int:
    """Far more pages than ``body`` could need, as an end for a story that has none.

    MuPDF's ``Story`` can be handed a document it will not finish: from some
    point on, ``place`` asks for another page, puts nothing on it, and still
    says there is more to come -- for ever. Left alone it fills memory, 400
    empty pages in half a second, and in the browser that is the reading worker
    gone. This is the backstop; ``_story_pdf`` handles the usual cause.

    A full A4 page at 11pt holds around 3000 characters, and even a sparse
    document of headings and one-line list items holds around 500. A page for
    every 250 characters is several times more than either needs and still
    ends, soon enough that the retry below is not a long wait.
    """
    return max(50, len(re.sub(r"<[^>]+>", " ", body)) // 250)


_TABLE = re.compile(r"<table>.*?</table>", re.S)
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)


def _flatten_tables(body: str) -> str:
    """Every table row as a paragraph of its cells, and the table itself gone.

    What a story that will not finish is asked to lay out instead. A table it
    cannot fit is the cause found here -- a real 125 KB Markdown file of release
    notes, whose tables run to ten columns -- and laying one out as rows of
    words keeps every word rather than losing the two fifths of the document
    that came after it. For a reader that is no loss: a ten-column table read
    aloud is a jumble of headings and numbers either way, and this at least
    keeps each row together.
    """
    def row(match):
        cells = [cell.strip() for cell in _CELL.findall(match.group(1))]
        kept = " — ".join(cell for cell in cells if cell)
        return f"<p>{kept}</p>" if kept else ""
    return _TABLE.sub(lambda m: _ROW.sub(row, m.group(0)).replace("<table>", "").replace("</table>", ""), body)


def _drop_blank_tail(pdf) -> None:
    """Blank pages left at the end by a story that would not say it had finished.

    Only the end: a blank page in the middle is one the document asked for.
    """
    last = pdf.page_count - 1
    while last > 0 and not pdf[last].get_text().strip():
        last -= 1
    if last < pdf.page_count - 1:
        pdf.delete_pages(last + 1, pdf.page_count - 1)


def _lay_out(body: str, css: str) -> tuple[bytes, list, bool]:
    """``body`` placed on A4 pages: the PDF, its headings, and whether it finished."""
    story = pymupdf.Story(html=body, user_css=css)
    out = io.BytesIO()
    writer = pymupdf.DocumentWriter(out)
    page = pymupdf.paper_rect("a4")
    where = page + (72, 72, -72, -72)
    toc = []
    def heading(position):
        if position.heading and position.open_close & 1 and position.text:
            toc.append([position.heading, " ".join(position.text.split()), number + 1, position.rect[1]])
    more, number, limit = True, 0, _page_limit(body)
    while more and number < limit:
        device = writer.begin_page(page)
        more, _ = story.place(where)
        story.element_positions(heading)
        story.draw(device)
        writer.end_page()
        number += 1
    writer.close()
    return out.getvalue(), toc, not more


def _story_pdf(body: str, css: str, title: str, creator: str) -> bytes:
    """HTML set on A4 pages with one-inch margins; its headings are the outline.

    When MuPDF will not finish the document it is asked again with the tables
    laid out as rows of words, which is the one thing found to stop it. Silently
    giving a reader the first three fifths of their document would be the worse
    answer of the two.
    """
    made, toc, finished = _lay_out(body, css)
    if not finished:
        flattened, flat_toc, flat_finished = _lay_out(_flatten_tables(body), css)
        if flat_finished:
            made, toc = flattened, flat_toc
    with pymupdf.open(stream=made, filetype="pdf") as pdf:
        _drop_blank_tail(pdf)
        pdf.set_metadata({"title": title, "creator": creator})
        # An entry pointing past the pages that are left would be a contents
        # line that goes nowhere, so the trimmed pages take their headings with
        # them -- there are none on a blank page anyway.
        _set_toc(pdf, [[lvl, t, p, {"kind": pymupdf.LINK_GOTO, "page": p - 1, "to": pymupdf.Point(72, y)}]
                       for lvl, t, p, y in toc if p <= pdf.page_count])
        return pdf.tobytes(garbage=3, deflate=True)


def _set_toc(doc, toc: list) -> None:
    """Set an outline. A document may skip levels (a Heading 2 with no Heading 1
    before it); an outline may not, so a skipped level is closed up."""
    fixed, last = [], 0
    for entry in toc:
        level = max(1, min(entry[0], last + 1))
        fixed.append([level, *entry[1:]])
        last = level
    if fixed:
        doc.set_toc(fixed)


def _pointing(pdf, level: int, text: str, page: int) -> list:
    """An outline entry pointing at its heading on the page, found by its words, or
    at the top of the page when they cannot be found."""
    if not 0 < page <= pdf.page_count:
        return [level, text, -1]
    hits = pdf[page - 1].search_for(text[:60]) if text.strip() else []
    if not hits:
        return [level, text, page]
    return [level, text, page, {"kind": pymupdf.LINK_GOTO, "page": page - 1, "to": pymupdf.Point(hits[0].x0, hits[0].y0)}]


_ODT = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
      "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
      "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0"}
_T = "{%s}" % _ODT["text"]
_TB = "{%s}" % _ODT["table"]


def _odt_html(data: bytes) -> tuple[str, str]:
    """An .odt's text as simple HTML -- headings, paragraphs, lists, tables --
    and its own title. Footnotes are left out, as the reading cleanup would."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("content.xml"))
        try:
            meta = ET.fromstring(z.read("meta.xml"))
            name = (meta.findtext(".//{http://purl.org/dc/elements/1.1/}title") or "").strip()
        except (KeyError, ET.ParseError):
            name = ""
    body = root.find("office:body/office:text", _ODT)
    if body is None:
        raise ValueError("this is not an OpenDocument text file")
    def inline(el):
        out = [html.escape(el.text or "")]
        for child in el:
            tag = child.tag
            if tag == _T + "s":
                out.append(" " * int(child.get(_T + "c", "1")))
            elif tag == _T + "tab":
                out.append("\t")
            elif tag == _T + "line-break":
                out.append("<br>")
            elif tag == _T + "note":
                pass
            else:
                out.append(inline(child))
            out.append(html.escape(child.tail or ""))
        return "".join(out)
    def block(el):
        tag = el.tag
        if tag == _T + "h":
            level = min(6, max(1, int(el.get(_T + "outline-level", "1"))))
            return f"<h{level}>{inline(el)}</h{level}>"
        if tag == _T + "p":
            return f"<p>{inline(el)}</p>"
        if tag == _T + "list":
            items = []
            for item in el:
                if item.tag in (_T + "list-item", _T + "list-header"):
                    items.append("<li>" + "".join(block(c) for c in item) + "</li>")
            return "<ul>" + "".join(items) + "</ul>"
        if tag == _T + "section":
            return "".join(block(c) for c in el)
        if tag == _TB + "table":
            rows = []
            for row in el.iter(_TB + "table-row"):
                cells = "".join("<td>" + "".join(block(c) for c in cell) + "</td>" for cell in row.findall(_TB + "table-cell"))
                rows.append(f"<tr>{cells}</tr>")
            return "<table>" + "".join(rows) + "</table>"
        return ""
    return "".join(block(el) for el in body), name


# -- Markdown ---------------------------------------------------------------------
#
# Enough of Markdown to read a file written in it, and no more: there is no
# library here that both apps could share, and a reader only needs the words in
# the right order with the headings marked. What a fuller converter would add --
# raw HTML blocks, footnote definitions, reference-style links -- is dropped
# rather than shown as its source, which is the one thing a reading must not do.

_MD_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*\S*\s*$")
_MD_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_RULE = re.compile(r"^ {0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$")
_MD_BULLET = re.compile(r"^( *)[-*+]\s+(.*)$")
_MD_NUMBER = re.compile(r"^( *)\d{1,9}[.)]\s+(.*)$")
_MD_QUOTE = re.compile(r"^ {0,3}>\s?(.*)$")
_MD_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
_MD_ROW = re.compile(r"^\s*\|.*\|\s*$")
_MD_SEPARATOR = re.compile(r"^\s*\|[\s:|-]*-[\s:|-]*\|\s*$")

_MD_SPAN = re.compile(r"(`+)(.+?)\1", re.S)
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_AUTOLINK = re.compile(r"&lt;((?:https?|mailto):[^&\s]+)&gt;")
_MD_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)
_MD_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
_MD_ITALIC = re.compile(r"(?<![\w*_])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*_])", re.S)


def _front_matter(source: str) -> tuple[str, str]:
    """``source`` without its YAML front matter, and the ``title:`` it gave."""
    lines = source.split("\n")
    if not lines or lines[0].strip() != "---":
        return source, ""
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            title = ""
            for line in lines[1:i]:
                found = re.match(r"\s*title\s*:\s*(.+?)\s*$", line)
                if found:
                    title = found.group(1).strip().strip("\"'")
                    break
            return "\n".join(lines[i + 1:]), title
    return source, ""          # an opening --- with no close is a rule, not matter


def _markdown_html(source: str) -> tuple[str, str]:
    """A Markdown file as simple HTML, and the title to give it.

    The title is the ``title:`` of its YAML front matter if it has any, else its
    first level-one heading, which is where a Markdown file usually keeps it.
    """
    source, title = _front_matter(source.replace("\r\n", "\n").replace("\r", "\n"))
    body = _md_blocks(source.split("\n"))
    if not title:
        first = re.search(r"<h1>(.*?)</h1>", body, re.S)
        title = re.sub(r"<[^>]+>", "", first.group(1)).strip() if first else ""
    return body, title


def _md_blocks(lines: list[str]) -> str:
    """A run of Markdown lines as HTML. Called again for what nests inside a
    list item or a quote, so those carry paragraphs and lists of their own."""
    out: list[str] = []
    para: list[str] = []
    i, count = 0, len(lines)

    def flush() -> None:
        if para:
            out.append(f"<p>{_md_inline(' '.join(para))}</p>")
            para.clear()

    while i < count:
        line = lines[i]
        fence = _MD_FENCE.match(line)
        if fence:
            flush()
            closing = re.compile(r"^ {0,3}%s{%d,}\s*$" % (re.escape(fence.group(1)[0]), len(fence.group(1))))
            i += 1
            block: list[str] = []
            while i < count and not closing.match(lines[i]):
                block.append(lines[i])
                i += 1
            i += 1                                     # the closing fence, or the end
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        heading = _MD_HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_md_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if para and _MD_SETEXT.match(line):            # a heading underlined instead
            level = 1 if line.strip()[0] == "=" else 2
            out.append(f"<h{level}>{_md_inline(' '.join(para))}</h{level}>")
            para.clear()
            i += 1
            continue
        if _MD_RULE.match(line):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if _MD_QUOTE.match(line):
            flush()
            quoted: list[str] = []
            while i < count and (_MD_QUOTE.match(lines[i]) or (quoted and lines[i].strip())):
                found = _MD_QUOTE.match(lines[i])
                quoted.append(found.group(1) if found else lines[i])
                i += 1
            out.append("<blockquote>" + _md_blocks(quoted) + "</blockquote>")
            continue
        bullet = _MD_BULLET.match(line) or _MD_NUMBER.match(line)
        if bullet:
            flush()
            made, i = _md_list(lines, i, len(bullet.group(1)))
            out.append(made)
            continue
        if (not para and _MD_ROW.match(line) and i + 1 < count
                and _MD_SEPARATOR.match(lines[i + 1])):
            head = _md_cells(line)
            i += 2
            rows = []
            while i < count and _MD_ROW.match(lines[i]):
                rows.append(_md_cells(lines[i]))
                i += 1
            out.append(_md_table(head, rows))
            continue
        if not para and line.startswith("    "):       # an indented code block
            block = []
            while i < count and (line.startswith("    ") or not line.strip()):
                block.append(line[4:])
                i += 1
                line = lines[i] if i < count else ""
            out.append("<pre>" + html.escape("\n".join(block).strip("\n")) + "</pre>")
            continue
        para.append(line.strip())
        i += 1
    flush()
    return "".join(out)


def _md_list(lines: list[str], i: int, indent: int) -> tuple[str, int]:
    """The list that starts at ``lines[i]``, and the line to go on from.

    An item's own lines are gathered and laid out by ``_md_blocks``, so a list
    inside a list, or a paragraph under an item, comes out as itself.
    """
    ordered = bool(_MD_NUMBER.match(lines[i]))
    items: list[list[str]] = []
    count = len(lines)
    while i < count:
        line = lines[i]
        item = _MD_NUMBER.match(line) or _MD_BULLET.match(line)
        if item and len(item.group(1)) <= indent:
            if len(item.group(1)) < indent:
                break                                  # this item belongs to a list outside
            if bool(_MD_NUMBER.match(line)) != ordered:
                break                                  # numbers after bullets start a second list
            items.append([item.group(2)])
            i += 1
            continue
        if not items:
            break
        if not line.strip():
            # A blank line ends the list unless what follows is indented under
            # the item it would belong to, or is another item of this list.
            after = lines[i + 1] if i + 1 < count else ""
            if not (after.startswith(" " * (indent + 1)) or _MD_BULLET.match(after) or _MD_NUMBER.match(after)):
                break
            items[-1].append("")
            i += 1
            continue
        if line.startswith(" " * (indent + 1)):
            items[-1].append(line[indent + 1:])
        else:
            items[-1].append(line.strip())             # carried on without indenting
        i += 1
    made = "".join("<li>" + _md_blocks(item) + "</li>" for item in items)
    return f"<{'ol' if ordered else 'ul'}>{made}</{'ol' if ordered else 'ul'}>", i


def _md_cells(row: str) -> list[str]:
    """A table row's cells, without the bars that hold them."""
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _md_table(head: list[str], rows: list[list[str]]) -> str:
    """A table, its heading row bold, every row padded to the widest."""
    width = max([len(head)] + [len(row) for row in rows])
    def line(cells, tag):
        cells = cells + [""] * (width - len(cells))
        return "<tr>" + "".join(f"<{tag}>{_md_inline(c)}</{tag}>" for c in cells) + "</tr>"
    return "<table>" + line(head, "th") + "".join(line(row, "td") for row in rows) + "</table>"


def _md_inline(text: str) -> str:
    """Emphasis, code and links within a line. A link keeps the words it shows
    and loses its address; an image goes entirely, since nothing can be fetched."""
    # Code spans come out first and go back last, so the markup inside one is
    # left as the characters it is rather than read as emphasis.
    kept: list[str] = []
    def keep(match):
        kept.append(html.escape(match.group(2).strip()))
        return f"\x00{len(kept) - 1}\x00"
    text = _MD_SPAN.sub(keep, text)
    text = html.escape(text)
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(lambda m: m.group(1), text)
    text = _MD_AUTOLINK.sub(lambda m: m.group(1), text)
    text = _MD_STRIKE.sub(r"<s>\1</s>", text)
    text = _MD_BOLD.sub(r"<b>\2</b>", text)
    text = _MD_ITALIC.sub(r"<i>\2</i>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{kept[int(m.group(1))]}</code>", text)


# -- HTML and Rich Text -----------------------------------------------------------

_HTML_GONE = "script|iframe|frame|frameset|video|audio|object|embed|canvas|svg|noscript"
_HTML_PAIRED = re.compile(rb"<(" + _HTML_GONE.encode() + rb")\b[^>]*>.*?</\s*\1\s*>", re.I | re.S)
_HTML_LONE = re.compile(rb"<(?:/\s*)?(?:" + _HTML_GONE.encode() + rb")\b[^>]*>", re.I)
_HTML_IMAGE = re.compile(rb"<img\b[^>]*>", re.I)
_HTML_DATA = re.compile(rb"""\bsrc\s*=\s*["']?\s*data:""", re.I)


def _safe_html(data: bytes) -> bytes:
    """A web page with what cannot be drawn, or should not be, taken out.

    Scripts, frames and media have no place in a reading. An ``<img>`` that
    would have to be fetched goes too: the browser version is offline-first and
    a converted PDF must not depend on the network, and what MuPDF draws for a
    picture it cannot get is the literal word "[image]", which the voice would
    then read out. A picture written into the page as a ``data:`` URI stays.

    The editing is done on the bytes rather than on decoded text on purpose: a
    page declares its own encoding in a ``<meta>`` inside itself, so decoding it
    here to edit it -- and having to guess that encoding to do so -- would make
    mojibake of every page that turned out not to be UTF-8.
    """
    data = _HTML_PAIRED.sub(b" ", data)
    data = _HTML_LONE.sub(b" ", data)
    return _HTML_IMAGE.sub(lambda m: m.group(0) if _HTML_DATA.search(m.group(0)) else b" ", data)


_RTF_TOKEN = re.compile(r"\\([a-zA-Z]{1,32})(-?\d{1,10})?[ ]?|\\'([0-9a-fA-F]{2})"
                        r"|\\([\\{}*])|([{}])|[\r\n]+|(.)", re.S)
# Groups whose contents describe the file rather than say anything: fonts,
# colours, styles, the author and title, and embedded pictures.
_RTF_SILENT = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "themedata",
               "listtable", "listoverridetable", "rsidtbl", "generator",
               "datastore", "latentstyles", "xmlnstbl", "filetbl", "upr"}
_RTF_BREAKS = {"par": "\n\n", "line": "\n", "tab": "\t", "cell": "\t", "row": "\n",
               "sect": "\n\n", "page": "\n\n", "lbr": "\n"}
_RTF_PRIVATE = re.compile("[\ue000-\uf8ff]")
_RTF_GLYPHS = {"emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022",
               "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201c",
               "rdblquote": "\u201d", "tilde": "\u00a0", "emspace": "\u2003",
               "enspace": "\u2002", "~": "\u00a0", "_": "\u2011", "-": ""}


_RTF_TITLE = re.compile(r"\{\\title\s*([^{}]*)\}")


def _rtf_title(data: bytes) -> str:
    """The title out of a Rich Text file's ``\\info`` group, if it named one.

    That group is skipped when the words are read, because none of what is in it
    is to be read aloud -- but the title is worth having, so the window and Save
    a copy can call the document what it calls itself rather than what its file
    happens to be named. Read back through the same decoder, so an accented
    title comes out as it was written.
    """
    found = _RTF_TITLE.search(data.decode("latin-1", "replace"))
    if not found or not found.group(1).strip():
        return ""
    wrapped = "{" + chr(92) + "rtf1" + chr(92) + "ansi " + found.group(1) + "}"
    return _rtf_text(wrapped.encode("latin-1", "replace"))[:200]


def _rtf_text(data: bytes) -> str:
    """The words of a Rich Text file, with its paragraphs kept and the rest let go.

    Formatting is lost -- this is a control-word stripper, not a reader of RTF --
    but the words come out in order, which is what there is to read aloud. A
    group that only describes the file (its fonts, its styles, its pictures) is
    skipped whole, as is any ``\\*`` destination, which is RTF's own way of
    saying "ignore this if you do not know it".
    """
    source = data.decode("latin-1", "replace")
    if not source.lstrip()[:5].startswith("{\\rt"):
        raise ValueError("this does not open as a Rich Text file")
    out: list[str] = []
    stack: list[dict] = []
    state = {"uc": 1, "quiet": False}
    page = "cp1252"
    pending = 0                       # characters standing in for a \u, still to swallow
    for token in _RTF_TOKEN.finditer(source):
        word, argument, hexed, escaped, brace, plain = token.group(1, 2, 3, 4, 5, 6)
        if brace == "{":
            stack.append(state)
            state = dict(state)
            continue
        if brace == "}":
            state = stack.pop() if stack else state
            pending = 0
            continue
        if escaped in ("\\", "{", "}"):
            plain, escaped = escaped, None
        elif escaped == "*":
            state["quiet"] = True     # a destination this reader is meant to skip
            continue
        if word:
            value = int(argument) if argument else None
            if word in _RTF_SILENT:
                state["quiet"] = True
            elif word == "ansicpg" and value:
                page = f"cp{value}"
            elif word == "uc":
                state["uc"] = max(0, value or 0)
            elif word == "u" and value is not None:
                if not state["quiet"]:
                    out.append(chr(value if value >= 0 else value + 65536))
                pending = state["uc"]
            elif word in _RTF_BREAKS and not state["quiet"]:
                out.append(_RTF_BREAKS[word])
                pending = 0
            elif word in _RTF_GLYPHS and not state["quiet"]:
                out.append(_RTF_GLYPHS[word])
            continue
        if hexed:
            if pending:
                pending -= 1
            elif not state["quiet"]:
                out.append(bytes([int(hexed, 16)]).decode(page, "replace"))
            continue
        if escaped in ("~", "_", "-"):
            if not state["quiet"]:
                out.append(_RTF_GLYPHS[escaped])
            continue
        if plain is not None:
            if pending:
                pending -= 1
            elif not state["quiet"]:
                out.append(plain)
    text = "".join(out)
    # Word writes a Symbol or Wingdings bullet as a character in the private use
    # area, which means nothing without the font it was meant for: MuPDF draws a
    # box and the voice has nothing to say. Better gone than either.
    text = _RTF_PRIVATE.sub("", text)
    # RTF writes a paragraph break after the last paragraph too, and many
    # writers put one between every line of a table; neither should become an
    # empty page's worth of blank paragraphs.
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_CSS = ("body { font-family: serif; font-size: 11pt; line-height: 1.45; } p { margin: 0 0 8pt 0; } "
       "h1 { font-size: 18pt; margin: 14pt 0 8pt 0; } h2 { font-size: 14pt; margin: 12pt 0 6pt 0; } "
       "h3, h4, h5, h6 { font-size: 12pt; margin: 10pt 0 5pt 0; } li p { margin: 0 0 3pt 0; } "
       "td, th { border: 0.5pt solid #999; padding: 3pt; vertical-align: top; } "
       "th { font-weight: bold; } blockquote { margin: 0 0 8pt 18pt; } "
       "pre { font-family: monospace; font-size: 9.5pt; white-space: pre-wrap; margin: 0 0 8pt 0; } "
       "code { font-family: monospace; font-size: 9.5pt; } hr { margin: 8pt 0; }")

# What document_to_pdf takes: CONVERTIBLE without the plain text file, which
# text_to_pdf handles instead. Derived rather than written out a second time, so
# a type cannot be offered in the Open dialog and then refused down here.
KINDS = {suffix.lstrip("."): name for suffix, name in CONVERTIBLE.items()
         if suffix != ".txt"}


def document_to_pdf(data, kind: str, title: str, progress=None) -> bytes:
    """Any of ``KINDS`` as PDF pages -- A4 for a document, slide-sized for a deck
    -- titled by the file's own title or else ``title``, and with its headings
    (or the book's table of contents, or the slide titles) as the outline.

    ``progress(done, total)``, if given, is called as the work goes on, for a
    caller with a bar to move. Only a slide deck reports it, and only a deck
    takes long enough to need to: the rest are a second or two at most, and
    MuPDF does not say how far through one of those it is.
    """
    data = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    if kind not in KINDS:
        raise ValueError(f"cannot open .{kind} files")
    # Named for what the person opened, converted as what it actually is.
    creator, named = f"Mimick, from {KINDS[kind]}", KINDS[kind]
    kind = ALIASES.get(kind, kind)
    if kind in ("pptx", "odp"):
        return slides.slides_pdf(data, kind, title, progress)
    if kind == "rtf":
        return text_to_pdf(_rtf_text(data), _rtf_title(data) or title, creator)
    if kind in ("odt", "md"):
        try:
            body, name = _odt_html(data) if kind == "odt" else _markdown_html(_read_text(data))
        except (zipfile.BadZipFile, KeyError, ET.ParseError):
            raise ValueError(f"this does not open as {named}") from None
        if not re.sub(r"<[^>]+>", "", body).strip():
            raise ValueError("the file has no text in it")
        return _story_pdf(body, _CSS, name or title, creator)
    if kind != "html":
        return _native_pdf(data, kind, title, creator, named)
    # A page may carry a picture written into it as a data: URI, and MuPDF
    # refuses the whole page when one of those turns out to be truncated or in a
    # format it cannot draw. A picture is worth having, but not at the price of
    # the words around it: keep them, and drop every picture if that is refused.
    safe = _safe_html(data)
    try:
        return _native_pdf(safe, kind, title, creator, named)
    except ValueError:
        raise
    except Exception:
        return _native_pdf(_HTML_IMAGE.sub(b" ", safe), kind, title, creator, named)


def _native_pdf(data: bytes, kind: str, title: str, creator: str, named: str) -> bytes:
    """A kind MuPDF reads itself, laid out on A4 and converted, its own outline kept."""
    try:
        source = pymupdf.open(stream=data, filetype=kind)
    except Exception:
        raise ValueError(f"this does not open as {named}") from None
    with source:
        if source.is_reflowable:
            source.apply_css("@page { margin: 72pt } body { margin: 0 }")
            source.layout(rect=pymupdf.paper_rect("a4"), fontsize=11)
        toc = source.get_toc(simple=True)
        pdf = pymupdf.open("pdf", source.convert_to_pdf())
        name = ((source.metadata or {}).get("title") or "").strip() or title
    with pdf:
        if not any(page.get_text().strip() for page in pdf):
            raise ValueError("the file has no text in it")
        pdf.set_metadata({"title": name, "creator": creator})
        _set_toc(pdf, [_pointing(pdf, level, text, page) for level, text, page in toc])
        return pdf.tobytes(garbage=3, deflate=True)


