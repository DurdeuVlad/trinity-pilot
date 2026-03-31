from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.e2e import _e2e_support as e2e_support


class _FakeApp:
    def __init__(self) -> None:
        self.process_events_calls = 0

    def processEvents(self) -> None:  # noqa: N802
        self.process_events_calls += 1


def test_wait_for_pumps_events_until_predicate_turns_true(monkeypatch):
    app = _FakeApp()
    checks = {"count": 0}
    timeline = iter([0.0, 0.01, 0.02, 0.03])

    monkeypatch.setattr(e2e_support.time, "monotonic", lambda: next(timeline))
    monkeypatch.setattr(e2e_support.time, "sleep", lambda _seconds: None)

    def predicate() -> bool:
        checks["count"] += 1
        return checks["count"] >= 3

    e2e_support.wait_for(predicate, app, timeout_seconds=0.05)

    assert checks["count"] == 3
    assert app.process_events_calls == 3


def test_submit_task_and_collect_waits_for_orchestrator_cleanup(monkeypatch):
    wait_calls: list[bool] = []

    class FakeSignalSpy(list):
        def __init__(self, _signal: object) -> None:
            super().__init__([["done"]])

    class FakeCombo:
        def __init__(self) -> None:
            self.current_index = None

        def findText(self, label: str) -> int:  # noqa: N802
            return 1 if label == "CLI" else -1

        def setCurrentIndex(self, index: int) -> None:  # noqa: N802
            self.current_index = index

    class FakeTaskInput:
        def __init__(self) -> None:
            self.value = None

        def setText(self, value: str) -> None:  # noqa: N802
            self.value = value

    class FakeRunButton:
        def __init__(self) -> None:
            self.enabled = True

        def isEnabled(self) -> bool:  # noqa: N802
            return self.enabled

    class FakeTaskInputPanel:
        def __init__(self) -> None:
            self.domain_combo = FakeCombo()
            self.task_input = FakeTaskInput()
            self.run_btn = FakeRunButton()
            self.clicked = False

        def on_run_clicked(self) -> None:
            self.clicked = True

    class FakeItem:
        def __init__(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

    class FakeTable:
        def item(self, row: int, column: int) -> FakeItem | None:
            if (row, column) == (0, 4):
                return FakeItem("task-123")
            return None

    class FakeQuery:
        def __init__(self, result):
            self._result = result

        def filter_by(self, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return self._result

        def all(self):
            return self._result

    class FakeSession:
        def __init__(self, task, steps) -> None:
            self._task = task
            self._steps = steps

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def query(self, model):
            if model is e2e_support.TaskHistory:
                return FakeQuery(self._task)
            if model is e2e_support.ExecutionStep:
                return FakeQuery(self._steps)
            raise AssertionError(f"Unexpected model lookup: {model!r}")

    class FakeHistoryManager:
        def __init__(self, task, steps) -> None:
            self._task = task
            self._steps = steps

        def get_session(self) -> FakeSession:
            return FakeSession(self._task, self._steps)

    class FakeHistoryView:
        def __init__(self, task, steps) -> None:
            self.table = FakeTable()
            self.history_manager = FakeHistoryManager(task, steps)
            self.load_calls = 0

        def load_history(self) -> None:
            self.load_calls += 1

    task = SimpleNamespace(task_id="task-123", status=SimpleNamespace(value="completed"), error_message=None, result_data='{"status":"success"}')
    step = SimpleNamespace(result_data='{"status":"success","artifacts":[],"metadata":{"raw_result":{"status":"success"}}}')
    window = SimpleNamespace(
        event_bus=SimpleNamespace(execution_complete=object()),
        task_input_panel=FakeTaskInputPanel(),
        orchestrator=SimpleNamespace(current_thread="busy", current_worker="busy"),
        history_view=FakeHistoryView(task, [step]),
    )

    def fake_wait_for(predicate, _app, timeout_seconds=30.0):
        wait_calls.append(predicate())
        if len(wait_calls) == 1:
            assert wait_calls[-1] is True
            return
        assert wait_calls[-1] is False
        window.orchestrator.current_thread = None
        window.orchestrator.current_worker = None
        assert predicate() is True

    monkeypatch.setattr(e2e_support, "QSignalSpy", FakeSignalSpy)
    monkeypatch.setattr(e2e_support, "wait_for", fake_wait_for)

    result = e2e_support.submit_task_and_collect(
        app=_FakeApp(),
        window=window,
        description="List files in current directory",
        domain_label="CLI",
        timeout_seconds=5.0,
    )

    assert wait_calls == [True, False]
    assert window.task_input_panel.clicked is True
    assert window.history_view.load_calls == 1
    assert result["task_id"] == "task-123"
    assert result["status"] == "completed"
    assert result["step_payloads"][0]["status"] == "success"


def test_submit_task_and_collect_rejects_unknown_domain():
    class FakeSignalSpy(list):
        def __init__(self, _signal: object) -> None:
            super().__init__()

    window = SimpleNamespace(
        event_bus=SimpleNamespace(execution_complete=object()),
        task_input_panel=SimpleNamespace(
            domain_combo=SimpleNamespace(findText=lambda _label: -1),
            task_input=SimpleNamespace(setText=lambda _value: None),
            run_btn=SimpleNamespace(isEnabled=lambda: True),
            on_run_clicked=lambda: None,
        ),
    )

    original_signal_spy = e2e_support.QSignalSpy
    e2e_support.QSignalSpy = FakeSignalSpy
    with pytest.raises(AssertionError, match="Unknown domain label"):
        try:
            e2e_support.submit_task_and_collect(
                app=_FakeApp(),
                window=window,
                description="noop",
                domain_label="Missing",
            )
        finally:
            e2e_support.QSignalSpy = original_signal_spy
