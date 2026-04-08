"""Unit tests for trinity_core.benchmarks framework and runtime benchmarks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trinity_core.benchmarks.benchmark_framework import (
    Benchmark,
    BenchmarkResult,
    BenchmarkRunner,
)
from trinity_core.benchmarks.runtime_benchmarks import (
    BrowserRuntimeBenchmark,
    CLIRuntimeBenchmark,
    DesktopRuntimeBenchmark,
)


# Minimal concrete benchmark for testing the framework alone
class _SumBenchmark(Benchmark):
    name = "sum_test"

    def __init__(self, succeed: bool = True) -> None:
        self.runs = 0
        self._succeed = succeed

    async def run(self) -> BenchmarkResult:
        self.runs += 1
        return BenchmarkResult(
            task_name=self.name,
            duration_ms=float(self.runs * 10),
            llm_calls=2,
            tool_calls=1,
            success=self._succeed,
        )


class TestBenchmarkRunner:
    @pytest.mark.asyncio
    async def test_runs_correct_iterations(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bench = _SumBenchmark()
        runner = BenchmarkRunner(bench, iterations=3, output_dir=tmp_path / "benchmarks")
        report = await runner.run(save=False)
        assert bench.runs == 3
        assert report["iterations"] == 3

    @pytest.mark.asyncio
    async def test_report_contains_expected_keys(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = BenchmarkRunner(_SumBenchmark(), iterations=3, output_dir=tmp_path / "benchmarks")
        report = await runner.run(save=False)
        for key in ("benchmark", "iterations", "success_rate", "duration_ms", "llm_calls", "tool_calls"):
            assert key in report

    @pytest.mark.asyncio
    async def test_success_rate_calculation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = BenchmarkRunner(_SumBenchmark(succeed=False), iterations=4, output_dir=tmp_path / "benchmarks")
        report = await runner.run(save=False)
        assert report["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_save_writes_json_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "benchmarks"
        runner = BenchmarkRunner(_SumBenchmark(), iterations=2, output_dir=out_dir)
        await runner.run(save=True)
        files = list(out_dir.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["benchmark"] == "sum_test"

    def test_compare_no_baseline(self, tmp_path):
        runner = BenchmarkRunner(_SumBenchmark(), output_dir=tmp_path)
        result = runner.compare_to_baseline({"benchmark": "x", "duration_ms": {"mean": 10}, "llm_calls": {"mean": 1}}, tmp_path / "missing.json")
        assert "error" in result


class TestRuntimeBenchmarks:
    @pytest.mark.asyncio
    async def test_browser_benchmark_runs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bench = BrowserRuntimeBenchmark()
        bench.setup()
        result = await bench.run()
        assert result.task_name == "browser_runtime_single_tool"
        assert result.success is True
        assert result.llm_calls > 0
        bench.teardown()

    @pytest.mark.asyncio
    async def test_desktop_benchmark_runs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bench = DesktopRuntimeBenchmark()
        bench.setup()
        result = await bench.run()
        assert result.task_name == "desktop_runtime_single_tool"
        assert result.success is True
        bench.teardown()

    @pytest.mark.asyncio
    async def test_cli_benchmark_runs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bench = CLIRuntimeBenchmark()
        bench.setup()
        result = await bench.run()
        assert result.task_name == "cli_runtime_single_tool"
        assert result.success is True
        bench.teardown()
