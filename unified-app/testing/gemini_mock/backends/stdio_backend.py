"""Stdio backend for pipe-driven Gemini mock responses."""
from __future__ import annotations

import json
import sys
from typing import Any

from testing.gemini_mock.mock_genai import GenerationConfig, _flatten_prompt


class StdioBackend:
    """Write prompt metadata to stdout and read one response line from stdin."""

    def respond(self, prompt: Any, model_name: str, generation_config: GenerationConfig) -> str:
        """Send one NDJSON prompt to stdout and return one stdin response line."""
        message = json.dumps(
            {
                "prompt": _flatten_prompt(prompt),
                "model": model_name,
                "mime_type": generation_config.response_mime_type or "text/plain",
            }
        )
        sys.stdout.write(message + "\n")
        sys.stdout.flush()
        response_line = sys.stdin.readline()
        if not response_line:
            raise RuntimeError("StdioBackend: stdin closed unexpectedly")
        return response_line.rstrip("\n")
