"""Highlight and Add note, in a strip you can pull off and put somewhere else.

The two buttons that mark up a page used to live apart: Highlight in a strip
under the top bar, Add note inside the notes panel's own header. That header is
positioned by hand inside the page view's viewport, so turning the notes column
off took Add note away with it -- there was no way to write a note without
giving up a quarter of the window to a column of cards.

So both buttons are one widget now, and that widget has four homes:

    panel   stacked in the notes panel header, one under the other (the
            default, and the only one that is part of the notes column)
    top     a strip across the top of the reading area
    bottom  a strip across the bottom of it
    float   loose over the page, wherever it was dropped

Drag it by the grip at its leading edge. Dropping it near the top or bottom
edge of the reading area snaps it there; dropping it over the notes column puts
it back in the panel; anywhere else leaves it floating. Where it was left is
remembered in settings.

Qt has a perfectly good QToolBar that does three of these four for free, and it
was the first thing tried. It cannot do the fourth: a QToolBar docks to the
edges of the QMainWindow, and the notes panel header is not in the main
window's layout at all -- it is a hand-placed child of the page view's
viewport. Since the panel is the home this bar is meant to have by default,
the docking is done here instead.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

# How close to an edge counts as aiming at it. Generous, because the bar is
# dragged by a grip a few pixels wide and nobody aims precisely with one.
SNAP_MARGIN = 56
# Homes, in the order the Display menu lists them.
HOMES = ("panel", "top", "bottom", "float")


class _Grip(QLabel):
    """The dotted handle at the leading edge. Dragging anywhere else is not
    dragging -- the rest of the bar is buttons, and a button that moved the
    window when you meant to press it would be maddening."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("⋮⋮", parent)
        self.setObjectName("Dim")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to move these buttons — the top or bottom of "
                        "the page, the notes panel, or loose over the page")


class MarkupBar(QFrame):
    """The Highlight and Add note buttons, wherever they currently live."""

    #: Emitted with the new home, and the top-left point when that home is
    #: "float" (in the page view's viewport coordinates).
    home_changed = Signal(str, QPoint)
    #: Emitted when a drag begins somewhere the bar is inside a layout. It has
    #: to come loose before it can be moved -- a widget in a layout is put back
    #: where the layout wants it the moment anything re-lays out.
    detached = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MarkupBar")
        self._home = "panel"
        self.setProperty("home", "panel")
        self._drag_from: QPoint | None = None
        self._buttons: list[QWidget] = []

        self.grip = _Grip(self)
        self.grip.installEventFilter(self)

        self._stage_widget: QWidget | None = None
        self._layout: QVBoxLayout | QHBoxLayout | None = None
        self._rebuild_layout(vertical=True)

    def set_stage(self, widget: QWidget) -> None:
        """The surface drags are measured against: the page view's viewport.

        Not simply ``parent()``: while the bar is clipped into the notes panel
        its parent is the panel header, which is itself only a few dozen pixels
        tall, and a drag measured against that would snap to the top edge the
        moment it began.
        """
        self._stage_widget = widget

    # -- contents ----------------------------------------------------------

    def set_buttons(self, widgets: list[QWidget]) -> None:
        """The buttons to carry. Given once, by the window that owns them."""
        self._buttons = widgets
        self._rebuild_layout(vertical=self._home == "panel")

    def _rebuild_layout(self, vertical: bool) -> None:
        """Lay the buttons out down the panel, or across a strip.

        The old layout is not merely emptied: a QLayout cannot be re-parented
        or swapped while it is installed, so it is given to a throwaway widget
        that takes it to the grave. Emptying it in place leaves the widgets
        owned by a layout that is about to be replaced, and they vanish.
        """
        if self._layout is not None:
            for index in reversed(range(self._layout.count())):
                item = self._layout.takeAt(index)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(self)
            QWidget().setLayout(self._layout)

        box = QVBoxLayout(self) if vertical else QHBoxLayout(self)
        box.setContentsMargins(*((8, 6, 8, 6) if vertical else (6, 4, 10, 4)))
        box.setSpacing(6)
        self._layout = box

        # The grip shows in every home, including the panel: being clipped in
        # is the state it most needs dragging out of.
        box.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignHCenter if vertical
                      else Qt.AlignmentFlag.AlignVCenter)
        self.grip.setText("\u22ef" if vertical else "\u22ee\u22ee")
        for widget in self._buttons:
            widget.setParent(self)
            widget.show()
            box.addWidget(widget, 1 if vertical else 0)
        if not vertical:
            box.addStretch(1)
        self.adjustSize()

    # -- where it lives ----------------------------------------------------

    @property
    def home(self) -> str:
        return self._home

    def set_home(self, home: str) -> None:
        """Change home without moving the widget -- the window does that part."""
        if home not in HOMES:
            home = "panel"
        if home == self._home:
            return
        self._home = home
        # Drives the [home="..."] rules in the stylesheet; Qt only re-reads a
        # dynamic property when the widget is repolished.
        self.setProperty("home", home)
        self.style().unpolish(self)
        self.style().polish(self)
        self._rebuild_layout(vertical=home == "panel")

    # -- dragging ----------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:
        """Drags start on the grip, so they are caught before it sees them."""
        if watched is not self.grip:
            return super().eventFilter(watched, event)
        kind = event.type()
        if kind == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.position().toPoint()
            self.grip.setCursor(Qt.CursorShape.ClosedHandCursor)
            stage = self._stage()
            if self._home != "float" and stage is not None:
                # Come loose first, at exactly the spot it is already in, so it
                # does not jump under the cursor as the drag starts.
                here = stage.mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))
                self.detached.emit(here)
            return True
        if kind == event.Type.MouseMove and self._drag_from is not None:
            self._drag_to(event.globalPosition().toPoint())
            return True
        if kind == event.Type.MouseButtonRelease and self._drag_from is not None:
            self._drag_from = None
            self.grip.setCursor(Qt.CursorShape.OpenHandCursor)
            self._drop(event.globalPosition().toPoint())
            return True
        return super().eventFilter(watched, event)

    def _stage(self) -> QWidget | None:
        return self._stage_widget

    def _drag_to(self, global_point: QPoint) -> None:
        stage = self._stage()
        if stage is None or self._drag_from is None:
            return
        local = stage.mapFromGlobal(global_point)
        self.move(local - self._drag_from - self.grip.pos())
        self.raise_()
        self._preview(local)

    def _preview(self, local: QPoint) -> None:
        """Say what a drop here would do, in the tooltip-free way: the cursor."""
        aim = self._aim(local)
        shapes = {
            "top": Qt.CursorShape.UpArrowCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "panel": Qt.CursorShape.PointingHandCursor,
            "float": Qt.CursorShape.ClosedHandCursor,
        }
        self.grip.setCursor(shapes.get(aim, Qt.CursorShape.ClosedHandCursor))

    def _aim(self, local: QPoint) -> str:
        """Which home a drop at this point means."""
        stage = self._stage()
        if stage is None:
            return "float"
        gutter = getattr(self.window(), "notes_gutter_rect", None)
        if gutter is not None:
            area: QRect = gutter()
            if area is not None and area.contains(local):
                return "panel"
        if local.y() <= SNAP_MARGIN:
            return "top"
        if local.y() >= stage.height() - SNAP_MARGIN:
            return "bottom"
        return "float"

    def _drop(self, global_point: QPoint) -> None:
        stage = self._stage()
        if stage is None:
            return
        local = stage.mapFromGlobal(global_point)
        aim = self._aim(local)
        self.home_changed.emit(aim, self.pos() if aim == "float" else QPoint())

