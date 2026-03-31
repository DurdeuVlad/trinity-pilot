"""Tests for glass box panel."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from ui.panels.glass_box_panel import GlassBoxPanel


def _create_png(path: Path) -> None:
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(0x0000FF)
    image.save(str(path))


def test_glass_box_panel_displays_frame(tmp_path):
    _ = QApplication.instance() or QApplication([])
    panel = GlassBoxPanel()
    path = tmp_path / "frame.png"
    _create_png(path)

    panel.display_frame(str(path))
    assert panel.current_frame == 1
    assert panel.screenshot_label.pixmap() is not None


def test_glass_box_panel_reset():
    _ = QApplication.instance() or QApplication([])
    panel = GlassBoxPanel()
    panel.current_frame = 5
    panel.update_fps(2.4)
    panel.reset()
    assert panel.current_frame == 0
    assert panel.current_fps == 0.0
