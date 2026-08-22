from __future__ import annotations

import asyncio
import glob as _glob
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google.genai import types as genai_types

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.llm.base import LLMProvider
from trinity_pilot.workers.agentic_mixin import (
    AgenticWorkerMixin,
    _BlockerSignal,
    _finish_decl,
    _FinishSignal,
    _make_tool,
    _report_blocking_decl,
    _take_screenshot_decl,
)
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence
from trinity_pilot.workers.write_verification import verify_and_write_file

_MAX_OUTPUT_CHARS = 10_000
_CMD_TIMEOUT = 60.0

# Terminal commands are untrusted agent output. Retain normal runtime variables
# (PATH, TEMP, SystemRoot, etc.) while ensuring credentials cannot be inherited.
_SECRET_ENV_NAME_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def _normalise_process_output(output: str) -> str:
    """Remove shell record terminators while preserving internal output lines."""
    return output.rstrip("\r\n")


_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?im)^(\s*[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Za-z0-9_]*\s*=\s*).*$"
)


def _safe_file_observation(text: str) -> str:
    """Make file readbacks useful to reviewers without exposing credentials."""
    return _SENSITIVE_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)


def _append_file_readback(evidence: dict[str, Any], text: str) -> None:
    """Accumulate sanitized file evidence without changing command stdout."""
    previous = str(evidence.get("file_readback", ""))
    combined = f"{previous}\n{text}" if previous else text
    combined = combined[-_MAX_OUTPUT_CHARS:]
    evidence["file_readback"] = combined


def _append_stdout_observation(evidence: dict[str, Any], text: str) -> None:
    """Accumulate concise action confirmations in the command-output channel."""
    previous = str(evidence.get("stdout", ""))
    combined = f"{previous}\n{text}" if previous else text
    combined = combined[-_MAX_OUTPUT_CHARS:]
    evidence["stdout"] = combined
    evidence["stdout_raw"] = combined


def _scrubbed_child_env() -> dict[str, str]:
    """Return the environment allowed to be inherited by terminal commands."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not any(part in name.upper() for part in _SECRET_ENV_NAME_PARTS)
    }
    runtime_dir = str(Path(sys.executable).resolve().parent)
    path_entries = env.get("PATH", "").split(os.pathsep)
    env["PATH"] = os.pathsep.join(
        [runtime_dir, *(entry for entry in path_entries if entry.casefold() != runtime_dir.casefold())]
    )
    return env


def _pin_runtime_python(command: str) -> str:
    """Resolve bare Python commands to the interpreter hosting Trinity Pilot."""
    runtime = Path(sys.executable).resolve()
    if runtime.name.casefold() not in {"python.exe", "python"}:
        return command
    quoted = "'" + str(runtime).replace("'", "''") + "'"
    command = re.sub(
        r"(?i)(?<![\w.])&\s+python(?:\.exe)?(?=\s|$)",
        lambda _: f"& {quoted}",
        command,
    )
    return re.sub(
        r"(?i)(?<![\w.&])python(?:\.exe)?(?=\s|$)",
        lambda _: f"& {quoted}",
        command,
    )

# Windows: CREATE_NEW_PROCESS_GROUP so timeout kill can target the whole tree.
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def _subprocess_kwargs() -> dict[str, Any]:
    """Extra kwargs for asyncio subprocess creation (Windows process-group)."""
    if sys.platform == "win32":
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP}
    return {}


class _WinJobObject:
    """Windows Job Object that can kill all assigned processes on terminate.

    Assigning the shell (and thus its children) to a job lets us tear down hung
    standalone .exe grandchildren that otherwise hold stdout pipes open forever.
    """

    def __init__(self) -> None:
        self._handle: int | None = None
        if sys.platform != "win32":
            return
        handle: int | None = None
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.CreateJobObjectW(None, None)
            # Require a real integer handle — mocks can be truthy and recurse.
            if not isinstance(handle, int) or handle == 0:
                return

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_uint64),
                    ("WriteOperationCount", ctypes.c_uint64),
                    ("OtherOperationCount", ctypes.c_uint64),
                    ("ReadTransferCount", ctypes.c_uint64),
                    ("WriteTransferCount", ctypes.c_uint64),
                    ("OtherTransferCount", ctypes.c_uint64),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            # Do not use KILL_ON_JOB_CLOSE: successful commands may intentionally
            # detach a child.  Timeout/cancellation paths call TerminateJobObject
            # explicitly, while normal completion only closes this handle.
            info.BasicLimitInformation.LimitFlags = 0
            ok = kernel32.SetInformationJobObject(
                handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            )
            if not ok:
                kernel32.CloseHandle(handle)
                handle = None
                return
            self._handle = int(handle)
        except Exception:
            if handle:
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
            self._handle = None

    @staticmethod
    def _k32():
        import ctypes
        return ctypes.WinDLL("kernel32", use_last_error=True)

    def assign(self, pid: int) -> None:
        if not self._handle or not isinstance(pid, int) or pid <= 0:
            return
        try:
            kernel32 = self._k32()
            PROCESS_SET_QUOTA = 0x0100
            PROCESS_TERMINATE = 0x0001
            PROCESS_DUP_HANDLE = 0x0040
            access = PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_DUP_HANDLE
            proc = kernel32.OpenProcess(access, False, pid)
            if not isinstance(proc, int) or proc == 0:
                return
            try:
                kernel32.AssignProcessToJobObject(self._handle, proc)
            finally:
                kernel32.CloseHandle(proc)
        except Exception:
            pass

    def terminate(self) -> None:
        if not self._handle:
            return
        try:
            self._k32().TerminateJobObject(self._handle, 1)
        except Exception:
            pass

    def close(self) -> None:
        if not self._handle:
            return
        try:
            self._k32().CloseHandle(self._handle)
        except Exception:
            pass
        self._handle = None


@dataclass
class _BackgroundProc:
    """Live handle for a detached process started via start_process.

    Lives on the TerminalWorker instance for the duration of one objective's
    execute() call — a fresh worker is constructed per objective (see
    terminal_server.py), so instance state never leaks across objectives.
    """
    proc: "asyncio.subprocess.Process"
    job: _WinJobObject
    command: str
    stdout_buf: bytearray = field(default_factory=bytearray)
    stderr_buf: bytearray = field(default_factory=bytearray)
    stdout_reader_task: "asyncio.Task | None" = None
    stderr_reader_task: "asyncio.Task | None" = None


async def _pump(reader: "asyncio.StreamReader | None", buf: bytearray) -> None:
    """Incrementally drain a stream into buf without blocking on EOF (unlike communicate())."""
    if reader is None:
        return
    _CAP = _MAX_OUTPUT_CHARS * 4
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            return
        buf.extend(chunk)
        if len(buf) > _CAP:
            del buf[: len(buf) - _CAP]


def _kill_process_tree(pid: int, job: _WinJobObject | None = None) -> None:
    """Kill a process and all of its descendants.

    On Windows, killing only the immediate child (e.g. powershell.exe) leaves any
    grandchild it spawned (e.g. git.exe) running, which can hold a duplicate handle
    to the redirected stdout/stderr pipe open and prevent asyncio's
    proc.communicate() from ever seeing EOF.

    Prefer Job Object terminate when available; fall back to CTRL_BREAK + psutil.
    """
    if job is not None:
        job.terminate()
    if sys.platform == "win32":
        try:
            import signal

            os.kill(pid, signal.CTRL_BREAK_EVENT)
        except Exception:
            pass
    try:
        import psutil

        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            parent.kill()
        except psutil.NoSuchProcess:
            pass
        psutil.wait_procs([parent, *children], timeout=3)
    except Exception:
        pass

_QUOTED_WIN_PATH_RE = re.compile(r"[\"']([A-Za-z]:\\[^\"']+)[\"']")


def _record_created_files_from_command(command: str, evidence: dict[str, Any]) -> None:
    """Detect files created via run_command (e.g. New-Item, Out-File, redirection) and
    append them to evidence["created_files"], which otherwise only gets populated by the
    write_file tool. Planner-authored checklists checking "created_files" false-fail
    real, successful run_command-based file creation without this — a recurring bug class
    (see CHANGELOG "Fixes" entries for T6 and HH04).

    Heuristic: any quoted absolute Windows path mentioned in the command that exists on
    disk after the command succeeded is useful artifact evidence. Files are recorded in
    ``created_files``; verified directories are recorded in ``observed_paths`` and the
    common directory root is exposed as ``file_path`` for planners that request a path
    artifact even when the artifact is a directory tree.
    """
    created_files = evidence.setdefault("created_files", [])
    observed_paths = evidence.setdefault("observed_paths", [])
    for path in _QUOTED_WIN_PATH_RE.findall(command):
        if path not in created_files and os.path.isfile(path):
            created_files.append(path)
        elif path not in observed_paths and os.path.isdir(path):
            observed_paths.append(path)
    if len(created_files) == 1:
        evidence.setdefault("file_path", created_files[0])
    elif observed_paths:
        evidence.setdefault("file_paths", list(observed_paths))
        try:
            evidence.setdefault("file_path", os.path.commonpath(observed_paths))
        except ValueError:
            evidence.setdefault("file_path", observed_paths[0])


_TERMINAL_SYSTEM = """\
You are a terminal automation agent on Windows (PowerShell 5.1).
Given a goal, use the available tools to accomplish it step by step.

Tool categories:
- SENSOR tools read, inspect, measure, and detect. They never change world state.
  Use them freely before and after actions to verify state.
- ACTION tools create, modify, execute, or delete. They change world state.
  Each action must be intentional. Prefer sensing first, then acting.

Available tools:

[SENSOR] screenshot: Capture a screenshot. mode='screen' (default), 'all_screens', or 'app' (supply app_title regex).
[SENSOR] read_file: Read a text file's contents. Does not change world state.
[SENSOR] list_directory: List entries (name, type, size) in a directory, non-recursive.
[SENSOR] file_exists: Check whether a path exists and whether it is a file or directory.
[SENSOR] path_info: Get filesystem metadata (type, size, mtime) for a path without reading it.
[SENSOR] env_get: Read one environment variable as run_command would see it (secrets redacted).
[SENSOR] glob_search: Find files matching a glob pattern (supports **) relative to the workspace.
[SENSOR] check_process: Check if a background process (by handle) is still running.
[SENSOR] read_process_output: Read accumulated output from a background process so far.

[ACTION] run_command: Execute a PowerShell command in the workspace directory.
[ACTION] write_file: Write text content directly to a file at an absolute path.
[ACTION] copy_file: Copy a file (absolute source/destination), verifying destination exists after.
[ACTION] move_file: Move/rename a file (absolute source/destination), verifying source is gone and destination exists.
[ACTION] delete_file: Delete a file at an absolute path, verifying it no longer exists.
[ACTION] start_process: Start a detached PowerShell command in the background; returns a handle.
[ACTION] kill_process: Kill a background process (by handle, from start_process) and its process tree.
[ACTION] finish: Signal that the objective is complete or definitively failed.
[ACTION] report_blocking: Signal an unresolvable blocker requiring orchestrator intervention.

RULES:
- Prefer read_file/list_directory/file_exists/path_info/glob_search over run_command for pure
  reads — they return clean, parseable results instead of PowerShell text you have to re-parse.
- Prefer copy_file/move_file/delete_file over Copy-Item/Move-Item/Remove-Item in run_command —
  they verify the result automatically so you don't need a separate Test-Path check.
- Use start_process (not run_command) for anything long-running or that should keep running in
  the background (a dev server, a watch process) — run_command blocks until the command exits or
  times out and will kill the whole process tree on timeout.
- After each ACTION tool call, read its result before proceeding. If a tool failed or
  produced unexpected state (wrong exit code, unexpected output), adapt — do not
  blindly continue to the next planned step.
- Always use backslash-escaped paths in run_command: C:\\\\Users\\\\User\\\\Documents\\\\file.txt
- For write_file paths you may use forward slashes: C:/Users/User/Documents/file.txt
- If the user asked to save a file to a SPECIFIC path, use EXACTLY that path. Do NOT redirect to Desktop.
- When listing or counting files in a directory, ALWAYS use -Recurse unless told otherwise.
  Example: Get-ChildItem "C:\\path\\to\\dir" -Filter "*.py" -Recurse
  Without -Recurse you only see the top-level folder — that is almost always wrong.
- Call finish when the objective is done or definitively cannot be completed.
- Call report_blocking only if you genuinely cannot proceed without external input.
- If write_file returns PERMISSION DENIED, call finish immediately with status=failure — OS permission errors are definitive and cannot be retried.
- Before updating an existing file, read its current contents and preserve every existing
  field, marker, and line that the goal does not explicitly replace. Prefer additive updates
  when the goal says to append or retain prior output. Before finish, reread the complete
  artifact and verify every named requirement is still present.
- Never invent null, blank, or placeholder values for a field the goal says to preserve or
  calculate. Read the source artifact, carry the exact value forward, and verify the final
  artifact contains that value before calling finish.
- For file copy or move operations, ALWAYS use absolute paths for BOTH source and destination.
  Example: Copy-Item "C:\\Users\\trinity\\Desktop\\source.txt" "C:\\Users\\trinity\\Desktop\\dest.txt"
  Never use relative paths for Desktop file operations.
- After any file copy or move, verify the destination exists before calling finish:
  run_command: Test-Path "C:\\Users\\trinity\\Desktop\\dest.txt"
  If False, retry before reporting success.
- When creating multiple files, create them in a single atomic command and verify all exist before finish:
  New-Item -ItemType File "C:\\path\\a.txt","C:\\path\\b.txt" -Force
  Then: Get-ChildItem "C:\\path" to confirm all files are present.
- PREFER PowerShell-native cmdlets/variables over launching a separate .exe when an equivalent
  exists — launching a standalone executable (git.exe, hostname.exe, etc.) can hang for the full
  command timeout in this environment, while built-in cmdlets (Test-Path, Get-ChildItem,
  Get-Process, Get-Command, Get-Content) never do. Examples: use $env:COMPUTERNAME instead of
  hostname.exe; use $env:USERNAME instead of whoami.exe; use (Get-Command <name>).Version instead
  of invoking the program with --version.
  When no native equivalent exists (e.g. running a .py script requires python.exe), launching the
  external process is unavoidable — accept that it may be slow.
"""

# Patterns for direct command extraction from goal strings
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# Match "run/execute/exec <cmd>" — strip trailing " in <phrase>" if present
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

_read_file_decl = genai_types.FunctionDeclaration(
    name="read_file",
    description="Read a text file's contents from an absolute path. Does not modify state.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "path": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute path to read."),
            "encoding": genai_types.Schema(type=genai_types.Type.STRING, description="Text encoding (default utf-8)."),
        },
        required=["path"],
    ),
)

_read_file_range_decl = genai_types.FunctionDeclaration(
    name="read_file_range",
    description="Read a byte-offset window of a large file/log without loading the whole thing.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "path": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute path to read."),
            "offset": genai_types.Schema(type=genai_types.Type.INTEGER, description="Byte offset to start reading from (default 0)."),
            "length": genai_types.Schema(type=genai_types.Type.INTEGER, description="Max bytes to read (default 10000)."),
        },
        required=["path"],
    ),
)

_list_directory_decl = genai_types.FunctionDeclaration(
    name="list_directory",
    description="List entries in a directory (non-recursive) with type and size.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"path": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute directory path.")},
        required=["path"],
    ),
)

_file_exists_decl = genai_types.FunctionDeclaration(
    name="file_exists",
    description="Check whether a path exists, and whether it is a file or directory.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"path": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute path to check.")},
        required=["path"],
    ),
)

_path_info_decl = genai_types.FunctionDeclaration(
    name="path_info",
    description="Get filesystem metadata for a path (exists, type, size, mtime) without reading contents.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"path": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute path.")},
        required=["path"],
    ),
)

_env_get_decl = genai_types.FunctionDeclaration(
    name="env_get",
    description="Read a single environment variable as run_command would see it (secrets are redacted).",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"name": genai_types.Schema(type=genai_types.Type.STRING, description="Environment variable name.")},
        required=["name"],
    ),
)

_copy_file_decl = genai_types.FunctionDeclaration(
    name="copy_file",
    description="Copy a file from source to destination (absolute paths), verifying the destination exists after.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "source": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute source path."),
            "destination": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute destination path."),
        },
        required=["source", "destination"],
    ),
)

_move_file_decl = genai_types.FunctionDeclaration(
    name="move_file",
    description="Move/rename a file from source to destination (absolute paths), verifying source is gone and destination exists.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "source": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute source path."),
            "destination": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute destination path."),
        },
        required=["source", "destination"],
    ),
)

_delete_file_decl = genai_types.FunctionDeclaration(
    name="delete_file",
    description="Delete a file at an absolute path, verifying it no longer exists.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"path": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute path to delete.")},
        required=["path"],
    ),
)

_glob_search_decl = genai_types.FunctionDeclaration(
    name="glob_search",
    description="Find files matching a glob pattern relative to the workspace (supports ** for recursive).",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"pattern": genai_types.Schema(type=genai_types.Type.STRING, description="Glob pattern, e.g. '**/*.py'.")},
        required=["pattern"],
    ),
)

_start_process_decl = genai_types.FunctionDeclaration(
    name="start_process",
    description="Start a long-running/detached PowerShell command in the background and return a handle.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"command": genai_types.Schema(type=genai_types.Type.STRING, description="PowerShell command to run detached.")},
        required=["command"],
    ),
)

_check_process_decl = genai_types.FunctionDeclaration(
    name="check_process",
    description="Check whether a background process (by handle) is still running, and its exit code if finished.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"handle": genai_types.Schema(type=genai_types.Type.STRING, description="Handle returned by start_process.")},
        required=["handle"],
    ),
)

_read_process_output_decl = genai_types.FunctionDeclaration(
    name="read_process_output",
    description="Read accumulated stdout/stderr so far from a background process, without waiting for it to finish.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"handle": genai_types.Schema(type=genai_types.Type.STRING, description="Handle returned by start_process.")},
        required=["handle"],
    ),
)

_terminal_kill_process_decl = genai_types.FunctionDeclaration(
    name="kill_process",
    description="Kill a background process (started via start_process) and its entire process tree.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"handle": genai_types.Schema(type=genai_types.Type.STRING, description="Handle returned by start_process.")},
        required=["handle"],
    ),
)

_list_processes_decl = genai_types.FunctionDeclaration(
    name="list_processes",
    description="List running processes on the system (pid, name, cmdline), optionally filtered by name.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"name_filter": genai_types.Schema(type=genai_types.Type.STRING, description="Optional substring/regex to filter process names.")},
        required=[],
    ),
)


class TerminalWorker(AgenticWorkerMixin, DomainWorker):
    """Terminal worker: ReAct loop with run_command and write_file tools."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        if llm is None:
            from trinity_pilot.llm.factory import create_provider_from_env
            llm = create_provider_from_env("worker")
        super().__init__(llm=llm)
        self._background_procs: dict[str, _BackgroundProc] = {}

    def _worker_system_prompt(self) -> str:
        return _TERMINAL_SYSTEM

    def _worker_environment_context(self, spec, evidence) -> str:
        workspace = evidence.get("workspace", "")
        if not workspace:
            return ""
        return (
            f"WORKSPACE DIRECTORY: {workspace}\n"
            "Use this path for all file operations. "
            "run_command CWD is already set to this directory — "
            "prefer relative paths (e.g. '.\\\\file.txt') over absolute."
        )

    def _worker_state_snapshot(self, evidence: dict[str, Any]) -> str:
        workspace = evidence.get("workspace", "")
        exit_code = evidence.get("exit_code")
        action_log = evidence.get("action_log", [])
        last_action = action_log[-1] if action_log else "none"

        # File listing: names up to cap, overflow summary
        _FILE_CAP = 20
        try:
            names = sorted(os.listdir(workspace)) if workspace else []
        except OSError:
            names = []
        if len(names) > _FILE_CAP:
            overflow = len(names) - _FILE_CAP
            files_str = f"[{', '.join(names[:_FILE_CAP])}, ...+{overflow} more]"
        else:
            files_str = f"[{', '.join(names)}]"

        lines = [
            f"workspace={workspace}",
            f"exit_code={exit_code}",
            f"files={files_str}",
            f"last_action={last_action}",
        ]

        _HISTORY_CAP = 10
        if len(action_log) > 1:
            history = action_log[-_HISTORY_CAP:]
            lines.append(f"commands_tried=[{', '.join(repr(e) for e in history)}]")

        # stdout/stderr snippets (last 200 chars each, only when non-empty)
        stdout = evidence.get("stdout", "")
        if stdout:
            lines.append(f"last_stdout={stdout[-200:]!r}")
        stderr = evidence.get("stderr", "")
        if stderr:
            lines.append(f"last_stderr={stderr[-200:]!r}")

        return "\n".join(lines)

    def _worker_tools(self) -> list[genai_types.Tool]:
        return [_make_tool([
            _run_command_decl,
            _write_file_decl,
            _read_file_decl,
            _read_file_range_decl,
            _list_directory_decl,
            _file_exists_decl,
            _path_info_decl,
            _env_get_decl,
            _copy_file_decl,
            _move_file_decl,
            _delete_file_decl,
            _glob_search_decl,
            _start_process_decl,
            _check_process_decl,
            _read_process_output_decl,
            _terminal_kill_process_decl,
            _list_processes_decl,
            _take_screenshot_decl,
            _finish_decl,
            _report_blocking_decl,
        ])]

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        workspace = tempfile.mkdtemp(prefix="trinity-term-")
        shell_raw = "shell_raw" in (spec.required_capabilities or [])
        evidence: dict[str, Any] = {
            "domain": "terminal",
            "objective_id": spec.objective_id,
            "stdout": "",
            "stderr": "",
            "stdout_raw": "",
            "stderr_raw": "",
            "exit_code": None,
            "created_files": [],
            "workspace": workspace,
            "error": None,
            "action_log": [],
            "shell_raw_used": shell_raw,
        }
        # GUI happy-path terminal objectives include multiple OpenAI tool turns;
        # the old 60s default expired while a command was still being awaited,
        # even though the outer GUI wait allows substantially longer workflows.
        # Explicit per-objective timeouts remain authoritative.
        timeout_seconds = int(spec.metadata.get("timeout_seconds", 120))

        def cleanup_failed_execution() -> None:
            shutil.rmtree(workspace, ignore_errors=True)

        async def reap_background_processes() -> None:
            # A crashed/timed-out/finished objective must never leave a detached
            # start_process handle running past the end of its ReAct loop.
            for bg in self._background_procs.values():
                _kill_process_tree(bg.proc.pid, job=bg.job)
                bg.job.close()
                for task in (bg.stdout_reader_task, bg.stderr_reader_task):
                    if task is None:
                        continue
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
            self._background_procs.clear()

        completed = False
        try:
            try:
                result = await asyncio.wait_for(
                    self.run_loop(spec, evidence),
                    timeout=timeout_seconds,
                )
                evidence["worker_result_status"] = result.status
                evidence["worker_result_summary"] = result.summary
                evidence["tokens_used"] = result.tokens_used
            except asyncio.TimeoutError:
                cleanup_failed_execution()
                raise WorkerError(
                    f"Terminal timeout after {timeout_seconds}s for '{spec.objective_id}'"
                )
            except asyncio.CancelledError:
                cleanup_failed_execution()
                raise
            except WorkerBlocker:
                cleanup_failed_execution()
                raise
            except WorkerError:
                cleanup_failed_execution()
                raise
            except Exception as exc:
                cleanup_failed_execution()
                evidence["error"] = str(exc)
                raise WorkerError(
                    f"Terminal execution failed for '{spec.objective_id}': {exc}"
                ) from exc
            try:
                # BH-001: retain the workspace when execution completes; dependents may
                # still need workspace-relative paths via portable evidence.
                validate_evidence(DomainType.TERMINAL, evidence)
                completed = True
                return evidence
            finally:
                if not completed:
                    shutil.rmtree(workspace, ignore_errors=True)
        finally:
            await reap_background_processes()

    async def _dispatch_tool(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> str | tuple[str, bytes] | _FinishSignal | _BlockerSignal:
        if tool_name == "run_command":
            command = args["command"]
            allow_failure = args.get("allow_failure", False)
            cwd = evidence.get("workspace") or tempfile.gettempdir()
            shell_raw = bool(evidence.get("shell_raw_used", False))
            stdout, stderr, exit_code = await self._run_command(command, cwd=cwd, shell_raw=shell_raw)
            stdout_limited = stdout[-_MAX_OUTPUT_CHARS:]
            stderr_limited = stderr[-_MAX_OUTPUT_CHARS:]
            evidence["stdout_raw"] = stdout_limited
            evidence["stderr_raw"] = stderr_limited
            evidence["stdout"] = _normalise_process_output(stdout_limited)
            evidence["stderr"] = _normalise_process_output(stderr_limited)
            evidence["exit_code"] = exit_code
            evidence["action_log"].append(f"run_command: exit={exit_code} cmd={command[:100]}")
            if exit_code == 0:
                _record_created_files_from_command(command, evidence)
            if exit_code != 0 and not allow_failure:
                return f"FAILED exit={exit_code}\nstderr: {stderr[:500]}\nstdout: {stdout[:200]}"
            return f"exit={exit_code}\nstdout: {stdout[:1000]}\nstderr: {stderr[:200]}"
        elif tool_name == "write_file":
            path = args["path"]
            content = args["content"]
            result = verify_and_write_file(path, content, evidence)
            if evidence.get("write_file_failures") and any(
                "PermissionError" in f.get("error", "") for f in evidence["write_file_failures"]
            ):
                return (
                    f"PERMISSION DENIED: Cannot write to {path} — "
                    "the file is read-only or the path is OS-protected. "
                    "This is a definitive system restriction. Call finish with status=failure."
                )
            if path not in evidence["created_files"]:
                evidence["created_files"].append(path)
            evidence.setdefault("file_path", path)
            evidence.setdefault("exit_code", 0)
            safe_content = _safe_file_observation(content[:_MAX_OUTPUT_CHARS])
            evidence[f"file_content_{Path(path).name}"] = safe_content
            _append_stdout_observation(
                evidence,
                f"write_file: path={path}\nexit_code=0\n{safe_content}",
            )
            _append_file_readback(evidence, safe_content)
            return result

        elif tool_name == "read_file":
            path = args["path"]
            encoding = args.get("encoding", "utf-8")
            _READ_FILE_CAP = 50_000
            try:
                data = Path(path).read_text(encoding=encoding, errors="replace")
            except FileNotFoundError:
                return f"read_file: {path} does not exist."
            except IsADirectoryError:
                return f"read_file: {path} is a directory, not a file."
            except Exception as exc:
                return f"read_file failed: {path}: {type(exc).__name__}: {exc}"
            truncated = len(data) > _READ_FILE_CAP
            body = data[:_READ_FILE_CAP]
            safe_body = _safe_file_observation(body)
            _append_file_readback(evidence, safe_body)
            return f"read_file: {path} ({len(data)} chars{', truncated' if truncated else ''})\n{safe_body}"

        elif tool_name == "read_file_range":
            path = args["path"]
            offset = int(args.get("offset", 0))
            length = int(args.get("length", 10_000))
            try:
                with open(path, "rb") as f:
                    f.seek(offset)
                    chunk = f.read(length)
                    eof = f.read(1) == b""
            except FileNotFoundError:
                return f"read_file_range: {path} does not exist."
            except Exception as exc:
                return f"read_file_range failed: {path}: {type(exc).__name__}: {exc}"
            text = chunk.decode("utf-8", errors="replace")
            return json.dumps({"offset": offset, "length": len(chunk), "eof": eof, "content": text})

        elif tool_name == "list_directory":
            path = args["path"]
            try:
                with os.scandir(path) as it:
                    entries = sorted(
                        (e.name + ("/" if e.is_dir() else ""), e.stat().st_size if e.is_file() else 0)
                        for e in it
                    )
            except FileNotFoundError:
                return f"list_directory: {path} does not exist."
            except NotADirectoryError:
                return f"list_directory: {path} is not a directory."
            _LIST_CAP = 200
            shown = entries[:_LIST_CAP]
            lines = [f"{name} ({size}b)" if not name.endswith("/") else name for name, size in shown]
            overflow = f" (+{len(entries) - _LIST_CAP} more)" if len(entries) > _LIST_CAP else ""
            return f"list_directory: {path} ({len(entries)} entries{overflow})\n" + "\n".join(lines)

        elif tool_name == "file_exists":
            path = args["path"]
            exists = os.path.exists(path)
            kind = "file" if os.path.isfile(path) else "directory" if os.path.isdir(path) else "none"
            return f"file_exists: {path} exists={exists} type={kind}"

        elif tool_name == "path_info":
            path = args["path"]
            if not os.path.exists(path):
                return f"path_info: {path} does not exist."
            st = os.stat(path)
            kind = "directory" if os.path.isdir(path) else "file"
            return f"path_info: {path} type={kind} size={st.st_size} mtime={st.st_mtime}"

        elif tool_name == "env_get":
            name = args["name"]
            if any(part in name.upper() for part in _SECRET_ENV_NAME_PARTS):
                return f"env_get: {name} = REDACTED"
            value = _scrubbed_child_env().get(name)
            return f"env_get: {name} = {value!r}" if value is not None else f"env_get: {name} is not set."

        elif tool_name == "copy_file":
            source, destination = args["source"], args["destination"]
            try:
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            except Exception as exc:
                evidence.setdefault("action_log", []).append(f"copy_file FAILED: {source} -> {destination}: {exc}")
                return f"copy_file failed: {source} -> {destination}: {type(exc).__name__}: {exc}"
            verified = os.path.isfile(destination)
            if verified and destination not in evidence["created_files"]:
                evidence["created_files"].append(destination)
            evidence.setdefault("file_path", destination)
            evidence.setdefault("exit_code", 0)
            evidence["action_log"].append(f"copy_file: {source} -> {destination} verified_exists={verified}")
            return f"copy_file: {source} -> {destination} verified_exists={verified}"

        elif tool_name == "move_file":
            source, destination = args["source"], args["destination"]
            try:
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(source, destination)
            except Exception as exc:
                evidence.setdefault("action_log", []).append(f"move_file FAILED: {source} -> {destination}: {exc}")
                return f"move_file failed: {source} -> {destination}: {type(exc).__name__}: {exc}"
            dest_ok = os.path.isfile(destination)
            source_gone = not os.path.exists(source)
            if dest_ok and destination not in evidence["created_files"]:
                evidence["created_files"].append(destination)
            evidence.setdefault("file_path", destination)
            evidence.setdefault("exit_code", 0)
            if source_gone:
                evidence.setdefault("deleted_files", []).append(source)
            evidence["action_log"].append(f"move_file: {source} -> {destination} dest_exists={dest_ok} source_gone={source_gone}")
            return f"move_file: {source} -> {destination} dest_exists={dest_ok} source_gone={source_gone}"

        elif tool_name == "delete_file":
            path = args["path"]
            try:
                os.remove(path)
            except FileNotFoundError:
                return f"delete_file: {path} already does not exist."
            except Exception as exc:
                evidence.setdefault("action_log", []).append(f"delete_file FAILED: {path}: {exc}")
                return f"delete_file failed: {path}: {type(exc).__name__}: {exc}"
            gone = not os.path.exists(path)
            if gone:
                evidence.setdefault("deleted_files", []).append(path)
            evidence["action_log"].append(f"delete_file: {path} verified_gone={gone}")
            return f"delete_file: {path} verified_gone={gone}"

        elif tool_name == "glob_search":
            pattern = args["pattern"]
            workspace = evidence.get("workspace") or tempfile.gettempdir()
            full_pattern = os.path.join(workspace, pattern)
            matches = sorted(_glob.glob(full_pattern, recursive=True))
            _GLOB_CAP = 200
            matches_shown = matches[:_GLOB_CAP]
            truncated = len(matches) > _GLOB_CAP
            return json.dumps({"pattern": pattern, "count": len(matches), "matches": matches_shown, "truncated": truncated})

        elif tool_name == "start_process":
            command = args["command"]
            extra = _subprocess_kwargs()
            job = _WinJobObject()
            proc = await asyncio.create_subprocess_exec(
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=evidence.get("workspace") or tempfile.gettempdir(),
                env=_scrubbed_child_env(), **extra,
            )
            if proc.pid:
                job.assign(proc.pid)
            handle = f"bg-{proc.pid}-{len(self._background_procs)}"
            bg = _BackgroundProc(proc=proc, job=job, command=command)
            bg.stdout_reader_task = asyncio.create_task(_pump(proc.stdout, bg.stdout_buf))
            bg.stderr_reader_task = asyncio.create_task(_pump(proc.stderr, bg.stderr_buf))
            self._background_procs[handle] = bg
            evidence.setdefault("background_processes", []).append(
                {"handle": handle, "command": command, "pid": proc.pid}
            )
            evidence["action_log"].append(f"start_process: handle={handle} pid={proc.pid} cmd={command[:100]}")
            return f"Started background process handle={handle} pid={proc.pid}"

        elif tool_name in ("check_process", "read_process_output", "kill_process"):
            handle = args["handle"]
            tracked = self._background_procs.get(handle)
            if tracked is None:
                return f"{tool_name}: unknown handle {handle!r}"
            if tool_name == "check_process":
                running = tracked.proc.returncode is None
                return f"handle={handle} running={running} exit_code={tracked.proc.returncode}"
            if tool_name == "read_process_output":
                return (
                    f"handle={handle} running={tracked.proc.returncode is None}\n"
                    f"stdout: {bytes(tracked.stdout_buf[-_MAX_OUTPUT_CHARS:]).decode(errors='replace')}\n"
                    f"stderr: {bytes(tracked.stderr_buf[-_MAX_OUTPUT_CHARS:]).decode(errors='replace')}"
                )
            # kill_process
            _kill_process_tree(tracked.proc.pid, job=tracked.job)
            tracked.job.close()
            for reader_task in (tracked.stdout_reader_task, tracked.stderr_reader_task):
                if reader_task is None:
                    continue
                reader_task.cancel()
                try:
                    await reader_task
                except (asyncio.CancelledError, Exception):
                    pass
            del self._background_procs[handle]
            evidence["action_log"].append(f"kill_process: handle={handle}")
            return f"Killed background process {handle}"

        elif tool_name == "list_processes":
            name_filter = args.get("name_filter")
            try:
                import psutil
                pattern = re.compile(name_filter, re.IGNORECASE) if name_filter else None
                tracked_pids = {bg.proc.pid for bg in self._background_procs.values()}
                rows = []
                for p in psutil.process_iter(["pid", "name", "cmdline"]):
                    info = p.info
                    name = info.get("name") or ""
                    if pattern and not pattern.search(name):
                        continue
                    rows.append({
                        "pid": info.get("pid"),
                        "name": name,
                        "cmdline": " ".join(info.get("cmdline") or []),
                        "is_tracked": info.get("pid") in tracked_pids,
                    })
                    if len(rows) >= 100:
                        break
            except Exception as exc:
                return f"list_processes failed: {exc}"
            return json.dumps({"count": len(rows), "processes": rows})

        else:
            return await super()._dispatch_tool(tool_name, args, evidence)

    # ------------------------------------------------------------------

    @staticmethod
    async def _run_command(
        command: str, cwd: str, shell_raw: bool = False,
    ) -> tuple[str, str, int]:
        """Run one command, killing its entire process tree on timeout.

        Uses a Windows Job Object + CREATE_NEW_PROCESS_GROUP so hung standalone
        .exe grandchildren (git.exe, hostname.exe, python.exe) are torn down and
        cannot keep stdout pipes open past the timeout (BH-003 / T13).
        """
        command = _pin_runtime_python(command)
        extra = _subprocess_kwargs()
        job = _WinJobObject()
        proc = None
        try:
            if shell_raw:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=_scrubbed_child_env(),
                    **extra,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=_scrubbed_child_env(),
                    **extra,
                )
            if proc.pid:
                job.assign(proc.pid)
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=_CMD_TIMEOUT
                )
            except asyncio.TimeoutError as exc:
                _kill_process_tree(proc.pid, job=job)
                try:
                    await asyncio.wait_for(proc.communicate(), timeout=5)
                except asyncio.TimeoutError as cleanup_exc:
                    raise WorkerError(
                        f"Command timed out after {_CMD_TIMEOUT}s and did not terminate cleanly: {command}"
                    ) from cleanup_exc
                raise WorkerError(f"Command timed out after {_CMD_TIMEOUT}s: {command}") from exc
            except asyncio.CancelledError:
                # Cancellation must not leave a command tree holding pipes or
                # running after the worker has stopped awaiting it.
                _kill_process_tree(proc.pid, job=job)
                try:
                    await asyncio.wait_for(proc.communicate(), timeout=5)
                except asyncio.TimeoutError as cleanup_exc:
                    raise WorkerError(
                        f"Command cancellation did not terminate cleanly: {command}"
                    ) from cleanup_exc
                raise
            return (
                stdout_bytes.decode(errors="replace"),
                stderr_bytes.decode(errors="replace"),
                proc.returncode or 0,
            )
        finally:
            # Closing a job handle must happen on success, timeout, cancellation,
            # and subprocess-start failures.  The job has no kill-on-close limit.
            job.close()
