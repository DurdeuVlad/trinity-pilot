"""Terminal-friendly CLI for the running unified desktop app."""
from __future__ import annotations

import argparse
import json
import time

from mcp_server.app_command_pipe import ensure_desktop_app_started, send_command_via_pipe


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Control the running TrinityPilot desktop app")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "start-ui",
        help="Launch the desktop app if needed and wait for the command surface",
        description="Launch the TrinityPilot desktop app if it is not already running and wait until the command surface is ready.",
    )
    subparsers.add_parser(
        "list-cases",
        help="List canonical live test cases",
        description="List canonical live test cases exposed through the desktop app command surface.",
    )
    subparsers.add_parser(
        "reset-session",
        help="Reset run state between repeated live iterations",
        description="Reset desktop-app session state after a run reaches terminal state so the next live iteration starts cleanly.",
    )
    subparsers.add_parser(
        "shutdown-ui",
        help="Shut down the desktop app after the batch",
        description="Schedule desktop-app shutdown after final artifact collection so the UI and owned backend sessions are not left running.",
    )

    submit_case = subparsers.add_parser(
        "submit-case",
        help="Submit one canonical live test case",
        description="Submit one canonical live test case by case id through the running desktop app.",
    )
    submit_case.add_argument("case_id")

    submit_task = subparsers.add_parser(
        "submit-task",
        help="Submit an ad hoc task",
        description="Submit an ad hoc task description and domain through the running desktop app.",
    )
    submit_task.add_argument("--description", required=True)
    submit_task.add_argument("--domain", default="mixed")

    get_run_status = subparsers.add_parser(
        "get-run-status",
        help="Get task status and recent events",
        description="Read one run's current status, steps, and latest live events from the desktop app.",
    )
    get_run_status.add_argument("task_id", nargs="?", default="latest")
    get_run_status.add_argument("--after-sequence", type=int, default=0)

    list_runs = subparsers.add_parser(
        "list-runs",
        help="List recent runs",
        description="List recent runs known to the desktop app history manager.",
    )
    list_runs.add_argument("--limit", type=int, default=20)

    stream_events = subparsers.add_parser(
        "stream-events",
        help="Stream live events until terminal state",
        description="Poll incremental live events for one run until it reaches a terminal status.",
    )
    stream_events.add_argument("task_id", nargs="?", default="latest")
    stream_events.add_argument("--poll-seconds", type=float, default=1.0)

    get_bundle = subparsers.add_parser(
        "get-artifact-bundle",
        help="Fetch the normalized artifact bundle",
        description="Read the normalized artifact bundle for one run from the desktop app command surface.",
    )
    get_bundle.add_argument("task_id", nargs="?", default="latest")

    approve = subparsers.add_parser(
        "approve-intervention",
        help="Resume after a bounded-drift intervention",
        description="Approve a bounded-drift intervention and resume the currently paused run.",
    )
    approve.add_argument("task_id", nargs="?", default="latest")

    terminate = subparsers.add_parser(
        "terminate-run",
        help="Request policy termination for a run",
        description="Request policy-stop termination for a run and wait for terminal state reconciliation.",
    )
    terminate.add_argument("task_id", nargs="?", default="latest")
    terminate.add_argument("--reason", default="terminated from terminal command surface")

    tail_latest = subparsers.add_parser(
        "tail-latest-run",
        help="Read the latest run's event tail",
        description="Fetch the latest run's live events starting after an optional sequence cursor.",
    )
    tail_latest.add_argument("--after-sequence", type=int, default=0)

    args = parser.parse_args()

    if args.command == "start-ui":
        _print_json(ensure_desktop_app_started())
        return 0
    if args.command == "list-cases":
        _print_json(send_command_via_pipe("list-cases"))
        return 0
    if args.command == "reset-session":
        _print_json(send_command_via_pipe("reset-session"))
        return 0
    if args.command == "shutdown-ui":
        _print_json(send_command_via_pipe("shutdown-ui"))
        return 0
    if args.command == "submit-case":
        _print_json(send_command_via_pipe("submit-case", args={"case_id": args.case_id}))
        return 0
    if args.command == "submit-task":
        _print_json(send_command_via_pipe("submit-task", args={"description": args.description, "domain": args.domain}))
        return 0
    if args.command == "get-run-status":
        _print_json(send_command_via_pipe("get-run-status", args={"task_id": args.task_id, "after_sequence": args.after_sequence}))
        return 0
    if args.command == "list-runs":
        _print_json(send_command_via_pipe("list-runs", args={"limit": args.limit}))
        return 0
    if args.command == "get-artifact-bundle":
        _print_json(send_command_via_pipe("get-artifact-bundle", args={"task_id": args.task_id}))
        return 0
    if args.command == "approve-intervention":
        _print_json(send_command_via_pipe("approve-intervention", args={"task_id": args.task_id}))
        return 0
    if args.command == "terminate-run":
        _print_json(send_command_via_pipe("terminate-run", args={"task_id": args.task_id, "reason": args.reason}))
        return 0
    if args.command == "tail-latest-run":
        _print_json(send_command_via_pipe("tail-latest-run", args={"after_sequence": args.after_sequence}))
        return 0
    if args.command == "stream-events":
        after_sequence = 0
        terminal_statuses = {"completed", "failed", "policy_terminated", "terminal_failure", "cancelled"}
        while True:
            response = send_command_via_pipe(
                "stream-events",
                args={"task_id": args.task_id, "after_sequence": after_sequence, "limit": 200},
            )
            _print_json(response)
            for event in response.get("payload", {}).get("events", []):
                after_sequence = max(after_sequence, int(event.get("sequence", 0)))
                if event.get("status") in terminal_statuses:
                    return 0
            time.sleep(args.poll_seconds)
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
