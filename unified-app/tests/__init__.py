"""Verify MCP server connection and submit test task."""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    """Verify MCP connection and submit test task."""
    from mcp_server.mcp_test_client import MCPTestClient

    client = MCPTestClient()
    
    try:
        print("Connecting to MCP server...")
        await client.connect()
        print("✅ Connected successfully")
        
        print("\nSubmitting test task...")
        result = await client.submit_task("echo MCP Connection Test", "cli")
        
        print(f"\n📋 Task submission result:")
        print(f"  Task ID: {result.get('task_id')}")
        print(f"  Status: {result.get('status')}")
        print(f"  Description: {result.get('description')}")
        
        if result.get('task_id'):
            print("\n✅ T01 PASS: Unified-app is running and MCP server is accessible")
            return 0
        else:
            print(f"\n⚠️ T01 SKIP: Task submission returned no task_id")
            print(f"  Error: {result.get('error_code', 'unknown')}")
            print(f"  Message: {result.get('message', 'No message')}")
            return 1
            
    except Exception as e:
        print(f"\n❌ T01 FAIL: Error connecting to MCP server: {e}")
        return 2
    finally:
        await client.disconnect()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
