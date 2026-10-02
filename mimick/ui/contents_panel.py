"""The table of contents, down the left-hand side.

The PDF's own bookmarks, nested as the file nests them. Click an entry to go
there; right-click one to start reading from it. The section you are looking at
is lit as you scroll, so the panel answers "where am I?" as well as "take me
there".

Hidden by its ‹ button and brought back by the tab on the page's edge, which is
how the notes panel behaves on the other side, so the two match.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from . import theme

PANEL_WIDTH = 260


class ContentsPanel(QWidget):
    """The document's own table of contents."""

    go_to = Signal(int)          # index into the entries given to set_outline
    read_from = Signal(int)
    hidden = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContentsPanel")
        self.setFixedWidth(PANEL_WIDTH)
        self.setVisible(False)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        head = QWidget()
        head.setObjectName("ContentsHead")
        row = QHBoxLayout(head)
        row.setContentsMargins(10, 8, 6, 8)
        title = QLabel("Contents")
        title.setObjectName("ContentsTitle")
        row.addWidget(title)
        row.addStretch(1)
        collapse = QPushButton("‹")
        collapse.setObjectName("ContentsCollapse")
        collapse.setToolTip("Hide the contents (F9)")
        collapse.setAccessibleName("Hide the contents")
        collapse.setFixedWidth(24)
        collapse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        collapse.clicked.connect(self.hidden.emit)
        row.addWidget(collapse)
        column.addWidget(head)

        self.tree = QTreeWidget()
        self.tree.setObjectName("ContentsTree")
        self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName("Contents of this document")
        self.tree.setIndentation(12)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemActivated.connect(self._on_clicked)
        column.addWidget(self.tree, 1)

        self._items: list[QTreeWidgetItem] = []
        self._current = -1

    # -- filling ------------------------------------------------------------

    def set_outline(self, entries: list[tuple[int, str, int, bool]]) -> None:
        """Show ``(level, title, page, open)`` entries, nested by level."""
        self.tree.clear()
        self._items = []
        self._current = -1
        # A stack of the last item seen at each level, so an entry hangs off
        # the nearest shallower one. Levels in a PDF are not always tidy -- a
        # file can jump from 1 to 3 -- so anything with no parent at its own
        # depth goes in at the top rather than being dropped.
        parents: dict[int, QTreeWidgetItem] = {}
        for number, (level, title, page, shown) in enumerate(entries):
            item = QTreeWidgetItem([title or "(untitled)"])
            item.setData(0, Qt.ItemDataRole.UserRole, number)
            if page >= 0:
                item.setToolTip(0, f"{title}\nPage {page + 1}")
            else:
                # Nothing to go to, so say so rather than letting a click do
                # nothing and look broken.
                item.setToolTip(0, f"{title}\nThis entry does not point anywhere in this file")
                item.setForeground(0, Qt.GlobalColor.gray)
            owner = next((parents[depth] for depth in range(level - 1, 0, -1)
                          if depth in parents), None)
            if owner is None:
                self.tree.addTopLevelItem(item)
            else:
                owner.addChild(item)
            parents[level] = item
            for deeper in [d for d in parents if d > level]:
                del parents[deeper]
            item.setExpanded(bool(shown))
            self._items.append(item)

    def set_current(self, number: int) -> None:
        """Light the section being read or looked at."""
        if number == self._current:
            return
        for at, item in enumerate(self._items):
            font = item.font(0)
            font.setBold(at == number)
            item.setFont(0, font)
        self._current = number
        if 0 <= number < len(self._items):
            self.tree.scrollToItem(self._items[number])

    def entry_at(self, point) -> int | None:
        """Which entry is under a point in the tree, for the context menu."""
        item = self.tree.itemAt(point)
        return None if item is None else item.data(0, Qt.ItemDataRole.UserRole)

    def _on_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        self.go_to.emit(item.data(0, Qt.ItemDataRole.UserRole))


class ContentsTab(QPushButton):
    """The sliver on the page's edge that brings the panel back."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("›", parent)
        self.setObjectName("ContentsTab")
        self.setToolTip("Show the contents (F9)")
        self.setAccessibleName("Show the contents")
        self.setFixedWidth(16)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVisible(False)
