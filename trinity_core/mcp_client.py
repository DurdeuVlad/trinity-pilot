"""Generic stdio MCP client used by strategy runtimes and wrappers."""

from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass(slots=True)
class MCPPromptDescriptor:
    name: str
    description: str
    arguments: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MCPToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class MCPStrategyClient:
    """Lazy stdio client for MCP strategy servers."""

    def __init__(
        self,
        command: str,
        args: list[str],
        env: Optional[dict[str, str]] = None,
    ) -> None:
        self.command = command
        self.args = list(args)
        self.env = dict(env or {})
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()
        self.stdio = None
        self.write = None
        self._connected = False

    async def connect(self) -> None:
        if self._connected:
            return
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env={**os.environ, **self.env},
        )
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        await self.session.initialize()
        self._connected = True

    async def disconnect(self) -> None:
        if not self._connected:
            return
        try:
            await self.exit_stack.aclose()
        except BaseException as exc:
            if exc.__class__.__name__ != "CancelledError":
                raise
        self._connected = False
        self.session = None

    async def list_tools(self) -> list[MCPToolDescriptor]:
        await self.connect()
        assert self.session is not None
        result = await self.session.list_tools()
        return [
            MCPToolDescriptor(
                name=tool.name,
                description=getattr(tool, "description", "") or "",
                input_schema=getattr(tool, "inputSchema", {}) or {},
                metadata=self._normalize_tool_metadata(getattr(tool, "annotations", None)),
            )
            for tool in result.tools
        ]

    def _normalize_tool_metadata(self, annotations: Any) -> dict[str, Any]:
        if annotations is None:
            return {}
        if isinstance(annotations, dict):
            return dict(annotations)
        model_dump = getattr(annotations, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                return dumped
        return {}

    async def list_prompts(self) -> list[MCPPromptDescriptor]:
        await self.connect()
        assert self.session is not None
        result = await self.session.list_prompts()
        return [
            MCPPromptDescriptor(
                name=p.name,
                description=getattr(p, "description", "") or "",
                arguments=[a.name for a in (getattr(p, "arguments", None) or [])],
            )
            for p in result.prompts
        ]

    async def get_prompt(self, name: str, arguments: Optional[dict[str, str]] = None) -> str:
        await self.connect()
        assert self.session is not None
        result = await self.session.get_prompt(name, arguments or {})
        texts: list[str] = []
        for msg in result.messages:
            content = getattr(msg, "content", None)
            if content is None:
                continue
            text = getattr(content, "text", None)
            if text:
                texts.append(text)
        return "\n".join(texts)

    async def list_resources(self) -> list[str]:
        await self.connect()
        assert self.session is not None
        result = await self.session.list_resources()
        return [str(r.uri) for r in result.resources]

    async def read_resource(self, uri: str) -> str:
        await self.connect()
        assert self.session is not None
        result = await self.session.read_resource(uri)
        for content in result.contents:
            text = getattr(content, "text", None)
            if text:
                return text
        return ""

    async def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        await self.connect()
        assert self.session is not None
        result = await self.session.call_tool(name, arguments or {})
        texts: list[str] = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text is not None:
                texts.append(text)
        payload_text = "\n".join(texts).strip()
        if not payload_text:
            return {"status": "success", "output": "", "metadata": {}}
        try:
            parsed = json.loads(payload_text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"status": "success", "output": payload_text, "metadata": {}}
