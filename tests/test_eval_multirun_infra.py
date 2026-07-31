from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from eval_multirun import (
    ROOT,
    _default_guest_checkpoints,
    _normalize_infra_checkpoints,
    infra_passed_from_checkpoints,
    run_single,
)


def test_infra_passed_from_checkpoints() -> None:
    assert infra_passed_from_checkpoints({
        "app_launched": True,
        "window_connected": True,
        "prompt_submitted": True,
        "execution_started": True,
        "no_app_crash": True,
        "graceful_close": True,
    })
    assert not infra_passed_from_checkpoints({
        "app_launched": True,
        "window_connected": True,
        "prompt_submitted": False,
        "execution_started": True,
        "no_app_crash": True,
        "graceful_close": True,
    })
    assert not infra_passed_from_checkpoints({
        "vm_boot_ok": False,
        "app_launched": True,
        "window_connected": True,
        "prompt_submitted": True,
        "execution_started": True,
        "no_app_crash": True,
        "graceful_close": True,
    })


def test_default_guest_checkpoints_timeout() -> None:
    defaults = _default_guest_checkpoints("timeout")
    assert all(v is False for v in defaults.values())


def test_normalize_legacy_app_crashed_checkpoint() -> None:
    normalized = _normalize_infra_checkpoints({
        "app_launched": True,
        "window_connected": True,
        "prompt_submitted": True,
        "execution_started": True,
        "app_crashed": True,
        "graceful_close": True,
    })
    assert normalized["no_app_crash"] is True
    assert "app_crashed" not in normalized
    assert infra_passed_from_checkpoints(normalized)


def test_run_single_loads_temp_infra_json(tmp_path: Path) -> None:
    checkpoints = {
        "app_launched": True,
        "window_connected": True,
        "prompt_submitted": True,
        "execution_started": True,
        "no_app_crash": True,
        "graceful_close": True,
    }
    temp_file = ROOT / "temp_infra.json"

    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = "1 passed"
    completed.stderr = ""

    def _write_infra_and_return(*_args, **_kwargs):
        temp_file.write_text(json.dumps(checkpoints), encoding="utf-8")
        return completed

    logs_dir = tmp_path / "pytest_logs"
    with patch("eval_multirun.subprocess.run", side_effect=_write_infra_and_return):
        passed, elapsed, failure_type, loaded, trace_lines, last_event = run_single(
            "tests/e2e/test_gui_happy_path.py::test_terminal_create_file",
            logs_dir=logs_dir,
        )

    assert passed is True
    assert failure_type is None
    assert loaded == checkpoints
    assert trace_lines == []
    assert last_event is None
    assert not temp_file.exists()
    infra_files = list(logs_dir.glob("*_infra.json"))
    assert len(infra_files) == 1
    assert json.loads(infra_files[0].read_text(encoding="utf-8")) == checkpoints


def test_run_single_ignores_stale_temp_infra_when_pytest_writes_none(tmp_path: Path) -> None:
    stale = {
        "app_launched": True,
        "window_connected": True,
        "prompt_submitted": True,
        "execution_started": True,
        "app_crashed": True,
        "graceful_close": True,
    }
    temp_file = ROOT / "temp_infra.json"
    temp_file.write_text(json.dumps(stale), encoding="utf-8")

    completed = MagicMock()
    completed.returncode = 1
    completed.stdout = "1 failed"
    completed.stderr = ""

    logs_dir = tmp_path / "pytest_logs"
    with patch("eval_multirun.subprocess.run", return_value=completed):
        passed, _elapsed, failure_type, loaded, _trace_lines, _last_event = run_single(
            "tests/e2e/test_gui_native_t4.py::test_T4_desktop_notepad_multiply_native",
            logs_dir=logs_dir,
        )

    assert passed is False
    assert failure_type == "assertion"
    assert loaded == {}
    assert not temp_file.exists()
