"""What Mimick is, what it does, and what it is built on."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
    QWidget,
)

from .. import __version__
from . import theme

TAGLINE = (
    "Linux's answer to Edge Read Aloud, and it runs on Windows too! "
    "Mimick-ing natural sounding human voices, read any pdf out loud "
    "slow or fast with no hassle."
)

FEATURES = [
    ("Read aloud in natural voices",
     "Using Microsoft's natural speech service (online) or Piper (offline), "
     "choose from over 40+ voices to be serenaded by."),
    ("Follow Along",
     "As Mimick reads, you will see the text highlighted on the page for you to "
     "follow along with."),
    ("Read at your speed",
     "Slow down the syllables or speed up reading that pesky syllabus with "
     "options from 0.75 to x3 reading speed."),
    ("Highlight and Annotate",
     "With four colours, highlight what you don't wanna forget and make notes "
     "on what piques your interest. These are saved as regular PDF annotations "
     "so other PDF readers can see them too."),
    ("Convert to Audio",
     "Turn any PDF document into an .mp3 for on the go listening. In the car, "
     "at home\u2026 just port the .mp3 to your device and playback."),
    ("Offline Voices",
     "When the internet just isn't cooperating, don't worry! Piper voices have "
     "your back."),
    ("Keeps your place",
     "When you leave a doc, returning means picking up where you left off from."),
]

BUILT_ON = [
    ("MuPDF", "rendering, text extraction and annotations", "https://mupdf.com/"),
    ("Qt (PySide6)", "the interface", "https://www.qt.io/"),
    ("edge-tts", "Microsoft's online voices", "https://github.com/rany2/edge-tts"),
    ("Piper", "offline voices", "https://github.com/OHF-Voice/piper1-gpl"),
    ("ffmpeg", "audio decoding and MP3 export", "https://ffmpeg.org/"),
]

LICENCE_BLURB = (
    "Please remix, fix, and break as you please! We're built on open source "
    "software, so we're giving it back as open source software."
)
LICENCE_NAME = "GNU Affero General Public License, version 3"
LICENCE_URL = "https://www.gnu.org/licenses/agpl-3.0.html"

class AboutDialog(QDialog):
    """A short tour of the program, its author and its licence."""

    def __init__(self, icon: QPixmap | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Mimick")
        self.setMinimumSize(560, 580)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 16)
        outer.setSpacing(14)

        # -- heading -------------------------------------------------------
        head = QHBoxLayout()
        head.setSpacing(14)
        if icon is not None and not icon.isNull():
            badge = QLabel()
            badge.setPixmap(icon.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
            head.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        title = QLabel(
            f"<div style='font-size:20px;font-weight:600'>Mimick {__version__}</div>"
            f"<div style='color:{theme.TEXT_DIM};margin-top:4px'>{TAGLINE}</div>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        head.addWidget(title, 1)
        outer.addLayout(head)

        # -- features, in a scroller so the window stays a sane size -------
        body = QLabel(self._body_html())
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        body.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(body)
        outer.addWidget(scroller, 1)

        buttons = QDialogButtonBox()
        close = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close.setObjectName("Primary")
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _body_html(self) -> str:
        rows = "".join(
            f"<p style='margin:0 0 12px 0'>"
            f"<b>{name}</b><br>"
            f"<span style='color:{theme.TEXT_DIM}'>{blurb}</span></p>"
            for name, blurb in FEATURES
        )
        built = " &middot; ".join(
            f"<a style='color:{theme.ACCENT}' href='{url}'>{name}</a> "
            f"<span style='color:{theme.TEXT_DIM}'>({what})</span>"
            for name, what, url in BUILT_ON
        )
        rule = f"<hr style='border:none;border-top:1px solid {theme.BORDER};margin:14px 0'>"
        return f"""
        <div style='font-size:13px'>
          <p style='margin:0 0 10px 0;font-weight:600'>What this does</p>
          {rows}
          {rule}
          <p style='margin:0 0 6px 0;font-weight:600'>Built on</p>
          <p style='margin:0 0 14px 0'>{built}</p>

          <p style='margin:0 0 6px 0;font-weight:600'>Written by</p>
          <p style='margin:0 0 14px 0;color:{theme.TEXT_DIM}'>Claude Code</p>

          <p style='margin:0 0 6px 0;font-weight:600'>Arranged by</p>
          <p style='margin:0 0 14px 0'>
            Kat Hollander &middot;
            <a style='color:{theme.ACCENT}' href='https://github.com/kathollander'>
              github.com/kathollander</a>
          </p>

          <p style='margin:0 0 6px 0;font-weight:600'>License</p>
          <p style='margin:0 0 6px 0;color:{theme.TEXT_DIM}'>{LICENCE_BLURB}</p>
          <p style='margin:0'>
            <a style='color:{theme.ACCENT}' href='{LICENCE_URL}'>{LICENCE_NAME}</a>
          </p>
        </div>
        """
