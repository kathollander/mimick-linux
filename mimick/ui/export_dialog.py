"""The window that sets up an MP3 conversion, and the one that shows progress."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from ..document import Document
from ..export import describe_duration, estimate_convert_seconds, estimate_listen_seconds
from . import theme


def _safe_filename(name: str) -> str:
    """Strip characters that make trouble in a file name."""
    cleaned = "".join("-" if ch in '/\\:*?"<>|' else ch for ch in name).strip()
    return cleaned or "audio"


class ExportDialog(QDialog):
    """Collects everything needed for a conversion, pre-filled from the app."""

    def __init__(self, document: Document, voices: list, current_voice: str,
                 current_speed: float, speeds: list[float], folder: Path,
                 selection: tuple[int, int] | None, finish_settings: dict | None = None,
                 clean_text: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self._selection = selection
        # Overriding the cleanup here means reading the PDF the other way, which
        # only a second Document can do. It is built on demand and thrown away
        # with the dialog, so the document being read is left alone.
        self._alternate: Document | None = None
        finish_settings = finish_settings or {}
        self.setWindowTitle("Convert to MP3")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)

        heading = QLabel(f"Convert “{document.title}” to an audio file")
        heading.setObjectName("Title")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.name_edit = QLineEdit(_safe_filename(document.title))
        self.name_edit.setToolTip("The name of the audio file, without the .mp3")
        form.addRow("File name", self._with_suffix(self.name_edit, ".mp3"))

        self.folder_edit = QLineEdit(str(folder))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._choose_folder)
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.setSpacing(8)
        folder_layout.addWidget(self.folder_edit, 1)
        folder_layout.addWidget(browse)
        form.addRow("Save to", folder_row)

        self.voice_box = QComboBox()
        for voice in voices:
            self.voice_box.addItem(voice.label, voice.id)
        position = self.voice_box.findData(current_voice)
        self.voice_box.setCurrentIndex(position if position >= 0 else 0)
        form.addRow("Voice", self.voice_box)

        self.speed_box = QComboBox()
        for speed in speeds:
            self.speed_box.addItem(f"{speed:g}×", speed)
        position = self.speed_box.findData(current_speed)
        self.speed_box.setCurrentIndex(position if position >= 0 else 0)
        form.addRow("Speed", self.speed_box)

        # What to convert: everything, a page range, or the current selection.
        self.scope_box = QComboBox()
        self.scope_box.addItem(f"Whole document ({document.page_count} pages)", "all")
        self.scope_box.addItem("Pages…", "range")
        if selection is not None:
            words = selection[1] - selection[0] + 1
            self.scope_box.addItem(f"Selected text ({words} words)", "selection")
            self.scope_box.setCurrentIndex(2)
        form.addRow("Convert", self.scope_box)

        self.range_row = QWidget()
        range_layout = QHBoxLayout(self.range_row)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(8)
        self.from_page = QSpinBox()
        self.to_page = QSpinBox()
        for box, value in ((self.from_page, 1), (self.to_page, document.page_count)):
            box.setMinimum(1)
            box.setMaximum(document.page_count)
            box.setValue(value)
            box.setFixedWidth(84)
        range_layout.addWidget(QLabel("from"))
        range_layout.addWidget(self.from_page)
        range_layout.addWidget(QLabel("to"))
        range_layout.addWidget(self.to_page)
        range_layout.addStretch(1)
        form.addRow("", self.range_row)
        self.range_row.setVisible(False)

        self.clean_box = QCheckBox("Clean up text for reading")
        self.clean_box.setChecked(clean_text)
        self.clean_box.setToolTip(
            "Leave out the reference list, the masthead and the author\n"
            "declarations, and repair ligatures and stranded accents.\n\n"
            "Starts from the setting in Display, and changes only this\n"
            "conversion."
        )
        form.addRow("Text", self.clean_box)
        layout.addLayout(form)

        # Estimates, refreshed whenever a choice changes.
        estimate_box = QFrame()
        estimate_box.setObjectName("ControlBar")
        estimate_layout = QVBoxLayout(estimate_box)
        estimate_layout.setContentsMargins(14, 12, 14, 12)
        estimate_layout.setSpacing(5)
        self.convert_label = QLabel()
        self.listen_label = QLabel()
        self.listen_label.setObjectName("Dim")
        estimate_layout.addWidget(self.convert_label)
        estimate_layout.addWidget(self.listen_label)
        layout.addWidget(estimate_box)

        # What to do once the file exists.
        self.reveal_after = QCheckBox("Open the file location when finished")
        self.reveal_after.setChecked(bool(finish_settings.get("reveal", True)))
        layout.addWidget(self.reveal_after)

        buttons = QDialogButtonBox()
        self.convert_button = buttons.addButton("Convert", QDialogButtonBox.ButtonRole.AcceptRole)
        self.convert_button.setObjectName("Primary")
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for signal in (self.speed_box.currentIndexChanged, self.scope_box.currentIndexChanged,
                       self.from_page.valueChanged, self.to_page.valueChanged,
                       self.clean_box.toggled):
            signal.connect(self._refresh_estimates)
        self.scope_box.currentIndexChanged.connect(self._refresh_scope)
        self._refresh_estimates()

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _with_suffix(edit: QLineEdit, suffix: str) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(edit, 1)
        label = QLabel(suffix)
        label.setObjectName("Dim")
        row.addWidget(label)
        return holder

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", self.folder_edit.text())
        if chosen:
            self.folder_edit.setText(chosen)

    def _refresh_scope(self) -> None:
        self.range_row.setVisible(self.scope_box.currentData() == "range")

    # -- results -----------------------------------------------------------

    @property
    def finish_actions(self) -> dict:
        """What the reader asked to happen once the file exists."""
        return {"reveal": self.reveal_after.isChecked()}

    @property
    def speed(self) -> float:
        return float(self.speed_box.currentData() or 1.0)

    @property
    def voice(self) -> str:
        return self.voice_box.currentData() or ""

    @property
    def clean_text(self) -> bool:
        return self.clean_box.isChecked()

    def _source(self) -> Document:
        """The document to take sentences from, honouring the override.

        Word indices and rectangles are the same in both, so a selection made
        against the open document still names the same passage here.
        """
        if self.clean_box.isChecked() == self.document.clean_text:
            return self.document
        if self._alternate is None:
            self._alternate = Document(
                self.document.path,
                skip_citations=self.document.skip_citations,
                clean_text=self.clean_box.isChecked(),
            )
        return self._alternate

    def sentences(self) -> list:
        """The sentences the chosen scope covers."""
        source = self._source()
        scope = self.scope_box.currentData()
        if scope == "selection" and self._selection is not None:
            return source.sentences_from_range(*self._selection)
        if scope == "range":
            first = min(self.from_page.value(), self.to_page.value()) - 1
            last = max(self.from_page.value(), self.to_page.value()) - 1
            return [s for s in source.sentences if first <= s.page <= last]
        return list(source.sentences)

    def release(self) -> None:
        """Close the second document, once its sentences have been taken.

        A Sentence holds plain strings and rectangles, not anything belonging to
        the open PDF, so the conversion is unaffected by this.
        """
        if self._alternate is not None:
            self._alternate.close()
            self._alternate = None

    def destination(self) -> Path:
        name = _safe_filename(self.name_edit.text().strip() or self.document.title)
        if not name.lower().endswith(".mp3"):
            name += ".mp3"
        return Path(self.folder_edit.text().strip() or str(Path.home())) / name

    def _refresh_estimates(self) -> None:
        sentences = self.sentences()
        if not sentences:
            self.convert_label.setText("Nothing to convert in this range.")
            self.listen_label.setText("")
            self.convert_button.setEnabled(False)
            return
        self.convert_button.setEnabled(True)
        convert = estimate_convert_seconds(sentences)
        listen = estimate_listen_seconds(sentences, self.speed)
        self.convert_label.setText(
            f"Converting takes {describe_duration(convert)} — {len(sentences)} sentences."
        )
        self.listen_label.setText(
            f"The finished audio runs {describe_duration(listen)} at {self.speed:g}×."
        )


class ExportProgressDialog(QDialog):
    """Progress for a running conversion, with a Cancel that really cancels."""

    cancelled = Signal()

    def __init__(self, total: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Converting to MP3")
        self.setMinimumWidth(460)
        self.setModal(True)
        # No close button: stopping goes through Cancel so the worker is told.
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        self._total = total
        self._started = time.monotonic()
        self._stopping = False
        self._closing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        self.heading = QLabel("Converting…")
        self.heading.setObjectName("Title")
        layout.addWidget(self.heading)

        self.bar = QProgressBar()
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

        self.detail = QLabel("Starting…")
        self.detail.setObjectName("Dim")
        layout.addWidget(self.detail)

        buttons = QDialogButtonBox()
        self.cancel_button = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self._on_cancel)
        layout.addWidget(buttons)

    def _on_cancel(self) -> None:
        if self._stopping:
            # Asked twice: let it go rather than leaving the window stuck.
            self.finish()
            return
        self._stopping = True
        self.cancel_button.setEnabled(False)
        self.heading.setText("Stopping…")
        self.detail.setText("Finishing the sentence in progress.")
        self.cancelled.emit()

    @property
    def stopping(self) -> bool:
        return self._stopping

    def advance(self, done: int, total: int) -> None:
        if self._stopping:
            return
        self.bar.setValue(done)
        elapsed = time.monotonic() - self._started
        if done >= 3:
            remaining = elapsed / done * (total - done)
            self.detail.setText(
                f"Sentence {done} of {total} · {describe_duration(remaining)} left"
            )
        else:
            self.detail.setText(f"Sentence {done} of {total}…")

    def finish(self) -> None:
        """Close for good, because the conversion is over.

        Everything that shuts this window must come through here. Qt routes
        ``close()`` through ``reject()``, and ``reject()`` means *cancel* while
        work is running -- so closing it any other way only asked it to stop and
        then left it on screen saying so.
        """
        self._closing = True
        self.close()

    def reject(self) -> None:  # noqa: D102 - Esc cancels while work is running
        if self._closing:
            super().reject()
            return
        self._on_cancel()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._closing:
            super().closeEvent(event)
            return
        # The window manager's close button lands here; treat it as Cancel.
        event.ignore()
        self._on_cancel()
