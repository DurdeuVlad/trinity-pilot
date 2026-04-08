"""Demo script to generate observability data for audit-debugger."""

import asyncio
from models import TaskInput
from orchestrators.browser_runtime import BrowserRuntime
from llm.llm_provider import LLMResponse, ToolCall


class DemoLLM:
    """Demo LLM that returns a single tool call then text."""
    def __init__(self):
        self.call_count = 0
    
    async def call(self, messages, tools):
        self.call_count += 1
        if self.call_count == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="navigate", arguments={"url": "https://example.com"})])
        return LLMResponse(text="Navigation complete")


class DemoAdapter:
    """Demo browser adapter."""
    async def navigate(self, url: str) -> None:
        print(f"[Demo] Navigating to {url}")
    
    async def click(self, selector: str) -> None:
        pass
    
    async def type_text(self, selector: str, text: str) -> None:
        pass
    
    async def extract_text(self, selector: str) -> str:
        return "demo text"
    
    async def screenshot(self) -> bytes:
        return b""
    
    async def wait_for_selector(self, selector: str, timeout: float = 10.0, state: str = "visible") -> None:
        pass
    
    async def wait_for_load_state(self, wait_until: str = "load", timeout: float = 30.0) -> None:
        pass
    
    async def get_current_url(self) -> str:
        return "https://example.com"


class DemoReviewer:
    """Demo reviewer that always approves."""
    async def review(self, objective, definition_of_done, execution_log):
        from orchestrators.review_types import ReviewResult
        return ReviewResult(approved=True, feedback="Demo approval")


async def main():
    print("=" * 60)
    print("Generating Observability Data")
    print("=" * 60)
    
    # Create runtime with demo components
    runtime = BrowserRuntime(
        adapter=DemoAdapter(),  # type: ignore
        llm_provider=DemoLLM(),  # type: ignore
        reviewer=DemoReviewer(),  # type: ignore
    )
    
    # Execute 3 demo tasks
    tasks = [
        TaskInput(task_id="demo-1", description="Navigate to example.com", domain="web"),
        TaskInput(task_id="demo-2", description="Search for Python tutorials", domain="web"),
        TaskInput(task_id="demo-3", description="Extract page title", domain="web"),
    ]
    
    for task in tasks:
        print(f"\n[Demo] Executing task: {task.description}")
        result = await runtime.execute(task)
        print(f"[Demo] Result: {result.status}")
    
    print("\n" + "=" * 60)
    print("Data Generation Complete!")
    print("=" * 60)
    print("\nGenerated files:")
    print("  - .logs/2026-04-07.jsonl (structured logs)")
    print("  - .metrics/2026-04-07.jsonl (metrics data)")
    print("\nView with audit-debugger:")
    print("  cd audit-debugger")
    print("  python src/audit_debugger/log_analyzer.py --log-dir ../trinity_core/.logs")
    print("  python src/audit_debugger/metrics_dashboard.py --metrics-dir ../trinity_core/.metrics")
    print()


if __name__ == "__main__":
    asyncio.run(main())
