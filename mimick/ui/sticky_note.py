"""Sticky notes on the page: a text box you type straight into.

Kat asked for these on 29 September 2026: a note that is part of the PDF, the
way a text box is in Acrobat -- moved and resized while you work, saved in
place, and editable again when the saved file is opened. Each one is a
``Sticky`` in the annotation store (``annotations.py``), which the browser
version shares; this is only how the desktop shows and edits one.

The box on the page is only the words. Their size, bold, italics, underline,
strikeout, list and colour are on the Highlight / Add note bar
(``StickyFormatRow``, carried by the markup bar), which lights up while a
sticky has the cursor. The usual keys work in the box itself.

Words on a sticky are in points on the page, so they grow and shrink with the
zoom like the document's own. The store keeps ``font-size:18pt``; the editor is
given that times ``scale`` -- the zoom, over the screen's points per pixel --
and its HTML is turned back on the way out (``to_editor``, ``from_editor``).
Fractional points, not pixels: a whole number of pixels at 125% turned 18pt
into 17.5.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QKeySequence, QPainter, QPen, QTextCharFormat,
                           QTextCursor, QTextListFormat)
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QPushButton, QTextEdit,
                               QToolButton, QWidget)

from ..annotations import STICKY_MIN, STICKY_PAD, STICKY_SIZE, STICKY_SIZES, clean_rich

COMMIT_MS = 600             # typing is written to the store this long after it stops
GRIP_HEIGHT = 16            # the bar above a sticky that drags it
FONT_FAMILY = "Helvetica"   # annotations.STICKY_FONT's first choice; Qt falls back to a sans

_POINTS = re.compile(r"font-size:\s*([\d.]+)pt")
_PIXELS = re.compile(r"font-size:\s*([\d.]+)px")


def to_editor(rich: str, scale: float) -> str:
    """A sticky's rich text as the editor shows it, its sizes times ``scale``."""
    return _POINTS.sub(lambda m: f"font-size:{float(m.group(1)) * scale:.3f}pt", rich or "")


def from_editor(html: str, scale: float, pixel_scale: float) -> str:
    """The editor's HTML as a sticky keeps it: sizes back in page points, cleaned."""
    html = _POINTS.sub(lambda m: f"font-size:{float(m.group(1)) / scale:.3f}pt", html)
    html = _PIXELS.sub(lambda m: f"font-size:{float(m.group(1)) / pixel_scale:.3f}pt", html)
    return clean_rich(html)


def _qcolour(colour, scale: float = 1.0) -> QColor:
    red, green, blue = colour
    return QColor(int(red * 255 * scale), int(green * 255 * scale), int(blue * 255 * scale))


# The keys a sticky answers while it is typed in, as the shortcuts window lists
# them; tools/check_shortcuts.py counts these as bound.
LISTED_KEYS = ("Ctrl+B", "Ctrl+I", "Ctrl+U", "Ctrl+Shift+X", "Ctrl+]", "Ctrl+[", "Ctrl+Shift+8", "Esc")


class StickyEditor(QTextEdit):
    """The words of one sticky, formatted as you type."""

    finished = Signal()                 # Esc, or Ctrl+Enter
    format_changed = Signal()           # the cursor moved into other formatting

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.zoom = 1.0
        self.scale = 1.0                # a page point, in the editor's own points
        self.setAcceptRichText(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setStyleSheet("QTextEdit { background: transparent; color: black; border: 0; }")
        self.cursorPositionChanged.connect(self.format_changed)
        self.selectionChanged.connect(self.format_changed)

    def set_zoom(self, zoom: float) -> None:
        self.zoom = zoom
        # A page point is `zoom` pixels on screen; the editor's point is dpi/72.
        self.scale = zoom * 72.0 / max(1, self.logicalDpiY())
        font = QFont(FONT_FAMILY)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        font.setPointSizeF(STICKY_SIZE * self.scale)
        document = self.document()
        document.setDefaultFont(font)
        document.setDocumentMargin(STICKY_PAD * zoom)
        document.setDefaultStyleSheet(
            f"p {{ margin-top: 0; margin-bottom: 0; }} "
            f"ul {{ margin-top: {4 * zoom:.1f}px; margin-bottom: {4 * zoom:.1f}px; }}")

    def set_rich(self, rich: str) -> None:
        self.setHtml(to_editor(rich, self.scale))

    def rich(self) -> str:
        return from_editor(self.toHtml(), self.scale, self.zoom)

    # -- keys --------------------------------------------------------------

    _MINE = {
        "Ctrl+B", "Ctrl+I", "Ctrl+U", "Ctrl+Shift+X", "Ctrl+]", "Ctrl+[", "Ctrl+Shift+*", "Ctrl+*",
        "Ctrl+Z", "Ctrl+Y", "Ctrl+Shift+Z", "Ctrl+A", "Ctrl+C", "Ctrl+X", "Ctrl+V",
        "Ctrl+Return", "Ctrl+Enter", "Esc",
    }

    def event(self, event) -> bool:  # noqa: D102 - Qt naming
        # A window shortcut beats a focused widget's own keys unless the widget
        # claims them first. These are the sticky's while it is being typed in:
        # Ctrl+B is bold here, and the notes panel everywhere else.
        if event.type() == event.Type.ShortcutOverride:
            if self._sequence(event) in self._MINE or (event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier
                                                        == Qt.KeyboardModifier.NoModifier and event.text()):
                event.accept()
                return True
        return super().event(event)

    @staticmethod
    def _sequence(event) -> str:
        key = event.key()
        if key == Qt.Key.Key_Asterisk or (key == Qt.Key.Key_8 and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            key = Qt.Key.Key_Asterisk
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        return QKeySequence(mods.value | key).toString()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        sequence = self._sequence(event)
        actions = {
            "Ctrl+B": "bold", "Ctrl+I": "italic", "Ctrl+U": "underline", "Ctrl+Shift+X": "strike",
            "Ctrl+]": "bigger", "Ctrl+[": "smaller", "Ctrl+Shift+*": "list", "Ctrl+*": "list",
        }
        if sequence in actions:
            self.apply(actions[sequence])
            return
        if sequence in ("Esc", "Ctrl+Return", "Ctrl+Enter"):
            self.finished.emit()
            return
        super().keyPressEvent(event)

    # -- formatting --------------------------------------------------------

    def size_here(self) -> float:
        """The text size where the cursor is, in page points."""
        points = self.currentCharFormat().fontPointSize() or self.currentCharFormat().font().pointSizeF()
        if not points or points <= 0:
            return float(STICKY_SIZE)
        return round(float(points) / self.scale * 2) / 2

    def state(self) -> dict:
        now = self.currentCharFormat()
        return {"bold": now.fontWeight() >= QFont.Weight.DemiBold.value, "italic": now.fontItalic(),
                "underline": now.fontUnderline(), "strike": now.fontStrikeOut(),
                "list": self.textCursor().currentList() is not None, "size": self.size_here()}

    def apply(self, what: str, value=None) -> None:
        """Format the selection, or what is typed next: from a key or the bar."""
        state = self.state()
        change = QTextCharFormat()
        if what == "bold":
            change.setFontWeight(QFont.Weight.Normal.value if state["bold"] else QFont.Weight.Bold.value)
        elif what == "italic":
            change.setFontItalic(not state["italic"])
        elif what == "underline":
            change.setFontUnderline(not state["underline"])
        elif what == "strike":
            change.setFontStrikeOut(not state["strike"])
        elif what in ("size", "bigger", "smaller"):
            now = state["size"]
            if what == "bigger":
                value = next((s for s in STICKY_SIZES if s > now), STICKY_SIZES[-1])
            elif what == "smaller":
                value = next((s for s in reversed(STICKY_SIZES) if s < now), STICKY_SIZES[0])
            change.setFontPointSize(float(value) * self.scale)
        elif what == "list":
            cursor = self.textCursor()
            current = cursor.currentList()
            if current is not None:
                block = cursor.block()
                current.remove(block)
                block_format = cursor.blockFormat()
                block_format.setIndent(0)
                cursor.setBlockFormat(block_format)
            else:
                cursor.createList(QTextListFormat.Style.ListDisc)
            self.format_changed.emit()
            self.setFocus()
            return
        self.mergeCurrentCharFormat(change)
        self.format_changed.emit()
        self.setFocus()


class _Grip(QWidget):
    """The bar above a sticky: drag it to move the note; fold and delete it."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to move this sticky note")
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(2)
        row.addStretch(1)
        self.fold = QToolButton(self)
        self.fold.setText("▾")
        self.fold.setToolTip("Fold it away to a small tab")
        self.delete = QToolButton(self)
        self.delete.setText("×")
        self.delete.setToolTip("Delete this sticky note")
        for button in (self.fold, self.delete):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoRaise(True)
            button.setFixedSize(GRIP_HEIGHT, GRIP_HEIGHT)
            button.setStyleSheet("QToolButton { color: white; border: 0; font-size: 12px; }"
                                 "QToolButton:hover { background: rgba(0,0,0,60); }")
            row.addWidget(button)
        self.edge = QColor(120, 100, 40)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.edge)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, 0, 4), 4, 4)


class StickyNote(QWidget):
    """One sticky on the page: the grip, the words, and a corner to resize by.

    The page view places it and hands it the zoom; everything it does to the
    note -- move, resize, fold, delete, type -- goes out as a signal, and the
    window makes the change in the store.
    """

    moved = Signal(object, tuple)        # the sticky, its new rectangle in points
    typed = Signal(object)               # the sticky, its words changed (debounced)
    folding = Signal(object, bool)       # the sticky, fold it or not
    delete_requested = Signal(object)
    menu_requested = Signal(object, QPoint)
    focused = Signal(object, bool)       # the sticky, being typed in or not
    format_changed = Signal()

    def __init__(self, item, parent: QWidget) -> None:
        super().__init__(parent)
        self.item = item
        self.page_scale = 1.0              # pixels per point on screen
        self._shown_rich: str | None = None
        self._drag: tuple[str, QPoint, tuple] | None = None
        self._preview: tuple | None = None
        self._start_pos = QPoint()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self.grip = _Grip(self)
        self.grip.fold.clicked.connect(lambda: self.folding.emit(self.item, True))
        self.grip.delete.clicked.connect(lambda: self.delete_requested.emit(self.item))
        self.grip.installEventFilter(self)

        self.editor = StickyEditor(self)
        self.editor.installEventFilter(self)
        self.editor.format_changed.connect(self.format_changed)
        self.editor.finished.connect(self._finish)
        self.editor.textChanged.connect(self._on_text)

        self.tab = QPushButton("✎", self)
        self.tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tab.setToolTip("Open this sticky note")
        self.tab.clicked.connect(lambda: self.folding.emit(self.item, False))

        self._commit = QTimer(self)
        self._commit.setSingleShot(True)
        self._commit.setInterval(COMMIT_MS)
        self._commit.timeout.connect(lambda: self.typed.emit(self.item))
        self._loading = False
        self.show_item(item)

    # -- showing -----------------------------------------------------------

    @property
    def editing(self) -> bool:
        return self.editor.hasFocus()

    def show_item(self, item) -> None:
        """Take the store's latest for this sticky; the words only if nobody is typing."""
        self.item = item
        if self._shown_rich != item.rich and not self.editing:
            self._loading = True
            self.editor.set_rich(item.rich)
            self._loading = False
            self._shown_rich = item.rich
        self.grip.edge = _qcolour(item.colour, 0.72)
        self.grip.setVisible(not item.folded)
        self.editor.setVisible(not item.folded)
        self.tab.setVisible(item.folded)
        tip = " ".join(item.text.split())[:80] or "empty"
        self.tab.setToolTip(f"Sticky note: {tip} — click to open")
        self.update()

    def set_zoom(self, zoom: float) -> None:
        if abs(zoom - self.editor.zoom) < 1e-6:
            return
        # The words are kept in points and shown in pixels, so a zoom sets them
        # again -- from what is being typed, if something is.
        rich = self.editor.rich() if self.editing else self.item.rich
        position = self.editor.textCursor().position()
        self.editor.set_zoom(zoom)
        self._loading = True
        self.editor.set_rich(rich)
        self._loading = False
        cursor = self.editor.textCursor()
        cursor.setPosition(min(position, len(self.editor.toPlainText())))
        self.editor.setTextCursor(cursor)

    def place(self, box: QRect) -> None:
        """Put the note over ``box``, its rectangle on screen; the grip sits above."""
        if self.item.folded:
            size = max(18, round(16 * self.page_scale))
            self.setGeometry(box.left(), box.top(), size, size)
            self.tab.setGeometry(0, 0, size, size)
            return
        body = box
        wanted = self.editor.document().size().height()
        if wanted > body.height():
            body = QRect(body.left(), body.top(), body.width(), int(wanted) + 1)
        self.setGeometry(body.left(), body.top() - GRIP_HEIGHT, body.width(), body.height() + GRIP_HEIGHT)
        self.grip.setGeometry(0, 0, body.width(), GRIP_HEIGHT)
        self.editor.setGeometry(0, GRIP_HEIGHT, body.width(), body.height())

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        if self.item.folded:
            painter.setBrush(_qcolour(self.item.colour))
            painter.setPen(QPen(_qcolour(self.item.colour, 0.72), 1))
            painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 3, 3)
            return
        paper = self.rect().adjusted(0, GRIP_HEIGHT, -1, -1)
        painter.setBrush(_qcolour(self.item.colour))
        painter.setPen(QPen(_qcolour(self.item.colour, 0.72), 1))
        painter.drawRect(paper)
        if self.editing or self.property("picked"):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(91, 157, 255), 2))
            painter.drawRect(paper.adjusted(-1, -1, 1, 1))
        # The corner that resizes it.
        corner = QRect(paper.right() - 9, paper.bottom() - 9, 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_qcolour(self.item.colour, 0.72))
        painter.drawPolygon([corner.topRight(), corner.bottomRight(), corner.bottomLeft()])

    # -- typing ------------------------------------------------------------

    def _on_text(self) -> None:
        if self._loading:
            return
        self._commit.start()

    def written(self) -> str:
        """The words as they now stand, as the store keeps them."""
        return self.editor.rich()

    def flush(self) -> bool:
        """Say now what is waiting to be said about the words. True if anything was."""
        if self._commit.isActive():
            self._commit.stop()
            self.typed.emit(self.item)
            return True
        return False

    def _finish(self) -> None:
        self.editor.clearFocus()
        self.parentWidget().setFocus()

    def focus(self) -> None:
        self.editor.setFocus()
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)

    # -- moving and resizing -------------------------------------------------

    def _in_corner(self, point: QPoint) -> bool:
        return (not self.item.folded and point.x() >= self.width() - 12
                and point.y() >= self.height() - 12)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        kind = event.type()
        if watched is self.editor and kind == event.Type.FocusIn:
            self.focused.emit(self.item, True)
            self.update()
        elif watched is self.editor and kind == event.Type.FocusOut:
            # The size list or the colour menu opening is not leaving the note.
            if event.reason() == Qt.FocusReason.PopupFocusReason:
                return super().eventFilter(watched, event)
            self.flush()
            self.focused.emit(self.item, False)
            self.update()
        elif watched is self.grip and kind == event.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._start("move", event.globalPosition().toPoint())
                return True
            if event.button() == Qt.MouseButton.RightButton:
                self.menu_requested.emit(self.item, event.globalPosition().toPoint())
                return True
        elif watched is self.grip and kind == event.Type.MouseMove and self._drag:
            self._follow(event.globalPosition().toPoint())
            return True
        elif watched is self.grip and kind == event.Type.MouseButtonRelease and self._drag:
            self._end()
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton and self._in_corner(event.position().toPoint()):
            self._start("size", event.globalPosition().toPoint())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._drag:
            self._follow(event.globalPosition().toPoint())
            return
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if self._in_corner(event.position().toPoint())
                       else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._drag:
            self._end()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.menu_requested.emit(self.item, event.globalPos())

    def _start(self, kind: str, at: QPoint) -> None:
        self.flush()
        self._drag = (kind, at, tuple(self.item.rect))
        self._preview = tuple(self.item.rect)
        self._start_pos = self.pos()

    def _follow(self, at: QPoint) -> None:
        kind, start, rect = self._drag
        dx = (at.x() - start.x()) / self.page_scale
        dy = (at.y() - start.y()) / self.page_scale
        x0, y0, x1, y1 = rect
        if kind == "move":
            self._preview = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
            self.move(self._start_pos + (at - start))
            return
        self._preview = (x0, y0, max(x0 + STICKY_MIN, x1 + dx), max(y0 + STICKY_MIN, y1 + dy))
        width = round((self._preview[2] - x0) * self.page_scale)
        height = round((self._preview[3] - y0) * self.page_scale)
        self.place(QRect(self.x(), self.y() + GRIP_HEIGHT, width, height))

    def _end(self) -> None:
        _kind, _start, rect = self._drag
        self._drag = None
        if self._preview and any(abs(a - b) >= 0.5 for a, b in zip(self._preview, rect)):
            self.moved.emit(self.item, self._preview)
        self._preview = None


class StickyFormatRow(QWidget):
    """Size, bold, italic, underline, strikeout, list and colour, for the
    sticky being typed in. Carried by the markup bar, so it goes wherever
    Highlight and Add note go. None of it takes the keyboard: a press here must
    leave the cursor in the note."""

    format_requested = Signal(str, object)     # what, and a size or colour
    colour_requested = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.size_box = QComboBox(self)
        self.size_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.size_box.setToolTip("Text size, in points  (Ctrl+] bigger, Ctrl+[ smaller)")
        for size in STICKY_SIZES:
            self.size_box.addItem(str(size), size)
        self.size_box.activated.connect(
            lambda index: self.format_requested.emit("size", self.size_box.itemData(index)))
        row.addWidget(self.size_box)
        self.buttons: dict[str, QToolButton] = {}
        for what, label, tip in (("bold", "B", "Bold  (Ctrl+B)"), ("italic", "I", "Italic  (Ctrl+I)"),
                                 ("underline", "U", "Underline  (Ctrl+U)"),
                                 ("strike", "S", "Strikeout  (Ctrl+Shift+X)"),
                                 ("list", "•≡", "Bullet list  (Ctrl+Shift+8)")):
            button = QToolButton(self)
            button.setText(label)
            button.setToolTip(tip)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            font = button.font()
            font.setBold(what == "bold")
            font.setItalic(what == "italic")
            font.setUnderline(what == "underline")
            font.setStrikeOut(what == "strike")
            button.setFont(font)
            button.clicked.connect(lambda _checked=False, w=what: self.format_requested.emit(w, None))
            row.addWidget(button)
            self.buttons[what] = button
        self.colour = QToolButton(self)
        self.colour.setToolTip("Sticky note colour — this one, or the next one you add")
        self.colour.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.colour.clicked.connect(
            lambda: self.colour_requested.emit(self.colour.mapToGlobal(QPoint(0, self.colour.height()))))
        row.addWidget(self.colour)
        row.addStretch(1)
        self.show_state(None)

    def show_state(self, state: dict | None) -> None:
        live = state is not None
        self.size_box.setEnabled(live)
        for what, button in self.buttons.items():
            button.setEnabled(live)
            button.setChecked(bool(live and state.get(what)))
        if live:
            size = state.get("size", STICKY_SIZE)
            nearest = min(STICKY_SIZES, key=lambda s: abs(s - size))
            self.size_box.setCurrentIndex(STICKY_SIZES.index(nearest))

