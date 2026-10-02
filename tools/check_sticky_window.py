#!/usr/bin/env python3
"""Sticky notes in the window: added, typed in with the keys, formatted from
the bar, moved, deleted and undone, saved into the notes PDF, exported; and
the quick switches.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        .venv/bin/python tools/check_sticky_window.py [--shot out.png]

Works on a copy of the test paper in a folder of its own, so the notes PDF it
writes lands there. Keys are real key events (QTest), so this also checks
that the window's own shortcuts -- Space, the arrows, Ctrl+B -- leave a
sticky's keys alone while it is typed in. The rich text itself is pinned by
tools/check_sticky.py.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf                                              # noqa: E402
from PySide6.QtCore import QPoint, Qt                       # noqa: E402
from PySide6.QtTest import QTest                            # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

from mimick.annotations import companion_for                # noqa: E402
from mimick.config import Settings                          # noqa: E402
from mimick.notes_export import notes_file                  # noqa: E402
from mimick.ui.main_window import MainWindow                # noqa: E402

SAMPLE = Path("Testing/Big Ideas from Atleo and Boron 2022.pdf")
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
failures: list[str] = []


def check(claim: str, ok: bool, detail="") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {claim}{'' if ok else f'  -- {detail}'}")
    if not ok:
        failures.append(claim)


def settle(app, rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()
        QTest.qWait(20)


def main() -> int:
    shot = sys.argv[sys.argv.index("--shot") + 1] if "--shot" in sys.argv else None
    folder = Path(tempfile.mkdtemp(prefix="mimick-sticky-"))
    paper = folder / "paper.pdf"
    shutil.copy(SAMPLE, paper)

    app = QApplication([])
    window = MainWindow(Settings())
    window.resize(1300, 900)
    window.show()
    window.activateWindow()
    settle(app)
    window.load_document(paper)
    settle(app, 10)
    view, store = window.page_view, window.store

    print("Adding one")
    check("+ Add sticky and the formatting row are on the bar",
          window.add_sticky_button.isVisible() and window.sticky_format.isVisible())
    check("its colour sits beside it, not on the formatting row",
          window.sticky_colour_button.isVisible()
          and window.sticky_colour_button.parent() is window.add_sticky_button.parent()
          and not hasattr(window.sticky_format, "colour")
          and not window.sticky_colour_button.icon().isNull())
    row = window.sticky_format
    check("in the panel the formatting row fills the bar's width",
          window.markup_bar.home == "panel" and row.width() >= window.add_note_button.width() - 2,
          (row.width(), window.add_note_button.width()))
    QTest.mouseClick(window.add_sticky_button, Qt.MouseButton.LeftButton)
    settle(app, 10)
    check("+ Add sticky adds one straight away", len(store.stickies) == 1, len(store.stickies))
    item = store.stickies[0] if store.stickies else None
    widget = view.sticky_widget(item) if item else None
    page_width = window.document.page_size(view.page)[0]
    check("…in the middle of the page on screen", item is not None and item.page == view.page
          and abs((item.rect[0] + item.rect[2]) / 2 - page_width / 2) < 40, item and item.rect)
    check("…ready to type in", widget is not None and widget.editor.hasFocus())
    if widget is None:
        return 1
    editor = widget.editor

    print("Typing and formatting")
    QTest.keyClicks(editor, "Exam ")
    QTest.keyClick(editor, Qt.Key.Key_B, CTRL)
    QTest.keyClicks(editor, "bold")
    QTest.keyClick(editor, Qt.Key.Key_B, CTRL)
    QTest.keyClicks(editor, " and ")
    QTest.keyClick(editor, Qt.Key.Key_X, CTRL | SHIFT)
    QTest.keyClicks(editor, "gone")
    QTest.keyClick(editor, Qt.Key.Key_X, CTRL | SHIFT)
    settle(app)
    rich = widget.written()
    check("Ctrl+B makes bold, and not the notes panel", "<b>bold</b>" in rich and view.notes_visible, rich)
    check("Ctrl+Shift+X strikes out", "<s>gone</s>" in rich, rich)
    check("Space went into the note, not to the voice", rich.startswith("<p>Exam <b>"), rich)
    window._apply_sticky_format("size", 18)
    QTest.keyClicks(editor, " BIG")
    window._apply_sticky_format("italic", None)
    QTest.keyClicks(editor, " slanted")
    settle(app)
    rich = widget.written()
    check("the bar's size makes the next words 18pt", 'font-size:18pt' in rich, rich)
    check("the bar's I makes italic, and the cursor stays in the note", "slanted</i>" in rich and editor.hasFocus(), rich)
    check("the bar shows what is under the cursor", window.sticky_format.buttons["italic"].isChecked()
          and window.sticky_format.size_box.currentText() == "18")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QTest.keyClick(editor, Qt.Key.Key_Asterisk, CTRL | SHIFT)
    QTest.keyClicks(editor, "a point")
    settle(app)
    check("Enter and Ctrl+Shift+8 start a bullet list", "<ul><li>" in widget.written()
          and "a point" in widget.written().split("<ul>")[-1], widget.written())

    QTest.keyClick(editor, Qt.Key.Key_Escape)
    settle(app, 10)
    check("Esc finishes: the words are in the store", "<b>bold</b>" in item.rich and "<s>gone</s>" in item.rich,
          item.rich)
    check("…and the keyboard is the page's again", not editor.hasFocus())
    check("…with one undo step, for adding it", [e[0] for e in window._undo_stack] == ["Sticky note removed"],
          [e[0] for e in window._undo_stack])
    check("the Sticky chip counts it", window.filter_sticky.text() == "Sticky  1", window.filter_sticky.text())

    QTest.keyClick(window, Qt.Key.Key_B, CTRL)
    settle(app)
    check("Ctrl+B outside a sticky still hides the notes panel", not view.notes_visible)
    check("…and the bar goes with it, still at home in the panel",
          window.markup_bar.home == "panel" and not window.markup_bar.isVisible()
          and window.settings.get("markup_place") == "panel")
    QTest.keyClick(window, Qt.Key.Key_B, CTRL)
    settle(app)
    check("…and comes back with it", view.notes_visible and window.markup_bar.isVisible())
    window._place_markup_bar("top", announce=True)
    QTest.keyClick(window, Qt.Key.Key_B, CTRL)
    settle(app)
    check("a bar across the top stays there when the panel is hidden",
          window.markup_bar.home == "top" and window.markup_bar.isVisible())
    window._place_markup_bar("panel", announce=True)
    settle(app)
    check("putting it in a closed panel opens the panel", view.notes_visible
          and window.markup_bar.home == "panel" and window.markup_bar.isVisible())
    QTest.keyClick(window, Qt.Key.Key_B, CTRL)
    settle(app)
    window.act_annotation_bar.trigger()
    settle(app)
    check("Ctrl+Shift+H with the bar in a closed panel opens the panel",
          view.notes_visible and window.markup_bar.isVisible() and window.act_annotation_bar.isChecked())

    print("Dragging the bar")
    # Kat, 1 October: it was unclear that the right-hand side docks it. Over a
    # home it docks in, it snaps there in that home's shape, labelled.
    bar, viewport = window.markup_bar, view.viewport()
    QTest.mousePress(bar.grip, Qt.MouseButton.LeftButton)
    settle(app)
    bar._drag_to(viewport.mapToGlobal(QPoint(viewport.width() // 3, viewport.height() // 2)))
    settle(app)
    label = bar._label
    check("dragged over the page it is loose, with no label", bar.property("preview") is not True
          and (label is None or not label.isVisible()))
    gutter = view.notes_gutter_rect()
    bar._drag_to(viewport.mapToGlobal(QPoint(viewport.width() - 4, viewport.height() - 80)))
    settle(app)
    label = bar._label
    check("at the far right, low down, it snaps into the notes column's shape",
          bar.property("preview") is True and bar.x() == gutter.left() and bar.width() == gutter.width()
          and bar.y() < viewport.height() // 3, (bar.geometry(), gutter))
    check("…labelled", label is not None and label.isVisible() and "notes panel" in label.text())
    if shot:
        window.grab().save(shot.replace(".png", "-dock-panel.png"))
    bar._drag_to(viewport.mapToGlobal(QPoint(viewport.width() // 3, 10)))
    settle(app)
    check("near the top it snaps across the top", bar.property("preview") is True and bar.y() == 0
          and bar.width() == viewport.width() and "across the top" in label.text(), bar.geometry())
    if shot:
        window.grab().save(shot.replace(".png", "-dock-top.png"))
    QTest.mouseRelease(bar.grip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       bar.grip.mapFromGlobal(viewport.mapToGlobal(QPoint(viewport.width() - 4, viewport.height() - 80))))
    settle(app)
    check("let go at the right, it is back in the panel", bar.home == "panel" and bar.isVisible()
          and not label.isVisible() and bar.property("preview") is not True, bar.home)

    print("Moving, deleting, undoing")
    before = tuple(item.rect)
    window._on_sticky_moved(item, (before[0] - 100, before[1] + 50, before[2] - 100, before[3] + 50))
    check("moving it puts it there", abs(item.rect[0] - (before[0] - 100)) < 0.5, item.rect)
    window.undo_annotation()
    check("Ctrl+Z puts it back", all(abs(a - b) < 0.5 for a, b in zip(item.rect, before)), item.rect)
    window.delete_sticky(item)
    check("× deletes it", not store.stickies)
    window.undo_annotation()
    settle(app)
    check("Ctrl+Z brings it back, formatting and all", len(store.stickies) == 1 and "<b>bold</b>" in store.stickies[0].rich,
          [s.rich for s in store.stickies])
    item = store.stickies[0]

    steps = [e[0] for e in window._undo_stack]
    window.add_sticky_here()
    settle(app, 10)
    fresh = [s for s in store.stickies if s is not item]
    check("Ctrl+Alt+M adds another, ready to type", len(fresh) == 1 and view.sticky_widget(fresh[0]).editor.hasFocus())
    if fresh:
        QTest.keyClick(view.sticky_widget(fresh[0]).editor, Qt.Key.Key_Escape)
        settle(app, 10)
    check("…which, left empty, goes again with its undo step", len(store.stickies) == 1
          and [e[0] for e in window._undo_stack] == steps, [e[0] for e in window._undo_stack])

    print("Find")
    window.open_find()
    window._on_find_query("slanted", False)
    settle(app)
    in_sticky = [m for m in window._matches if m[0] < 0]
    check("Ctrl+F finds words in a sticky note too", len(in_sticky) == 1 and in_sticky[0][3] is item,
          [m[:3] for m in window._matches])
    number = window._matches.index(in_sticky[0]) if in_sticky else -1
    if number >= 0:
        window._show_match(number)
        settle(app)
        check("…and going to that match picks the sticky out", view.active_note is item
              and view.selection is None)
    window.close_find()
    settle(app)

    print("Saving and exporting")
    window.save_annotations()
    companion = companion_for(paper)
    check("the notes PDF is written", companion.exists(), companion)
    if companion.exists():
        with pymupdf.open(companion) as written:
            page = written[0]
            boxes = list(page.annots(types=(pymupdf.PDF_ANNOT_FREE_TEXT,)))
            rich = pymupdf.mupdf.pdf_annot_rich_contents(boxes[0].this) if boxes else ""
            check("…with the sticky in it as a text box, rich text and all",
                  len(boxes) == 1 and "<b>bold</b>" in rich and "font-size:18pt" in rich, rich[190:600])
    markdown = notes_file("md", "T", "paper.pdf", window._everything()).decode()
    check("Export notes has it", "**Sticky note**" in markdown and "**bold**" in markdown, markdown[-300:])

    print("Display and the quick switches")
    window._set_sticky_shown(False)
    settle(app)
    check("Display > Sticky notes off takes + Add sticky off the bar",
          not window.add_sticky_button.isVisible() and not window.sticky_colour_button.isVisible()
          and not window.sticky_format.isVisible())
    check("…and the sticky stays on the page", len(store.stickies) == 1 and view.sticky_widget(item).isVisible())
    window._set_sticky_shown(True)
    window._show_switches(True)
    settle(app)
    names = [button.text() for button in window.switches.findChildren(type(window.switches_button))
             if button.objectName() == "Switch"]
    check("the quick switches are there, Sticky notes among them", "Sticky notes" in names and "Clean up text" in names,
          names)
    if shot:
        window.grab().save(shot)
        print(f"  (saved {shot})")

    window.store.dirty = False
    window.close()
    print()
    if failures:
        print(f"{len(failures)} failed.")
        return 1
    print("Sticky notes work in the window.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
