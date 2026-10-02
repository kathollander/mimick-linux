"""Downloading and removing the offline Piper voices."""

from __future__ import annotations

import sounddevice as sd

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QFrame, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..engines import EngineError
from ..audio_preview import ClipPlayer
from ..engines import piper
from ..engines.base import decode_audio


def _size_text(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "—"
    return f"{size_bytes / 1_000_000:.0f} MB"


# The passage every Piper voice is recorded saying. Because the publisher's
# recording exists for every voice, this is the one phrase that can be heard
# from a voice that has not been downloaded yet -- which is why it is the only
# phrase Preview uses. Reading a phrase of your own needed the voice downloaded
# first, so it could not do the one job a preview has.
RAINBOW = ("When the sunlight strikes raindrops in the air, "
           "they act as a prism and form a rainbow.")


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
        self.setMinimumSize(680, 560)
        self._catalogue: dict = {}
        self._tick = QTimer(self)
        self._tick.setInterval(400)
        self._tick.timeout.connect(self._refresh_buttons)
        self._tick.start()
        self._worker: VoiceDownloader | None = None
        self._sampler: SamplePlayer | None = None
        self._player = ClipPlayer()
        # The voice the nickname box is showing, and a flag held up while the
        # list is rebuilt: between them they stop a refill overwriting a name
        # part typed.
        self._nickname_key: str | None = None
        self._filling = False
        self._shown = self._installed = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        blurb = QLabel(
            "These are <b>Piper</b> voices, from the open collection at "
            "<b>huggingface.co/rhasspy/piper-voices</b> \u2014 the same voices Pied "
            "installs. Community-trained, free, and they work with no internet "
            "once downloaded; about 60 MB each, and higher quality takes a little "
            "longer to speak. <b>Preview</b> hears one before you download it, and "
            "a <b>nickname</b> is whatever will remind you which one you liked \u2014 "
            "it shows in italics."
        )
        blurb.setWordWrap(True)
        blurb.setTextFormat(Qt.TextFormat.RichText)
        blurb.setObjectName("Dim")
        # A wrapped label reports a one-line minimum, so a layout with anything
        # else asking for room clips it. This makes the layout ask the label how
        # tall it needs to be at the width it has been given.
        policy = blurb.sizePolicy()
        policy.setHeightForWidth(True)
        blurb.setSizePolicy(policy)
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
        filters.addStretch(1)
        layout.addLayout(filters)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Voice", "Language", "Quality", "Size", ""])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Nothing is typed into the list. Naming a voice by clicking its name a
        # second time, or with F2, was easy to trigger by accident and easy to
        # miss on purpose; the nickname box under the list does it instead.
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(lambda *_: self._voice_picked())
        self.tree.itemDoubleClicked.connect(lambda *_: self._act())
        # A floor for the list, so the row beneath it cannot squeeze the thing
        # the window is for down to a few rows.
        self.tree.setMinimumHeight(220)
        layout.addWidget(self.tree, 1)

        # Everything done to whichever voice is picked out, in one row under
        # the list: getting it on the left, naming and hearing it on the right.
        # Download used to sit in the dialog's button box beside Close, a long
        # way from the list it acts on.
        controls = QHBoxLayout()
        controls.setSpacing(8)
        # Clear of the list: the row read as being inside it otherwise, and the
        # scrollbar came down to meet the buttons.
        controls.setContentsMargins(0, 4, 0, 2)

        self.action_button = QPushButton("Download")
        self.action_button.setObjectName("Primary")
        self.action_button.clicked.connect(self._act)
        controls.addWidget(self.action_button)
        controls.addStretch(1)

        self.nickname_edit = QLineEdit()
        self.nickname_edit.setPlaceholderText("Nickname\u2026")
        self.nickname_edit.setMaximumWidth(180)
        self.nickname_edit.setToolTip(
            "What to call the selected voice. Empty it to put its own name back."
        )
        self.nickname_edit.returnPressed.connect(self._set_nickname)
        controls.addWidget(self.nickname_edit)

        self.nickname_button = QPushButton("Set nickname")
        self.nickname_button.setToolTip("Give the selected voice this name")
        self.nickname_button.clicked.connect(self._set_nickname)
        controls.addWidget(self.nickname_button)

        self.transport_button = QPushButton("▶")
        self.transport_button.setFixedWidth(38)
        self.transport_button.setToolTip("Play or pause the preview")
        self.transport_button.clicked.connect(self._toggle_playback)
        controls.addWidget(self.transport_button)

        self.preview_button = QPushButton("Preview")
        self.preview_button.setToolTip("Hear the selected voice")
        self.preview_button.clicked.connect(self._preview)
        controls.addWidget(self.preview_button)
        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)      # busy, since size is not reported
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # What Preview will say. Every voice is recorded saying this passage,
        # so it is the same words whether the voice is downloaded or not.
        phrase = QFrame()
        phrase.setObjectName("PhraseBox")
        phrase_layout = QVBoxLayout(phrase)
        phrase_layout.setContentsMargins(10, 8, 10, 8)
        quote = QLabel(f"\u201c{RAINBOW}\u201d")
        quote.setObjectName("Dim")
        quote.setWordWrap(True)
        policy = quote.sizePolicy()
        policy.setHeightForWidth(True)
        quote.setSizePolicy(policy)
        phrase_layout.addWidget(quote)
        layout.addWidget(phrase)

        self.status = QLabel("")
        self.status.setObjectName("Dim")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox()
        close = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close.clicked.connect(self.reject)
        layout.addWidget(buttons)

        # Enter in the nickname box should only set a nickname. Without this,
        # Qt also fires whichever button it considers the dialog's default.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

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

    def _nickname(self, key: str) -> str:
        return self._settings.nickname(key) if self._settings else ""

    def _refill(self) -> None:
        """Redraw the list, keeping the reader where they were.

        This runs after a preview as well as after a search, so it must not
        move the selection: losing your place in six hundred voices every time
        you listened to one made the list impossible to work through.
        """
        keep = self._current_key()
        scrolled = self.tree.verticalScrollBar().value()
        self._filling = True
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
            nickname = self._nickname(key)
            if needle and needle not in f"{key} {person} {nickname} {language_label}".lower():
                continue
            item = QTreeWidgetItem([
                nickname or person, language_label, quality,
                _size_text(piper.download_size(entry)),
                "Installed" if key in installed else "",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            # The real name is kept beside the key so a nickname can be cleared
            # by typing the name back, or by emptying the box.
            item.setData(0, Qt.ItemDataRole.UserRole + 1, person)
            item.setToolTip(0, self._name_tip(key, person, nickname))
            if nickname:
                # A name the reader gave is set in italics, so it is obvious
                # which voices have been named and which are as published.
                font = item.font(0)
                font.setItalic(True)
                item.setFont(0, font)
            if key not in installed and piper.has_sample(key):
                item.setText(4, "Preview ready")
            self.tree.addTopLevelItem(item)

        count = self.tree.topLevelItemCount()
        self._shown, self._installed = count, len(installed)
        self.status.setText(self._list_summary())
        if count:
            self._select(keep)
            if keep and self._current_key() == keep:
                # The same voice is still picked out, so the view should not
                # jump either.
                self.tree.verticalScrollBar().setValue(scrolled)
        self._filling = False
        self._show_nickname()
        self._refresh_buttons()

    @staticmethod
    def _name_tip(key: str, person: str, nickname: str) -> str:
        if nickname:
            return f"{person} \u00b7 {key}\nYou call this one {nickname}"
        return key

    def _select(self, key: str | None) -> None:
        """Pick out a voice by key, falling back to the suggested one."""
        for wanted in (key, piper.SUGGESTED):
            if not wanted:
                continue
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item.data(0, Qt.ItemDataRole.UserRole) == wanted:
                    self.tree.setCurrentItem(item)
                    self.tree.scrollToItem(item)
                    return
        self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _current_person(self) -> str:
        """The voice's published name, kept beside its key in the list."""
        item = self.tree.currentItem()
        return (item.data(0, Qt.ItemDataRole.UserRole + 1) or "") if item else ""

    def _voice_picked(self) -> None:
        """A different voice is picked out, so the box shows that one's name."""
        self._show_nickname()
        self._say_which_voice()
        self._refresh_buttons()

    def _list_summary(self) -> str:
        shown, installed = self._shown, self._installed
        return (f"{shown} voice{'s' if shown != 1 else ''} shown · "
                f"{installed} installed")

    def _say_which_voice(self) -> None:
        """Name the voice under a nickname, for whoever gave it one.

        A name of your own is the only thing in the list that hides what the
        voice is actually called, so picking one out says so. Voices with no
        nickname hide nothing, and put the list's own summary back rather than
        leaving the last voice's line standing.

        Only ever from a selection the reader made. A refill is not one: it
        walks the selection down the whole list as it fills, and the status
        line it writes itself is the summary anyway. Writing this line from
        `_refill` as well put it over the top of the preview's line -- trap 15
        in its third guise.
        """
        if self._filling:
            return
        key = self._current_key()
        nickname = self._nickname(key or "")
        if not key or not nickname:
            self.status.setText(self._list_summary())
            return
        self.status.setText(f"{nickname} is your name for "
                            f"{self._current_person()} · {key}")

    def _show_nickname(self) -> None:
        """Put the selected voice's nickname in the box.

        Only when the selection has actually moved, and never mid-refill: a
        refill runs after every preview, and a tree being filled reports each
        row it is given as the current one, so the selection appears to walk
        the whole list. Either would wipe a name part typed.
        """
        key = self._current_key()
        if self._filling or key is None or key == self._nickname_key:
            return
        self._nickname_key = key
        self.nickname_edit.setText(self._nickname(key or ""))

    def _set_nickname(self) -> None:
        """Remember what the reader has decided to call the selected voice."""
        key = self._current_key()
        if not key or self._settings is None:
            return
        person = self._current_person()
        typed = self.nickname_edit.text().strip()
        self._settings.set_nickname(key, "" if typed == person else typed)
        nickname = self._nickname(key)
        self._refill()
        self.nickname_edit.setText(nickname)
        self.status.setText(
            f"{person} is now {nickname} to you." if nickname
            else f"{person} goes by its own name again."
        )

    # -- actions -----------------------------------------------------------

    def _current_key(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _refresh_buttons(self) -> None:
        key = self._current_key()
        busy = self._worker is not None
        self.action_button.setEnabled(bool(key) and not busy)
        self.preview_button.setEnabled(bool(key) and self._sampler is None)
        self.nickname_edit.setEnabled(bool(key))
        self.nickname_button.setEnabled(bool(key))

        self.transport_button.setText("⏸" if self._player.playing else "▶")
        self.transport_button.setEnabled(bool(key) and self._sampler is None)
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

    def _preview(self) -> None:
        """Speak the passage with a downloaded voice, or play the recording of it."""
        key = self._current_key()
        if not key or self._sampler is not None:
            return
        entry = self._catalogue.get(key)
        if not entry:
            return
        self._player.stop()
        name = self._nickname(key) or key
        if piper.is_installed(key):
            self.status.setText(f"Speaking with {name}\u2026")
        elif piper.has_sample(key):
            self.status.setText(f"Playing the saved sample of {name}")
        else:
            self.status.setText(f"Fetching a sample of {name}\u2026")
        sampler = SamplePlayer(entry, key, RAINBOW)
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
        # Before the status line, not after: the refill writes a line of its
        # own, and it used to wipe this one out immediately.
        self._refill()
        name = self._nickname(key or "") or key
        if piper.is_installed(key or ""):
            self.status.setText(f"{name} reading the passage")
        else:
            self.status.setText(f"{name} \u2014 the publisher's recording")

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
            self._refill()
            # After the refill, not before: the refill writes a status line of
            # its own, and it used to wipe this one out immediately.
            self.status.setText(f"Removed {key}")
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
        if self._worker is not None:
            QMessageBox.information(self, "Still downloading",
                                    "Wait for the download to finish first.")
            return
        super().reject()
