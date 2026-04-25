"""Trinity MCP package — FastMCP-backed server infrastructure."""

from trinity_core.runtime_mcp.base import TrinityMCPServer
from trinity_core.runtime_mcp.root import TrinityRootServer, create_default_root

__all__ = ["TrinityMCPServer", "TrinityRootServer", "create_default_root"]
