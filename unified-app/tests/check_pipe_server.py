"""Check if the task submission pipe server is accessible."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from multiprocessing.connection import Client

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from mcp_server.task_submission_pipe import PIPE_AUTHKEY, get_pipe_address, get_pipe_family


def main() -> int:
    """Check pipe server accessibility."""
    address = get_pipe_address()
    family = get_pipe_family()

    print(f"Checking pipe server at: {address}")
    print(f"Family: {family}")

    try:
        print("\nAttempting to connect...")
        conn = Client(address, family=family, authkey=PIPE_AUTHKEY)
        print("Connected to pipe server.")

        payload = {
            "request_id": "test-123",
            "description": "echo Pipe Test",
            "domain": "cli",
            "observe_timeout_seconds": 5.0,
        }

        print(f"\nSending test payload: {payload}")
        conn.send(payload)

        if conn.poll(6.0):
            response = conn.recv()
            print("\nResponse received:")
            print(json.dumps(response, indent=2))

            if response.get("ok"):
                print("\nPipe server is working.")
                return 0

            print(f"\nPipe server returned error: {response.get('error_code')}")
            print(f"   Message: {response.get('message')}")
            return 1

        print("\nNo response from pipe server (timeout).")
        return 2

    except FileNotFoundError:
        print(f"\nPipe not found: {address}")
        print("   The unified-app GUI may not be running or pipe server not started.")
        return 3
    except ConnectionRefusedError:
        print(f"\nConnection refused: {address}")
        print("   The pipe server is not accepting connections.")
        return 4
    except Exception as exc:
        print(f"\nError: {exc}")
        import traceback

        traceback.print_exc()
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
