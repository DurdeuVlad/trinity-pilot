"""Integration tests for unified-app MCP routing layer.

Tests backend routing with feature flags, MCP client infrastructure,
artifact handling, and session lifecycle management.
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.artifact_mapper import ArtifactMapper
from orchestrator.backend_router import BackendRouter
from orchestrator.mcp_backend_client import MCPBackendClient


class TestArtifactMapper:
    """Test artifact normalization and mapping."""

    def test_normalize_cli_artifacts(self):
        """Test CLI artifact normalization."""
        artifacts = [
            {
                "artifact_id": "cmd-1",
                "artifact_type": "command",
                "path": "/tmp/output.txt",
            },
            {
                "artifact_id": "log-1",
                "artifact_type": "log",
                "path": None,
            },
        ]

        result = ArtifactMapper.normalize_artifacts("cli", artifacts)

        assert len(result) == 2
        assert result[0] == "/tmp/output.txt"
        assert result[1] == "cli:log:log-1"

    def test_normalize_browser_artifacts(self):
        """Test browser artifact normalization."""
        artifacts = [
            {
                "artifact_id": "screenshot-1",
                "artifact_type": "screenshot",
                "path": "/tmp/screenshot.png",
            },
            {
                "artifact_id": "html-1",
                "artifact_type": "html",
                "path": "/tmp/page.html",
            },
        ]

        result = ArtifactMapper.normalize_artifacts("browser", artifacts)

        assert len(result) == 2
        assert result[0] == "/tmp/screenshot.png"
        assert result[1] == "/tmp/page.html"

    def test_normalize_desktop_artifacts(self):
        """Test desktop artifact normalization."""
        artifacts = [
            {
                "artifact_id": "window-1",
                "artifact_type": "screenshot",
                "path": "/tmp/window.png",
            },
            {
                "artifact_id": "uia-1",
                "artifact_type": "uia_tree",
                "path": None,
            },
        ]

        result = ArtifactMapper.normalize_artifacts("desktop", artifacts)

        assert len(result) == 2
        assert result[0] == "/tmp/window.png"
        assert result[1] == "desktop:uia_tree:uia-1"

    def test_extract_cli_metadata(self):
        """Test CLI metadata extraction."""
        result = {
            "session_id": "test-session",
            "objective_id": "test-obj",
            "metadata": {
                "commands_executed": 3,
                "files_modified": ["/tmp/file1.txt", "/tmp/file2.txt"],
            },
        }

        metadata = ArtifactMapper.extract_metadata("cli", result)

        assert metadata["backend"] == "cli"
        assert metadata["session_id"] == "test-session"
        assert metadata["commands_executed"] == 3
        assert len(metadata["files_modified"]) == 2

    def test_extract_browser_metadata(self):
        """Test browser metadata extraction."""
        result = {
            "session_id": "test-session",
            "objective_id": "test-obj",
            "metadata": {
                "pages_visited": ["https://example.com"],
                "screenshots_captured": 2,
            },
        }

        metadata = ArtifactMapper.extract_metadata("browser", result)

        assert metadata["backend"] == "browser"
        assert metadata["pages_visited"] == ["https://example.com"]
        assert metadata["screenshots_captured"] == 2

    def test_extract_desktop_metadata(self):
        """Test desktop metadata extraction."""
        result = {
            "session_id": "test-session",
            "objective_id": "test-obj",
            "metadata": {
                "windows_interacted": ["Notepad"],
                "uia_elements_accessed": 5,
            },
        }

        metadata = ArtifactMapper.extract_metadata("desktop", result)

        assert metadata["backend"] == "desktop"
        assert metadata["windows_interacted"] == ["Notepad"]
        assert metadata["uia_elements_accessed"] == 5

    def test_map_failure_categories(self):
        """Test failure category mapping."""
        assert (
            ArtifactMapper.map_failure_category("cli", "service unavailable")
            == "backend_unavailable"
        )
        assert (
            ArtifactMapper.map_failure_category("browser", "timeout occurred")
            == "timeout"
        )
        assert (
            ArtifactMapper.map_failure_category("desktop", "blocked by policy")
            == "validator_rejection"
        )
        assert (
            ArtifactMapper.map_failure_category("cli", "execution failed")
            == "execution_failure"
        )

    def test_map_explicit_failure_category(self):
        """Test explicit failure category takes precedence."""
        result = ArtifactMapper.map_failure_category(
            "cli", "some error", failure_category="timeout"
        )
        assert result == "timeout"


class TestBackendRouter:
    """Test backend routing with feature flags."""

    @pytest.mark.asyncio
    async def test_router_initialization_default_flags(self):
        """Test router initializes with default feature flags (all disabled)."""
        with patch.dict(os.environ, {}, clear=True):
            router = BackendRouter()

            assert router.use_cli_mcp is False
            assert router.use_browser_mcp is False
            assert router.use_desktop_mcp is False

    @pytest.mark.asyncio
    async def test_router_initialization_with_flags(self):
        """Test router initializes with feature flags from environment."""
        with patch.dict(
            os.environ,
            {
                "USE_CLI_MCP": "true",
                "USE_BROWSER_MCP": "false",
                "USE_DESKTOP_MCP": "true",
            },
        ):
            router = BackendRouter()

            assert router.use_cli_mcp is True
            assert router.use_browser_mcp is False
            assert router.use_desktop_mcp is True

    @pytest.mark.asyncio
    async def test_cli_task_routes_to_http_when_flag_disabled(self):
        """Test CLI task routes to HTTP when MCP flag is disabled."""
        with patch.dict(os.environ, {"USE_CLI_MCP": "false"}):
            router = BackendRouter()

            with patch.object(
                router, "_execute_via_http", new_callable=AsyncMock
            ) as mock_http:
                mock_http.return_value = {
                    "result": "success",
                    "steps_taken": 1,
                    "error": None,
                }

                result = await router.cli_task("test task")

                mock_http.assert_called_once()
                assert result["result"] == "success"

    @pytest.mark.asyncio
    async def test_cli_task_routes_to_mcp_when_flag_enabled(self):
        """Test CLI task routes to MCP when flag is enabled."""
        with patch.dict(os.environ, {"USE_CLI_MCP": "true"}):
            router = BackendRouter()

            with patch.object(
                router, "_execute_via_mcp", new_callable=AsyncMock
            ) as mock_mcp:
                mock_mcp.return_value = {
                    "result": "success",
                    "steps_taken": 1,
                    "error": None,
                }

                result = await router.cli_task("test task")

                mock_mcp.assert_called_once_with("cli", "test task", None)
                assert result["result"] == "success"

    @pytest.mark.asyncio
    async def test_browser_task_routes_to_http_when_flag_disabled(self):
        """Test browser task routes to HTTP when MCP flag is disabled."""
        with patch.dict(os.environ, {"USE_BROWSER_MCP": "false"}):
            router = BackendRouter()

            with patch.object(
                router, "_execute_via_http", new_callable=AsyncMock
            ) as mock_http:
                mock_http.return_value = {
                    "result": "success",
                    "steps_taken": 1,
                    "error": None,
                }

                result = await router.browser_task("test task")

                mock_http.assert_called_once()
                assert result["result"] == "success"

    @pytest.mark.asyncio
    async def test_browser_task_routes_to_mcp_when_flag_enabled(self):
        """Test browser task routes to MCP when flag is enabled."""
        with patch.dict(os.environ, {"USE_BROWSER_MCP": "true"}):
            router = BackendRouter()

            with patch.object(
                router, "_execute_via_mcp", new_callable=AsyncMock
            ) as mock_mcp:
                mock_mcp.return_value = {
                    "result": "success",
                    "steps_taken": 1,
                    "error": None,
                }

                result = await router.browser_task("test task")

                mock_mcp.assert_called_once_with("browser", "test task", None)
                assert result["result"] == "success"

    @pytest.mark.asyncio
    async def test_desktop_task_routes_to_http_when_flag_disabled(self):
        """Test desktop task routes to HTTP when MCP flag is disabled."""
        with patch.dict(os.environ, {"USE_DESKTOP_MCP": "false"}):
            router = BackendRouter()

            with patch.object(
                router, "_execute_via_http", new_callable=AsyncMock
            ) as mock_http:
                mock_http.return_value = {
                    "result": "success",
                    "steps_taken": 1,
                    "error": None,
                }

                result = await router.desktop_task("test task")

                mock_http.assert_called_once()
                assert result["result"] == "success"

    @pytest.mark.asyncio
    async def test_desktop_task_routes_to_mcp_when_flag_enabled(self):
        """Test desktop task routes to MCP when flag is enabled."""
        with patch.dict(os.environ, {"USE_DESKTOP_MCP": "true"}):
            router = BackendRouter()

            with patch.object(
                router, "_execute_via_mcp", new_callable=AsyncMock
            ) as mock_mcp:
                mock_mcp.return_value = {
                    "result": "success",
                    "steps_taken": 1,
                    "error": None,
                }

                result = await router.desktop_task("test task")

                mock_mcp.assert_called_once_with("desktop", "test task", None)
                assert result["result"] == "success"

    @pytest.mark.asyncio
    async def test_mixed_mode_routing(self):
        """Test mixed mode: CLI via MCP, Browser via HTTP, Desktop via MCP."""
        with patch.dict(
            os.environ,
            {
                "USE_CLI_MCP": "true",
                "USE_BROWSER_MCP": "false",
                "USE_DESKTOP_MCP": "true",
            },
        ):
            router = BackendRouter()

            with patch.object(
                router, "_execute_via_mcp", new_callable=AsyncMock
            ) as mock_mcp, patch.object(
                router, "_execute_via_http", new_callable=AsyncMock
            ) as mock_http:
                mock_mcp.return_value = {"result": "mcp", "steps_taken": 1, "error": None}
                mock_http.return_value = {"result": "http", "steps_taken": 1, "error": None}

                cli_result = await router.cli_task("cli task")
                browser_result = await router.browser_task("browser task")
                desktop_result = await router.desktop_task("desktop task")

                assert cli_result["result"] == "mcp"
                assert browser_result["result"] == "http"
                assert desktop_result["result"] == "mcp"

                assert mock_mcp.call_count == 2
                assert mock_http.call_count == 1

    @pytest.mark.asyncio
    async def test_router_cleanup(self):
        """Test router cleanup disconnects all MCP clients."""
        router = BackendRouter()

        mock_client_1 = AsyncMock()
        mock_client_2 = AsyncMock()

        router._mcp_clients = {
            "cli": mock_client_1,
            "browser": mock_client_2,
        }

        await router.cleanup()

        mock_client_1.disconnect.assert_called_once()
        mock_client_2.disconnect.assert_called_once()
        assert len(router._mcp_clients) == 0


class TestMCPBackendClient:
    """Test MCP backend client infrastructure."""

    @pytest.mark.asyncio
    async def test_client_initialization(self):
        """Test MCP client initializes correctly."""
        script_path = Path("/fake/path/server.py")
        client = MCPBackendClient("cli", script_path)

        assert client.backend_type == "cli"
        assert client.server_script_path == script_path
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_client_connect_failure_missing_script(self):
        """Test client connect fails when script doesn't exist."""
        script_path = Path("/nonexistent/server.py")
        client = MCPBackendClient("cli", script_path)

        with pytest.raises(FileNotFoundError):
            await client.connect()

    @pytest.mark.asyncio
    async def test_client_call_tool_not_connected(self):
        """Test calling tool before connect raises error."""
        script_path = Path("/fake/path/server.py")
        client = MCPBackendClient("cli", script_path)

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.call_tool("health")

    @pytest.mark.asyncio
    async def test_client_health_check_failure(self):
        """Test health check returns False on error."""
        script_path = Path("/fake/path/server.py")
        client = MCPBackendClient("cli", script_path)

        result = await client.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_execute_task_session_cleanup_on_success(self):
        """Test execute_task always closes session on success."""
        script_path = Path("/fake/path/server.py")
        client = MCPBackendClient("cli", script_path)
        client._connected = True

        with patch.object(client, "create_session", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "run_objective", new_callable=AsyncMock) as mock_run, \
             patch.object(client, "list_artifacts", new_callable=AsyncMock) as mock_artifacts, \
             patch.object(client, "close_session", new_callable=AsyncMock) as mock_close:

            mock_create.return_value = {"session_id": "test-session"}
            mock_run.return_value = {
                "result": {
                    "status": "completed",
                    "output": "success",
                    "actions": [{"action": "test"}],
                }
            }
            mock_artifacts.return_value = {"artifacts": []}

            result = await client.execute_task("test objective")

            mock_close.assert_called_once_with("test-session")
            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_task_session_cleanup_on_failure(self):
        """Test execute_task always closes session even on failure."""
        script_path = Path("/fake/path/server.py")
        client = MCPBackendClient("cli", script_path)
        client._connected = True

        with patch.object(client, "create_session", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "run_objective", new_callable=AsyncMock) as mock_run, \
             patch.object(client, "close_session", new_callable=AsyncMock) as mock_close:

            mock_create.return_value = {"session_id": "test-session"}
            mock_run.side_effect = Exception("Test error")

            result = await client.execute_task("test objective")

            mock_close.assert_called_once_with("test-session")
            assert "mcp_error" in result["error"]
            assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execute_task_handles_close_session_failure(self):
        """Test execute_task handles close_session failure gracefully."""
        script_path = Path("/fake/path/server.py")
        client = MCPBackendClient("cli", script_path)
        client._connected = True

        with patch.object(client, "create_session", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "run_objective", new_callable=AsyncMock) as mock_run, \
             patch.object(client, "list_artifacts", new_callable=AsyncMock) as mock_artifacts, \
             patch.object(client, "close_session", new_callable=AsyncMock) as mock_close:

            mock_create.return_value = {"session_id": "test-session"}
            mock_run.return_value = {
                "result": {
                    "status": "completed",
                    "output": "success",
                    "actions": [],
                }
            }
            mock_artifacts.return_value = {"artifacts": []}
            mock_close.side_effect = Exception("Close failed")

            result = await client.execute_task("test objective")

            mock_close.assert_called_once()
            assert result["status"] == "completed"
