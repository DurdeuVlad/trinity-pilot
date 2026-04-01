from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from testing.gemini_mock.mock_genai import GenerationConfig
from testing.gemini_mock.server import HttpBackend, run_server


def _get_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read())


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def test_run_server_exposes_queue_and_calls_endpoints() -> None:
    server = run_server(port=0)
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    time.sleep(0.05)

    try:
        assert _get_json(f"{base_url}/status") == {
            "status": "ok",
            "queue_length": 0,
            "call_count": 0,
        }
        assert _post_json(f"{base_url}/push", {"response": "queued"})["ok"] is True
        assert _get_json(f"{base_url}/next_response")["response"] == "queued"
        assert isinstance(_get_json(f"{base_url}/calls")["calls"], list)
        assert _post_json(f"{base_url}/reset", {})["ok"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_http_backend_records_call_and_fetches_response() -> None:
    server = run_server(port=0)
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    time.sleep(0.05)

    try:
        _post_json(f"{base_url}/push", {"response": "http response"})
        backend = HttpBackend(base_url)

        assert backend.respond("prompt text", "gemini", GenerationConfig()) == "http response"
        calls = _get_json(f"{base_url}/calls")["calls"]
        assert calls[0]["prompt"] == "prompt text"
        assert calls[0]["model_name"] == "gemini"
    finally:
        server.shutdown()
        server.server_close()


def test_server_returns_404_for_unknown_path() -> None:
    server = run_server(port=0)
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    time.sleep(0.05)

    try:
        try:
            urllib.request.urlopen(f"{base_url}/missing", timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            assert json.loads(exc.read()) == {"error": "not found"}
        else:
            raise AssertionError("unknown path should return 404")
    finally:
        server.shutdown()
        server.server_close()
