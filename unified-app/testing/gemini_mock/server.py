"""HTTP control server and backend for cross-process Gemini mock use."""
from __future__ import annotations

import json
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from testing.gemini_mock.backends.queue_backend import QueueBackend
from testing.gemini_mock.mock_genai import GenerationConfig, _flatten_prompt


class MockControlServer(ThreadingHTTPServer):
    """Threaded control server that owns a queue backend and call log."""

    allow_reuse_address = True

    def __init__(self, host: str = "localhost", port: int = 8765) -> None:
        self.backend = QueueBackend()
        self._lock = threading.Lock()
        super().__init__((host, port), _MockHandler)

    def server_bind(self) -> None:
        """Enable address reuse before binding the server socket."""
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()


class _MockHandler(BaseHTTPRequestHandler):
    """Serve queue/call operations for the Gemini mock control API."""

    @property
    def mock_server(self) -> MockControlServer:
        """Return the typed server instance for this request."""
        return cast(MockControlServer, self.server)

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        """Write one JSON response with the given status code."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        """Read and decode one JSON request body."""
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def _pop_response(self) -> str:
        """Return the next queued response or the backend default."""
        with self.mock_server._lock:
            if self.mock_server.backend._queue:
                return self.mock_server.backend._queue.popleft()
            return self.mock_server.backend.default_response

    def do_GET(self) -> None:
        """Handle GET endpoints for status, queued responses, and call logs."""
        if self.path == "/status":
            with self.mock_server._lock:
                queue_length = len(self.mock_server.backend._queue)
                call_count = len(self.mock_server.backend.calls)
            self._send_json({"status": "ok", "queue_length": queue_length, "call_count": call_count})
            return
        if self.path == "/next_response":
            self._send_json({"response": self._pop_response()})
            return
        if self.path == "/calls":
            with self.mock_server._lock:
                calls = list(self.mock_server.backend.calls)
            self._send_json({"calls": calls})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        """Handle POST endpoints for queue and call-log mutation."""
        payload = self._read_json()
        if self.path == "/push":
            self.mock_server.backend.push(str(payload.get("response", "")))
            self._send_json({"ok": True})
            return
        if self.path == "/push_many":
            responses = [str(item) for item in payload.get("responses", [])]
            self.mock_server.backend.push_many(responses)
            self._send_json({"ok": True, "count": len(responses)})
            return
        if self.path == "/record_call":
            call = {
                "prompt": str(payload.get("prompt", ""))[:500],
                "model_name": str(payload.get("model_name", "")),
                "mime_type": str(payload.get("mime_type", "")),
            }
            with self.mock_server._lock:
                self.mock_server.backend.calls.append(call)
            self._send_json({"ok": True})
            return
        if self.path == "/reset":
            self.mock_server.backend.reset()
            self._send_json({"ok": True})
            return
        self._send_json({"error": "not found"}, status=404)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default request logging."""


class HttpBackend:
    """Forward Gemini mock calls to a running MockControlServer."""

    def __init__(self, server_url: str = "http://localhost:8765") -> None:
        self.server_url = server_url.rstrip("/")

    def _get(self, path: str) -> dict[str, Any]:
        """Read one JSON response from the server."""
        with urllib.request.urlopen(f"{self.server_url}{path}", timeout=10) as response:
            return json.loads(response.read())

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send one JSON request body to the server."""
        request = urllib.request.Request(
            f"{self.server_url}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def respond(self, prompt: Any, model_name: str, generation_config: GenerationConfig) -> str:
        """Record the prompt and fetch the next queued response from the server."""
        self._post(
            "/record_call",
            {
                "prompt": _flatten_prompt(prompt),
                "model_name": model_name,
                "mime_type": generation_config.response_mime_type or "text/plain",
            },
        )
        return str(self._get("/next_response")["response"])


def run_server(host: str = "localhost", port: int = 8765) -> MockControlServer:
    """Start a control server in a daemon thread and return it."""
    server = MockControlServer(host=host, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
