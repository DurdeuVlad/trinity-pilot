"""
Command-line tool for controlling the unified app via MCP.

Usage:
    python tools/app_control.py start
    python tools/app_control.py submit "Open Notepad" --domain desktop
    python tools/app_control.py status <run_id>
    python tools/app_control.py stop
    python tools/app_control.py logs [--tail N]
"""
import argparse
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.app_command_pipe import (
    ensure_desktop_app_started,
    send_command_via_pipe,
    CommandSurfaceUnavailable,
)
from mcp_server.task_submission_pipe import submit_task_via_pipe


def start_app():
    """Start the unified app if not running."""
    print("Starting unified app...")
    try:
        result = ensure_desktop_app_started()
        if result.get("launched"):
            print(f"✅ App started (PID: {result.get('pid')})")
        else:
            print(f"✅ App already running: {result.get('message')}")
        return 0
    except CommandSurfaceUnavailable as e:
        print(f"❌ Failed to start app: {e}")
        return 1


def submit_task(description: str, domain: str = "cli"):
    """Submit a task to the running app."""
    print(f"Submitting task: {description}")
    print(f"Domain: {domain}")
    try:
        result = submit_task_via_pipe(description=description, domain=domain)
        print(f"Result: {result}")
        task_id = result.get("task_id") or result.get("run_id")
        if task_id and result.get("ok"):
            print(f"✅ Task submitted: {task_id}")
            print(f"   Status: {result.get('status')}")
            return 0
        else:
            error = result.get("error") or result.get("message") or "Unknown error"
            print(f"❌ Task submission failed: {error}")
            return 1
    except Exception as e:
        import traceback
        print(f"❌ Error: {e}")
        traceback.print_exc()
        return 1


def get_status(run_id: str):
    """Get status of a running task."""
    print(f"Checking status of run: {run_id}")
    try:
        result = send_command_via_pipe("get-run-status", args={"run_id": run_id})
        status = result.get("status")
        print(f"Status: {status}")
        if result.get("payload"):
            print(f"Details: {result['payload']}")
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


def stop_app():
    """Stop the unified app."""
    print("Stopping unified app...")
    try:
        result = send_command_via_pipe("shutdown")
        print(f"✅ {result.get('message', 'App stopped')}")
        return 0
    except CommandSurfaceUnavailable:
        print("✅ App not running")
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


def show_logs(tail: int = 50):
    """Show recent logs from the app."""
    log_file = Path(__file__).parent.parent / "_runtime" / "logs" / "main.stderr.log"
    if not log_file.exists():
        print(f"❌ Log file not found: {log_file}")
        return 1
    
    print(f"Last {tail} lines from {log_file.name}:")
    print("=" * 80)
    
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        for line in lines[-tail:]:
            print(line.rstrip())
    
    return 0


def main():
    parser = argparse.ArgumentParser(description="Control the unified app via MCP")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Start command
    subparsers.add_parser("start", help="Start the app")
    
    # Submit command
    submit_parser = subparsers.add_parser("submit", help="Submit a task")
    submit_parser.add_argument("description", help="Task description")
    submit_parser.add_argument("--domain", default="cli", choices=["cli", "browser", "desktop", "mixed"],
                               help="Task domain")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Get task status")
    status_parser.add_argument("run_id", help="Run ID to check")
    
    # Stop command
    subparsers.add_parser("stop", help="Stop the app")
    
    # Logs command
    logs_parser = subparsers.add_parser("logs", help="Show recent logs")
    logs_parser.add_argument("--tail", type=int, default=50, help="Number of lines to show")
    
    args = parser.parse_args()
    
    if args.command == "start":
        return start_app()
    elif args.command == "submit":
        return submit_task(args.description, args.domain)
    elif args.command == "status":
        return get_status(args.run_id)
    elif args.command == "stop":
        return stop_app()
    elif args.command == "logs":
        return show_logs(args.tail)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
