"""Abstract base class for all LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Swappable LLM backend interface.

    All providers must implement:
    - call(): send a messages list, get back a string (JSON if json_mode=True)
    - probe(): cheap liveness check — raises on failure
    """

    @abstractmethod
    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        """Send a chat messages list and return the model's response string.

        When json_mode=True the response should be a valid JSON string.
        The caller is responsible for parsing it.
        """
        ...

    @abstractmethod
    async def probe(self) -> None:
        """Perform a cheap liveness check against the live API.

        Raises an exception with a descriptive message if the provider
        is not reachable or the credentials are invalid.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier, e.g. 'gemini' or 'openai'."""
        ...

    async def close(self) -> None:
        """Release provider resources before the worker event loop shuts down."""
        return None
