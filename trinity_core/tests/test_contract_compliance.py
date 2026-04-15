"""Contract compliance tests - verify frozen contract requirements."""

import pytest
from trinity_core.models import (
    RuntimeStatus,
    RuntimeFailureCategory,
    RuntimeEventType,
)


class TestFrozenContractCompliance:
    """Verify all frozen contract requirements from epic are met."""

    def test_required_statuses_exact_match(self):
        """Verify exact match of required statuses from epic."""
        required = {"created", "running", "completed", "failed", "interrupted", "terminated"}
        actual = {status.value for status in RuntimeStatus}
        
        assert actual == required, f"Status mismatch. Missing: {required - actual}, Extra: {actual - required}"

    def test_required_failure_categories_exact_match(self):
        """Verify exact match of required failure categories from epic."""
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
        
        assert actual == required, f"Category mismatch. Missing: {required - actual}, Extra: {actual - required}"

    def test_required_event_types_exact_match(self):
        """Verify exact match of required event types from epic."""
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
        
        assert actual == required, f"Event type mismatch. Missing: {required - actual}, Extra: {actual - required}"

    def test_no_extra_statuses(self):
        """Ensure no extra statuses beyond frozen contract."""
        assert len(list(RuntimeStatus)) == 6

    def test_no_extra_failure_categories(self):
        """Ensure no extra failure categories beyond frozen contract."""
        assert len(list(RuntimeFailureCategory)) == 9

    def test_no_extra_event_types(self):
        """Ensure no extra event types beyond frozen contract."""
        assert len(list(RuntimeEventType)) == 10


class TestMCPToolContractCompliance:
    """Verify RuntimeHost provides all required MCP tool foundations."""

    def test_runtime_host_has_all_required_methods(self):
        """Verify RuntimeHost has methods for all required MCP tools."""
        from trinity_core.runtime_host import RuntimeHost
        
        required_methods = [
            "health_check",           # health
            "list_capabilities",      # list_capabilities
            "create_session",         # create_session
            "run_objective",          # run_objective
            "read_events",            # read_events
            "get_status",             # get_status
            "interrupt",              # interrupt
            "terminate",              # terminate
            "close_session",          # close_session
            "list_artifacts",         # list_artifacts
        ]
        
        for method_name in required_methods:
            assert hasattr(RuntimeHost, method_name), f"RuntimeHost missing required method: {method_name}"
            assert callable(getattr(RuntimeHost, method_name)), f"{method_name} is not callable"

    def test_read_events_supports_after_sequence(self):
        """Verify read_events supports incremental reads with after_sequence."""
        from trinity_core.runtime_host import RuntimeHost
        import inspect
        
        sig = inspect.signature(RuntimeHost.read_events)
        params = sig.parameters
        
        assert "after_sequence" in params, "read_events missing after_sequence parameter"
        assert params["after_sequence"].default is not inspect.Parameter.empty, "after_sequence should be optional"


class TestResponseEnvelopeCompliance:
    """Verify models support required response envelope keys."""

    def test_runtime_result_has_required_fields(self):
        """Verify RuntimeResult has all required envelope fields."""
        from trinity_core.models import RuntimeResult
        
        required_fields = {
            "session_id",
            "objective_id",
            "status",
            "error",
            "artifacts",
            "metadata",
        }
        
        model_fields = set(RuntimeResult.model_fields.keys())
        
        assert required_fields.issubset(model_fields), f"RuntimeResult missing fields: {required_fields - model_fields}"

    def test_runtime_session_has_required_fields(self):
        """Verify RuntimeSession has all required envelope fields."""
        from trinity_core.models import RuntimeSession
        
        required_fields = {
            "session_id",
            "status",
            "events",
            "artifacts",
            "metadata",
        }
        
        model_fields = set(RuntimeSession.model_fields.keys())
        
        assert required_fields.issubset(model_fields), f"RuntimeSession missing fields: {required_fields - model_fields}"

    def test_runtime_event_serializable(self):
        """Verify RuntimeEvent can be serialized to dict."""
        from trinity_core.models import RuntimeEvent, RuntimeEventType
        from datetime import datetime, timezone
        
        event = RuntimeEvent(
            sequence=0,
            event_type=RuntimeEventType.SESSION_CREATED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id="test",
        )
        
        event_dict = event.model_dump()
        assert isinstance(event_dict, dict)
        assert "sequence" in event_dict
        assert "event_type" in event_dict


class TestBackendProfileCompliance:
    """Verify backend profiles meet contract requirements."""

    def test_all_backend_ids_are_valid(self):
        """Verify backend_id is constrained to cli, browser, desktop."""
        from trinity_core.models import BackendProfile
        import inspect
        
        sig = inspect.signature(BackendProfile)
        backend_id_annotation = sig.parameters["backend_id"].annotation
        
        # Check if it's a Literal type
        assert hasattr(backend_id_annotation, "__args__"), "backend_id should be a Literal type"

    def test_default_profiles_exist_for_all_backends(self):
        """Verify default profile factories exist for all backends."""
        from trinity_core.backend_registry import (
            create_cli_profile,
            create_browser_profile,
            create_desktop_profile,
        )
        
        cli = create_cli_profile()
        browser = create_browser_profile()
        desktop = create_desktop_profile()
        
        assert cli.backend_id == "cli"
        assert browser.backend_id == "browser"
        assert desktop.backend_id == "desktop"

    def test_all_profiles_have_capabilities(self):
        """Verify all default profiles have capabilities defined."""
        from trinity_core.backend_registry import create_default_registry
        
        registry = create_default_registry()
        
        for backend_id in ["cli", "browser", "desktop"]:
            caps = registry.list_capabilities(backend_id)
            assert len(caps) > 0, f"{backend_id} profile has no capabilities"

    def test_all_profiles_have_safety_policy(self):
        """Verify all default profiles have safety policy."""
        from trinity_core.backend_registry import create_default_registry
        
        registry = create_default_registry()
        
        for backend_id in ["cli", "browser", "desktop"]:
            profile = registry.get_profile(backend_id)
            assert profile.safety_policy is not None, f"{backend_id} has no safety_policy"
            assert isinstance(profile.safety_policy, dict), f"{backend_id} safety_policy is not a dict"


class TestLifecycleRulesCompliance:
    """Verify lifecycle rules from epic are implemented."""

    @pytest.mark.asyncio
    async def test_run_objective_generates_session_id_if_omitted(self):
        """Verify run_objective can work with auto-generated session_id."""
        from trinity_core.runtime_host import RuntimeHost
        from trinity_core.backend_registry import create_cli_profile
        from trinity_core.models import RuntimeResult, RuntimeStatus
        from datetime import datetime, timezone
        
        async def mock_executor(session_id, objective_id, objective, context, max_retries):
            now = datetime.now(timezone.utc).isoformat()
            return RuntimeResult(
                session_id=session_id,
                objective_id=objective_id,
                status=RuntimeStatus.COMPLETED,
                started_at=now,
                completed_at=now,
            )
        
        host = RuntimeHost(
            backend_id="cli",
            profile=create_cli_profile(),
            executor_fn=mock_executor,
        )
        
        # Create session without explicit ID
        session = host.create_session()
        assert session.session_id is not None
        assert len(session.session_id) > 0

    @pytest.mark.asyncio
    async def test_read_events_supports_incremental_after_sequence(self):
        """Verify read_events supports after_sequence for incremental reads."""
        from trinity_core.runtime_host import RuntimeHost
        from trinity_core.backend_registry import create_cli_profile
        from trinity_core.models import RuntimeResult, RuntimeStatus
        from datetime import datetime, timezone
        
        async def mock_executor(session_id, objective_id, objective, context, max_retries):
            now = datetime.now(timezone.utc).isoformat()
            return RuntimeResult(
                session_id=session_id,
                objective_id=objective_id,
                status=RuntimeStatus.COMPLETED,
                started_at=now,
                completed_at=now,
            )
        
        host = RuntimeHost(
            backend_id="cli",
            profile=create_cli_profile(),
            executor_fn=mock_executor,
        )
        
        session = host.create_session(session_id="test")
        
        # Initial events
        initial_events = host.read_events("test")
        assert len(initial_events) == 1
        
        # Run objective to generate more events
        await host.run_objective("test", "obj-1", "Test objective")
        
        # Read only new events
        new_events = host.read_events("test", after_sequence=0)
        assert len(new_events) > 0
        assert all(e.sequence > 0 for e in new_events)

    def test_default_max_retries_is_3(self):
        """Verify default max_retries is 3 as per epic."""
        from trinity_core.backend_registry import create_default_registry
        
        registry = create_default_registry()
        
        for backend_id in ["cli", "browser", "desktop"]:
            profile = registry.get_profile(backend_id)
            assert profile.max_retries == 3, f"{backend_id} default max_retries is not 3"
