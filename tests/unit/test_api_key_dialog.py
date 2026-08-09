from trinity_pilot.ui.api_key_dialog import ensure_api_key


def test_ensure_api_key_when_already_in_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-12345")
    assert ensure_api_key() is True
