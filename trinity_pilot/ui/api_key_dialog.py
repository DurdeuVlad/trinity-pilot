"""First-run setup dialog for the selected LLM provider."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


def _env_path() -> Path:
    """Return the writable environment-file path for this runtime."""
    configured = os.environ.get("TRINITY_PILOT_ENV_PATH")
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        return Path.home() / ".trinity-pilot" / ".env"
    return Path.cwd() / ".env"


def _configured_provider() -> str:
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider:
        return provider
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    load_dotenv(dotenv_path=_env_path())
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider:
        return provider
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "gemini"


def _api_key_env_name(provider: str | None = None) -> str:
    return "OPENAI_API_KEY" if (provider or _configured_provider()) == "openai" else "GEMINI_API_KEY"


def _provider_label(provider: str | None = None) -> str:
    return "OpenAI" if (provider or _configured_provider()) == "openai" else "Gemini"


def _persist_api_key(key: str, env_path: Path, env_name: str) -> None:
    """Persist the API key while retaining unrelated environment settings."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        lines = [line for line in lines if not line.startswith(f"{env_name}=")]
    lines.append(f"{env_name}={key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ApiKeyDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._provider = _configured_provider()
        self._env_name = _api_key_env_name(self._provider)
        provider_label = _provider_label(self._provider)
        self.setWindowTitle(f"Trinity Pilot — Setup {provider_label} API Key")
        self.setFixedWidth(460)
        self.setModal(True)
        self.api_key: str = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Welcome to Trinity Pilot", self)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e88e5;")
        layout.addWidget(title)

        desc = QLabel(
            f"To orchestrate desktop automation objectives, Trinity Pilot requires an {provider_label} API key.\n"
            f"Create one in the {provider_label} developer dashboard, then paste it below.",
            self,
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.input_field = QLineEdit(self)
        self.input_field.setPlaceholderText(f"Paste your {self._env_name} here...")
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
            QMessageBox.warning(self, "Invalid Key", f"Please enter a valid {self._provider} API key.")
            return

        self.api_key = key
        os.environ[self._env_name] = key

        _persist_api_key(key, _env_path(), self._env_name)

        self.accept()


def ensure_api_key(parent=None) -> bool:
    """Check the selected provider key; prompt user via dialog if missing."""
    provider = _configured_provider()
    env_name = _api_key_env_name(provider)
    if os.environ.get(env_name):
        return True

    env_path = _env_path()
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{env_name}=") and len(line.split("=", 1)[1].strip()) > 5:
                os.environ[env_name] = line.split("=", 1)[1].strip()
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
