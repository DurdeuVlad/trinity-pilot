from __future__ import annotations

import io
import json
import sys
from unittest.mock import patch

from testing.gemini_mock import cli


def test_cli_status_prints_server_state(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_get", lambda url: {"status": "ok", "queue_length": 2, "call_count": 3})
    stdout = io.StringIO()

    with patch.object(sys, "argv", ["testing.gemini_mock", "status"]), patch("sys.stdout", stdout):
        cli.main()

    assert "queue_length: 2" in stdout.getvalue()
    assert "call_count:   3" in stdout.getvalue()


def test_cli_calls_prints_table(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "_get",
        lambda url: {"calls": [{"prompt": "prompt text", "model_name": "gemini", "mime_type": "application/json"}]},
    )
    stdout = io.StringIO()

    with patch.object(sys, "argv", ["testing.gemini_mock", "calls"]), patch("sys.stdout", stdout):
        cli.main()

    output = stdout.getvalue()
    assert "Model" in output
    assert "prompt text" in output


def test_cli_push_posts_response(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, payload: dict[str, object]) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        return {"ok": True}

    monkeypatch.setattr(cli, "_post", fake_post)
    stdout = io.StringIO()

    with patch.object(
        sys,
        "argv",
        ["testing.gemini_mock", "push", '{"steps":["x"],"estimated_duration":5,"confidence":0.8}'],
    ), patch("sys.stdout", stdout):
        cli.main()

    assert captured["url"] == "http://localhost:8765/push"
    assert json.loads(captured["payload"]["response"])["steps"] == ["x"]
    assert "queued" in stdout.getvalue().lower()
