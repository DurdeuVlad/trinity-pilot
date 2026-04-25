"""Trinity Root MCP server — composition gateway for all domain servers."""

from __future__ import annotations

import importlib
import logging

from fastmcp import FastMCP

from trinity_core.runtime_mcp.base import TrinityMCPServer

logger = logging.getLogger(__name__)

_DOMAIN_CLASS_MAP: dict[str, str] = {
    "web":     "trinity_core.runtime_mcp.domains.browser.BrowserMCPServer",
    "cli":     "trinity_core.runtime_mcp.domains.cli.CLIMCPServer",
    "desktop": "trinity_core.runtime_mcp.domains.desktop.DesktopMCPServer",
    "excel":   "trinity_core.runtime_mcp.domains.excel.ExcelMCPServer",
}


def _load_domain_server(domain: str) -> TrinityMCPServer | None:
    """Lazy-load domain server class. Returns None if dependencies unavailable."""
    class_path = _DOMAIN_CLASS_MAP.get(domain)
    if not class_path:
        return None
    module_path, class_name = class_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()
    except ImportError as e:
        logger.warning("Domain '%s' unavailable (missing dependency): %s", domain, e)
        return None


class TrinityRootServer:
    """Composition gateway — all domains mounted, one active at a time.

    FastMCP has no unmount(). Active domain is controlled via tag visibility:
    root.enable(tags={"web"}, only=True) shows only web-tagged components.
    Tag filtering is ANY match — components tagged {"meta", "web"} ARE shown.
    Tag filtering propagates recursively to all mounted children.

    NOT used by MCPStrategyRuntime (which spawns individual stdio subprocesses).
    Used by: orchestrator AI discovery, supervisor layer, external clients.
    """

    def __init__(self, servers: list[TrinityMCPServer] | None = None) -> None:
        self._servers: list[TrinityMCPServer] = servers or []

    def register(self, server: TrinityMCPServer) -> None:
        self._servers.append(server)

    def build(self, active_domain: str | None = None) -> FastMCP:
        available = [s.domain for s in self._servers]
        domain_list = ", ".join(available)

        root = FastMCP(
            name="trinity-root",
            instructions=f"""\
Trinity Root Server — unified gateway to all Trinity domain servers.
Registered domains: {domain_list}

All domain components are namespace-prefixed with the domain key:
- Tools:     <domain>_<tool_name>   (e.g. web_navigate, cli_run_command)
- Prompts:   <domain>_<prompt_name> (e.g. web_capability_briefing)
- Resources: server://<domain>/<resource> (e.g. server://web/capabilities)

To filter to one active domain: enable(tags={{<domain>}}, only=True).
Tag filtering uses ANY match — domain tag is sufficient.
""",
        )
        for server in self._servers:
            try:
                child = server.build()
                root.mount(child, namespace=server.domain)
            except Exception as e:
                logger.error("Failed to mount domain '%s': %s", server.domain, e)

        if active_domain is not None:
            root.enable(tags={active_domain}, only=True)

        return root

    def switch_domain(self, root_mcp: FastMCP, domain: str) -> None:
        """Switch active domain on a running root instance.
        Caller must ensure no task is active before switching."""
        root_mcp.enable(tags={domain}, only=True)

    async def serve(self, active_domain: str | None = None) -> None:
        mcp = self.build(active_domain=active_domain)
        await mcp.run_async(transport="stdio")

    def run(self, active_domain: str | None = None) -> None:
        """Sync entry point for CLI use."""
        mcp = self.build(active_domain=active_domain)
        mcp.run()


def create_default_root() -> TrinityRootServer:
    """Build TrinityRootServer with all available default domain servers.
    Domains whose dependencies are missing are skipped with a warning."""
    root = TrinityRootServer()
    for domain in ("web", "cli", "desktop"):
        server = _load_domain_server(domain)
        if server is not None:
            root.register(server)
    return root
