"""
MCP Client for Automated Testing

Provides a Python client interface to the orchestrator-control MCP server.
Used by automated test runners to submit tasks and monitor execution.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, List


class MCPClient:
    """Client for orchestrator-control MCP server"""
    
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.connected = False
        
    async def connect(self):
        """Start MCP server process and establish connection"""
        if self.connected:
            return
        
        # Get MCP server path
        mcp_server_path = Path(__file__).parent / "orchestrator_mcp.py"
        
        if not mcp_server_path.exists():
            raise FileNotFoundError(f"MCP server not found: {mcp_server_path}")
        
        # Start MCP server process
        # Note: In production, this would use the actual MCP protocol
        # For now, we'll use direct imports
        self.connected = True
    
    async def disconnect(self):
        """Disconnect from MCP server"""
        if self.process:
            self.process.terminate()
            self.process.wait()
        
        self.connected = False
    
    async def submit_task(self, description: str, domain: str) -> Dict:
        """
        Submit a task to the orchestrator.
        
        Args:
            description: Task description
            domain: Task domain (cli, browser, desktop, mixed)
        
        Returns:
            Dictionary with task_id and status
        """
        if not self.connected:
            raise RuntimeError("MCP client not connected")
        
        # Import the MCP server module directly
        # In production, this would use MCP protocol over stdio
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from mcp_server import orchestrator_mcp
            
            # Call submit_task tool
            result = await orchestrator_mcp.submit_task(description, domain)
            
            return result
            
        except Exception as e:
            return {
                "error": str(e),
                "task_id": None
            }
    
    async def get_task_status(self, task_id: str) -> Dict:
        """
        Get current status of a task.
        
        Args:
            task_id: Task identifier
        
        Returns:
            Dictionary with task status
        """
        if not self.connected:
            raise RuntimeError("MCP client not connected")
        
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from mcp_server import orchestrator_mcp
            
            result = await orchestrator_mcp.get_task_status(task_id)
            
            return result
            
        except Exception as e:
            return {
                "error": str(e),
                "state": "unknown"
            }
    
    async def get_task_details(self, task_id: str) -> Dict:
        """
        Get full details of a task including all steps.
        
        Args:
            task_id: Task identifier
        
        Returns:
            Dictionary with complete task information
        """
        if not self.connected:
            raise RuntimeError("MCP client not connected")
        
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from mcp_server import orchestrator_mcp
            
            result = await orchestrator_mcp.get_task_details(task_id)
            
            return result
            
        except Exception as e:
            return {
                "error": str(e),
                "task_id": task_id
            }
    
    async def list_tasks(self, limit: int = 10) -> List[Dict]:
        """
        List recent tasks from history.
        
        Args:
            limit: Maximum number of tasks to return
        
        Returns:
            List of task dictionaries
        """
        if not self.connected:
            raise RuntimeError("MCP client not connected")
        
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from mcp_server import orchestrator_mcp
            
            result = await orchestrator_mcp.list_tasks(limit)
            
            return result
            
        except Exception as e:
            return []
    
    async def list_checkpoints(self, task_id: str) -> List[Dict]:
        """
        List all checkpoints for a task.
        
        Args:
            task_id: Task identifier
        
        Returns:
            List of checkpoint dictionaries
        """
        if not self.connected:
            raise RuntimeError("MCP client not connected")
        
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from mcp_server import orchestrator_mcp
            
            result = await orchestrator_mcp.list_checkpoints(task_id)
            
            return result
            
        except Exception as e:
            return []


async def test_client():
    """Test the MCP client"""
    client = MCPClient()
    
    print("Connecting to MCP server...")
    await client.connect()
    
    print("Submitting test task...")
    result = await client.submit_task(
        description="Run echo Hello World in the terminal",
        domain="cli"
    )
    
    print(f"Task submitted: {result}")
    
    if result.get("task_id"):
        task_id = result["task_id"]
        
        # Monitor task
        print("Monitoring task execution...")
        while True:
            status = await client.get_task_status(task_id)
            print(f"Status: {status.get('state')}")
            
            if status.get("state") in ["completed", "failed", "cancelled"]:
                break
            
            await asyncio.sleep(1)
        
        # Get final details
        details = await client.get_task_details(task_id)
        print(f"Task details: {details}")
    
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(test_client())
