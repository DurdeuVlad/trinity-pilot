"""Trinity Core - Shared backend execution runtime."""

from .models import (
    BackendProfile,
    CapabilityDescriptor,
    RuntimeArtifact,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeFailureCategory,
    RuntimeResult,
    RuntimeSession,
    RuntimeStatus,
    TaskInput,
    TaskResult,
    VerificationCheck,
    VerificationEnvelope,
)
from .runtime_host import RuntimeHost
from .backend_registry import (
    BackendRegistry,
    create_cli_profile,
    create_browser_profile,
    create_desktop_profile,
    create_default_registry,
)

__all__ = [
    "BackendProfile",
    "BackendRegistry",
    "CapabilityDescriptor",
    "RuntimeArtifact",
    "RuntimeEvent",
    "RuntimeEventType",
    "RuntimeFailureCategory",
    "RuntimeHost",
    "RuntimeResult",
    "RuntimeSession",
    "RuntimeStatus",
    "TaskInput",
    "TaskResult",
    "VerificationCheck",
    "VerificationEnvelope",
    "create_browser_profile",
    "create_cli_profile",
    "create_default_registry",
    "create_desktop_profile",
]
