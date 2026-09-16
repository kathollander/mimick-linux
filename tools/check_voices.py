#!/usr/bin/env python3
"""Check the offline-voices list: the place you were, and the names you gave.

    QT_QPA_PLATFORM=offscreen MIMICK_CONFIG_DIR=/tmp/mimick-test \\
        .venv/bin/python tools/check_voices.py

Two things are easy to break here and invisible to the other tools. Previewing
a voice refills the list, which used to throw away the selection and the status
line with it; and a nickname has to survive that refill, reach the voice box in
the main window, and come off again when the box is emptied. Exits non-zero on
the first failure.

The catalogue is a stand-in, so this needs neither the network nor a downloaded
voice.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt                                      # noqa: E402
from PySide6.QtWidgets import (                                    # noqa: E402
    QApplication, QStyleOptionViewItem,
)

from mimick.config import Settings                                 # noqa: E402
from mimick.engines import piper                                   # noqa: E402
from mimick.engines.base import Voice                              # noqa: E402

CATALOGUE = {
    f"en_GB-{person}-medium": {
        "language": {"name_english": "English", "country_english": "GB"},
        "files": {
            f"en/en_GB/{person}/medium/en_GB-{person}-medium.onnx":
                {"size_bytes": 63_000_000},
        },
    }
    for person in ("alan", "bramble", "cove", "delta")
}
INSTALLED = ["en_GB-cove-medium"]
NAMED = "en_GB-delta-medium"

failures: list[str] = []


def check(what: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}{'  — ' + detail if detail else ''}")
    if not ok:
        failures.append(what)


def stub_catalogue() -> None:
    """Stand in for the published catalogue, the downloads and the samples."""
    piper.load_catalogue = lambda: CATALOGUE
    piper.installed_voices = lambda: list(INSTALLED)
    piper.is_installed = lambda key: key in INSTALLED
    piper.has_sample = lambda key: False
    piper.cached_sample_count = lambda: (0, 0)
    piper.download_size = lambda entry: 63_000_000


def pick(tree, key: str) -> None:
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item.data(0, Qt.ItemDataRole.UserRole) == key:
            tree.setCurrentItem(item)
            return
    raise SystemExit(f"{key} is not in the list at all")


def check_dialog(settings: Settings) -> None:
    from mimick.ui.voices_dialog import OfflineVoicesDialog

    dialog = OfflineVoicesDialog(settings)
    tree = dialog.tree

    print("The list")
    check("opens on the suggested voice",
          dialog._current_key() == piper.SUGGESTED, dialog._current_key() or "none")

    pick(tree, NAMED)
    dialog._refill()
    check("keeps the selection through a refill", dialog._current_key() == NAMED,
          dialog._current_key() or "none")

    # What a finished preview does, without the audio.
    dialog._refill()
    dialog.status.setText("a line about the preview")
    check("leaves the preview's own status line alone",
          dialog.status.text() == "a line about the preview", dialog.status.text())

    print("Nicknames")
    pick(tree, NAMED)
    tree.currentItem().setText(0, "  Warm one  ")
    check("a typed name is stored, trimmed", settings.nickname(NAMED) == "Warm one",
          repr(settings.nickname(NAMED)))
    check("and shown in the list", tree.currentItem().text(0) == "Warm one")

    dialog._refill()
    check("it survives a refill, and so does the selection",
          tree.currentItem().text(0) == "Warm one" and dialog._current_key() == NAMED)

    dialog.search.setText("warm")
    check("searching finds a voice by its nickname",
          tree.topLevelItemCount() == 1 and dialog._current_key() == NAMED)
    dialog.search.clear()

    pick(tree, NAMED)
    tree.currentItem().setText(0, "")
    check("emptying the box puts the real name back",
          settings.nickname(NAMED) == "" and tree.currentItem().text(0) == "Delta",
          tree.currentItem().text(0))

    tree.currentItem().setText(0, "Delta")
    check("typing the real name stores no nickname", settings.nickname(NAMED) == "")

    delegate = tree.itemDelegate()
    option = QStyleOptionViewItem()
    editable = [
        column for column in range(tree.columnCount())
        if delegate.createEditor(
            tree.viewport(), option,
            tree.indexFromItem(tree.currentItem(), column)) is not None
    ]
    check("only the Voice column can be renamed", editable == [0], str(editable))
    dialog.deleteLater()


def check_main_window(settings: Settings) -> None:
    from mimick.ui.main_window import MainWindow

    settings.set_nickname(NAMED, "Warm one")
    window = MainWindow(settings)
    window.voices = [
        Voice(id=NAMED, name="Delta", locale="English (GB)", gender="medium",
              engine="piper"),
        Voice(id="en_GB-alan-medium", name="Alan", locale="English (GB)",
              gender="medium", engine="piper"),
    ]
    window.voice_box.blockSignals(True)
    window.voice_box.clear()
    for voice in window.voices:
        window.voice_box.addItem(voice.label, voice.id)
    window.voice_box.blockSignals(False)

    print("The voice box")
    window._relabel_voices()
    check("a nicknamed voice reads by its nickname",
          window.voice_box.itemText(0) == "Warm one · English (GB)",
          window.voice_box.itemText(0))
    check("the rest read as they always did",
          window.voice_box.itemText(1) == "Alan · English (GB) · medium",
          window.voice_box.itemText(1))
    check("and the box still points at the same voice",
          window.voice_box.itemData(0) == NAMED)

    settings.set_nickname(NAMED, "")
    window._relabel_voices()
    check("clearing the nickname restores the real name",
          window.voice_box.itemText(0) == "Delta · English (GB) · medium",
          window.voice_box.itemText(0))
    window.close()


def main() -> int:
    stub_catalogue()
    QApplication(sys.argv)
    settings = Settings()
    check_dialog(settings)
    check_main_window(settings)
    print()
    if failures:
        print(f"{len(failures)} check{'s' if len(failures) != 1 else ''} failed:")
        for what in failures:
            print(f"  - {what}")
        return 1
    print("The voice list keeps your place, and your names for the voices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
