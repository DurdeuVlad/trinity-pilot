"""Test real task submission to orchestrator via MCP with event bus integration."""
import asyncio
import json
import sys
import time
from pathlib import Path

module_root = Path(__file__).resolve().parents[2]
if str(module_root) not in sys.path:
    sys.path.insert(0, str(module_root))

from mcp_server.orchestrator_mcp import OrchestratorMCPServer


async def test_real_submission():
    """Submit a real task via MCP to the running orchestrator."""
    print("=" * 70)
    print("MCP → ORCHESTRATOR REAL TASK SUBMISSION TEST")
    print("=" * 70)

    server = OrchestratorMCPServer()

    # Submit task via event bus
    task_description = "Open Notepad and type 'Hello from MCP'"

    print("\nSubmitting task via MCP event bus:")
    print(f"   {task_description}")
    print("\n" + "-" * 70)

    result = await server._submit_task({
        "description": task_description,
        "domain": "desktop"
    })

    print("\nTask submission result:")
    print(result[0].text)

    task_data = json.loads(result[0].text)
    task_id = task_data.get("task_id")

    if not task_id:
        print("\n❌ No task_id returned")
        return

    # Monitor execution
    print("\n" + "-" * 70)
    print("Monitoring task execution...")
    print("-" * 70)

    for i in range(30):  # Monitor for up to 60 seconds
        await asyncio.sleep(2)

        result = await server._get_task_status({"task_id": task_id})

        if "Task not found" in result[0].text:
            # Try getting from history
            tasks = await server._list_tasks({"limit": 5})
            print(f"\n[{i+1}] Recent tasks:")
            print(tasks[0].text)
            continue

        status_data = json.loads(result[0].text)
        status = status_data.get("status", "unknown")

        print(f"[{i+1}] Status: {status}")

        if status in ["completed", "failed", "cancelled"]:
            print(f"\nTask finished: {status}")

            # Get full details
            details_result = await server._get_task_details({"task_id": task_id})
            print("\nTask Details:")
            print(details_result[0].text)

            # Check checkpoints
            checkpoints_result = await server._list_checkpoints({"task_id": task_id})
            print("\nCheckpoints:")
            print(checkpoints_result[0].text)

            break

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    print("\nWARNING: Make sure the orchestrator GUI is running!")
    print("    (python main.py should be running in another terminal)\n")
    time.sleep(2)
    asyncio.run(test_real_submission())
