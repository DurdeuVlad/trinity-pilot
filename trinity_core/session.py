"""JSONL-backed conversation session state for runtime loops."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from .llm.llm_provider import ToolCall
from .tools.base import ToolResult


class Session:
    """Runtime session that stores user/assistant/tool events in JSONL format."""

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id = session_id or uuid.uuid4().hex
        self.messages: list[dict] = []
        sessions_dir = Path(".trinity") / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        self.session_path = sessions_dir / f"{self.session_id}.jsonl"

    def append_user_message(self, content: str) -> None:
        message = {"role": "user", "content": content}
        self.messages.append(message)
        self._persist(message)

    def append_assistant_message(self, content: str) -> None:
        message = {"role": "assistant", "content": content}
        self.messages.append(message)
        self._persist(message)

    def append_assistant_tool_calls(self, tool_calls: list[ToolCall], content: str = "") -> None:
        message = {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments),
                    },
                }
                for tool_call in tool_calls
            ],
        }
        self.messages.append(message)
        self._persist(message)

    def append_tool_result(self, tool_call_id: str, tool_name: str, result: ToolResult) -> None:
        message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "status": result.status,
            "content": result.output,
            "error": result.error,
            "metadata": result.metadata,
        }
        self.messages.append(message)
        self._persist(message)

    def _persist(self, message: dict) -> None:
        with self.session_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message) + "\n")

    @classmethod
    def load(cls, session_id: str) -> "Session":
        session = cls(session_id=session_id)
        if not session.session_path.exists():
            return session
        with session.session_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    session.messages.append(json.loads(line))
        return session
