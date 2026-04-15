"""Quick MCP connection test."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.mcp_backend_client import MCPBackendClient


async def test_cli_mcp():
    """Test CLI MCP server connection."""
    print("Testing CLI MCP server...")
    
    script_path = Path(__file__).parent.parent / "cli-automation-poc" / "cli_mcp_server.py"
    client = MCPBackendClient("cli", script_path)
    
    try:
        await client.connect()
        print("✓ Connected to CLI MCP server")
        
        result = await client.call_tool("health", {})
        print(f"✓ Health check: {result}")
        
        await client.disconnect()
        print("✓ Disconnected successfully")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_browser_mcp():
    """Test Browser MCP server connection."""
    print("\nTesting Browser MCP server...")
    
    script_path = Path(__file__).parent.parent / "browser-gui-automation" / "browser_mcp_server.py"
    client = MCPBackendClient("browser", script_path)
    
    try:
        await client.connect()
        print("✓ Connected to Browser MCP server")
        
        result = await client.call_tool("health", {})
        print(f"✓ Health check: {result}")
        
        await client.disconnect()
        print("✓ Disconnected successfully")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_desktop_mcp():
    """Test Desktop MCP server connection."""
    print("\nTesting Desktop MCP server...")
    
    script_path = Path(__file__).parent.parent / "api-accessibility-poc" / "desktop_mcp_server.py"
    client = MCPBackendClient("desktop", script_path)
    
    try:
        await client.connect()
        print("✓ Connected to Desktop MCP server")
        
        result = await client.call_tool("health", {})
        print(f"✓ Health check: {result}")
        
        await client.disconnect()
        print("✓ Disconnected successfully")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    results = []
    
    results.append(await test_cli_mcp())
    results.append(await test_browser_mcp())
    results.append(await test_desktop_mcp())
    
    print("\n" + "="*60)
    if all(results):
        print("✓ ALL MCP SERVERS WORKING")
    else:
        print("✗ SOME MCP SERVERS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
