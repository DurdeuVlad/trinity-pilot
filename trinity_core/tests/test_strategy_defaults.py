from __future__ import annotations

import sys
from pathlib import Path

from trinity_core.strategy_registry import StrategyRegistry


def test_default_web_strategy_is_internal_browser_until_puppeteer_is_explicitly_enabled():
    registry = StrategyRegistry.create_default(Path(__file__).resolve().parents[1])
    assert registry.get("browser_mcp").domain == "web"
    assert registry.get("browser_mcp").server_command == sys.executable
