"""TrinityPilot entry point."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.resolve()
for _p in (".", "api-accessibility-poc", "browser-gui-automation", "cli-automation-poc"):
    _abs = str((_REPO_ROOT / _p).resolve())
    if _abs not in sys.path:
        sys.path.insert(0, _abs)

try:
    from dotenv import load_dotenv
    _env = Path(__file__).with_name(".env")
    if _env.exists():
        load_dotenv(_env, override=False)
except ImportError:
    pass

from PyQt6.QtWidgets import QApplication

from app import MainWindow
from crash_reporter import install_excepthook


def main() -> int:
    install_excepthook()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
