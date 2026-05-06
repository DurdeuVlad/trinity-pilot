from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget, QPlainTextEdit, QPushButton, QTextEdit

import app as app_module
from event_bus import get_event_bus


pytestmark = pytest.mark.e2e


class _ArtifactOrchestrator:
    def __init__(self, artifact: Path, objectives: list[str], domain: str) -> None:
        self.artifact = artifact
        self.objectives = objectives
        self.domain = domain
        self.planned_task = ""
        self.executed_task = ""

    def start_planning(self, task: str) -> None:
        self.planned_task = task
        bus = get_event_bus()
        bus.busy_changed.emit(True)
        bus.chat_reply.emit("Generating execution plan...")
        bus.plan_ready.emit(list(self.objectives))
        bus.busy_changed.emit(False)

    def start_execution(self, task: str, objectives: list[str]) -> None:
        self.executed_task = task
        bus = get_event_bus()
        bus.busy_changed.emit(True)
        bus.execution_started.emit()

        self.artifact.parent.mkdir(parents=True, exist_ok=True)
        self.artifact.write_text(
            "\n".join(
                [
                    "domain=cli",
                    f"expected_domain={self.domain}",
                    f"task={task}",
                    "objectives=" + " | ".join(objectives),
                ]
            ),
            encoding="utf-8",
        )

        output = f"wrote {self.artifact}"
        for i, objective in enumerate(objectives, start=1):
            bus.step_started.emit(i, objective)
            bus.step_done.emit(i, True, output)
        bus.status_message.emit(output, "success")
        bus.execution_done.emit(True, output)
        bus.busy_changed.emit(False)

    def cancel(self) -> None:
        get_event_bus().task_cancelled.emit()

    def shutdown(self) -> bool:
        return True


@pytest.mark.parametrize(
    ("domain", "prompt"),
    [
        ("cli", "Create a CLI smoke artifact from the real unified app user flow"),
        ("web", "Open a documentation page and summarize it through the unified app flow"),
        ("desktop", "Open a desktop app after the user accepts the plan"),
        ("mixed", "Research a page and save a local summary after plan acceptance"),
    ],
)
def test_user_prompt_plan_acceptance_and_run_create_artifact(
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    domain: str,
    prompt: str,
) -> None:
    artifact = tmp_path / f"user_flow_smoke_{domain}.txt"
    generated_objectives = [
        f"Create the smoke artifact at {artifact}",
        f"Handle the request as domain {domain}",
        "Report the artifact path",
    ]
    orchestrator = _ArtifactOrchestrator(artifact, generated_objectives, domain)
    monkeypatch.setattr(app_module, "OrchestratorCore", lambda: orchestrator)

    window = app_module.MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    input_box = window.findChild(QPlainTextEdit)
    assert input_box is not None

    qtbot.mouseClick(input_box.viewport(), Qt.MouseButton.LeftButton)
    qtbot.keyClicks(input_box, prompt)
    qtbot.keyClick(input_box, Qt.Key.Key_Return)

    plan_list = window.findChild(QListWidget)
    assert plan_list is not None
    qtbot.waitUntil(lambda: plan_list.count() == len(generated_objectives), timeout=5000)
    assert [plan_list.item(i).text() for i in range(plan_list.count())] == generated_objectives

    run_button = next(
        button for button in window.findChildren(QPushButton)
        if button.text() == "Run"
    )

    qtbot.mouseClick(run_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: artifact.exists(), timeout=5000)

    text = artifact.read_text(encoding="utf-8")
    assert "domain=cli" in text
    assert f"expected_domain={domain}" in text
    assert prompt in text
    assert generated_objectives[0] in text
    assert orchestrator.planned_task == prompt
    assert orchestrator.executed_task == prompt

    histories = window.findChildren(QTextEdit)
    assert histories
    qtbot.waitUntil(
        lambda: any("Done:" in history.toPlainText() for history in histories),
        timeout=5000,
    )
