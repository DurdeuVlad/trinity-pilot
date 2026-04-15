"""Tests for BackendRegistry and profile creation."""

import pytest

from trinity_core.backend_registry import (
    BackendRegistry,
    create_cli_profile,
    create_browser_profile,
    create_desktop_profile,
    create_default_registry,
)
from trinity_core.models import BackendProfile, CapabilityDescriptor


class TestBackendRegistry:
    """Test BackendRegistry."""

    def test_register_profile(self):
        """Test registering a backend profile."""
        registry = BackendRegistry()
        profile = BackendProfile(
            backend_id="cli",
            name="CLI",
            description="CLI backend",
        )
        
        registry.register_profile(profile)
        
        assert "cli" in registry.profiles
        assert registry.get_profile("cli") == profile

    def test_get_profile_not_found(self):
        """Test getting non-existent profile."""
        registry = BackendRegistry()
        assert registry.get_profile("nonexistent") is None

    def test_list_backends(self):
        """Test listing registered backends."""
        registry = BackendRegistry()
        
        cli_profile = BackendProfile(
            backend_id="cli",
            name="CLI",
            description="CLI backend",
        )
        browser_profile = BackendProfile(
            backend_id="browser",
            name="Browser",
            description="Browser backend",
        )
        
        registry.register_profile(cli_profile)
        registry.register_profile(browser_profile)
        
        backends = registry.list_backends()
        assert set(backends) == {"cli", "browser"}

    def test_list_capabilities(self):
        """Test listing capabilities for a backend."""
        registry = BackendRegistry()
        
        profile = BackendProfile(
            backend_id="cli",
            name="CLI",
            description="CLI backend",
            capabilities=[
                CapabilityDescriptor(
                    capability_id="cap1",
                    name="Capability 1",
                    description="Test capability",
                    category="test",
                ),
                CapabilityDescriptor(
                    capability_id="cap2",
                    name="Capability 2",
                    description="Test capability 2",
                    category="test",
                ),
            ],
        )
        
        registry.register_profile(profile)
        
        caps = registry.list_capabilities("cli")
        assert len(caps) == 2
        assert caps[0].capability_id == "cap1"
        assert caps[1].capability_id == "cap2"

    def test_list_capabilities_not_found(self):
        """Test listing capabilities for non-existent backend."""
        registry = BackendRegistry()
        assert registry.list_capabilities("nonexistent") == []

    def test_find_capability(self):
        """Test finding a specific capability."""
        registry = BackendRegistry()
        
        profile = BackendProfile(
            backend_id="cli",
            name="CLI",
            description="CLI backend",
            capabilities=[
                CapabilityDescriptor(
                    capability_id="test_cap",
                    name="Test Capability",
                    description="Test",
                    category="test",
                ),
            ],
        )
        
        registry.register_profile(profile)
        
        cap = registry.find_capability("cli", "test_cap")
        assert cap is not None
        assert cap.capability_id == "test_cap"

    def test_find_capability_not_found(self):
        """Test finding non-existent capability."""
        registry = BackendRegistry()
        
        profile = BackendProfile(
            backend_id="cli",
            name="CLI",
            description="CLI backend",
        )
        
        registry.register_profile(profile)
        
        assert registry.find_capability("cli", "nonexistent") is None
        assert registry.find_capability("nonexistent", "cap") is None

    def test_update_capability(self):
        """Test updating capability configuration."""
        registry = BackendRegistry()
        
        profile = BackendProfile(
            backend_id="cli",
            name="CLI",
            description="CLI backend",
            capabilities=[
                CapabilityDescriptor(
                    capability_id="test_cap",
                    name="Test Capability",
                    description="Test",
                    category="test",
                    enabled=True,
                    parameters={"key": "value"},
                ),
            ],
        )
        
        registry.register_profile(profile)
        
        result = registry.update_capability(
            "cli",
            "test_cap",
            enabled=False,
            parameters={"key": "new_value", "new_key": "new"},
        )
        
        assert result is True
        
        cap = registry.find_capability("cli", "test_cap")
        assert cap.enabled is False
        assert cap.parameters["key"] == "new_value"
        assert cap.parameters["new_key"] == "new"

    def test_update_capability_not_found(self):
        """Test updating non-existent capability."""
        registry = BackendRegistry()
        
        result = registry.update_capability("cli", "nonexistent", enabled=False)
        assert result is False


class TestProfileCreation:
    """Test profile creation functions."""

    def test_create_cli_profile(self):
        """Test creating CLI profile."""
        profile = create_cli_profile()
        
        assert profile.backend_id == "cli"
        assert profile.name == "CLI Automation"
        assert len(profile.capabilities) > 0
        assert profile.max_retries == 3
        assert profile.timeout == 300
        assert "blocked_commands" in profile.safety_policy
        assert "system_prompt" in profile.prompt_config

    def test_create_browser_profile(self):
        """Test creating browser profile."""
        profile = create_browser_profile()
        
        assert profile.backend_id == "browser"
        assert profile.name == "Browser Automation"
        assert len(profile.capabilities) > 0
        assert any(cap.capability_id == "navigate" for cap in profile.capabilities)
        assert any(cap.capability_id == "screenshot" for cap in profile.capabilities)

    def test_create_desktop_profile(self):
        """Test creating desktop profile."""
        profile = create_desktop_profile()
        
        assert profile.backend_id == "desktop"
        assert profile.name == "Desktop Automation"
        assert len(profile.capabilities) > 0
        assert any(cap.capability_id == "window_control" for cap in profile.capabilities)

    def test_create_default_registry(self):
        """Test creating default registry."""
        registry = create_default_registry()
        
        backends = registry.list_backends()
        assert set(backends) == {"cli", "browser", "desktop"}
        
        cli_profile = registry.get_profile("cli")
        assert cli_profile is not None
        assert cli_profile.backend_id == "cli"
        
        browser_profile = registry.get_profile("browser")
        assert browser_profile is not None
        assert browser_profile.backend_id == "browser"
        
        desktop_profile = registry.get_profile("desktop")
        assert desktop_profile is not None
        assert desktop_profile.backend_id == "desktop"


class TestCapabilityDescriptors:
    """Test capability descriptors in default profiles."""

    def test_cli_capabilities(self):
        """Test CLI profile capabilities."""
        profile = create_cli_profile()
        
        cap_ids = {cap.capability_id for cap in profile.capabilities}
        assert "execute_command" in cap_ids
        assert "file_operations" in cap_ids
        assert "process_management" in cap_ids
        
        for cap in profile.capabilities:
            assert cap.enabled is True
            assert cap.name
            assert cap.description
            assert cap.category

    def test_browser_capabilities(self):
        """Test browser profile capabilities."""
        profile = create_browser_profile()
        
        cap_ids = {cap.capability_id for cap in profile.capabilities}
        assert "navigate" in cap_ids
        assert "interact" in cap_ids
        assert "extract" in cap_ids
        assert "screenshot" in cap_ids

    def test_desktop_capabilities(self):
        """Test desktop profile capabilities."""
        profile = create_desktop_profile()
        
        cap_ids = {cap.capability_id for cap in profile.capabilities}
        assert "window_control" in cap_ids
        assert "ui_interaction" in cap_ids
        assert "text_extraction" in cap_ids


class TestSafetyPolicies:
    """Test safety policy configurations."""

    def test_cli_safety_policy(self):
        """Test CLI safety policy."""
        profile = create_cli_profile()
        
        assert "blocked_commands" in profile.safety_policy
        assert "require_confirmation" in profile.safety_policy
        
        blocked = profile.safety_policy["blocked_commands"]
        assert isinstance(blocked, list)
        assert len(blocked) > 0

    def test_browser_safety_policy(self):
        """Test browser safety policy."""
        profile = create_browser_profile()
        
        assert "allowed_domains" in profile.safety_policy
        assert "blocked_domains" in profile.safety_policy

    def test_desktop_safety_policy(self):
        """Test desktop safety policy."""
        profile = create_desktop_profile()
        
        assert "blocked_apps" in profile.safety_policy
        assert "require_confirmation" in profile.safety_policy
