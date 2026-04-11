from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ui.panels.execution_plan_panel import ExecutionPlanPanel


def test_execution_plan_panel_tracks_live_plan_revisions(qtbot) -> None:
    panel = ExecutionPlanPanel()
    qtbot.addWidget(panel)
    panel.display_plan(["Open the app"])
    panel.update_step_status(1, "running")

    panel.on_plan_state_updated(
        1,
        {
            "revision": 1,
            "steps": [
                {"title": "Launch application", "status": "done"},
                {"title": "Wait for window", "status": "in_progress"},
                {"title": "Read screen", "status": "pending"},
            ],
        },
    )

    widget = panel.step_widgets[0]
    assert widget._plan_count == 3  # noqa: SLF001
    assert [row.status_text for row in widget._plan_rows] == [  # noqa: SLF001
        "completed",
        "running",
        "pending",
    ]

    panel.on_plan_state_updated(
        1,
        {
            "revision": 2,
            "steps": [
                {"title": "Launch application", "status": "done"},
                {"title": "Wait for window", "status": "done"},
                {"title": "Read screen", "status": "in_progress"},
                {"title": "Extract result", "status": "pending"},
            ],
        },
    )

    assert [row.label_text for row in widget._plan_rows] == [  # noqa: SLF001
        "Launch application",
        "Wait for window",
        "Read screen",
        "Extract result",
    ]
    assert [row.status_text for row in widget._plan_rows] == [  # noqa: SLF001
        "completed",
        "completed",
        "running",
        "pending",
    ]
