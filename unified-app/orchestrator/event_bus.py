"""Orchestrator-layer event bus with execution_complete signal."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class EventBus(QObject):
    execution_complete = pyqtSignal(object)  # dict payload
    execution_started = pyqtSignal()
    execution_failed = pyqtSignal(str)
    step_started = pyqtSignal(int, str)
    step_done = pyqtSignal(int, bool, str)
    status_message = pyqtSignal(str, str)
    task_cancelled = pyqtSignal()
