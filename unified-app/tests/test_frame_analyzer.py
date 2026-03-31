"""Unit tests for FrameAnalyzer.analyze() — A-03 coverage.

Regression: this class had zero test coverage until 2026-03-10.
pytest-qt's qtbot fixture is used so QApplication is alive when QImage is constructed.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QImage

from orchestrator.frame_analyzer import FrameAnalyzer


def test_analyze_returns_not_exists_for_missing_path(qtbot):
    """Non-existent path → exists=False, width=0, height=0, size_bytes=0."""
    analyzer = FrameAnalyzer()

    result = analyzer.analyze("/no/such/path/frame_99999.png")

    assert result["exists"] is False
    assert result["width"] == 0
    assert result["height"] == 0
    assert result["size_bytes"] == 0


def test_analyze_returns_correct_dimensions_for_valid_png(qtbot, tmp_path):
    """Valid 20×10 PNG → exists=True, correct width/height, size_bytes > 0."""
    png_path = tmp_path / "test_frame.png"

    # Create a real PNG using QImage (QApplication already live via qtbot)
    img = QImage(20, 10, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    assert img.save(str(png_path)), "QImage.save() must succeed for this test to be valid"

    analyzer = FrameAnalyzer()

    result = analyzer.analyze(str(png_path))

    assert result["exists"] is True
    assert result["width"] == 20
    assert result["height"] == 10
    assert result["size_bytes"] > 0
    assert result["suffix"] == ".png"
    assert result["name"] == "test_frame.png"
