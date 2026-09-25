"""The handful of places Mimick has to know which operating system it is on.

Everything platform-specific lives here so the rest of the codebase can stay
unaware of it. Three things differ between Linux and Windows:

*Where settings and downloads belong.* ``config`` asks this module, because
``~/.config`` is a Linux convention and littering a Windows home folder with
dotfolders is rude.

*Where ffmpeg is.* On Linux it is a package and always on ``PATH``. On Windows
there is no system copy, so ``install.ps1`` puts a static build in the cache
folder and :func:`ffmpeg_command` looks there as well as on ``PATH``.

*Whether a subprocess flashes a console window.* Windows opens one for every
child process of a windowed app. ``decode_audio`` runs once per **sentence**
during playback, so without :func:`no_window_kwargs` a black box blinks on
screen every few seconds while Mimick reads.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"


# -- where our folders go ----------------------------------------------------

def default_config_dir() -> Path:
    """Where settings belong when the environment does not say otherwise."""
    if IS_WINDOWS:
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "Mimick"
        return Path.home() / "AppData" / "Roaming" / "Mimick"
    return Path.home() / ".config" / "mimick"


def default_cache_dir() -> Path:
    """Where downloaded voices and previews belong.

    Kept out of the roaming profile on Windows: voices are ~60 MB each and
    Kokoro is far larger, which is not something to copy between machines at
    every login.
    """
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Mimick" / "Cache"
        return Path.home() / "AppData" / "Local" / "Mimick" / "Cache"
    return Path.home() / ".cache" / "mimick"


# -- running things without a console window ---------------------------------

def no_window_kwargs() -> dict:
    """Extra ``subprocess`` arguments that keep a child process off screen.

    Empty everywhere but Windows, so it is safe to splat into every call.
    """
    if not IS_WINDOWS:
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    # Both: STARTUPINFO covers a console app launched from a console, the
    # creation flag covers one launched from a windowed process.
    return {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}


# -- finding ffmpeg ----------------------------------------------------------

def bundled_ffmpeg() -> Path | None:
    """The copy ``install.ps1`` downloads, if it is there."""
    # Imported here rather than at module scope: config asks *us* for its
    # directories, so importing it at the top would be a cycle.
    from .config import CACHE_DIR

    candidate = CACHE_DIR / "ffmpeg" / ("ffmpeg.exe" if IS_WINDOWS else "ffmpeg")
    return candidate if candidate.exists() else None


def ffmpeg_command() -> str | None:
    """The ffmpeg to run, or ``None`` if there isn't one.

    ``PATH`` wins: someone who installed ffmpeg themselves should get theirs.
    """
    found = shutil.which("ffmpeg")
    if found:
        return found
    bundled = bundled_ffmpeg()
    return str(bundled) if bundled else None


def ffmpeg_missing_message(purpose: str) -> str:
    """What to tell the reader when ffmpeg is not installed.

    ``purpose`` completes the sentence "ffmpeg is needed to ...".
    """
    if IS_WINDOWS:
        how = ("Run  install.ps1  again and it will download a copy, or "
               "install it yourself with:\n\n    winget install Gyan.FFmpeg")
    elif IS_MACOS:
        how = "Install it with:\n\n    brew install ffmpeg"
    else:
        how = "Install it with:\n\n    sudo apt install ffmpeg"
    return f"ffmpeg is needed to {purpose}.\n\n{how}"
