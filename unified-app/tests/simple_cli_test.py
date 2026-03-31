"""Test with simplest possible CLI command to isolate execution issue."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.mcp_test_client import MCPTestClient


async def main():
    """Test with echo command - simplest possible CLI task."""
    client = MCPTestClient()
    
    try:
        await client.connect()
        print("✅ Connected to MCP server\n")
        
        # Submit simplest possible CLI task
        print("Submitting: 'echo Hello World'")
        result = await client.submit_task("echo Hello World", "cli")
        
        task_id = result.get('task_id')
        if not task_id:
            print(f"❌ No task_id: {result}")
            return 1
        
        print(f"✅ Task submitted: {task_id}\n")
        
        # Monitor for 30 seconds
        for i in range(30):
            await asyncio.sleep(1)
            status = await client.get_task_status(task_id)
            current_status = status.get('status') or status.get('state', 'unknown')
            print(f"[{i+1}s] Status: {current_status}")
            
            if current_status in ['completed', 'failed', 'error']:
                print(f"\n✅ Task finished: {current_status}")
                details = await client.get_task_details(task_id)
                
                import json
                print("\nTask details:")
                print(json.dumps(details, indent=2, default=str))
                return 0
        
        print("\n⚠️ Task still running after 30 seconds")
        return 1
        
    finally:
        await client.disconnect()


if __name__ == "__main__":
    exit(asyncio.run(main()))
