from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ui.overlay.execution_overlay import ExecutionOverlay


def test_overlay_steer_controls_follow_execution_state(qtbot) -> None:
    overlay = ExecutionOverlay()
    qtbot.addWidget(overlay)

    assert overlay._steer_enabled is False  # noqa: SLF001
    assert overlay._steer_input is not None  # noqa: SLF001
    assert overlay._steer_btn is not None  # noqa: SLF001
    assert overlay._steer_input.isEnabled() is False  # noqa: SLF001

    overlay.set_steer_enabled(True)
    assert overlay._steer_input.isEnabled() is True  # noqa: SLF001
    assert overlay._steer_btn.isEnabled() is True  # noqa: SLF001

    overlay.show_blocker("Solve captcha")
    assert overlay._steer_input.isEnabled() is False  # noqa: SLF001

    overlay.clear_blocker()
    assert overlay._steer_input.isEnabled() is True  # noqa: SLF001

    overlay.show_paused()
    assert overlay._steer_input.isEnabled() is False  # noqa: SLF001


def test_overlay_steer_submit_trims_and_clears(qtbot) -> None:
    overlay = ExecutionOverlay()
    qtbot.addWidget(overlay)
    overlay.set_steer_enabled(True)
    received: list[str] = []
    overlay.steer_requested.connect(received.append)

    overlay._steer_input.setText("   use site x instead   ")  # noqa: SLF001
    overlay._emit_steer()  # noqa: SLF001

    assert received == ["use site x instead"]
    assert overlay._steer_input.text() == ""  # noqa: SLF001

    overlay._steer_input.setText("   ")  # noqa: SLF001
    overlay._emit_steer()  # noqa: SLF001
    assert received == ["use site x instead"]
