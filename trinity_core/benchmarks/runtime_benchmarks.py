"""Runtime benchmark scenarios for browser, desktop, and CLI domains.

These benchmarks use lightweight in-process stubs rather than live backends so
they can be run in a standard CI environment.  The measurements exercise the
runtime loop overhead (session management, tool dispatch, reviewer path) and
are useful for detecting regressions.

Live comparison (runtime vs adapter) is handled by ``PerformanceTracker`` in
the audit-debugger.
"""

from __future__ import annotations

import time
from typing import Any

from ..llm.llm_provider import LLMResponse, ToolCall
from ..models import TaskInput
from ..orchestrators.browser_runtime import BrowserRuntime
from ..orchestrators.cli_runtime import CLIRuntime
from ..orchestrators.desktop_runtime import DesktopRuntime
from ..orchestrators.review_types import ReviewResult
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


class _InstantApproveReviewer:
    async def review(self, *args: Any, **kwargs: Any) -> ReviewResult:
        return ReviewResult(approved=True, feedback="ok")


# ---------------------------------------------------------------------------
# Browser benchmark
# ---------------------------------------------------------------------------

class _BrowserAdapter:
    async def navigate(self, url: str) -> None: ...
    async def click(self, selector: str) -> None: ...
    async def type_text(self, selector: str, text: str) -> None: ...
    async def extract_text(self, selector: str) -> str: return ""
    async def screenshot(self) -> bytes: return b""
    async def wait_for_selector(self, selector: str, timeout: float = 10.0, state: str = "visible") -> None: ...
    async def wait_for_load_state(self, wait_until: str = "load", timeout: float = 30.0) -> None: ...
    async def get_current_url(self) -> str: return "https://example.com"


class BrowserRuntimeBenchmark(Benchmark):
    """Benchmark: browser runtime single-tool task (navigate + text response)."""

    name = "browser_runtime_single_tool"

    def __init__(self) -> None:
        self._llm: _CountingLLM | None = None

    def setup(self) -> None:
        self._llm = _CountingLLM("navigate", {"url": "https://www.example.com"})

    async def run(self) -> BenchmarkResult:
        assert self._llm is not None
        self._llm.calls = 0
        t0 = time.monotonic()
        runtime = BrowserRuntime(
            adapter=_BrowserAdapter(),  # type: ignore[arg-type]
            llm_provider=self._llm,
            reviewer=_InstantApproveReviewer(),  # type: ignore[arg-type]
        )
        task = TaskInput(task_id="bench-browser", description="Navigate to example.com and search for python", domain="web")
        # Metrics writes go to a temp path; capture tool/llm counts from llm stub.
        result = await runtime.execute(task)
        duration_ms = (time.monotonic() - t0) * 1000
        return BenchmarkResult(
            task_name=self.name,
            duration_ms=duration_ms,
            llm_calls=self._llm.calls,
            tool_calls=1,
            success=result.status == "success",
        )


# ---------------------------------------------------------------------------
# Desktop benchmark
# ---------------------------------------------------------------------------

class _DesktopAdapter:
    async def open_app(self, app_name: str) -> None: ...
    async def click(self, element_id: str) -> None: ...
    async def type_text(self, element_id: str, text: str) -> None: ...
    async def focus_window(self, window_title: str) -> None: ...
    async def wait_for_process(self, process_name: str, timeout: float = 10.0) -> None: ...
    async def wait_for_window_title(self, title: str, timeout: float = 10.0) -> None: ...
    async def wait_for_ui_element(self, element_id: str, timeout: float = 10.0) -> None: ...
    async def wait_for_text_in_window(self, window_title: str, text: str, timeout: float = 10.0) -> None: ...


class DesktopRuntimeBenchmark(Benchmark):
    """Benchmark: desktop runtime single-tool task (open_app + text response)."""

    name = "desktop_runtime_single_tool"

    def __init__(self) -> None:
        self._llm: _CountingLLM | None = None

    def setup(self) -> None:
        self._llm = _CountingLLM("open_app", {"app_name": "Notepad"})

    async def run(self) -> BenchmarkResult:
        assert self._llm is not None
        self._llm.calls = 0
        t0 = time.monotonic()
        runtime = DesktopRuntime(
            adapter=_DesktopAdapter(),  # type: ignore[arg-type]
            llm_provider=self._llm,
            reviewer=_InstantApproveReviewer(),  # type: ignore[arg-type]
        )
        task = TaskInput(task_id="bench-desktop", description="Open Notepad and type Hello World", domain="desktop")
        result = await runtime.execute(task)
        duration_ms = (time.monotonic() - t0) * 1000
        return BenchmarkResult(
            task_name=self.name,
            duration_ms=duration_ms,
            llm_calls=self._llm.calls,
            tool_calls=1,
            success=result.status == "success",
        )


# ---------------------------------------------------------------------------
# CLI benchmark
# ---------------------------------------------------------------------------

class _CLIAdapter:
    async def run_command(self, command: str, timeout: float = 30.0) -> tuple[int, str, str]:
        return 0, "output", ""
    async def read_output(self, process_id: str) -> str: return "output"
    async def wait_for_output_contains(self, process_id: str, text: str, timeout: float = 30.0) -> None: ...
    async def wait_for_process_exit(self, process_id: str, timeout: float = 30.0) -> int: return 0
    async def wait_for_file_condition(self, path: str, condition: str, timeout: float = 30.0) -> None: ...


class CLIRuntimeBenchmark(Benchmark):
    """Benchmark: CLI runtime single-tool task (run_command + text response)."""

    name = "cli_runtime_single_tool"

    def __init__(self) -> None:
        self._llm: _CountingLLM | None = None

    def setup(self) -> None:
        self._llm = _CountingLLM("run_command", {"command": "dir"})

    async def run(self) -> BenchmarkResult:
        assert self._llm is not None
        self._llm.calls = 0
        t0 = time.monotonic()
        runtime = CLIRuntime(
            adapter=_CLIAdapter(),  # type: ignore[arg-type]
            llm_provider=self._llm,
            reviewer=_InstantApproveReviewer(),  # type: ignore[arg-type]
        )
        task = TaskInput(task_id="bench-cli", description="Run dir command and wait for output", domain="cli")
        result = await runtime.execute(task)
        duration_ms = (time.monotonic() - t0) * 1000
        return BenchmarkResult(
            task_name=self.name,
            duration_ms=duration_ms,
            llm_calls=self._llm.calls,
            tool_calls=1,
            success=result.status == "success",
        )
