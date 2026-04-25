"""MCP strategy runtime benchmark scenarios for browser, desktop, and CLI domains.

These benchmarks use the shared MCP-first runtime against the fake strategy
server so they measure the active orchestration path rather than the retired
adapter/reviewer runtimes.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from ..llm.llm_provider import LLMResponse, ToolCall
from ..mcp_strategy_runtime import MCPStrategyRuntime
from ..models import TaskInput
from ..strategy_registry import MCPStrategy
from .benchmark_framework import Benchmark, BenchmarkResult


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

class _CountingLLM:
    """LLM stub that fires one tool call then returns a text response."""

    def __init__(self, tool_name: str, tool_args: dict[str, Any], text_response: str = "done") -> None:
        self.calls = 0
        self._tool_name = tool_name
        self._tool_args = tool_args
        self._text = text_response

    async def call(self, messages: Any, tools: Any) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name=self._tool_name, arguments=self._tool_args)])
        return LLMResponse(text=self._text)

_FAKE_SERVER = Path(__file__).resolve().parents[1] / "tests" / "fake_strategy_server.py"


class _StrategyRuntimeBenchmark(Benchmark):
    strategy_name: str
    domain: str
    tool_name: str
    tool_args: dict[str, Any]
    description: str

    def __init__(self) -> None:
        self._llm: _CountingLLM | None = None
        self._strategy: MCPStrategy | None = None

    def setup(self) -> None:
        self._llm = _CountingLLM(self.tool_name, self.tool_args)
        self._strategy = MCPStrategy(
            strategy_id=self.strategy_name,
            server_command=sys.executable,
            server_args=[str(_FAKE_SERVER)],
            domain=self.domain,
            display_name=self.strategy_name,
            description=f"{self.strategy_name} benchmark strategy",
        )

    async def run(self) -> BenchmarkResult:
        assert self._llm is not None
        assert self._strategy is not None
        self._llm.calls = 0
        runtime = MCPStrategyRuntime(strategy=self._strategy, llm_provider=self._llm)
        try:
            t0 = time.monotonic()
            result = await runtime.execute(
                TaskInput(task_id=f"bench-{self.strategy_name}", description=self.description, domain=self.domain)
            )
            duration_ms = (time.monotonic() - t0) * 1000
            return BenchmarkResult(
                task_name=self.name,
                duration_ms=duration_ms,
                llm_calls=self._llm.calls,
                tool_calls=1,
                success=result.status == "success",
            )
        finally:
            await runtime.close()

    def teardown(self) -> None:
        self._strategy = None


class BrowserRuntimeBenchmark(_StrategyRuntimeBenchmark):
    name = "browser_runtime_single_tool"
    strategy_name = "browser-bench"
    domain = "web"
    tool_name = "inspect_state"
    tool_args = {}
    description = "Inspect browser state"


class DesktopRuntimeBenchmark(_StrategyRuntimeBenchmark):
    name = "desktop_runtime_single_tool"
    strategy_name = "desktop-bench"
    domain = "desktop"
    tool_name = "inspect_window"
    tool_args = {}
    description = "Inspect desktop state"


class CLIRuntimeBenchmark(_StrategyRuntimeBenchmark):
    name = "cli_runtime_single_tool"
    strategy_name = "cli-bench"
    domain = "cli"
    tool_name = "echo"
    tool_args = {"text": "benchmark output"}
    description = "Echo benchmark output"
