"""Debug task submission to see why task_id is None."""
import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.mcp_test_client import MCPTestClient


async def main():
    """Debug task submission."""
    client = MCPTestClient()
    
    try:
        await client.connect()
        print("✅ Connected to MCP server\n")
        
        # Submit simple CLI task
        print("Submitting task: 'echo Test'")
        result = await client.submit_task("echo Test", "cli")
        
        print("\n📋 Full submission result:")
        print(json.dumps(result, indent=2))
        
        # Check what we got
        if result.get('task_id'):
            print(f"\n✅ Got task_id: {result['task_id']}")
            
            # Wait a moment
            await asyncio.sleep(2)
            
            # Try to get status
            print("\nGetting task status...")
            status = await client.get_task_status(result['task_id'])
            print(json.dumps(status, indent=2))
        else:
            print(f"\n⚠️ No task_id in response")
            print(f"Status: {result.get('status')}")
            print(f"Error code: {result.get('error_code')}")
            print(f"Message: {result.get('message')}")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
