"""Showing a finished file in the file manager."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .system import IS_MACOS, IS_WINDOWS, no_window_kwargs


def open_with_default(path: Path) -> bool:
    """Hand a path to whatever the desktop uses for it."""
    if IS_WINDOWS:
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows only
            return True
        except OSError:
            return False
    opener = "open" if IS_MACOS else "xdg-open"
    if not shutil.which(opener):
        return False
    try:
        subprocess.Popen([opener, str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def reveal(path: Path) -> bool:
    """Show a file in the file manager, selected where that is supported."""
    if IS_WINDOWS:
        try:
            # Explorer wants a single argument with no space after the comma,
            # and returns non-zero even when it works, so its exit code is not
            # worth checking.
            subprocess.Popen(f'explorer /select,"{path}"', **no_window_kwargs())
            return True
        except (OSError, subprocess.SubprocessError):
            return open_with_default(path.parent)
    if IS_MACOS and shutil.which("open"):
        try:
            subprocess.Popen(["open", "-R", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            pass
    if shutil.which("gdbus"):
        try:
            subprocess.Popen(
                ["gdbus", "call", "--session",
                 "--dest", "org.freedesktop.FileManager1",
                 "--object-path", "/org/freedesktop/FileManager1",
                 "--method", "org.freedesktop.FileManager1.ShowItems",
                 f"['file://{path}']", ""],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            pass
    return open_with_default(path.parent)
