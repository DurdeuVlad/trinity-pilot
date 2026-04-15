"""MCP backend client for unified-app integration.

This module provides a client for connecting to backend MCP servers (CLI, Browser, Desktop)
via stdio transport and managing session lifecycles.
"""

import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPBackendClient:
    """Client for backend MCP servers using stdio transport."""

    def __init__(
        self,
        backend_type: Literal["cli", "browser", "desktop"],
        server_script_path: Path,
    ):
        """
        Initialize MCP backend client.
        
        Args:
            backend_type: Backend type (cli, browser, desktop)
            server_script_path: Path to backend MCP server script
        """
        self.backend_type = backend_type
        self.server_script_path = server_script_path
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.stdio = None
        self.write = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to backend MCP server via stdio."""
        if self._connected:
            return

        if not self.server_script_path.exists():
            raise FileNotFoundError(
                f"MCP server script not found: {self.server_script_path}"
            )

        logger.info("Connecting to %s MCP server at %s", self.backend_type, self.server_script_path)

        # Pass current environment to subprocess (includes API keys, etc.)
        import os
        server_params = StdioServerParameters(
            command="python",
            args=[str(self.server_script_path)],
            env=dict(os.environ),
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport

        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()
        self._connected = True
        logger.info("Connected to %s MCP server", self.backend_type)

    async def disconnect(self) -> None:
        """Disconnect from backend MCP server and clean up resources."""
        if not self._connected:
            return

        try:
            await self.exit_stack.aclose()
            self._connected = False
            logger.info("Disconnected from %s MCP server", self.backend_type)
        except Exception as e:
            logger.warning("Error during disconnect: %s", e)

    async def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Call an MCP tool and return parsed JSON response.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            
        Returns:
            Parsed JSON response dictionary
            
        Raises:
            RuntimeError: If not connected or response format is invalid
        """
        if not self._connected or not self.session:
            raise RuntimeError(
                f"Not connected to {self.backend_type} MCP server. Call connect() first."
            )

        result = await self.session.call_tool(name, arguments or {})

        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, "text"):
                return json.loads(content.text)

        raise RuntimeError(f"Unexpected result format from {name}: {result}")

    async def health_check(self) -> bool:
        """
        Check if backend is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            result = await self.call_tool("health")
            return result.get("ok", False)
        except Exception as e:
            logger.error("Health check failed for %s: %s", self.backend_type, e)
            return False

    async def create_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new backend session.
        
        Args:
            session_id: Optional session ID
            
        Returns:
            Session creation response
        """
        args = {}
        if session_id:
            args["session_id"] = session_id

        return await self.call_tool("create_session", args)

    async def run_objective(
        self,
        session_id: str,
        objective_id: str,
        objective: str,
        context: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute an objective in a backend session.
        
        Args:
            session_id: Session identifier
            objective_id: Objective identifier
            objective: Objective description
            context: Optional context dictionary
            max_retries: Optional max retries
            timeout: Optional timeout in seconds
            
        Returns:
            Objective execution response
        """
        args = {
            "session_id": session_id,
            "objective_id": objective_id,
            "objective": objective,
        }

        if context:
            args["context"] = context
        if max_retries is not None:
            args["max_retries"] = max_retries
        if timeout is not None:
            args["timeout"] = timeout

        return await self.call_tool("run_objective", args)

    async def read_events(
        self, session_id: str, after_sequence: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Read events from a session.
        
        Args:
            session_id: Session identifier
            after_sequence: Optional cursor for incremental reads
            
        Returns:
            Events response
        """
        args = {"session_id": session_id}
        if after_sequence is not None:
            args["after_sequence"] = after_sequence

        return await self.call_tool("read_events", args)

    async def get_status(self, session_id: str) -> Dict[str, Any]:
        """
        Get session status.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Status response
        """
        return await self.call_tool("get_status", {"session_id": session_id})

    async def list_artifacts(self, session_id: str) -> Dict[str, Any]:
        """
        List artifacts from a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Artifacts response
        """
        return await self.call_tool("list_artifacts", {"session_id": session_id})

    async def interrupt(self, session_id: str) -> Dict[str, Any]:
        """
        Interrupt a running session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Interrupt response
        """
        return await self.call_tool("interrupt", {"session_id": session_id})

    async def terminate(self, session_id: str) -> Dict[str, Any]:
        """
        Terminate a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Terminate response
        """
        return await self.call_tool("terminate", {"session_id": session_id})

    async def close_session(self, session_id: str) -> Dict[str, Any]:
        """
        Close a session and clean up resources.
        
        CRITICAL: This must always be called in a finally block to ensure
        two-phase cleanup (runtime + executor) happens correctly.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Close response
        """
        return await self.call_tool("close_session", {"session_id": session_id})

    async def execute_task(
        self,
        objective: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute a complete task with automatic session management.
        
        This is a high-level convenience method that:
        1. Creates a session
        2. Runs the objective
        3. Collects artifacts
        4. Closes the session (in finally block)
        
        Args:
            objective: Task objective description
            context: Optional context dictionary
            timeout: Optional timeout in seconds
            
        Returns:
            Dictionary with result, artifacts, error, and metadata
        """
        session_id = None
        try:
            create_response = await self.create_session()
            session_id = create_response["session_id"]

            objective_id = f"task-{session_id[:8]}"
            run_response = await self.run_objective(
                session_id=session_id,
                objective_id=objective_id,
                objective=objective,
                context=context,
                timeout=timeout,
            )

            result = run_response.get("result", {})
            status = result.get("status", "unknown")

            artifacts_response = await self.list_artifacts(session_id)
            artifacts = artifacts_response.get("artifacts", [])

            return {
                "result": result.get("output", ""),
                "steps_taken": len(result.get("actions", [])),
                "error": None if status == "completed" else result.get("error"),
                "status": status,
                "artifacts": artifacts,
                "metadata": result.get("metadata", {}),
            }

        except Exception as e:
            logger.error("Task execution failed for %s: %s", self.backend_type, e, exc_info=True)
            return {
                "result": "",
                "steps_taken": 0,
                "error": f"mcp_error: {str(e)}",
                "status": "failed",
                "artifacts": [],
                "metadata": {},
            }

        finally:
            if session_id:
                try:
                    await self.close_session(session_id)
                except Exception as e:
                    logger.error(
                        "Failed to close session %s for %s: %s",
                        session_id,
                        self.backend_type,
                        e,
                    )
