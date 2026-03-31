"""Submit a real task to the orchestrator via MCP and monitor it."""
import asyncio
import json
import sys
import time
from pathlib import Path

module_root = Path(__file__).resolve().parents[2]
if str(module_root) not in sys.path:
    sys.path.insert(0, str(module_root))

from mcp_server.orchestrator_mcp import OrchestratorMCPServer


async def submit_and_monitor_task():
    """Submit a multi-module task and monitor execution."""
    print("=" * 70)
    print("REAL ORCHESTRATOR TASK SUBMISSION VIA MCP")
    print("=" * 70)

    server = OrchestratorMCPServer()

    # Submit a multi-module task
    task_description = """
    Use CLI to list all Python files in the current directory,
    then use browser to open google.com and search for 'Python testing',
    then use desktop to open Notepad
    """

    print("\nSubmitting task:")
    print(f"   {task_description.strip()}")
    print("\n" + "-" * 70)

    result = await server._submit_task({
        "description": task_description,
        "domain": "mixed"
    })

    task_data = json.loads(result[0].text)
    task_id = task_data.get("task_id")

    print(f"\nTask submitted: {task_id}")
    print(f"   Status: {task_data['status']}")

    # Monitor task status
    print("\n" + "-" * 70)
    print("Monitoring task status...")
    print("-" * 70)

    for i in range(10):  # Monitor for up to 10 iterations
        await asyncio.sleep(2)  # Wait 2 seconds between checks

        if not task_id:
            print(f"[{i+1}] No task_id returned; stopping monitor loop.")
            break

        result = await server._get_task_status({"task_id": task_id})
        try:
            status_data = json.loads(result[0].text)
        except json.JSONDecodeError:
            print(f"[{i+1}] Non-JSON status response: {result[0].text}")
            continue

        print(f"\n[{i+1}] Status: {status_data.get('status', 'unknown')}")

        if status_data.get('status') in ['completed', 'failed', 'cancelled']:
            print(f"\nTask finished with status: {status_data['status']}")
            break

    # Get final task details
    print("\n" + "-" * 70)
    print("Final Task Details:")
    print("-" * 70)

    if task_id:
        result = await server._get_task_details({"task_id": task_id})
        details = json.loads(result[0].text)
    else:
        details = {"message": "No task_id available; no details to fetch."}

    print(json.dumps(details, indent=2))

    # Check for checkpoints
    print("\n" + "-" * 70)
    print("Checkpoints:")
    print("-" * 70)

    if task_id:
        result = await server._list_checkpoints({"task_id": task_id})
        checkpoints = json.loads(result[0].text)
    else:
        checkpoints = {"checkpoint_count": 0, "checkpoints": []}

    print(json.dumps(checkpoints, indent=2))

    if checkpoints['checkpoint_count'] > 0:
        # Inspect first checkpoint
        checkpoint_id = checkpoints['checkpoints'][0]['checkpoint_id']
        result = await server._get_checkpoint_details({"checkpoint_id": checkpoint_id})
        checkpoint_details = json.loads(result[0].text)

        print("\nFirst Checkpoint Details:")
        print(json.dumps(checkpoint_details, indent=2))

    print("\n" + "=" * 70)
    print("MCP TASK SUBMISSION AND MONITORING COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(submit_and_monitor_task())
