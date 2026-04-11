"""Terminal-friendly CLI for the running unified desktop app."""
from __future__ import annotations

import argparse
import json
import time

from mcp_server.app_command_pipe import send_command_via_pipe


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Control the running TrinityPilot desktop app")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("start-ui")
    subparsers.add_parser("list-cases")

    submit_case = subparsers.add_parser("submit-case")
    submit_case.add_argument("case_id")

    submit_task = subparsers.add_parser("submit-task")
    submit_task.add_argument("--description", required=True)
    submit_task.add_argument("--domain", default="mixed")

    get_run_status = subparsers.add_parser("get-run-status")
    get_run_status.add_argument("task_id", nargs="?", default="latest")
    get_run_status.add_argument("--after-sequence", type=int, default=0)

    list_runs = subparsers.add_parser("list-runs")
    list_runs.add_argument("--limit", type=int, default=20)

    stream_events = subparsers.add_parser("stream-events")
    stream_events.add_argument("task_id", nargs="?", default="latest")
    stream_events.add_argument("--poll-seconds", type=float, default=1.0)

    get_bundle = subparsers.add_parser("get-artifact-bundle")
    get_bundle.add_argument("task_id", nargs="?", default="latest")

    approve = subparsers.add_parser("approve-intervention")
    approve.add_argument("task_id", nargs="?", default="latest")

    terminate = subparsers.add_parser("terminate-run")
    terminate.add_argument("task_id", nargs="?", default="latest")
    terminate.add_argument("--reason", default="terminated from terminal command surface")

    tail_latest = subparsers.add_parser("tail-latest-run")
    tail_latest.add_argument("--after-sequence", type=int, default=0)

    args = parser.parse_args()

    if args.command == "start-ui":
        _print_json(send_command_via_pipe("start-ui"))
        return 0
    if args.command == "list-cases":
        _print_json(send_command_via_pipe("list-cases"))
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
