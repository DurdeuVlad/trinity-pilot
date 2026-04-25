"""CLI entry point -- dispatches to the domain MCP server class. No domain logic here."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import sys
from pathlib import Path

from typing import Any, Dict

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "browser-gui-automation"))
sys.path.insert(0, str(project_root / "cli-automation-poc"))
sys.path.insert(0, str(project_root / "api-accessibility-poc"))

DOMAIN_SERVER_MAP: Dict[str, str] = {
    "web":     "trinity_core.runtime_mcp.domains.browser.BrowserMCPServer",
    "cli":     "trinity_core.runtime_mcp.domains.cli.CLIMCPServer",
    "desktop": "trinity_core.runtime_mcp.domains.desktop.DesktopMCPServer",
    "excel":   "trinity_core.runtime_mcp.domains.excel.ExcelMCPServer",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve a Trinity domain toolset as an MCP server via stdio."
    )
    parser.add_argument(
        "--domain",
        required=True,
        help=f"Domain toolset to expose. Available: {list(DOMAIN_SERVER_MAP.keys())}",
    )
    args = parser.parse_args()

    if args.domain not in DOMAIN_SERVER_MAP:
        print(
            f"Unsupported domain: {args.domain}. Available: {list(DOMAIN_SERVER_MAP.keys())}",
            file=sys.stderr,
        )
        sys.exit(1)

    module_path, class_name = DOMAIN_SERVER_MAP[args.domain].rsplit(".", 1)
    module = importlib.import_module(module_path)
    ServerClass = getattr(module, class_name)
    asyncio.run(ServerClass().serve())


if __name__ == "__main__":
    main()
