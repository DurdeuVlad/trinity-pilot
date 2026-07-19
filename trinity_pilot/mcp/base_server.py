"""Shared in-process control state for MCP worker servers."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ControlState:
    """Owns short-lived todo lists for one MCP server process."""

    todos: dict[str, list[dict[str, object]]] = field(default_factory=dict)

    def _render(self, session_id: str) -> dict:
        items = self.todos.get(session_id, [])
        return {
            "session_id": session_id,
            "items": [
                {"index": index, "text": item["text"], "done": item["done"]}
                for index, item in enumerate(items)
            ],
        }

    def write(self, items: list[str], session_id: str = "default") -> dict:
        self.todos[session_id] = [{"text": str(item), "done": False} for item in items]
        return self._render(session_id)

    def read(self, session_id: str = "default") -> dict:
        return self._render(session_id)

    def check(self, index: int, session_id: str = "default") -> dict:
        items = self.todos.get(session_id, [])
        if not 0 <= index < len(items):
            return {**self._render(session_id), "error": f"invalid todo index: {index}"}
        items[index]["done"] = True
        return self._render(session_id)

    def add(self, item: str, session_id: str = "default") -> dict:
        self.todos.setdefault(session_id, []).append({"text": item, "done": False})
        return self._render(session_id)
