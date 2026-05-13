"""Unit tests for MCP terminal server tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trinity_pilot.mcp.terminal_server import terminal_run


class TestMcpTerminalRun:
    async def test_terminal_run_returns_evidence_dict(self):
        fake_evidence = {
            "domain": "terminal",
            "objective_id": "obj-1",
            "stdout": "hi\n",
            "stderr": "",
            "exit_code": 0,
            "created_files": [],
            "workspace": "/tmp/test",
            "error": None,
        }
        with patch(
            "trinity_pilot.mcp.terminal_server.TerminalWorker.execute",
            new_callable=AsyncMock,
            return_value=fake_evidence,
        ):
            result = await terminal_run(
                objective_id="obj-1",
                goal="echo hi",
                success_tests=["stdout contains hi"],
            )
        assert result["exit_code"] == 0
        assert result["stdout"] == "hi\n"

    async def test_terminal_run_passes_objective_id(self):
        fake_evidence = {
            "domain": "terminal",
            "objective_id": "obj-smoke",
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "created_files": [],
            "workspace": "/tmp",
            "error": None,
        }
        captured: list = []

        async def _capture(spec):
            captured.append(spec)
            return fake_evidence

        with patch(
            "trinity_pilot.mcp.terminal_server.TerminalWorker.execute",
            side_effect=_capture,
        ):
            await terminal_run(
                objective_id="obj-smoke",
                goal="true",
                success_tests=["exit_code is 0"],
            )

        assert captured[0].objective_id == "obj-smoke"

    def test_terminal_run_invalid_risk_class_raises(self):
        with pytest.raises(ValueError):
            # RiskClass("not-a-valid-class") should raise immediately at spec creation
            import asyncio
            asyncio.run(
                terminal_run(
                    objective_id="obj-1",
                    goal="echo hi",
                    success_tests=["ok"],
                    risk_class="not-a-valid-class",
                )
            )
