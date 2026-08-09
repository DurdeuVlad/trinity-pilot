"""First-run setup dialog for missing GEMINI_API_KEY."""
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class ApiKeyDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trinity Pilot — Setup API Key")
        self.setFixedWidth(460)
        self.setModal(True)
        self.api_key: str = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Welcome to Trinity Pilot", self)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e88e5;")
        layout.addWidget(title)

        desc = QLabel(
            "To orchestrate desktop automation objectives, Trinity Pilot requires a Gemini API key.\n"
            "You can get a free key from Google AI Studio (aistudio.google.com).",
            self,
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.input_field = QLineEdit(self)
        self.input_field.setPlaceholderText("Paste your GEMINI_API_KEY here...")
        self.input_field.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.input_field)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("Save & Start", self)
        save_btn.setStyleSheet(
            "background-color: #1e88e5; color: white; padding: 6px 16px; border-radius: 4px; font-weight: bold;"
        )
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _on_save(self) -> None:
        key = self.input_field.text().strip()
        if not key:
            QMessageBox.warning(self, "Invalid Key", "Please enter a valid Gemini API key.")
            return

        self.api_key = key
        os.environ["GEMINI_API_KEY"] = key

        # Persist to local .env if possible
        env_path = Path(".env")
        lines = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
            lines = [line for line in lines if not line.startswith("GEMINI_API_KEY=")]
        lines.append(f"GEMINI_API_KEY={key}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.accept()


def ensure_api_key(parent=None) -> bool:
    """Check if GEMINI_API_KEY is present; prompt user via dialog if missing."""
    if os.environ.get("GEMINI_API_KEY"):
        return True

    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY=") and len(line.split("=", 1)[1].strip()) > 5:
                os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip()
                return True

    import sys

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    _created_app = False
    if app is None:
        app = QApplication(sys.argv)
        _created_app = True

    dialog = ApiKeyDialog(parent)
    res = dialog.exec() == QDialog.DialogCode.Accepted
    return res
