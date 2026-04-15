"""Tests for RuntimeHost."""

import pytest
from datetime import datetime, timezone

from trinity_core.runtime_host import RuntimeHost
from trinity_core.models import (
    BackendProfile,
    CapabilityDescriptor,
    RuntimeEventType,
    RuntimeFailureCategory,
    RuntimeStatus,
)


@pytest.fixture
def test_profile():
    """Create a test backend profile."""
    return BackendProfile(
        backend_id="cli",
        name="Test CLI",
        description="Test CLI backend",
        capabilities=[
            CapabilityDescriptor(
                capability_id="test_cap",
                name="Test Capability",
                description="Test",
                category="test",
            )
        ],
        max_retries=3,
        timeout=30,
    )


@pytest.fixture
def mock_executor():
    """Create a mock executor function."""
    async def executor(session_id, objective_id, objective, context, max_retries):
        from trinity_core.models import RuntimeResult, RuntimeStatus
        now = datetime.now(timezone.utc).isoformat()
        return RuntimeResult(
            session_id=session_id,
            objective_id=objective_id,
            status=RuntimeStatus.COMPLETED,
            output="Mock execution completed",
            started_at=now,
            completed_at=now,
        )
    return executor


@pytest.fixture
def runtime_host(test_profile, mock_executor):
    """Create a RuntimeHost instance."""
    return RuntimeHost(
        backend_id="cli",
        profile=test_profile,
        executor_fn=mock_executor,
    )


class TestRuntimeHostLifecycle:
    """Test RuntimeHost lifecycle operations."""

    @pytest.mark.asyncio
    async def test_health_check_no_fn(self, runtime_host):
        """Test health check with no readiness function."""
        result = await runtime_host.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_with_fn(self, test_profile, mock_executor):
        """Test health check with readiness function."""
        async def readiness_check():
            return True
        
        host = RuntimeHost(
            backend_id="cli",
            profile=test_profile,
            executor_fn=mock_executor,
            readiness_check_fn=readiness_check,
        )
        
        result = await host.health_check()
        assert result is True

    def test_list_capabilities(self, runtime_host):
        """Test listing capabilities."""
        caps = runtime_host.list_capabilities()
        assert len(caps) == 1
        assert caps[0].capability_id == "test_cap"


class TestSessionManagement:
    """Test session management."""

    def test_create_session_auto_id(self, runtime_host):
        """Test creating session with auto-generated ID."""
        session = runtime_host.create_session()
        
        assert session.session_id is not None
        assert session.backend_id == "cli"
        assert session.status == RuntimeStatus.CREATED
        assert len(session.events) == 1
        assert session.events[0].event_type == RuntimeEventType.SESSION_CREATED

    def test_create_session_explicit_id(self, runtime_host):
        """Test creating session with explicit ID."""
        session = runtime_host.create_session(session_id="test-session")
        
        assert session.session_id == "test-session"
        assert session.backend_id == "cli"

    def test_create_duplicate_session_raises(self, runtime_host):
        """Test that creating duplicate session raises error."""
        runtime_host.create_session(session_id="test-session")
        
        with pytest.raises(ValueError, match="already exists"):
            runtime_host.create_session(session_id="test-session")

    def test_get_status(self, runtime_host):
        """Test getting session status."""
        session = runtime_host.create_session(session_id="test-session")
        
        retrieved = runtime_host.get_status("test-session")
        assert retrieved.session_id == session.session_id
        assert retrieved.status == RuntimeStatus.CREATED

    def test_get_status_not_found(self, runtime_host):
        """Test getting status for non-existent session."""
        with pytest.raises(ValueError, match="not found"):
            runtime_host.get_status("nonexistent")

    def test_close_session(self, runtime_host):
        """Test closing a session."""
        runtime_host.create_session(session_id="test-session")
        runtime_host.close_session("test-session")
        
        with pytest.raises(ValueError, match="not found"):
            runtime_host.get_status("test-session")


class TestObjectiveExecution:
    """Test objective execution."""

    @pytest.mark.asyncio
    async def test_run_objective_success(self, runtime_host):
        """Test successful objective execution."""
        session = runtime_host.create_session(session_id="test-session")
        
        result = await runtime_host.run_objective(
            session_id="test-session",
            objective_id="obj-1",
            objective="Test objective",
        )
        
        assert result.status == RuntimeStatus.COMPLETED
        assert result.session_id == "test-session"
        assert result.objective_id == "obj-1"
        assert result.output == "Mock execution completed"
        
        session = runtime_host.get_status("test-session")
        assert session.status == RuntimeStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_objective_session_not_found(self, runtime_host):
        """Test running objective on non-existent session."""
        with pytest.raises(ValueError, match="not found"):
            await runtime_host.run_objective(
                session_id="nonexistent",
                objective_id="obj-1",
                objective="Test",
            )

    @pytest.mark.asyncio
    async def test_run_objective_timeout(self, test_profile):
        """Test objective execution timeout."""
        async def slow_executor(session_id, objective_id, objective, context, max_retries):
            import asyncio
            await asyncio.sleep(10)
        
        host = RuntimeHost(
            backend_id="cli",
            profile=test_profile,
            executor_fn=slow_executor,
        )
        
        host.create_session(session_id="test-session")
        
        result = await host.run_objective(
            session_id="test-session",
            objective_id="obj-1",
            objective="Test",
            timeout=1,
        )
        
        assert result.status == RuntimeStatus.FAILED
        assert result.failure_category == RuntimeFailureCategory.TIMEOUT
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_run_objective_with_safety_hook(self, test_profile, mock_executor):
        """Test objective execution with safety hook."""
        async def safety_hook(objective, context):
            if "dangerous" in objective.lower():
                return {"allowed": False, "reason": "Dangerous operation blocked"}
            return {"allowed": True}
        
        host = RuntimeHost(
            backend_id="cli",
            profile=test_profile,
            executor_fn=mock_executor,
            safety_hook_fn=safety_hook,
        )
        
        host.create_session(session_id="test-session")
        
        result = await host.run_objective(
            session_id="test-session",
            objective_id="obj-1",
            objective="Dangerous operation",
        )
        
        assert result.status == RuntimeStatus.FAILED
        assert result.failure_category == RuntimeFailureCategory.VALIDATOR_REJECTION
        assert "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_run_objective_with_artifact_hook(self, test_profile, mock_executor):
        """Test objective execution with artifact collection."""
        from trinity_core.models import RuntimeArtifact
        
        async def artifact_hook(session_id, objective_id):
            now = datetime.now(timezone.utc).isoformat()
            return [
                RuntimeArtifact(
                    artifact_id="art-1",
                    artifact_type="log",
                    content="Test log",
                    timestamp=now,
                )
            ]
        
        host = RuntimeHost(
            backend_id="cli",
            profile=test_profile,
            executor_fn=mock_executor,
            artifact_hook_fn=artifact_hook,
        )
        
        host.create_session(session_id="test-session")
        
        result = await host.run_objective(
            session_id="test-session",
            objective_id="obj-1",
            objective="Test",
        )
        
        assert len(result.artifacts) == 1
        assert result.artifacts[0].artifact_id == "art-1"


class TestEventManagement:
    """Test event management."""

    def test_read_events_all(self, runtime_host):
        """Test reading all events."""
        session = runtime_host.create_session(session_id="test-session")
        
        events = runtime_host.read_events("test-session")
        assert len(events) == 1
        assert events[0].event_type == RuntimeEventType.SESSION_CREATED

    @pytest.mark.asyncio
    async def test_read_events_incremental(self, runtime_host):
        """Test incremental event reading."""
        runtime_host.create_session(session_id="test-session")
        
        initial_events = runtime_host.read_events("test-session")
        assert len(initial_events) == 1
        
        await runtime_host.run_objective(
            session_id="test-session",
            objective_id="obj-1",
            objective="Test",
        )
        
        new_events = runtime_host.read_events("test-session", after_sequence=0)
        assert len(new_events) > 0
        assert all(e.sequence > 0 for e in new_events)

    def test_read_events_not_found(self, runtime_host):
        """Test reading events from non-existent session."""
        with pytest.raises(ValueError, match="not found"):
            runtime_host.read_events("nonexistent")


class TestSessionControl:
    """Test session control operations."""

    @pytest.mark.asyncio
    async def test_interrupt_session(self, runtime_host):
        """Test interrupting a running session."""
        session = runtime_host.create_session(session_id="test-session")
        session.status = RuntimeStatus.RUNNING
        
        await runtime_host.interrupt("test-session")
        
        session = runtime_host.get_status("test-session")
        assert session.status == RuntimeStatus.INTERRUPTED
        
        events = runtime_host.read_events("test-session")
        assert any(e.event_type == RuntimeEventType.SESSION_INTERRUPTED for e in events)

    @pytest.mark.asyncio
    async def test_terminate_session(self, runtime_host):
        """Test terminating a session."""
        runtime_host.create_session(session_id="test-session")
        
        await runtime_host.terminate("test-session")
        
        session = runtime_host.get_status("test-session")
        assert session.status == RuntimeStatus.TERMINATED
        
        events = runtime_host.read_events("test-session")
        assert any(e.event_type == RuntimeEventType.SESSION_TERMINATED for e in events)

    @pytest.mark.asyncio
    async def test_interrupt_not_found(self, runtime_host):
        """Test interrupting non-existent session."""
        with pytest.raises(ValueError, match="not found"):
            await runtime_host.interrupt("nonexistent")

    @pytest.mark.asyncio
    async def test_terminate_not_found(self, runtime_host):
        """Test terminating non-existent session."""
        with pytest.raises(ValueError, match="not found"):
            await runtime_host.terminate("nonexistent")


class TestArtifactManagement:
    """Test artifact management."""

    def test_list_artifacts_empty(self, runtime_host):
        """Test listing artifacts from empty session."""
        runtime_host.create_session(session_id="test-session")
        
        artifacts = runtime_host.list_artifacts("test-session")
        assert artifacts == []

    @pytest.mark.asyncio
    async def test_list_artifacts_after_execution(self, test_profile, mock_executor):
        """Test listing artifacts after execution with artifact hook."""
        from trinity_core.models import RuntimeArtifact
        
        async def artifact_hook(session_id, objective_id):
            now = datetime.now(timezone.utc).isoformat()
            return [
                RuntimeArtifact(
                    artifact_id="art-1",
                    artifact_type="screenshot",
                    path="/tmp/screenshot.png",
                    timestamp=now,
                )
            ]
        
        host = RuntimeHost(
            backend_id="cli",
            profile=test_profile,
            executor_fn=mock_executor,
            artifact_hook_fn=artifact_hook,
        )
        
        host.create_session(session_id="test-session")
        await host.run_objective(
            session_id="test-session",
            objective_id="obj-1",
            objective="Test",
        )
        
        artifacts = host.list_artifacts("test-session")
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == "screenshot"

    def test_list_artifacts_not_found(self, runtime_host):
        """Test listing artifacts from non-existent session."""
        with pytest.raises(ValueError, match="not found"):
            runtime_host.list_artifacts("nonexistent")
