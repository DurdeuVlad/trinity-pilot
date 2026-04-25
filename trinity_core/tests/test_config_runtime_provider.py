from __future__ import annotations

import pytest

from trinity_core.config import TrinityConfig


def test_openai_provider_does_not_require_gemini_key():
    config = TrinityConfig(
        gemini_api_key="",
        openai_api_key="openai-test-key",
        ai_provider="openai",
    )
    assert config.openai_api_key == "openai-test-key"

def test_unsupported_provider_is_rejected_early():
    with pytest.raises(ValueError, match="Unsupported ai_provider 'anthropic'"):
        TrinityConfig(
            gemini_api_key="",
            openai_api_key="",
            ai_provider="anthropic",
        )
