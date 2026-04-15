"""
Backend MCP Server Conformance Test Suite.

This suite verifies that all backend MCP servers (CLI, Browser, Desktop)
implement the frozen backend MCP contract correctly.

Run this suite against each backend to verify contract compliance.
"""
import asyncio
import json
import sys
from pathlib import Path
from contextlib import AsyncExitStack
from typing import Any, Dict

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class BackendMCPTestClient:
    """Test client for backend MCP servers using real stdio protocol."""

    def __init__(self, server_script: Path):
        self.server_script = server_script
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()
        self.stdio = None
        self.write = None

    async def connect(self):
        """Connect to backend MCP server via stdio."""
        if not self.server_script.exists():
            raise FileNotFoundError(f"MCP server script not found: {self.server_script}")
        
        server_params = StdioServerParameters(
            command="python",
            args=[str(self.server_script)],
            env=None,
        )
        
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )
        
        await self.session.initialize()

    async def disconnect(self):
        """Clean up resources and close connection."""
        await self.exit_stack.aclose()

    async def call_tool(self, name: str, arguments: dict | None = None) -> Dict[str, Any]:
        """Call an MCP tool and return parsed JSON response."""
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self.session.call_tool(name, arguments or {})
        
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, "text"):
                return json.loads(content.text)
        
        raise RuntimeError(f"Unexpected result format: {result}")


@pytest_asyncio.fixture(params=["cli", "browser", "desktop"])
async def backend_client(request):
    """Fixture providing connected backend MCP client for each backend."""
    backend = request.param
    
    # Map backend to server script
    server_scripts = {
        "cli": Path(__file__).parent.parent.parent / "cli-automation-poc" / "cli_mcp_server.py",
        "browser": Path(__file__).parent.parent.parent / "browser-gui-automation" / "browser_mcp_server.py",
        "desktop": Path(__file__).parent.parent.parent / "api-accessibility-poc" / "desktop_mcp_server.py",
    }
    
    server_script = server_scripts[backend]
    
    if not server_script.exists():
        pytest.skip(f"Backend {backend} server not found at {server_script}")
    
    client = BackendMCPTestClient(server_script)
    await client.connect()
    
    # Store backend ID for assertions
    client.backend_id = backend
    
    yield client
    
    try:
        await client.disconnect()
    except RuntimeError as e:
        if "cancel scope" not in str(e):
            raise


# ============================================================================
# CONFORMANCE TEST: Required MCP Tools
# ============================================================================

@pytest.mark.asyncio
async def test_required_tools_exist(backend_client):
    """Verify all 10 required MCP tools exist."""
    tools = await backend_client.session.list_tools()
    tool_names = [t.name for t in tools.tools]
    
    required_tools = [
        "health",
        "list_capabilities",
        "create_session",
        "run_objective",
        "read_events",
        "get_status",
        "interrupt",
        "terminate",
        "close_session",
        "list_artifacts",
    ]
    
    for tool in required_tools:
        assert tool in tool_names, f"Required tool {tool} not found in {backend_client.backend_id} backend"


# ============================================================================
# CONFORMANCE TEST: Response Envelope Keys
# ============================================================================

@pytest.mark.asyncio
async def test_health_response_envelope(backend_client):
    """Verify health response contains all 8 required envelope keys."""
    result = await backend_client.call_tool("health")
    
    required_keys = ["ok", "status", "session_id", "result", "error", "events", "artifacts", "metadata"]
    
    for key in required_keys:
        assert key in result, f"Required envelope key '{key}' missing in {backend_client.backend_id} health response"


@pytest.mark.asyncio
async def test_list_capabilities_response_envelope(backend_client):
    """Verify list_capabilities response contains all 8 required envelope keys."""
    result = await backend_client.call_tool("list_capabilities")
    
    required_keys = ["ok", "status", "session_id", "result", "error", "events", "artifacts", "metadata"]
    
    for key in required_keys:
        assert key in result, f"Required envelope key '{key}' missing in {backend_client.backend_id} list_capabilities response"


@pytest.mark.asyncio
async def test_create_session_response_envelope(backend_client):
    """Verify create_session response contains all 8 required envelope keys."""
    result = await backend_client.call_tool("create_session")
    
    required_keys = ["ok", "status", "session_id", "result", "error", "events", "artifacts", "metadata"]
    
    for key in required_keys:
        assert key in result, f"Required envelope key '{key}' missing in {backend_client.backend_id} create_session response"
    
    # Cleanup
    if result.get("session_id"):
        await backend_client.call_tool("close_session", {"session_id": result["session_id"]})


# ============================================================================
# CONFORMANCE TEST: Frozen Statuses
# ============================================================================

@pytest.mark.asyncio
async def test_session_status_values(backend_client):
    """Verify session status values match frozen statuses."""
    frozen_statuses = ["created", "running", "completed", "failed", "interrupted", "terminated"]
    
    # Create session
    create_result = await backend_client.call_tool("create_session")
    session_id = create_result["session_id"]
    
    # Check created status
    assert create_result["status"] == "created", f"Initial status should be 'created' in {backend_client.backend_id}"
    
    # Get status
    status_result = await backend_client.call_tool("get_status", {"session_id": session_id})
    assert status_result["status"] in frozen_statuses, f"Status '{status_result['status']}' not in frozen statuses for {backend_client.backend_id}"
    
    # Cleanup
    await backend_client.call_tool("close_session", {"session_id": session_id})


# ============================================================================
# CONFORMANCE TEST: Frozen Event Types
# ============================================================================

@pytest.mark.asyncio
async def test_event_types(backend_client):
    """Verify event types match frozen event types."""
    frozen_event_types = [
        "session_created",
        "objective_started",
        "action_started",
        "action_completed",
        "action_failed",
        "retry_scheduled",
        "objective_completed",
        "objective_failed",
        "session_interrupted",
        "session_terminated",
    ]
    
    # Create session
    create_result = await backend_client.call_tool("create_session")
    session_id = create_result["session_id"]
    
    # Read events
    events_result = await backend_client.call_tool("read_events", {"session_id": session_id})
    
    assert events_result["ok"] is True
    assert "events" in events_result
    assert len(events_result["events"]) > 0, f"No events emitted for {backend_client.backend_id}"
    
    # Verify session_created event exists
    event_types = [e["event_type"] for e in events_result["events"]]
    assert "session_created" in event_types, f"session_created event not found in {backend_client.backend_id}"
    
    # Verify all event types are in frozen set
    for event in events_result["events"]:
        assert event["event_type"] in frozen_event_types, f"Event type '{event['event_type']}' not in frozen event types for {backend_client.backend_id}"
    
    # Cleanup
    await backend_client.call_tool("close_session", {"session_id": session_id})


# ============================================================================
# CONFORMANCE TEST: Incremental Event Reads
# ============================================================================

@pytest.mark.asyncio
async def test_incremental_event_reads(backend_client):
    """Verify read_events supports incremental reads with after_sequence."""
    # Create session
    create_result = await backend_client.call_tool("create_session")
    session_id = create_result["session_id"]
    
    # Read all events
    all_events_result = await backend_client.call_tool("read_events", {"session_id": session_id})
    all_events = all_events_result["events"]
    
    assert len(all_events) > 0, f"No events to test incremental reads for {backend_client.backend_id}"
    
    # Get last sequence
    last_sequence = all_events[-1]["sequence"]
    
    # Read events after last sequence (should be empty)
    incremental_result = await backend_client.call_tool("read_events", {
        "session_id": session_id,
        "after_sequence": last_sequence
    })
    
    assert incremental_result["ok"] is True
    assert len(incremental_result["events"]) == 0, f"Incremental read should return empty list for {backend_client.backend_id}"
    
    # Read events after sequence 0 (should return all events except first)
    if len(all_events) > 1:
        incremental_result = await backend_client.call_tool("read_events", {
            "session_id": session_id,
            "after_sequence": 0
        })
        
        assert len(incremental_result["events"]) == len(all_events) - 1, f"Incremental read count mismatch for {backend_client.backend_id}"
        assert all(e["sequence"] > 0 for e in incremental_result["events"]), f"Incremental read returned events with sequence <= 0 for {backend_client.backend_id}"
    
    # Cleanup
    await backend_client.call_tool("close_session", {"session_id": session_id})


# ============================================================================
# CONFORMANCE TEST: Session Lifecycle
# ============================================================================

@pytest.mark.asyncio
async def test_session_lifecycle(backend_client):
    """Verify complete session lifecycle works correctly."""
    # 1. Create session
    create_result = await backend_client.call_tool("create_session")
    
    assert create_result["ok"] is True
    assert create_result["status"] == "created"
    assert create_result["session_id"] is not None
    
    session_id = create_result["session_id"]
    
    # 2. Get status
    status_result = await backend_client.call_tool("get_status", {"session_id": session_id})
    
    assert status_result["ok"] is True
    assert status_result["session_id"] == session_id
    assert status_result["status"] == "created"
    
    # 3. Read events
    events_result = await backend_client.call_tool("read_events", {"session_id": session_id})
    
    assert events_result["ok"] is True
    assert len(events_result["events"]) > 0
    
    # 4. List artifacts (should be empty initially)
    artifacts_result = await backend_client.call_tool("list_artifacts", {"session_id": session_id})
    
    assert artifacts_result["ok"] is True
    assert "artifacts" in artifacts_result
    
    # 5. Close session
    close_result = await backend_client.call_tool("close_session", {"session_id": session_id})
    
    assert close_result["ok"] is True


# ============================================================================
# CONFORMANCE TEST: close_session Always Available
# ============================================================================

@pytest.mark.asyncio
async def test_close_session_always_available(backend_client):
    """Verify close_session can be called on any session in any state."""
    # Test 1: Close immediately after creation
    create_result = await backend_client.call_tool("create_session")
    session_id = create_result["session_id"]
    
    close_result = await backend_client.call_tool("close_session", {"session_id": session_id})
    assert close_result["ok"] is True, f"close_session failed on created session for {backend_client.backend_id}"
    
    # Test 2: Close after interrupt
    create_result = await backend_client.call_tool("create_session")
    session_id = create_result["session_id"]
    
    await backend_client.call_tool("interrupt", {"session_id": session_id})
    
    close_result = await backend_client.call_tool("close_session", {"session_id": session_id})
    assert close_result["ok"] is True, f"close_session failed on interrupted session for {backend_client.backend_id}"
    
    # Test 3: Close after terminate
    create_result = await backend_client.call_tool("create_session")
    session_id = create_result["session_id"]
    
    await backend_client.call_tool("terminate", {"session_id": session_id})
    
    close_result = await backend_client.call_tool("close_session", {"session_id": session_id})
    assert close_result["ok"] is True, f"close_session failed on terminated session for {backend_client.backend_id}"


# ============================================================================
# CONFORMANCE TEST: Artifact Schema
# ============================================================================

@pytest.mark.asyncio
async def test_artifact_schema(backend_client):
    """Verify artifacts follow the required schema."""
    # Create session and run a simple objective to generate artifacts
    create_result = await backend_client.call_tool("create_session")
    session_id = create_result["session_id"]
    
    # Backend-specific smoke objectives
    smoke_objectives = {
        "cli": "List files in the current directory",
        "browser": "Navigate to https://example.com",
        "desktop": "Find the Windows Start button",
    }
    
    objective = smoke_objectives.get(backend_client.backend_id, "Test objective")
    
    # Run objective (may fail, we just want to check artifact schema if any are produced)
    try:
        await backend_client.call_tool("run_objective", {
            "session_id": session_id,
            "objective_id": "artifact-test",
            "objective": objective,
            "timeout": 30
        })
    except Exception:
        pass  # Ignore failures, we just want to check artifacts
    
    # List artifacts
    artifacts_result = await backend_client.call_tool("list_artifacts", {"session_id": session_id})
    
    assert artifacts_result["ok"] is True
    assert "artifacts" in artifacts_result
    
    # If artifacts exist, verify schema
    for artifact in artifacts_result["artifacts"]:
        assert "artifact_id" in artifact, f"artifact_id missing in {backend_client.backend_id} artifact"
        assert "artifact_type" in artifact, f"artifact_type missing in {backend_client.backend_id} artifact"
        assert "timestamp" in artifact, f"timestamp missing in {backend_client.backend_id} artifact"
        assert "metadata" in artifact, f"metadata missing in {backend_client.backend_id} artifact"
        
        # Either path or content should be present
        assert "path" in artifact or "content" in artifact, f"Neither path nor content in {backend_client.backend_id} artifact"
    
    # Cleanup
    await backend_client.call_tool("close_session", {"session_id": session_id})


# ============================================================================
# CONFORMANCE TEST: Contract Behavior Consistency
# ============================================================================

@pytest.mark.asyncio
async def test_contract_behavior_consistency(backend_client):
    """Verify contract behavior is consistent across backends."""
    # All backends should behave the same for basic operations
    
    # 1. Health check should always return ok=True
    health_result = await backend_client.call_tool("health")
    assert health_result["ok"] is True, f"Health check failed for {backend_client.backend_id}"
    
    # 2. List capabilities should always return ok=True and non-empty capabilities
    cap_result = await backend_client.call_tool("list_capabilities")
    assert cap_result["ok"] is True, f"List capabilities failed for {backend_client.backend_id}"
    assert len(cap_result.get("capabilities", [])) > 0, f"No capabilities returned for {backend_client.backend_id}"
    
    # 3. Create session should always return ok=True and a session_id
    create_result = await backend_client.call_tool("create_session")
    assert create_result["ok"] is True, f"Create session failed for {backend_client.backend_id}"
    assert create_result["session_id"] is not None, f"No session_id returned for {backend_client.backend_id}"
    
    session_id = create_result["session_id"]
    
    # 4. Get status should return the session
    status_result = await backend_client.call_tool("get_status", {"session_id": session_id})
    assert status_result["ok"] is True, f"Get status failed for {backend_client.backend_id}"
    assert status_result["session_id"] == session_id, f"Session ID mismatch for {backend_client.backend_id}"
    
    # 5. Close session should always succeed
    close_result = await backend_client.call_tool("close_session", {"session_id": session_id})
    assert close_result["ok"] is True, f"Close session failed for {backend_client.backend_id}"


# ============================================================================
# CONFORMANCE SUMMARY
# ============================================================================

def test_conformance_suite_summary():
    """
    Conformance Suite Summary
    
    This suite verifies:
    - All 10 required MCP tools exist
    - All 8 envelope keys present in responses
    - Frozen statuses respected
    - Frozen event types respected
    - Incremental event reads work
    - Session lifecycle works correctly
    - close_session always available
    - Artifact schema correct
    - Contract behavior consistent across backends
    
    Run with: pytest trinity_core/tests/test_backend_conformance.py -v
    """
    pass
