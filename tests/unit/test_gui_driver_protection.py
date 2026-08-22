from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import tests.e2e._gui_driver as gui_driver
from tests.e2e._gui_driver import STATUS_DONE, AppDriver, _ProtectedEnvFile


def _make_writable(path):
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def test_protected_env_file_restores_modified_bytes(tmp_path):
    path = tmp_path / ".env"
    original = b"LLM_PROVIDER=openai\nOPENAI_API_KEY=local-only\n"
    path.write_bytes(original)

    guard = _ProtectedEnvFile(path)
    _make_writable(path)
    path.write_bytes(b"accidental overwrite\n")
    guard.restore()

    assert path.read_bytes() == original


def test_protected_env_file_restores_deleted_file(tmp_path):
    path = tmp_path / ".env"
    original = b"LLM_PROVIDER=openai\n"
    path.write_bytes(original)

    guard = _ProtectedEnvFile(path)
    _make_writable(path)
    path.unlink()
    guard.restore()

    assert path.read_bytes() == original


def test_wait_for_stall_observation_never_sends_app_input(monkeypatch):
    """A slow task must not be cancelled by the GUI test harness."""
    driver = object.__new__(AppDriver)
    driver._proc = SimpleNamespace(poll=lambda: None)
    driver._win = object()
    driver.infra_checkpoints = {"execution_started": True}

    statuses = iter(("Executing...", STATUS_DONE))
    clock = iter((0.0, 0.0, 0.02, 0.03, 0.03, 0.03))
    monkeypatch.setattr(gui_driver.time, "monotonic", lambda: next(clock, 0.03))
    monkeypatch.setattr(gui_driver.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        AppDriver,
        "_read_status",
        staticmethod(lambda _window: next(statuses, STATUS_DONE)),
    )

    input_calls = []
    monkeypatch.setattr(
        AppDriver,
        "_wait_for_ready_without_input",
        staticmethod(lambda *_args, **_kwargs: input_calls.append(True)),
    )

    assert driver.wait_for({STATUS_DONE}, timeout=1, stall_nudge_after=0.01) == STATUS_DONE
    assert input_calls == []
