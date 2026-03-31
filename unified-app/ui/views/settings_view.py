"""Settings view and editor UI."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from orchestrator.settings_manager import SettingsManager
from ui import theme as ui_theme


class SettingsView(QWidget):
    """Render and persist app settings."""

    settings_saved = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.settings_manager = SettingsManager()
        self._setup_ui()
        self.load_settings()

    def _setup_ui(self) -> None:
        self.setObjectName("SettingsViewRoot")
        self.setStyleSheet(ui_theme.dark_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        title = QLabel("Settings")
        title.setStyleSheet(ui_theme.title_style(15))
        layout.addWidget(title)

        note = QLabel("API credentials are loaded from the shell environment or unified-app/.env.")
        note.setWordWrap(True)
        note.setObjectName("SettingsRuntimeConfigNote")
        note.setStyleSheet(ui_theme.muted_style())
        layout.addWidget(note)

        form = QFormLayout()
        form.setSpacing(10)

        self.ai_provider = QComboBox()
        self.ai_provider.setObjectName("SettingsAIProvider")
        self.ai_provider.addItems(["Gemini", "OpenAI"])
        form.addRow("AI Provider", self.ai_provider)

        self.api_key_input = QLineEdit()
        self.api_key_input.setObjectName("SettingsApiKey")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Gemini API key (or set GEMINI_API_KEY env var)")
        form.addRow("Gemini API Key", self.api_key_input)

        self.openai_api_key_input = QLineEdit()
        self.openai_api_key_input.setObjectName("SettingsOpenAIApiKey")
        self.openai_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_api_key_input.setPlaceholderText("OpenAI API key (or set OPENAI_API_KEY env var)")
        form.addRow("OpenAI API Key", self.openai_api_key_input)

        self.default_timeout = QSpinBox()
        self.default_timeout.setObjectName("SettingsDefaultTimeout")
        self.default_timeout.setRange(5, 1200)
        form.addRow("Default Timeout (s)", self.default_timeout)

        self.max_retries = QSpinBox()
        self.max_retries.setObjectName("SettingsMaxRetries")
        self.max_retries.setRange(0, 10)
        form.addRow("Max Retries", self.max_retries)

        self.default_domain = QComboBox()
        self.default_domain.setObjectName("SettingsDefaultDomain")
        self.default_domain.addItems(["Auto-detect", "Web", "Desktop", "CLI", "Mixed"])
        form.addRow("Default Domain", self.default_domain)

        layout.addLayout(form)

        actions = QHBoxLayout()
        actions.addStretch()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setObjectName("SettingsSaveButton")
        self.save_btn.clicked.connect(self.save_settings)
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)

    def load_settings(self) -> None:
        """Load from settings manager and populate fields."""
        data = self.settings_manager.load()
        provider = str(data.get("ai_provider", "gemini")).capitalize()
        index = self.ai_provider.findText(provider)
        if index >= 0:
            self.ai_provider.setCurrentIndex(index)
        self.api_key_input.setText(data["gemini_api_key"])
        self.openai_api_key_input.setText(data.get("openai_api_key", ""))
        self.default_timeout.setValue(int(data["default_timeout_seconds"]))
        self.max_retries.setValue(int(data["max_retries"]))
        self.default_domain.setCurrentText(data["default_domain"])

    def save_settings(self) -> None:
        """Persist values through settings manager."""
        payload = {
            "ai_provider": self.ai_provider.currentText().lower(),
            "gemini_api_key": self.api_key_input.text().strip(),
            "openai_api_key": self.openai_api_key_input.text().strip(),
            "default_timeout_seconds": self.default_timeout.value(),
            "max_retries": self.max_retries.value(),
            "default_domain": self.default_domain.currentText(),
        }
        merged = self.settings_manager.save(payload)
        self.settings_saved.emit(merged)
