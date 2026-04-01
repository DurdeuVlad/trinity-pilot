"""Drop-in mock for the google.generativeai surface used in this repo."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_BACKEND_ERROR = (
    "gemini_mock: No backend configured. Call testing.gemini_mock.activate() first, "
    "or set GEMINI_MOCK=1."
)
_backend: Any = None


def configure(api_key: str | None = None, **_: Any) -> None:
    """Accept configuration without performing any external work."""


def set_backend(backend: Any) -> None:
    """Set the active backend for the mock module."""
    global _backend
    _backend = backend


def get_backend() -> Any:
    """Return the active backend or raise an actionable error."""
    if _backend is None:
        raise RuntimeError(_DEFAULT_BACKEND_ERROR)
    return _backend


@dataclass(slots=True)
class GenerationConfig:
    """Subset of generation config fields used by app code."""

    response_mime_type: str | None = None
    response_schema: Any = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None


@dataclass(slots=True)
class UsageMetadata:
    """Token usage metadata returned on mock responses."""

    prompt_token_count: int
    candidates_token_count: int
    total_token_count: int


@dataclass(slots=True)
class MockPart:
    """Response content part containing generated text."""

    text: str


@dataclass(slots=True)
class MockContent:
    """Response content wrapper."""

    parts: list[MockPart]


@dataclass(slots=True)
class MockCandidate:
    """Candidate wrapper matching the SDK shape."""

    content: MockContent


@dataclass(slots=True)
class MockFile:
    """File reference returned by upload_file()."""

    path: str
    name: str = field(init=False)
    uri: str = field(init=False)

    def __post_init__(self) -> None:
        filename = Path(self.path).name or "mock-file"
        self.name = filename
        self.uri = f"mock://{filename}"


class MockResponse:
    """Mock Gemini response with text, usage metadata, and candidates."""

    def __init__(self, text: str, prompt: Any = "") -> None:
        prompt_text = _flatten_prompt(prompt)
        prompt_tokens = max(1, len(prompt_text) // 4) if prompt_text else 1
        output_tokens = max(1, len(text) // 4) if text else 1
        self._text = text
        self.usage_metadata = UsageMetadata(
            prompt_token_count=prompt_tokens,
            candidates_token_count=output_tokens,
            total_token_count=prompt_tokens + output_tokens,
        )
        self.candidates = [MockCandidate(content=MockContent(parts=[MockPart(text=text)]))]

    @property
    def text(self) -> str:
        """Return the response text."""
        return self._text


def upload_file(path: str, **_: Any) -> MockFile:
    """Return a lightweight mock file reference."""
    return MockFile(path=path)


def _flatten_prompt(prompt: Any) -> str:
    """Convert prompt inputs into a stable text preview."""
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, (list, tuple)):
        return " ".join(_flatten_prompt(item) for item in prompt)
    text = getattr(prompt, "text", None)
    if isinstance(text, str):
        return text
    return "[media_content]"


def _coerce_generation_config(
    generation_config: GenerationConfig | dict[str, Any] | None,
) -> GenerationConfig:
    """Normalize config inputs to a GenerationConfig instance."""
    if generation_config is None:
        return GenerationConfig()
    if isinstance(generation_config, GenerationConfig):
        return generation_config
    allowed = GenerationConfig.__dataclass_fields__.keys()
    filtered = {key: value for key, value in generation_config.items() if key in allowed}
    return GenerationConfig(**filtered)


class GenerativeModel:
    """Mock GenerativeModel that delegates responses to the active backend."""

    def __init__(
        self,
        model_name: str,
        generation_config: GenerationConfig | dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        self.model_name = model_name
        self._generation_config = _coerce_generation_config(generation_config)

    def generate_content(
        self,
        prompt: Any,
        generation_config: GenerationConfig | dict[str, Any] | None = None,
        **_: Any,
    ) -> MockResponse:
        """Generate a synchronous mock response."""
        config = _coerce_generation_config(generation_config) if generation_config else self._generation_config
        text = get_backend().respond(prompt=prompt, model_name=self.model_name, generation_config=config)
        return MockResponse(text=text, prompt=prompt)

    async def generate_content_async(
        self,
        prompt: Any,
        generation_config: GenerationConfig | dict[str, Any] | None = None,
        **_: Any,
    ) -> MockResponse:
        """Generate an asynchronous mock response."""
        config = _coerce_generation_config(generation_config) if generation_config else self._generation_config
        backend = get_backend()
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            None,
            lambda: backend.respond(prompt=prompt, model_name=self.model_name, generation_config=config),
        )
        return MockResponse(text=text, prompt=prompt)


class _MockModels:
    """Stub for google.genai Client().models — new SDK surface."""

    def generate_content(
        self,
        *,
        model: str = "mock-model",
        contents: Any = "",
        config: Any = None,
        **_: Any,
    ) -> MockResponse:
        """Generate a synchronous mock response via the new SDK surface."""
        gen_config = _coerce_generation_config(config) if config else GenerationConfig()
        text = get_backend().respond(prompt=contents, model_name=model, generation_config=gen_config)
        return MockResponse(text=text, prompt=contents)

    async def generate_content_async(
        self,
        *,
        model: str = "mock-model",
        contents: Any = "",
        config: Any = None,
        **_: Any,
    ) -> MockResponse:
        """Generate an async mock response via the new SDK surface."""
        gen_config = _coerce_generation_config(config) if config else GenerationConfig()
        backend = get_backend()
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            None,
            lambda: backend.respond(prompt=contents, model_name=model, generation_config=gen_config),
        )
        return MockResponse(text=text, prompt=contents)


class Client:
    """Mock for google.genai.Client — new google-genai SDK entry point."""

    def __init__(self, api_key: str | None = None, **_: Any) -> None:
        self.models = _MockModels()
        self.aio = _AsyncClient()


class _AsyncModels:
    """Async version of _MockModels — generate_content is a coroutine."""

    async def generate_content(
        self,
        *,
        model: str = "mock-model",
        contents: Any = "",
        config: Any = None,
        **_: Any,
    ) -> "MockResponse":
        gen_config = _coerce_generation_config(config) if config else GenerationConfig()
        backend = get_backend()
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            None,
            lambda: backend.respond(prompt=contents, model_name=model, generation_config=gen_config),
        )
        return MockResponse(text=text, prompt=contents)


class _AsyncClient:
    """Async sub-namespace on Client (client.aio.models.generate_content)."""

    def __init__(self) -> None:
        self.models = _AsyncModels()


# ── types stub ────────────────────────────────────────────────────────────────

class _TypesModule:
    """Minimal google.genai.types / google.generativeai.types surface."""

    @dataclass
    class Content:
        role: str
        parts: list

    @dataclass
    class Part:
        text: str

    @dataclass
    class GenerateContentConfig:
        system_instruction: str | None = None
        temperature: float | None = None
        response_mime_type: str | None = None
        max_output_tokens: int | None = None


types = _TypesModule()
