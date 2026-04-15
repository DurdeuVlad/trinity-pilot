"""Simple MCP task test with proper lifecycle."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from orchestrator.mcp_backend_client import MCPBackendClient


async def test_cli_task():
    """Test CLI task via MCP with proper lifecycle."""
    print("="*60)
    print("Testing CLI task via MCP")
    print("="*60)
    
    script_path = Path(__file__).parent.parent / "cli-automation-poc" / "cli_mcp_server.py"
    client = MCPBackendClient("cli", script_path)
    
    try:
        print("1. Connecting to CLI MCP server...")
        await client.connect()
        print("   ✓ Connected")
        
        print("2. Executing task: echo 'Hello from MCP'")
        result = await client.execute_task(
            objective="echo 'Hello from MCP'",
            timeout=30
        )
        
        print(f"   ✓ Task completed")
        print(f"   Raw result: {result}")
        if result:
            print(f"   Result: {result.get('result', '')[:100] if result.get('result') else 'None'}")
            print(f"   Status: {result.get('status')}")
            print(f"   Error: {result.get('error', 'None')}")
        else:
            print(f"   ✗ Result is None!")
        
        return result.get('error') is None
        
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        print("3. Disconnecting...")
        try:
            await client.disconnect()
            print("   ✓ Disconnected")
        except Exception as e:
            print(f"   ⚠ Disconnect error (non-fatal): {e}")


async def main():
    """Run test."""
    success = await test_cli_task()
    
    print("\n" + "="*60)
    if success:
        print("✓ MCP TASK EXECUTION WORKING")
        print("\nNext step: Test in unified app GUI")
    else:
        print("✗ MCP TASK EXECUTION FAILED")
        print("\nNeed to fix errors before proceeding")


if __name__ == "__main__":
    asyncio.run(main())
