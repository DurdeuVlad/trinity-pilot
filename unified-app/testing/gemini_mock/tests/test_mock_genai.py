from __future__ import annotations

import asyncio

from testing.gemini_mock.mock_genai import (
    GenerationConfig,
    GenerativeModel,
    MockFile,
    set_backend,
    upload_file,
)


class _StubBackend:
    """Backend stub that records calls and returns queued text."""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: list[dict[str, object]] = []

    def respond(
        self,
        prompt: object,
        model_name: str,
        generation_config: GenerationConfig,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "mime_type": generation_config.response_mime_type,
            }
        )
        return self.response_text


def teardown_function() -> None:
    """Reset the module backend between tests."""
    set_backend(None)


def test_generate_content_returns_mock_response() -> None:
    backend = _StubBackend('{"steps":["one"],"estimated_duration":10,"confidence":0.9}')
    set_backend(backend)

    model = GenerativeModel(
        "gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"},
    )
    response = model.generate_content("Plan one task")

    assert response.text == '{"steps":["one"],"estimated_duration":10,"confidence":0.9}'
    assert response.usage_metadata.prompt_token_count > 0
    assert response.candidates[0].content.parts[0].text == response.text
    assert backend.calls[0]["model_name"] == "gemini-2.5-flash"
    assert backend.calls[0]["mime_type"] == "application/json"


def test_generate_content_async_uses_backend() -> None:
    backend = _StubBackend('{"steps":["async"],"estimated_duration":5,"confidence":0.7}')
    set_backend(backend)

    async def run() -> str:
        model = GenerativeModel("gemini-2.5-flash")
        response = await model.generate_content_async("Async prompt")
        return response.text

    assert asyncio.run(run()) == '{"steps":["async"],"estimated_duration":5,"confidence":0.7}'
    assert backend.calls[0]["prompt"] == "Async prompt"


def test_upload_file_returns_mock_file() -> None:
    file_ref = upload_file("C:/temp/image.png")

    assert isinstance(file_ref, MockFile)
    assert file_ref.name == "image.png"
    assert file_ref.uri == "mock://image.png"

