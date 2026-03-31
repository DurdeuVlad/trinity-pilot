"""Test-only LLM provider that routes through google.generativeai (mock-intercepted)."""
from __future__ import annotations

from .base import LLMProvider


class MockProvider(LLMProvider):
    """Routes AI calls through google.generativeai so the QueueBackend mock intercepts them.

    Used automatically by make_provider() when api_key == "mock".
    Do NOT use in production.
    """

    def __init__(self) -> None:
        """Ensure the Gemini mock backend is active before any SDK import occurs."""
        from testing.gemini_mock.activator import activate

        activate()

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        """Forward to the mock GenerativeModel and return response text."""
        import google.generativeai as genai

        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        turns = [m["content"] for m in messages if m["role"] in ("user", "assistant")]
        prompt = (f"{system}\n" if system else "") + "\n".join(turns)

        config = genai.GenerationConfig(
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        model = genai.GenerativeModel("gemini-2.0-flash", generation_config=config)
        response = await model.generate_content_async(prompt)
        return response.text

    async def probe(self) -> None:
        """No-op — mock is always reachable."""
