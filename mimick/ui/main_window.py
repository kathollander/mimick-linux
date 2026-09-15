"""The Mimick window: a PDF on the left of nothing, and a voice reading it."""

from __future__ import annotations

from pathlib import Path

import sounddevice as sd

from PySide6.QtCore import (QCoreApplication, QEvent, QEventLoop, QPoint, Qt, QThread,
                            QTime, QTimer, Signal, Slot)
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QApplication, QMenu, QMessageBox, QProgressDialog, QPushButton, QSizePolicy,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ..annotations import (COLOURS, AnnotationStore, companion_for,
                           existing_companion, fallback_companion_for)
from ..apps import reveal
from .. import layout
from ..config import NOTES_DIR, Settings
from ..document import Document
from ..engines import Engine, EngineError, Voice, build_engine
from ..engines import kokoro as kokoro_engine
from ..engines import piper as piper_engine
from ..export import ExportWorker
from .about_dialog import AboutDialog
from .export_dialog import ExportDialog, ExportProgressDialog
from .shortcuts_dialog import ShortcutsDialog
from .note_dialog import NoteDialog, NoteStyleDialog, _same_colour, colour_swatch
from .voices_dialog import OfflineVoicesDialog
from ..player import Player
from . import theme
from .markup_bar import HOMES, MarkupBar
from .page_view import PageView

SPEEDS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
# How long after the last change the notes are written. Long enough that
# highlighting three sentences in a row is one save, short enough that closing
# the lid straight afterwards does not lose anything.
AUTOSAVE_DELAY_MS = 1200
# How long the window stays up after a save on the way out, so the confirmation
# in the corner is actually readable rather than a flicker.
CLOSING_PAUSE_MS = 900
PREVIEW_TEXT = "This is how I sound when I read your documents aloud."
# How many highlights and notes back Ctrl+Z reaches. Deep enough to cover a
# misfire noticed a few passages later, shallow enough that the stack is not
# quietly holding a session's worth of dead annotations.
UNDO_DEPTH = 50

# How a click on the page behaves.
MODE_CLICK = "click"        # click a sentence to read from there
MODE_SELECT = "select"      # only read what you have selected


class VoiceLoader(QThread):
    """Fetches the voice list off the UI thread, since it may hit the network."""

    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine

    def run(self) -> None:
        try:
            self.loaded.emit(self._engine.list_voices())
        except EngineError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Could not load the voice list: {exc}")


class ExportEvent(QEvent):
    """Carries a finished conversion back to the interface thread.

    PySide6 delivers a worker's signals straight into the worker thread even
    with Slot decorations and a queued connection, and closing the thread down
    from inside itself deadlocks. A posted event is the one mechanism Qt
    guarantees is handled in the receiving object's own thread.
    """

    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, kind: str, payload: str = "") -> None:
        super().__init__(ExportEvent.TYPE)
        self.kind = kind
        self.payload = payload


class PreviewWorker(QThread):
    """Renders a short sample off the UI thread."""

    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, engine: Engine, voice: str, rate: float) -> None:
        super().__init__()
        self._engine, self._voice, self._rate = engine, voice, rate

    def run(self) -> None:
        try:
            self.ready.emit(self._engine.render(PREVIEW_TEXT, self._voice, self._rate))
        except EngineError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Could not play a sample: {exc}")


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.document: Document | None = None
        self.engine: Engine = build_engine(settings.get("engine", "edge"))
        self.voices: list[Voice] = []
        self._voice_loader: VoiceLoader | None = None
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._preview: PreviewWorker | None = None
        self._export_progress = None
        self._export_finish: dict = {}
        self._suppress_page_signal = False
        # Sentences currently loaded into the player: the whole document, or
        # just a selection while one is being read.
        self._active_sentences: list = []
        self._reading_selection = False
        self._buffering = False
        self._resume_after_voices: int | None = None
        self.store: AnnotationStore | None = None
        # Ctrl+Z. Each entry is (said when undone, said when redone, undo,
        # redo); both halves find the annotation they act on by word index
        # rather than holding on to the object, because undoing a deletion has
        # to build a new one.
        self._undo_stack: list[tuple[str, str, object, object]] = []
        self._redo_stack: list[tuple[str, str, object, object]] = []
        self._click_mode = self.settings.get("click_mode", MODE_CLICK)
        # Where this document's notes are written, and a debounce so a burst of
        # highlighting is one save rather than twenty.
        self._notes_path: Path | None = None
        self._autosave_failed = False
        self._closing_save_shown = False
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(AUTOSAVE_DELAY_MS)
        self._autosave.timeout.connect(self.save_annotations)

        self.setWindowTitle("Mimick")
        self.resize(1040, 900)

        self.player = Player(self)
        self.player.sentence_changed.connect(self._on_sentence)
        self.player.word_changed.connect(self._on_word)
        self.player.state_changed.connect(self._on_state)
        self.player.failed.connect(self._on_player_error)
        self.player.finished.connect(self._on_finished)

        self._build_ui()
        self._build_shortcuts()
        self._apply_view_settings()
        self._load_voices()
        self._update_enabled()

    # -- construction ------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())

        # Slots the markup bar can dock into. They stay empty and hidden until
        # it is dragged to one of them.
        self.markup_top = self._markup_slot()
        layout.addWidget(self.markup_top)

        # The view is its own scroll area, so it goes straight into the layout.
        self.page_view = PageView()
        self.page_view.clicked.connect(self._on_page_clicked)
        self.page_view.selection_changed.connect(self._on_selection_changed)
        self.page_view.page_changed.connect(self._on_page_scrolled)
        self.page_view.annotation_clicked.connect(self._on_annotation_clicked)
        self.page_view.annotation_activated.connect(self.edit_note)
        self.page_view.region_clicked.connect(self._on_region_clicked)
        self.page_view.context_requested.connect(self._on_page_context_menu)
        self.page_view.card_context_requested.connect(self._on_card_context_menu)
        self.page_view.annotation_remove_requested.connect(self.delete_annotation)
        layout.addWidget(self.page_view, 1)

        self.markup_bottom = self._markup_slot()
        layout.addWidget(self.markup_bottom)

        layout.addWidget(self._build_controls())
        # The bar owns the Highlight and Add note buttons, so it has to exist
        # before the notes panel, which is one of the places it can live.
        self._build_markup_bar()
        self._build_notes_panel()
        self.setCentralWidget(central)
        self._build_menus()

    @staticmethod
    def _section(align_right: bool = False) -> tuple[QWidget, QHBoxLayout]:
        """A slot in a three-part bar, so the middle part stays truly centred."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        if align_right:
            row.addStretch(1)
        return holder, row

    def _build_toolbar(self) -> QWidget:
        """Top bar: speed on the left, transport centred, voice on the right."""
        bar = QFrame()
        bar.setObjectName("ControlBar")
        outer = QHBoxLayout(bar)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(12)

        left, left_row = self._section()
        left_row.addWidget(QLabel("Speed"))
        self.speed_box = QComboBox()
        self.speed_box.setFixedWidth(86)
        for speed in SPEEDS:
            self.speed_box.addItem(f"{speed:g}\u00d7", speed)
        self.speed_box.setToolTip("How fast the voice reads")
        self.speed_box.currentIndexChanged.connect(self._on_speed_changed)
        left_row.addWidget(self.speed_box)
        left_row.addStretch(1)

        centre, centre_row = self._section()
        self.back_button = QPushButton("\u21b6")
        self.back_button.setFixedWidth(44)
        self.back_button.setToolTip("Previous sentence  (\u2190)")
        self.back_button.clicked.connect(lambda: self.player.skip(-1))
        centre_row.addWidget(self.back_button)

        self.play_button = QPushButton("Read aloud")
        self.play_button.setObjectName("Primary")
        self.play_button.setMinimumWidth(150)
        self.play_button.setToolTip("Start or pause reading  (Space)")
        self.play_button.clicked.connect(self.toggle_play)
        centre_row.addWidget(self.play_button)

        self.forward_button = QPushButton("\u21b7")
        self.forward_button.setFixedWidth(44)
        self.forward_button.setToolTip("Next sentence  (\u2192)")
        self.forward_button.clicked.connect(lambda: self.player.skip(1))
        centre_row.addWidget(self.forward_button)

        right, right_row = self._section(align_right=True)
        right_row.addWidget(QLabel("Voice"))
        self.voice_box = QComboBox()
        self.voice_box.setMinimumWidth(210)
        self.voice_box.setToolTip("Which voice reads to you")
        self.voice_box.currentIndexChanged.connect(self._on_voice_changed)
        right_row.addWidget(self.voice_box)

        self.preview_button = QPushButton("Preview")
        self.preview_button.setToolTip("Hear a sample of this voice")
        self.preview_button.clicked.connect(self.preview_voice)
        right_row.addWidget(self.preview_button)

        outer.addWidget(left, 1)
        outer.addWidget(centre, 0)
        outer.addWidget(right, 1)
        return bar

    @staticmethod
    def _markup_slot() -> QWidget:
        """An empty strip the markup bar can be dropped into, top or bottom."""
        slot = QFrame()
        slot.setObjectName("ControlBar")
        box = QVBoxLayout(slot)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        slot.hide()
        return slot

    def _build_markup_bar(self) -> None:
        """Highlight and Add note, in the strip that can be moved about.

        Both buttons used to be fixed in place, and Add note was fixed inside
        the notes panel, so it could only be reached by giving up a quarter of
        the window to the column of cards. They travel together now -- see
        ``markup_bar.py`` for the four places they can travel to.
        """
        self.highlight_button = QPushButton("Highlight")
        self.highlight_button.setToolTip("Highlight the selected text  (Ctrl+H)")
        self.highlight_button.clicked.connect(self.highlight_selection)

        self.colour_button = QPushButton()
        self.colour_button.setFixedWidth(48)
        self.colour_button.setToolTip("Highlight colour")
        self._colour = COLOURS[0][1]
        colour_menu = QMenu(self)
        for name, colour in COLOURS:
            action = QAction(colour_swatch(colour, 14), name, self)
            action.triggered.connect(lambda _checked=False, c=colour: self._set_colour(c))
            colour_menu.addAction(action)
        self.colour_button.setMenu(colour_menu)
        self._refresh_colour_button()

        # Highlight and its colour are one control wherever the bar is, so they
        # travel as one widget rather than as two the layout has to keep together.
        self.highlight_group = QWidget()
        pair = QHBoxLayout(self.highlight_group)
        pair.setContentsMargins(0, 0, 0, 0)
        pair.setSpacing(4)
        pair.addWidget(self.highlight_button, 1)
        pair.addWidget(self.colour_button)

        self.add_note_button = QPushButton("+  Add note")
        self.add_note_button.setToolTip("Highlight the selected text and write a note  (Ctrl+M)")
        self.add_note_button.clicked.connect(self.note_selection)

        self.markup_bar = MarkupBar(self.page_view.viewport())
        # Add note first, Highlight under it: writing is what the panel is for.
        self.markup_bar.set_buttons([self.add_note_button, self.highlight_group])
        self.markup_bar.set_stage(self.page_view.viewport())
        self.markup_bar.home_changed.connect(self._on_markup_moved)
        self.markup_bar.detached.connect(
            lambda point: self._place_markup_bar("float", point))

    def _build_notes_panel(self) -> None:
        """The controls docked at the top and bottom of the notes panel."""
        header = QFrame()
        header.setObjectName("NotesPanel")
        stack = QVBoxLayout(header)
        stack.setContentsMargins(10, 8, 10, 8)
        stack.setSpacing(6)

        # Sift the panel: quotes you only marked, versus ones you wrote on.
        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.filter_quotes = QPushButton("Highlights")
        self.filter_written = QPushButton("Notes")
        for button, slot in ((self.filter_quotes, "quotes"), (self.filter_written, "written")):
            button.setCheckable(True)
            button.setChecked(True)
            button.setObjectName("FilterChip")
            button.clicked.connect(self._on_card_filter_changed)
            filters.addWidget(button, 1)
        self.filter_quotes.setToolTip("Show passages you highlighted without writing anything")
        self.filter_written.setToolTip("Show the ones you wrote a note on")
        stack.addLayout(filters)

        # Where the markup bar sits when it is clipped into the panel. It is
        # put in and taken out by _place_markup_bar, so this stays an empty
        # slot the rest of the time.
        self.markup_slot = QVBoxLayout()
        self.markup_slot.setContentsMargins(0, 0, 0, 0)
        self.markup_slot.setSpacing(0)
        stack.addLayout(self.markup_slot)

        top = QHBoxLayout()
        top.setSpacing(6)
        stack.addLayout(top)

        top.addStretch(1)
        self.prev_note_button = QPushButton("\u2039")
        self.prev_note_button.setFixedWidth(30)
        self.prev_note_button.setToolTip("Previous note  (Ctrl+K)")
        self.prev_note_button.clicked.connect(lambda: self._step_note(-1))
        top.addWidget(self.prev_note_button)

        self.next_note_button = QPushButton("\u203a")
        self.next_note_button.setFixedWidth(30)
        self.next_note_button.setToolTip("Next note  (Ctrl+J)")
        self.next_note_button.clicked.connect(lambda: self._step_note(1))
        top.addWidget(self.next_note_button)

        self.note_style_button = QPushButton("\u2699")
        self.note_style_button.setFixedWidth(32)
        self.note_style_button.setToolTip("How notes look \u2014 typeface and size")
        self.note_style_button.clicked.connect(self.choose_note_style)
        top.addWidget(self.note_style_button)

        footer = QFrame()
        footer.setObjectName("NotesPanel")
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(10, 8, 10, 10)
        bottom.setSpacing(6)
        self.note_count_label = QLabel("")
        self.note_count_label.setObjectName("Dim")
        bottom.addWidget(self.note_count_label)
        bottom.addStretch(1)
        self.save_notes_button = QPushButton("Save notes")
        self.save_notes_button.setToolTip(
            "Save your highlights and notes now \u2014 they also save "
            "themselves to a copy as you work  (Ctrl+S)")
        self.save_notes_button.clicked.connect(lambda _checked=False: self.save_annotations())
        bottom.addWidget(self.save_notes_button)

        self.notes_header, self.notes_footer = header, footer
        self.page_view.set_panel_widgets(header, footer)

    def _build_controls(self) -> QWidget:
        """Bottom bar: pages centred, reading position and zoom on the right."""
        bar = QFrame()
        bar.setObjectName("ControlBar")
        outer = QHBoxLayout(bar)
        outer.setContentsMargins(14, 8, 14, 10)
        outer.setSpacing(12)

        left, left_row = self._section()
        self.status_label = QLabel("Open a PDF to begin")
        self.status_label.setObjectName("Dim")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # Ignored width: a long message is clipped rather than shoving the
        # page controls out of the centre.
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # Takes the stretch itself: a trailing spacer would squeeze it to nothing.
        left_row.addWidget(self.status_label, 1)

        centre, centre_row = self._section()
        self.prev_page_button = QPushButton("\u2039")
        self.prev_page_button.setFixedWidth(38)
        self.prev_page_button.setToolTip("Previous page  (Page Up)")
        self.prev_page_button.clicked.connect(lambda: self._go_page(self.page_view.page - 1))
        centre_row.addWidget(self.prev_page_button)

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setFixedWidth(74)
        self.page_spin.setToolTip("Jump to page")
        self.page_spin.valueChanged.connect(self._on_page_spin)
        centre_row.addWidget(self.page_spin)

        self.page_total = QLabel("of \u2014")
        self.page_total.setObjectName("Dim")
        centre_row.addWidget(self.page_total)

        self.next_page_button = QPushButton("\u203a")
        self.next_page_button.setFixedWidth(38)
        self.next_page_button.setToolTip("Next page  (Page Down)")
        self.next_page_button.clicked.connect(lambda: self._go_page(self.page_view.page + 1))
        centre_row.addWidget(self.next_page_button)

        right, right_row = self._section(align_right=True)
        zoom_out = QPushButton("\u2212")
        zoom_out.setFixedWidth(30)
        zoom_out.setToolTip("Zoom out  (Ctrl+\u2212)")
        zoom_out.clicked.connect(lambda: self._zoom_by(1 / 1.15))
        right_row.addWidget(zoom_out)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(40, 400)       # per cent of natural size
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.setToolTip("Zoom")
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider)
        right_row.addWidget(self.zoom_slider)

        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(30)
        zoom_in.setToolTip("Zoom in  (Ctrl++)")
        zoom_in.clicked.connect(lambda: self._zoom_by(1.15))
        right_row.addWidget(zoom_in)

        # Typeable, so an exact zoom can be set without dragging the slider.
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(40, 400)
        self.zoom_spin.setSuffix("%")
        self.zoom_spin.setFixedWidth(78)
        self.zoom_spin.setToolTip("Zoom \u2014 click to type an exact amount")
        self.zoom_spin.setKeyboardTracking(False)   # wait for Enter, not each digit
        self.zoom_spin.valueChanged.connect(self._on_zoom_spin)
        right_row.addWidget(self.zoom_spin)

        outer.addWidget(left, 1)
        outer.addWidget(centre, 0)
        outer.addWidget(right, 1)
        return bar

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        act_open = QAction("&Open PDF…", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.open_file)
        file_menu.addAction(act_open)

        self.recent_menu = file_menu.addMenu("Open &Recent")
        self._refresh_recent()
        file_menu.addSeparator()

        self.act_export = QAction("&Convert to MP3\u2026", self)
        self.act_export.setToolTip("Turn this PDF into an audio file")
        self.act_export.triggered.connect(self.export_audio)
        file_menu.addAction(self.act_export)
        file_menu.addSeparator()
        self.act_save = QAction("&Save", self)
        self.act_save.setToolTip(
            "Save your highlights and notes now \u2014 they also save "
            "themselves to a copy as you work")
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        # triggered carries a checked flag; it must not land in `quiet`.
        self.act_save.triggered.connect(lambda _checked=False: self.save_annotations())
        file_menu.addAction(self.act_save)

        self.act_save_copy = QAction("Save &As\u2026", self)
        self.act_save_copy.setToolTip("Write a separate PDF, with your highlights and notes")
        self.act_save_copy.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.act_save_copy.triggered.connect(self.save_annotations_copy)
        file_menu.addAction(self.act_save_copy)
        file_menu.addSeparator()

        act_quit = QAction("&Quit", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        display_menu = self.menuBar().addMenu("&Display")
        self.act_annotation_bar = QAction("&Highlight and note buttons", self, checkable=True)
        self.act_annotation_bar.setShortcut(QKeySequence("Ctrl+T"))
        self.act_annotation_bar.setToolTip("The Highlight and Add note buttons, "
                                           "wherever you have put them")
        self.act_annotation_bar.triggered.connect(self._toggle_markup_bar)
        display_menu.addAction(self.act_annotation_bar)

        # Where those buttons sit. Dragging them does the same thing; this is
        # here so the arrangement can be found without knowing to drag.
        where_menu = display_menu.addMenu("Put those buttons")
        self._markup_home_actions = {}
        labels = {"panel": "In the &notes panel", "top": "Across the &top",
                  "bottom": "Across the &bottom", "float": "&Loose over the page"}
        group = QActionGroup(self)
        group.setExclusive(True)
        for name in HOMES:
            action = QAction(labels[name], self, checkable=True)
            action.triggered.connect(
                lambda _checked=False, n=name: self._place_markup_bar(n, announce=True))
            group.addAction(action)
            where_menu.addAction(action)
            self._markup_home_actions[action] = name

        self.act_filter_quotes = QAction("Show &highlights in the panel", self, checkable=True)
        self.act_filter_quotes.setChecked(True)
        self.act_filter_quotes.triggered.connect(
            lambda checked: self._set_card_filter(quotes=checked))
        self.act_filter_written = QAction("Show &notes in the panel", self, checkable=True)
        self.act_filter_written.setChecked(True)
        self.act_filter_written.triggered.connect(
            lambda checked: self._set_card_filter(written=checked))

        self.act_show_plan = QAction("Show &reading order", self, checkable=True)
        self.act_show_plan.setShortcut(QKeySequence("Ctrl+R"))
        self.act_show_plan.setToolTip(
            "Outline what Mimick will read, in order, and what it is leaving out.\n"
            "Click any region to include or exclude it."
        )
        self.act_show_plan.triggered.connect(self._toggle_plan)
        display_menu.addAction(self.act_show_plan)

        self.act_skip_citations = QAction("Skip &citations while reading", self, checkable=True)
        self.act_skip_citations.setToolTip(
            "Pass over things like [51] and (Smith et al., 2020) instead of\n"
            "reading them out in the middle of a sentence."
        )
        self.act_skip_citations.setChecked(True)
        self.act_skip_citations.triggered.connect(self._toggle_citations)
        display_menu.addAction(self.act_skip_citations)

        self.act_clean_text = QAction("Clean &up text for reading", self, checkable=True)
        self.act_clean_text.setToolTip(
            "Read the document, not the paperwork around it.\n\n"
            "Expands the ﬁ and ﬂ ligatures a PDF stores as single characters,\n"
            "repairs stranded accents, and passes over the masthead, the\n"
            "author declarations and the reference list.\n\n"
            "Applies to reading aloud and to converting to MP3 alike.\n"
            "Ctrl+R shows what is being left out; click a region to put it back."
        )
        self.act_clean_text.setChecked(True)
        self.act_clean_text.triggered.connect(self._toggle_clean_text)
        display_menu.addAction(self.act_clean_text)

        act_reset_plan = QAction("Reset reading order", self)
        act_reset_plan.setToolTip("Forget your changes and analyse this document again")
        act_reset_plan.triggered.connect(self.forget_region_choices)
        display_menu.addAction(act_reset_plan)

        self.act_show_notes = QAction("&Notes panel", self, checkable=True)
        self.act_show_notes.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.act_show_notes.setToolTip("The column of notes beside the page")
        self.act_show_notes.setChecked(True)
        self.act_show_notes.triggered.connect(self._toggle_notes)
        display_menu.addAction(self.act_show_notes)
        display_menu.addAction(self.act_filter_quotes)
        display_menu.addAction(self.act_filter_written)


        display_menu.addSeparator()

        self.mode_menu = display_menu.addMenu("&Click to read")
        self.mode_menu.setToolTip("Whether clicking a sentence starts reading it")
        self.act_mode_click = QAction("On", self, checkable=True)
        self.act_mode_click.setToolTip("Click a sentence on the page to read from there")
        self.act_mode_select = QAction("Off", self, checkable=True)
        self.act_mode_select.setToolTip("Clicking never starts reading; select text and press Enter")
        self.act_mode_click.triggered.connect(lambda: self._set_click_mode(MODE_CLICK))
        self.act_mode_select.triggered.connect(lambda: self._set_click_mode(MODE_SELECT))
        self.mode_menu.addAction(self.act_mode_click)
        self.mode_menu.addAction(self.act_mode_select)
        display_menu.addSeparator()

        for label, shortcut, zoom in [("Zoom &in", "Ctrl++", 1.15),
                                      ("Zoom &out", "Ctrl+-", 1 / 1.15)]:
            action = QAction(label, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda _checked=False, f=zoom: self._zoom_by(f))
            display_menu.addAction(action)
        act_reset_zoom = QAction("&Reset zoom", self)
        act_reset_zoom.setShortcut(QKeySequence("Ctrl+0"))
        act_reset_zoom.triggered.connect(lambda: self._set_zoom(1.25))
        display_menu.addAction(act_reset_zoom)

        self.notes_menu = notes_menu = self.menuBar().addMenu("&Notes")
        self.act_copy = QAction("&Copy", self)
        self.act_copy.setToolTip("Copy the selected words \u2014 or, with a "
                                 "highlight picked out, that passage and its note")
        self.act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        self.act_copy.triggered.connect(self.copy_selection)
        notes_menu.addAction(self.act_copy)
        notes_menu.addSeparator()

        self.act_highlight = QAction("&Highlight selection", self)
        self.act_highlight.setShortcut(QKeySequence("Ctrl+H"))
        self.act_highlight.triggered.connect(self.highlight_selection)
        notes_menu.addAction(self.act_highlight)

        self.act_note = QAction("Highlight and write a &note\u2026", self)
        self.act_note.setShortcut(QKeySequence("Ctrl+M"))
        self.act_note.triggered.connect(self.note_selection)
        notes_menu.addAction(self.act_note)
        notes_menu.addSeparator()

        act_next_note = QAction("Go to ne&xt note", self)
        act_next_note.setShortcut(QKeySequence("Ctrl+J"))
        act_next_note.triggered.connect(lambda: self._step_note(1))
        notes_menu.addAction(act_next_note)

        act_prev_note = QAction("Go to &previous note", self)
        act_prev_note.setShortcut(QKeySequence("Ctrl+K"))
        act_prev_note.triggered.connect(lambda: self._step_note(-1))
        notes_menu.addAction(act_prev_note)
        notes_menu.addSeparator()

        notes_menu.addSeparator()

        self.act_undo = QAction("&Undo the last highlight or note", self)
        self.act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self.act_undo.triggered.connect(self.undo_annotation)
        notes_menu.addAction(self.act_undo)

        self.act_redo = QAction("&Redo it", self)
        self.act_redo.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self.act_redo.triggered.connect(self.redo_annotation)
        notes_menu.addAction(self.act_redo)

        notes_menu.addSeparator()

        act_note_style = QAction("Note &appearance\u2026", self)
        act_note_style.setToolTip("Typeface, size and your name on notes")
        act_note_style.triggered.connect(self.choose_note_style)
        notes_menu.addAction(act_note_style)

        voice_menu = self.menuBar().addMenu("&Voice")
        self.act_online = QAction("&Edge voices \u2014 online, most natural", self, checkable=True)
        self.act_piper = QAction("&Piper voices \u2014 offline", self, checkable=True)
        self.act_kokoro = QAction("&Kokoro voice \u2014 offline, slower", self, checkable=True)
        self._engine_actions = {
            "edge": self.act_online, "piper": self.act_piper, "kokoro": self.act_kokoro,
        }
        for engine_id, action in self._engine_actions.items():
            action.setChecked(self.engine.id == engine_id)
            action.triggered.connect(lambda _c=False, e=engine_id: self._switch_engine(e))
            voice_menu.addAction(action)
        voice_menu.addSeparator()

        act_manage = QAction("&Manage offline voices\u2026", self)
        act_manage.setToolTip("Download voices that work without an internet connection")
        act_manage.triggered.connect(self.manage_offline_voices)
        voice_menu.addAction(act_manage)

        help_menu = self.menuBar().addMenu("&Help")
        act_keys = QAction("&Keyboard shortcuts", self)
        act_keys.triggered.connect(self.show_shortcuts)
        help_menu.addAction(act_keys)
        act_about = QAction("&About Mimick", self)
        act_about.triggered.connect(self.show_about)
        help_menu.addAction(act_about)

    def _refresh_mode_menu(self) -> None:
        """Tick the current choice and set it in italics, so it reads at a glance."""
        on = self._click_mode == MODE_CLICK
        self.act_mode_click.setChecked(on)
        self.act_mode_select.setChecked(not on)
        for action, active in ((self.act_mode_click, on), (self.act_mode_select, not on)):
            font = action.font()
            font.setItalic(active)
            action.setFont(font)
        self.mode_menu.setTitle("&Click to read" + ("  \u2014 on" if on else "  \u2014 off"))

    def _apply_view_settings(self) -> None:
        """Restore the display choices from last time."""
        self._markup_shown = bool(self.settings.get("show_annotation_bar", True))
        self.act_annotation_bar.setChecked(self._markup_shown)
        self._place_markup_bar(str(self.settings.get("markup_home", "panel")))

        self._set_card_filter(
            quotes=bool(self.settings.get("panel_shows_quotes", True)),
            written=bool(self.settings.get("panel_shows_notes", True)),
        )

        self.act_skip_citations.setChecked(bool(self.settings.get("skip_citations", True)))
        self.act_clean_text.setChecked(bool(self.settings.get("clean_text", True)))

        show_plan = bool(self.settings.get("show_plan", False))
        self.act_show_plan.setChecked(show_plan)
        self.page_view.set_plan_visible(show_plan)

        show_notes = bool(self.settings.get("show_notes", True))
        self.act_show_notes.setChecked(show_notes)
        self.page_view.set_notes_visible(show_notes)

        self.page_view.set_note_style(self.settings.get("note_font", ""),
                                      float(self.settings.get("note_size", 9.0)))

        # An earlier build could hide this; make sure it is always back.
        self.notes_menu.menuAction().setVisible(True)

        self._refresh_mode_menu()

        self.page_view.set_zoom(float(self.settings.get("zoom", 1.25)))
        self._sync_zoom_controls()

    def _build_shortcuts(self) -> None:
        def bind(sequence: str, handler) -> None:
            QShortcut(QKeySequence(sequence), self, activated=handler)

        bind("Space", self.toggle_play)
        bind("Return", self.read_selection_or_play)
        bind("Enter", self.read_selection_or_play)
        bind("Escape", self.page_view.clear_selection)
        bind("Ctrl+A", self.select_page_text)
        bind("Right", lambda: self.player.skip(1))
        bind("Left", lambda: self.player.skip(-1))
        bind("Ctrl+=", lambda: self._zoom_by(1.15))
        bind("Page Down", lambda: self._go_page(self.page_view.page + 1))
        bind("Page Up", lambda: self._go_page(self.page_view.page - 1))
        bind("Ctrl+Down", lambda: self._go_page(self.page_view.page + 1))
        bind("Ctrl+Up", lambda: self._go_page(self.page_view.page - 1))
        bind("Ctrl+Home", lambda: self._go_page(0))
        bind("Ctrl+End", lambda: self._go_page(self.document.page_count - 1 if self.document else 0))

    # -- opening documents -------------------------------------------------

    def open_file(self) -> None:
        start = self.settings.get("recent") or []
        directory = str(Path(start[0]).parent) if start and Path(start[0]).exists() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open a PDF", directory, "PDF documents (*.pdf);;All files (*)")
        if path:
            self.load_document(Path(path))

    def load_document(self, path: Path) -> None:
        if not self._offer_to_save():
            return
        self.player.stop()
        # Notes made last time live in the companion file, so that is the one to
        # open -- otherwise opening the original again would show a document
        # with no highlights on it and quietly start a second set.
        original = Path(path)
        found = existing_companion(original, NOTES_DIR)
        if found is not None:
            path = found
        try:
            document = Document(
                path,
                skip_citations=bool(self.settings.get("skip_citations", True)),
                clean_text=bool(self.settings.get("clean_text", True)),
            )
        except Exception as exc:
            self._warn("That file could not be opened",
                       f"Mimick could not read {path.name}.\n\nIt may be damaged, "
                       f"password-protected, or not a PDF.\n\n({exc})")
            return

        if not document.sentences:
            document.close()
            self._warn("No readable text",
                       f"{path.name} contains no text Mimick can read.\n\n"
                       "Scanned documents are pictures of text, so they need to be "
                       "run through OCR before any reader can speak them.")
            return

        # Point the view at the new document *before* closing the old one, so
        # nothing can dereference a document that has already been closed.
        previous = self.document
        self.document = document
        # Word indices only mean anything within one document, and the
        # annotations the stack refers to belong to the one being closed.
        self._clear_undo()
        try:
            self.store = AnnotationStore(document, self._author())
        except Exception:
            # A document whose annotations cannot be read is still worth reading aloud.
            self.store = None

        self.page_view.set_zoom(float(self.settings.get("zoom", 1.25)))
        self.page_view.set_document(document)
        self.page_view.set_store(self.store)
        if previous is not None:
            previous.close()

        self._notes_path = companion_for(path)
        self._autosave_failed = False

        self._apply_region_choices()
        # Recent files list the document the reader asked for. Opening it again
        # finds the companion again, so the entry keeps working either way.
        self.settings.note_recent(original)
        self._refresh_recent()

        self.setWindowTitle(f"{document.title} — Mimick")
        self._sync_zoom_controls()

        self._suppress_page_signal = True
        self.page_spin.setMaximum(document.page_count)
        self.page_spin.setValue(1)
        self._suppress_page_signal = False
        self.page_total.setText(f"of {document.page_count}")

        self.page_view.clear_selection()
        self._reading_selection = False
        self._active_sentences = document.sentences
        self.player.configure(document.sentences, self.engine, self._current_voice(), self._current_speed())
        resume_at = self.settings.position_for(path)
        if 0 < resume_at < len(document.sentences):
            self.player.seek(resume_at, autoplay=False)
            self._show_sentence(resume_at)
            self._set_status(f"Picked up where you left off — sentence {resume_at + 1}")
        else:
            self._set_status(f"{len(document.sentences)} sentences · press Space to start")
        if found is not None:
            self._set_status(f"Opened your annotated copy, {found.name}")
        self._update_enabled()

    def _refresh_recent(self) -> None:
        self.recent_menu.clear()
        entries = [Path(p) for p in (self.settings.get("recent") or [])]
        entries = [p for p in entries if p.exists()]
        if not entries:
            empty = QAction("Nothing yet", self)
            empty.setEnabled(False)
            self.recent_menu.addAction(empty)
            return
        for path in entries:
            action = QAction(path.name, self)
            action.setToolTip(str(path))
            action.triggered.connect(lambda _=False, p=path: self.load_document(p))
            self.recent_menu.addAction(action)

    # -- voices ------------------------------------------------------------

    def _load_voices(self) -> None:
        self.voice_box.clear()
        self.voice_box.addItem("Loading voices…", None)
        self.voice_box.setEnabled(False)
        loader = VoiceLoader(self.engine)
        loader.loaded.connect(self._on_voices_loaded)
        loader.failed.connect(self._on_voices_failed)
        loader.finished.connect(loader.deleteLater)
        # deleteLater leaves this attribute holding a wrapper whose C++ object
        # is gone; touching it then raises. Drop the reference at the same time.
        loader.finished.connect(self._forget_voice_loader)
        self._voice_loader = loader
        loader.start()

    def _forget_voice_loader(self) -> None:
        self._voice_loader = None

    def _on_voices_loaded(self, voices: list) -> None:
        self.voices = voices
        preferred = self.settings.get("voice", "en-US-AvaNeural")
        self.voice_box.blockSignals(True)
        self.voice_box.clear()
        for voice in voices:
            self.voice_box.addItem(voice.label, voice.id)
        index = self.voice_box.findData(preferred)
        self.voice_box.setCurrentIndex(index if index >= 0 else 0)
        self.voice_box.blockSignals(False)
        self.voice_box.setEnabled(True)

        speed = float(self.settings.get("rate", 1.0))
        position = self.speed_box.findData(speed)
        self.speed_box.blockSignals(True)
        self.speed_box.setCurrentIndex(position if position >= 0 else SPEEDS.index(1.0))
        self.speed_box.blockSignals(False)

        self.player.set_voice(self._current_voice(), self.engine)
        # The speed box was filled with signals blocked, so tell the player
        # about the speed explicitly rather than relying on the signal.
        self.player.set_rate(self._current_speed())
        self._update_enabled()

        if self._resume_after_voices is not None:
            index, self._resume_after_voices = self._resume_after_voices, None
            self._set_status(f"Reading on offline with {self._current_voice()}")
            self.player.play(index)

    def _on_voices_failed(self, message: str) -> None:
        self.voice_box.clear()
        self.voice_box.addItem("No voices available", None)
        self.voice_box.setEnabled(False)
        self._resume_after_voices = None
        self._update_enabled()

        if self.engine.id == "edge" and piper_engine.any_installed():
            self._set_status("No connection \u2014 using your offline voices instead")
            self._switch_engine("piper")
            return
        if self.engine.id == "edge" and self._looks_offline(message):
            self._offer_offline_voices(message)
            return
        self._warn("Voices could not be loaded", message)

    def _sync_player(self) -> None:
        """Push the on-screen voice and speed into the player.

        The controls are populated asynchronously, so this guards against the
        player still holding defaults from before the voice list arrived.
        """
        voice = self._current_voice()
        if voice and voice != self.player._voice:
            self.player.set_voice(voice, self.engine)
        self.player.set_rate(self._current_speed())

    def _current_voice(self) -> str:
        return self.voice_box.currentData() or ""

    def _current_speed(self) -> float:
        return float(self.speed_box.currentData() or 1.0)

    def _on_voice_changed(self, _index: int) -> None:
        voice = self._current_voice()
        if not voice:
            return
        self.settings.set("voice", voice)
        self.player.set_voice(voice, self.engine)

    def _on_speed_changed(self, _index: int) -> None:
        speed = self._current_speed()
        self.settings.set("rate", speed)
        self.player.set_rate(speed)

    def preview_voice(self) -> None:
        voice = self._current_voice()
        if not voice or self._preview is not None:
            return
        # Silence anything already speaking, so the sample plays on its own.
        self.stop_all_audio()
        self._set_status("Preparing a sample\u2026")

        worker = PreviewWorker(self.engine, voice, self._current_speed())
        worker.ready.connect(self._play_preview)
        worker.failed.connect(lambda m: (self._clear_preview(), self._warn("Could not play a sample", m)))
        worker.finished.connect(worker.deleteLater)
        self._preview = worker
        worker.start()

    def _play_preview(self, clip) -> None:
        self._clear_preview()
        try:
            sd.play(clip.pcm, clip.sample_rate)
        except Exception as exc:
            self._warn("No sound came out", f"Mimick could not reach your speakers.\n\n({exc})")
            return
        self._set_status(f"Sample at {self._current_speed():g}\u00d7")

    def _clear_preview(self) -> None:
        self._preview = None

    def stop_all_audio(self) -> None:
        """Stop the reader and any sample that happens to be playing."""
        self.player.stop()
        try:
            sd.stop()
        except Exception:
            pass

    def _switch_engine(self, engine_id: str) -> None:
        """Change which voice engine reads, offering a download if needed."""
        if engine_id == "piper" and not piper_engine.any_installed():
            self._check_engine_actions(self.engine.id)
            answer = QMessageBox.question(
                self, "Download an offline voice?",
                "No offline voices are installed yet.\n\n"
                "They are about 60 MB each and work with no internet "
                "afterwards. Choose one now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.manage_offline_voices()
            return

        if engine_id == "kokoro" and not kokoro_engine.is_installed():
            self._check_engine_actions(self.engine.id)
            answer = QMessageBox.question(
                self, "Download the Kokoro voice?",
                "The Kokoro voice needs a one-time download of about 350 MB.\n\n"
                "Piper voices are far smaller and much faster. Download Kokoro "
                "anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.download_kokoro()
            return

        self.stop_all_audio()
        self.engine.close()
        self.engine = build_engine(engine_id)
        self.settings.set("engine", engine_id)
        self._check_engine_actions(engine_id)
        self._load_voices()

    def _check_engine_actions(self, engine_id: str) -> None:
        for key, action in self._engine_actions.items():
            action.setChecked(key == engine_id)

    def manage_offline_voices(self) -> None:
        """Open the download manager for Piper voices."""
        dialog = OfflineVoicesDialog(self.settings, self)
        dialog.changed.connect(self._offline_voices_changed)
        dialog.exec()

    def _offline_voices_changed(self) -> None:
        """Switch to Piper once a voice exists, or refresh the list if already on it."""
        if not piper_engine.any_installed():
            return
        if self.engine.id == "piper":
            self._load_voices()
        else:
            self._switch_engine("piper")

    def download_kokoro(self) -> None:
        if kokoro_engine.is_installed():
            QMessageBox.information(self, "Already installed",
                                    "The Kokoro voice is already downloaded.")
            return
        dialog = QProgressDialog("Downloading the Kokoro voice\u2026", "Cancel", 0, 100, self)
        dialog.setWindowTitle("Offline voice")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        cancelled = {"yes": False}

        def report(fraction: float, name: str) -> None:
            if dialog.wasCanceled():
                cancelled["yes"] = True
                raise EngineError("Download cancelled.")
            dialog.setValue(int(fraction * 100))
            dialog.setLabelText(f"Downloading {name}\u2026")
            QApplication.processEvents()

        try:
            kokoro_engine.download_models(progress=report)
        except EngineError as exc:
            dialog.close()
            if not cancelled["yes"]:
                self._warn("Download failed", str(exc))
            return
        dialog.setValue(100)
        dialog.close()
        self._switch_engine("kokoro")

    # -- playback ----------------------------------------------------------

    def toggle_play(self) -> None:
        if self.document is None:
            self.open_file()
            return
        if not self._current_voice():
            self._warn("No voice selected", "Mimick has no voice to read with yet.")
            return

        if self.player.is_playing:
            self.player.pause()
            return
        if self.player.is_active:          # paused mid-sentence, so carry on
            self.player.play()
            return

        # A fresh start. If text is selected, read that; otherwise read on from
        # wherever we left off in the document.
        if self.page_view.selection is not None:
            self.read_selection()
            return
        self._play_document()

    def read_selection_or_play(self) -> None:
        """Enter: read the selection if there is one, otherwise act like Space."""
        if self.page_view.selection is not None:
            self.read_selection()
        else:
            self.toggle_play()

    def read_selection(self) -> None:
        """Read only the selected text, then go quiet."""
        span = self.page_view.selection
        if span is None or self.document is None:
            return
        if not self._current_voice():
            self._warn("No voice selected", "Mimick has no voice to read with yet.")
            return
        pieces = self.document.sentences_from_range(*span)
        if not pieces:
            self._set_status("That selection has no readable text")
            return

        self.stop_all_audio()
        self._reading_selection = True
        self._active_sentences = pieces
        self.player.configure(pieces, self.engine, self._current_voice(), self._current_speed())
        words = span[1] - span[0] + 1
        self._set_status(f"Reading your selection \u2014 {words} words")
        self.player.play(0)

    def read_annotation(self, item) -> None:
        """Read a highlighted passage aloud, then go quiet.

        The same path as reading a selection -- ``sentences_from_range`` is
        where citation skipping and the cleanup are applied, so a highlight read
        this way sounds like the same passage read any other way.
        """
        if self.document is None or item is None or item.first_word < 0:
            return
        if not self._current_voice():
            self._warn("No voice selected", "Mimick has no voice to read with yet.")
            return
        pieces = self.document.sentences_from_range(item.first_word, item.last_word)
        if not pieces:
            self._set_status("That highlight has no readable text")
            return
        self.stop_all_audio()
        self._reading_selection = True
        self._active_sentences = pieces
        self.player.configure(pieces, self.engine, self._current_voice(), self._current_speed())
        self._set_status("Reading the highlighted passage")
        self.player.play(0)

    def _play_document(self) -> None:
        """Read the whole document, continuing from the remembered position."""
        if self.document is None:
            return
        if self._reading_selection or self._active_sentences is not self.document.sentences:
            self._restore_document()
        self._sync_player()
        self.player.play()

    def _restore_document(self) -> None:
        """Put the full document back into the player after a selection."""
        if self.document is None:
            return
        resume_at = self.settings.position_for(self.document.path)
        self._reading_selection = False
        self._active_sentences = self.document.sentences
        self.player.configure(self.document.sentences, self.engine,
                              self._current_voice(), self._current_speed())
        if 0 < resume_at < len(self.document.sentences):
            self.player.seek(resume_at, autoplay=False)

    def select_page_text(self) -> None:
        """Ctrl+A: select every word on the page being shown."""
        if self.document is None:
            return
        words = self.document.page_words.get(self.page_view.page) or []
        if words:
            self.page_view.select_range(words[0].index, words[-1].index)

    def _on_selection_changed(self, first: int, last: int) -> None:
        has_selection = first >= 0
        self._refresh_copy_action()
        if has_selection and self.document is not None:
            count = last - first + 1
            self._set_status(f"{count} words selected \u2014 press Enter to read them")
        self._refresh_play_button()

    def _refresh_play_button(self) -> None:
        # While a sentence is being fetched, say so on the button itself rather
        # than in the corner of the window, where it is easy to miss.
        if self._buffering:
            self.play_button.setText("Preparing\u2026")
            return
        if self.player.is_playing:
            self.play_button.setText("Pause")
        elif self.player.is_active:
            self.play_button.setText("Resume")
        elif self.page_view.selection is not None:
            self.play_button.setText("Read selection")
        else:
            self.play_button.setText("Read aloud")

    def _set_click_mode(self, mode: str) -> None:
        self._click_mode = mode
        self.settings.set("click_mode", mode)
        self._refresh_mode_menu()
        if mode == MODE_SELECT:
            self._set_status("Drag to select text, then press Enter to read it")
        else:
            self._set_status("Click any sentence to read from there")

    def _on_sentence(self, index: int) -> None:
        self._show_sentence(index)
        # Only the document's own sentence numbers are worth remembering.
        if self.document is not None and not self._reading_selection:
            self.settings.remember_position(self.document.path, index)

    def _show_sentence(self, index: int) -> None:
        if not (0 <= index < len(self._active_sentences)):
            return
        sentence = self._active_sentences[index]
        self.page_view.set_highlight(sentence, -1)
        self._scroll_to_highlight()
        total = len(self._active_sentences)
        where = "selection" if self._reading_selection else f"page {sentence.page + 1}"
        self._set_status(f"Sentence {index + 1} of {total} \u00b7 {where}")

    def _on_word(self, sentence_index: int, word_index: int) -> None:
        if 0 <= sentence_index < len(self._active_sentences):
            self.page_view.set_highlight(self._active_sentences[sentence_index], word_index)

    def _on_state(self, state: str) -> None:
        self._buffering = state == "buffering"
        self._refresh_play_button()

    _OFFLINE_HINTS = ("could not reach", "connection", "network", "dns",
                      "timed out", "temporary failure", "unreachable", "resolve")

    def _looks_offline(self, message: str) -> bool:
        lowered = message.lower()
        return any(hint in lowered for hint in self._OFFLINE_HINTS)

    def _on_player_error(self, message: str) -> None:
        self._refresh_play_button()
        # Losing the connection mid-chapter should not end the session if an
        # offline voice is sitting right there.
        if (self.engine.id == "edge" and self._looks_offline(message)
                and piper_engine.any_installed()):
            self._fall_back_offline(resume_at=self.player.index)
            return
        if self.engine.id == "edge" and self._looks_offline(message):
            self._offer_offline_voices(message)
            return
        self._warn("Reading stopped", message)

    def _fall_back_offline(self, resume_at: int | None = None) -> None:
        """Switch to a downloaded Piper voice and carry on where we stopped."""
        self._resume_after_voices = resume_at
        self._set_status("Lost the connection \u2014 switching to an offline voice\u2026")
        self._switch_engine("piper")

    def _offer_offline_voices(self, message: str) -> None:
        answer = QMessageBox.question(
            self, "No connection",
            "The Edge voices need an internet connection, and Mimick could not "
            "reach them.\n\nYou can download an offline voice instead \u2014 about "
            "60 MB, and it works with no connection afterwards.\n\n"
            "Choose an offline voice now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.manage_offline_voices()
        else:
            self._warn("Reading stopped", message)

    def _on_finished(self) -> None:
        self.page_view.clear_highlight()
        if self._reading_selection:
            self._set_status("Finished the selection")
            self._restore_document()
        else:
            self._set_status("Reached the end of the document")
        self._refresh_play_button()

    def _on_page_clicked(self, page: int, x: float, y: float) -> None:
        if self.document is None or self._click_mode != MODE_CLICK:
            return
        self.read_from_point(page, x, y)

    def read_from_point(self, page: int, x: float, y: float) -> bool:
        """Start reading at the sentence under a point. False if it missed the text.

        Separate from the click handler because right-click reaches it too, and
        has to work in select mode -- where clicking deliberately does not read,
        which left no way at all to say "carry on from here".
        """
        if self.document is None:
            return False
        index = self.document.sentence_at_point(page, x, y)
        if index is None:
            return False      # the click missed the text, so do nothing
        self.stop_all_audio()
        if self._reading_selection or self._active_sentences is not self.document.sentences:
            self._reading_selection = False
            self._active_sentences = self.document.sentences
            self.player.configure(self.document.sentences, self.engine,
                                  self._current_voice(), self._current_speed())
        self._sync_player()
        self.player.seek(index, autoplay=True)
        return True

    def _on_page_context_menu(self, page: int, x: float, y: float, annotation) -> None:
        menu = self.build_page_menu(page, x, y, annotation)
        if menu is not None:
            menu.exec(QCursor.pos())

    def build_page_menu(self, page: int, x: float, y: float, annotation):
        """The right-click menu for a point on the page, or None if there is none.

        Built separately from showing it so what it offers can be checked
        without putting a modal menu on the screen.
        """
        if self.document is None:
            return None
        menu = QMenu(self)
        sentence = self.document.sentence_at_point(page, x, y)
        has_voice = bool(self._current_voice())

        start = menu.addAction("Start reading from here")
        start.setEnabled(sentence is not None and has_voice)
        start.triggered.connect(lambda: self.read_from_point(page, x, y))

        selection = self.page_view.selection
        if selection is not None:
            read = menu.addAction("Read the selection")
            read.setEnabled(has_voice)
            read.triggered.connect(self.read_selection)
        menu.addSeparator()

        if selection is not None:
            copy = menu.addAction("Copy")
            copy.triggered.connect(self.copy_selection)
            if self.store is not None:
                highlight = menu.addAction("Highlight")
                highlight.triggered.connect(self.highlight_selection)
                note = menu.addAction("Highlight and write a note\u2026")
                note.triggered.connect(self.note_selection)
        elif annotation is not None and self.store is not None:
            # Right-clicking a highlight offers the same things as right-clicking
            # its card in the panel, so the two cannot say different things.
            self.add_annotation_actions(menu, annotation)
        else:
            nothing = menu.addAction("Select some text to copy or highlight it")
            nothing.setEnabled(False)

        return menu

    # -- navigation --------------------------------------------------------

    def _go_page(self, page: int) -> None:
        if self.document is None:
            return
        page = max(0, min(page, self.document.page_count - 1))
        self.page_view.set_page(page)
        self._suppress_page_signal = True
        self.page_spin.setValue(page + 1)
        self._suppress_page_signal = False

    def _on_page_scrolled(self, page: int) -> None:
        """Keep the page box in step while the reader scrolls by hand."""
        self._suppress_page_signal = True
        self.page_spin.setValue(page + 1)
        self._suppress_page_signal = False

    def _on_page_spin(self, value: int) -> None:
        if not self._suppress_page_signal:
            self._go_page(value - 1)

    def _zoom_by(self, factor: float) -> None:
        self._set_zoom(self.page_view.zoom * factor)

    def _sync_zoom_controls(self, skip: str = "") -> None:
        """Put both zoom controls in step with the view, without looping."""
        percent = int(round(self.page_view.zoom * 100))
        for name, widget in (("slider", self.zoom_slider), ("spin", self.zoom_spin)):
            if name == skip:
                continue
            widget.blockSignals(True)
            widget.setValue(percent)
            widget.blockSignals(False)

    def _on_zoom_slider(self, percent: int) -> None:
        self._set_zoom(percent / 100.0, skip="slider")

    def _on_zoom_spin(self, percent: int) -> None:
        self._set_zoom(percent / 100.0, skip="spin")

    def _set_zoom(self, zoom: float, skip: str = "") -> None:
        self.page_view.set_zoom(zoom)
        self.settings.set("zoom", self.page_view.zoom)
        self._sync_zoom_controls(skip=skip)

    def _scroll_to_highlight(self) -> None:
        self.page_view.ensure_highlight_visible()

    # -- export ------------------------------------------------------------

    def export_audio(self) -> None:
        if self.document is None:
            self._warn("Nothing to convert", "Open a PDF first.")
            return
        if not self.voices:
            self._warn("No voices available", "Mimick needs a voice list before it can convert.")
            return

        folder = Path(self.settings.get("export_folder") or str(Path.home()))
        if not folder.is_dir():
            folder = Path.home()

        dialog = ExportDialog(
            self.document, self.voices, self._current_voice(), self._current_speed(),
            SPEEDS, folder, self.page_view.selection,
            self.settings.get("export_finish") or {},
            clean_text=bool(self.settings.get("clean_text", True)),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.release()
            return

        sentences = dialog.sentences()
        destination = dialog.destination()
        # The conversion's own choice, not the app's: taking the sentences is
        # the last thing that needs the second document, and the setting in
        # Display is deliberately left as it was.
        dialog.release()
        if not sentences:
            self._warn("Nothing to convert", "That range has no readable text.")
            return
        if destination.exists():
            answer = QMessageBox.question(
                self, "Replace that file?",
                f"{destination.name} already exists in that folder.\n\nReplace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.settings.set("export_folder", str(destination.parent))
        finish = dialog.finish_actions
        self.settings.set("export_finish", finish)

        # Converting hits the same voice service the reader uses, so stop reading.
        self.stop_all_audio()
        self._run_export(sentences, dialog.voice, dialog.speed, destination, finish)

    def _run_export(self, sentences: list, voice: str, speed: float,
                     destination: Path, finish: dict) -> None:
        """Start a conversion and hand the result back on the interface thread.

        The handlers below are methods on this window rather than local
        functions on purpose. Qt decides which thread a slot runs on from the
        receiver's thread, and a plain function has no receiver -- so Qt ran it
        inside the worker, where closing down that very thread deadlocked.
        """
        progress = ExportProgressDialog(len(sentences), self)
        worker = ExportWorker(sentences, self.engine, voice, speed, destination)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        self._export_progress = progress
        self._export_finish = dict(finish)

        worker.progress.connect(progress.advance)
        worker.done.connect(self._on_export_done)
        worker.failed.connect(self._on_export_failed)
        worker.cancelled.connect(self._on_export_cancelled)
        # Cancelling only sets a flag, so it can land immediately.
        progress.cancelled.connect(worker.cancel, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(thread.deleteLater)

        self._export_thread, self._export_worker = thread, worker
        thread.start()
        progress.show()

    def _finish_export(self) -> bool:
        """Close the progress window and retire the worker thread, once."""
        thread = self._export_thread
        if thread is None:
            return False
        if self._export_progress is not None:
            self._export_progress.finish()
            self._export_progress = None
        thread.quit()
        thread.wait(2000)
        self._export_thread = None
        self._export_worker = None
        return True

    # These three may be invoked on the worker thread, so they only post.
    @Slot(str)
    def _on_export_done(self, path: str) -> None:
        QCoreApplication.postEvent(self, ExportEvent("done", path))

    @Slot(str)
    def _on_export_failed(self, message: str) -> None:
        QCoreApplication.postEvent(self, ExportEvent("failed", message))

    @Slot()
    def _on_export_cancelled(self) -> None:
        QCoreApplication.postEvent(self, ExportEvent("cancelled"))

    def event(self, incoming) -> bool:  # noqa: D102 - Qt naming
        if incoming.type() == ExportEvent.TYPE:
            self._handle_export_event(incoming.kind, incoming.payload)
            return True
        return super().event(incoming)

    def _handle_export_event(self, kind: str, payload: str) -> None:
        """Runs on the interface thread, so it may touch widgets and wait."""
        if kind == "done":
            self._export_finished(payload)
        elif kind == "failed":
            if self._finish_export():
                self._warn("Could not convert", payload)
        elif kind == "cancelled":
            if self._finish_export():
                self._set_status("Conversion cancelled \u2014 nothing was saved")

    def _export_finished(self, path: str) -> None:
        finish = self._export_finish
        if not self._finish_export():
            return
        saved = Path(path)
        self._set_status(f"Saved {saved.name}")
        if finish.get("reveal"):
            reveal(saved)
        QMessageBox.information(
            self, "Conversion finished",
            f"Your audio file is ready:\n\n{path}",
        )

    # -- notes and highlights ----------------------------------------------

    def _set_colour(self, colour) -> None:
        self._colour = colour
        self._refresh_colour_button()

    def _refresh_colour_button(self) -> None:
        self.colour_button.setIcon(colour_swatch(self._colour, 14))

    def _on_card_filter_changed(self) -> None:
        self._set_card_filter(quotes=self.filter_quotes.isChecked(),
                              written=self.filter_written.isChecked())

    def _set_card_filter(self, quotes: bool | None = None,
                         written: bool | None = None) -> None:
        """Apply the panel filter, keeping the chips and the menu in step."""
        current_quotes, current_written = self.page_view.card_filter
        quotes = current_quotes if quotes is None else quotes
        written = current_written if written is None else written

        self.page_view.set_card_filter(quotes, written)
        for widget, value in ((self.filter_quotes, quotes), (self.filter_written, written)):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.act_filter_quotes.setChecked(quotes)
        self.act_filter_written.setChecked(written)
        self.settings.set("panel_shows_quotes", quotes)
        self.settings.set("panel_shows_notes", written)
        self._refresh_filter_labels()

    def _refresh_filter_labels(self) -> None:
        quotes, written = self.page_view.counts()
        self.filter_quotes.setText(f"Highlights{f'  {quotes}' if quotes else ''}")
        self.filter_written.setText(f"Notes{f'  {written}' if written else ''}")

    def _toggle_citations(self, checked: bool) -> None:
        """Read in-text citations aloud, or pass over them."""
        self.settings.set("skip_citations", checked)
        if self.document is None:
            return
        was_playing = self.player.is_playing
        self.player.stop()
        self.document.set_skip_citations(checked)
        self._reading_selection = False
        self._active_sentences = self.document.sentences
        self.player.configure(self.document.sentences, self.engine,
                              self._current_voice(), self._current_speed())
        self.page_view.clear_highlight()
        self._set_status("Citations will be skipped" if checked
                         else "Citations will be read aloud")
        if was_playing:
            self.player.play(0)

    def _toggle_plan(self, checked: bool) -> None:
        """Show or hide the outline of what will be read."""
        self.page_view.set_plan_visible(checked)
        self.settings.set("show_plan", checked)
        if checked and self.document is not None:
            reads = sum(1 for rs in self.document.regions.values() for r in rs if r.reads)
            skipped = sum(1 for rs in self.document.regions.values() for r in rs if not r.reads)
            self._set_status(
                f"Reading {reads} regions, skipping {skipped} \u2014 click one to change it"
            )
        elif not checked:
            self._set_status("Reading order hidden")

    def _toggle_clean_text(self, checked: bool) -> None:
        """Tidy the text before it reaches the voice, or read the PDF verbatim.

        This changes the reading order as well as the words -- the reference
        list stops being a region of its own -- so the reader's own corrections
        are put back afterwards.
        """
        self.settings.set("clean_text", checked)
        if self.document is None:
            return
        was_playing = self.player.is_playing
        self.player.stop()
        # Sentence numbers mean nothing across a rebuild -- this drops or adds a
        # quarter of them -- so the reader's place is held by the word they were
        # on, which keeps its index because region order does not change.
        anchor = self._current_word_anchor()
        self.document.set_clean_text(checked)
        self._apply_region_choices()
        self._reading_selection = False
        self._active_sentences = self.document.sentences
        self.player.configure(self.document.sentences, self.engine,
                              self._current_voice(), self._current_speed())
        self.page_view.clear_highlight()
        self.page_view.viewport().update()
        self._set_status(
            f"{len(self.document.sentences)} sentences · "
            + ("tidied for reading" if checked else "reading the PDF verbatim")
        )
        self.player.seek(self._sentence_for_word(anchor), autoplay=was_playing)

    def _current_word_anchor(self) -> int:
        """The document word the playhead is on, or -1 if there is nowhere to hold."""
        index = self.player.index
        if not (0 <= index < len(self._active_sentences)):
            return -1
        words = self._active_sentences[index].words
        return words[0].index if words else -1

    def _sentence_for_word(self, anchor: int) -> int:
        """The sentence to resume at so a rebuild lands back on the same passage."""
        if anchor < 0 or self.document is None:
            return 0
        for sentence in self.document.sentences:
            # The first sentence that reaches the anchor: the passage itself if
            # it survived the rebuild, otherwise the next one to be read.
            if sentence.words and sentence.words[-1].index >= anchor:
                return sentence.index
        return max(len(self.document.sentences) - 1, 0)

    def _apply_region_choices(self) -> None:
        """Put back the reading-order corrections made last time."""
        if self.document is None:
            return
        choices = self.settings.region_choices(self.document.path)
        if not choices:
            return
        changed = 0
        for page, regions in self.document.regions.items():
            for region in regions:
                key = Settings._region_key(page, region.rect)
                if key in choices and choices[key] != region.reads:
                    region.kind = layout.BODY if choices[key] else layout.SKIPPED
                    region.reason = ("you chose to read this" if choices[key]
                                     else "you chose to skip this")
                    changed += 1
        if changed:
            self.document.rebuild()
            self._set_status(
                f"Restored {changed} reading-order change{'s' if changed != 1 else ''} "
                "you made to this document"
            )

    def forget_region_choices(self) -> None:
        """Throw away this document's corrections and analyse it afresh."""
        if self.document is None:
            return
        path = self.document.path
        self.settings.forget_regions(path)
        self.load_document(path)
        self._set_status("Reading order reset to what Mimick works out by itself")

    def _on_region_clicked(self, region) -> None:
        """Include or exclude a region the reader clicked in the plan."""
        if self.document is None:
            return
        was_playing = self.player.is_playing
        self.player.stop()
        self.document.set_region_reads(region, not region.reads)
        self.settings.remember_region(self.document.path, region.page,
                                      region.rect, region.reads)

        self._reading_selection = False
        self._active_sentences = self.document.sentences
        self.player.configure(self.document.sentences, self.engine,
                              self._current_voice(), self._current_speed())
        self.page_view.clear_highlight()
        self.page_view.viewport().update()
        self._set_status(
            f"{'Now reading' if region.reads else 'Now skipping'} that region "
            f"\u2014 {len(self.document.sentences)} sentences in total"
        )
        if was_playing:
            self.player.play(0)

    # -- where the markup bar lives ----------------------------------------

    def notes_gutter_rect(self):
        """The notes column, for the markup bar to aim a drop at."""
        return self.page_view.notes_gutter_rect()

    def _place_markup_bar(self, home: str, point: QPoint | None = None,
                          announce: bool = False) -> None:
        """Move the bar to one of its four homes and remember it was there."""
        if home == "panel" and not self.page_view.notes_visible:
            # The panel is the one home that can be taken away underneath it.
            home = "top"

        # Out of wherever it is. Taking it out of a layout means taking it out
        # by hand: a layout will not let go of a widget just because the widget
        # was re-parented.
        for box in (self.markup_slot,
                    self.markup_top.layout(), self.markup_bottom.layout()):
            box.removeWidget(self.markup_bar)
        self.markup_bar.set_home(home)

        if home == "panel":
            self.markup_bar.setParent(self.notes_header)
            self.markup_slot.addWidget(self.markup_bar)
        elif home in ("top", "bottom"):
            slot = self.markup_top if home == "top" else self.markup_bottom
            slot.layout().addWidget(self.markup_bar)
        else:
            self.markup_bar.setParent(self.page_view.viewport())
            self.markup_bar.adjustSize()
            self.markup_bar.move(self._markup_float_point(point))
            self.markup_bar.raise_()

        self.markup_top.setVisible(home == "top" and self._markup_shown)
        self.markup_bottom.setVisible(home == "bottom" and self._markup_shown)
        self.markup_bar.setVisible(self._markup_shown)
        self.page_view.refresh_panel_widgets()

        self.settings.set("markup_home", home)
        if home == "float":
            spot = self.markup_bar.pos()
            self.settings.set("markup_point", [spot.x(), spot.y()])
        for action, name in self._markup_home_actions.items():
            action.setChecked(name == home)
        if announce:
            self._set_status({
                "panel": "Highlight and Add note are in the notes panel",
                "top": "Highlight and Add note are across the top",
                "bottom": "Highlight and Add note are across the bottom",
                "float": "Highlight and Add note are loose over the page \u2014 "
                         "drag the handle to put them back",
            }[home])

    def _markup_float_point(self, point: QPoint | None) -> QPoint:
        """Keep a floating bar on screen, wherever it was left."""
        if point is None or point.isNull():
            saved = self.settings.get("markup_point") or []
            point = QPoint(*saved[:2]) if len(saved) == 2 else QPoint(24, 24)
        view = self.page_view.viewport()
        size = self.markup_bar.sizeHint()
        x = max(0, min(point.x(), max(0, view.width() - size.width())))
        y = max(0, min(point.y(), max(0, view.height() - size.height())))
        return QPoint(x, y)

    def _on_markup_moved(self, home: str, point: QPoint) -> None:
        self._place_markup_bar(home, point, announce=True)

    def _toggle_markup_bar(self, checked: bool) -> None:
        """Show or hide the Highlight and Add note buttons altogether."""
        self._markup_shown = checked
        self.settings.set("show_annotation_bar", checked)
        self._place_markup_bar(self.markup_bar.home)
        self._set_status("Highlight and Add note shown" if checked
                         else "Highlight and Add note hidden \u2014 Ctrl+H and "
                              "Ctrl+M still work")

    def _toggle_notes(self, checked: bool) -> None:
        """Show or hide the notes column beside the page."""
        self.page_view.set_notes_visible(checked)
        self.settings.set("show_notes", checked)
        # Putting the column away must not take Add note away with it -- that
        # was the old behaviour, and the reason the markup bar exists.
        if not checked and self.markup_bar.home == "panel":
            self._place_markup_bar("top")
            self._set_status("Notes panel hidden \u2014 Highlight and Add note "
                             "moved to the top")
            return
        self._set_status("Notes panel shown" if checked else "Notes panel hidden")



    def _author(self) -> str:
        """The name saved with each highlight, which other readers display."""
        stored = (self.settings.get("author") or "").strip()
        if stored:
            return stored
        import getpass

        try:
            return getpass.getuser()
        except Exception:
            return "Mimick"

    def choose_note_style(self) -> None:
        """Pick the typeface, size and author name, previewed as you go."""
        family, size = self.page_view.note_style
        dialog = NoteStyleDialog(family, size, self._author(), self)
        dialog.changed.connect(self.page_view.set_note_style)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.page_view.set_note_style(dialog.family, dialog.size)
            self.settings.set("note_font", dialog.family)
            self.settings.set("note_size", dialog.size)
            self.settings.set("author", dialog.author)
            if self.store is not None:
                self.store.author = dialog.author or self._author()
            self._set_status("Note appearance updated")
        else:
            self.page_view.set_note_style(family, size)

    def copy_selection(self) -> None:
        """Put the selected words on the clipboard, as they appear on the page.

        The words as written, not as spoken -- see Document.selection_text.

        With nothing dragged over, this copies whatever highlight or note card
        is currently picked out instead. Clicking a highlight deliberately
        clears the text selection -- otherwise clicking one would look like
        selecting its words -- so without this fallback Ctrl+C on a highlight
        did nothing at all, which is not what a reader means by pressing it.
        """
        chosen = self.page_view.selection
        if self.document is None:
            return
        if chosen is None:
            active = self.page_view.active_note
            if active is not None:
                self.copy_annotation(active)
                return
            self._set_status("Select some text first \u2014 drag across it, or press Ctrl+A")
            return
        text = self.document.selection_text(*chosen)
        if not text:
            return
        QApplication.clipboard().setText(text)
        words = chosen[1] - chosen[0] + 1
        self._set_status(f"Copied {words} word{'s' if words != 1 else ''}")

    def annotation_text(self, item, part: str = "both") -> str:
        """A highlight as text: its passage, its note, or both.

        The passage is rebuilt from the document rather than read off the
        annotation, so a word broken across a line comes back whole -- the same
        reason ``copy_selection`` goes through ``Document.selection_text``.
        """
        passage = ""
        if self.document is not None and item.first_word >= 0:
            passage = self.document.selection_text(item.first_word, item.last_word)
        passage = passage or " ".join((item.text or "").split())
        note = "\n".join(bit for bit in ((item.heading or "").strip(),
                                         (item.note or "").strip()) if bit)
        if part == "passage":
            return passage
        if part == "note":
            return note
        if passage and note:
            return f"\u201c{passage}\u201d\n\n{note}"
        return passage or note

    def copy_annotation(self, item, part: str = "both") -> None:
        """Put a highlight, its note, or both on the clipboard."""
        if item is None:
            return
        text = self.annotation_text(item, part)
        if not text:
            self._set_status("There is nothing written on that one to copy")
            return
        QApplication.clipboard().setText(text)
        self._set_status({
            "passage": "Copied the highlighted passage",
            "note": "Copied the note",
            "both": "Copied the passage and the note" if (item.note or item.heading)
                    else "Copied the highlighted passage",
        }[part])

    def _on_card_context_menu(self, item) -> None:
        """Right-click on a note card in the panel."""
        menu = self.build_annotation_menu(item)
        if menu is not None:
            menu.exec(QCursor.pos())

    def build_annotation_menu(self, item):
        """The menu for a highlight, wherever it was right-clicked.

        Shared by the page and the notes panel so the two cannot drift, and
        built separately from showing it so it can be checked without putting a
        modal menu on screen -- the same arrangement as ``build_page_menu``.
        """
        if item is None or self.store is None:
            return None
        menu = QMenu(self)
        self.add_annotation_actions(menu, item)
        return menu

    def add_annotation_actions(self, menu, item) -> None:
        """Put the things you can do to a highlight onto an existing menu.

        Takes the menu rather than returning one so the page's right-click menu
        can carry these alongside its own entries. Actions belong to the menu
        that created them, so they cannot simply be lifted from one to another.
        """
        written = bool((item.note or "").strip() or (item.heading or "").strip())

        passage = menu.addAction("Copy the highlighted passage")
        passage.triggered.connect(lambda: self.copy_annotation(item, "passage"))

        if written:
            note = menu.addAction("Copy the note")
            note.triggered.connect(lambda: self.copy_annotation(item, "note"))
            both = menu.addAction("Copy both")
            both.triggered.connect(lambda: self.copy_annotation(item, "both"))

        menu.addSeparator()
        edit = menu.addAction("Edit this note\u2026" if written else "Write a note on this\u2026")
        edit.triggered.connect(lambda: self.edit_note(item))

        read = menu.addAction("Read this passage")
        read.setEnabled(bool(self._current_voice()) and item.first_word >= 0)
        read.triggered.connect(lambda: self.read_annotation(item))

        menu.addSeparator()
        delete = menu.addAction("Delete this highlight")
        delete.triggered.connect(lambda: self.delete_annotation(item))

    def delete_annotation(self, item) -> None:
        """Remove a highlight, undoably."""
        if self.store is None or item is None:
            return
        self._remember_deletion(item)
        self.store.remove(item)
        self.page_view.set_active_note(None)
        self.page_view.refresh_annotations()
        self._refresh_filter_labels()
        self._update_enabled()
        self._set_status("Highlight deleted \u2014 Ctrl+Z puts it back")

    # -- undo --------------------------------------------------------------
    #
    # Only highlights and notes are undoable. Reading, zoom and the reading
    # order are not: nothing is lost by redoing them by hand, whereas a
    # highlight taken back by mistake is gone unless something remembers it.
    #
    # Nothing here holds on to an ``Annotation`` object. Undoing a deletion has
    # to build a new one, with a new PDF xref, so anything remembered by object
    # would be pointing at a corpse the second time round. Word indices are
    # stable for the life of a document -- they survive a rebuild, which is
    # what makes ``set_region_reads`` safe -- so they are what an edit records.

    def _live_annotation(self, span: tuple[int, int], ref: list[int] | None = None):
        """The annotation an undo step is about, whatever object it is now.

        Three ways of finding it, in descending order of certainty:

        1. **Its PDF object.** ``ref`` is a one-element list rather than a
           number because undoing a deletion builds a *new* annotation with a
           new xref, and the step has to follow it there.
        2. **Its exact word span**, preferring the newest. ``store.at_word``
           alone is not enough: it returns the first annotation merely
           *containing* a word, so highlighting a passage inside something
           already highlighted and pressing Ctrl+Z would take back the older
           highlight instead of the one just made.
        3. **Anything covering the first word**, which is what annotations made
           in another reader -- with no span recorded -- fall back to.
        """
        if self.store is None:
            return None
        if ref:
            for item in self.store.items:
                if item.xref == ref[0]:
                    return item
        exact = [item for item in self.store.items
                 if (item.first_word, item.last_word) == span]
        if exact:
            return max(exact, key=lambda item: item.xref)
        return self.store.at_word(span[0])

    def _push_undo(self, undone: str, redone: str, undo, redo) -> None:
        self._undo_stack.append((undone, redone, undo, redo))
        del self._undo_stack[:-UNDO_DEPTH]
        # A fresh edit makes the redo branch unreachable, as everywhere else.
        self._redo_stack.clear()
        self._update_enabled()

    def _clear_undo(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()

    def _remember_highlight(self, item) -> None:
        """Record a highlight's creation, so Ctrl+Z can take it back."""
        span = (item.first_word, item.last_word)
        colour, note, title = item.colour, item.note, item.title
        ref = [item.xref]

        def undo() -> None:
            live = self._live_annotation(span, ref)
            if live is not None:
                self.store.remove(live)
                self.page_view.set_active_note(None)

        def redo() -> None:
            restored = self.store.add(span[0], span[1], colour, note=note,
                                      title=title, author=self._author())
            if restored is not None:
                ref[0] = restored.xref
            self.page_view.set_active_note(restored)

        thing = "Note" if note or title else "Highlight"
        self._push_undo(f"{thing} removed", f"{thing} put back", undo, redo)

    def _remember_note_change(self, item, before: tuple, after: tuple) -> None:
        """Record an edit to a note's text, heading or colour."""
        span = (item.first_word, item.last_word)
        ref = [item.xref]

        def apply(values: tuple) -> None:
            note, title, colour = values
            live = self._live_annotation(span, ref)
            if live is None:
                return
            self.store.set_note(live, note, title)
            if not _same_colour(colour, live.colour):
                self.store.set_colour(live, colour)

        self._push_undo("Note change undone", "Note change put back",
                        lambda: apply(before), lambda: apply(after))

    def _remember_deletion(self, item) -> None:
        """Record a highlight's deletion. Call this before removing it."""
        span = (item.first_word, item.last_word)
        colour, note, title = item.colour, item.note, item.title
        thing = "Note" if note or title else "Highlight"
        ref = [item.xref]

        def undo() -> None:
            restored = self.store.add(span[0], span[1], colour, note=note,
                                      title=title, author=self._author())
            if restored is not None:
                ref[0] = restored.xref
            self.page_view.set_active_note(restored)

        def redo() -> None:
            live = self._live_annotation(span, ref)
            if live is not None:
                self.store.remove(live)
                self.page_view.set_active_note(None)

        self._push_undo(f"{thing} put back", f"{thing} deleted again", undo, redo)

    def undo_annotation(self) -> None:
        if not self._undo_stack:
            self._set_status("Nothing to undo")
            return
        entry = self._undo_stack.pop()
        entry[2]()
        self._redo_stack.append(entry)
        self._after_undo(entry[0])

    def redo_annotation(self) -> None:
        if not self._redo_stack:
            self._set_status("Nothing to put back")
            return
        entry = self._redo_stack.pop()
        entry[3]()
        self._undo_stack.append(entry)
        self._after_undo(entry[1])

    def _after_undo(self, message: str) -> None:
        """Everything an undo or a redo has to refresh, in one place.

        ``_update_enabled`` is what notices the store is dirty and starts the
        autosave, so an undo writes itself to the companion file exactly like
        any other change. It must not be skipped.
        """
        self.page_view.refresh_annotations()
        self._refresh_filter_labels()
        self._update_enabled()
        self._set_status(message)

    def highlight_selection(self, with_note: bool = False) -> None:
        """Highlight whatever is selected, optionally opening the note editor."""
        if self.document is None or self.store is None:
            return
        span = self.page_view.selection
        if span is None:
            self._set_status("Select some text first, then highlight it")
            return
        item = self.store.add(span[0], span[1], self._colour, author=self._author())
        if item is None:
            self._set_status("That selection could not be highlighted")
            return
        self.page_view.clear_selection()
        self.page_view.refresh_annotations()
        self.page_view.set_active_note(item)
        self._update_enabled()
        if with_note:
            # Highlighting and writing on it is one action to the reader, so it
            # is one Ctrl+Z: the note editor does not record its own step, and
            # what gets remembered is the finished note. If the editor was used
            # to delete the highlight again, there is nothing left to remember.
            self.edit_note(item, undoable=False)
            written = self._live_annotation((item.first_word, item.last_word), [item.xref])
            if written is not None:
                self._remember_highlight(written)
        else:
            self._remember_highlight(item)
            self._set_status(f"Highlighted \u2014 {len(self.store.items)} in this document")

    def note_selection(self) -> None:
        """Ctrl+M: highlight the selection and write a note on it at once."""
        if self.page_view.selection is None:
            # With nothing selected, edit the highlight that is currently active.
            if self.page_view.active_note is not None:
                self.edit_note(self.page_view.active_note)
            else:
                self._set_status("Select some text first, then add a note")
            return
        self.highlight_selection(with_note=True)

    def edit_note(self, item, undoable: bool = True) -> None:
        """Open the note editor on a highlight.

        ``undoable`` is False only when the caller is recording the whole
        highlight-and-write as a single step -- see ``highlight_selection``.
        """
        if self.store is None or item is None:
            return
        # Keep the originals so cancelling really does undo the live preview.
        original_note, original_colour, original_title = item.note, item.colour, item.title

        def preview(note: str, colour) -> None:
            item.note, item.colour = note, colour
            item.title = dialog.title
            self.page_view.refresh_annotations()

        dialog = NoteDialog(item, self.page_view.note_style, self)
        dialog.changed.connect(preview)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if not accepted:
            item.note, item.colour, item.title = original_note, original_colour, original_title
            self.page_view.refresh_annotations()
            return
        # Put the stored values back before writing, so the store sees a change.
        item.note, item.colour, item.title = original_note, original_colour, original_title
        if dialog.deleted:
            if undoable:
                # Recorded before the deletion, while there is still something
                # to read the words and colour off.
                self._remember_deletion(item)
            self.store.remove(item)
            self.page_view.set_active_note(None)
            self._set_status("Highlight deleted")
        else:
            before = (item.note, item.title, item.colour)
            self.store.set_note(item, dialog.note, dialog.title)
            if not _same_colour(dialog.colour, item.colour):
                self.store.set_colour(item, dialog.colour)
            if undoable and before != (item.note, item.title, item.colour):
                self._remember_note_change(
                    item, before, (item.note, item.title, item.colour))
            self._set_status("Note saved")
        self.page_view.refresh_annotations()
        self._update_enabled()

    def _on_annotation_clicked(self, item) -> None:
        # Picking out a highlight is what Ctrl+C acts on when nothing is
        # dragged over, so the action has to come back to life here.
        self._refresh_copy_action()
        preview = item.note or item.preview
        self._set_status(f"\u201c{preview[:70]}\u201d \u2014 Ctrl+C copies it, "
                         f"double-click to edit")

    def _refresh_copy_action(self) -> None:
        """Copy is live when there is a selection *or* a highlight picked out."""
        something = (self.page_view.selection is not None
                     or self.page_view.active_note is not None)
        self.act_copy.setEnabled(self.document is not None and something)

    def _step_note(self, delta: int) -> None:
        """Move between notes in document order."""
        if self.store is None or not self.store.items:
            return
        items = self.store.items
        current = self.page_view.active_note
        index = items.index(current) + delta if current in items else (0 if delta > 0 else len(items) - 1)
        index = max(0, min(index, len(items) - 1))
        self.page_view.scroll_to_annotation(items[index])
        self._on_annotation_clicked(items[index])

    def save_annotations(self, quiet: bool = False) -> bool:
        """Write highlights and notes to this document's companion file.

        The PDF you opened is never written to. Everything goes to the file
        named by ``_notes_path``: either the companion beside the original, or
        -- when the open document *is* that companion -- the open file itself,
        which ``save_as`` then writes incrementally.
        """
        if self.store is None or self.document is None or self._notes_path is None:
            return True
        if not self.store.dirty:
            if not quiet:
                self._set_status("No changes to save \u2014 everything is written")
            return True

        target, wrote = self._notes_path, None
        try:
            wrote = self.store.save_as(target)
        except Exception as first:
            # The original's folder may be read-only. Fall back to Mimick's own
            # notes folder once, and stay there for the rest of the session.
            fallback = fallback_companion_for(self.document.path, NOTES_DIR)
            if target == fallback:
                return self._autosave_gave_up(first)
            try:
                NOTES_DIR.mkdir(parents=True, exist_ok=True)
                wrote = self.store.save_as(fallback)
            except Exception as second:
                return self._autosave_gave_up(second)
            self._notes_path = target = fallback
            self._autosave_failed = False
            self._update_enabled()
            # Said instead of the usual confirmation, not before it: where the
            # notes went is the part worth reading when it is not the folder
            # the reader would look in.
            self._set_status(f"{self.document.path.name} is in a read-only folder "
                             f"\u2014 notes saved to {fallback.parent}")
            return True

        self._autosave_failed = False
        if wrote is not None:
            # Always announced, autosave included: a save you did not ask for
            # is only reassuring if you can see it happen. The clock matters
            # because the message stays up -- without it, a save from an hour
            # ago reads exactly like one from a second ago.
            when = QTime.currentTime().toString("HH:mm")
            self._set_status(f"Notes saved to {target.name} \u00b7 {when}")
        self._update_enabled()
        return True

    def _autosave_gave_up(self, exc: Exception) -> bool:
        """Report a failed save once, and stop retrying it every few seconds."""
        if not self._autosave_failed:
            self._autosave_failed = True
            self._warn(
                "Could not save your notes",
                "Mimick could not write your highlights and notes to "
                f"{self._notes_path.name if self._notes_path else 'the notes file'}.\n\n"
                "Your notes are still here in the window. Use File \u2192 Save As "
                "to put them somewhere writable.\n\n"
                f"({exc})",
            )
        return False

    def _flush_autosave(self) -> None:
        """Write anything pending right now, rather than on the timer."""
        if self._autosave.isActive():
            self._autosave.stop()
        if self.store is not None and self.store.dirty and not self._autosave_failed:
            # Only ever set, never cleared: _offer_to_save flushes before
            # closeEvent does, and a second flush with nothing left to write
            # must not undo the record that the first one saved something.
            if self.save_annotations(quiet=True):
                self._closing_save_shown = True

    def save_annotations_copy(self) -> bool:
        if self.store is None or self.document is None:
            return True
        suggested = str(self.document.path.with_name(self.document.path.stem + " (notes).pdf"))
        path, _ = QFileDialog.getSaveFileName(self, "Save a copy with notes", suggested,
                                              "PDF documents (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            wrote_copy = self.store.save_as(path)
        except Exception as exc:
            self._warn("Could not save the copy", str(exc))
            return False
        if wrote_copy:
            self._set_status(f"Saved a copy: {Path(path).name}")
        else:
            # They picked the open document itself, so it was saved in place.
            self._set_status(f"Saved into {Path(path).name}")
        self._update_enabled()
        return True

    def _offer_to_save(self) -> bool:
        """Settle any outstanding notes. False means the reader cancelled.

        There is normally nothing to ask about: notes are written to the
        companion file a moment after each change, so this just flushes what
        the debounce is still holding. The question only comes back when
        saving has actually been failing, where losing the notes is real.
        """
        if self.store is None or not self.store.dirty:
            return True
        if not self._autosave_failed:
            self._flush_autosave()
            return True
        answer = QMessageBox.question(
            self, "Your notes could not be saved",
            f"Mimick could not write your highlights and notes for "
            f"{self.document.path.name}.\n\nClosing now loses them. Choose "
            "somewhere to save them instead?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_annotations_copy()
        return True

    # -- help --------------------------------------------------------------

    def show_shortcuts(self) -> None:
        ShortcutsDialog(self).exec()

    def show_about(self) -> None:
        AboutDialog(self.windowIcon().pixmap(64, 64), self).exec()

    # -- odds and ends -----------------------------------------------------

    def _update_enabled(self) -> None:
        has_document = self.document is not None
        has_voice = bool(self._current_voice())
        for widget in (self.prev_page_button, self.next_page_button, self.page_spin):
            widget.setEnabled(has_document)
        for widget in (self.play_button, self.back_button, self.forward_button):
            widget.setEnabled(has_document and has_voice)
        self.act_export.setEnabled(has_document and has_voice)

        # Open Recent is pointless with nothing in it.
        self.recent_menu.menuAction().setEnabled(
            bool([path for path in (self.settings.get("recent") or []) if Path(path).exists()])
        )

        can_annotate = has_document and self.store is not None
        for widget in (self.highlight_button, self.colour_button, self.add_note_button):
            widget.setEnabled(can_annotate)
        for action in (self.act_highlight, self.act_note, self.act_save_copy):
            action.setEnabled(can_annotate)
        self._refresh_copy_action()
        self.act_undo.setEnabled(can_annotate and bool(self._undo_stack))
        self.act_redo.setEnabled(can_annotate and bool(self._redo_stack))

        count = len(self.store.items) if self.store else 0
        dirty = bool(self.store and self.store.dirty)
        # Every path that changes a note ends up here, so this is the one place
        # that has to notice there is something to write.
        if dirty and self._notes_path is not None and not self._autosave_failed:
            self._autosave.start()
        self.act_save.setEnabled(can_annotate and dirty)
        self.save_notes_button.setEnabled(dirty)
        for widget in (self.prev_note_button, self.next_note_button):
            widget.setEnabled(count > 0)
        self.note_count_label.setText(
            "" if not count else f"{count} note{'s' if count != 1 else ''}"
        )
        # The footer only matters once something has been marked up.
        self.page_view.set_panel_footer_visible(can_annotate and count > 0)
        self._refresh_filter_labels()
        if self.document is not None:
            marker = " \u2022" if (self.store and self.store.dirty) else ""
            self.setWindowTitle(f"{self.document.title}{marker} \u2014 Mimick")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setToolTip(text)

    def _warn(self, title: str, message: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(message)
        box.exec()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Keep a floating markup bar inside the window when it narrows.

        Nothing else moves it: it is a child of the viewport at a fixed point,
        so a window dragged smaller would otherwise leave it out of reach.
        """
        super().resizeEvent(event)
        bar = getattr(self, "markup_bar", None)
        if bar is not None and bar.home == "float":
            bar.move(self._markup_float_point(bar.pos()))
            bar.raise_()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._closing_save_shown = False
        if not self._offer_to_save():
            event.ignore()
            return
        # Anything the debounce is still holding is written before the window
        # goes, and the confirmation is left up long enough to read -- closing
        # an app that saves for you should visibly finish saving.
        self._flush_autosave()
        if self._closing_save_shown:
            QApplication.processEvents()        # paint the confirmation first
            loop = QEventLoop()
            QTimer.singleShot(CLOSING_PAUSE_MS, loop.quit)
            loop.exec()
        if self._export_worker is not None:
            self._export_worker.cancel()
        self.stop_all_audio()
        self.player.shutdown()
        # The voice list is fetched over the network on its own thread. Qt
        # aborts the process if a QThread is destroyed while still running, so
        # it is given a moment to finish -- bounded, because the request it is
        # waiting on cannot be interrupted.
        loader = self._voice_loader
        try:
            if loader is not None and loader.isRunning():
                loader.wait(3000)
        except RuntimeError:
            pass        # it finished and Qt deleted it while we were looking
        if self.document is not None:
            self.document.close()
        self.settings.save()
        super().closeEvent(event)
