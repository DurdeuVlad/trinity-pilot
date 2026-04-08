"""Abstract base class for all LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
import importlib
import time
from typing import Any


class LLMProvider(ABC):
    """Swappable LLM backend interface.

    All providers must implement:
    - call(): send a messages list, get back a string (JSON if json_mode=True)
    - probe(): cheap liveness check — raises on failure
    """

    @abstractmethod
    async def call(
        self,
        messages: list[dict],
        *,
        json_mode: bool = True,
        purpose: str | None = None,
    ) -> str:
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

    def _log_prompt_event(
        self,
        *,
        messages: list[dict],
        model: str,
        temperature: float | None,
        purpose: str | None,
        json_mode: bool,
        call_id: str | None = None,
    ) -> str | None:
        prompt_logger = self._prompt_logger_module()
        if prompt_logger is None:
            return call_id
        try:
            log_fn = (
                getattr(prompt_logger, "log_prompt", None)
                or getattr(prompt_logger, "record_prompt", None)
                or getattr(prompt_logger, "emit_prompt", None)
            )
            if not callable(log_fn):
                return call_id
            prompt_text = self._messages_to_prompt(messages)
            resolved_call_id = call_id or self._new_call_id(purpose)
            log_fn(
                prompt=prompt_text,
                system_instructions=self._system_instruction(messages),
                purpose=purpose or self._infer_purpose(messages),
                model=model,
                temperature=temperature,
                provider=self.provider_name,
                call_id=resolved_call_id,
                prompt_preview=prompt_text[:500],
                prompt_length=len(prompt_text),
                context_tokens_estimate=self._estimate_tokens(prompt_logger, prompt_text),
                metadata={"json_mode": json_mode},
            )
            return resolved_call_id
        except Exception:
            return call_id

    def _log_response_event(
        self,
        *,
        response_obj: Any,
        response_text: str,
        model: str,
        purpose: str | None,
        latency_ms: dict[str, int] | None = None,
        call_id: str | None = None,
    ) -> None:
        prompt_logger = self._prompt_logger_module()
        if prompt_logger is None:
            return
        try:
            log_fn = (
                getattr(prompt_logger, "log_response", None)
                or getattr(prompt_logger, "record_response", None)
                or getattr(prompt_logger, "emit_response", None)
            )
            if not callable(log_fn):
                return
            finish_reason = self._extract_finish_reason(response_obj)
            tokens = self._extract_tokens(response_obj)
            log_fn(
                response=response_text,
                raw_response=response_obj,
                response_obj=response_obj,
                purpose=purpose,
                model=model,
                provider=self.provider_name,
                call_id=call_id,
                response_preview=response_text[:500],
                response_length=len(response_text or ""),
                finish_reason=finish_reason,
                tokens=tokens,
                latency_ms=latency_ms or {},
            )
        except Exception:
            return

    def _messages_to_prompt(self, messages: list[dict]) -> str:
        lines: list[str] = []
        for message in messages:
            role = str(message.get("role", "user")).upper()
            content = str(message.get("content", ""))
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def _system_instruction(self, messages: list[dict]) -> str:
        for message in messages:
            if message.get("role") == "system":
                return str(message.get("content", ""))
        return ""

    def _infer_purpose(self, messages: list[dict]) -> str:
        system_text = self._system_instruction(messages).lower()
        if "reflect" in system_text or "critique" in system_text:
            return "reflection"
        if "clarif" in system_text:
            return "clarification"
        if "decompose" in system_text or "plan" in system_text:
            return "planning"
        return "execution"

    def _prompt_logger_module(self) -> Any | None:
        try:
            return importlib.import_module("audit_debugger.prompt_logger")
        except ImportError:
            return None

    def _estimate_tokens(self, prompt_logger: Any, text: str) -> int:
        estimate_fn = getattr(prompt_logger, "estimate_tokens", None)
        if callable(estimate_fn):
            try:
                return int(estimate_fn(text=text))
            except Exception:
                pass
        return max(1, len(text) // 4) if text else 0

    def _extract_tokens(self, response_obj: Any) -> dict[str, int]:
        usage = getattr(response_obj, "usage_metadata", None)
        if usage is not None:
            prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
            completion = int(getattr(usage, "candidates_token_count", 0) or 0)
            total = int(getattr(usage, "total_token_count", prompt + completion) or 0)
            return {"prompt": prompt, "completion": completion, "total": total}

        usage = getattr(response_obj, "usage", None)
        if usage is not None:
            prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion = int(getattr(usage, "completion_tokens", 0) or 0)
            total = int(getattr(usage, "total_tokens", prompt + completion) or 0)
            return {"prompt": prompt, "completion": completion, "total": total}

        return {"prompt": 0, "completion": 0, "total": 0}

    def _extract_finish_reason(self, response_obj: Any) -> str | None:
        value = getattr(response_obj, "finish_reason", None)
        if value is not None:
            return str(value)
        candidates = getattr(response_obj, "candidates", None)
        if isinstance(candidates, list) and candidates:
            candidate = candidates[0]
            reason = getattr(candidate, "finish_reason", None)
            if reason is not None:
                return str(reason)
        return None

    def _new_call_id(self, purpose: str | None) -> str:
        slug = (purpose or "call").strip().lower().replace(" ", "_")
        return f"{self.provider_name}-{slug}-{time.time_ns()}"
