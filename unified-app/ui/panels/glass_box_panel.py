"""Glass-box panel for real-time screenshot feedback."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class GlassBoxPanel(QWidget):
    """Display most recent screenshot frame and capture metrics."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.current_frame = 0
        self.current_fps = 0.0
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("Glass Box Live View")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        self.screenshot_label = QLabel()
        self.screenshot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screenshot_label.setMinimumSize(400, 260)
        self.screenshot_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.screenshot_label.setStyleSheet("background-color: #1f1f1f; border: 1px solid #555;")
        layout.addWidget(self.screenshot_label, stretch=1)

        info_row = QHBoxLayout()
        self.frame_info_label = QLabel("Waiting for frames...")
        self.meta_label = QLabel("")
        self.fps_label = QLabel("FPS: 0.0")
        info_row.addWidget(self.frame_info_label)
        info_row.addWidget(self.meta_label)
        info_row.addStretch()
        info_row.addWidget(self.fps_label)
        layout.addLayout(info_row)

        self.show_empty_state()

    def show_empty_state(self) -> None:
        """Reset to default empty-state content."""
        self.screenshot_label.setPixmap(QPixmap())
        self.screenshot_label.setText("No live frame yet")
        self.screenshot_label.setStyleSheet(
            "background-color: #1f1f1f; color: #888; border: 1px solid #555; font-size: 14px;"
        )

    @pyqtSlot(bytes)
    def display_frame(self, frame_data: bytes) -> None:
        """Render a raw JPEG frame received from the CDP screencast."""
        if not frame_data:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(frame_data):
            return

        scaled = pixmap.scaled(
            self.screenshot_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.screenshot_label.setText("")
        self.screenshot_label.setPixmap(scaled)
        self.screenshot_label.setStyleSheet("background-color: #000; border: 1px solid #555;")
        self.current_frame += 1
        self.frame_info_label.setText(f"Frame: {self.current_frame}")

    @pyqtSlot(float)
    def update_fps(self, fps: float) -> None:
        """Update current fps label."""
        self.current_fps = fps
        self.fps_label.setText(f"FPS: {fps:.1f}")

    def reset(self) -> None:
        """Reset state before a new execution starts."""
        self.current_frame = 0
        self.current_fps = 0.0
        self.frame_info_label.setText("Waiting for frames...")
        self.meta_label.setText("")
        self.fps_label.setText("FPS: 0.0")
        self.show_empty_state()

    def update_metadata(self, width: int, height: int, size_bytes: int) -> None:
        """Display lightweight frame metadata."""
        kb = size_bytes / 1024 if size_bytes else 0
        self.meta_label.setText(f"{width}x{height} {kb:.1f}KB")
