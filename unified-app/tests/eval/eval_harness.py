"""Evaluation harness for Epic 9 - Sharp Tools.

Runs eval tasks and detects false completions.
"""

import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from eval_tasks import ALL_TASKS, EvalTask


class EvalResult:
    """Result of a single eval task execution."""
    
    def __init__(self, task: EvalTask):
        self.task = task
        self.success: bool = False
        self.false_completion_detected: bool = False
        self.error_code: str | None = None
        self.actual_outcome: str = ""
        self.execution_time_seconds: float = 0.0
        self.tool_calls: list[dict[str, Any]] = []
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task.task_id,
            "category": self.task.category,
            "description": self.task.description,
            "expected_outcome": self.task.expected_outcome,
            "should_succeed": self.task.should_succeed,
            "success": self.success,
            "false_completion_detected": self.false_completion_detected,
            "error_code": self.error_code,
            "actual_outcome": self.actual_outcome,
            "execution_time_seconds": self.execution_time_seconds,
            "tool_call_count": len(self.tool_calls),
        }


class EvalHarness:
    """Harness for running evaluation tasks."""
    
    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or Path("_runtime/eval_results")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[EvalResult] = []
    
    async def run_task(self, task: EvalTask) -> EvalResult:
        """
        Run a single eval task.
        
        This is a stub implementation. In a real scenario, this would:
        1. Submit the task to the orchestrator
        2. Monitor execution
        3. Collect tool calls and results
        4. Detect false completions
        """
        result = EvalResult(task)
        
        # Stub: simulate task execution
        # In real implementation, call orchestrator.execute_task(task.description)
        result.success = task.should_succeed
        result.actual_outcome = task.expected_outcome if task.should_succeed else "Task failed as expected"
        result.execution_time_seconds = 1.0
        
        # Detect false completions
        result.false_completion_detected = self._detect_false_completion(task, result)
        
        return result
    
    def _detect_false_completion(self, task: EvalTask, result: EvalResult) -> bool:
        """
        Detect if the task reported success but actually failed.
        
        Checks:
        1. Task reported success but should_succeed=False
        2. Actual outcome contains false completion indicators
        3. Error code indicates failure but status is success
        """
        # Check 1: Success when should fail
        if result.success and not task.should_succeed:
            return True
        
        # Check 2: False completion indicators in outcome
        outcome_lower = result.actual_outcome.lower()
        for indicator in task.false_completion_indicators:
            if indicator.lower() in outcome_lower:
                return True
        
        # Check 3: Error code but success status
        if result.success and result.error_code and result.error_code != "NONE":
            return True
        
        return False
    
    async def run_all(self, tasks: list[EvalTask] | None = None) -> dict[str, Any]:
        """
        Run all evaluation tasks and generate report.
        
        Args:
            tasks: List of tasks to run (defaults to ALL_TASKS)
        
        Returns:
            Summary statistics dictionary
        """
        tasks = tasks or ALL_TASKS
        
        print(f"Running {len(tasks)} evaluation tasks...")
        
        for i, task in enumerate(tasks, 1):
            print(f"[{i}/{len(tasks)}] Running {task.task_id}: {task.description[:50]}...")
            result = await self.run_task(task)
            self.results.append(result)
        
        # Generate summary
        summary = self._generate_summary()
        
        # Save results
        self._save_results(summary)
        
        return summary
    
    def _generate_summary(self) -> dict[str, Any]:
        """Generate summary statistics from results."""
        total = len(self.results)
        
        # Overall stats
        successful = sum(1 for r in self.results if r.success)
        false_completions = sum(1 for r in self.results if r.false_completion_detected)
        
        # By category
        by_category = {}
        for result in self.results:
            cat = result.task.category
            if cat not in by_category:
                by_category[cat] = {
                    "total": 0,
                    "successful": 0,
                    "false_completions": 0,
                }
            by_category[cat]["total"] += 1
            if result.success:
                by_category[cat]["successful"] += 1
            if result.false_completion_detected:
                by_category[cat]["false_completions"] += 1
        
        # Expected vs actual
        should_succeed_count = sum(1 for r in self.results if r.task.should_succeed)
        should_fail_count = total - should_succeed_count
        
        correctly_succeeded = sum(
            1 for r in self.results
            if r.task.should_succeed and r.success and not r.false_completion_detected
        )
        correctly_failed = sum(
            1 for r in self.results
            if not r.task.should_succeed and not r.success
        )
        
        accuracy = (correctly_succeeded + correctly_failed) / total if total > 0 else 0.0
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_tasks": total,
            "successful": successful,
            "failed": total - successful,
            "false_completions": false_completions,
            "accuracy": accuracy,
            "should_succeed_count": should_succeed_count,
            "should_fail_count": should_fail_count,
            "correctly_succeeded": correctly_succeeded,
            "correctly_failed": correctly_failed,
            "by_category": by_category,
        }
    
    def _save_results(self, summary: dict[str, Any]) -> None:
        """Save results to JSON files."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save detailed results
        detailed_path = self.output_dir / f"eval_results_{timestamp}.json"
        with open(detailed_path, "w") as f:
            json.dump({
                "summary": summary,
                "results": [r.to_dict() for r in self.results],
            }, f, indent=2)
        
        print(f"\nResults saved to: {detailed_path}")
        
        # Save summary only
        summary_path = self.output_dir / f"eval_summary_{timestamp}.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        
        print(f"Summary saved to: {summary_path}")
    
    def print_summary(self, summary: dict[str, Any]) -> None:
        """Print summary to console."""
        print("\n" + "=" * 60)
        print("EVALUATION SUMMARY")
        print("=" * 60)
        print(f"Total tasks: {summary['total_tasks']}")
        print(f"Successful: {summary['successful']}")
        print(f"Failed: {summary['failed']}")
        print(f"False completions detected: {summary['false_completions']}")
        print(f"Accuracy: {summary['accuracy']:.1%}")
        print()
        print(f"Should succeed: {summary['should_succeed_count']}")
        print(f"  Correctly succeeded: {summary['correctly_succeeded']}")
        print(f"Should fail: {summary['should_fail_count']}")
        print(f"  Correctly failed: {summary['correctly_failed']}")
        print()
        print("By category:")
        for cat, stats in summary['by_category'].items():
            print(f"  {cat}:")
            print(f"    Total: {stats['total']}")
            print(f"    Successful: {stats['successful']}")
            print(f"    False completions: {stats['false_completions']}")
        print("=" * 60)


async def main():
    """Run the evaluation harness."""
    harness = EvalHarness()
    summary = await harness.run_all()
    harness.print_summary(summary)


if __name__ == "__main__":
    asyncio.run(main())
