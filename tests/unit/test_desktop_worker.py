"""DesktopWorker unit tests - no real desktop automation."""
from __future__ import annotations

import builtins

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.workers.desktop_worker import DesktopWorker


def _desktop_spec() -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="desktop-1",
        goal='Inspect app "Calculator"',
        dependencies=[],
        domain=DomainType.DESKTOP,
        required_capabilities=["desktop_automation"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["desktop evidence captured or degraded"],
        evidence_bundle=["screenshot"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )


class TestDesktopWorkerDegradedMode:
    async def test_execute_sets_degraded_mode_when_uia_and_screenshot_imports_fail(
        self, monkeypatch
    ):
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in {"pywinauto", "pyautogui"}:
                raise ModuleNotFoundError(name)
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("sys.platform", "win32")
        monkeypatch.setattr(builtins, "__import__", fake_import)

        evidence = await DesktopWorker().execute(_desktop_spec())

        assert evidence["degraded_mode"] is True
        assert evidence["screenshot"] is None
        assert evidence["element_tree_snapshot"] is None
        assert any("UIA failed" in item for item in evidence["action_log"])
        assert any("Screenshot failed" in item for item in evidence["action_log"])
