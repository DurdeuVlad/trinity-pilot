"""Backend profile and capability registry."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .models import BackendProfile, CapabilityDescriptor


class BackendRegistry:
    """
    Registry for backend profiles and capabilities.
    
    This class manages backend profile loading, capability registration,
    and discovery.
    """

    def __init__(self):
        self.profiles: Dict[str, BackendProfile] = {}
        self._capability_index: Dict[str, List[str]] = {}

    def register_profile(self, profile: BackendProfile) -> None:
        """
        Register a backend profile.
        
        Args:
            profile: BackendProfile to register
        """
        self.profiles[profile.backend_id] = profile
        
        self._capability_index[profile.backend_id] = [
            cap.capability_id for cap in profile.capabilities
        ]

    def get_profile(self, backend_id: str) -> Optional[BackendProfile]:
        """
        Get a backend profile by ID.
        
        Args:
            backend_id: Backend identifier
            
        Returns:
            BackendProfile or None if not found
        """
        return self.profiles.get(backend_id)

    def list_backends(self) -> List[str]:
        """
        List all registered backend IDs.
        
        Returns:
            List of backend IDs
        """
        return list(self.profiles.keys())

    def list_capabilities(self, backend_id: str) -> List[CapabilityDescriptor]:
        """
        List capabilities for a backend.
        
        Args:
            backend_id: Backend identifier
            
        Returns:
            List of CapabilityDescriptor
        """
        profile = self.profiles.get(backend_id)
        if profile is None:
            return []
        return profile.capabilities

    def find_capability(
        self,
        backend_id: str,
        capability_id: str,
    ) -> Optional[CapabilityDescriptor]:
        """
        Find a specific capability.
        
        Args:
            backend_id: Backend identifier
            capability_id: Capability identifier
            
        Returns:
            CapabilityDescriptor or None if not found
        """
        profile = self.profiles.get(backend_id)
        if profile is None:
            return None
        
        for cap in profile.capabilities:
            if cap.capability_id == capability_id:
                return cap
        
        return None

    def update_capability(
        self,
        backend_id: str,
        capability_id: str,
        enabled: Optional[bool] = None,
        parameters: Optional[Dict] = None,
    ) -> bool:
        """
        Update a capability configuration.
        
        Args:
            backend_id: Backend identifier
            capability_id: Capability identifier
            enabled: Optional enabled flag
            parameters: Optional parameters update
            
        Returns:
            True if updated, False if not found
        """
        capability = self.find_capability(backend_id, capability_id)
        if capability is None:
            return False
        
        if enabled is not None:
            capability.enabled = enabled
        if parameters is not None:
            capability.parameters.update(parameters)
        
        return True


def create_cli_profile() -> BackendProfile:
    """Create default CLI backend profile."""
    return BackendProfile(
        backend_id="cli",
        name="CLI Automation",
        description="Command-line interface automation backend",
        capabilities=[
            CapabilityDescriptor(
                capability_id="execute_command",
                name="Execute Command",
                description="Execute shell commands",
                category="execution",
                enabled=True,
                parameters={"shell": "powershell"},
            ),
            CapabilityDescriptor(
                capability_id="file_operations",
                name="File Operations",
                description="File system operations",
                category="filesystem",
                enabled=True,
            ),
            CapabilityDescriptor(
                capability_id="process_management",
                name="Process Management",
                description="Process management operations",
                category="system",
                enabled=True,
            ),
        ],
        max_retries=3,
        timeout=300,
        safety_policy={
            "blocked_commands": ["rm -rf /", "format", "del /f /s /q"],
            "require_confirmation": ["shutdown", "restart"],
        },
        prompt_config={
            "system_prompt": "You are a CLI automation assistant.",
            "max_iterations": 50,
        },
    )


def create_browser_profile() -> BackendProfile:
    """Create default browser backend profile."""
    return BackendProfile(
        backend_id="browser",
        name="Browser Automation",
        description="Web browser automation backend",
        capabilities=[
            CapabilityDescriptor(
                capability_id="navigate",
                name="Navigate",
                description="Navigate to URLs",
                category="navigation",
                enabled=True,
            ),
            CapabilityDescriptor(
                capability_id="interact",
                name="Interact",
                description="Interact with page elements",
                category="interaction",
                enabled=True,
            ),
            CapabilityDescriptor(
                capability_id="extract",
                name="Extract",
                description="Extract page content",
                category="extraction",
                enabled=True,
            ),
            CapabilityDescriptor(
                capability_id="screenshot",
                name="Screenshot",
                description="Capture screenshots",
                category="observation",
                enabled=True,
            ),
        ],
        max_retries=3,
        timeout=300,
        safety_policy={
            "allowed_domains": [],
            "blocked_domains": [],
        },
        prompt_config={
            "system_prompt": "You are a browser automation assistant.",
            "max_iterations": 50,
        },
    )


def create_desktop_profile() -> BackendProfile:
    """Create default desktop backend profile."""
    return BackendProfile(
        backend_id="desktop",
        name="Desktop Automation",
        description="Desktop UI automation backend",
        capabilities=[
            CapabilityDescriptor(
                capability_id="window_control",
                name="Window Control",
                description="Control application windows",
                category="window",
                enabled=True,
            ),
            CapabilityDescriptor(
                capability_id="ui_interaction",
                name="UI Interaction",
                description="Interact with UI elements",
                category="interaction",
                enabled=True,
            ),
            CapabilityDescriptor(
                capability_id="text_extraction",
                name="Text Extraction",
                description="Extract text from UI elements",
                category="extraction",
                enabled=True,
            ),
        ],
        max_retries=3,
        timeout=300,
        safety_policy={
            "blocked_apps": [],
            "require_confirmation": [],
        },
        prompt_config={
            "system_prompt": "You are a desktop automation assistant.",
            "max_iterations": 50,
        },
    )


def create_default_registry() -> BackendRegistry:
    """Create a registry with default backend profiles."""
    registry = BackendRegistry()
    registry.register_profile(create_cli_profile())
    registry.register_profile(create_browser_profile())
    registry.register_profile(create_desktop_profile())
    return registry
