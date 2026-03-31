"""
Integration tests for MCP test client using stdio protocol.

Tests verify that the MCP test client can properly communicate with the
orchestrator-control MCP server via stdio.
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mcp_server.mcp_test_client import MCPTestClient


@pytest.mark.asyncio
async def test_mcp_client_connection():
    """Test that MCP client can connect to server via stdio."""
    client = MCPTestClient()

    try:
        await client.connect()
        assert client.session is not None
        assert client.stdio is not None
        assert client.write is not None
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_submit_task_via_stdio():
    """Test task submission via stdio MCP protocol."""
    client = MCPTestClient()

    try:
        await client.connect()

        # Submit a simple CLI task
        result = await client.submit_task("echo Test", "cli")

        assert "task_id" in result

        # If unified-app is not running, task_id will be None with error status
        if result["task_id"] is None:
            assert result["status"] == "error"
            assert "error_code" in result
            pytest.skip("Unified-app not running - task submission failed as expected")
        else:
            assert result["task_id"].startswith("run_")
            assert result["status"] == "submitted"

    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_get_task_status_via_stdio():
    """Test getting task status via stdio MCP protocol."""
    client = MCPTestClient()

    try:
        await client.connect()

        # Submit task
        submit_result = await client.submit_task("echo Status Test", "cli")
        task_id = submit_result.get("task_id")

        if task_id is None:
            pytest.skip("Unified-app not running - cannot test task status")

        # Get status
        status = await client.get_task_status(task_id)

        assert "status" in status or "state" in status

    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_get_task_details_via_stdio():
    """Test getting full task details via stdio MCP protocol."""
    client = MCPTestClient()

    try:
        await client.connect()

        # Submit task
        submit_result = await client.submit_task("echo Details Test", "cli")
        task_id = submit_result.get("task_id")

        if task_id is None:
            pytest.skip("Unified-app not running - cannot test task details")

        # Wait a moment for task to process
        await asyncio.sleep(2)

        # Get details
        details = await client.get_task_details(task_id)

        assert "task" in details or "task_id" in details

    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_list_tasks_via_stdio():
    """Test listing tasks via stdio MCP protocol."""
    client = MCPTestClient()

    try:
        await client.connect()

        # Submit a task first
        await client.submit_task("echo List Test", "cli")

        # List tasks
        result = await client.list_tasks(limit=5)

        assert "tasks" in result
        assert isinstance(result["tasks"], list)
        assert len(result["tasks"]) > 0

    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_mcp_client_error_handling():
    """Test error handling when server not running."""
    client = MCPTestClient()

    # Try to use client without connecting
    with pytest.raises(RuntimeError, match="Not connected"):
        await client.submit_task("test", "cli")


@pytest.mark.asyncio
async def test_all_mcp_tools_via_stdio():
    """Test that all MCP tools work via stdio."""
    client = MCPTestClient()

    try:
        await client.connect()

        # 1. submit_task
        submit_result = await client.submit_task("echo All Tools Test", "cli")
        task_id = submit_result.get("task_id")

        if task_id is None:
            pytest.skip("Unified-app not running - cannot test all tools end-to-end")

        # 2. get_task_status
        status = await client.get_task_status(task_id)
        assert "status" in status or "state" in status

        # 3. get_task_details
        details = await client.get_task_details(task_id)
        assert "task" in details or "task_id" in details

        # 4. list_tasks
        tasks = await client.list_tasks(limit=1)
        assert "tasks" in tasks

        # 5. list_checkpoints
        checkpoints = await client.list_checkpoints(task_id)
        assert "checkpoints" in checkpoints or "checkpoint_count" in checkpoints

        # Note: get_checkpoint_details, get_settings, update_settings
        # require additional setup and are tested separately

    finally:
        await client.disconnect()
