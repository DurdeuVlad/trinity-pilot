"""Entry point for `python -m trinity_pilot`.

Lazy-imports PySide6 only when actually launching the UI so headless
environments (CI, worker nodes) can import trinity_pilot without error.
"""
from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trinity-pilot",
        description="Trinity Pilot — LLM-orchestrated desktop automation agent",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help="Deprecated no-op; orchestration now runs in-process.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="trinity-pilot 0.1.0",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.worker:
        print("--worker is deprecated; orchestration now runs in-process.", file=sys.stderr)
    else:
        try:
            from trinity_pilot.ui.app import run_app
            run_app()
        except ImportError as exc:
            print(f"UI unavailable (PySide6 not installed?): {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
