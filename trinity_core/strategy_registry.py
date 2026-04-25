"""Top-level MCP target registry for visible tool-backed execution."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PromptContribution:
    """Static prompt fragments contributed by a selected strategy.

    DEPRECATED: FastMCP domain servers expose guidance natively via MCP prompts
    and resources. MCPStrategyRuntime uses server self-documentation when available
    and falls back to this only for legacy/pre-FastMCP servers. Remove the fallback
    branch in _build_system_prompt once all servers are migrated.
    """

    system_guidance: list[str] = field(default_factory=list)
    tool_guidance: list[str] = field(default_factory=list)
    recovery_guidance: list[str] = field(default_factory=list)
    verification_guidance: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    def render(self) -> str:
        sections: list[str] = []
        if self.system_guidance:
            sections.append("System guidance:\n- " + "\n- ".join(self.system_guidance))
        if self.tool_guidance:
            sections.append("Tool guidance:\n- " + "\n- ".join(self.tool_guidance))
        if self.recovery_guidance:
            sections.append("Recovery guidance:\n- " + "\n- ".join(self.recovery_guidance))
        if self.verification_guidance:
            sections.append("Verification guidance:\n- " + "\n- ".join(self.verification_guidance))
        if self.forbidden_patterns:
            sections.append("Forbidden patterns:\n- " + "\n- ".join(self.forbidden_patterns))
        if self.examples:
            sections.append("Examples:\n- " + "\n- ".join(self.examples))
        return "\n\n".join(section for section in sections if section)


@dataclass(slots=True)
class MCPStrategy:
    """Registered strategy backed by an MCP server/toolset."""

    strategy_id: str
    server_command: str
    server_args: list[str]
    domain: str
    display_name: str
    description: str
    prompt_contribution: PromptContribution = field(default_factory=PromptContribution)
    env: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    objective_keywords: list[str] = field(default_factory=list)
    serial_execution: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class StrategyRegistry:
    """Registry of available MCP-backed strategies."""

    def __init__(self) -> None:
        self._strategies: dict[str, MCPStrategy] = {}

    def register(self, strategy: MCPStrategy) -> None:
        self._strategies[strategy.strategy_id] = strategy

    def get(self, strategy_id: str) -> MCPStrategy:
        if strategy_id not in self._strategies:
            raise KeyError(f"Unknown strategy: {strategy_id}")
        return self._strategies[strategy_id]

    def list(self) -> list[MCPStrategy]:
        return list(self._strategies.values())

    def suggest_domain(self, description: str) -> str:
        """Suggest a domain based on description matching strategy keywords and tags."""
        lowered = description.lower()
        
        # Track hits per domain
        domain_hits: dict[str, int] = {}

        for strategy in self._strategies.values():
            hits = 0
            # Check keywords
            for kw in strategy.objective_keywords:
                if kw.lower() in lowered:
                    hits += 2 # Keywords are strong signals
            # Check tags
            for tag in strategy.tags:
                if tag.lower() in lowered:
                    hits += 1

            if hits > 0:
                domain_hits[strategy.domain] = domain_hits.get(strategy.domain, 0) + hits

        if not domain_hits:
            return "cli" # Default fallback

        # If multiple domains hit, return "mixed"
        if len(domain_hits) > 1:
            # But only if the second highest is significant
            sorted_hits = sorted(domain_hits.items(), key=lambda x: x[1], reverse=True)
            if len(sorted_hits) > 1 and sorted_hits[1][1] >= 1:
                return "mixed"
            return sorted_hits[0][0]

        return list(domain_hits.keys())[0]

    @classmethod
    def create_default(cls, project_root: Path) -> "StrategyRegistry":
        registry = cls()
        python_exe = sys.executable
        internal_server = str(project_root / "trinity_core" / "toolset_mcp_server.py")
        puppeteer_server = str(project_root / "puppeteer-mcp-wrapper" / "proxy_server.py")

        registry.register(
            MCPStrategy(
                strategy_id="browser_mcp",
                server_command=python_exe,
                server_args=[internal_server, "--domain", "web"],
                domain="web",
                display_name="Trinity Browser Toolset",
                description="Current Trinity browser tools exposed as an MCP strategy.",
                objective_keywords=["browser", "website", "google", "navigate", "search", "wikipedia", "url", "site", "github", "www", "http", "https"],
                tags=["browser", "web"],
                prompt_contribution=PromptContribution(
                    system_guidance=[
                        "You are operating a browser-focused MCP toolset.",
                        "All exposed browser tools are available for direct reasoning and use.",
                    ],
                    tool_guidance=[
                        "Prefer inspect/read-oriented browser tools before mutating actions when state is uncertain.",
                        "Use browser-native waiting tools instead of repeating clicks on stale pages.",
                    ],
                    recovery_guidance=[
                        "If a selector fails, try another visible selector or a wait tool before abandoning the page.",
                    ],
                    verification_guidance=[
                        "Verify current URL, visible text, or screenshots after material navigation or form actions.",
                    ],
                    forbidden_patterns=[
                        "Do not fall back to CLI or desktop to recover a browser-only objective.",
                    ],
                ),
                serial_execution=False,
            )
        )
        registry.register(
            MCPStrategy(
                strategy_id="cli_mcp",
                server_command=python_exe,
                server_args=[internal_server, "--domain", "cli"],
                domain="cli",
                display_name="Trinity CLI Toolset",
                description="Current Trinity CLI tools exposed as an MCP strategy.",
                objective_keywords=["terminal", "command", "shell", "powershell", "cmd", "files", "directory", "run script"],
                tags=["cli", "shell"],
                prompt_contribution=PromptContribution(
                    system_guidance=[
                        "You are operating a Windows CLI-oriented MCP toolset.",
                    ],
                    tool_guidance=[
                        "Prefer read-only commands first when filesystem or process state is unknown.",
                        "Use wait tools instead of polling manually in repeated command calls.",
                    ],
                    recovery_guidance=[
                        "If a command fails, change the command or inspect state; do not blindly repeat it.",
                    ],
                    verification_guidance=[
                        "Use command output and wait conditions as evidence of completion.",
                    ],
                    forbidden_patterns=[
                        "Do not use destructive commands unless the objective explicitly requires them.",
                    ],
                ),
                serial_execution=True,
            )
        )
        registry.register(
            MCPStrategy(
                strategy_id="desktop_mcp",
                server_command=python_exe,
                server_args=[internal_server, "--domain", "desktop"],
                domain="desktop",
                display_name="Trinity Desktop Toolset",
                description="Current Trinity desktop tools exposed as an MCP strategy.",
                objective_keywords=["notepad", "calculator", "window", "desktop", "application", "app", "ui", "automation"],
                tags=["desktop", "uia"],
                prompt_contribution=PromptContribution(
                    system_guidance=[
                        "You are operating a desktop UI automation MCP toolset.",
                    ],
                    tool_guidance=[
                        "Focus the correct window before typing or interacting with controls.",
                        "Use wait tools to confirm apps, windows, and UI elements before acting.",
                    ],
                    recovery_guidance=[
                        "If a window or element is missing, inspect and wait instead of repeating raw interactions.",
                    ],
                    verification_guidance=[
                        "Verify visible window titles or elements after meaningful desktop actions.",
                    ],
                    forbidden_patterns=[
                        "Do not use CLI tools to simulate desktop shortcuts in a desktop objective.",
                    ],
                ),
                serial_execution=True,
            )
        )
        registry.register(
            MCPStrategy(
                strategy_id="puppeteer_mcp",
                server_command=python_exe,
                server_args=[puppeteer_server],
                domain="web",
                display_name="Puppeteer MCP Wrapper",
                description="Thin Trinity wrapper around an upstream Puppeteer-compatible MCP server.",
                objective_keywords=["puppeteer", "playwright", "scraping", "automation", "headless"],
                tags=["browser", "puppeteer", "web"],
                prompt_contribution=PromptContribution(
                    system_guidance=[
                        "You are operating a wrapped Puppeteer MCP strategy.",
                        "All upstream Puppeteer tools exposed by the wrapper are available for direct use.",
                    ],
                    tool_guidance=[
                        "Prefer the most specific upstream Puppeteer tool for the current page state.",
                        "Use screenshots and extraction tools as evidence rather than guessing.",
                    ],
                    recovery_guidance=[
                        "If an interaction fails, inspect the page again before retrying a similar action.",
                    ],
                    verification_guidance=[
                        "Use the wrapped browser metadata, page text, and screenshots to confirm completion.",
                    ],
                    forbidden_patterns=[
                        "Do not rely on hidden wrapper-only actions; only use tools visible in the discovered tool catalog.",
                    ],
                ),
                serial_execution=False,
                metadata={"wrapper": "thin"},
            )
        )
        return registry
