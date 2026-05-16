from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from google.genai import types as genai_types

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.llm.base import LLMProvider
from trinity_pilot.workers.agentic_mixin import (
    AgenticWorkerMixin,
    _finish_decl,
    _make_tool,
    _report_blocking_decl,
)
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence

_MAX_OUTPUT_CHARS = 10_000
_CMD_TIMEOUT = 30.0

_TERMINAL_SYSTEM = """\
You are a terminal automation agent on Windows (PowerShell 5.1).
Given a goal, use the available tools to accomplish it step by step.

Available tools:
- run_command: Execute a PowerShell command in the workspace directory.
- write_file: Write text content directly to a file at an absolute path.
- finish: Signal that the objective is complete or definitively failed.
- report_blocking: Signal an unresolvable blocker requiring orchestrator intervention.

RULES:
- Always use backslash-escaped paths in run_command: C:\\\\Users\\\\User\\\\Desktop\\\\file.txt
- For write_file paths you may use forward slashes: C:/Users/User/Desktop/file.txt
- Call finish when the objective is done or definitively cannot be completed.
- Call report_blocking only if you genuinely cannot proceed without external input.
"""

# Patterns for direct command extraction from goal strings
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# Match "run/execute/exec <cmd>" — strip trailing " in <phrase>" if present
_EXEC_PREFIX_RE = re.compile(
    r"(?:run|execute|exec)\s+(?!`)(.+?)(?:\s+in\b.+)?$", re.IGNORECASE
)

# Domain tool declarations
_run_command_decl = genai_types.FunctionDeclaration(
    name="run_command",
    description="Execute a PowerShell command in the workspace directory.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "command": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="The PowerShell command to run.",
            ),
            "allow_failure": genai_types.Schema(
                type=genai_types.Type.BOOLEAN,
                description="If true, non-zero exit codes are not treated as errors.",
            ),
        },
        required=["command"],
    ),
)

_write_file_decl = genai_types.FunctionDeclaration(
    name="write_file",
    description="Write text content directly to a file at an absolute path.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "path": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Absolute path to write.",
            ),
            "content": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Text content to write.",
            ),
        },
        required=["path", "content"],
    ),
)


class TerminalWorker(AgenticWorkerMixin, DomainWorker):
    """Terminal worker: ReAct loop with run_command and write_file tools."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        if llm is None:
            from trinity_pilot.llm.gemini import GeminiProvider
            llm = GeminiProvider(
                api_key=os.environ.get("GEMINI_API_KEY", ""),
                model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.0-flash"),
            )
        super().__init__(llm=llm)

    def _worker_system_prompt(self) -> str:
        return _TERMINAL_SYSTEM

    def _worker_environment_context(self, spec, evidence) -> str:  # type: ignore[override]
        workspace = evidence.get("workspace", "")
        if not workspace:
            return ""
        return (
            f"WORKSPACE DIRECTORY: {workspace}\n"
            "Use this path for all file operations. "
            "run_command CWD is already set to this directory — "
            "prefer relative paths (e.g. '.\\\\file.txt') over absolute."
        )

    def _worker_tools(self) -> list[genai_types.Tool]:
        return [_make_tool([_run_command_decl, _write_file_decl, _finish_decl, _report_blocking_decl])]

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        workspace = tempfile.mkdtemp(prefix="trinity-term-")
        shell_raw = "shell_raw" in (spec.required_capabilities or [])
        evidence: dict[str, Any] = {
            "domain": "terminal",
            "objective_id": spec.objective_id,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "created_files": [],
            "workspace": workspace,
            "error": None,
            "action_log": [],
            "shell_raw_used": shell_raw,
        }
        timeout_seconds = int(spec.metadata.get("timeout_seconds", 60))
        try:
            result = await asyncio.wait_for(
                self.run_loop(spec, evidence),
                timeout=timeout_seconds,
            )
            evidence["worker_result_status"] = result.status
            evidence["worker_result_summary"] = result.summary
        except asyncio.TimeoutError:
            raise WorkerError(
                f"Terminal timeout after {timeout_seconds}s for '{spec.objective_id}'"
            )
        except WorkerBlocker:
            raise
        except WorkerError:
            raise
        except Exception as exc:
            evidence["error"] = str(exc)
            raise WorkerError(
                f"Terminal execution failed for '{spec.objective_id}': {exc}"
            ) from exc
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
        validate_evidence(DomainType.TERMINAL, evidence)
        return evidence

    async def _dispatch_tool(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> str:
        if tool_name == "run_command":
            command = args["command"]
            allow_failure = args.get("allow_failure", False)
            cwd = evidence.get("workspace") or tempfile.gettempdir()
            shell_raw = bool(evidence.get("shell_raw_used", False))
            stdout, stderr, exit_code = await self._run_command(command, cwd=cwd, shell_raw=shell_raw)
            evidence["stdout"] = stdout[-_MAX_OUTPUT_CHARS:]
            evidence["stderr"] = stderr[-_MAX_OUTPUT_CHARS:]
            evidence["exit_code"] = exit_code
            evidence["action_log"].append(f"run_command: exit={exit_code} cmd={command[:100]}")
            if exit_code != 0 and not allow_failure:
                return f"FAILED exit={exit_code}\nstderr: {stderr[:500]}\nstdout: {stdout[:200]}"
            return f"exit={exit_code}\nstdout: {stdout[:1000]}\nstderr: {stderr[:200]}"
        elif tool_name == "write_file":
            path = args["path"]
            content = args["content"]
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
            evidence["created_files"].append(path)
            evidence["action_log"].append(f"write_file: {path} ({len(content)} chars)")
            return f"File written: {path} ({len(content)} chars)"
        else:
            return await super()._dispatch_tool(tool_name, args, evidence)

    # ------------------------------------------------------------------
    # Legacy objective runner (kept for existing tests)
    # ------------------------------------------------------------------

    async def _run_objective(
        self,
        workspace: str,
        spec: ObjectiveSpec,
        evidence: dict[str, Any],
    ) -> None:
        shell_raw = "shell_raw" in (spec.required_capabilities or [])
        metadata_cmd = str(spec.metadata.get("command", "")).strip()
        direct_cmd = metadata_cmd if metadata_cmd else self._extract_command(spec.goal)
        if direct_cmd is None:
            raise WorkerError(
                f"No runnable command found in goal: {spec.goal!r}"
            )

        evidence["action_log"].append("Generated 1 action steps")
        stdout, stderr, exit_code = await self._run_command(
            direct_cmd, cwd=workspace, shell_raw=shell_raw
        )
        evidence["stdout"] = stdout[-_MAX_OUTPUT_CHARS:]
        evidence["stderr"] = stderr[-_MAX_OUTPUT_CHARS:]
        evidence["exit_code"] = exit_code
        evidence["action_log"].append(
            f"run: exit={exit_code} stdout={stdout[:200]}"
        )
        if exit_code != 0:
            raise WorkerError(
                f"Command failed (exit {exit_code}): {stderr[:500]}"
            )

        # List files created in workspace
        created: list[str] = []
        for root, _, files in os.walk(workspace):
            for f in files:
                created.append(
                    str(Path(root) / f).replace(workspace + os.sep, "", 1)
                )
        evidence["created_files"] = created

    # ------------------------------------------------------------------
    # Backward-compatible helpers (kept for existing tests)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_command(goal: str) -> str | None:
        """Extract a runnable command from a goal string."""
        m = _BACKTICK_RE.search(goal)
        if m:
            cmd = m.group(1).strip()
            return cmd if cmd else None
        m = _EXEC_PREFIX_RE.search(goal)
        if m:
            cmd = m.group(1).strip()
            return cmd if cmd else None
        return None

    @staticmethod
    async def _run_command(
        command: str,
        cwd: str,
        shell_raw: bool = False,
    ) -> tuple[str, str, int]:
        """Run a shell command."""
        if shell_raw:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        else:
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_exec(
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_CMD_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError as exc:
                raise WorkerError(
                    f"Command timed out after {_CMD_TIMEOUT}s and did not terminate cleanly: {command}"
                ) from exc
            raise WorkerError(f"Command timed out after {_CMD_TIMEOUT}s: {command}")
        return (
            stdout_bytes.decode(errors="replace"),
            stderr_bytes.decode(errors="replace"),
            proc.returncode or 0,
        )

    @staticmethod
    async def _run_powershell(command: str, cwd: str) -> tuple[str, str, int]:
        """Backward-compat alias for _run_command."""
        return await TerminalWorker._run_command(command, cwd=cwd, shell_raw=False)

    async def _generate_actions(self, goal: str) -> list[dict[str, Any]]:
        from trinity_pilot.llm.base import LLMMessage
        from trinity_pilot.llm.gemini import GeminiProvider

        provider = GeminiProvider(
            api_key=os.environ["GEMINI_API_KEY"],
            model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.0-flash"),
        )
        response = await provider.complete(
            [LLMMessage(role="user", content=f"GOAL: {goal}\n\nGenerate the action list now.")],
            system=_TERMINAL_SYSTEM,
        )
        raw = response.content.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*(?:```|$)", raw)
        if match:
            raw = match.group(1).strip()
        return json.loads(raw)
