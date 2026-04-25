"""Abstract base for every Trinity MCP server."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.prompts import Message, PromptResult
from fastmcp.tools import FunctionTool
from fastmcp.tools.tool import ToolAnnotations

from trinity_core.runtime_mcp.middleware import ResponseSizeGuardMiddleware


class TrinityMCPServer(ABC):
    """Abstract base for every Trinity MCP server.

    build() auto-wires:
    - 4 standard prompts (capability_briefing, tool_selection_guide,
      error_recovery, forbidden_patterns)
    - 3 standard resources (server://capabilities, server://tool-index,
      server://domain-info)

    Tools register via raw MCP handlers (Option B) — FastMCP's add_tool()
    has no input_schema override and bans **kwargs. FastMCP wraps the server
    container for protocol compliance; prompts/resources use FastMCP decorators.
    """

    # ── Identity — ABSTRACT ──────────────────────────────────────────────

    @property
    @abstractmethod
    def domain(self) -> str:
        """Short domain key: 'web', 'cli', 'desktop', 'orchestrator'..."""

    @property
    @abstractmethod
    def server_name(self) -> str:
        """MCP server name e.g. 'trinity-web-toolset'."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human label e.g. 'Trinity Browser Toolset'."""

    @abstractmethod
    def instructions(self) -> str:
        """Server-level instructions surfaced at MCP handshake."""

    # ── Self-documentation content — non-abstract defaults ──────────────
    # Override in subclasses. Service servers (orchestrator, terminal) only
    # override the methods that make sense for their domain.

    def capability_briefing(self) -> str:
        return self.instructions()

    def tool_guides(self) -> dict[str, str]:
        """Override with action-type guidance. Required key: 'general'."""
        return {"general": "Use available tools as described in the tool list."}

    def recovery_guides(self) -> dict[str, str]:
        """Override with error_code->strategy mapping. Required key: 'default'."""
        return {"default": "Inspect current state before retrying."}

    def forbidden_patterns(self) -> str:
        return "No specific forbidden patterns defined for this server."

    def constraint_summaries(self) -> list[str]:
        return []

    def example_tasks(self) -> list[str]:
        return []

    def domain_metadata(self) -> dict[str, Any]:
        return {}

    # ── Tool registration — ABSTRACT ─────────────────────────────────────

    @abstractmethod
    def register_tools(self, mcp: FastMCP) -> None:
        """Register tools via mcp._mcp_server raw handlers.
        Must also set self._tools: dict[str, Tool] for resource use."""

    # ── Extension hooks — non-abstract ───────────────────────────────────

    def register_extra_prompts(self, mcp: FastMCP) -> None:
        """Override to add domain-specific prompts beyond the 4 standard."""

    def register_extra_resources(self, mcp: FastMCP) -> None:
        """Override to add domain-specific resources beyond the 3 standard."""

    def _max_output_chars(self) -> int:
        """Override per domain. Default 32k chars (~8k tokens)."""
        return 32_000

    # ── Framework — not overridden ────────────────────────────────────────

    def build(self) -> FastMCP:
        mcp = FastMCP(
            name=self.server_name,
            instructions=self.instructions(),
            on_duplicate="error",
        )
        mcp.add_middleware(ResponseSizeGuardMiddleware(max_chars=self._max_output_chars()))
        # Tools first — sets self._tools used by standard resources
        self.register_tools(mcp)
        self._register_standard_prompts(mcp)
        self._register_standard_resources(mcp)
        self.register_extra_prompts(mcp)
        self.register_extra_resources(mcp)
        return mcp

    async def serve(self) -> None:
        """Run as standalone stdio MCP server."""
        mcp = self.build()
        await mcp.run_async(transport="stdio")

    # ── Shared tool registration helper ──────────────────────────────────

    def _register_trinity_tools(self, mcp: FastMCP, trinity_tools: dict[str, Any]) -> None:
        """Register Trinity Tool instances as FastMCP FunctionTools.

        Using FunctionTool (vs raw _mcp_server handlers) makes tools visible
        through root.mount() namespace composition and tag-based filtering.
        Each tool's parameters schema passes through verbatim; **kwargs dispatch
        avoids FastMCP's strict signature inspection.
        """
        self._tools = trinity_tools
        for name, tool in trinity_tools.items():
            ann = tool.annotations()
            _tool = tool  # capture loop variable

            async def _execute(_t=_tool, **kwargs: Any) -> str:
                result = await _t.execute(**kwargs)
                return json.dumps({
                    "status": result.status,
                    "output": result.output,
                    "error": result.error,
                    "error_code": result.error_code,
                    "retryable": result.retryable,
                    "metadata": result.metadata,
                })

            _execute.__name__ = name
            mcp.add_tool(FunctionTool(
                name=name,
                description=tool.description(),
                parameters=tool.parameters(),
                tags={self.domain},  # enables tag-based domain filtering in root server
                annotations=ToolAnnotations(
                    title=ann.get("title", name),
                    readOnlyHint=ann.get("readOnlyHint", False),
                    destructiveHint=ann.get("destructiveHint", False),
                    idempotentHint=ann.get("idempotentHint", False),
                    openWorldHint=ann.get("openWorldHint", False),
                ),
                fn=_execute,
            ))

    # ── Standard prompt wiring ────────────────────────────────────────────

    def _register_standard_prompts(self, mcp: FastMCP) -> None:
        _self = self

        @mcp.prompt(
            name="capability_briefing",
            description="Full briefing: capabilities, constraints, guidance, forbidden patterns.",
            tags={"meta", _self.domain},
        )
        def _briefing() -> PromptResult:
            return PromptResult(
                messages=[Message(_self.capability_briefing())],
                description=f"{_self.display_name} capability briefing",
            )

        @mcp.prompt(
            name="tool_selection_guide",
            description="Which tool to use for a given action type.",
            tags={"meta", _self.domain},
        )
        def _tool_guide(
            action_type: Annotated[
                str, "Action type: inspect|mutate|wait|verify|recover|general"
            ] = "general",
        ) -> list[Message]:
            guides = _self.tool_guides()
            text = guides.get(action_type, guides.get("general", "No guide available."))
            return [
                Message(f"Tool selection guide for action_type='{action_type}':"),
                Message(text, role="assistant"),
            ]

        @mcp.prompt(
            name="error_recovery",
            description="Recovery strategy for a failed tool call.",
            tags={"meta", _self.domain},
        )
        def _recovery(
            error_code: Annotated[str, "Error code from the failed tool call"] = "",
            tool_name: Annotated[str, "Name of the tool that failed"] = "",
        ) -> list[Message]:
            guides = _self.recovery_guides()
            strategy = guides.get(
                error_code, guides.get("default", "Inspect state before retrying.")
            )
            return [
                Message(
                    f"Tool `{tool_name or 'unknown'}` failed with "
                    f"error_code=`{error_code or 'unknown'}`."
                ),
                Message(strategy, role="assistant"),
            ]

        @mcp.prompt(
            name="forbidden_patterns",
            description="What this server must NOT be used for.",
            tags={"meta", _self.domain},
        )
        def _forbidden() -> str:
            return _self.forbidden_patterns()

    # ── Standard resource wiring ──────────────────────────────────────────

    def _register_standard_resources(self, mcp: FastMCP) -> None:
        _self = self

        @mcp.resource(
            "server://capabilities",
            name="Capability Manifest",
            description="JSON: domain, tools, constraints, example tasks.",
            mime_type="application/json",
            annotations={"readOnlyHint": True, "idempotentHint": True},
            tags={"meta", _self.domain},
        )
        def _capabilities() -> str:
            tools = getattr(_self, "_tools", {})
            return json.dumps(
                {
                    "domain": _self.domain,
                    "server_name": _self.server_name,
                    "display_name": _self.display_name,
                    "tool_count": len(tools),
                    "tools": list(tools.keys()),
                    "constraints": _self.constraint_summaries(),
                    "example_tasks": _self.example_tasks(),
                },
                indent=2,
            )

        @mcp.resource(
            "server://tool-index",
            name="Tool Index",
            description="JSON list: name, description, params, safety hints per tool.",
            mime_type="application/json",
            annotations={"readOnlyHint": True, "idempotentHint": True},
            tags={"meta", _self.domain},
        )
        def _tool_index() -> str:
            tools = getattr(_self, "_tools", {})
            return json.dumps(
                [
                    {
                        "name": name,
                        "description": t.description(),
                        "params": list(t.parameters().get("properties", {}).keys()),
                        "read_only": t.annotations().get("readOnlyHint", False),
                        "destructive": t.annotations().get("destructiveHint", False),
                        "idempotent": t.annotations().get("idempotentHint", False),
                    }
                    for name, t in tools.items()
                ],
                indent=2,
            )

        @mcp.resource(
            "server://domain-info",
            name="Domain Info",
            description="JSON: domain, display name, execution model, tech stack.",
            mime_type="application/json",
            annotations={"readOnlyHint": True, "idempotentHint": True},
            tags={"meta", _self.domain},
        )
        def _domain_info() -> str:
            info: dict[str, Any] = {
                "domain": _self.domain,
                "server_name": _self.server_name,
                "display_name": _self.display_name,
            }
            info.update(_self.domain_metadata())
            return json.dumps(info, indent=2)
