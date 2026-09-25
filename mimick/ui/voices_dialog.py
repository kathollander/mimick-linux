"""Downloading and removing the offline Piper voices."""

from __future__ import annotations

import sounddevice as sd

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QFrame, QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..engines import EngineError
from ..audio_preview import ClipPlayer
from ..engines import piper
from ..engines.base import decode_audio


def _size_text(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "—"
    return f"{size_bytes / 1_000_000:.0f} MB"


# The passage every Piper voice is recorded saying, so it is the one phrase that
# can be heard from a voice that has not been downloaded.
RAINBOW = ("When the sunlight strikes raindrops in the air, "
           "they act as a prism and form a rainbow.")
DEFAULT_PHRASE = "This is what it sounds like when I read aloud."


class PhraseRow(QFrame):
    """One preview phrase: a bin, the words, and the chip that selects it."""

    selected = Signal(str)
    deleted = Signal(str)

    def __init__(self, text: str, built_in: bool, current: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PhraseRow")
        self.text = text
        self._built_in = built_in

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(8)

        if built_in:
            # The default phrase stays put; only added ones can be removed.
            spacer = QLabel("")
            spacer.setFixedWidth(26)
            row.addWidget(spacer)
        else:
            bin_button = QPushButton()
            bin_button.setFixedWidth(26)
            bin_button.setIcon(self.style().standardIcon(
                QStyle.StandardPixmap.SP_TrashIcon))
            bin_button.setToolTip("Remove this phrase")
            bin_button.clicked.connect(lambda: self.deleted.emit(self.text))
            row.addWidget(bin_button)

        words = QLabel(f"\u201c{text}\u201d")
        words.setWordWrap(False)
        words.setToolTip(text)
        row.addWidget(words, 1)

        self.chip = QPushButton()
        self.chip.setFixedWidth(84)
        self.chip.setToolTip(
            "Tap to make this the phrase Preview speaks"
            if not current else "Preview speaks this phrase"
        )
        self.chip.clicked.connect(lambda: self.selected.emit(self.text))
        row.addWidget(self.chip)
        self.set_current(current)

    def set_current(self, current: bool) -> None:
        self.chip.setText("current" if current else ("default" if self._built_in else "use"))
        self.chip.setObjectName("ChipOn" if current else "Chip")
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)


class SamplePlayer(QThread):
    """Produces a clip of a voice, without blocking the dialog.

    A downloaded voice is spoken locally, so it can say any phrase. One that is
    not downloaded can only play the fixed sample its publisher provides.
    """

    ready = Signal(object, int)
    failed = Signal(str)

    def __init__(self, entry: dict, key: str, phrase: str) -> None:
        super().__init__()
        self._entry, self._key, self._phrase = entry, key, phrase

    def run(self) -> None:
        try:
            if piper.is_installed(self._key):
                from ..engines.piper import PiperEngine

                clip = PiperEngine().synthesize(self._phrase, self._key, 1.0)
                self.ready.emit(clip.pcm, clip.sample_rate)
                return
            data = piper.fetch_sample(self._entry, self._key)
            self.ready.emit(decode_audio(data, 22_050), 22_050)
        except EngineError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Could not play that sample: {exc}")


class SampleFetcher(QThread):
    """Downloads the sample clips for a list of voices."""

    progress = Signal(int, int)
    done = Signal(int)

    def __init__(self, catalogue: dict, keys: list[str]) -> None:
        super().__init__()
        self._catalogue, self._keys = catalogue, keys
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:
        got = 0
        for position, key in enumerate(self._keys, start=1):
            if self._stop:
                break
            entry = self._catalogue.get(key)
            if entry and not piper.has_sample(key):
                try:
                    piper.fetch_sample(entry, key)
                    got += 1
                except Exception:
                    pass          # one missing sample should not stop the rest
            self.progress.emit(position, len(self._keys))
        self.done.emit(got)


class VoiceDownloader(QThread):
    """Fetches one voice off the interface thread."""

    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, key: str) -> None:
        super().__init__()
        self._key = key

    def run(self) -> None:
        try:
            piper.download(self._key)
        except EngineError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"Could not download that voice: {exc}")
            return
        self.finished_ok.emit(self._key)


class OfflineVoicesDialog(QDialog):
    """Browse the Piper voice catalogue and install the ones you want."""

    changed = Signal()

    def __init__(self, settings=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Offline voices")
        self.setMinimumSize(680, 520)
        self._catalogue: dict = {}
        self._tick = QTimer(self)
        self._tick.setInterval(400)
        self._tick.timeout.connect(self._refresh_buttons)
        self._tick.start()
        self._worker: VoiceDownloader | None = None
        self._sampler: SamplePlayer | None = None
        self._fetcher: SampleFetcher | None = None
        self._player = ClipPlayer()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        blurb = QLabel(
            "These are <b>Piper</b> voices, from the open Piper voice collection "
            "published at <b>huggingface.co/rhasspy/piper-voices</b> \u2014 the same "
            "voices Pied installs. They are community-trained, free to use, and "
            "work with no internet once downloaded. Each is about 60 MB.<br><br>"
            "Press <b>Preview</b> to hear one before downloading it. Higher "
            "quality sounds better and takes a little longer to speak."
        )
        blurb.setWordWrap(True)
        blurb.setTextFormat(Qt.TextFormat.RichText)
        blurb.setObjectName("Dim")
        layout.addWidget(blurb)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search voices…")
        self.search.textChanged.connect(self._refill)
        # Narrower than before, to leave room for the language filter and Preview.
        self.search.setMaximumWidth(220)
        filters.addWidget(self.search, 1)

        self.language_box = QComboBox()
        self.language_box.setMinimumWidth(180)
        self.language_box.currentIndexChanged.connect(self._refill)
        filters.addWidget(self.language_box)

        self.transport_button = QPushButton("▶")
        self.transport_button.setFixedWidth(38)
        self.transport_button.setToolTip("Play or pause the preview")
        self.transport_button.clicked.connect(self._toggle_playback)
        filters.addWidget(self.transport_button)

        filters.addStretch(1)

        self.preview_button = QPushButton("Preview")
        self.preview_button.setToolTip("Hear the selected voice")
        self.preview_button.clicked.connect(self._preview)
        filters.addWidget(self.preview_button)
        layout.addLayout(filters)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Voice", "Language", "Quality", "Size", ""])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(lambda *_: self._refresh_buttons())
        self.tree.itemDoubleClicked.connect(lambda *_: self._act())
        layout.addWidget(self.tree, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)      # busy, since size is not reported
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        phrase_title = QLabel("Preview phrase")
        phrase_title.setObjectName("Dim")
        layout.addWidget(phrase_title)

        self.phrase_box = QFrame()
        self.phrase_box.setObjectName("PhraseBox")
        self.phrase_layout = QVBoxLayout(self.phrase_box)
        self.phrase_layout.setContentsMargins(4, 4, 4, 4)
        self.phrase_layout.setSpacing(2)
        layout.addWidget(self.phrase_box)

        # Enter adds the phrase; a separate button beside a download button
        # only muddied what each one did.
        self.phrase_edit = QLineEdit()
        self.phrase_edit.setPlaceholderText(
            "Write a phrase and press Enter to add it\u2026"
        )
        self.phrase_edit.returnPressed.connect(self._add_phrase)
        layout.addWidget(self.phrase_edit)

        cache_row = QHBoxLayout()
        cache_row.setSpacing(8)
        self.cache_label = QLabel("")
        self.cache_label.setObjectName("Dim")
        cache_row.addWidget(self.cache_label, 1)

        self.fetch_button = QPushButton("Get all recordings")
        self.fetch_button.setToolTip(
            "Download the recording for every voice in the list above, so "
            "previews play instantly and work offline"
        )
        self.fetch_button.clicked.connect(self._fetch_samples)
        cache_row.addWidget(self.fetch_button)

        self.cache_delete = QPushButton("Delete saved recordings")
        self.cache_delete.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.cache_delete.setToolTip(
            "Remove the downloaded recordings. The phrases themselves stay, and "
            "recordings download again next time you preview a voice."
        )
        self.cache_delete.clicked.connect(self._delete_cache)
        cache_row.addWidget(self.cache_delete)
        layout.addLayout(cache_row)

        self.status = QLabel("")
        self.status.setObjectName("Dim")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox()
        self.action_button = buttons.addButton("Download", QDialogButtonBox.ButtonRole.ActionRole)
        self.action_button.setObjectName("Primary")
        self.action_button.clicked.connect(self._act)
        close = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close.clicked.connect(self.reject)
        layout.addWidget(buttons)

        # Enter in the phrase box should only add a phrase. Without this, Qt
        # also fires whichever button it considers the dialog's default.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

        self._rebuild_phrases()
        self._load()

    # -- data --------------------------------------------------------------

    def _load(self) -> None:
        try:
            self._catalogue = piper.load_catalogue()
        except EngineError as exc:
            self._catalogue = {}
            self.status.setText(str(exc).splitlines()[0])
            return

        languages = sorted({
            (entry.get("language") or {}).get("name_english") or "Other"
            for entry in self._catalogue.values()
        })
        self.language_box.blockSignals(True)
        self.language_box.addItem("All languages", "")
        for language in languages:
            self.language_box.addItem(language, language)
        english = self.language_box.findData("English")
        self.language_box.setCurrentIndex(english if english >= 0 else 0)
        self.language_box.blockSignals(False)
        self._refill()

    def _refill(self) -> None:
        self.tree.clear()
        needle = self.search.text().strip().lower()
        wanted = self.language_box.currentData() or ""
        installed = set(piper.installed_voices())

        for key in sorted(self._catalogue):
            entry = self._catalogue[key]
            language = (entry.get("language") or {}).get("name_english") or "Other"
            if wanted and language != wanted:
                continue
            person, language_label, quality = piper.describe(key, entry)
            if needle and needle not in f"{key} {person} {language_label}".lower():
                continue
            item = QTreeWidgetItem([
                person, language_label, quality,
                _size_text(piper.download_size(entry)),
                "Installed" if key in installed else "",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setToolTip(0, key)
            if key not in installed and piper.has_sample(key):
                item.setText(4, "Preview ready")
            self.tree.addTopLevelItem(item)

        count = self.tree.topLevelItemCount()
        samples, size = piper.cached_sample_count()
        self.status.setText(
            f"{count} voice{'s' if count != 1 else ''} shown · "
            f"{len(installed)} installed · "
            f"{samples} preview{'s' if samples != 1 else ''} saved "
            f"({size / 1_000_000:.1f} MB)"
        )
        if count:
            # Preselect the recommended voice when it is in view.
            for index in range(count):
                if self.tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole) == piper.SUGGESTED:
                    self.tree.setCurrentItem(self.tree.topLevelItem(index))
                    break
            else:
                self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._refresh_buttons()

    # -- actions -----------------------------------------------------------

    def _refresh_cache_row(self) -> None:
        """One line describing the saved clips, or nothing if there are none."""
        count, size = piper.cached_sample_count()
        self.cache_delete.setVisible(count > 0)
        if not count:
            self.cache_label.setText("No preview recordings saved yet.")
            self.cache_label.setToolTip("")
            return
        self.cache_label.setText(
            f"Saved recordings of the default passage \u00b7 "
            f"{count} voice{'s' if count != 1 else ''} \u00b7 {size / 1_000_000:.1f} MB"
        )
        self.cache_label.setToolTip(f"Stored in {piper.sample_cache_dir()}")

    def _delete_cache(self) -> None:
        answer = QMessageBox.question(
            self, "Delete saved previews?",
            "Delete every saved preview clip?\n\n"
            "Your downloaded voices are not affected. Previews will be fetched "
            "again the next time you play one.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._player.stop()
        piper.clear_samples()
        self._refill()
        self.status.setText("Saved previews deleted.")

    def _current_key(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _refresh_buttons(self) -> None:
        key = self._current_key()
        busy = self._worker is not None
        self.action_button.setEnabled(bool(key) and not busy)
        self.preview_button.setEnabled(bool(key) and self._sampler is None)

        self.transport_button.setText("⏸" if self._player.playing else "▶")
        self.transport_button.setEnabled(bool(key) and self._sampler is None)
        self._refresh_cache_row()
        if key and piper.is_installed(key):
            self.action_button.setText("Remove")
            self.action_button.setObjectName("")
        else:
            self.action_button.setText("Download")
            self.action_button.setObjectName("Primary")
        # Restyle after changing the object name.
        self.action_button.style().unpolish(self.action_button)
        self.action_button.style().polish(self.action_button)

    def _toggle_playback(self) -> None:
        """Play or pause whatever preview is loaded; start one if none is."""
        if self._player.active:
            self._player.toggle()
            self._refresh_buttons()
            self.status.setText("Preview paused" if self._player.paused else "Playing preview")
            return
        self._preview()

    # -- preview phrases ---------------------------------------------------

    def _saved_phrases(self) -> list[str]:
        stored = (self._settings.get("preview_phrases") if self._settings else None) or []
        return [p for p in stored if isinstance(p, str) and p.strip()]

    def _current_phrase(self) -> str:
        chosen = (self._settings.get("preview_phrase") if self._settings else "") or RAINBOW
        if chosen != RAINBOW and chosen not in self._saved_phrases():
            return RAINBOW
        return chosen

    def _rebuild_phrases(self) -> None:
        """Redraw the phrase rows, marking which one Preview will speak."""
        while self.phrase_layout.count():
            item = self.phrase_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        current = self._current_phrase()
        entries = [(RAINBOW, True)] + [(text, False) for text in self._saved_phrases()]
        for text, built_in in entries:
            row = PhraseRow(text, built_in, text == current, self.phrase_box)
            for button in row.findChildren(QPushButton):
                button.setAutoDefault(False)
                button.setDefault(False)
            row.selected.connect(self._choose_phrase)
            row.deleted.connect(self._remove_phrase)
            self.phrase_layout.addWidget(row)

    def _choose_phrase(self, text: str) -> None:
        if self._settings is not None:
            self._settings.set("preview_phrase", text)
        self._rebuild_phrases()
        if text == RAINBOW:
            self.status.setText(
                "Preview will speak the default passage. Voices you have not "
                "downloaded always play this one."
            )
        else:
            self.status.setText(
                "Preview will speak that phrase \u2014 for voices you have "
                "downloaded. Others still play the default passage."
            )

    def _add_phrase(self) -> None:
        text = self.phrase_edit.text().strip()
        if not text or self._settings is None:
            return
        phrases = self._saved_phrases()
        if text not in phrases:
            phrases.append(text)
            self._settings.set("preview_phrases", phrases)
        self._settings.set("preview_phrase", text)
        self.phrase_edit.clear()
        self._rebuild_phrases()
        self.status.setText("Phrase added, and Preview will now speak it.")

    def _remove_phrase(self, text: str) -> None:
        if self._settings is None:
            return
        phrases = [p for p in self._saved_phrases() if p != text]
        self._settings.set("preview_phrases", phrases)
        if self._current_phrase() == text:
            self._settings.set("preview_phrase", RAINBOW)
        self._rebuild_phrases()

    def _fetch_samples(self) -> None:
        """Download the sample clips for every voice currently listed."""
        if self._fetcher is not None:
            return
        keys = [
            self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(self.tree.topLevelItemCount())
        ]
        missing = [k for k in keys if not piper.has_sample(k) and not piper.is_installed(k)]
        if not missing:
            self.status.setText("Every voice in this list already has a preview saved.")
            return
        self.progress.setRange(0, len(missing))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.fetch_button.setEnabled(False)
        self.status.setText(
            f"Downloading {len(missing)} previews \u2014 roughly "
            f"{len(missing) * 92 / 1000:.1f} MB."
        )

        fetcher = SampleFetcher(self._catalogue, missing)
        # A lambda has no thread affinity, so Qt would run it inside the
        # fetcher and touch widgets off the interface thread.
        fetcher.progress.connect(self._fetch_progress, Qt.ConnectionType.QueuedConnection)
        fetcher.done.connect(self._samples_fetched, Qt.ConnectionType.QueuedConnection)
        fetcher.finished.connect(fetcher.deleteLater)
        self._fetcher = fetcher
        fetcher.start()

    def _fetch_progress(self, done: int, _total: int) -> None:
        self.progress.setValue(done)

    def _samples_fetched(self, got: int) -> None:
        self._fetcher = None
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        self.fetch_button.setEnabled(True)
        self._refill()
        self.status.setText(f"Saved {got} preview{'s' if got != 1 else ''}. "
                            "They now play instantly, with no internet needed.")

    def _preview(self) -> None:
        """Speak the phrase with a downloaded voice, or play the published sample."""
        key = self._current_key()
        if not key or self._sampler is not None:
            return
        entry = self._catalogue.get(key)
        if not entry:
            return
        self._player.stop()
        if piper.is_installed(key):
            self.status.setText(f"Speaking with {key}\u2026")
        elif piper.has_sample(key):
            self.status.setText(f"Playing the saved sample of {key}")
        else:
            self.status.setText(f"Fetching a sample of {key}\u2026")
        sampler = SamplePlayer(entry, key, self._current_phrase())
        sampler.ready.connect(self._play_sample)
        sampler.failed.connect(self._sample_failed)
        sampler.finished.connect(sampler.deleteLater)
        self._sampler = sampler
        self._refresh_buttons()
        sampler.start()

    def _play_sample(self, pcm, sample_rate: int) -> None:
        self._sampler = None
        try:
            self._player.play(pcm, sample_rate)
        except Exception as exc:
            self._refresh_buttons()
            self.status.setText(f"Could not reach your speakers: {exc}")
            return
        self._refresh_buttons()
        key = self._current_key()
        if piper.is_installed(key or ""):
            self.status.setText(f"{key} saying your phrase")
        else:
            self.status.setText(f"{key} \u2014 the publisher's sample. "
                                "Download it to hear your own phrase.")
        self._refill()

    def _sample_failed(self, message: str) -> None:
        self._sampler = None
        self._refresh_buttons()
        self.status.setText(message.splitlines()[0])

    def _act(self) -> None:
        key = self._current_key()
        if not key or self._worker is not None:
            return
        if piper.is_installed(key):
            piper.remove(key)
            self.status.setText(f"Removed {key}")
            self._refill()
            self.changed.emit()
            return

        self.progress.setVisible(True)
        self.status.setText(f"Downloading {key}… this usually takes a few seconds.")
        self._refresh_buttons()

        worker = VoiceDownloader(key)
        worker.finished_ok.connect(self._downloaded)
        worker.failed.connect(self._download_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _downloaded(self, key: str) -> None:
        self._worker = None
        self.progress.setVisible(False)
        self.status.setText(f"{key} is ready to use offline.")
        self._refill()
        self.changed.emit()

    def _download_failed(self, message: str) -> None:
        self._worker = None
        self.progress.setVisible(False)
        self._refresh_buttons()
        QMessageBox.warning(self, "Download failed", message)

    def reject(self) -> None:
        self._player.stop()
        if self._fetcher is not None:
            self._fetcher.cancel()
        if self._worker is not None:
            QMessageBox.information(self, "Still downloading",
                                    "Wait for the download to finish first.")
            return
        super().reject()
