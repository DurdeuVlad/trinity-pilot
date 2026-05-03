"""
Deterministic unit tests: domain routing table.

No mocks, no I/O, no network. _resolve_domain is a pure dict lookup
that must always return the same result for the same input.
"""
from __future__ import annotations

import pytest

from orchestrator.orchestrator_core import _resolve_domain


@pytest.mark.parametrize("domain,expected_domain,expected_server", [
    ("cli",     "cli",     "cli_mcp"),
    ("web",     "web",     "browser_mcp"),
    ("browser", "web",     "browser_mcp"),   # alias → web
    ("desktop", "desktop", "desktop_mcp"),
    ("mixed",   "web",     "browser_mcp"),   # mixed collapses to web
    ("MIXED",   "web",     "browser_mcp"),   # case-insensitive
    ("CLI",     "cli",     "cli_mcp"),        # case-insensitive
    ("unknown", "web",     "browser_mcp"),   # unknown → default
    ("",        "web",     "browser_mcp"),   # empty → default
])
def test_resolve_domain(domain: str, expected_domain: str, expected_server: str) -> None:
    resolved_domain, server = _resolve_domain(domain)
    assert resolved_domain == expected_domain, f"domain={domain!r}: expected resolved_domain={expected_domain!r}, got {resolved_domain!r}"
    assert server == expected_server, f"domain={domain!r}: expected server={expected_server!r}, got {server!r}"
