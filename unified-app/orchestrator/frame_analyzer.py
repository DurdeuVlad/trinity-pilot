"""Frame metadata extraction utilities for Sprint 2."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QImage


class FrameAnalyzer:
    """Extract lightweight metadata from screenshot frames."""

    def analyze(self, frame_path: str) -> dict:
        file_path = Path(frame_path)
        image = QImage(str(file_path))
        width = image.width() if not image.isNull() else 0
        height = image.height() if not image.isNull() else 0
        return {
            "path": str(file_path),
            "name": file_path.name,
            "suffix": file_path.suffix.lower(),
            "exists": file_path.exists(),
            "size_bytes": file_path.stat().st_size if file_path.exists() else 0,
            "width": width,
            "height": height,
        }
