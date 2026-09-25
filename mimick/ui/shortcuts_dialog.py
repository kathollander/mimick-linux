"""The keyboard and mouse reference, grouped by what you are trying to do."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from . import theme

# (group, [(keys, what it does)]). Keys are written as Qt reports them, so the
# test in docs/ROADMAP.md can check every one is really bound.
GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Reading", [
        ("Space", "Start reading, or pause it"),
        ("Enter", "Read the selected text, then stop"),
        ("←  →", "Back or forward one sentence"),
    ]),
    ("Choosing what gets read", [
        ("Click a sentence", "Start reading from there. Turn this off under "
                             "Display → Click to read."),
        ("Drag across text", "Select a passage"),
        ("Double-click", "Select the whole sentence"),
        ("Right-click", "Start reading from that point, whichever mode you are in"),
        ("Ctrl+A", "Select every word on the page"),
        ("Ctrl+C", "Copy the selected text"),
        ("Esc", "Clear the selection"),
    ]),
    ("Moving around", [
        ("Page Up / Page Down", "Turn the page"),
        ("Ctrl+↑ / Ctrl+↓", "Turn the page"),
        ("Ctrl+Home / Ctrl+End", "First or last page"),
        ("Ctrl++ / Ctrl+-", "Zoom in or out"),
        ("Ctrl+0", "Back to 125%"),
    ]),
    ("Highlights and notes", [
        ("Ctrl+H", "Highlight the selected text"),
        ("Ctrl+M", "Highlight it and write a note"),
        ("Ctrl+J / Ctrl+K", "Jump to the next or previous note"),
        ("Click a highlight", "Select it, on the page or in the margin"),
        ("Double-click it", "Edit the note, its heading or its colour"),
    ]),
    ("Files", [
        ("Ctrl+O", "Open a PDF"),
        ("Ctrl+S", "Save now — notes also save themselves as you work"),
        ("Ctrl+Shift+S", "Save As — writes a separate annotated copy"),
    ]),
    ("Showing and hiding", [
        ("Ctrl+T", "The highlighting toolbar"),
        ("Ctrl+Shift+N", "The notes panel beside the page"),
        ("Ctrl+R", "The reading order \u2014 what gets read, and what is skipped"),
    ]),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.setMinimumSize(560, 600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 16)
        outer.setSpacing(12)

        body = QLabel(self._html())
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(body)
        outer.addWidget(scroller, 1)

        buttons = QDialogButtonBox()
        close = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close.setObjectName("Primary")
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _html(self) -> str:
        blocks = []
        for heading, rows in GROUPS:
            cells = "".join(
                f"<tr>"
                f"<td style='padding:3px 14px 3px 0;white-space:nowrap;"
                f"color:{theme.TEXT};font-weight:600'>{keys}</td>"
                f"<td style='padding:3px 0;color:{theme.TEXT_DIM}'>{what}</td>"
                f"</tr>"
                for keys, what in rows
            )
            blocks.append(
                f"<p style='margin:0 0 4px 0;font-weight:600;font-size:13px'>{heading}</p>"
                f"<table style='margin:0 0 14px 0' cellspacing='0'>{cells}</table>"
            )
        return f"<div style='font-size:13px'>{''.join(blocks)}</div>"
