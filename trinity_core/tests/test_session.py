import json

from trinity_core.session import Session
from trinity_core.tools.base import ToolResult


def test_session_persists_and_loads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    session = Session(session_id="session-a")
    session.append_user_message("hello")
    session.append_assistant_message("world")
    session.append_tool_result("call-1", "echo", ToolResult(status="success", output="ok"))

    loaded = Session.load("session-a")
    assert len(loaded.messages) == 3
    assert loaded.messages[0]["role"] == "user"
    assert loaded.messages[1]["role"] == "assistant"
    assert loaded.messages[2]["tool_call_id"] == "call-1"

    lines = session.session_path.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["content"] == "hello"
