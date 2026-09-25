"""The document canvas: every page stacked in one continuous scroll.

This is a scroll area in its own right rather than a tall widget inside one.
A widget sized to the whole document would be tens of thousands of pixels high
-- past the point where Qt's widget coordinates stay reliable -- so instead the
canvas stays the size of the window and paints the slice of the document the
scrollbar has landed on.

Only pages near that slice are rendered, and a small cache holds the rendered
bitmaps, so a long reading scrolls without stalling or filling memory.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication, QImage,
                           QPainter, QPen, QPixmap)
from PySide6.QtWidgets import QAbstractScrollArea, QWidget

from ..document import Document, Sentence, _merge_rects
from . import theme

# Pages are rendered above their on-screen size and handed to Qt with a matching
# device-pixel ratio, so text stays sharp instead of being scaled up from 72 dpi.
SUPERSAMPLE = 2.0

PAGE_GAP = 16          # blank space between pages, in logical pixels
PAGE_MARGIN = 12       # space above the first page and below the last
RENDER_MARGIN = 1      # pages rendered beyond the visible band, each way
CACHE_PAGES = 6        # rendered pages kept in memory

# The margin where notes are written, to the right of the page.
NOTE_GUTTER = 272
NOTE_PAD = 18          # space between the page edge and the notes
CARD_PAD = 10          # padding inside a note card
CARD_GAP = 8           # smallest gap between stacked cards
CARD_MIN_HEIGHT = 34
HEADING_GAP = 2        # between a note's heading and its body
NOTES_WHEEL_STEP = 90  # how far one wheel notch moves the notes column


class PageView(QAbstractScrollArea):
    """Shows a whole document as one scrolling column of pages."""

    clicked = Signal(int, float, float)      # page, x, y in PDF coordinates
    selection_changed = Signal(int, int)     # first, last word index (-1, -1 when cleared)
    page_changed = Signal(int)               # page now at the top of the viewport
    annotation_clicked = Signal(object)      # a highlight or its note card was clicked
    annotation_activated = Signal(object)    # double-clicked: open it for editing
    region_clicked = Signal(object)          # a layout region, while the plan is shown
    # A right-click on the page: where it landed, and the highlight under it if
    # there was one. The window builds the menu, because what belongs on it
    # depends on the player and the selection, which live there.
    context_requested = Signal(int, float, float, object)   # page, x, y, annotation|None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: Document | None = None
        self._zoom = 1.25
        self._supersample = SUPERSAMPLE

        self._sizes: list[QSize] = []        # logical page sizes
        self._offsets: list[int] = []        # y of each page top
        self._content_width = 0              # widest page
        self._column_width = 0               # page plus the notes margin
        self._total_height = 0
        self._current_page = 0

        self._store = None                   # AnnotationStore, once a file is open
        self._show_notes = True
        self._active_note = None
        # The notes panel is its own column: it shows one page's notes at a
        # time, stacked from the top, and scrolls independently of the page.
        self._notes_scroll = 0
        self._note_family = ""               # empty means the interface font
        self._note_size = 9.0                # points at 100% zoom
        # Which kinds of mark appear in the panel: plain highlights (quotes
        # with nothing written on them) and ones carrying a note.
        self._show_plan = False              # draw what will and will not be read
        self._show_quotes = True
        self._show_written = True
        self._panel_header: QWidget | None = None
        self._panel_footer: QWidget | None = None
        self._footer_wanted = True

        self._cache: OrderedDict[int, QPixmap] = OrderedDict()

        self._sentence: Sentence | None = None
        self._word_index = -1
        self._anchor = -1
        self._focus = -1
        self._dragging = False
        self._press_point: QPoint | None = None

        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.setMinimumSize(420, 560)
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())
        # A wheel notch should move a comfortable amount of text.
        self.verticalScrollBar().setSingleStep(48)

    # -- scrolling ---------------------------------------------------------

    def _viewport_band(self) -> tuple[int, int]:
        """The vertical slice of the document currently on screen."""
        top = self.verticalScrollBar().value()
        return top, top + self.viewport().height()

    def _scroll_offset(self) -> QPoint:
        """How far the document is shifted relative to the viewport."""
        return QPoint(self.horizontalScrollBar().value(), self.verticalScrollBar().value())

    def _update_scrollbars(self) -> None:
        view = self.viewport().size()
        vertical = self.verticalScrollBar()
        vertical.setRange(0, max(0, self._total_height - view.height()))
        vertical.setPageStep(view.height())
        horizontal = self.horizontalScrollBar()
        pane = max(view.width() - self._gutter_width(), 1)
        horizontal.setRange(0, max(0, self._content_width - pane))
        horizontal.setPageStep(pane)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._update_scrollbars()
        self._position_panel_widgets()
        # The centring offset depends on the window width, so redraw fully.
        self.viewport().update()

    # -- content -----------------------------------------------------------

    def set_document(self, document: Document | None) -> None:
        self._document = document
        self._sentence = None
        self._word_index = -1
        self._current_page = 0
        self._cache.clear()
        self.clear_selection()
        self._relayout()
        self.verticalScrollBar().setValue(0)

    def _gutter_width(self) -> int:
        """Width of the notes panel: reserved whenever the margin is turned on."""
        return NOTE_GUTTER if self._show_notes else 0

    # -- widgets docked inside the notes panel ------------------------------

    def set_panel_widgets(self, header: QWidget | None, footer: QWidget | None) -> None:
        """Dock a header and footer inside the notes panel."""
        self._panel_header, self._panel_footer = header, footer
        for widget in (header, footer):
            if widget is not None:
                widget.setParent(self.viewport())
        self._position_panel_widgets()

    @property
    def plan_visible(self) -> bool:
        return self._show_plan

    def set_plan_visible(self, visible: bool) -> None:
        """Show which parts of each page Mimick will read."""
        if visible != self._show_plan:
            self._show_plan = visible
            self.viewport().update()

    def _draw_plan(self, painter: QPainter, page: int) -> None:
        """Outline each region, numbered in the order it will be read."""
        if self._document is None:
            return
        regions = self._document.regions.get(page) or []
        reading = [r for r in regions if r.reads]
        numbers = {id(r): n + 1 for n, r in enumerate(reading)}

        badge_font = QFont(self.font())
        badge_font.setPointSizeF(max(badge_font.pointSizeF() - 1.0, 7.0))
        badge_font.setBold(True)

        for region in regions:
            box = self._to_widget(region.rect, page)
            if region.reads:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(theme.ACCENT), 1.4))
                painter.drawRoundedRect(box, 4, 4)
                tag = str(numbers.get(id(region), ""))
                fill = QColor(theme.ACCENT)
                ink = QColor("#0b1220")
            else:
                # A wash over what is being left out, so it is obvious at a glance.
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(16, 18, 22, 150))
                painter.drawRoundedRect(box, 4, 4)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                pen = QPen(QColor(theme.TEXT_DIM), 1.0)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawRoundedRect(box, 4, 4)
                tag = region.label
                fill = QColor(theme.PANEL_HI)
                ink = QColor(theme.TEXT_DIM)

            painter.setFont(badge_font)
            metrics = QFontMetrics(badge_font)
            width = metrics.horizontalAdvance(tag) + 12
            height = metrics.height() + 4
            badge = QRect(box.left() + 3, box.top() + 3, width, height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(ink)
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), tag)

    def set_card_filter(self, quotes: bool, written: bool) -> None:
        """Choose whether plain highlights, notes, or both are listed."""
        if (quotes, written) == (self._show_quotes, self._show_written):
            return
        self._show_quotes, self._show_written = quotes, written
        # Drop a selection the filter has just hidden, so nothing is selected
        # but invisible.
        active = self._active_note
        if active is not None and not (written if active.note else quotes):
            self._active_note = None
        self.viewport().update()

    @property
    def card_filter(self) -> tuple[bool, bool]:
        return self._show_quotes, self._show_written

    def counts(self) -> tuple[int, int]:
        """How many plain highlights and how many notes the document holds."""
        if self._store is None:
            return 0, 0
        written = sum(1 for item in self._store.items if item.note)
        return len(self._store.items) - written, written

    def set_panel_footer_visible(self, visible: bool) -> None:
        """Hide the footer when there is nothing for it to act on."""
        self._footer_wanted = visible
        self._position_panel_widgets()

    def _panel_header_height(self) -> int:
        if self._panel_header is None or not self._show_notes:
            return 0
        return self._panel_header.sizeHint().height()

    def _panel_footer_height(self) -> int:
        if self._panel_footer is None or not self._show_notes or not self._footer_wanted:
            return 0
        return self._panel_footer.sizeHint().height()

    def _panel_body(self) -> QRect:
        """The strip of the panel where cards may be drawn."""
        top = self._panel_header_height()
        bottom = self.viewport().height() - self._panel_footer_height()
        return QRect(self._margin_starts_at(), top, NOTE_GUTTER, max(bottom - top, 0))

    def _position_panel_widgets(self) -> None:
        left, width = self._margin_starts_at(), NOTE_GUTTER
        height = self.viewport().height()
        if self._panel_header is not None:
            if self._show_notes:
                size = self._panel_header.sizeHint().height()
                self._panel_header.setGeometry(left, 0, width, size)
                self._panel_header.show()
                self._panel_header.raise_()
            else:
                self._panel_header.hide()
        if self._panel_footer is not None:
            if self._show_notes and self._footer_wanted:
                size = self._panel_footer.sizeHint().height()
                self._panel_footer.setGeometry(left, height - size, width, size)
                self._panel_footer.show()
                self._panel_footer.raise_()
            else:
                self._panel_footer.hide()

    def _relayout(self) -> None:
        """Work out where every page sits at the current zoom."""
        # Cards are measured in a font that scales with the zoom, so the column
        # gets taller or shorter here and a scroll position from before may now
        # be past its end.
        self._notes_scroll = min(
            self._notes_scroll, self._max_notes_scroll(self._notes_page()))
        self._sizes, self._offsets = [], []
        if self._document is None:
            self._content_width = 420
            self._column_width = 420
            self._total_height = 560
            self._update_scrollbars()
            self.viewport().update()
            return

        y = PAGE_MARGIN
        widest = 0
        for page in range(self._document.page_count):
            width, height = self._document.page_size(page)
            size = QSize(max(int(width * self._zoom), 1), max(int(height * self._zoom), 1))
            self._sizes.append(size)
            self._offsets.append(y)
            y += size.height() + PAGE_GAP
            widest = max(widest, size.width())

        self._content_width = widest
        self._column_width = widest + self._gutter_width()
        self._total_height = y - PAGE_GAP + PAGE_MARGIN
        self._update_scrollbars()
        self.viewport().update()

    # -- zoom and paging ---------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        zoom = max(0.4, min(zoom, 4.0))
        if abs(zoom - self._zoom) < 1e-6:
            return
        anchor_page, fraction = self._anchor_position()
        self._zoom = zoom
        self._cache.clear()
        self._relayout()
        self._restore_position(anchor_page, fraction)
        self.viewport().update()

    def _anchor_position(self) -> tuple[int, float]:
        """Where we are now, as a page and a fraction down it, to survive a zoom."""
        if not self._offsets:
            return 0, 0.0
        top, _ = self._viewport_band()
        page = self._page_at(top)
        into = top - self._offsets[page]
        height = max(self._sizes[page].height(), 1)
        return page, into / height

    def _restore_position(self, page: int, fraction: float) -> None:
        if not self._offsets:
            return
        page = max(0, min(page, len(self._offsets) - 1))
        target = self._offsets[page] + int(fraction * self._sizes[page].height())
        bar = self.verticalScrollBar()
        bar.setValue(max(0, min(target, bar.maximum())))

    @property
    def page(self) -> int:
        return self._current_page

    def set_page(self, page: int) -> None:
        """Scroll so a page starts at the top of the view."""
        if self._document is None or not self._offsets:
            return
        page = max(0, min(page, len(self._offsets) - 1))
        bar = self.verticalScrollBar()
        bar.setValue(max(0, min(self._offsets[page] - PAGE_MARGIN, bar.maximum())))

    def _page_at(self, y: int) -> int:
        """Which page covers a y position in the column."""
        if not self._offsets:
            return 0
        for page in range(len(self._offsets) - 1, -1, -1):
            if y >= self._offsets[page] - PAGE_GAP:
                return page
        return 0

    def _on_scrolled(self, _value: int) -> None:
        top, bottom = self._viewport_band()
        # The page occupying most of the view is the one we call current.
        page = self._page_at(top + (bottom - top) // 3)
        if page != self._current_page:
            self._current_page = page
            # A different page means a different set of notes, from the top.
            self._notes_scroll = 0
            self.page_changed.emit(page)
        self._trim_cache()

    # -- rendering ---------------------------------------------------------

    def _x_shift(self) -> int:
        """Offset that centres the page in the space left of the notes panel.

        The notes panel is pinned to the right edge of the window, so the page
        is centred within what remains rather than within the whole window.
        That way the two read as a document pane and a notes pane, instead of
        the page looking randomly off to one side.
        """
        available = self.viewport().width() - self._gutter_width()
        return max(0, (available - self._content_width) // 2)

    def _margin_starts_at(self) -> int:
        """Left edge of the notes panel, in viewport coordinates."""
        return self.viewport().width() - NOTE_GUTTER

    def _page_area(self) -> QRect:
        """The part of the window the page may occupy, left of the notes panel."""
        width = self.viewport().width() - self._gutter_width()
        return QRect(0, 0, max(width, 0), self.viewport().height())

    def _origin(self, page: int) -> QPoint:
        """Top-left of a page in document coordinates; pages are centred."""
        x = self._x_shift() + (self._content_width - self._sizes[page].width()) // 2
        return QPoint(x, self._offsets[page])

    def _visible_pages(self, rect: QRect) -> range:
        if not self._offsets:
            return range(0)
        first = self._page_at(rect.top())
        last = self._page_at(rect.bottom())
        first = max(0, first - RENDER_MARGIN)
        last = min(len(self._offsets) - 1, last + RENDER_MARGIN)
        return range(first, last + 1)

    def _pixmap_for(self, page: int) -> QPixmap:
        cached = self._cache.get(page)
        if cached is not None:
            self._cache.move_to_end(page)
            return cached

        screen = self.screen() or QGuiApplication.primaryScreen()
        ratio = max(screen.devicePixelRatio() if screen else 1.0, SUPERSAMPLE)
        self._supersample = ratio

        raw = self._document.render_page(page, self._zoom * ratio)
        image = QImage(raw.samples, raw.width, raw.height, raw.stride, QImage.Format.Format_RGB888)
        # copy() because the underlying MuPDF buffer is freed after this call.
        pixmap = QPixmap.fromImage(image.copy())
        # Telling Qt the ratio makes it draw the big pixmap at logical size.
        pixmap.setDevicePixelRatio(ratio)

        self._cache[page] = pixmap
        self._cache.move_to_end(page)
        self._trim_cache()
        return pixmap

    def _trim_cache(self) -> None:
        """Drop rendered pages that are far from the viewport."""
        while len(self._cache) > CACHE_PAGES:
            self._cache.popitem(last=False)

    def viewportEvent(self, event) -> bool:  # noqa: N802 - Qt naming
        """Qt sends the viewport's events here, so dispatch the ones we handle."""
        kind = event.type()
        if kind == QEvent.Type.Paint:
            self._paint(event)
            return True
        if kind == QEvent.Type.MouseButtonPress:
            self._on_press(event)
            return True
        if kind == QEvent.Type.MouseMove:
            self._on_move(event)
            return True
        if kind == QEvent.Type.MouseButtonRelease:
            self._on_release(event)
            return True
        if kind == QEvent.Type.MouseButtonDblClick:
            self._on_double_click(event)
            return True
        if kind == QEvent.Type.ContextMenu:
            return self._on_context_menu(event)
        return super().viewportEvent(event)

    def _on_context_menu(self, event) -> bool:
        """Right-click on the page: say what is under the cursor and let go."""
        if self._document is None:
            return False
        point = event.pos()
        if self._show_notes and point.x() >= self._margin_starts_at():
            return False          # the notes column has nothing to offer yet
        located = self._locate(point)
        if located is None:
            return False
        self.context_requested.emit(*located, self._annotation_at(point))
        event.accept()
        return True

    def _paint(self, event) -> None:
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(event.rect(), QColor(theme.BACKDROP))

        if self._document is None:
            painter.setPen(QColor(theme.TEXT_DIM))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                             "Open a PDF to start reading\n\nCtrl+O")
            return

        offset = self._scroll_offset()

        # Everything to do with the page is confined to its own pane, so a
        # zoomed-in page scrolls rather than sliding under the notes panel.
        painter.save()
        painter.setClipRect(self._page_area())

        # Only the pages overlapping the visible band are touched.
        band = event.rect().translated(offset)
        selection = self.selection
        pages = list(self._visible_pages(band))
        for page in pages:
            painter.drawPixmap(self._origin(page) - offset, self._pixmap_for(page))

            self._draw_page_highlights(painter, page)

            painter.setPen(Qt.PenStyle.NoPen)
            if selection is not None:
                painter.setBrush(QColor(*theme.SELECTION_TINT))
                for rect in self._page_rects(selection[0], selection[1], page):
                    painter.drawRoundedRect(self._to_widget(rect, page), 3, 3)

            if self._sentence is not None and any(w.page == page for w in self._sentence.words):
                painter.setBrush(QColor(*theme.SENTENCE_TINT))
                words = [w.rect for w in self._sentence.words if w.page == page]
                for rect in _merge_rects(words):
                    painter.drawRoundedRect(self._to_widget(rect, page), 3, 3)

                if 0 <= self._word_index < len(self._sentence.words):
                    word = self._sentence.words[self._word_index]
                    if word.page == page:
                        painter.setBrush(QColor(*theme.WORD_TINT))
                        painter.drawRoundedRect(self._to_widget(word.rect, page), 3, 3)

        painter.restore()

        if self._show_notes:
            # A darker strip, so it is obvious where notes will appear. Drawn
            # after the pages, so nothing can spill across it.
            panel = QRect(self._margin_starts_at(), 0, NOTE_GUTTER, self.viewport().height())
            painter.fillRect(panel, QColor(theme.NOTE_PANEL))
            painter.setPen(QColor(theme.BORDER))
            painter.drawLine(panel.left(), 0, panel.left(), panel.height())
            painter.setPen(Qt.PenStyle.NoPen)
            self._paint_note_layer(painter)

    def _paint_note_layer(self, painter: QPainter) -> None:
        """Draw the current page's cards, clipped clear of the docked widgets."""
        body = self._panel_body()
        if body.height() <= 0:
            return
        page = self._notes_page()
        painter.save()
        # Full width so the connector lines still reach the page, but limited
        # vertically so nothing spills under the docked widgets.
        painter.setClipRect(QRect(0, body.top(), self.viewport().width(), body.height()))
        self._draw_note_cards(painter, page)
        painter.restore()
        self._draw_scroll_hints(painter, page)

    def _draw_scroll_hints(self, painter: QPainter, page: int) -> None:
        """Show that the column carries on above or below what is on screen.

        Without this a page with more notes than fit simply looks like it has
        fewer, because the panel's scrolling is its own and nothing else on
        screen moves when you use it.
        """
        limit = self._max_notes_scroll(page)
        if limit <= 0:
            return
        body = self._panel_body()
        middle = self._margin_starts_at() + NOTE_GUTTER // 2
        painter.save()
        pen = QPen(QColor(theme.TEXT_DIM), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._notes_scroll > 0:
            y = body.top() + 5
            painter.drawLine(middle - 5, y + 3, middle, y)
            painter.drawLine(middle, y, middle + 5, y + 3)
        if self._notes_scroll < limit:
            y = body.bottom() - 5
            painter.drawLine(middle - 5, y - 3, middle, y)
            painter.drawLine(middle, y, middle + 5, y - 3)
        painter.restore()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """The notes column scrolls on its own; the page scrolls as usual."""
        if self._show_notes and event.position().x() >= self._margin_starts_at():
            page = self._notes_page()
            limit = self._max_notes_scroll(page)
            if limit > 0:
                delta = event.angleDelta().y() or event.angleDelta().x()
                if delta:
                    step = int(delta / 120 * NOTES_WHEEL_STEP)
                    moved = max(0, min(self._notes_scroll - step, limit))
                    if moved != self._notes_scroll:
                        self._notes_scroll = moved
                        self.viewport().update()
                    event.accept()
                    return
            # Nothing to scroll here: swallow it rather than moving the page
            # out from under the notes the reader is pointing at.
            event.accept()
            return
        super().wheelEvent(event)

    def _page_rects(self, first: int, last: int, page: int) -> list[tuple[float, float, float, float]]:
        if self._document is None:
            return []
        rects = [w.rect for w in self._document.words[first : last + 1] if w.page == page]
        return _merge_rects(rects)

    def _doc_rect(self, rect: tuple[float, float, float, float], page: int) -> QRect:
        """A PDF rectangle in document coordinates."""
        origin = self._origin(page)
        x0, y0, x1, y1 = (value * self._zoom for value in rect)
        return QRect(origin.x() + int(x0) - 1, origin.y() + int(y0) - 1,
                     int(x1 - x0) + 2, int(y1 - y0) + 2)

    def _to_widget(self, rect: tuple[float, float, float, float], page: int) -> QRect:
        """The same rectangle, shifted into the viewport."""
        return self._doc_rect(rect, page).translated(-self._scroll_offset())

    # -- annotations -------------------------------------------------------

    def set_store(self, store) -> None:
        # No re-layout here: the panel's width does not depend on the notes, and
        # re-laying out would touch a document that may have just been replaced.
        self._store = store
        self._active_note = None
        self.viewport().update()

    def refresh_annotations(self) -> None:
        """Redraw the notes. The panel's width no longer depends on them."""
        self.viewport().update()

    @property
    def notes_visible(self) -> bool:
        return self._show_notes

    def set_notes_visible(self, visible: bool) -> None:
        if visible == self._show_notes:
            return
        self._show_notes = visible
        self._position_panel_widgets()
        self._relayout()

    def set_active_note(self, item) -> None:
        self._active_note = item
        if item is not None:
            self._reveal_card(item)
        self.refresh_annotations()

    def _reveal_card(self, item) -> None:
        """Scroll the notes column so a card is on screen, if it is not already.

        Selecting a highlight on the page has to bring its card into the panel:
        the column is only as tall as the window, and on a page with a dozen
        notes the one you just clicked is as likely as not below the fold.
        """
        page = self._notes_page()
        if item.page != page:
            return
        body = self._panel_body()
        for placed, rect in self._layout_notes(page):
            if placed is not item:
                continue
            if rect.top() < body.top() + CARD_GAP:
                shift = rect.top() - (body.top() + CARD_GAP)
            elif rect.bottom() > body.bottom() - CARD_GAP:
                shift = rect.bottom() - (body.bottom() - CARD_GAP)
            else:
                return
            limit = self._max_notes_scroll(page)
            self._notes_scroll = max(0, min(self._notes_scroll + shift, limit))
            return

    def scroll_to_annotation(self, item) -> None:
        """Bring a highlight into view, a third of the way down."""
        if item is None or item.page >= len(self._offsets):
            return
        top = self._offsets[item.page] + int(item.top * self._zoom)
        bar = self.verticalScrollBar()
        # Moving the page settles which notes the panel shows and puts the
        # column back to the top, so the card is placed after this, not before.
        bar.setValue(max(0, min(top - self.viewport().height() // 3, bar.maximum())))
        self.set_active_note(item)

    def set_note_style(self, family: str, size: float) -> None:
        self._note_family = family or ""
        self._note_size = max(6.0, min(float(size), 24.0))
        self.viewport().update()

    @property
    def note_style(self) -> tuple[str, float]:
        return self._note_family, self._note_size

    def _annotation_font(self) -> QFont:
        """Notes grow and shrink with the page, like the text they sit beside."""
        font = QFont(self._note_family) if self._note_family else QFont(self.font())
        scaled = self._note_size * self._zoom
        font.setPointSizeF(max(6.0, min(scaled, 40.0)))
        return font

    def _heading_font(self) -> QFont:
        font = QFont(self._annotation_font())
        font.setBold(True)
        return font

    @staticmethod
    def _wrapped_height(font: QFont, width: int, text: str) -> int:
        """How tall `text` is once wrapped to `width`, in this font."""
        if not text:
            return 0
        return QFontMetrics(font).boundingRect(
            QRect(0, 0, width, 10_000), int(Qt.TextFlag.TextWordWrap), text,
        ).height()

    def _notes_page(self) -> int:
        """The page whose notes the panel is showing: the one you are reading."""
        return self._current_page

    def _card_sizes(self, page: int) -> list[tuple[object, int]]:
        """Each card on a page and how tall it needs to be, in stacking order.

        Order is the order the highlights appear down the page, so the column
        reads the same way the page does even though the cards no longer line
        up with the passages they belong to.
        """
        if self._store is None or not self._show_notes:
            return []
        # The filter wins even over the selected card: a chip switched off
        # should empty the column, not leave the last-touched note pinned there.
        items = [
            item for item in self._store.for_page(page)
            if (self._show_written if item.note else self._show_quotes)
        ]
        if not items:
            return []

        font = self._annotation_font()
        heading_font = self._heading_font()
        text_width = NOTE_GUTTER - NOTE_PAD * 2 - CARD_PAD * 2

        sizes: list[tuple[object, int]] = []
        for item in sorted(items, key=lambda a: a.top):
            # The heading is bold and wraps on its own, so it has to be
            # measured in its own font -- measuring it as the first line of the
            # body made the card too short and the title ran off the edge.
            needed = self._wrapped_height(font, text_width, item.note or item.preview)
            if item.heading:
                needed += self._wrapped_height(
                    heading_font, text_width, item.heading) + HEADING_GAP
            sizes.append((item, max(needed + CARD_PAD * 2, CARD_MIN_HEIGHT)))
        return sizes

    def _notes_extent(self, page: int) -> int:
        """How tall the whole stack of a page's cards is, gaps included."""
        sizes = self._card_sizes(page)
        if not sizes:
            return 0
        return sum(height for _, height in sizes) + CARD_GAP * (len(sizes) + 1)

    def _max_notes_scroll(self, page: int) -> int:
        return max(0, self._notes_extent(page) - self._panel_body().height())

    def _layout_notes(self, page: int) -> list[tuple[object, QRect]]:
        """Place a page's note cards in the panel, in viewport coordinates.

        The stack starts at the top of the column and works down, rather than
        each card floating beside the passage it belongs to. Two notes a line
        apart used to shove each other down the page and a note near the foot
        of a long page sat below the window entirely; the connector line is
        what ties a card to its highlight now, not its height on the screen.
        """
        sizes = self._card_sizes(page)
        if not sizes:
            return []
        body = self._panel_body()
        left = self._margin_starts_at() + NOTE_PAD
        width = NOTE_GUTTER - NOTE_PAD * 2

        placed: list[tuple[object, QRect]] = []
        cursor = body.top() + CARD_GAP - self._notes_scroll
        for item, height in sizes:
            placed.append((item, QRect(left, cursor, width, height)))
            cursor += height + CARD_GAP
        return placed

    def _draw_page_highlights(self, painter: QPainter, page: int) -> None:
        """Paint the highlight tint over the words on the page."""
        if self._store is None:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        for item in self._store.for_page(page):
            red, green, blue = item.colour
            alpha = 150 if item is self._active_note else 105
            painter.setBrush(QColor(int(red * 255), int(green * 255), int(blue * 255), alpha))
            for rect in item.rects:
                painter.drawRoundedRect(self._to_widget(rect, page), 2, 2)

    def _draw_note_cards(self, painter: QPainter, page: int) -> None:
        """Paint this page's note cards in the panel."""
        if self._store is None or not self._show_notes:
            return

        font = self._annotation_font()
        painter.setFont(font)

        for item, card in self._layout_notes(page):
            red, green, blue = item.colour
            accent = QColor(int(red * 255), int(green * 255), int(blue * 255))
            active = item is self._active_note

            # A line from the highlighted words out to the card.
            if item.rects:
                anchor = self._to_widget(item.rects[0], page)
                start = min(anchor.right() + 2, self._margin_starts_at() - 2)
                painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 120), 1.2))
                painter.drawLine(start, anchor.center().y(), card.left() - 4, card.top() + 14)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.PANEL_HI if active else theme.PANEL))
            painter.drawRoundedRect(card, 7, 7)
            if active:
                painter.setPen(QPen(accent, 1.4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(card, 7, 7)

            # The colour of the highlight, as a stripe down the card's edge.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRect(card.left(), card.top() + 6, 3, card.height() - 12), 2, 2)

            text_area = card.adjusted(CARD_PAD, CARD_PAD, -CARD_PAD, -CARD_PAD)
            heading = item.heading
            if heading:
                bold = self._heading_font()
                tall = self._wrapped_height(bold, text_area.width(), heading)
                painter.setFont(bold)
                painter.setPen(QColor(theme.TEXT))
                painter.drawText(
                    QRect(text_area.left(), text_area.top(), text_area.width(), tall),
                    int(Qt.TextFlag.TextWordWrap), heading,
                )
                text_area = text_area.adjusted(0, tall + HEADING_GAP, 0, 0)
                painter.setFont(font)
            if item.note:
                painter.setPen(QColor(theme.TEXT))
            else:
                painter.setPen(QColor(theme.TEXT_DIM))
                italic = QFont(font)
                italic.setItalic(True)
                painter.setFont(italic)
            painter.drawText(text_area, int(Qt.TextFlag.TextWordWrap),
                             item.note or item.preview)
            painter.setFont(font)

    def _annotation_at(self, point: QPoint):
        """A note card or highlight under a viewport point, if any."""
        if self._store is None:
            return None
        if self._show_notes and point.x() >= self._margin_starts_at():
            body = self._panel_body()
            if not body.contains(point):
                return None
            for item, rect in self._layout_notes(self._notes_page()):
                if rect.contains(point):
                    return item
            return None
        located = self._locate(point)
        if located is None:
            return None
        page, x, y = located
        for item in self._store.for_page(page):
            if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in item.rects):
                return item
        return None

    # -- highlight ---------------------------------------------------------

    def set_highlight(self, sentence: Sentence | None, word_index: int = -1) -> None:
        if sentence is not self._sentence or word_index != self._word_index:
            self._sentence = sentence
            self._word_index = word_index
            self.viewport().update()

    def clear_highlight(self) -> None:
        self.set_highlight(None, -1)

    def highlight_rect(self) -> QRect | None:
        """Where the spoken sentence sits, in widget coordinates."""
        if self._sentence is None or not self._offsets:
            return None
        combined: QRect | None = None
        for page in {w.page for w in self._sentence.words}:
            if page >= len(self._offsets):
                continue
            words = [w.rect for w in self._sentence.words if w.page == page]
            for rect in _merge_rects(words):
                box = self._doc_rect(rect, page)
                combined = box if combined is None else combined.united(box)
        return combined

    def ensure_highlight_visible(self) -> None:
        """Keep the spoken line about a third of the way down the view."""
        rect = self.highlight_rect()
        if rect is None:
            return
        bar = self.verticalScrollBar()
        viewport = self.viewport().height()
        if bar.value() <= rect.top() and rect.bottom() <= bar.value() + viewport:
            return          # already comfortably on screen, so leave it alone
        target = rect.center().y() - viewport // 3
        bar.setValue(max(0, min(target, bar.maximum())))

    # -- text selection ----------------------------------------------------

    @property
    def selection(self) -> tuple[int, int] | None:
        if self._anchor < 0 or self._focus < 0:
            return None
        return (min(self._anchor, self._focus), max(self._anchor, self._focus))

    def clear_selection(self) -> None:
        had = self.selection is not None
        self._anchor = self._focus = -1
        self._dragging = False
        if had:
            self.selection_changed.emit(-1, -1)
        self.viewport().update()

    def select_range(self, first: int, last: int) -> None:
        self._anchor, self._focus = first, last
        self.viewport().update()
        self.selection_changed.emit(*self.selection)

    # -- interaction -------------------------------------------------------

    def _locate(self, point: QPoint) -> tuple[int, float, float] | None:
        """Map a viewport point to a page and PDF coordinates on it."""
        if self._document is None or not self._offsets:
            return None
        if self._show_notes and point.x() >= self._margin_starts_at():
            return None          # that is the notes panel, not the page
        point = point + self._scroll_offset()
        page = self._page_at(point.y())
        origin = self._origin(page)
        return page, (point.x() - origin.x()) / self._zoom, (point.y() - origin.y()) / self._zoom

    def _on_press(self, event) -> None:
        if self._document is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._press_point = event.position().toPoint()
        self._dragging = False

        # A click on a highlight or its note card picks that up instead of
        # starting a new text selection.
        existing = self._annotation_at(self._press_point)
        if existing is not None:
            self.clear_selection()
            self.set_active_note(existing)
            self.annotation_clicked.emit(existing)
            return
        if self._active_note is not None:
            self.set_active_note(None)

        located = self._locate(self._press_point)
        if located is None:
            return
        word = self._document.word_at_point(*located)
        if word is None:
            # Starting off the text clears any selection, as in a normal reader.
            self.clear_selection()
            return
        self._anchor = self._focus = word.index
        self.viewport().update()

    def _on_move(self, event) -> None:
        if self._document is None or self._anchor < 0 or self._press_point is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        point = event.position().toPoint()
        if not self._dragging and (point - self._press_point).manhattanLength() < 4:
            return
        self._dragging = True
        located = self._locate(point)
        if located is None:
            return
        page, x, y = located
        word = self._document.word_at_point(page, x, y, pad=4.0)
        if word is None:
            word = self._document.nearest_word_on_line(page, x, y)
        if word is not None and word.index != self._focus:
            self._focus = word.index
            self.viewport().update()

    def _on_release(self, event) -> None:
        if self._document is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging and self.selection is not None:
            self._dragging = False
            self.selection_changed.emit(*self.selection)
            return
        self._dragging = False
        located = self._locate(event.position().toPoint())
        if located is None:
            return
        if self._show_plan:
            region = self._document.region_at(*located)
            if region is not None:
                self.region_clicked.emit(region)
                return
        # A plain click with no drag: report it and drop the one-word selection.
        if self._document.word_at_point(*located) is not None:
            self._anchor = self._focus = -1
            self.viewport().update()
            self.clicked.emit(*located)

    def _on_double_click(self, event) -> None:
        """Double-click opens an annotation, or selects the sentence under the cursor."""
        if self._document is None or event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        existing = self._annotation_at(point)
        if existing is not None:
            self.set_active_note(existing)
            self.annotation_activated.emit(existing)
            return
        located = self._locate(point)
        if located is None:
            return
        word = self._document.word_at_point(*located)
        if word is None or word.sentence < 0:
            return
        words = self._document.sentences[word.sentence].words
        self.select_range(words[0].index, words[-1].index)
