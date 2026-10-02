"""A small editor for the note attached to a highlight."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QKeySequence, QPainter,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFontComboBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ..annotations import COLOURS
from . import theme


def colour_swatch(colour: tuple[float, float, float], size: int = 14) -> QPixmap:
    """A round chip of colour, for buttons and menus."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    red, green, blue = colour
    painter.setBrush(QColor(int(red * 255), int(green * 255), int(blue * 255)))
    painter.drawEllipse(0, 0, size - 1, size - 1)
    painter.end()
    return pixmap


class NoteCardPreview(QWidget):
    """A small stand-in for the card as it will look in the margin."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._title = ""
        self._colour = COLOURS[0][1]
        self._family = ""
        self._size = 9.0
        self.setMinimumHeight(74)

    def set_card(self, text: str, colour, family: str = None,
                 size: float = None, title: str = None) -> None:
        self._text = text
        if title is not None:
            self._title = title
        self._colour = colour
        if family is not None:
            self._family = family
        if size is not None:
            self._size = size
        self.update()

    def _font(self) -> QFont:
        font = QFont(self._family) if self._family else QFont(self.font())
        font.setPointSizeF(max(6.0, min(self._size, 40.0)))
        return font

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # The strip the card sits on, as in the notes panel.
        painter.fillRect(self.rect(), QColor(theme.NOTE_PANEL))

        card = self.rect().adjusted(10, 8, -10, -8)
        red, green, blue = self._colour
        accent = QColor(int(red * 255), int(green * 255), int(blue * 255))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.PANEL))
        painter.drawRoundedRect(card, 7, 7)
        painter.setBrush(accent)
        painter.drawRoundedRect(QRect(card.left(), card.top() + 6, 3, card.height() - 12), 2, 2)

        area = card.adjusted(14, 10, -10, -10)
        heading = self._title.strip()
        if heading:
            bold = self._font()
            bold.setBold(True)
            painter.setFont(bold)
            painter.setPen(QColor(theme.TEXT))
            line = QFontMetrics(bold).height()
            painter.drawText(area, int(Qt.TextFlag.TextSingleLine), heading)
            area = area.adjusted(0, line + 2, 0, 0)

        painter.setFont(self._font())
        body = self._text.strip()
        painter.setPen(QColor(theme.TEXT if body else theme.TEXT_DIM))
        painter.drawText(area, int(Qt.TextFlag.TextWordWrap),
                         body or "Your note appears here")


class NoteDialog(QDialog):
    """Write or change the note on a highlight, and pick its colour.

    Emits ``changed`` on every keystroke and colour pick, so the card out in the
    margin updates as you type rather than only when the dialog closes.
    """

    changed = Signal(str, object)      # note text, colour

    def __init__(self, item, style: tuple[str, float] = ("", 9.0),
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._colour = item.colour
        self.deleted = False

        self.setWindowTitle("Note")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        quoted = QLabel(f"“{item.preview}”")
        quoted.setWordWrap(True)
        quoted.setObjectName("Dim")
        layout.addWidget(quoted)

        self.title_edit = QLineEdit(item.title)
        self.title_edit.setPlaceholderText("Heading (optional) \u2014 shown by other PDF readers")
        self.title_edit.textChanged.connect(self._announce)
        layout.addWidget(self.title_edit)

        self.editor = QTextEdit()
        self.editor.setPlainText(item.note)
        self.editor.setPlaceholderText("Write your note here…")
        self.editor.setMinimumHeight(110)
        self.editor.textChanged.connect(self._announce)
        layout.addWidget(self.editor)

        preview_label = QLabel("In the margin")
        preview_label.setObjectName("Dim")
        layout.addWidget(preview_label)
        self.card = NoteCardPreview()
        layout.addWidget(self.card)

        swatches = QHBoxLayout()
        swatches.setSpacing(6)
        swatches.addWidget(QLabel("Colour"))
        self._buttons: list[QPushButton] = []
        for name, colour in COLOURS:
            button = QPushButton()
            button.setIcon(colour_swatch(colour, 16))
            button.setToolTip(name)
            button.setCheckable(True)
            button.setFixedWidth(44)
            button.setChecked(_same_colour(colour, self._colour))
            button.clicked.connect(lambda _checked=False, c=colour: self._pick(c))
            swatches.addWidget(button)
            self._buttons.append(button)
        swatches.addStretch(1)

        remove = QPushButton("Delete highlight")
        remove.setToolTip("Remove this highlight and its note")
        remove.clicked.connect(self._delete)
        swatches.addWidget(remove)
        layout.addLayout(swatches)

        buttons = QDialogButtonBox()
        save = buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName("Primary")
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Ctrl+Enter saves, since Enter itself belongs to the text box.
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.accept)
        self.card.set_card(item.note, self._colour, style[0], style[1], item.title)
        self.editor.setFocus()

    def _pick(self, colour: tuple[float, float, float]) -> None:
        self._colour = colour
        for button, (_name, option) in zip(self._buttons, COLOURS):
            button.setChecked(_same_colour(option, colour))
        self._announce()

    def _announce(self) -> None:
        text = self.editor.toPlainText().strip()
        self.card.set_card(text, self._colour, title=self.title_edit.text().strip())
        self.changed.emit(text, self._colour)

    @property
    def title(self) -> str:
        return self.title_edit.text().strip()

    def _delete(self) -> None:
        self.deleted = True
        self.accept()

    @property
    def note(self) -> str:
        return self.editor.toPlainText().strip()

    @property
    def colour(self) -> tuple[float, float, float]:
        return self._colour


def _same_colour(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return all(abs(x - y) < 0.02 for x, y in zip(a, b))


class NoteStyleDialog(QDialog):
    """Choose the typeface and size used for notes in the margin."""

    changed = Signal(str, float)

    def __init__(self, family: str, size: float, author: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Note appearance")
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        blurb = QLabel("How notes are written in the margin beside the page.")
        blurb.setObjectName("Dim")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        form = QFormLayout()
        form.setSpacing(10)
        self.font_box = QFontComboBox()
        if family:
            self.font_box.setCurrentFont(QFont(family))
        form.addRow("Typeface", self.font_box)

        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(6.0, 24.0)
        self.size_spin.setSingleStep(0.5)
        self.size_spin.setDecimals(1)
        self.size_spin.setSuffix(" pt")
        self.size_spin.setValue(size)
        self.size_spin.setToolTip("Size at 100% zoom \u2014 notes scale with the page")
        form.addRow("Size", self.size_spin)

        self.author_edit = QLineEdit(author)
        self.author_edit.setPlaceholderText("Your name")
        self.author_edit.setToolTip(
            "Saved with each highlight as its author. Other PDF readers show "
            "this beside your notes."
        )
        form.addRow("Your name", self.author_edit)
        layout.addLayout(form)

        self.sample = NoteCardPreview()
        self.sample.setMinimumHeight(96)
        layout.addWidget(self.sample)

        buttons = QDialogButtonBox()
        done = buttons.addButton("Done", QDialogButtonBox.ButtonRole.AcceptRole)
        done.setObjectName("Primary")
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.font_box.currentFontChanged.connect(self._announce)
        self.size_spin.valueChanged.connect(self._announce)
        self._refresh_sample()

    def _announce(self) -> None:
        self._refresh_sample()
        self.changed.emit(self.family, self.size)

    def _refresh_sample(self) -> None:
        self.sample.set_card(
            "Foucault's point here is about normalisation, not repression.",
            COLOURS[0][1], self.family, self.size,
        )

    @property
    def author(self) -> str:
        return self.author_edit.text().strip()

    @property
    def family(self) -> str:
        return self.font_box.currentFont().family()

    @property
    def size(self) -> float:
        return float(self.size_spin.value())
