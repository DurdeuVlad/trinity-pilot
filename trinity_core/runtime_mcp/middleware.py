"""Trinity MCP middleware."""

from __future__ import annotations

import json

from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import TextContent


class ResponseSizeGuardMiddleware(Middleware):
    """Truncate oversized tool output to protect executor AI context window.

    Parses Trinity's JSON payload, truncates the 'output' field if it exceeds
    max_chars, and reconstructs a valid TextContent. Does NOT mutate Pydantic
    model attributes in-place — creates new TextContent instances.
    """

    def __init__(self, max_chars: int = 32_000) -> None:
        self.max_chars = max_chars

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        result = await call_next(context)

        new_content = []
        changed = False
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text is None:
                new_content.append(item)
                continue
            try:
                payload = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                new_content.append(item)
                continue

            output = payload.get("output", "")
            if isinstance(output, str) and len(output) > self.max_chars:
                payload["metadata"] = payload.get("metadata") or {}
                payload["metadata"]["truncated"] = True
                payload["metadata"]["original_length"] = len(output)
                payload["output"] = output[: self.max_chars] + "\n[OUTPUT TRUNCATED]"
                new_content.append(TextContent(type="text", text=json.dumps(payload)))
                changed = True
            else:
                new_content.append(item)

        if changed:
            try:
                result.content = new_content
            except Exception:
                # result may be frozen Pydantic model — return original unchanged
                pass

        return result
