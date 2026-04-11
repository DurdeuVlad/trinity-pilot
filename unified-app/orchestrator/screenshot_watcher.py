"""Screenshot directory monitor for history and recording."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QTimer


class ScreenshotWatcher(QObject):
    """Poll screenshot directory to track new frames for history/recording."""

    def __init__(
        self,
        screenshot_dir: str = "_runtime/screenshots",
        poll_ms: int = 250,
        max_fps: int = 5,
        max_frames: int = 100,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.scan_directory)
        self._poll_timer.setInterval(poll_ms)

        self.seen_files: set[str] = set()
        self.frame_count = 0
        self.max_fps = max(1, max_fps)
        self.max_frames = max(1, max_frames)

    def start_watching(self) -> None:
        """Start directory monitoring."""
        self.seen_files.clear()
        self.frame_count = 0
        self.scan_directory()
        self._poll_timer.start()

    def stop_watching(self) -> None:
        """Stop directory monitoring."""
        self._poll_timer.stop()

    def scan_directory(self) -> None:
        """Track newly created image frames for history/recording."""
        if not self.screenshot_dir.exists():
            return
        patterns = ("*.png", "*.jpg", "*.jpeg")
        for pattern in patterns:
            for file_path in sorted(self.screenshot_dir.glob(pattern)):
                key = str(file_path.resolve())
                if key in self.seen_files:
                    continue
                self.seen_files.add(key)
                if self.frame_count < self.max_frames:
                    self.frame_count += 1

    def set_max_fps(self, max_fps: int) -> None:
        self.max_fps = max(1, max_fps)

    def set_max_frames(self, max_frames: int) -> None:
        self.max_frames = max(1, max_frames)
