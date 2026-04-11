"""Screenshot monitoring for glass-box live view."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import monotonic

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class ScreenshotWatcher(QObject):
    """Poll screenshot directory and emit newly discovered frames."""

    frame_captured = pyqtSignal(bytes)
    frame_rate_updated = pyqtSignal(float)

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

        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self.calculate_fps)
        self._fps_timer.setInterval(1000)

        self.seen_files: set[str] = set()
        self.frame_count = 0
        self.start_time: datetime | None = None
        self.max_fps = max(1, max_fps)
        self.max_frames = max(1, max_frames)
        self._last_scan_at = monotonic()
        self._emit_budget = float(self.max_fps)

    def start_watching(self) -> None:
        """Start directory monitoring."""
        self.seen_files.clear()
        self.frame_count = 0
        self.start_time = datetime.now()
        self._last_scan_at = monotonic()
        self._emit_budget = float(self.max_fps)
        self.scan_directory()
        self._poll_timer.start()
        self._fps_timer.start()

    def stop_watching(self) -> None:
        """Stop directory monitoring."""
        self._poll_timer.stop()
        self._fps_timer.stop()
        self.start_time = None

    def scan_directory(self) -> None:
        """Emit signal for any newly created image frame."""
        if not self.screenshot_dir.exists():
            return
        patterns = ("*.png", "*.jpg", "*.jpeg")
        for pattern in patterns:
            for file_path in sorted(self.screenshot_dir.glob(pattern)):
                key = str(file_path.resolve())
                if key in self.seen_files:
                    continue
                self.seen_files.add(key)
                if self._can_emit_frame():
                    try:
                        frame_bytes = file_path.read_bytes()
                    except OSError:
                        continue
                    self.frame_count += 1
                    self.frame_captured.emit(frame_bytes)

    def calculate_fps(self) -> None:
        """Emit current frames-per-second estimate."""
        if self.start_time is None or self.frame_count == 0:
            return
        elapsed = (datetime.now() - self.start_time).total_seconds()
        if elapsed <= 0:
            return
        self.frame_rate_updated.emit(self.frame_count / elapsed)

    def set_max_fps(self, max_fps: int) -> None:
        """Update the frame emission ceiling used by the watcher."""

        self.max_fps = max(1, max_fps)
        self._emit_budget = min(float(self.max_fps), self._emit_budget)

    def set_max_frames(self, max_frames: int) -> None:
        """Update the total frame emission ceiling used by the watcher."""

        self.max_frames = max(1, max_frames)

    def _can_emit_frame(self) -> bool:
        now = monotonic()
        elapsed = now - self._last_scan_at
        self._last_scan_at = now
        self._emit_budget = min(float(self.max_fps), self._emit_budget + elapsed * self.max_fps)
        if self.frame_count >= self.max_frames:
            return False
        if self._emit_budget < 1.0:
            return False
        self._emit_budget -= 1.0
        return True
