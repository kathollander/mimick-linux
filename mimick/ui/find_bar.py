"""The strip that searches the open document, under the toolbar.

Shaped after the find bars in Chrome and Firefox, because that is what a reader
already knows: a box, a count beside it, arrows, Match case, and a close button.
Enter and Shift+Enter step, F3 does too, and Escape closes it leaving the match
selected so it can be highlighted, copied or read straight away.

The bar knows nothing about the document. It reports what was typed and which
way to step; the window does the searching.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget,
)

from . import theme


class FindBar(QWidget):
    """A search strip for the open document."""

    query_changed = Signal(str, bool)    # what to look for, match case
    step = Signal(int)                   # +1 next, -1 previous
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FindBar")
        self.setVisible(False)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)

        self.box = QLineEdit()
        self.box.setPlaceholderText("Find in document")
        self.box.setClearButtonEnabled(True)
        self.box.setAccessibleName("Find in document")
        self.box.setFixedWidth(280)
        self.box.textChanged.connect(self._announce)
        self.box.returnPressed.connect(lambda: self.step.emit(1))
        row.addWidget(self.box)

        self.count = QLabel("")
        self.count.setObjectName("FindCount")
        self.count.setMinimumWidth(96)
        # Read out as one phrase rather than letter by letter.
        self.count.setAccessibleName("Matches found")
        row.addWidget(self.count)

        for label, direction, tip in (("‹", -1, "Previous match (Shift+Enter)"),
                                      ("›", 1, "Next match (Enter)")):
            button = QPushButton(label)
            button.setObjectName("FindStep")
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setFixedWidth(30)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _checked=False, d=direction: self.step.emit(d))
            row.addWidget(button)
            if direction == -1:
                self.previous_button = button
            else:
                self.next_button = button

        self.match_case = QPushButton("Match case")
        self.match_case.setObjectName("FilterChip")
        self.match_case.setCheckable(True)
        self.match_case.setToolTip("Tell capitals and small letters apart")
        self.match_case.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.match_case.clicked.connect(self._announce)
        row.addWidget(self.match_case)

        row.addStretch(1)

        close = QPushButton("×")
        close.setObjectName("FindStep")
        close.setToolTip("Close the find bar (Esc)")
        close.setAccessibleName("Close the find bar")
        close.setFixedWidth(30)
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self.closed.emit)
        row.addWidget(close)

        # Return and Escape are also bound on the window, but those are switched
        # off while this box has the focus, so these are what answer here.
        for sequence in ("Shift+Return", "Shift+Enter", "Shift+F3"):
            self._bind(sequence, lambda: self.step.emit(-1))
        self._bind("F3", lambda: self.step.emit(1))
        self._bind("Esc", self.closed.emit)

    # -- use ----------------------------------------------------------------

    def open_with(self, text: str = "") -> None:
        """Show the bar, seeded with ``text`` if there is any, and take focus."""
        self.setVisible(True)
        if text:
            self.box.setText(text)
        self.box.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.box.selectAll()
        # Seeding counts as typing: the window has to search for what is now in
        # the box, and setText() only says so when the text actually changed.
        self._announce()

    def query(self) -> tuple[str, bool]:
        return self.box.text(), self.match_case.isChecked()

    def _announce(self) -> None:
        self.query_changed.emit(*self.query())

    def show_count(self, current: int, total: int, cut_short: bool = False) -> None:
        """The count beside the box: "3 of 41", or that nothing was found."""
        if not self.box.text():
            self.count.setText("")
            found = True
        elif total == 0:
            self.count.setText("No matches")
            found = False
        else:
            more = "+" if cut_short else ""
            self.count.setText(f"{current + 1} of {total}{more}")
            found = True
        # A red box is the whole signal for "that is not in here", and it is the
        # one bit of this bar a reader will see without looking at it.
        self.box.setStyleSheet("" if found else
                               f"QLineEdit {{ border-color: {theme.DANGER}; }}")
        for button in (self.previous_button, self.next_button):
            button.setEnabled(total > 1)

    def _bind(self, sequence: str, handler) -> None:
        """A key that works anywhere in the bar, including inside the box.

        Real QShortcuts rather than a keyPressEvent, because tools/check_shortcuts.py
        can only see keys bound this way -- a key handled by hand is a key the
        shortcuts window can claim without anything checking it is true. Forward
        Enter is the box's own returnPressed, which cannot tell Shift apart, so
        the backward half is bound here.
        """
        shortcut = QShortcut(QKeySequence(sequence), self, activated=handler)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
