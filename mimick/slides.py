"""Lay a PowerPoint or OpenDocument presentation out as a PDF, one page per slide.

Mimick reads the words on a page, so what matters here is that every slide's
words land on its page in about the place they were put, at about the size
they were given, and that the pictures come with them. What does not come
across: theme backgrounds and colours (the text is always dark on white, which
is what reading it needs), drawn shapes and arrows, charts, SmartArt, video,
animations and speaker notes. A title that runs long is shrunk to fit its box,
as PowerPoint would.

``.pptx`` and ``.ppsx`` are PowerPoint's; ``.odp`` is LibreOffice Impress's.
The old binary ``.ppt`` is not read here at all -- the desktop app hands it to
LibreOffice when that is installed, and the browser cannot open it.

Shared with the browser version through tools/port.sh.
"""

from __future__ import annotations

import html
import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field

import pymupdf

# -- what a slide is, once read ---------------------------------------------------


@dataclass
class _Box:
    """Something drawn on a slide: words set in a box, a picture, or a table."""
    rect: tuple[float, float, float, float]
    html: str = ""
    anchor: str = "t"           # t, ctr or b: where the words sit in a taller box
    picture: bytes = b""


@dataclass
class _Slide:
    boxes: list[_Box] = field(default_factory=list)
    title: str = ""


_FONT = "font-family: sans-serif; color: #111;"
_CSS = ("body { margin: 0; } p { margin: 0 0 0.25em 0; line-height: 1.15; } "
        "table { border-collapse: collapse; } "
        "td { border: 0.75pt solid #888; padding: 2pt 4pt; vertical-align: top; }")


def slides_pdf(data: bytes, kind: str, title: str, progress=None) -> bytes:
    """A presentation (``pptx`` or ``odp``) as PDF pages the size of its slides,
    each slide's title an entry in the outline.

    ``progress(done, total)``, if given, is called as each slide is drawn. A
    lecture deck of 67 slides takes about nine seconds, which is a long time to
    show nothing; the browser passes one in so its bar can count the slides.
    Nothing else depends on it, and the desktop passes nothing.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("this does not open as a presentation") from None
    with archive:
        try:
            size, name, slides = (_read_pptx if kind == "pptx" else _read_odp)(archive)
        except (KeyError, ET.ParseError):
            raise ValueError("this does not open as a presentation") from None
    if not slides:
        raise ValueError("the presentation has no slides in it")
    return _draw(size, slides, name or title, kind, progress)


def _draw(size, slides: list[_Slide], title: str, kind: str, progress=None) -> bytes:
    width, height = size
    doc = pymupdf.open()
    # A box's words are set once on a spare page to learn how much room they
    # leave, so a title anchored to the middle or bottom of its box can be put
    # there, as the slide shows it.
    spare = pymupdf.open()
    scratch = spare.new_page(width=width, height=height)
    toc = []
    # A picture used on many slides (a logo, a background photo) is stored once
    # and drawn from there, not once per slide.
    stored: dict[int, int] = {}
    for number, slide in enumerate(slides, start=1):
        page = doc.new_page(width=width, height=height)
        for box in slide.boxes:
            rect = pymupdf.Rect(box.rect) & page.rect
            if rect.is_empty or rect.width < 2 or rect.height < 2:
                continue
            if box.picture:
                key = hash(box.picture)
                try:
                    if key in stored:
                        page.insert_image(rect, xref=stored[key], keep_proportion=False)
                    else:
                        stored[key] = page.insert_image(rect, stream=_smaller(box.picture, rect),
                                                        keep_proportion=False)
                except Exception:
                    pass          # a picture MuPDF cannot draw (EMF, WMF) is left out
                continue
            if box.anchor != "t":
                left, _scale = scratch.insert_htmlbox(rect, box.html, css=_CSS, scale_low=0)
                if left > 0:
                    rect.y0 += left / 2 if box.anchor == "ctr" else left
            page.insert_htmlbox(rect, box.html, css=_CSS, scale_low=0)
        toc.append([1, slide.title or f"Slide {number}", number])
        if progress is not None:
            progress(number, len(slides))
    spare.close()
    doc.set_metadata({"title": title, "creator": "Mimick, from " +
                      ("a PowerPoint presentation" if kind == "pptx" else "an OpenDocument presentation")})
    doc.set_toc(toc)
    made = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return made


def _smaller(picture: bytes, rect) -> bytes:
    """A large picture made no sharper than the slide can show -- 150 dots to
    the inch at the size it is drawn -- and a photo kept as a JPEG. Decks are
    full of camera photos, often saved as PNG, and a PDF of them runs to tens of
    megabytes, which the browser version has to hold in memory. LibreOffice
    does the same when it saves a PDF. Small pictures are left exactly as they are."""
    if len(picture) < 300_000:
        return picture
    try:
        pix = pymupdf.Pixmap(picture)
    except Exception:
        return picture
    if pix.colorspace is None or pix.colorspace.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if pix.alpha and pix.samples[pix.n - 1::pix.n].count(255) == pix.width * pix.height:
        pix = pymupdf.Pixmap(pix, 0)           # see-through nowhere: a photo after all
    most = max(rect.width, rect.height) * 150 / 72
    if max(pix.width, pix.height) > most * 1.25:
        factor = most / max(pix.width, pix.height)
        pix = pymupdf.Pixmap(pix, max(1, round(pix.width * factor)),
                             max(1, round(pix.height * factor)), None)
    made = pix.tobytes("png") if pix.alpha else pix.tobytes("jpg", jpg_quality=85)
    return made if len(made) < len(picture) else picture


def _paragraph(runs: str, size: float, align: str = "", left: float = 0, bullet: str = "") -> str:
    """One paragraph as HTML: ``runs`` already escaped, ``size`` in points."""
    style = f"{_FONT} font-size: {size:.1f}pt;"
    if align in ("center", "right", "justify"):
        style += f" text-align: {align};"
    if bullet:
        hang = size * 0.9
        style += f" margin-left: {left + hang:.1f}pt; text-indent: -{hang:.1f}pt;"
        runs = f"{html.escape(bullet)}&#160; {runs}"
    elif left:
        style += f" margin-left: {left:.1f}pt;"
    return f'<p style="{style}">{runs or "&#160;"}</p>'


def _span(text: str, bold=False, italic=False, underline=False, size: float | None = None) -> str:
    out = html.escape(text).replace("\n", "<br>")
    if not out:
        return ""
    if size:
        out = f'<span style="font-size: {size:.1f}pt">{out}</span>'
    if underline:
        out = f"<u>{out}</u>"
    if italic:
        out = f"<i>{out}</i>"
    if bold:
        out = f"<b>{out}</b>"
    return out


def _numbered(style: str, n: int) -> str:
    """PowerPoint's automatic numbering (``arabicPeriod``, ``alphaLcParenR``...)."""
    if style.startswith("alphaLc"):
        mark = chr(ord("a") + (n - 1) % 26)
    elif style.startswith("alphaUc"):
        mark = chr(ord("A") + (n - 1) % 26)
    elif style.startswith("roman"):
        mark = _roman(n)
        mark = mark.lower() if style.startswith("romanLc") else mark
    else:
        mark = str(n)
    if style.endswith("ParenBoth"):
        return f"({mark})"
    if style.endswith("ParenR"):
        return f"{mark})"
    return f"{mark}."


def _roman(n: int) -> str:
    out = ""
    for value, letters in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                           (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out, n = out + letters, n - value
    return out


# -- PowerPoint -------------------------------------------------------------------

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_EMU = 12700                    # English Metric Units to the point
_ALIGN = {"ctr": "center", "r": "right", "just": "justify", "dist": "justify"}
# Placeholders that are the slide's furniture rather than its content. They
# would be read aloud as a stray date or number in the middle of the reading.
_FURNITURE = {"dt", "ftr", "sldNum", "hdr"}


def _rels(archive, part: str) -> dict[str, str]:
    """The relationships of ``part``, id -> the path they point at in the zip."""
    folder, name = posixpath.split(part)
    path = posixpath.join(folder, "_rels", name + ".rels")
    try:
        root = ET.fromstring(archive.read(path))
    except KeyError:
        return {}
    out = {}
    for rel in root.iter(_REL + "Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        out[rel.get("Id")] = posixpath.normpath(posixpath.join(folder, rel.get("Target", "")))
    return out


def _of_type(archive, part: str, kind: str) -> str | None:
    folder, name = posixpath.split(part)
    try:
        root = ET.fromstring(archive.read(posixpath.join(folder, "_rels", name + ".rels")))
    except KeyError:
        return None
    for rel in root.iter(_REL + "Relationship"):
        if rel.get("Type", "").endswith("/" + kind):
            return posixpath.normpath(posixpath.join(folder, rel.get("Target", "")))
    return None


def _levels(list_style) -> dict[int, dict]:
    """A list style (``a:lstStyle``, a master's ``p:bodyStyle``...) as level -> the
    properties Mimick uses from it."""
    out: dict[int, dict] = {}
    if list_style is None:
        return out
    for level in range(1, 10):
        el = list_style.find(f"{_A}lvl{level}pPr")
        if el is not None:
            out[level] = _paragraph_props(el)
    return out


def _paragraph_props(el) -> dict:
    props: dict = {}
    if el.get("algn"):
        props["align"] = _ALIGN.get(el.get("algn"), "")
    if el.get("marL") is not None:
        props["left"] = int(el.get("marL")) / _EMU
    if el.find(_A + "buNone") is not None:
        props["bullet"] = ""
    elif el.find(_A + "buChar") is not None:
        props["bullet"] = el.find(_A + "buChar").get("char", "•")
    elif el.find(_A + "buAutoNum") is not None:
        props["bullet"] = "#" + el.find(_A + "buAutoNum").get("type", "arabicPeriod")
    run = el.find(_A + "defRPr")
    if run is not None:
        props.update(_run_props(run))
    return props


def _run_props(el) -> dict:
    props: dict = {}
    if el.get("sz"):
        props["size"] = int(el.get("sz")) / 100
    if el.get("b") is not None:
        props["bold"] = el.get("b") in ("1", "true")
    if el.get("i") is not None:
        props["italic"] = el.get("i") in ("1", "true")
    if el.get("u") is not None:
        props["underline"] = el.get("u") != "none"
    return props


def _merged(*layers: dict[int, dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for layer in layers:
        for level, props in layer.items():
            out.setdefault(level, {}).update(props)
    return out


def _placeholder(sp):
    ph = sp.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
    if ph is None:
        ph = sp.find(f"{_P}nvPicPr/{_P}nvPr/{_P}ph")
    if ph is None:
        ph = sp.find(f"{_P}nvGraphicFramePr/{_P}nvPr/{_P}ph")
    return ph


def _ph_class(kind: str | None) -> str:
    """Which master text style a placeholder type takes its look from."""
    if kind in ("title", "ctrTitle"):
        return "title"
    if kind in (None, "body", "subTitle", "obj"):
        return "body"
    return kind


def _find_ph(tree, ph):
    """The shape in a layout or master that the slide's placeholder ``ph``
    inherits from: the same index first, then the same kind."""
    if tree is None or ph is None:
        return None
    idx, kind = ph.get("idx"), _ph_class(ph.get("type"))
    by_kind = None
    for sp in tree.iter():
        if sp.tag not in (_P + "sp", _P + "pic", _P + "graphicFrame"):
            continue
        other = _placeholder(sp)
        if other is None:
            continue
        if idx is not None and other.get("idx") == idx:
            return sp
        if by_kind is None and _ph_class(other.get("type")) == kind:
            by_kind = sp
    return by_kind


def _xfrm(sp):
    for path in (f"{_P}spPr/{_A}xfrm", f"{_P}xfrm", f"{_P}grpSpPr/{_A}xfrm"):
        x = sp.find(path)
        if x is not None:
            off, ext = x.find(_A + "off"), x.find(_A + "ext")
            if off is not None and ext is not None:
                return (int(off.get("x", 0)), int(off.get("y", 0)),
                        int(ext.get("cx", 0)), int(ext.get("cy", 0)))
    return None


class _Deck:
    """What a slide inherits: its layout and master, and the master's styles."""

    def __init__(self, archive):
        self.archive = archive
        self.parsed: dict[str, ET.Element] = {}

    def xml(self, part: str | None):
        if part is None:
            return None
        if part not in self.parsed:
            try:
                self.parsed[part] = ET.fromstring(self.archive.read(part))
            except KeyError:
                self.parsed[part] = None
        return self.parsed[part]


def _read_pptx(archive):
    deck = _Deck(archive)
    main = "ppt/presentation.xml"
    root = deck.xml(main)
    if root is None:
        raise KeyError(main)
    size_el = root.find(_P + "sldSz")
    size = ((int(size_el.get("cx")) / _EMU, int(size_el.get("cy")) / _EMU)
            if size_el is not None else (720.0, 540.0))
    rels = _rels(archive, main)
    slides = []
    for sid in root.iterfind(f"{_P}sldIdLst/{_P}sldId"):
        part = rels.get(sid.get(_R + "id"))
        tree = deck.xml(part)
        if tree is None or tree.get("show") in ("0", "false"):
            continue          # a hidden slide is not shown, so not read either
        slides.append(_pptx_slide(deck, part, tree))
    name = ""
    core = deck.xml("docProps/core.xml")
    if core is not None:
        name = (core.findtext("{http://purl.org/dc/elements/1.1/}title") or "").strip()
    return size, name, slides


def _pptx_slide(deck: _Deck, part: str, tree) -> _Slide:
    layout_part = _of_type(deck.archive, part, "slideLayout")
    layout = deck.xml(layout_part)
    master_part = _of_type(deck.archive, layout_part, "slideMaster") if layout_part else None
    master = deck.xml(master_part)
    styles = {}
    if master is not None:
        for kind, tag in (("title", "titleStyle"), ("body", "bodyStyle"), ("other", "otherStyle")):
            styles[kind] = _levels(master.find(f"{_P}txStyles/{_P}{tag}"))
    slide = _Slide()
    media = _rels(deck.archive, part)
    tree_root = tree.find(f"{_P}cSld/{_P}spTree")
    if tree_root is not None:
        _pptx_shapes(deck, tree_root, (0, 0, 1, 1), slide, layout, master, styles, media, part)
    return slide


def _children(group):
    """A group's shapes, looking through the markup-compatibility wrappers
    PowerPoint puts round anything newer than 2007."""
    for child in group:
        if child.tag == _MC + "AlternateContent":
            pick = child.find(_MC + "Fallback")
            if pick is None:
                pick = child.find(_MC + "Choice")
            if pick is not None:
                yield from _children(pick)
        else:
            yield child


def _pptx_shapes(deck, group, place, slide, layout, master, styles, media, part):
    """Every shape in ``group``, ``place`` being (dx, dy, sx, sy) from the
    group's own coordinates to the slide's, in EMU."""
    dx, dy, sx, sy = place
    for sp in _children(group):
        tag = sp.tag
        if tag == _P + "grpSp":
            x = sp.find(f"{_P}grpSpPr/{_A}xfrm")
            if x is None:
                _pptx_shapes(deck, sp, place, slide, layout, master, styles, media, part)
                continue
            off, ext = x.find(_A + "off"), x.find(_A + "ext")
            coff, cext = x.find(_A + "chOff"), x.find(_A + "chExt")
            if None in (off, ext, coff, cext):
                _pptx_shapes(deck, sp, place, slide, layout, master, styles, media, part)
                continue
            gx, gy = int(off.get("x")), int(off.get("y"))
            cw, ch = int(cext.get("cx")) or 1, int(cext.get("cy")) or 1
            kx, ky = int(ext.get("cx")) / cw, int(ext.get("cy")) / ch
            inner = (dx + sx * (gx - int(coff.get("x")) * kx), dy + sy * (gy - int(coff.get("y")) * ky),
                     sx * kx, sy * ky)
            _pptx_shapes(deck, sp, inner, slide, layout, master, styles, media, part)
            continue
        if tag not in (_P + "sp", _P + "pic", _P + "graphicFrame", _P + "cxnSp"):
            continue
        ph = _placeholder(sp)
        if ph is not None and ph.get("type") in _FURNITURE:
            continue
        from_layout = _find_ph(layout, ph)
        from_master = _find_ph(master, ph)
        where = _xfrm(sp) or (from_layout is not None and _xfrm(from_layout)) or \
            (from_master is not None and _xfrm(from_master))
        if not where:
            continue
        x, y, w, h = where
        rect = ((dx + sx * x) / _EMU, (dy + sy * y) / _EMU,
                (dx + sx * (x + w)) / _EMU, (dy + sy * (y + h)) / _EMU)
        if tag == _P + "pic":
            blip = sp.find(f"{_P}blipFill/{_A}blip")
            target = media.get(blip.get(_R + "embed")) if blip is not None else None
            if target:
                try:
                    slide.boxes.append(_Box(rect, picture=deck.archive.read(target)))
                except KeyError:
                    pass
            continue
        if tag == _P + "graphicFrame":
            table = sp.find(f"{_A}graphic/{_A}graphicData/{_A}tbl")
            if table is not None:
                slide.boxes.append(_Box(rect, html=_pptx_table(table, styles.get("other", {}))))
            continue
        body = sp.find(_P + "txBody")
        if body is None:
            continue
        kind = _ph_class(ph.get("type")) if ph is not None else "other"
        base = styles.get(kind if kind in ("title", "body") else "other", {})
        inherited = [base]
        for source in (from_master, from_layout):
            if source is not None:
                inherited.append(_levels(source.find(f"{_P}txBody/{_A}lstStyle")))
        inherited.append(_levels(body.find(_A + "lstStyle")))
        levels = _merged(*inherited)
        words, text = _pptx_text(body, levels)
        if not text.strip():
            continue
        anchor = "t"
        for source in (from_master, from_layout, sp):
            if source is None:
                continue
            props = source.find(f"{_P}txBody/{_A}bodyPr")
            if props is not None and props.get("anchor"):
                anchor = props.get("anchor")
        props = body.find(_A + "bodyPr")
        inset = [7.2, 3.6, 7.2, 3.6]
        if props is not None:
            for i, name in enumerate(("lIns", "tIns", "rIns", "bIns")):
                if props.get(name) is not None:
                    inset[i] = int(props.get(name)) / _EMU
        rect = (rect[0] + inset[0], rect[1] + inset[1], rect[2] - inset[2], rect[3] - inset[3])
        slide.boxes.append(_Box(rect, html=words, anchor=anchor if anchor in ("ctr", "b") else "t"))
        if kind == "title" and not slide.title:
            slide.title = " ".join(text.split())[:120]


def _pptx_text(body, levels: dict[int, dict]) -> tuple[str, str]:
    """A text body as HTML, and as plain words."""
    scale = 1.0
    fit = body.find(f"{_A}bodyPr/{_A}normAutofit")
    if fit is not None and fit.get("fontScale"):
        scale = int(fit.get("fontScale")) / 100000
    paragraphs, plain, counters = [], [], {}
    for p in body.iterfind(_A + "p"):
        ppr = p.find(_A + "pPr")
        level = int(ppr.get("lvl", 0)) + 1 if ppr is not None else 1
        props = dict(levels.get(level, {}))
        if ppr is not None:
            props.update(_paragraph_props(ppr))
        size = props.get("size", 18.0)
        runs, words = [], []
        for run in p:
            if run.tag in (_A + "r", _A + "fld"):
                text = run.findtext(_A + "t") or ""
                rpr = run.find(_A + "rPr")
                mine = dict(props)
                if rpr is not None:
                    mine.update(_run_props(rpr))
                runs.append(_span(text, mine.get("bold"), mine.get("italic"), mine.get("underline"),
                                  mine.get("size", size) * scale if mine.get("size", size) != size else None))
                words.append(text)
            elif run.tag == _A + "br":
                runs.append("<br>")
                words.append("\n")
        end = p.find(_A + "endParaRPr")
        if not words and end is not None and end.get("sz"):
            size = int(end.get("sz")) / 100
        bullet = props.get("bullet", "") if "".join(words).strip() else ""
        if bullet.startswith("#"):
            counters[level] = counters.get(level, 0) + 1
            for deeper in [k for k in counters if k > level]:
                del counters[deeper]
            bullet = _numbered(bullet[1:], counters[level])
        paragraphs.append(_paragraph("".join(runs), size * scale, props.get("align", ""),
                                     props.get("left", 0) if bullet else 0, bullet))
        plain.append("".join(words))
    # Empty paragraphs at the end push nothing down on the slide, but would
    # push an anchored box's words up here.
    while plain and not plain[-1].strip():
        plain.pop()
        paragraphs.pop()
    return "".join(paragraphs), "\n".join(plain)


def _pptx_table(table, other: dict[int, dict]) -> str:
    rows = []
    for tr in table.iterfind(_A + "tr"):
        cells = []
        for tc in tr.iterfind(_A + "tc"):
            if tc.get("hMerge") in ("1", "true") or tc.get("vMerge") in ("1", "true"):
                continue
            body = tc.find(_A + "txBody")
            words = _pptx_text(body, _merged({1: {"size": 18.0}}, other))[0] if body is not None else ""
            span = f' colspan="{tc.get("gridSpan")}"' if tc.get("gridSpan") else ""
            span += f' rowspan="{tc.get("rowSpan")}"' if tc.get("rowSpan") else ""
            cells.append(f"<td{span}>{words}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return '<table style="width: 100%">' + "".join(rows) + "</table>"


# -- OpenDocument (LibreOffice Impress) ---------------------------------------------

_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
}
_Q = {prefix: "{%s}" % uri for prefix, uri in _NS.items()}


def _length(value: str | None) -> float | None:
    """An OpenDocument length (``2.5cm``, ``1in``, ``12pt``) in points."""
    if not value:
        return None
    m = re.match(r"\s*(-?[\d.]+)\s*(cm|mm|in|pt|pc|px)?", value)
    if not m:
        return None
    number = float(m.group(1))
    return number * {"cm": 72 / 2.54, "mm": 72 / 25.4, "in": 72, "pt": 1, "pc": 12,
                     "px": 0.75, None: 1}[m.group(2)]


class _OdpStyles:
    """Every named style in the file, with the chain of parents each one has."""

    def __init__(self, *roots):
        self.by_name: dict[str, ET.Element] = {}
        for root in roots:
            if root is None:
                continue
            for el in root.iter(_Q["style"] + "style"):
                self.by_name.setdefault(el.get(_Q["style"] + "name"), el)

    def find(self, name: str | None, props: str, attribute: str):
        seen = set()
        while name and name not in seen:
            seen.add(name)
            el = self.by_name.get(name)
            if el is None:
                return None
            got = el.find(_Q["style"] + props)
            if got is not None and got.get(attribute) is not None:
                return got.get(attribute)
            name = el.get(_Q["style"] + "parent-style-name")
        return None


def _read_odp(archive):
    content = ET.fromstring(archive.read("content.xml"))
    try:
        styles_root = ET.fromstring(archive.read("styles.xml"))
    except KeyError:
        styles_root = None
    styles = _OdpStyles(content, styles_root)
    body = content.find(f"{_Q['office']}body/{_Q['office']}presentation")
    if body is None:
        raise ValueError("this is not an OpenDocument presentation")
    masters, size = {}, (720.0, 540.0)
    if styles_root is not None:
        layouts = {}
        for el in styles_root.iter(_Q["style"] + "page-layout"):
            p = el.find(_Q["style"] + "page-layout-properties")
            if p is not None:
                w, h = _length(p.get(_Q["fo"] + "page-width")), _length(p.get(_Q["fo"] + "page-height"))
                if w and h:
                    layouts[el.get(_Q["style"] + "name")] = (w, h)
        for el in styles_root.iter(_Q["style"] + "master-page"):
            masters[el.get(_Q["style"] + "name")] = el
            if el.get(_Q["style"] + "page-layout-name") in layouts:
                size = layouts[el.get(_Q["style"] + "page-layout-name")]
    slides = []
    for page in body.iterfind(_Q["draw"] + "page"):
        if styles.find(page.get(_Q["draw"] + "style-name"), "drawing-page-properties",
                       _Q["presentation"] + "visibility") == "hidden":
            continue
        slide = _Slide()
        master = masters.get(page.get(_Q["draw"] + "master-page-name"))
        _odp_shapes(archive, page, master, styles, slide)
        slides.append(slide)
    name = ""
    try:
        meta = ET.fromstring(archive.read("meta.xml"))
        name = (meta.findtext(".//{http://purl.org/dc/elements/1.1/}title") or "").strip()
    except (KeyError, ET.ParseError):
        pass
    return size, name, slides


def _odp_rect(el, master, kind):
    """Where a frame sits, in points: its own place, or, for an empty
    placeholder that left it out, the place its master gives that kind."""
    got = [_length(el.get(_Q["svg"] + a)) for a in ("x", "y", "width", "height")]
    if None in got and master is not None and kind:
        for other in master.iter(_Q["draw"] + "frame"):
            if other.get(_Q["presentation"] + "class") == kind:
                got = [_length(other.get(_Q["svg"] + a)) for a in ("x", "y", "width", "height")]
                break
    if None in got:
        return None
    x, y, w, h = got
    return (x, y, x + w, y + h)


def _odp_shapes(archive, group, master, styles, slide):
    for el in group:
        tag = el.tag
        if tag == _Q["draw"] + "g":
            _odp_shapes(archive, el, master, styles, slide)
            continue
        if tag == _Q["presentation"] + "notes":
            continue
        kind = el.get(_Q["presentation"] + "class")
        if kind in ("date-time", "footer", "header", "page-number", "notes"):
            continue
        if el.get(_Q["presentation"] + "placeholder") == "true":
            continue          # an empty placeholder shows "Click to add..." only while editing
        rect = _odp_rect(el, master, kind)
        if rect is None:
            continue
        frame_style = el.get(_Q["presentation"] + "style-name") or el.get(_Q["draw"] + "style-name")
        if tag == _Q["draw"] + "frame":
            image = el.find(_Q["draw"] + "image")
            table = el.find(_Q["table"] + "table")
            box = el.find(_Q["draw"] + "text-box")
            if table is not None:
                slide.boxes.append(_Box(rect, html=_odp_table(table, styles)))
            elif box is not None:
                _odp_text_box(box, rect, kind, frame_style, styles, slide)
            elif image is not None:
                href = image.get(_Q["xlink"] + "href", "")
                try:
                    slide.boxes.append(_Box(rect, picture=archive.read(href.lstrip("./"))))
                except KeyError:
                    pass
            continue
        # Drawn shapes -- rectangles, ellipses, callouts -- are not drawn, but
        # the words written in them are.
        if el.find(_Q["text"] + "p") is not None or el.find(_Q["text"] + "list") is not None:
            _odp_text_box(el, rect, kind, frame_style, styles, slide)


def _odp_size(styles, names, default: float) -> float:
    for name in names:
        value = styles.find(name, "text-properties", _Q["fo"] + "font-size")
        if value and not value.endswith("%"):
            got = _length(value)
            if got:
                return got
    return default


def _odp_text_box(box, rect, kind, frame_style, styles, slide):
    title = kind in ("title",)
    base = _odp_size(styles, [frame_style], 40.0 if title else 24.0)
    paragraphs, plain = [], []

    def inline(el):
        out, words = [html.escape(el.text or "")], [el.text or ""]
        for child in el:
            tag = child.tag
            if tag == _Q["text"] + "s":
                count = int(child.get(_Q["text"] + "c", "1"))
                out.append(" " * count)
                words.append(" " * count)
            elif tag == _Q["text"] + "tab":
                out.append(" ")
                words.append(" ")
            elif tag == _Q["text"] + "line-break":
                out.append("<br>")
                words.append("\n")
            elif tag == _Q["text"] + "note":
                pass
            else:
                inner, said = inline(child)
                size = styles.find(child.get(_Q["text"] + "style-name"), "text-properties", _Q["fo"] + "font-size")
                weight = styles.find(child.get(_Q["text"] + "style-name"), "text-properties", _Q["fo"] + "font-weight")
                slant = styles.find(child.get(_Q["text"] + "style-name"), "text-properties", _Q["fo"] + "font-style")
                if size and not size.endswith("%") and _length(size):
                    inner = f'<span style="font-size: {_length(size):.1f}pt">{inner}</span>'
                if weight == "bold":
                    inner = f"<b>{inner}</b>"
                if slant == "italic":
                    inner = f"<i>{inner}</i>"
                out.append(inner)
                words.append(said)
            out.append(html.escape(child.tail or ""))
            words.append(child.tail or "")
        return "".join(out), "".join(words)

    def paragraph(p, level, bullet):
        runs, words = inline(p)
        name = p.get(_Q["text"] + "style-name")
        size = _odp_size(styles, [name], base * (1, 0.875, 0.75, 0.7, 0.65)[min(level, 4)])
        align = styles.find(name, "paragraph-properties", _Q["fo"] + "text-align") or ""
        align = {"center": "center", "end": "right", "right": "right", "justify": "justify"}.get(align, "")
        paragraphs.append(_paragraph(runs, size, align, level * size * 1.2 if bullet else 0,
                                     bullet if words.strip() else ""))
        plain.append(words)

    def walk_list(el, level):
        for item in el:
            if item.tag not in (_Q["text"] + "list-item", _Q["text"] + "list-header"):
                continue
            for inner in item:
                if inner.tag == _Q["text"] + "list":
                    walk_list(inner, level + 1)
                elif inner.tag in (_Q["text"] + "p", _Q["text"] + "h"):
                    paragraph(inner, level, "•" if item.tag == _Q["text"] + "list-item" and not title else "")

    for child in box:
        if child.tag in (_Q["text"] + "p", _Q["text"] + "h"):
            paragraph(child, 0, "")
        elif child.tag == _Q["text"] + "list":
            walk_list(child, 0)
    while plain and not plain[-1].strip():
        plain.pop()
        paragraphs.pop()
    text = "\n".join(plain)
    if not text.strip():
        return
    anchor = styles.find(frame_style, "graphic-properties", _Q["draw"] + "textarea-vertical-align")
    anchor = {"middle": "ctr", "bottom": "b"}.get(anchor or ("middle" if title else "top"), "t")
    inset = 7.2
    slide.boxes.append(_Box((rect[0] + inset, rect[1] + inset / 2, rect[2] - inset, rect[3] - inset / 2),
                            html="".join(paragraphs), anchor=anchor))
    if title and not slide.title:
        slide.title = " ".join(text.split())[:120]


def _odp_table(table, styles) -> str:
    rows = []
    for row in table.iter(_Q["table"] + "table-row"):
        cells = []
        for cell in row:
            if cell.tag != _Q["table"] + "table-cell":
                continue
            words = []
            for p in cell.iter(_Q["text"] + "p"):
                words.append(_paragraph(html.escape("".join(p.itertext())), 16.0))
            span = cell.get(_Q["table"] + "number-columns-spanned")
            cells.append(f'<td{f" colspan={span}" if span else ""}>{"".join(words)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return '<table style="width: 100%">' + "".join(rows) + "</table>"
