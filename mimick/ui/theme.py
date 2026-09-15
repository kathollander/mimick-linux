"""A dark, low-chrome look so the page itself is the brightest thing on screen."""

from __future__ import annotations

BACKDROP = "#101216"
PANEL = "#191d24"
PANEL_HI = "#222732"
BORDER = "#2b313d"
TEXT = "#e7eaf0"
TEXT_DIM = "#98a1b3"
ACCENT = "#5b9dff"
ACCENT_DEEP = "#3a7fe0"

# Drawn over the page, so these are tuned against white paper.
SENTENCE_TINT = (91, 157, 255, 48)
WORD_TINT = (255, 190, 60, 130)
SELECTION_TINT = (120, 200, 255, 70)

# The strip down the right where notes are written.
NOTE_PANEL = "#1a1d23"

STYLESHEET = f"""
QWidget {{
    background: {BACKDROP};
    color: {TEXT};
    font-size: 14px;
}}
QMainWindow, QDialog {{ background: {BACKDROP}; }}

QToolBar {{
    background: {PANEL};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px;
    spacing: 6px;
}}

QFrame#PhraseBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#PhraseRow {{ background: transparent; border: none; }}
QFrame#PhraseRow:hover {{ background: {PANEL_HI}; border-radius: 6px; }}
QPushButton#Chip {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 2px 8px;
    color: {TEXT_DIM};
    font-size: 12px;
}}
QPushButton#Chip:hover {{ border-color: {ACCENT}; color: {TEXT}; }}
QPushButton#ChipOn {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: 10px;
    padding: 2px 8px;
    color: #0b1220;
    font-size: 12px;
    font-weight: 600;
}}

QFrame#CacheRow {{
    background: {PANEL_HI};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QFrame#NotesPanel {{
    background: {NOTE_PANEL};
    border: none;
}}
QPushButton#FilterChip {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 6px;
    color: {TEXT_DIM};
    font-size: 12px;
}}
QPushButton#FilterChip:hover {{ border-color: {ACCENT}; color: {TEXT}; }}
QPushButton#FilterChip:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #0b1220;
    font-weight: 600;
}}

QFrame#NotesPanel QPushButton {{
    padding: 5px 9px;
    background: {PANEL_HI};
}}
QFrame#NotesPanel QPushButton:hover {{ background: #2b3140; }}
QFrame#NotesPanel QPushButton:disabled {{ background: #1c2029; color: #5c6577; }}

QFrame#ControlBar {{
    background: {PANEL};
    border: none;
    border-top: 1px solid {BORDER};
}}

/* The movable Highlight / Add note strip. Clipped into the notes panel it is
   part of the panel and wants no edges of its own; anywhere else it is an
   object sitting on top of something, and needs them. */
QFrame#MarkupBar {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#MarkupBar[home="panel"] {{
    background: transparent;
    border: none;
}}
QFrame#MarkupBar[home="top"], QFrame#MarkupBar[home="bottom"] {{
    border-radius: 0;
    border-left: none;
    border-right: none;
}}
QFrame#MarkupBar QLabel {{ color: {TEXT_DIM}; font-size: 15px; }}

QScrollArea {{ border: none; background: {BACKDROP}; }}

QPushButton, QToolButton {{
    background: {PANEL_HI};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover, QToolButton:hover {{ background: #2b3140; border-color: #3a4152; }}
QPushButton:pressed, QToolButton:pressed {{ background: #333b4d; }}
QPushButton:disabled, QToolButton:disabled {{ color: #5c6577; background: #1c2029; }}

QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #0b1220;
    font-weight: 600;
    padding: 8px 20px;
}}
QPushButton#Primary:hover {{ background: #6fa9ff; }}
QPushButton#Primary:pressed {{ background: {ACCENT_DEEP}; }}

QComboBox, QSpinBox, QLineEdit {{
    background: {PANEL_HI};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 18px;
    selection-background-color: {ACCENT};
}}
QComboBox:hover, QSpinBox:hover {{ border-color: #3a4152; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_HI};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: #0b1220;
    outline: none;
}}

QSlider::groove:horizontal {{
    height: 4px; background: {BORDER}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 14px; height: 14px;
    margin: -6px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}

QLabel#Dim {{ color: {TEXT_DIM}; }}
QLabel#Title {{ font-size: 15px; font-weight: 600; }}

QProgressBar {{
    background: {PANEL_HI}; border: 1px solid {BORDER};
    border-radius: 6px; height: 8px; text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #39404f; border-radius: 6px; min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: #495265; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; }}
QScrollBar::handle:horizontal {{ background: #39404f; border-radius: 6px; min-width: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QMenu {{
    background: {PANEL_HI}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 6px;
}}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT}; color: #0b1220; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QToolTip {{
    background: {PANEL_HI}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
}}
"""
