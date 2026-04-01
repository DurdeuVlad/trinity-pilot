"""CLI entrypoints for controlling a running Gemini mock server."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import Any


def _server_url(host: str, port: int) -> str:
    """Build the control server URL from host and port."""
    return f"http://{host}:{port}"


def _get(url: str) -> dict[str, Any]:
    """Fetch JSON from the given URL."""
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read())


def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Send one JSON payload to the given URL."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the control server and block until interrupted."""
    from testing.gemini_mock.server import MockControlServer

    server = MockControlServer(host=args.host, port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


def _cmd_push(args: argparse.Namespace) -> None:
    """Enqueue one response on the control server."""
    _post(f"{_server_url(args.host, args.port)}/push", {"response": args.response})
    print("Response queued.")


def _cmd_calls(args: argparse.Namespace) -> None:
    """Print a compact table of recorded calls."""
    calls = _get(f"{_server_url(args.host, args.port)}/calls").get("calls", [])
    if not calls:
        print("No calls recorded.")
        return
    print(f"{'#':<4} {'Model':<20} {'MIME':<20} Prompt")
    for index, call in enumerate(calls):
        prompt = str(call.get("prompt", "")).replace("\n", " ")[:60]
        print(f"{index:<4} {str(call.get('model_name', '')):<20} {str(call.get('mime_type', '')):<20} {prompt}")


def _cmd_status(args: argparse.Namespace) -> None:
    """Print current server health and queue state."""
    status = _get(f"{_server_url(args.host, args.port)}/status")
    print(f"status:       {status.get('status', 'unknown')}")
    print(f"queue_length: {status.get('queue_length', '?')}")
    print(f"call_count:   {status.get('call_count', '?')}")


def _cmd_reset(args: argparse.Namespace) -> None:
    """Clear the queue and recorded calls."""
    _post(f"{_server_url(args.host, args.port)}/reset", {})
    print("Queue and call log cleared.")


def main() -> None:
    """Run the Gemini mock control CLI."""
    parser = argparse.ArgumentParser(prog="python -m testing.gemini_mock")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8765)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve")
    push_parser = subparsers.add_parser("push")
    push_parser.add_argument("response")
    subparsers.add_parser("calls")
    subparsers.add_parser("status")
    subparsers.add_parser("reset")
    args = parser.parse_args()
    commands = {
        "serve": _cmd_serve,
        "push": _cmd_push,
        "calls": _cmd_calls,
        "status": _cmd_status,
        "reset": _cmd_reset,
    }
    commands[args.command](args)
