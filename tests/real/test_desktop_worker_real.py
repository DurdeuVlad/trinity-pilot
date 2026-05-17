"""Real desktop worker test - runs DesktopWorker directly with live Gemini."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.workers.desktop_worker import DesktopWorker

pytestmark = pytest.mark.real


def _desktop_spec(goal: str, timeout_seconds: int = 90) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="real-desktop-worker-isolated",
        goal=goal,
        dependencies=[],
        domain=DomainType.DESKTOP,
        required_capabilities=["desktop_automation", "file_write", "app_launch"],
        risk_class=RiskClass.LOW,
        preconditions=["Windows interactive desktop", "GEMINI_API_KEY set"],
        success_tests=["target file exists with expected marker"],
        evidence_bundle=["action_log", "written_files", "worker_result_status"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
        metadata={
            "timeout_seconds": timeout_seconds,
            "max_agent_steps": 8,
        },
    )


def _notepad_pids_for(path: Path) -> set[int]:
    target = str(path).lower()
    return {
        pid for pid, cmdline in _notepad_processes().items()
        if target in cmdline
    }


def _notepad_processes() -> dict[int, str]:
    try:
        import psutil
    except Exception:
        return {}

    processes: dict[int, str] = {}
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name == "notepad.exe":
            processes[int(proc.info["pid"])] = cmdline
    return processes


def _close_notepads(pids: set[int]) -> None:
    if not pids:
        return
    try:
        import psutil
    except Exception:
        return

    for pid in pids:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            continue


@pytest.mark.skipif(sys.platform != "win32", reason="Desktop worker real test requires Windows")
async def test_real_gemini_desktop_worker_writes_file_and_launches_notepad(
    gemini_api_key: str,
    tmp_path: Path,
):
    """Bypass orchestrator: live Gemini -> DesktopWorker tool loop -> real desktop side effect."""
    del gemini_api_key  # Fixture enforces that the key exists; DesktopWorker reads the env var.

    target = tmp_path / "trinity-worker-real-notepad.txt"
    marker = "TRINITY_DESKTOP_WORKER_REAL_GEMINI_OK"
    goal = (
        f"Write this marker to {target.as_posix()}: {marker} "
        "Then launch notepad.exe with that exact file path as its argument. "
        "After Notepad is launched, finish with success."
    )

    worker = DesktopWorker()
    evidence = None
    preexisting_notepad_pids = set(_notepad_processes())
    launched_pids: set[int] = set()

    try:
        evidence = await worker.execute(_desktop_spec(goal))
        launched_pids = _notepad_pids_for(target)
        assert evidence["domain"] == "desktop"
        assert evidence["worker_result_status"] == "success"
        assert target.exists()
        assert marker in target.read_text(encoding="utf-8")
        assert str(target).replace("\\", "/") in evidence["written_files"]
        assert launched_pids, "Notepad was not launched with the target file path"
        assert any("Wrote file" in item for item in evidence["action_log"])
        assert any("Launched: notepad.exe" in item for item in evidence["action_log"])
    finally:
        new_notepad_pids = set(_notepad_processes()) - preexisting_notepad_pids
        _close_notepads(launched_pids | _notepad_pids_for(target) | new_notepad_pids)
