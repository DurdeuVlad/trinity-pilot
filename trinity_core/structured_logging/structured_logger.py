"""Structured JSON logger for trinity_core.

Wraps stdlib logging and emits JSON records including context fields such as
task_id, domain, runtime, and tool.  Context fields can be attached for the
lifetime of a with-block using the context() context manager.
"""

from __future__ import annotations

import json
import logging
import threading
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

# Thread-local storage for scoped context fields.
_context_local = threading.local()


def _get_context() -> dict[str, Any]:
    if not hasattr(_context_local, "stack"):
        _context_local.stack = [{}]
    merged: dict[str, Any] = {}
    for frame in _context_local.stack:
        merged.update(frame)
    return merged


class _JsonFormatter(logging.Formatter):
    """Format a LogRecord as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = _get_context()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName,
        }
        if ctx:
            payload["context"] = ctx
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class StructuredLogger:
    """Application-level structured logger backed by stdlib logging.

    Usage::

        logger = StructuredLogger("trinity_core.orchestrators.browser_runtime")
        logger.info("Task started")

        with logger.context(task_id="abc", domain="web"):
            logger.info("Running tool loop")
    """

    def __init__(self, name: str, level: int = logging.INFO) -> None:
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(_JsonFormatter())
            self._logger.addHandler(console_handler)
            
            # File handler - write to .logs/{date}.jsonl
            from pathlib import Path
            from datetime import datetime, timezone
            log_dir = Path(".logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            log_file = log_dir / f"{date_str}.jsonl"
            file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
            file_handler.setFormatter(_JsonFormatter())
            self._logger.addHandler(file_handler)
            
            self._logger.propagate = False
        self._logger.setLevel(level)

    # -------------------------------------------------------------------------
    # Log level methods
    # -------------------------------------------------------------------------

    def debug(self, message: str, **extra: Any) -> None:
        self._emit(logging.DEBUG, message, extra)

    def info(self, message: str, **extra: Any) -> None:
        self._emit(logging.INFO, message, extra)

    def warning(self, message: str, **extra: Any) -> None:
        self._emit(logging.WARNING, message, extra)

    def error(self, message: str, **extra: Any) -> None:
        self._emit(logging.ERROR, message, extra)

    def critical(self, message: str, **extra: Any) -> None:
        self._emit(logging.CRITICAL, message, extra)

    # -------------------------------------------------------------------------
    # Context manager
    # -------------------------------------------------------------------------

    @contextmanager
    def context(self, **fields: Any) -> Generator[None, None, None]:
        """Attach scoped context fields to all log records within the block."""
        if not hasattr(_context_local, "stack"):
            _context_local.stack = [{}]
        _context_local.stack.append(fields)
        try:
            yield
        finally:
            _context_local.stack.pop()

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _emit(self, level: int, message: str, extra: dict[str, Any]) -> None:
        if extra:
            # Push extra fields as an inner context frame for this single call.
            if not hasattr(_context_local, "stack"):
                _context_local.stack = [{}]
            _context_local.stack.append(extra)
            try:
                self._logger.log(level, message, stacklevel=3)
            finally:
                _context_local.stack.pop()
        else:
            self._logger.log(level, message, stacklevel=3)


def get_logger(name: str, level: int = logging.INFO) -> StructuredLogger:
    """Return a StructuredLogger for *name*."""
    return StructuredLogger(name, level=level)
