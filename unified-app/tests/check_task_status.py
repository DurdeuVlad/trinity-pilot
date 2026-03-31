"""Check status of the HP-01 task that's still running."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.mcp_test_client import MCPTestClient


async def main():
    """Check task status."""
    client = MCPTestClient()
    
    try:
        await client.connect()
        
        # Get latest task
        tasks = await client.list_tasks(limit=5)
        print("Recent tasks:")
        for task in tasks.get('tasks', []):
            print(f"  {task.get('task_id')}: {task.get('description')} - {task.get('status')}")
        
        # Get details of first task
        if tasks.get('tasks'):
            task_id = tasks['tasks'][0].get('task_id')
            print(f"\nGetting details for {task_id}...")
            details = await client.get_task_details(task_id)
            
            import json
            print(json.dumps(details, indent=2, default=str))
            
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
