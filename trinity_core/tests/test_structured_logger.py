"""Unit tests for trinity_core.logging.StructuredLogger."""

from __future__ import annotations

import json
import logging
import pytest

from trinity_core.structured_logging import StructuredLogger, get_logger
from trinity_core.structured_logging.structured_logger import _JsonFormatter


class TestStructuredLogger:
    def _capture(self, logger: StructuredLogger) -> list[str]:
        """Return a list buffer and attach it to the underlying logger."""
        records: list[str] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(self.format(record))

        handler = _ListHandler()
        handler.setFormatter(_JsonFormatter())
        logger._logger.handlers.clear()
        logger._logger.addHandler(handler)
        logger._logger.setLevel(logging.DEBUG)
        return records

    def test_info_produces_json(self):
        logger = StructuredLogger("test.info")
        captured = self._capture(logger)
        logger.info("hello world")
        assert len(captured) == 1
        obj = json.loads(captured[0])
        assert obj["level"] == "INFO"
        assert obj["message"] == "hello world"
        assert "timestamp" in obj

    def test_all_levels_emitted(self):
        logger = StructuredLogger("test.levels")
        captured = self._capture(logger)
        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        logger.critical("c")
        levels = [json.loads(r)["level"] for r in captured]
        assert levels == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def test_context_manager_adds_fields(self):
        logger = StructuredLogger("test.ctx")
        captured = self._capture(logger)
        with logger.context(task_id="abc", domain="web"):
            logger.info("inside context")
        obj = json.loads(captured[0])
        assert obj["context"]["task_id"] == "abc"
        assert obj["context"]["domain"] == "web"

    def test_context_fields_removed_after_block(self):
        logger = StructuredLogger("test.ctx_cleanup")
        captured = self._capture(logger)
        with logger.context(task_id="abc"):
            pass
        logger.info("outside context")
        obj = json.loads(captured[0])
        assert "task_id" not in obj.get("context", {})

    def test_extra_kwargs_appear_in_context(self):
        logger = StructuredLogger("test.extra")
        captured = self._capture(logger)
        logger.info("msg", tool="my_tool")
        obj = json.loads(captured[0])
        assert obj["context"]["tool"] == "my_tool"

    def test_json_has_file_line_function(self):
        logger = StructuredLogger("test.meta")
        captured = self._capture(logger)
        logger.info("check meta")
        obj = json.loads(captured[0])
        assert "file" in obj
        assert "line" in obj
        assert "function" in obj

    def test_get_logger_factory(self):
        logger = get_logger("test.factory")
        assert isinstance(logger, StructuredLogger)
