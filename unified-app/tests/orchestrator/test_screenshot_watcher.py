"""Tests for screenshot watcher frame throttling."""
from __future__ import annotations

from pathlib import Path

from orchestrator.screenshot_watcher import ScreenshotWatcher


def test_screenshot_watcher_respects_max_fps_gate(tmp_path):
    screenshot_dir = Path(tmp_path)
    first = screenshot_dir / "frame-01.png"
    second = screenshot_dir / "frame-02.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    watcher = ScreenshotWatcher(screenshot_dir=str(screenshot_dir), max_fps=1)
    emitted: list[str] = []
    watcher.frame_captured.connect(lambda path: emitted.append(path))

    watcher.scan_directory()

    assert len(emitted) == 1


def test_screenshot_watcher_respects_max_frame_count(tmp_path):
    screenshot_dir = Path(tmp_path)
    for index in range(3):
        (screenshot_dir / f"frame-{index:02d}.png").write_bytes(f"frame-{index}".encode("utf-8"))

    watcher = ScreenshotWatcher(screenshot_dir=str(screenshot_dir), max_fps=30, max_frames=2)
    emitted: list[str] = []
    watcher.frame_captured.connect(lambda path: emitted.append(path))

    watcher.scan_directory()

    assert len(emitted) == 2
