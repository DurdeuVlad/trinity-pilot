"""Check if the named pipe server is accessible."""
import os
import time
from multiprocessing.connection import Client

PIPE_AUTHKEY = b"orchestrator-mcp"
PIPE_NAME = "orchestrator-task-submit"


def get_pipe_address() -> str:
    """Return platform-specific pipe address."""
    if os.name == "nt":
        return rf"\\.\pipe\{PIPE_NAME}"
    return f"_runtime/{PIPE_NAME}.sock"


def main():
    """Check pipe server accessibility."""
    address = get_pipe_address()
    family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
    
    print(f"Checking pipe server at: {address}")
    print(f"Family: {family}")
    
    try:
        print("\nAttempting to connect...")
        conn = Client(address, family=family, authkey=PIPE_AUTHKEY)
        print("✅ Connected to pipe server!")
        
        # Send a test payload
        payload = {
            "request_id": "test-123",
            "description": "echo Pipe Test",
            "domain": "cli",
            "observe_timeout_seconds": 5.0
        }
        
        print(f"\nSending test payload: {payload}")
        conn.send(payload)
        
        # Wait for response
        if conn.poll(6.0):
            response = conn.recv()
            print(f"\n📋 Response received:")
            import json
            print(json.dumps(response, indent=2))
            
            if response.get('ok'):
                print("\n✅ Pipe server is working!")
                return 0
            else:
                print(f"\n⚠️ Pipe server returned error: {response.get('error_code')}")
                print(f"   Message: {response.get('message')}")
                return 1
        else:
            print("\n⚠️ No response from pipe server (timeout)")
            return 2
            
    except FileNotFoundError:
        print(f"\n❌ Pipe not found: {address}")
        print("   The unified-app GUI may not be running or pipe server not started.")
        return 3
    except ConnectionRefusedError:
        print(f"\n❌ Connection refused: {address}")
        print("   The pipe server is not accepting connections.")
        return 4
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 5


if __name__ == "__main__":
    exit(main())
