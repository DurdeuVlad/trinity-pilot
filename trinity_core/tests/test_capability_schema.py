"""TC-S3 + TC-S4: Capability schema v1 conformance and domain-adapter routing tests."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from trinity_core.capability_schema import validate_capabilities, SCHEMA_VERSION
from trinity_core.adapters.cli import CLIAdapter
from trinity_core.adapters.browser import BrowserAdapter
from trinity_core.adapters.desktop import DesktopAdapter
from trinity_core.models import TaskInput


# ---------------------------------------------------------------------------
# TC-S3: validate_capabilities utility unit tests
# ---------------------------------------------------------------------------

class TestCapabilitySchemaValidator:
    def test_valid_payload_returns_no_errors(self):
        caps = {
            "schema_version": "1.0",
            "domain": "cli",
            "actions": ["run_command"],
            "limits": {"timeout_seconds": 600},
            "constraints": {"thread_safe": False},
        }
        assert validate_capabilities(caps) == []

    def test_missing_schema_version_reports_error(self):
        caps = {
            "domain": "cli",
            "actions": ["run_command"],
            "limits": {"timeout_seconds": 600},
            "constraints": {"thread_safe": False},
        }
        errors = validate_capabilities(caps)
        assert any("schema_version" in e for e in errors)

    def test_wrong_schema_version_reports_error(self):
        caps = {
            "schema_version": "0.9",
            "domain": "cli",
            "actions": ["run_command"],
            "limits": {"timeout_seconds": 600},
            "constraints": {"thread_safe": False},
        }
        errors = validate_capabilities(caps)
        assert any("schema_version" in e for e in errors)

    def test_empty_actions_list_reports_error(self):
        caps = {
            "schema_version": "1.0",
            "domain": "cli",
            "actions": [],
            "limits": {"timeout_seconds": 600},
            "constraints": {"thread_safe": False},
        }
        errors = validate_capabilities(caps)
        assert any("actions" in e for e in errors)

    def test_missing_limits_timeout_reports_error(self):
        caps = {
            "schema_version": "1.0",
            "domain": "cli",
            "actions": ["run_command"],
            "limits": {},
            "constraints": {"thread_safe": False},
        }
        errors = validate_capabilities(caps)
        assert any("timeout_seconds" in e for e in errors)

    def test_missing_constraints_thread_safe_reports_error(self):
        caps = {
            "schema_version": "1.0",
            "domain": "cli",
            "actions": ["run_command"],
            "limits": {"timeout_seconds": 600},
            "constraints": {},
        }
        errors = validate_capabilities(caps)
        assert any("thread_safe" in e for e in errors)

    def test_non_dict_input_reports_error(self):
        errors = validate_capabilities("not-a-dict")  # type: ignore[arg-type]
        assert errors


# ---------------------------------------------------------------------------
# TC-S3: Adapter conformance tests
# ---------------------------------------------------------------------------

class TestAdapterCapabilitiesConformance:
    def test_cli_adapter_capabilities_conform_to_schema_v1(self):
        adapter = CLIAdapter()
        caps = adapter.get_capabilities()
        assert validate_capabilities(caps) == [], validate_capabilities(caps)
        assert caps["schema_version"] == SCHEMA_VERSION

    def test_browser_adapter_capabilities_conform_to_schema_v1(self):
        adapter = BrowserAdapter()
        caps = adapter.get_capabilities()
        assert validate_capabilities(caps) == [], validate_capabilities(caps)
        assert caps["schema_version"] == SCHEMA_VERSION

    def test_desktop_adapter_capabilities_conform_to_schema_v1(self):
        adapter = DesktopAdapter()
        caps = adapter.get_capabilities()
        assert validate_capabilities(caps) == [], validate_capabilities(caps)
        assert caps["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# TC-S4: Domain-adapter routing tests
# ---------------------------------------------------------------------------

class TestDomainAdapterRouting:
    @pytest.mark.asyncio
    async def test_web_domain_routes_to_browser_adapter(self):
        from trinity_core.trinity import TrinityExecutor
        async with TrinityExecutor() as executor:
            assert "web" in executor.adapters
            assert isinstance(executor.adapters["web"], BrowserAdapter)

    @pytest.mark.asyncio
    async def test_desktop_domain_routes_to_desktop_adapter(self):
        from trinity_core.trinity import TrinityExecutor
        async with TrinityExecutor() as executor:
            assert "desktop" in executor.adapters
            assert isinstance(executor.adapters["desktop"], DesktopAdapter)

    @pytest.mark.asyncio
    async def test_cli_domain_routes_to_cli_adapter(self):
        from trinity_core.trinity import TrinityExecutor
        async with TrinityExecutor() as executor:
            assert "cli" in executor.adapters
            assert isinstance(executor.adapters["cli"], CLIAdapter)

    @pytest.mark.asyncio
    async def test_unsupported_domain_raises_value_error(self):
        from trinity_core.trinity import TrinityExecutor
        async with TrinityExecutor() as executor:
            task = TaskInput(
                task_id="bad-domain",
                description="test",
                domain="web",  # valid domain for model, but we'll override routing
            )
            # Patch adapters to simulate unsupported domain
            executor.adapters = {"web": executor.adapters["web"]}
            task_bad = TaskInput(task_id="bd", description="d", domain="cli")
            with pytest.raises(ValueError, match="Invalid domain"):
                await executor.execute(task_bad)

    @pytest.mark.asyncio
    async def test_routing_uses_web_alias_for_browser(self):
        from trinity_core.trinity import TrinityExecutor
        async with TrinityExecutor() as executor:
            # "web" is the canonical alias for browser domain
            assert executor.adapters["web"].get_capabilities()["domain"] == "web"

    @pytest.mark.asyncio
    async def test_routing_matrix_all_domains_present(self):
        from trinity_core.trinity import TrinityExecutor
        async with TrinityExecutor() as executor:
            for expected_domain in ("web", "desktop", "cli"):
                assert expected_domain in executor.adapters, (
                    f"Expected domain {expected_domain!r} not found in adapter map"
                )
