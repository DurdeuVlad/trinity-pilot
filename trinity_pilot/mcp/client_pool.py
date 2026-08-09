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

from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.workers.base import WorkerBlocker, WorkerError
from trinity_pilot.workers.worker_result import WorkerResult

# Bounds a single dispatch end-to-end. Without this, a stalled MCP server
# subprocess hangs call_tool() forever. Per-objective metadata.timeout_seconds
# overrides these domain defaults when set by the planner.
_DISPATCH_TIMEOUT_DEFAULTS: dict[DomainType, float] = {
    DomainType.DESKTOP: 180.0,
    DomainType.BROWSER: 600.0,
    DomainType.TERMINAL: 120.0,
}

_MCP_DIR = Path(__file__).parent
# MCP server subprocesses are spawned as bare scripts (`python desktop_server.py`),
# not via `-m`, so sys.path[0] is trinity_pilot/mcp/, not the repo root — `import
# trinity_pilot` inside them fails unless the package happens to be pip-installed.
# Ensure the repo root is always on PYTHONPATH for spawned servers, regardless of
# how (or from where) the parent process itself was launched.
_REPO_ROOT = _MCP_DIR.parent.parent


def _spawn_env() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    repo_root = str(_REPO_ROOT)
    parts = [p for p in existing.split(os.pathsep) if p]
    if repo_root not in parts:
        parts.insert(0, repo_root)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env

_SERVER_SCRIPTS: dict[DomainType, str] = {
    DomainType.BROWSER: str(_MCP_DIR / "browser_server.py"),
    DomainType.TERMINAL: str(_MCP_DIR / "terminal_server.py"),
    DomainType.DESKTOP: str(_MCP_DIR / "desktop_server.py"),
}
_SENSOR_SERVER_SCRIPT = str(_MCP_DIR / "sensor_server.py")

_TOOL_NAMES: dict[DomainType, str] = {
    DomainType.BROWSER: "browser_navigate",
    DomainType.TERMINAL: "terminal_run",
    DomainType.DESKTOP: "desktop_run",
}


class MCPClientPool:
    """Lazily spawns one MCP server subprocess per domain, reused across
    every objective dispatched to that domain for the life of this pool."""

    def __init__(self) -> None:
        # Servers are independent subprocesses and do not import Settings, so
        # explicitly load the project .env before copying the process env.
        load_dotenv()
        self._clients: dict[DomainType, Client] = {}
        self._sensor_client: Client | None = None

    async def _get_client(self, domain: DomainType) -> Client:
        client = self._clients.get(domain)
        if client is None:
            script = _SERVER_SCRIPTS.get(domain)
            if script is None:
                raise WorkerError(f"No MCP server configured for domain '{domain.value}'")
            # MCP's stdio client defaults to a minimal env (PATH only) for
            # security — pass the full parent env through explicitly so the
            # spawned server subprocess gets GEMINI_API_KEY, model overrides, etc.
            transport = PythonStdioTransport(script_path=script, env=_spawn_env())
            client = Client(transport)
            await client.__aenter__()
            self._clients[domain] = client
        return client

    async def _evict_client(self, domain: DomainType) -> None:
        """Drop a cached client so the next dispatch spawns a fresh subprocess.

        Without this, a server subprocess that crashed or wedged mid-run stays
        cached forever — every subsequent objective for that domain would keep
        hitting the same dead transport for the rest of the orchestrator run.
        """
        client = self._clients.pop(domain, None)
        if client is not None:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass

    async def dispatch(self, domain: DomainType, spec: ObjectiveSpec) -> dict[str, Any]:
        """Dispatch one objective through the real MCP server for its domain.

        Mirrors the contract of `await worker.execute(spec)`: returns the
        evidence dict on success, raises WorkerBlocker/WorkerError on failure
        — identical to the in-process path, so callers need no branching.

        On a connect/transport failure, evicts the (possibly dead) cached
        client and retries once against a freshly spawned subprocess before
        giving up — a single crashed server process should degrade one
        objective, not permanently break its whole domain for the run.
        """
        tool_name = _TOOL_NAMES.get(domain)
        if tool_name is None:
            raise WorkerError(f"No MCP tool configured for domain '{domain.value}'")

        default_timeout = _DISPATCH_TIMEOUT_DEFAULTS.get(domain, 180.0)
        dispatch_timeout = float(spec.metadata.get("timeout_seconds", default_timeout))

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                client = await self._get_client(domain)
            except WorkerError:
                raise
            except Exception as exc:
                last_exc = exc
                await self._evict_client(domain)
                continue
            try:
                result = await asyncio.wait_for(
                    client.call_tool(tool_name, {"spec_dict": spec.to_dict()}),
                    timeout=dispatch_timeout,
                )
                last_exc = None
                break
            except asyncio.TimeoutError as exc:
                # A timeout doesn't necessarily mean the transport is dead
                # (the server may just be slow on this one call) — don't evict,
                # just fail this dispatch.
                raise WorkerError(
                    f"MCP dispatch to '{domain.value}' timed out after {dispatch_timeout:.0f}s"
                ) from exc
            except Exception as exc:  # transport failure, server crash, etc.
                last_exc = exc
                await self._evict_client(domain)
                continue

        if last_exc is not None:
            raise WorkerError(
                f"MCP transport failure dispatching '{domain.value}' "
                f"(retried once with a fresh server process): {last_exc}"
            ) from last_exc

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

    async def call_sensor(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a read-only sensor tool for independent review verification."""
        if self._sensor_client is None:
            transport = PythonStdioTransport(script_path=_SENSOR_SERVER_SCRIPT, env=_spawn_env())
            self._sensor_client = Client(transport)
            await self._sensor_client.__aenter__()
        result = await self._sensor_client.call_tool(tool_name, arguments)
        payload = result.data if hasattr(result, "data") else result
        if not isinstance(payload, dict):
            raise WorkerError(f"Sensor '{tool_name}' returned malformed response: {payload!r}")
        return payload

    async def aclose(self) -> None:
        for client in self._clients.values():
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
        self._clients.clear()
        if self._sensor_client is not None:
            try:
                await self._sensor_client.__aexit__(None, None, None)
            except Exception:
                pass
            self._sensor_client = None
