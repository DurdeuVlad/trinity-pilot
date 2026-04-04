"""Test the simplest MCP-driven CLI task through the orchestrator."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.mcp_test_client import MCPTestClient


async def main():
    """Submit a minimal CLI task and print its terminal status."""
    client = MCPTestClient()

    try:
        await client.connect()
        print("Connected to MCP server\n")

        print("Submitting: 'echo Hello World'")
        result = await client.submit_task("echo Hello World", "cli")

        task_id = result.get("task_id")
        if not task_id:
            print(f"No task_id: {result}")
            return 1

        print(f"Task submitted: {task_id}\n")

        for i in range(30):
            await asyncio.sleep(1)
            status = await client.get_task_status(task_id)
            current_status = status.get("status") or status.get("state", "unknown")
            print(f"[{i + 1}s] Status: {current_status}")

            if current_status in ["completed", "failed", "error"]:
                print(f"\nTask finished: {current_status}")
                details = await client.get_task_details(task_id)
                print("\nTask details:")
                print(json.dumps(details, indent=2, default=str))
                return 0

        print("\nTask still running after 30 seconds")
        return 1

    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
