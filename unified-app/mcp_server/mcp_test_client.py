"""
MCP Test Client - stdio-based client for testing orchestrator-control MCP server.

This is a separate test client that uses proper stdio protocol to communicate
with the MCP server, designed for use by automated test suites.

Usage:
    client = MCPTestClient()
    await client.connect()
    result = await client.submit_task("echo Hello World", "cli")
    await client.disconnect()
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPTestClient:
    """
    Test client for orchestrator-control MCP server using stdio protocol.
    
    This client is designed for automated testing and does NOT modify the
    existing mcp_client.py which may be used by other parts of the system.
    """
    
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.stdio = None
        self.write = None
    
    async def connect(self):
        """
        Connect to the orchestrator-control MCP server via stdio.
        
        Launches the MCP server as a subprocess and establishes stdio communication.
        """
        # Path to MCP server script
        server_script = Path(__file__).parent / "orchestrator_mcp.py"
        
        if not server_script.exists():
            raise FileNotFoundError(f"MCP server script not found: {server_script}")
        
        # Configure stdio server parameters
        server_params = StdioServerParameters(
            command="python",
            args=[str(server_script)],
            env=None
        )
        
        # Establish stdio transport
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        
        # Create client session
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )
        
        # Initialize session
        await self.session.initialize()
        
        # Verify tools are available
        response = await self.session.list_tools()
        tools = response.tools
        print(f"Connected to MCP server with {len(tools)} tools: {[t.name for t in tools]}")
    
    async def disconnect(self):
        """Clean up resources and close connection."""
        await self.exit_stack.aclose()
    
    async def submit_task(self, description: str, domain: str) -> Dict[str, Any]:
        """
        Submit a task to the orchestrator via MCP server.
        
        Args:
            description: Task description
            domain: Task domain (cli, browser, desktop, mixed)
        
        Returns:
            Task submission result with task_id
        """
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self.session.call_tool(
            "submit_task",
            {"description": description, "domain": domain}
        )
        
        # Parse result content
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return json.loads(content.text)
        
        raise RuntimeError(f"Unexpected result format: {result}")
    
    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get task execution status.
        
        Args:
            task_id: Task ID from submit_task
        
        Returns:
            Task status information
        """
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self.session.call_tool(
            "get_task_status",
            {"task_id": task_id}
        )
        
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return json.loads(content.text)
        
        raise RuntimeError(f"Unexpected result format: {result}")
    
    async def get_task_details(self, task_id: str) -> Dict[str, Any]:
        """
        Get full task details including all steps.
        
        Args:
            task_id: Task ID from submit_task
        
        Returns:
            Complete task information
        """
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self.session.call_tool(
            "get_task_details",
            {"task_id": task_id}
        )
        
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return json.loads(content.text)
        
        raise RuntimeError(f"Unexpected result format: {result}")
    
    async def list_tasks(self, limit: int = 10) -> Dict[str, Any]:
        """
        List recent tasks from history.
        
        Args:
            limit: Maximum number of tasks to return
        
        Returns:
            List of tasks
        """
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self.session.call_tool(
            "list_tasks",
            {"limit": limit}
        )
        
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return json.loads(content.text)
        
        raise RuntimeError(f"Unexpected result format: {result}")
    
    async def list_checkpoints(self, task_id: str) -> Dict[str, Any]:
        """
        List checkpoints for a task.
        
        Args:
            task_id: Task ID from submit_task
        
        Returns:
            List of checkpoints
        """
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self.session.call_tool(
            "list_checkpoints",
            {"task_id": task_id}
        )
        
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return json.loads(content.text)
        
        raise RuntimeError(f"Unexpected result format: {result}")


async def main():
    """Example usage of MCP test client."""
    client = MCPTestClient()
    
    try:
        # Connect to MCP server
        print("Connecting to MCP server...")
        await client.connect()
        
        # Submit a test task
        print("\nSubmitting test task...")
        result = await client.submit_task("echo Hello World", "cli")
        print(f"Task submitted: {result}")
        
        task_id = result.get("task_id")
        if task_id:
            # Monitor task status
            print(f"\nMonitoring task {task_id}...")
            for i in range(10):
                status = await client.get_task_status(task_id)
                print(f"Status: {status.get('state')}")
                
                if status.get("state") in ["completed", "failed"]:
                    break
                
                await asyncio.sleep(1)
            
            # Get full task details
            print("\nGetting task details...")
            details = await client.get_task_details(task_id)
            print(f"Task details: {json.dumps(details, indent=2)}")
    
    finally:
        # Clean up
        print("\nDisconnecting...")
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
