"""Direct test of MCP server tools without Windsurf integration."""
import asyncio
import json
import sys
from pathlib import Path

module_root = Path(__file__).resolve().parents[2]
if str(module_root) not in sys.path:
    sys.path.insert(0, str(module_root))

from mcp_server.orchestrator_mcp import OrchestratorMCPServer


async def test_mcp_tools():
    """Test all MCP tools directly."""
    print("=" * 60)
    print("Testing Orchestrator MCP Server")
    print("=" * 60)
    
    server = OrchestratorMCPServer()
    
    # Test 1: Submit a task
    print("\n1. Testing submit_task...")
    result = await server._submit_task({
        "description": "List all Python files in the current directory using CLI, then open the first result in a browser",
        "domain": "mixed"
    })
    print(result[0].text)
    
    # Extract task_id from result
    task_data = json.loads(result[0].text)
    task_id = task_data["task_id"]
    
    # Test 2: Get task status
    print("\n2. Testing get_task_status...")
    result = await server._get_task_status({"task_id": task_id})
    print(result[0].text)
    
    # Test 3: List tasks
    print("\n3. Testing list_tasks...")
    result = await server._list_tasks({"limit": 5})
    print(result[0].text)
    
    # Test 4: Get settings
    print("\n4. Testing get_settings...")
    result = await server._get_settings({})
    print(result[0].text)
    
    # Test 5: Update settings
    print("\n5. Testing update_settings...")
    result = await server._update_settings({
        "settings": {
            "test_setting": "test_value"
        }
    })
    print(result[0].text)
    
    # Test 6: List checkpoints (will be empty for simulated task)
    print("\n6. Testing list_checkpoints...")
    result = await server._list_checkpoints({"task_id": task_id})
    print(result[0].text)
    
    print("\n" + "=" * 60)
    print("All MCP tools tested successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_mcp_tools())
