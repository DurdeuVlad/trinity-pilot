from __future__ import annotations

import io
from unittest.mock import patch

from testing.gemini_mock.backends.stdio_backend import StdioBackend
from testing.gemini_mock.mock_genai import GenerationConfig


def test_stdio_backend_writes_prompt_and_reads_response() -> None:
    backend = StdioBackend()
    config = GenerationConfig(response_mime_type="application/json")

    with patch("sys.stdin", io.StringIO("queued response\n")), patch("sys.stdout", io.StringIO()) as stdout:
        result = backend.respond(["plan this", object()], "gemini-2.0-flash-exp", config)

    assert result == "queued response"
    written = stdout.getvalue()
    assert '"model": "gemini-2.0-flash-exp"' in written
    assert '"mime_type": "application/json"' in written
    assert "plan this" in written


def test_stdio_backend_raises_on_eof() -> None:
    backend = StdioBackend()

    with patch("sys.stdin", io.StringIO("")), patch("sys.stdout", io.StringIO()):
        try:
            backend.respond("prompt", "gemini", GenerationConfig())
        except RuntimeError as exc:
            assert "stdin closed unexpectedly" in str(exc)
        else:
            raise AssertionError("StdioBackend should raise on EOF")
