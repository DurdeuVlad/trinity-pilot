"""MCP Server for controlling the Orchestrator Desktop App.

This server provides tools to:
- Submit tasks to the orchestrator
- Monitor task execution status
- Query task history
- Control orchestrator settings
- Inspect checkpoints and resilience features
- Read execution logs and plans from the database
- Read flight records from disk
"""
import asyncio
import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator-mcp")

# Import orchestrator components
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.database import HistoryManager, TaskStatus
from orchestrator.checkpoint_manager import CheckpointManager
from orchestrator.settings_manager import SettingsManager
from orchestrator.event_bus import get_event_bus
from mcp_server.app_command_pipe import CommandSurfaceUnavailable, send_command_via_pipe
from mcp_server.live_test_cases import LiveTestCaseLibrary
from mcp_server.task_submission_pipe import PipeSubmissionUnavailable, submit_task_via_pipe

_RUNTIME_DIR = Path(__file__).parent.parent / "_runtime"
_DB_PATH = _RUNTIME_DIR / "orchestrator_history.db"
_FLIGHT_REPORTS_DIR = _RUNTIME_DIR / "flight_reports"


def _serialize_task_record(task: Any) -> dict[str, Any]:
    """Convert ORM-backed task objects into JSON-friendly dictionaries."""
    status = getattr(task, "status", None)
    if hasattr(status, "value"):
        status = status.value

    result_data = getattr(task, "result_data", None)
    if isinstance(result_data, str) and result_data.strip():
        try:
            result_data = json.loads(result_data)
        except Exception:
            pass

    final_status = None
    if isinstance(result_data, dict):
        final_status = result_data.get("status") or result_data.get("category")
    if final_status is None and status == "completed":
        final_status = "success"

    def _maybe_iso(value: Any) -> Any:
        return value.isoformat() if hasattr(value, "isoformat") else value

    return {
        "task_id": getattr(task, "task_id", ""),
        "description": getattr(task, "description", ""),
        "domain": getattr(task, "domain", ""),
        "status": status or "unknown",
        "created_at": _maybe_iso(getattr(task, "created_at", None)),
        "started_at": _maybe_iso(getattr(task, "started_at", None)),
        "completed_at": _maybe_iso(getattr(task, "completed_at", None)),
        "confidence": getattr(task, "confidence", None),
        "estimated_duration": getattr(task, "estimated_duration", None),
        "error_message": getattr(task, "error_message", None),
        "result_data": result_data,
        "final_status": final_status,
    }


class OrchestratorMCPServer:
    """MCP Server for orchestrator control."""

    def __init__(self):
        self.server = Server("orchestrator-control")
        self.history_manager = HistoryManager()
        self.checkpoint_manager = CheckpointManager(checkpoint_dir=_RUNTIME_DIR / "checkpoints")
        self.settings_manager = SettingsManager()
        self.event_bus = get_event_bus()
        self.active_tasks = {}
        self.case_library = LiveTestCaseLibrary()

        # Register tools
        self._register_tools()

    def _register_tools(self):
        """Register all MCP tools."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools."""
            return [
                Tool(
                    name="submit_task",
                    description="Submit a new task to the orchestrator",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "Natural language task description"
                            },
                            "domain": {
                                "type": "string",
                                "description": "Task execution domain",
                                "enum": ["cli", "browser", "web", "desktop", "mixed"],
                                "default": "mixed"
                            }
                        },
                        "required": ["description"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_task_status",
                    description="Get the current status of a task by ID or 'latest'",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "Task ID to query, or 'latest' for most recent task"
                            }
                        },
                        "required": ["task_id"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="list_tasks",
                    description="List tasks from history with optional status filter",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of tasks to return (default 10)",
                                "default": 10,
                                "minimum": 1,
                                "maximum": 100
                            },
                            "status": {
                                "type": "string",
                                "description": "Filter by task status",
                                "enum": ["completed", "failed", "running", "cancelled", "pending"]
                            }
                        },
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_task_details",
                    description="Get detailed information about a task including all execution steps",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "Task ID to query, or 'latest' for most recent task"
                            }
                        },
                        "required": ["task_id"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_execution_log",
                    description="Read the full execution log for a task including all status messages and events",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "Task ID, or 'latest' for the most recent task"
                            }
                        },
                        "required": ["task_id"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_execution_plan",
                    description="Read the execution plan for a task including objectives, steps, and AI confidence",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "Task ID, or 'latest' for the most recent task"
                            }
                        },
                        "required": ["task_id"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="list_cases",
                    description="List canonical live test cases from trinity-pilot/docs/live-test-cases/",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="submit_case",
                    description="Submit a canonical live test case by case_id or path",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "case_id": {
                                "type": "string",
                                "description": "Canonical case id such as TC-BROWSER-01 or an absolute case file path"
                            }
                        },
                        "required": ["case_id"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_live_events",
                    description="Read incremental live events for a task from the desktop app command surface",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "Task ID, or 'latest' for the most recent task"
                            },
                            "after_sequence": {
                                "type": "integer",
                                "description": "Cursor for incremental event reads",
                                "default": 0,
                                "minimum": 0
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum events to return",
                                "default": 200,
                                "minimum": 1,
                                "maximum": 1000
                            }
                        },
                        "required": ["task_id"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_artifact_bundle",
                    description="Return the normalized artifact bundle for a task",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "Task ID, or 'latest' for the most recent task"
                            }
                        },
                        "required": ["task_id"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="list_flight_records",
                    description="List flight records (execution reports) from disk with metadata",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of records to list (newest first, default 20)",
                                "default": 20,
                                "minimum": 1,
                                "maximum": 100
                            }
                        },
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="read_flight_record",
                    description="Read the full content of a specific flight record file from disk",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "filename": {
                                "type": "string",
                                "description": "Flight record filename (from list_flight_records output)"
                            }
                        },
                        "required": ["filename"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_latest_flight_record",
                    description="Read the most recently modified flight record from disk",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="list_checkpoints",
                    description="List all checkpoints for a task by ID or 'latest'",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "Task ID to query checkpoints for, or 'latest' for most recent task"
                            }
                        },
                        "required": ["task_id"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_checkpoint_details",
                    description="Get details of a specific checkpoint including context and state",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "checkpoint_id": {
                                "type": "string",
                                "description": "Checkpoint ID to query (from list_checkpoints output)"
                            }
                        },
                        "required": ["checkpoint_id"],
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_settings",
                    description="Get current orchestrator settings (API keys are redacted)",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="update_settings",
                    description="Update orchestrator settings with new key-value pairs",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "settings": {
                                "type": "object",
                                "description": "Settings to update as key-value pairs"
                            }
                        },
                        "required": ["settings"],
                        "additionalProperties": False
                    }
                )
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            """Handle tool calls."""
            try:
                if name == "submit_task":
                    return await self._submit_task(arguments)
                elif name == "get_task_status":
                    return await self._get_task_status(arguments)
                elif name == "list_tasks":
                    return await self._list_tasks(arguments)
                elif name == "get_task_details":
                    return await self._get_task_details(arguments)
                elif name == "get_execution_log":
                    return await self._get_execution_log(arguments)
                elif name == "get_execution_plan":
                    return await self._get_execution_plan(arguments)
                elif name == "list_cases":
                    return await self._list_cases_catalog(arguments)
                elif name == "submit_case":
                    return await self._submit_case(arguments)
                elif name == "get_live_events":
                    return await self._get_live_events(arguments)
                elif name == "get_artifact_bundle":
                    return await self._get_artifact_bundle(arguments)
                elif name == "list_flight_records":
                    return await self._list_flight_records(arguments)
                elif name == "read_flight_record":
                    return await self._read_flight_record(arguments)
                elif name == "get_latest_flight_record":
                    return await self._get_latest_flight_record(arguments)
                elif name == "list_checkpoints":
                    return await self._list_checkpoints(arguments)
                elif name == "get_checkpoint_details":
                    return await self._get_checkpoint_details(arguments)
                elif name == "get_settings":
                    return await self._get_settings(arguments)
                elif name == "update_settings":
                    return await self._update_settings(arguments)
                else:
                    return [TextContent(
                        type="text",
                        text=f"Unknown tool: {name}"
                    )]
            except Exception as e:
                logger.error(f"Error calling tool {name}: {e}")
                return [TextContent(
                    type="text",
                    text=f"Error: {str(e)}"
                )]

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _resolve_task_id(self, task_id: str) -> str | None:
        """Resolve 'latest' to the most recent task_id from the DB."""
        if task_id != "latest":
            return task_id
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            row = conn.execute(
                "SELECT task_id FROM task_history ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def _db_rows(self, query: str, params: tuple = ()) -> list[dict]:
        """Run a query against the history DB and return rows as dicts."""
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    async def _wait_for_submitted_task(
        self,
        description: str,
        domain: str,
        timeout_seconds: float = 3.0,
    ) -> dict | None:
        """Wait briefly for a just-submitted task to appear in history."""
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            recent_tasks = self.history_manager.list_tasks(limit=10)
            for task in recent_tasks:
                if task.get("description") == description and task.get("domain") == domain:
                    return task
            await asyncio.sleep(0.1)
        return None

    # ── Tool implementations ─────────────────────────────────────────────────

    async def _submit_task(self, args: dict) -> list[TextContent]:
        """Submit a new task to the orchestrator via event bus."""
        if not args:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "Arguments cannot be None or empty"
            }, indent=2))]

        description = args.get("description")
        if not description:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "Task description is required"
            }, indent=2))]

        domain = args.get("domain", "mixed")

        domain_map = {
            "mixed": "Auto-detect",
            "cli": "cli",
            "browser": "web",
            "web": "web",
            "desktop": "desktop"
        }
        mapped_domain = domain_map.get(domain.lower(), "Auto-detect")

        try:
            request_id = f"mcp-{uuid.uuid4().hex[:16]}"
            pipe_result = self._submit_task_via_pipe(
                request_id=request_id,
                description=description,
                mapped_domain=mapped_domain,
            )
            if pipe_result is not None:
                if pipe_result.get("ok"):
                    result = {
                        "success": True,
                        "data": {
                            "task_id": pipe_result.get("task_id"),
                            "description": pipe_result.get("description", description),
                            "domain": pipe_result.get("domain", mapped_domain),
                            "status": pipe_result.get("status", "submitted"),
                        },
                        "error_code": None,
                        "message": "Task submitted to orchestrator. Use get_task_status to monitor progress.",
                    }
                else:
                    result = {
                        "success": False,
                        "data": None,
                        "error_code": pipe_result.get("error_code", "TASK_NOT_OBSERVED"),
                        "message": pipe_result.get("message", "Task submission failed."),
                    }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            self.event_bus.task_submitted.emit(description, mapped_domain)
            task = await self._wait_for_submitted_task(description, mapped_domain)

            if task:
                result = {
                    "success": True,
                    "data": {
                        "task_id": task["task_id"],
                        "description": task["description"],
                        "domain": task["domain"],
                        "status": task["status"],
                    },
                    "error_code": None,
                    "message": "Task submitted to orchestrator. Use get_task_status to monitor progress."
                }
            else:
                result = {
                    "success": False,
                    "data": None,
                    "error_code": "TASK_NOT_OBSERVED",
                    "message": (
                        "Task emit did not produce a persisted task record. "
                        "Ensure MCP is running in/connected to the active GUI app process."
                    ),
                }

            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except Exception as e:
            logger.error(f"Error submitting task: {e}")
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "data": None,
                    "error_code": "EXCEPTION",
                    "message": f"Failed to submit task: {str(e)}"
                }, indent=2)
            )]

    async def _list_cases_catalog(self, args: dict) -> list[TextContent]:
        """List canonical live test cases."""
        try:
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": {"cases": self.case_library.list_cases()},
                "error_code": None,
                "message": "Canonical live test cases retrieved successfully"
            }, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "EXCEPTION",
                "message": f"Error listing cases: {str(e)}"
            }, indent=2))]

    async def _submit_case(self, args: dict) -> list[TextContent]:
        """Submit a canonical live test case via the app command surface."""
        case_id = (args or {}).get("case_id")
        if not case_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "case_id is required"
            }, indent=2))]
        try:
            response = send_command_via_pipe("submit-case", args={"case_id": case_id})
            return [TextContent(type="text", text=json.dumps({
                "success": bool(response.get("ok")),
                "data": response.get("payload"),
                "error_code": response.get("error_code"),
                "message": response.get("message") or "Case submitted"
            }, indent=2))]
        except CommandSurfaceUnavailable as e:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "COMMAND_SURFACE_UNAVAILABLE",
                "message": str(e)
            }, indent=2))]

    async def _get_live_events(self, args: dict) -> list[TextContent]:
        """Fetch incremental live events through the app command surface."""
        task_id = (args or {}).get("task_id")
        if not task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "task_id is required"
            }, indent=2))]
        try:
            response = send_command_via_pipe(
                "stream-events",
                args={
                    "task_id": task_id,
                    "after_sequence": int((args or {}).get("after_sequence", 0)),
                    "limit": int((args or {}).get("limit", 200)),
                },
            )
            return [TextContent(type="text", text=json.dumps({
                "success": bool(response.get("ok")),
                "data": response.get("payload"),
                "error_code": response.get("error_code"),
                "message": response.get("message") or "Live events retrieved successfully"
            }, indent=2))]
        except CommandSurfaceUnavailable as e:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "COMMAND_SURFACE_UNAVAILABLE",
                "message": str(e)
            }, indent=2))]

    async def _get_artifact_bundle(self, args: dict) -> list[TextContent]:
        """Return the normalized artifact bundle for one task."""
        task_id = (args or {}).get("task_id")
        if not task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "task_id is required"
            }, indent=2))]
        try:
            response = send_command_via_pipe("get-artifact-bundle", args={"task_id": task_id})
            return [TextContent(type="text", text=json.dumps({
                "success": bool(response.get("ok")),
                "data": response.get("payload"),
                "error_code": response.get("error_code"),
                "message": response.get("message") or "Artifact bundle retrieved successfully"
            }, indent=2))]
        except CommandSurfaceUnavailable as e:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "COMMAND_SURFACE_UNAVAILABLE",
                "message": str(e)
            }, indent=2))]

    def _submit_task_via_pipe(
        self,
        *,
        request_id: str,
        description: str,
        mapped_domain: str,
    ) -> dict[str, Any] | None:
        """Submit over named pipe when GUI listener is available.

        Returns:
            dict payload from listener when transport is reachable.
            None when transport is unavailable (fallback path).
        """
        try:
            return submit_task_via_pipe(
                request_id=request_id,
                description=description,
                domain=mapped_domain,
                timeout_seconds=6.0,
            )
        except PipeSubmissionUnavailable:
            return None

    async def _get_task_status(self, args: dict) -> list[TextContent]:
        """Get task status."""
        if not args:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "Arguments cannot be None or empty"
            }, indent=2))]

        requested_task_id = args.get("task_id")
        if not requested_task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "Task ID is required"
            }, indent=2))]

        task_id = self._resolve_task_id(requested_task_id)

        if not task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": "No tasks found in history."
            }, indent=2))]

        if task_id in self.active_tasks:
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": self.active_tasks[task_id],
                "error_code": None,
                "message": "Task status retrieved from active tasks"
            }, indent=2))]

        try:
            task = self.history_manager.get_task(task_id)
            if task:
                task_data = _serialize_task_record(task)
                task_data["task_id"] = task_data.get("task_id") or task_id
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "data": task_data,
                    "error_code": None,
                    "message": "Task status retrieved successfully"
                }, indent=2))]
        except Exception as e:
            logger.error(f"Error getting task status: {e}")

        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "data": None,
            "error_code": "NOT_FOUND",
            "message": f"Task not found: {task_id}"
        }, indent=2))]

    async def _list_tasks(self, args: dict) -> list[TextContent]:
        """List tasks from history."""
        limit = args.get("limit", 10)
        status_filter = args.get("status")

        try:
            tasks = self.history_manager.list_tasks(limit=limit)
            if status_filter:
                tasks = [t for t in tasks if t.get("status") == status_filter]
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": {"count": len(tasks), "tasks": tasks},
                "error_code": None,
                "message": f"Retrieved {len(tasks)} task(s)"
            }, indent=2))]
        except Exception as e:
            logger.error(f"Error listing tasks: {e}")
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "EXCEPTION",
                "message": f"Error listing tasks: {str(e)}"
            }, indent=2))]

    async def _get_task_details(self, args: dict) -> list[TextContent]:
        """Get detailed task information."""
        if not args:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "Arguments cannot be None or empty"
            }, indent=2))]

        requested_task_id = args.get("task_id")
        if not requested_task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "Task ID is required"
            }, indent=2))]

        task_id = self._resolve_task_id(requested_task_id)

        if not task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": "No tasks found in history."
            }, indent=2))]

        try:
            task = self.history_manager.get_task(task_id)
            if not task:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "data": None,
                    "error_code": "NOT_FOUND",
                    "message": f"Task not found: {task_id}"
                }, indent=2))]

            steps = self.history_manager.get_task_steps(task_id)
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": {"task": _serialize_task_record(task), "steps": steps, "step_count": len(steps)},
                "error_code": None,
                "message": f"Retrieved task details with {len(steps)} step(s)"
            }, indent=2, default=str))]
        except Exception as e:
            logger.error(f"Error getting task details: {e}")
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "EXCEPTION",
                "message": f"Error: {str(e)}"
            }, indent=2))]

    async def _get_execution_log(self, args: dict) -> list[TextContent]:
        """Read the full execution log (status messages) for a task from the DB."""
        task_id = self._resolve_task_id(args["task_id"])
        if not task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": "No tasks found in history."
            }, indent=2))]

        # Pull task summary
        rows = self._db_rows(
            "SELECT task_id, description, status, created_at, completed_at, error_message "
            "FROM task_history WHERE task_id = ?",
            (task_id,)
        )
        if not rows:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": f"Task not found: {task_id}"
            }, indent=2))]

        task_row = rows[0]

        # Pull execution steps with their result_data (which contains per-step logs)
        steps = self._db_rows(
            "SELECT step_number, description, status, started_at, completed_at, "
            "result_data, error_message FROM execution_steps WHERE task_id = ? "
            "ORDER BY step_number",
            (task_id,)
        )

        # Decode result_data JSON blobs
        for s in steps:
            if s.get("result_data"):
                try:
                    s["result_data"] = json.loads(s["result_data"])
                except Exception:
                    pass

        log_data = {
            "task_id": task_id,
            "description": task_row["description"],
            "status": task_row["status"],
            "created_at": task_row["created_at"],
            "completed_at": task_row["completed_at"],
            "error_message": task_row["error_message"],
            "execution_steps": steps,
            "step_count": len(steps),
        }
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "data": log_data,
            "error_code": None,
            "message": f"Retrieved execution log with {len(steps)} step(s)"
        }, indent=2, default=str))]

    async def _get_execution_plan(self, args: dict) -> list[TextContent]:
        """Read the execution plan (objectives + step statuses) for a task."""
        task_id = self._resolve_task_id(args["task_id"])
        if not task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": "No tasks found in history."
            }, indent=2))]

        rows = self._db_rows(
            "SELECT task_id, description, domain, status, plan_steps, "
            "estimated_duration, confidence, created_at FROM task_history WHERE task_id = ?",
            (task_id,)
        )
        if not rows:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": f"Task not found: {task_id}"
            }, indent=2))]

        row = rows[0]
        plan_steps_raw = row.get("plan_steps") or "[]"
        try:
            plan_steps = json.loads(plan_steps_raw)
        except Exception:
            plan_steps = [plan_steps_raw]

        # Get step statuses
        steps = self._db_rows(
            "SELECT step_number, description, status, error_message "
            "FROM execution_steps WHERE task_id = ? ORDER BY step_number",
            (task_id,)
        )

        plan_data = {
            "task_id": task_id,
            "description": row["description"],
            "domain": row["domain"],
            "task_status": row["status"],
            "created_at": row["created_at"],
            "plan": {
                "objectives": plan_steps,
                "estimated_duration_seconds": row["estimated_duration"],
                "ai_confidence": row["confidence"],
            },
            "step_statuses": steps,
        }
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "data": plan_data,
            "error_code": None,
            "message": "Retrieved execution plan successfully"
        }, indent=2, default=str))]

    async def _list_flight_records(self, args: dict) -> list[TextContent]:
        """List flight record files on disk."""
        limit = args.get("limit", 20)

        if not _FLIGHT_REPORTS_DIR.exists():
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": {
                    "flight_reports_dir": str(_FLIGHT_REPORTS_DIR),
                    "exists": False,
                    "count": 0,
                    "records": []
                },
                "error_code": None,
                "message": "Flight reports directory does not exist"
            }, indent=2))]

        records = []
        for path in sorted(_FLIGHT_REPORTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.is_file():
                stat = path.stat()
                records.append({
                    "filename": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "path": str(path),
                })
            if len(records) >= limit:
                break

        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "data": {
                "flight_reports_dir": str(_FLIGHT_REPORTS_DIR),
                "count": len(records),
                "records": records
            },
            "error_code": None,
            "message": f"Retrieved {len(records)} flight record(s)"
        }, indent=2))]

    async def _read_flight_record(self, args: dict) -> list[TextContent]:
        """Read a specific flight record file."""
        filename = args["filename"]
        # Prevent path traversal
        path = (_FLIGHT_REPORTS_DIR / Path(filename).name).resolve()
        if not str(path).startswith(str(_FLIGHT_REPORTS_DIR.resolve())):
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "Invalid filename (path traversal detected)"
            }, indent=2))]

        if not path.exists():
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": f"File not found: {filename}"
            }, indent=2))]

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": {
                    "filename": path.name,
                    "size_bytes": path.stat().st_size,
                    "content": content
                },
                "error_code": None,
                "message": "Flight record retrieved successfully"
            }, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "EXCEPTION",
                "message": f"Error reading file: {e}"
            }, indent=2))]

    async def _get_latest_flight_record(self, args: dict) -> list[TextContent]:
        """Read the most recently modified flight record."""
        if not _FLIGHT_REPORTS_DIR.exists():
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": "Flight reports directory does not exist."
            }, indent=2))]

        files = sorted(
            (p for p in _FLIGHT_REPORTS_DIR.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if not files:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": "No flight records found."
            }, indent=2))]

        path = files[0]
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": {
                    "filename": path.name,
                    "size_bytes": path.stat().st_size,
                    "content": content
                },
                "error_code": None,
                "message": "Latest flight record retrieved successfully"
            }, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "EXCEPTION",
                "message": f"Error reading file: {e}"
            }, indent=2))]

    async def _list_checkpoints(self, args: dict) -> list[TextContent]:
        """List checkpoints for a task."""
        if not args:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "Arguments cannot be None or empty"
            }, indent=2))]

        requested_task_id = args.get("task_id")
        if not requested_task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "INVALID_ARG",
                "message": "Task ID is required"
            }, indent=2))]

        task_id = self._resolve_task_id(requested_task_id)

        if not task_id:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "NOT_FOUND",
                "message": "No tasks found in history."
            }, indent=2))]

        try:
            checkpoint_dir = self.checkpoint_manager.checkpoint_dir
            checkpoints = list(checkpoint_dir.glob(f"{task_id}_*.json"))

            checkpoint_list = []
            for cp_path in checkpoints:
                checkpoint_list.append({
                    "checkpoint_id": cp_path.stem,
                    "size_bytes": cp_path.stat().st_size,
                    "created_at": cp_path.stat().st_mtime
                })

            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": {
                    "task_id": task_id,
                    "checkpoint_count": len(checkpoint_list),
                    "checkpoints": checkpoint_list
                },
                "error_code": None,
                "message": f"Retrieved {len(checkpoint_list)} checkpoint(s)"
            }, indent=2))]
        except Exception as e:
            logger.error(f"Error listing checkpoints: {e}")
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "EXCEPTION",
                "message": f"Error: {str(e)}"
            }, indent=2))]

    async def _get_checkpoint_details(self, args: dict) -> list[TextContent]:
        """Get checkpoint details."""
        checkpoint_id = args["checkpoint_id"]

        try:
            context, objective_index = self.checkpoint_manager.load_checkpoint(checkpoint_id)
            checkpoint_data = {
                "checkpoint_id": checkpoint_id,
                "objective_index": objective_index,
                "context": {
                    "objective": context.objective,
                    "module_results_count": len(context.module_results),
                    "error_history_count": len(context.error_history),
                    "learned_constraints": context.learned_constraints,
                    "retry_count": context.retry_count,
                    "fallback_level": context.fallback_level
                }
            }
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": checkpoint_data,
                "error_code": None,
                "message": "Checkpoint details retrieved successfully"
            }, indent=2))]
        except Exception as e:
            logger.error(f"Error getting checkpoint details: {e}")
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "EXCEPTION",
                "message": f"Error: {str(e)}"
            }, indent=2))]

    async def _get_settings(self, args: dict) -> list[TextContent]:
        """Get current settings."""
        import os as _os
        try:
            settings = self.settings_manager.load()
            # Redact API keys for safety
            safe = {k: ("***" if "key" in k.lower() and v else v) for k, v in settings.items()}
            # Append smart-cache configuration (env-var driven; runtime stats are
            # in-process and not available here)
            safe["gemini_cache"] = {
                "enabled": _os.getenv("GEMINI_MOCK", "") == "",
                "cache_dir": _os.getenv(
                    "GEMINI_CACHE_DIR", "_runtime/cache/gemini_responses"
                ),
                "default_ttl_seconds": int(_os.getenv("GEMINI_CACHE_TTL_SECONDS", "3600")),
                "action_ttl_seconds": int(_os.getenv("GEMINI_CACHE_ACTION_TTL_SECONDS", "300")),
                "bypass_threshold": int(_os.getenv("GEMINI_CACHE_BYPASS_THRESHOLD", "2")),
                "max_size_bytes": int(_os.getenv(
                    "GEMINI_CACHE_MAX_SIZE_BYTES", str(500 * 1024 * 1024)
                )),
                "note": (
                    "Runtime hit/miss stats are tracked in-process by SmartCache. "
                    "See GeminiProvider.cache_stats for live counters."
                ),
            }
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": safe,
                "error_code": None,
                "message": "Settings retrieved successfully (API keys redacted)"
            }, indent=2))]
        except Exception as e:
            logger.error(f"Error getting settings: {e}")
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "EXCEPTION",
                "message": f"Error: {str(e)}"
            }, indent=2))]

    async def _update_settings(self, args: dict) -> list[TextContent]:
        """Update settings."""
        try:
            new_settings = args["settings"]
            current_settings = self.settings_manager.load()
            current_settings.update(new_settings)
            self.settings_manager.save(current_settings)
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "data": {"updated_settings": new_settings},
                "error_code": None,
                "message": "Settings updated successfully"
            }, indent=2))]
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "data": None,
                "error_code": "EXCEPTION",
                "message": f"Error: {str(e)}"
            }, indent=2))]

    async def run(self):
        """Run the MCP server."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


async def main():
    """Main entry point."""
    server = OrchestratorMCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
