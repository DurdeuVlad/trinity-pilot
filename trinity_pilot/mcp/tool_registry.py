"""Machine-readable MCP tool metadata and filtering helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

ToolKind = Literal["sensor", "action", "control", "task"]

VALID_TOOL_KINDS: frozenset[str] = frozenset(("sensor", "action", "control", "task"))


@dataclass(frozen=True)
class ToolMetadata:
    """Explicit policy metadata for one MCP tool."""

    name: str
    server: str
    kind: ToolKind
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("ToolMetadata.name must be non-empty")
        if not self.server.strip():
            raise ValueError("ToolMetadata.server must be non-empty")
        if self.kind not in VALID_TOOL_KINDS:
            raise ValueError(f"Invalid MCP tool kind: {self.kind!r}")


ToolManifest = tuple[ToolMetadata, ...]


def filter_tools(
    tools: Iterable[ToolMetadata],
    allowed_kinds: Iterable[ToolKind],
) -> list[ToolMetadata]:
    """Return tools whose explicit kind is included in allowed_kinds."""
    allowed = set(allowed_kinds)
    invalid = allowed - VALID_TOOL_KINDS
    if invalid:
        raise ValueError(f"Invalid MCP tool kind filter: {sorted(invalid)!r}")
    return [tool for tool in tools if tool.kind in allowed]


def sensor_only_tools(manifests: Iterable[Iterable[ToolMetadata]]) -> list[ToolMetadata]:
    """Build the observer/reviewer view across any number of MCP manifests."""
    return filter_tools(
        (tool for manifest in manifests for tool in manifest),
        allowed_kinds=("sensor",),
    )


def validate_manifest(manifest: Iterable[ToolMetadata]) -> None:
    """Force validation and catch duplicate tool names within one server manifest."""
    seen: set[str] = set()
    for tool in manifest:
        if tool.name in seen:
            raise ValueError(f"Duplicate MCP tool in {tool.server}: {tool.name}")
        seen.add(tool.name)
