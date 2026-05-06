from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.event_bus import EventBus


def test_event_bus_mirrors_status_to_console(capsys) -> None:
    bus = EventBus()

    bus.emit_status("Live steps:\n[ok] Open app", "plan")

    captured = capsys.readouterr()
    assert "Live steps:" in captured.out
    assert "[ok] Open app" in captured.out


def test_event_bus_exposes_steer_signal() -> None:
    bus = EventBus()
    received: list[str] = []

    bus.steer_input.connect(received.append)
    bus.steer_input.emit("prefer keyboard shortcuts")

    assert received == ["prefer keyboard shortcuts"]
