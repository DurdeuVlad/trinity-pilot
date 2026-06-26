"""Real MCP client pool used by the Orchestrator to dispatch objectives.

One persistent fastmcp.Client (and underlying subprocess) per domain, spawned
lazily on first use and kept alive for the life of an AsyncTaskOrchestrator
run. Each call_tool still constructs a fresh worker instance server-side
(see browser_server.py/terminal_server.py/desktop_server.py) — this pool only
owns the transport, not worker state.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

# Bounds a single dispatch end-to-end. Without this, a stalled MCP server
# subprocess (e.g. its own LLM tool-call stuck on a transient API outage)
# hangs call_tool() forever with no way for the orchestrator to recover —
# the GUI sits at "Executing..." indefinitely. 900s covers the slowest
# documented legitimate single-objective runs (~950s cold-start cases)
# while still turning a genuine stall into a clean, recoverable failure.
_DISPATCH_TIMEOUT_S = 900.0

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.workers.base import WorkerError, WorkerBlocker
from trinity_pilot.workers.worker_result import WorkerResult

_MCP_DIR = Path(__file__).parent

_SERVER_SCRIPTS: dict[DomainType, str] = {
    DomainType.BROWSER: str(_MCP_DIR / "browser_server.py"),
    DomainType.TERMINAL: str(_MCP_DIR / "terminal_server.py"),
    DomainType.DESKTOP: str(_MCP_DIR / "desktop_server.py"),
}

_TOOL_NAMES: dict[DomainType, str] = {
    DomainType.BROWSER: "browser_navigate",
    DomainType.TERMINAL: "terminal_run",
    DomainType.DESKTOP: "desktop_run",
}


class MCPClientPool:
    """Lazily spawns one MCP server subprocess per domain, reused across
    every objective dispatched to that domain for the life of this pool."""

    def __init__(self) -> None:
        self._clients: dict[DomainType, Client] = {}

    async def _get_client(self, domain: DomainType) -> Client:
        client = self._clients.get(domain)
        if client is None:
            script = _SERVER_SCRIPTS.get(domain)
            if script is None:
                raise WorkerError(f"No MCP server configured for domain '{domain.value}'")
            # MCP's stdio client defaults to a minimal env (PATH only) for
            # security — pass the full parent env through explicitly so the
            # spawned server subprocess gets GEMINI_API_KEY, model overrides, etc.
            transport = PythonStdioTransport(script_path=script, env=dict(os.environ))
            client = Client(transport)
            await client.__aenter__()
            self._clients[domain] = client
        return client

    async def dispatch(self, domain: DomainType, spec: ObjectiveSpec) -> dict[str, Any]:
        """Dispatch one objective through the real MCP server for its domain.

        Mirrors the contract of `await worker.execute(spec)`: returns the
        evidence dict on success, raises WorkerBlocker/WorkerError on failure
        — identical to the in-process path, so callers need no branching.
        """
        tool_name = _TOOL_NAMES.get(domain)
        if tool_name is None:
            raise WorkerError(f"No MCP tool configured for domain '{domain.value}'")

        client = await self._get_client(domain)
        try:
            result = await asyncio.wait_for(
                client.call_tool(tool_name, {"spec_dict": spec.to_dict()}),
                timeout=_DISPATCH_TIMEOUT_S,
            )
        except asyncio.TimeoutError as exc:
            raise WorkerError(
                f"MCP dispatch to '{domain.value}' timed out after {_DISPATCH_TIMEOUT_S:.0f}s"
            ) from exc
        except Exception as exc:  # transport failure, server crash, etc.
            raise WorkerError(f"MCP transport failure dispatching '{domain.value}': {exc}") from exc

        payload = result.data if hasattr(result, "data") else result
        if not isinstance(payload, dict) or "mcp_status" not in payload:
            raise WorkerError(
                f"MCP server returned malformed response for '{domain.value}': {payload!r}"
            )

        status = payload["mcp_status"]
        if status == "ok":
            return payload["evidence"]
        if status == "error":
            raise WorkerError(payload.get("message", "Unknown MCP worker error"))
        if status == "blocker":
            r = payload["result"]
            worker_result = WorkerResult(
                status=r["status"],
                summary=r["summary"],
                evidence=r["evidence"],
                steps_taken=r["steps_taken"],
                tokens_used=r["tokens_used"],
            )
            raise WorkerBlocker(payload["reason"], worker_result)

        raise WorkerError(f"Unrecognized mcp_status '{status}' from '{domain.value}' server")

    async def aclose(self) -> None:
        for client in self._clients.values():
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
        self._clients.clear()
