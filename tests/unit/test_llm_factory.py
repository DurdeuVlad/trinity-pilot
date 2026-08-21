from unittest.mock import patch


def test_create_provider_selects_openai():
    from trinity_pilot.llm.factory import create_provider

    with patch("trinity_pilot.llm.factory.OpenAIProvider") as provider_cls:
        result = create_provider(
            provider="openai",
            api_key="openai-key",
            model="gpt-5.6-luna",
            default_timeout=30,
        )

    provider_cls.assert_called_once_with(
        api_key="openai-key",
        model="gpt-5.6-luna",
        default_timeout=30,
    )
    assert result is provider_cls.return_value


def test_create_provider_selects_gemini_for_legacy_configuration():
    from trinity_pilot.llm.factory import create_provider

    with patch("trinity_pilot.llm.factory.GeminiProvider") as provider_cls:
        result = create_provider(
            provider="gemini",
            api_key="gemini-key",
            model="gemini-2.5-flash",
        )

    provider_cls.assert_called_once_with(
        api_key="gemini-key",
        model="gemini-2.5-flash",
        default_timeout=None,
    )
    assert result is provider_cls.return_value


def test_create_provider_rejects_unknown_provider():
    import pytest

    from trinity_pilot.llm.factory import create_provider

    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        create_provider(provider="unknown", api_key="key", model="model")


def test_create_provider_from_env_rejects_unknown_provider(monkeypatch):
    import pytest

    from trinity_pilot.llm.factory import create_provider_from_env

    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        create_provider_from_env()
