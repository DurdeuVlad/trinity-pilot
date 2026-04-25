"""Minimal MCP strategy server for tests."""

from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool, ToolAnnotations


async def main() -> None:
    server = Server("fake-strategy-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="echo",
                description="Echo text back to the orchestrator",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                annotations=ToolAnnotations(
                    title="Echo Tool",
                    readOnlyHint=True,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            ),
            Tool(
                name="inspect_state",
                description="Return fake state metadata",
                inputSchema={"type": "object", "properties": {}, "required": []},
                annotations=ToolAnnotations(
                    title="Inspect State",
                    readOnlyHint=True,
                    idempotentHint=True,
                    openWorldHint=True,
                ),
            ),
            Tool(
                name="inspect_window",
                description="Return fake desktop window metadata",
                inputSchema={"type": "object", "properties": {}, "required": []},
                annotations=ToolAnnotations(
                    title="Inspect Window",
                    readOnlyHint=True,
                    idempotentHint=True,
                    openWorldHint=True,
                ),
            ),
            Tool(
                name="silent_success",
                description="Return success without evidence-bearing metadata",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            Tool(
                name="transient_fail",
                description="Return a transient backend-style failure",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments):
        if name == "echo":
            payload = {
                "status": "success",
                "output": str((arguments or {}).get("text", "")),
                "metadata": {"tool": "echo", "exit_code": 0},
                "retryable": True,
            }
        elif name == "inspect_state":
            payload = {
                "status": "success",
                "output": "state-ok",
                "metadata": {"tool": "inspect_state", "current_url": "https://example.com/app", "page_title": "Example App"},
                "retryable": True,
            }
        elif name == "inspect_window":
            payload = {
                "status": "success",
                "output": "window-ok",
                "metadata": {"tool": "inspect_window", "active_window": "Example Desktop App", "app_context": "Example Desktop App"},
                "retryable": True,
            }
        elif name == "silent_success":
            payload = {
                "status": "success",
                "output": "",
                "metadata": {"tool": "silent_success"},
                "retryable": True,
            }
        elif name == "transient_fail":
            payload = {
                "status": "error",
                "output": "",
                "error": "window_not_found while app is still loading",
                "error_code": "WINDOW_NOT_FOUND",
                "retryable": True,
                "metadata": {"tool": "transient_fail"},
            }
        else:
            payload = {
                "status": "error",
                "output": "",
                "error": f"unknown tool: {name}",
                "error_code": "UNKNOWN_TOOL",
                "retryable": False,
                "metadata": {},
            }
        return [TextContent(type="text", text=json.dumps(payload))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
