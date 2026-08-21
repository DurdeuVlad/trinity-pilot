from pathlib import Path

import trinity_pilot.ui.api_key_dialog as api_key_dialog
from trinity_pilot.ui.api_key_dialog import ensure_api_key


def test_ensure_api_key_when_already_in_env(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-12345")
    assert ensure_api_key() is True


def test_frozen_runtime_uses_user_app_data_for_env(monkeypatch, tmp_path):
    monkeypatch.delenv("TRINITY_PILOT_ENV_PATH", raising=False)
    monkeypatch.setattr(api_key_dialog.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        api_key_dialog.Path,
        "home",
        classmethod(lambda cls: Path(tmp_path)),
    )

    assert api_key_dialog._env_path() == tmp_path / ".trinity-pilot" / ".env"


def test_persist_api_key_replaces_existing_value(tmp_path):
    env_path = tmp_path / ".trinity-pilot" / ".env"
    env_path.parent.mkdir()
    env_path.write_text("OTHER=value\nGEMINI_API_KEY=old-key\n", encoding="utf-8")

    api_key_dialog._persist_api_key("new-key", env_path, "GEMINI_API_KEY")

    assert env_path.read_text(encoding="utf-8") == "OTHER=value\nGEMINI_API_KEY=new-key\n"


def test_ensure_api_key_supports_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key-12345")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert api_key_dialog.ensure_api_key() is True


def test_configured_provider_reads_local_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_PROVIDER=openai\nOPENAI_MODEL=gpt-5.6-luna\n", encoding="utf-8")
    monkeypatch.setattr(api_key_dialog, "_env_path", lambda: env_path)

    assert api_key_dialog._configured_provider() == "openai"
