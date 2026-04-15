"""Backend routing layer with feature flag support.

Routes tasks to MCP or HTTP backends based on feature flags.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Literal, Optional

import httpx

from .artifact_mapper import ArtifactMapper
from .mcp_backend_client import MCPBackendClient

logger = logging.getLogger(__name__)


class BackendRouter:
    """Routes backend tasks to MCP or HTTP based on feature flags."""

    def __init__(self):
        """Initialize backend router with feature flag configuration."""
        self.use_cli_mcp = os.getenv("USE_CLI_MCP", "false").lower() == "true"
        self.use_browser_mcp = os.getenv("USE_BROWSER_MCP", "false").lower() == "true"
        self.use_desktop_mcp = os.getenv("USE_DESKTOP_MCP", "false").lower() == "true"

        self.desktop_port = int(os.getenv("DESKTOP_SERVICE_PORT", "8101"))
        self.cli_port = int(os.getenv("CLI_SERVICE_PORT", "8102"))
        self.browser_port = int(os.getenv("BROWSER_SERVICE_PORT", "8103"))

        self.desktop_url = f"http://127.0.0.1:{self.desktop_port}"
        self.cli_url = f"http://127.0.0.1:{self.cli_port}"
        self.browser_url = f"http://127.0.0.1:{self.browser_port}"

        self._mcp_clients: Dict[str, MCPBackendClient] = {}
        self._artifact_mapper = ArtifactMapper()

        logger.info(
            "Backend router initialized - CLI MCP: %s, Browser MCP: %s, Desktop MCP: %s",
            self.use_cli_mcp,
            self.use_browser_mcp,
            self.use_desktop_mcp,
        )

    def _get_mcp_client(
        self, backend_type: Literal["cli", "browser", "desktop"]
    ) -> MCPBackendClient:
        """
        Get or create MCP client for backend type.
        
        Args:
            backend_type: Backend type
            
        Returns:
            MCPBackendClient instance
        """
        if backend_type in self._mcp_clients:
            return self._mcp_clients[backend_type]

        project_root = Path(__file__).parent.parent.parent

        if backend_type == "cli":
            script_path = project_root / "cli-automation-poc" / "cli_mcp_server.py"
        elif backend_type == "browser":
            script_path = project_root / "browser-gui-automation" / "browser_mcp_server.py"
        elif backend_type == "desktop":
            script_path = project_root / "api-accessibility-poc" / "desktop_mcp_server.py"
        else:
            raise ValueError(f"Unknown backend type: {backend_type}")

        client = MCPBackendClient(backend_type, script_path)
        self._mcp_clients[backend_type] = client
        return client

    async def _execute_via_mcp(
        self,
        backend_type: Literal["cli", "browser", "desktop"],
        description: str,
        context: Optional[str] = None,
    ) -> dict:
        """
        Execute task via MCP backend.
        
        Args:
            backend_type: Backend type
            description: Task description
            context: Optional context
            
        Returns:
            Task result dictionary
        """
        client = self._get_mcp_client(backend_type)

        try:
            await client.connect()

            context_dict = {"description": description}
            if context:
                context_dict["context"] = context

            result = await client.execute_task(
                objective=description,
                context=context_dict,
                timeout=90,
            )

            normalized_artifacts = self._artifact_mapper.normalize_artifacts(
                backend_type, result.get("artifacts", [])
            )

            normalized_metadata = self._artifact_mapper.extract_metadata(
                backend_type, result
            )

            return {
                "result": result.get("result", ""),
                "steps_taken": result.get("steps_taken", 0),
                "error": result.get("error"),
                "artifacts": normalized_artifacts,
                "metadata": normalized_metadata,
            }

        except Exception as e:
            logger.error("MCP execution failed for %s: %s", backend_type, e, exc_info=True)
            return {
                "result": "",
                "steps_taken": 0,
                "error": f"mcp_error: {str(e)}",
                "artifacts": [],
                "metadata": {"backend": backend_type},
            }

    async def _execute_via_http(
        self,
        backend_url: str,
        backend_type: str,
        description: str,
        context: Optional[str] = None,
    ) -> dict:
        """
        Execute task via HTTP backend service.
        
        Args:
            backend_url: Backend service URL
            backend_type: Backend type for logging
            description: Task description
            context: Optional context
            
        Returns:
            Task result dictionary
        """
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{backend_url}/task",
                    json={"description": description, "context": context},
                )
                response.raise_for_status()
                return response.json()
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("%s service connection error: %s", backend_type, e)
            return {
                "result": "",
                "steps_taken": 0,
                "error": f"service_error: {backend_type} service unavailable - {str(e)}",
            }
        except Exception as e:
            logger.error("%s service error: %s", backend_type, e, exc_info=True)
            return {
                "result": "",
                "steps_taken": 0,
                "error": f"service_error: {str(e)}",
            }

    async def desktop_task(
        self, description: str, context: Optional[str] = None
    ) -> dict:
        """
        Execute desktop task via MCP or HTTP based on feature flag.
        
        Args:
            description: Task description
            context: Optional context
            
        Returns:
            Task result dictionary
        """
        if self.use_desktop_mcp:
            logger.debug("Routing desktop task via MCP")
            return await self._execute_via_mcp("desktop", description, context)
        else:
            logger.debug("Routing desktop task via HTTP")
            return await self._execute_via_http(
                self.desktop_url, "Desktop", description, context
            )

    async def cli_task(self, description: str, context: Optional[str] = None) -> dict:
        """
        Execute CLI task via MCP or HTTP based on feature flag.
        
        Args:
            description: Task description
            context: Optional context
            
        Returns:
            Task result dictionary
        """
        if self.use_cli_mcp:
            logger.debug("Routing CLI task via MCP")
            return await self._execute_via_mcp("cli", description, context)
        else:
            logger.debug("Routing CLI task via HTTP")
            return await self._execute_via_http(
                self.cli_url, "CLI", description, context
            )

    async def browser_task(
        self, description: str, context: Optional[str] = None
    ) -> dict:
        """
        Execute browser task via MCP or HTTP based on feature flag.
        
        Args:
            description: Task description
            context: Optional context
            
        Returns:
            Task result dictionary
        """
        if self.use_browser_mcp:
            logger.debug("Routing browser task via MCP")
            return await self._execute_via_mcp("browser", description, context)
        else:
            logger.debug("Routing browser task via HTTP")
            return await self._execute_via_http(
                self.browser_url, "Browser", description, context
            )

    async def cleanup(self):
        """Clean up all MCP client connections."""
        for backend_type, client in self._mcp_clients.items():
            try:
                await client.disconnect()
            except Exception as e:
                logger.warning("Error disconnecting %s MCP client: %s", backend_type, e)

        self._mcp_clients.clear()
