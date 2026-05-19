"""Entry point for `python -m trinity_pilot`.

Lazy-imports PySide6 only when actually launching the UI so headless
environments (CI, worker nodes) can import trinity_pilot without error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Shared crashes directory — all crash artefacts land here.
CRASHES_DIR = Path(__file__).parent.parent / "crashes"


def _ensure_crashes_dir() -> Path:
    CRASHES_DIR.mkdir(exist_ok=True)
    return CRASHES_DIR


def _install_crash_hooks() -> None:
    """Install Python-level and C-level crash handlers.

    1. sys.excepthook   — unhandled Python exceptions in the main thread
    2. threading.excepthook — unhandled exceptions in background threads
    3. faulthandler     — C-level crashes: segfault, stack overflow, Qt abort
    """
    import datetime
    import faulthandler
    import traceback
    import threading

    crashes = _ensure_crashes_dir()

    # ── faulthandler (C-level) ─────────────────────────────────────────────
    fault_log = crashes / f"fault-{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}.log"
    try:
        _fh = open(fault_log, "w", encoding="utf-8")  # noqa: WPS515 — kept open intentionally
        faulthandler.enable(file=_fh, all_threads=True)
    except Exception:
        faulthandler.enable()   # fallback: dump to stderr

    # ── Python main-thread exceptions ────────────────────────────────────
    def _main_hook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_crash("main-thread", msg, crashes)
        print(msg, file=sys.stderr)

    sys.excepthook = _main_hook

    # ── Python background-thread exceptions ──────────────────────────────
    def _thread_hook(args):
        msg = "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback
        ))
        thread_name = getattr(args.thread, "name", "unknown-thread")
        _write_crash(f"thread-{thread_name}", msg, crashes)
        print(f"[THREAD CRASH: {thread_name}]\n{msg}", file=sys.stderr)

    threading.excepthook = _thread_hook


def _write_crash(source: str, traceback_str: str, crashes_dir: Path) -> Path | None:
    """Write a crash report JSON and return its path."""
    import datetime, json
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    path = crashes_dir / f"crash-{ts}-{source[:40]}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.datetime.now().isoformat(),
                "source": source,
                "traceback": traceback_str,
            }, f, indent=2, ensure_ascii=False)
        return path
    except Exception:
        return None


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
        "--test-mode",
        action="store_true",
        help="Skip crash hooks and enable graceful WM_CLOSE shutdown (used by E2E tests).",
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

    if not args.test_mode:
        _install_crash_hooks()

    if args.worker:
        print("--worker is deprecated; orchestration now runs in-process.", file=sys.stderr)
    else:
        try:
            from trinity_pilot.ui.app import run_app
            run_app(test_mode=args.test_mode)
        except ImportError as exc:
            print(f"UI unavailable (PySide6 not installed?): {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
