"""Top-level MCP target registry for visible tool-backed execution."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PromptContribution:
    """Static prompt fragments contributed by a selected strategy.

    DEPRECATED: FastMCP domain servers expose guidance natively via MCP prompts
    and resources. SubObjectiveExecutor uses server self-documentation when available
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
    example_tasks: list[str] = field(default_factory=list)
    serial_execution: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _mutate_strategy(strategy: MCPStrategy, **fields: Any) -> None:
    """Mutate fields on a slots=True dataclass instance via object.__setattr__."""
    for key, value in fields.items():
        object.__setattr__(strategy, key, value)


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
            if len(sorted_hits) > 1 and sorted_hits[1][1] >= 3:
                return "mixed"
            return sorted_hits[0][0]

        return list(domain_hits.keys())[0]

    _STOP_WORDS: frozenset[str] = frozenset({
        "the", "a", "an", "and", "or", "to", "in", "on", "at", "for",
        "of", "with", "by", "from", "its", "it", "is", "are", "was",
        "that", "this", "then", "into", "use", "via", "all",
    })

    def suggest_strategy_for_objective(self, objective: str) -> str:
        """Return the best strategy_id for a single objective string.

        Scores each strategy against:
        - objective_keywords: +2 per keyword found in objective
        - tags: +1 per tag found in objective
        - example_tasks token overlap: +1 per content token (>=4 chars, not a stop word)
          found in objective

        Returns the highest-scoring strategy_id. Falls back to 'cli_mcp' if no signal.
        """
        lowered = objective.lower()
        scores: dict[str, int] = {}

        for strategy in self._strategies.values():
            score = 0
            for kw in strategy.objective_keywords:
                if kw.lower() in lowered:
                    score += 2
            for tag in strategy.tags:
                if tag.lower() in lowered:
                    score += 1
            for example in strategy.example_tasks:
                for token in example.lower().split():
                    if token in self._STOP_WORDS or len(token) < 4:
                        continue
                    if token in lowered:
                        score += 1
            if score > 0:
                scores[strategy.strategy_id] = scores.get(strategy.strategy_id, 0) + score

        if not scores:
            return "cli_mcp"
        return max(scores, key=lambda k: scores[k])

    async def enrich_from_server(
        self,
        strategy_id: str,
        timeout: float = 10.0,
    ) -> bool:
        """Connect to a strategy's MCP server and enrich the registry entry.

        Reads server://capabilities and merges the reported data into the strategy:
        - example_tasks: server tasks appended to manifest tasks (deduped)
        - live_tools: stored in strategy.metadata["live_tools"]
        - constraints: stored in strategy.metadata["constraints"]
        - domain: validated against manifest; manifest wins on mismatch

        Returns True on success, False if server was unreachable.
        Never raises -- enrichment failure is non-fatal.
        """
        from .mcp_client import MCPStrategyClient

        strategy = self._strategies.get(strategy_id)
        if strategy is None:
            return False

        client = MCPStrategyClient(
            command=strategy.server_command,
            args=strategy.server_args,
            env=strategy.env,
        )

        async def _fetch() -> str:
            await client.connect()
            return await client.read_resource("server://capabilities")

        try:
            raw = await asyncio.wait_for(_fetch(), timeout=timeout)
            data = json.loads(raw)
        except Exception as exc:
            _logger.warning(
                "Capability enrichment skipped for '%s' (non-fatal): %s",
                strategy_id,
                exc,
            )
            return False
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        # Validate domain -- manifest wins
        reported_domain = str(data.get("domain") or "")
        if reported_domain and reported_domain != strategy.domain:
            _logger.warning(
                "Strategy '%s': manifest domain '%s' != server-reported '%s'. Manifest wins.",
                strategy_id,
                strategy.domain,
                reported_domain,
            )

        # Merge example_tasks: append server tasks not already in manifest list
        server_examples = [t for t in data.get("example_tasks", []) if isinstance(t, str)]
        existing = set(strategy.example_tasks)
        merged_examples = list(strategy.example_tasks) + [t for t in server_examples if t not in existing]

        # Collect live tools and constraints into metadata
        new_meta = dict(strategy.metadata)
        new_meta["live_tools"] = [t for t in data.get("tools", []) if isinstance(t, str)]
        new_meta["constraints"] = [c for c in data.get("constraints", []) if isinstance(c, str)]

        _mutate_strategy(strategy, example_tasks=merged_examples, metadata=new_meta)

        _logger.info(
            "Enriched '%s': %d example_tasks total, %d live_tools",
            strategy_id,
            len(merged_examples),
            len(new_meta["live_tools"]),
        )
        return True

    async def enrich_all(
        self,
        timeout_per_server: float = 10.0,
    ) -> dict[str, bool]:
        """Enrich all registered strategies in parallel.

        Returns {strategy_id: success_bool} for every registered strategy.
        """
        strategy_ids = list(self._strategies.keys())
        results = await asyncio.gather(
            *[self.enrich_from_server(sid, timeout=timeout_per_server) for sid in strategy_ids],
            return_exceptions=False,
        )
        return dict(zip(strategy_ids, results))

    @classmethod
    def create_from_manifest(
        cls,
        manifest_path: Path,
        project_root: Path,
    ) -> "StrategyRegistry":
        """Load strategies from a JSON manifest file.

        Path tokens resolved at load time:
          {python}       -> sys.executable
          {trinity_core} -> <project_root>/trinity_core  (absolute)
          {project_root} -> <project_root>               (absolute)
        """
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)

        project_root = project_root.resolve()
        tokens = {
            "{python}": sys.executable,
            "{trinity_core}": str(project_root / "trinity_core"),
            "{project_root}": str(project_root),
        }

        def _resolve(value: str) -> str:
            for token, replacement in tokens.items():
                value = value.replace(token, replacement)
            return value

        registry = cls()
        for entry in data.get("servers", []):
            env_raw = entry.get("env") or {}
            strategy = MCPStrategy(
                strategy_id=entry["strategy_id"],
                server_command=_resolve(entry["command"]),
                server_args=[_resolve(a) for a in entry.get("args", [])],
                domain=entry["domain"],
                display_name=entry.get("display_name", entry["strategy_id"]),
                description=entry.get("description", ""),
                env={k: _resolve(v) for k, v in env_raw.items()},
                tags=list(entry.get("tags", [])),
                objective_keywords=list(entry.get("objective_keywords", [])),
                example_tasks=list(entry.get("example_tasks", [])),
                serial_execution=bool(entry.get("serial_execution", False)),
                metadata=dict(entry.get("metadata", {})),
            )
            registry.register(strategy)

        _logger.info("Loaded %d strategies from %s", len(registry._strategies), manifest_path)
        return registry

    @classmethod
    def create_default(cls, project_root: Path) -> "StrategyRegistry":
        """Load strategies from mcp_servers.json; fall back to inline definitions."""
        manifest = project_root / "trinity_core" / "mcp_servers.json"
        if manifest.exists():
            return cls.create_from_manifest(manifest, project_root)
        _logger.warning(
            "mcp_servers.json not found at %s; using inline strategy definitions.", manifest
        )
        return cls._create_inline(project_root)

    @classmethod
    def _create_inline(cls, project_root: Path) -> "StrategyRegistry":
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
                env={"MCP_SERVER": "1"},
                objective_keywords=[
                    "browser", "website", "google", "navigate", "search", "wikipedia",
                    "wiki", "url", "site", "github", "www", "http", "https",
                    "page", "pagina", "pagină", "caut", "cauta", "caută",
                    "look up", "find online", "visit", "open link", "web search",
                    "online", "internet",
                ],
                example_tasks=[
                    "Navigate to https://example.com and extract the page title",
                    "Fill in a login form and submit it",
                    "Wait for a dynamic element to appear and click it",
                    "Take a screenshot to verify page state",
                    "Search for a term on Google",
                    "Open a URL in the browser",
                    "Scroll down the page and extract text",
                    "Find information on Wikipedia",
                ],
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
                env={"MCP_SERVER": "1"},
                objective_keywords=["terminal", "command", "shell", "powershell", "cmd", "files", "directory", "run script"],
                example_tasks=[
                    "List files in a directory",
                    "Read the contents of a configuration file",
                    "Run a Python script and capture its output",
                    "Check if a process is running",
                    "Save text to a file",
                    "Create a new folder",
                    "Delete a temporary file",
                ],
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
                env={"MCP_SERVER": "1"},
                objective_keywords=[
                    "notepad", "calculator", "window", "desktop", "application",
                    "app", "ui", "automation", "excel", "word", "explorer",
                    "paint", "settings", "launch", "open app", "task manager",
                    "control panel", "click on", "right click", "double click",
                ],
                example_tasks=[
                    "Open Notepad and type text into the editor",
                    "Click a button in a running desktop application",
                    "Read the text content of a window control",
                    "Close an application via its window controls",
                    "Open Calculator and perform a calculation",
                    "Launch an application from the start menu",
                    "Right-click the desktop and open properties",
                ],
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
