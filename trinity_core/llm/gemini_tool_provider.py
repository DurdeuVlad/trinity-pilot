"""Gemini tool-calling provider for Trinity Core MCP runtime."""

from __future__ import annotations

import json
import logging
from typing import Any

from .llm_provider import LLMProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class GeminiToolCallingProvider(LLMProvider):
    """Gemini-based tool-calling provider using google-genai SDK."""

    def __init__(self, api_key: str, model: str = "models/gemini-3.1-flash-lite-preview"):
        """Initialize Gemini provider.
        
        Args:
            api_key: Gemini API key
            model: Model name (default: models/gemini-3.1-flash-lite-preview)
        """
        try:
            from google import genai
            from google.genai import types as genai_types
        except (ImportError, AttributeError):
            try:
                import google.generativeai as genai
                from google.generativeai import types as genai_types
            except ImportError as exc:
                raise ImportError(
                    "google-genai is required for GeminiToolCallingProvider. "
                    "Install it with: pip install google-genai"
                ) from exc

        self._genai = genai
        self._types = genai_types
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.api_key = api_key

    async def call(self, messages: list[dict], tools: dict[str, Any]) -> LLMResponse:
        """Generate response with tool calling support.
        
        Args:
            messages: OpenAI-style message list
            tools: Dict of tool name -> tool object
            
        Returns:
            LLMResponse with text and/or tool calls
        """
        temperature = 0.2
        # Convert messages to Gemini format
        system_instruction = next(
            (m["content"] for m in messages if m["role"] == "system"), None
        )
        
        contents = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "user" if m["role"] == "user" else "model"
            
            # Handle tool responses
            if m["role"] == "tool":
                # Tool responses go as user messages with special formatting
                contents.append(
                    self._types.Content(
                        role="user",
                        parts=[self._types.Part(
                            text=f"Tool {m.get('name', 'unknown')} returned: {m['content']}"
                        )],
                    )
                )
            else:
                contents.append(
                    self._types.Content(
                        role=role,
                        parts=[self._types.Part(text=m["content"])],
                    )
                )

        # Convert tools dict to Gemini function declarations
        gemini_tools = None
        if tools:
            function_declarations = []
            for tool_name, tool_obj in tools.items():
                # Get tool description and parameters from tool object
                description = str(tool_obj.description() or "") if hasattr(tool_obj, 'description') else ""
                parameters = tool_obj.parameters() if hasattr(tool_obj, 'parameters') else {}
                
                function_declarations.append(
                    self._types.FunctionDeclaration(
                        name=tool_name,
                        description=description,
                        parameters=parameters,
                    )
                )
            
            if function_declarations:
                gemini_tools = [self._types.Tool(function_declarations=function_declarations)]

        # Generate content
        config = self._types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            tools=gemini_tools,
        )

        # ── Prompt observability (fail-safe) ─────────────────────────────────
        import importlib as _il, time as _time
        _pl = None
        try:
            _pl = _il.import_module("audit_debugger.prompt_logger")
        except ImportError:
            pass
        _call_id: str | None = None
        _t0 = _time.perf_counter()
        if _pl is not None:
            try:
                _prompt_text = "\n\n".join(
                    f"{m['role'].upper()}: {m.get('content', '')}"
                    for m in messages
                    if m["role"] in ("system", "user", "assistant")
                )
                _call_id = _pl.log_prompt(
                    prompt=_prompt_text,
                    system_instructions=system_instruction or "",
                    purpose="execution",
                    model=self.model,
                    temperature=temperature,
                    provider=self.provider_name,
                    prompt_preview=_prompt_text[:500],
                    prompt_length=len(_prompt_text),
                    context_tokens_estimate=max(1, len(_prompt_text) // 4),
                )
            except Exception:
                pass

        try:
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )

            # Parse response
            text_content = ""
            tool_calls = []

            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                
                for part in candidate.content.parts:
                    # Text content
                    if hasattr(part, "text") and part.text:
                        text_content += part.text
                    
                    # Function calls
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        tool_calls.append(
                            ToolCall(
                                id=f"call_{fc.name}_{len(tool_calls)}",
                                name=fc.name,
                                arguments=dict(fc.args) if fc.args else {},
                            )
                        )
            
            if _pl is not None:
                try:
                    _pl.log_response(
                        response=text_content or "",
                        raw_response=response,
                        purpose="execution",
                        model=self.model,
                        provider=self.provider_name,
                        call_id=_call_id,
                        response_preview=(text_content or "")[:500],
                        response_length=len(text_content or ""),
                        latency_ms={"total": max(1, int((_time.perf_counter() - _t0) * 1000))},
                    )
                except Exception:
                    pass

            return LLMResponse(
                text=text_content or "",
                tool_calls=tool_calls if tool_calls else [],
            )

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def probe(self) -> None:
        """Verify Gemini API reachability with a minimal call."""
        try:
            await self._client.aio.models.generate_content(
                model=self.model,
                contents=[self._types.Content(role="user", parts=[self._types.Part(text="ping")])],
                config=self._types.GenerateContentConfig(max_output_tokens=1),
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini probe failed: {exc}") from exc
