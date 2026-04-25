"""CLI entry point for the Trinity Root composition server."""

from __future__ import annotations

import argparse
import asyncio

from trinity_core.runtime_mcp.root import create_default_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Trinity Root MCP composition server.")
    parser.add_argument(
        "--domain",
        default=None,
        help="Start with only this domain active. Omit for all domains.",
    )
    args = parser.parse_args()
    root = create_default_root()
    asyncio.run(root.serve(active_domain=args.domain))


if __name__ == "__main__":
    main()
