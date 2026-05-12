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

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.workers.base import DomainWorker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence

_MAX_OUTPUT_CHARS = 10_000
_CMD_TIMEOUT = 30.0

_TERMINAL_SYSTEM = """\
You are a terminal automation agent on Windows (PowerShell 5.1).
Given a goal, output ONLY a JSON array of action steps to accomplish it.
Each step is one of:
  {"action":"run","command":"<complete powershell expression>","allow_failure":false}
  {"action":"write_file","path":"<absolute-path>","content":"<text>"}

RULES:
- "run": the command string is passed directly to: powershell.exe -NoProfile -Command <command>
- Use "run" to execute shell commands, run scripts, pipe output to files, etc.
- Use "write_file" to directly write static text content to a file (no shell needed).
- Always use backslash-escaped paths in "run" commands: C:\\\\Users\\\\User\\\\Desktop\\\\file.txt
- For "write_file" paths you may use forward slashes: C:/Users/User/Desktop/file.txt
- Return ONLY the JSON array. No markdown fences, no prose.
"""

# Patterns for direct command extraction from goal strings
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# Match "run/execute/exec <cmd>" — strip trailing " in <phrase>" if present
_EXEC_PREFIX_RE = re.compile(
    r"(?:run|execute|exec)\s+(?!`)(.+?)(?:\s+in\b.+)?$", re.IGNORECASE
)


class TerminalWorker(DomainWorker):
    """Terminal worker: extracts commands directly from goal strings."""

    def __init__(self) -> None:
        super().__init__()

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
            await asyncio.wait_for(
                self._run_objective(workspace, spec, evidence),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise WorkerError(
                f"Terminal timeout after {timeout_seconds}s for '{spec.objective_id}'"
            )
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

    @staticmethod
    def _extract_command(goal: str) -> str | None:
        """Extract a runnable command from a goal string.

        Backtick-enclosed commands take priority: run `cmd`.
        Falls back to "run/execute/exec <cmd>" prefix pattern.
        Returns None if no command can be extracted.
        """
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
        """Run a shell command.

        When shell_raw is True, uses create_subprocess_shell.
        Otherwise uses create_subprocess_exec (cmd.exe on Windows).
        """
        if shell_raw:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        else:
            if sys.platform == "win32":
                shell_exe = os.environ.get("ComSpec", "cmd.exe")
                proc = await asyncio.create_subprocess_exec(
                    shell_exe,
                    "/c",
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
