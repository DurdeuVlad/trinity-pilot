"""Tests for frozen runtime contract types."""

import pytest
from datetime import datetime, timezone

from trinity_core.models import (
    BackendProfile,
    CapabilityDescriptor,
    RuntimeArtifact,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeFailureCategory,
    RuntimeResult,
    RuntimeSession,
    RuntimeStatus,
)


class TestRuntimeStatus:
    """Test RuntimeStatus enum."""

    def test_all_required_statuses_present(self):
        """Verify all required statuses are defined."""
        required = {"created", "running", "completed", "failed", "interrupted", "terminated"}
        actual = {status.value for status in RuntimeStatus}
        assert actual == required

    def test_status_values_are_strings(self):
        """Verify status values are lowercase strings."""
        for status in RuntimeStatus:
            assert isinstance(status.value, str)
            assert status.value.islower()


class TestRuntimeFailureCategory:
    """Test RuntimeFailureCategory enum."""

    def test_all_required_categories_present(self):
        """Verify all required failure categories are defined."""
        required = {
            "backend_unavailable",
            "tool_schema_error",
            "session_lifecycle_error",
            "validator_rejection",
            "execution_failure",
            "timeout",
            "interrupted",
            "terminated",
            "transport_error",
        }
        actual = {cat.value for cat in RuntimeFailureCategory}
        assert actual == required


class TestRuntimeEventType:
    """Test RuntimeEventType enum."""

    def test_all_required_event_types_present(self):
        """Verify all required event types are defined."""
        required = {
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
        }
        actual = {event.value for event in RuntimeEventType}
        assert actual == required


class TestRuntimeEvent:
    """Test RuntimeEvent model."""

    def test_create_event(self):
        """Test creating a runtime event."""
        event = RuntimeEvent(
            sequence=0,
            event_type=RuntimeEventType.SESSION_CREATED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id="test-session",
            data={"backend_id": "cli"},
        )
        
        assert event.sequence == 0
        assert event.event_type == RuntimeEventType.SESSION_CREATED
        assert event.session_id == "test-session"
        assert event.data["backend_id"] == "cli"

    def test_event_with_objective_and_action(self):
        """Test event with objective and action IDs."""
        event = RuntimeEvent(
            sequence=5,
            event_type=RuntimeEventType.ACTION_COMPLETED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id="test-session",
            objective_id="obj-1",
            action_id="act-1",
            data={"result": "success"},
        )
        
        assert event.objective_id == "obj-1"
        assert event.action_id == "act-1"


class TestRuntimeArtifact:
    """Test RuntimeArtifact model."""

    def test_create_artifact_with_path(self):
        """Test creating an artifact with file path."""
        artifact = RuntimeArtifact(
            artifact_id="art-1",
            artifact_type="screenshot",
            path="/tmp/screenshot.png",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        assert artifact.artifact_id == "art-1"
        assert artifact.artifact_type == "screenshot"
        assert artifact.path == "/tmp/screenshot.png"
        assert artifact.content is None

    def test_create_artifact_with_content(self):
        """Test creating an artifact with inline content."""
        artifact = RuntimeArtifact(
            artifact_id="art-2",
            artifact_type="log",
            content="Log content here",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        assert artifact.artifact_type == "log"
        assert artifact.content == "Log content here"
        assert artifact.path is None


class TestRuntimeResult:
    """Test RuntimeResult model."""

    def test_create_success_result(self):
        """Test creating a successful result."""
        now = datetime.now(timezone.utc).isoformat()
        result = RuntimeResult(
            session_id="sess-1",
            objective_id="obj-1",
            status=RuntimeStatus.COMPLETED,
            output="Task completed successfully",
            started_at=now,
            completed_at=now,
        )
        
        assert result.status == RuntimeStatus.COMPLETED
        assert result.error is None
        assert result.failure_category is None
        assert result.output == "Task completed successfully"

    def test_create_failure_result(self):
        """Test creating a failure result."""
        now = datetime.now(timezone.utc).isoformat()
        result = RuntimeResult(
            session_id="sess-1",
            objective_id="obj-1",
            status=RuntimeStatus.FAILED,
            error="Backend unavailable",
            failure_category=RuntimeFailureCategory.BACKEND_UNAVAILABLE,
            started_at=now,
            completed_at=now,
        )
        
        assert result.status == RuntimeStatus.FAILED
        assert result.error == "Backend unavailable"
        assert result.failure_category == RuntimeFailureCategory.BACKEND_UNAVAILABLE

    def test_result_with_artifacts(self):
        """Test result with artifacts."""
        now = datetime.now(timezone.utc).isoformat()
        artifact = RuntimeArtifact(
            artifact_id="art-1",
            artifact_type="screenshot",
            path="/tmp/screenshot.png",
            timestamp=now,
        )
        
        result = RuntimeResult(
            session_id="sess-1",
            objective_id="obj-1",
            status=RuntimeStatus.COMPLETED,
            artifacts=[artifact],
            started_at=now,
            completed_at=now,
        )
        
        assert len(result.artifacts) == 1
        assert result.artifacts[0].artifact_id == "art-1"


class TestCapabilityDescriptor:
    """Test CapabilityDescriptor model."""

    def test_create_capability(self):
        """Test creating a capability descriptor."""
        cap = CapabilityDescriptor(
            capability_id="execute_command",
            name="Execute Command",
            description="Execute shell commands",
            category="execution",
            enabled=True,
            parameters={"shell": "powershell"},
        )
        
        assert cap.capability_id == "execute_command"
        assert cap.enabled is True
        assert cap.parameters["shell"] == "powershell"

    def test_capability_defaults(self):
        """Test capability descriptor defaults."""
        cap = CapabilityDescriptor(
            capability_id="test",
            name="Test",
            description="Test capability",
            category="test",
        )
        
        assert cap.enabled is True
        assert cap.parameters == {}
        assert cap.metadata == {}


class TestBackendProfile:
    """Test BackendProfile model."""

    def test_create_cli_profile(self):
        """Test creating a CLI backend profile."""
        profile = BackendProfile(
            backend_id="cli",
            name="CLI Automation",
            description="Command-line interface automation",
            capabilities=[
                CapabilityDescriptor(
                    capability_id="execute_command",
                    name="Execute Command",
                    description="Execute shell commands",
                    category="execution",
                )
            ],
            max_retries=3,
            timeout=300,
        )
        
        assert profile.backend_id == "cli"
        assert len(profile.capabilities) == 1
        assert profile.max_retries == 3
        assert profile.timeout == 300

    def test_profile_with_safety_policy(self):
        """Test profile with safety policy."""
        profile = BackendProfile(
            backend_id="cli",
            name="CLI",
            description="CLI backend",
            safety_policy={
                "blocked_commands": ["rm -rf /"],
                "require_confirmation": ["shutdown"],
            },
        )
        
        assert "blocked_commands" in profile.safety_policy
        assert "rm -rf /" in profile.safety_policy["blocked_commands"]

    def test_profile_with_prompt_config(self):
        """Test profile with prompt configuration."""
        profile = BackendProfile(
            backend_id="browser",
            name="Browser",
            description="Browser backend",
            prompt_config={
                "system_prompt": "You are a browser automation assistant.",
                "max_iterations": 50,
            },
        )
        
        assert profile.prompt_config["max_iterations"] == 50


class TestRuntimeSession:
    """Test RuntimeSession model."""

    def test_create_session(self):
        """Test creating a runtime session."""
        now = datetime.now(timezone.utc).isoformat()
        session = RuntimeSession(
            session_id="sess-1",
            backend_id="cli",
            status=RuntimeStatus.CREATED,
            created_at=now,
        )
        
        assert session.session_id == "sess-1"
        assert session.backend_id == "cli"
        assert session.status == RuntimeStatus.CREATED
        assert session.events == []
        assert session.artifacts == []

    def test_session_with_events(self):
        """Test session with events."""
        now = datetime.now(timezone.utc).isoformat()
        event = RuntimeEvent(
            sequence=0,
            event_type=RuntimeEventType.SESSION_CREATED,
            timestamp=now,
            session_id="sess-1",
        )
        
        session = RuntimeSession(
            session_id="sess-1",
            backend_id="cli",
            status=RuntimeStatus.CREATED,
            created_at=now,
            events=[event],
        )
        
        assert len(session.events) == 1
        assert session.events[0].event_type == RuntimeEventType.SESSION_CREATED

    def test_session_lifecycle_timestamps(self):
        """Test session lifecycle timestamps."""
        now = datetime.now(timezone.utc).isoformat()
        session = RuntimeSession(
            session_id="sess-1",
            backend_id="cli",
            status=RuntimeStatus.RUNNING,
            created_at=now,
            started_at=now,
        )
        
        assert session.created_at == now
        assert session.started_at == now
        assert session.completed_at is None
        
        session.status = RuntimeStatus.COMPLETED
        session.completed_at = now
        
        assert session.completed_at == now
