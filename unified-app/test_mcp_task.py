"""Test MCP task execution through backend router."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from orchestrator.backend_router import BackendRouter


async def test_cli_task():
    """Test CLI task via MCP."""
    print("Testing CLI task via MCP...")
    print(f"USE_CLI_MCP={os.getenv('USE_CLI_MCP')}")
    
    router = BackendRouter()
    
    try:
        result = await router.cli_task(
            description="echo 'Hello from MCP'",
            context=None
        )
        
        print(f"✓ CLI task completed")
        print(f"  Result: {result.get('result', '')[:200]}")
        print(f"  Steps: {result.get('steps_taken', 0)}")
        print(f"  Error: {result.get('error', 'None')}")
        
        await router.cleanup()
        return result.get('error') is None
    except Exception as e:
        print(f"✗ CLI task failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_browser_task():
    """Test Browser task via MCP."""
    print("\nTesting Browser task via MCP...")
    print(f"USE_BROWSER_MCP={os.getenv('USE_BROWSER_MCP')}")
    
    router = BackendRouter()
    
    try:
        result = await router.browser_task(
            description="navigate to example.com",
            context=None
        )
        
        print(f"✓ Browser task completed")
        print(f"  Result: {result.get('result', '')[:200]}")
        print(f"  Steps: {result.get('steps_taken', 0)}")
        print(f"  Error: {result.get('error', 'None')}")
        
        await router.cleanup()
        return result.get('error') is None
    except Exception as e:
        print(f"✗ Browser task failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run task tests."""
    print("="*60)
    print("MCP TASK EXECUTION TEST")
    print("="*60)
    
    results = []
    
    # Test CLI (fast)
    results.append(await test_cli_task())
    
    # Test Browser (slower, might fail if Playwright not ready)
    results.append(await test_browser_task())
    
    print("\n" + "="*60)
    if all(results):
        print("✓ ALL MCP TASKS WORKING")
    else:
        print("⚠ SOME TASKS FAILED (check errors above)")
        print("Note: Browser tasks may fail if Playwright not installed")


if __name__ == "__main__":
    asyncio.run(main())
