"""Tests for settings view persistence wiring."""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QLabel

from ui import theme as ui_theme
from ui.views.settings_view import SettingsView


def test_settings_view_save_and_reload(tmp_path):
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    view.settings_manager = view.settings_manager.__class__(str(tmp_path / "settings.json"))
    view.api_key_input.setText("saved-key")
    view.default_timeout.setValue(99)
    view.max_retries.setValue(4)
    view.default_domain.setCurrentText("CLI")
    view.openai_api_key_input.setText("openai-key")
    view.ai_provider.setCurrentText("OpenAI")
    view.save_settings()

    view.load_settings()
    assert view.api_key_input.text() == "saved-key"
    assert view.default_timeout.value() == 99
    assert view.max_retries.value() == 4
    assert view.default_domain.currentText() == "CLI"
    assert view.openai_api_key_input.text() == "openai-key"
    assert view.ai_provider.currentText() == "OpenAI"


def test_settings_view_exposes_stable_object_names() -> None:
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    assert view.api_key_input.objectName() == "SettingsApiKey"
    assert view.default_timeout.objectName() == "SettingsDefaultTimeout"
    assert view.max_retries.objectName() == "SettingsMaxRetries"
    assert view.default_domain.objectName() == "SettingsDefaultDomain"
    assert view.ai_provider.objectName() == "SettingsAIProvider"
    assert view.openai_api_key_input.objectName() == "SettingsOpenAIApiKey"
    assert view.save_btn.objectName() == "SettingsSaveButton"


def test_settings_view_shows_runtime_config_note() -> None:
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    note = view.findChild(QLabel, "SettingsRuntimeConfigNote")
    assert note is not None
    assert ".env" in note.text()


def test_settings_view_applies_dark_theme() -> None:
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    assert ui_theme.BG in view.styleSheet()
    assert "QComboBox" in view.styleSheet()
    view.close()


def test_settings_view_emits_merged_settings_on_save(tmp_path) -> None:
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    view.settings_manager = view.settings_manager.__class__(str(tmp_path / "settings.json"))
    emitted: list[dict] = []
    view.settings_saved.connect(lambda payload: emitted.append(payload))

    view.api_key_input.setText("signal-key")
    view.default_domain.setCurrentText("CLI")
    view.save_settings()

    assert emitted
    assert emitted[-1]["gemini_api_key"] == "signal-key"
    assert emitted[-1]["default_domain"] == "CLI"
    # frame_rate_limit and max_frame_count remain in DEFAULTS and are preserved
    assert emitted[-1]["max_frame_count"] == 100


def test_api_key(tmp_path) -> None:
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    view.settings_manager = view.settings_manager.__class__(str(tmp_path / "settings.json"))
    view.api_key_input.setText("api-key")
    view.save_settings()

    assert view.settings_manager.load()["gemini_api_key"] == "api-key"


def test_timeout(tmp_path) -> None:
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    view.settings_manager = view.settings_manager.__class__(str(tmp_path / "settings.json"))
    view.default_timeout.setValue(321)
    view.save_settings()

    assert view.settings_manager.load()["default_timeout_seconds"] == 321


def test_retry(tmp_path) -> None:
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    view.settings_manager = view.settings_manager.__class__(str(tmp_path / "settings.json"))
    view.max_retries.setValue(6)
    view.save_settings()

    assert view.settings_manager.load()["max_retries"] == 6


def test_domain_default(tmp_path) -> None:
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    view.settings_manager = view.settings_manager.__class__(str(tmp_path / "settings.json"))
    view.default_domain.setCurrentText("Desktop")
    view.save_settings()

    assert view.settings_manager.load()["default_domain"] == "Desktop"


def test_provider_and_openai_key(tmp_path) -> None:
    _ = QApplication.instance() or QApplication([])
    view = SettingsView()
    view.settings_manager = view.settings_manager.__class__(str(tmp_path / "settings.json"))
    view.ai_provider.setCurrentText("OpenAI")
    view.openai_api_key_input.setText("sk-test")
    view.save_settings()

    data = view.settings_manager.load()
    assert data["ai_provider"] == "openai"
    assert data["openai_api_key"] == "sk-test"
