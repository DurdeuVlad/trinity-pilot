from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.workers.base import DomainWorker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence

_MAX_OUTPUT_CHARS = 10_000
_READ_TIMEOUT = 30.0


class TerminalWorker(DomainWorker):
    """PTY-backed terminal worker. Isolated tempdir per attempt, cleaned in finally."""

    def __init__(self) -> None:
        super().__init__()

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        workspace = tempfile.mkdtemp(prefix="trinity-term-")
        evidence: dict[str, Any] = {
            "domain": "terminal",
            "objective_id": spec.objective_id,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "created_files": [],
            "workspace": workspace,
            "error": None,
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
        command = self._extract_command(spec.goal)
        if not command:
            raise WorkerError(
                f"No runnable command found in goal: '{spec.goal}'"
            )

        shell_raw = "shell_raw" in spec.required_capabilities
        stdout, stderr, exit_code = await self._run_command(
            command, cwd=workspace, allow_shell=shell_raw
        )
        if shell_raw:
            evidence["shell_raw_used"] = True
        evidence["stdout"] = stdout[-_MAX_OUTPUT_CHARS:]
        evidence["stderr"] = stderr[-_MAX_OUTPUT_CHARS:]
        evidence["exit_code"] = exit_code

        # List files created in workspace
        created: list[str] = []
        for root, _, files in os.walk(workspace):
            for f in files:
                created.append(
                    str(Path(root) / f).replace(workspace + os.sep, "", 1)
                )
        evidence["created_files"] = created

        if exit_code != 0:
            raise WorkerError(
                f"Command exited with code {exit_code}. stderr: {stderr[:500]}"
            )

    @staticmethod
    async def _run_command(
        command: str, cwd: str, allow_shell: bool = False
    ) -> tuple[str, str, int]:
        if allow_shell:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        else:
            try:
                args = shlex.split(command)
            except ValueError as exc:
                raise WorkerError(f"Command parse failed: {exc}") from exc
            if sys.platform == "win32" and args and args[0].lower() in {
                "assoc",
                "break",
                "call",
                "cd",
                "chdir",
                "cls",
                "copy",
                "del",
                "dir",
                "echo",
                "erase",
                "exit",
                "md",
                "mkdir",
                "move",
                "rd",
                "ren",
                "rename",
                "rmdir",
                "set",
                "type",
                "ver",
                "vol",
            }:
                comspec = os.environ.get("ComSpec", "cmd.exe")
                args = [comspec, "/c", command]
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_READ_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise WorkerError(
                f"Command timed out after {_READ_TIMEOUT}s: {command}"
            )
        return (
            stdout_bytes.decode(errors="replace"),
            stderr_bytes.decode(errors="replace"),
            proc.returncode or 0,
        )

    @staticmethod
    def _extract_command(goal: str) -> str | None:
        """Extract shell command from backtick or 'run X' patterns."""
        import re
        # Backtick: `command here`
        match = re.search(r"`([^`]+)`", goal)
        if match:
            return match.group(1).strip()
        # 'run X' or 'execute X' pattern
        match = re.search(r"(?:run|execute|call)\s+(.+)", goal, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
