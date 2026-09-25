"""Entry point: ``python -m mimick [file.pdf]``."""

from __future__ import annotations

import sys
from pathlib import Path


def _missing_dependencies() -> list[str]:
    required = {
        "PySide6": "PySide6",
        "pymupdf": "PyMuPDF",
        "edge_tts": "edge-tts",
        "sounddevice": "sounddevice",
        "numpy": "numpy",
    }
    import importlib.util

    return [name for module, name in required.items() if importlib.util.find_spec(module) is None]


def main() -> int:
    missing = _missing_dependencies()
    if missing:
        print(
            "Mimick is missing some parts it needs to run:\n"
            + "\n".join(f"  • {name}" for name in missing)
            + "\n\nRun the installer again:  ./install.sh\n",
            file=sys.stderr,
        )
        return 1

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .config import Settings
    from .ui import theme
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Mimick")
    app.setApplicationDisplayName("Mimick")
    app.setDesktopFileName("mimick")
    app.setStyleSheet(theme.STYLESHEET)

    icon_path = Path(__file__).resolve().parent.parent / "assets" / "mimick.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    settings = Settings()
    window = MainWindow(settings)
    window.show()

    for argument in sys.argv[1:]:
        candidate = Path(argument).expanduser()
        if candidate.suffix.lower() == ".pdf" and candidate.exists():
            window.load_document(candidate)
            break

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
