#!/usr/bin/env bash
# Setup script for trinity-pilot.
# Run once after cloning or when dependencies change.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[setup] Installing trinity-pilot dependencies via uv sync..."
uv sync

echo "[setup] Done."
echo "[setup] Start the app with:     python -m trinity_pilot"
echo "[setup] Start the MCP server with: python -m trinity_pilot.mcp.orchestrator_server"
