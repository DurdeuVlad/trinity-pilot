"""Dedicated terminal/session MCP server for durable dev-AI supervision."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


@dataclass(slots=True)
class TerminalEvent:
    sequence: int
    stream: str
    text: str
    timestamp: float


@dataclass(slots=True)
class TerminalSession:
    id: str
    cwd: str
    purpose: str
    env: dict[str, str]
    created_at: float
    updated_at: float
    status: str = "idle"
    process: subprocess.Popen[str] | None = None
    pid: int | None = None
    command: str | None = None
    events: list[TerminalEvent] = field(default_factory=list)
    next_sequence: int = 1
    lock: threading.Lock = field(default_factory=threading.Lock)


class TerminalSessionManager:
    """Manage durable subprocess sessions and cursor-based output reads."""

    def __init__(self, metadata_dir: Path | None = None) -> None:
        self.sessions: dict[str, TerminalSession] = {}
        self.metadata_dir = (metadata_dir or (Path(__file__).resolve().parents[1] / "_runtime" / "terminal_sessions")).resolve()
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, *, cwd: str, purpose: str = "", env: dict[str, str] | None = None) -> TerminalSession:
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        merged_env = dict(os.environ)
        merged_env.update(env or {})
        session = TerminalSession(
            id=session_id,
            cwd=str(Path(cwd).expanduser().resolve()),
            purpose=purpose,
            env=merged_env,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self.sessions[session_id] = session
        self._persist_session(session)
        return session

    def start_process(self, session_id: str, command: str) -> dict[str, Any]:
        session = self.sessions[session_id]
        if session.process and session.process.poll() is None:
            raise RuntimeError("session already has a running process")
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = subprocess.Popen(
            command,
            cwd=session.cwd,
            env=session.env,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        session.process = process
        session.pid = process.pid
        session.command = command
        session.status = "running"
        session.updated_at = time.time()
        self._append_event(session, "system", f"[start] {command}")
        self._spawn_reader(session, "stdout", process.stdout)
        self._spawn_reader(session, "stderr", process.stderr)
        threading.Thread(target=self._watch_process, args=(session,), daemon=True).start()
        self._persist_session(session)
        return self.get_session_status(session_id)

    def run_command(self, session_id: str, command: str, timeout_seconds: float = 60.0) -> dict[str, Any]:
        session = self.sessions[session_id]
        result = subprocess.run(
            command,
            cwd=session.cwd,
            env=session.env,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        session.updated_at = time.time()
        if result.stdout:
            self._append_event(session, "stdout", result.stdout.rstrip())
        if result.stderr:
            self._append_event(session, "stderr", result.stderr.rstrip())
        self._persist_session(session)
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def read_output(self, session_id: str, after_sequence: int = 0, stream: str = "merged", limit: int = 200) -> list[dict[str, Any]]:
        session = self.sessions[session_id]
        with session.lock:
            items = [event for event in session.events if event.sequence > after_sequence]
        if stream != "merged":
            items = [event for event in items if event.stream == stream]
        return [
            {
                "sequence": event.sequence,
                "stream": event.stream,
                "text": event.text,
                "timestamp": event.timestamp,
            }
            for event in items[:limit]
        ]

    def write_input(self, session_id: str, text: str) -> None:
        session = self.sessions[session_id]
        if session.process is None or session.process.stdin is None:
            raise RuntimeError("session has no interactive stdin")
        session.process.stdin.write(text)
        session.process.stdin.flush()
        session.updated_at = time.time()
        self._append_event(session, "stdin", text.rstrip())
        self._persist_session(session)

    def list_sessions(self) -> list[dict[str, Any]]:
        return [self.get_session_status(session_id) for session_id in sorted(self.sessions)]

    def get_session_status(self, session_id: str) -> dict[str, Any]:
        session = self.sessions[session_id]
        if session.process and session.status == "running" and session.process.poll() is not None:
            session.status = "exited" if session.process.returncode == 0 else "failed"
        return {
            "id": session.id,
            "cwd": session.cwd,
            "purpose": session.purpose,
            "status": session.status,
            "pid": session.pid,
            "command": session.command,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }

    def interrupt_session(self, session_id: str) -> dict[str, Any]:
        session = self.sessions[session_id]
        process = session.process
        if process is None or process.poll() is not None:
            return self.get_session_status(session_id)
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGINT)
        except Exception:
            process.terminate()
        session.status = "interrupted"
        session.updated_at = time.time()
        self._append_event(session, "system", "[interrupt]")
        self._persist_session(session)
        return self.get_session_status(session_id)

    def terminate_session(self, session_id: str) -> dict[str, Any]:
        session = self.sessions[session_id]
        process = session.process
        if process is None or process.poll() is not None:
            session.status = "terminated"
            return self.get_session_status(session_id)
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, check=False)
        else:
            process.kill()
        session.status = "terminated"
        session.updated_at = time.time()
        self._append_event(session, "system", "[terminate]")
        self._persist_session(session)
        return self.get_session_status(session_id)

    def close_session(self, session_id: str) -> dict[str, Any]:
        status = self.get_session_status(session_id)
        self.sessions.pop(session_id, None)
        self._delete_session_metadata(session_id)
        return status

    def tail_file(self, path: str, after_offset: int = 0, max_bytes: int = 8192) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(str(target))
        with target.open("rb") as handle:
            handle.seek(after_offset)
            chunk = handle.read(max_bytes)
            next_offset = handle.tell()
        return {
            "path": str(target),
            "next_offset": next_offset,
            "content": chunk.decode("utf-8", errors="replace"),
        }

    def list_artifacts(self, session_id: str) -> list[dict[str, Any]]:
        session = self.sessions[session_id]
        root = Path(session.cwd)
        if not root.exists():
            return []
        artifacts: list[dict[str, Any]] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
        if stat.st_mtime >= session.created_at:
                artifacts.append({"path": str(path), "size_bytes": stat.st_size, "modified_at": stat.st_mtime})
        return artifacts[:200]

    def _spawn_reader(self, session: TerminalSession, stream_name: str, stream: Any) -> None:
        if stream is None:
            return
        threading.Thread(target=self._read_stream, args=(session, stream_name, stream), daemon=True).start()

    def _read_stream(self, session: TerminalSession, stream_name: str, stream: Any) -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                self._append_event(session, stream_name, line.rstrip("\r\n"))
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _watch_process(self, session: TerminalSession) -> None:
        process = session.process
        if process is None:
            return
        returncode = process.wait()
        session.updated_at = time.time()
        if session.status not in {"interrupted", "terminated"}:
            session.status = "exited" if returncode == 0 else "failed"
        self._append_event(session, "system", f"[exit {returncode}]")
        self._persist_session(session)

    def _append_event(self, session: TerminalSession, stream: str, text: str) -> None:
        with session.lock:
            event = TerminalEvent(
                sequence=session.next_sequence,
                stream=stream,
                text=text,
                timestamp=time.time(),
            )
            session.events.append(event)
            session.next_sequence += 1
            session.updated_at = time.time()
        self._persist_session(session)

    def _persist_session(self, session: TerminalSession) -> None:
        payload = {
            "id": session.id,
            "cwd": session.cwd,
            "purpose": session.purpose,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "status": session.status,
            "pid": session.pid,
            "command": session.command,
            "events": [
                {
                    "sequence": event.sequence,
                    "stream": event.stream,
                    "text": event.text,
                    "timestamp": event.timestamp,
                }
                for event in session.events[-200:]
            ],
        }
        (self.metadata_dir / f"{session.id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _delete_session_metadata(self, session_id: str) -> None:
        target = self.metadata_dir / f"{session_id}.json"
        if target.exists():
            target.unlink()


class TerminalSessionMCPServer:
    """MCP tool surface for durable terminal sessions."""

    def __init__(self) -> None:
        self.server = Server("terminal-session-control")
        self.manager = TerminalSessionManager()
        self._register_tools()

    def _register_tools(self) -> None:
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(name="create_session", description="Create a terminal session", inputSchema={"type": "object", "properties": {"cwd": {"type": "string"}, "purpose": {"type": "string"}, "env": {"type": "object"}}, "required": ["cwd"], "additionalProperties": False}),
                Tool(name="start_process", description="Start a long-lived process in a session", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}, "command": {"type": "string"}}, "required": ["session_id", "command"], "additionalProperties": False}),
                Tool(name="run_command", description="Run a bounded command in a session", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}, "command": {"type": "string"}, "timeout_seconds": {"type": "number"}}, "required": ["session_id", "command"], "additionalProperties": False}),
                Tool(name="read_output", description="Read incremental output from a session", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}, "after_sequence": {"type": "integer"}, "stream": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["session_id"], "additionalProperties": False}),
                Tool(name="write_input", description="Write stdin to a session", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["session_id", "text"], "additionalProperties": False}),
                Tool(name="list_sessions", description="List terminal sessions", inputSchema={"type": "object", "properties": {}, "additionalProperties": False}),
                Tool(name="get_session_status", description="Get one session status", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"], "additionalProperties": False}),
                Tool(name="interrupt_session", description="Soft-interrupt a running session", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"], "additionalProperties": False}),
                Tool(name="terminate_session", description="Force-terminate a session process tree", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"], "additionalProperties": False}),
                Tool(name="close_session", description="Close session metadata", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"], "additionalProperties": False}),
                Tool(name="tail_file", description="Read a file incrementally by offset", inputSchema={"type": "object", "properties": {"path": {"type": "string"}, "after_offset": {"type": "integer"}, "max_bytes": {"type": "integer"}}, "required": ["path"], "additionalProperties": False}),
                Tool(name="list_artifacts", description="List files modified in the session cwd after session creation", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"], "additionalProperties": False}),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            args = arguments or {}
            try:
                if name == "create_session":
                    session = self.manager.create_session(cwd=args["cwd"], purpose=args.get("purpose", ""), env=args.get("env") or {})
                    payload = {"ok": True, "session": self.manager.get_session_status(session.id)}
                elif name == "start_process":
                    payload = {"ok": True, "session": self.manager.start_process(args["session_id"], args["command"])}
                elif name == "run_command":
                    payload = {"ok": True, "result": self.manager.run_command(args["session_id"], args["command"], float(args.get("timeout_seconds", 60.0)))}
                elif name == "read_output":
                    payload = {"ok": True, "events": self.manager.read_output(args["session_id"], int(args.get("after_sequence", 0)), str(args.get("stream", "merged")), int(args.get("limit", 200)))}
                elif name == "write_input":
                    self.manager.write_input(args["session_id"], args["text"])
                    payload = {"ok": True}
                elif name == "list_sessions":
                    payload = {"ok": True, "sessions": self.manager.list_sessions()}
                elif name == "get_session_status":
                    payload = {"ok": True, "session": self.manager.get_session_status(args["session_id"])}
                elif name == "interrupt_session":
                    payload = {"ok": True, "session": self.manager.interrupt_session(args["session_id"])}
                elif name == "terminate_session":
                    payload = {"ok": True, "session": self.manager.terminate_session(args["session_id"])}
                elif name == "close_session":
                    payload = {"ok": True, "session": self.manager.close_session(args["session_id"])}
                elif name == "tail_file":
                    payload = {"ok": True, "tail": self.manager.tail_file(args["path"], int(args.get("after_offset", 0)), int(args.get("max_bytes", 8192)))}
                elif name == "list_artifacts":
                    payload = {"ok": True, "artifacts": self.manager.list_artifacts(args["session_id"])}
                else:
                    payload = {"ok": False, "error": f"Unknown tool: {name}"}
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    async def run(self) -> None:
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream, self.server.create_initialization_options())


async def main() -> None:
    server = TerminalSessionMCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
