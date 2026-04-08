"""Benchmark framework for measuring trinity_core execution performance.

Provides a base ``Benchmark`` class, a ``BenchmarkResult`` dataclass, and a
``BenchmarkRunner`` that executes multiple iterations and computes statistics.
"""

from __future__ import annotations

import json
import statistics
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BenchmarkResult:
    """Metrics captured from one benchmark iteration."""

    task_name: str
    duration_ms: float
    llm_calls: int
    tool_calls: int
    success: bool
    metadata: dict[str, Any] = field(default_factory=dict)


class Benchmark(ABC):
    """Abstract base for a single benchmark scenario."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable benchmark name."""

    def setup(self) -> None:
        """Prepare the test environment.  Override if needed."""

    @abstractmethod
    async def run(self) -> BenchmarkResult:
        """Execute one benchmark iteration and return metrics."""

    def teardown(self) -> None:
        """Clean up after the benchmark.  Override if needed."""


class BenchmarkRunner:
    """Run a Benchmark N times, compute statistics, and optionally compare to baseline.

    Parameters
    ----------
    benchmark:
        The Benchmark instance to execute.
    iterations:
        Number of repetitions.  Defaults to 5.
    output_dir:
        Directory where JSON result files are written.  Defaults to ``.audit/benchmarks``.
    """

    def __init__(
        self,
        benchmark: Benchmark,
        iterations: int = 5,
        output_dir: str | Path = ".audit/benchmarks",
    ) -> None:
        self.benchmark = benchmark
        self.iterations = iterations
        self.output_dir = Path(output_dir)

    async def run(self, save: bool = True) -> dict[str, Any]:
        """Execute all iterations and return an aggregated report dict."""
        self.benchmark.setup()
        results: list[BenchmarkResult] = []
        try:
            for _ in range(self.iterations):
                result = await self.benchmark.run()
                results.append(result)
        finally:
            self.benchmark.teardown()

        report = self._aggregate(results)
        if save:
            self._save(report)
        return report

    def compare_to_baseline(self, report: dict[str, Any], baseline_path: str | Path) -> dict[str, Any]:
        """Compare *report* to a saved baseline.  Returns a comparison dict."""
        baseline_file = Path(baseline_path)
        if not baseline_file.exists():
            return {"error": f"Baseline not found: {baseline_file}"}
        with open(baseline_file, encoding="utf-8") as fh:
            baseline = json.load(fh)

        delta_duration = report["duration_ms"]["mean"] - baseline["duration_ms"]["mean"]
        delta_llm = report["llm_calls"]["mean"] - baseline["llm_calls"]["mean"]
        pct_duration = (delta_duration / baseline["duration_ms"]["mean"] * 100) if baseline["duration_ms"]["mean"] else 0
        pct_llm = (delta_llm / baseline["llm_calls"]["mean"] * 100) if baseline["llm_calls"]["mean"] else 0

        return {
            "benchmark": report["benchmark"],
            "baseline": baseline["benchmark"],
            "duration_ms_delta_pct": round(pct_duration, 2),
            "llm_calls_delta_pct": round(pct_llm, 2),
            "regression": delta_duration > baseline["duration_ms"]["mean"] * 0.1,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _aggregate(self, results: list[BenchmarkResult]) -> dict[str, Any]:
        durations = [r.duration_ms for r in results]
        llm_calls = [r.llm_calls for r in results]
        tool_calls = [r.tool_calls for r in results]
        success_count = sum(1 for r in results if r.success)

        def _stats(values: list[float]) -> dict[str, float]:
            if not values:
                return {}
            return {
                "mean": round(statistics.mean(values), 3),
                "median": round(statistics.median(values), 3),
                "stdev": round(statistics.stdev(values) if len(values) > 1 else 0.0, 3),
                "p95": round(sorted(values)[int(len(values) * 0.95)], 3),
                "p99": round(sorted(values)[int(len(values) * 0.99)], 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
            }

        return {
            "benchmark": self.benchmark.name,
            "iterations": len(results),
            "success_rate": success_count / len(results) if results else 0,
            "duration_ms": _stats(durations),
            "llm_calls": _stats([float(v) for v in llm_calls]),
            "tool_calls": _stats([float(v) for v in tool_calls]),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _save(self, report: dict[str, Any]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_{self.benchmark.name.replace(' ', '_')}.json"
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
