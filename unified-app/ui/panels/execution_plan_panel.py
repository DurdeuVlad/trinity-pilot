"""Execution plan panel with objective status and live backend step timelines."""
from __future__ import annotations

from typing import Any, List

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.theme import (
    APP_BG,
    BORDER,
    DANGER,
    MUTED,
    SUCCESS,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_WEAK,
)

_INFO = "#58a6ff"
_WAIT = "#d29922"
_RUNNING_BG = "#13263a"
_SUCCESS_BG = "#10251a"
_FAILED_BG = "#2b1518"
_PENDING_BG = SURFACE

_ACTION_LABELS = {
    "browse": "browser",
    "desktop": "desktop",
    "cli": "cli",
}


def _normalize_text(text: str) -> str:
    normalized = str(text or "")
    replacements = {
        "Ã¢â€ â€™": "->",
        "â†’": "->",
        "Ã¢â‚¬Â¦": "...",
        "â€¦": "...",
        "Ã¢â‚¬â€": " - ",
        "â€”": " - ",
        "â€“": " - ",
        "Ã¢Å“â€œ": "OK",
        "âœ“": "OK",
        "Ã¢Å“â€”": "X",
        "âœ—": "X",
        "Ã¢â€“Â¶": ">",
        "â–¶": ">",
        "Ã¢â€“Â¼": "v",
        "â–¼": "v",
        "Ã¢â€”Â": "*",
        "â—": "*",
        "â€œ": '"',
        "â€": '"',
        "â€˜": "'",
        "â€™": "'",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized


def _normalize_step_status(status: Any) -> str:
    normalized = str(status or "pending").strip().lower()
    return {
        "done": "completed",
        "success": "completed",
        "completed": "completed",
        "in_progress": "running",
        "running": "running",
        "failed": "failed",
        "failure": "failed",
        "blocked": "waiting",
        "pending": "pending",
    }.get(normalized, "pending")


def _step_label(step: dict[str, Any], index: int) -> str:
    return _normalize_text(
        str(
            step.get("title")
            or step.get("command")
            or step.get("action")
            or step.get("expectedResult")
            or f"step {index}"
        )
    )


def _step_note(step: dict[str, Any]) -> str:
    notes = step.get("notes")
    if isinstance(notes, list) and notes:
        return _normalize_text(str(notes[-1]))
    note = step.get("note")
    if note:
        return _normalize_text(str(note))
    return ""


class _ActionRow(QFrame):
    """One action turn inside an objective timeline."""

    def __init__(self, step_num: int, action_type: str, result: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ObjectiveActionRow")
        self.setStyleSheet(
            f"QFrame#ObjectiveActionRow {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:8px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        step_tag = QLabel(f"T{step_num}")
        step_tag.setFixedWidth(28)
        step_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        step_tag.setStyleSheet(
            f"background:#0d1117; color:{MUTED}; border:1px solid {BORDER}; "
            "border-radius:9px; font-size:10px; font-weight:700; padding:1px 0;"
        )
        layout.addWidget(step_tag)

        action_tag = QLabel(_ACTION_LABELS.get(action_type, _normalize_text(action_type or "tool")))
        action_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_tag.setMinimumWidth(64)
        action_tag.setStyleSheet(
            f"background:#13263a; color:{_INFO}; border:1px solid {_INFO}; "
            "border-radius:9px; font-size:10px; font-weight:700; padding:1px 8px;"
        )
        layout.addWidget(action_tag)

        result_label = QLabel(_normalize_text(result[:140] + ("..." if len(result) > 140 else "")))
        result_label.setWordWrap(True)
        result_label.setStyleSheet(f"color:{TEXT}; font-size:11px; background:transparent;")
        layout.addWidget(result_label, stretch=1)


class _PlanRow(QFrame):
    """One low-level backend plan step inside an objective."""

    STYLES = {
        "pending": {"tag": "[ ]", "fg": MUTED, "border": BORDER, "bg": SURFACE},
        "running": {"tag": "[run]", "fg": _INFO, "border": _INFO, "bg": "#10253b"},
        "completed": {"tag": "[ok]", "fg": SUCCESS, "border": SUCCESS, "bg": "#13291b"},
        "failed": {"tag": "[x]", "fg": DANGER, "border": DANGER, "bg": "#311519"},
        "waiting": {"tag": "[wait]", "fg": _WAIT, "border": _WAIT, "bg": "#2a1f00"},
    }

    def __init__(self, index: int, label: str, status: str, note: str = "", parent=None) -> None:
        super().__init__(parent)
        self._status = _normalize_step_status(status)
        self._label_text = label
        self._note_text = note

        self.setObjectName("ObjectivePlanRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._tag = QLabel("")
        self._tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tag.setMinimumWidth(44)
        layout.addWidget(self._tag)

        index_label = QLabel(f"S{index}")
        index_label.setFixedWidth(26)
        index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index_label.setStyleSheet(
            f"background:#0d1117; color:{MUTED}; border:1px solid {BORDER}; "
            "border-radius:9px; font-size:10px; font-weight:700; padding:1px 0;"
        )
        layout.addWidget(index_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self._title = QLabel(_normalize_text(label))
        self._title.setWordWrap(True)
        self._title.setStyleSheet(f"color:{TEXT}; font-size:11px; background:transparent;")
        text_layout.addWidget(self._title)

        self._note = QLabel(_normalize_text(note))
        self._note.setWordWrap(True)
        self._note.setStyleSheet(f"color:{MUTED}; font-size:10px; background:transparent;")
        self._note.setVisible(bool(note))
        text_layout.addWidget(self._note)
        layout.addLayout(text_layout, stretch=1)

        self._apply_style()

    @property
    def status_text(self) -> str:
        return self._status

    @property
    def label_text(self) -> str:
        return self._label_text

    def _apply_style(self) -> None:
        style = self.STYLES.get(self._status, self.STYLES["pending"])
        self.setStyleSheet(
            f"QFrame#ObjectivePlanRow {{ background:{style['bg']}; border:1px solid {style['border']}; "
            "border-radius:8px; }}"
        )
        self._tag.setText(style["tag"])
        self._tag.setStyleSheet(
            f"color:{style['fg']}; border:1px solid {style['border']}; border-radius:9px; "
            "font-size:10px; font-weight:700; padding:1px 6px;"
        )


class StepWidget(QFrame):
    """Widget representing one objective in the execution plan."""

    STATUS_STYLES = {
        "pending": {
            "badge": "P",
            "bg": _PENDING_BG,
            "fg": TEXT,
            "accent": BORDER,
            "badge_bg": "#0d1117",
        },
        "running": {
            "badge": "RUN",
            "bg": _RUNNING_BG,
            "fg": TEXT,
            "accent": _INFO,
            "badge_bg": "#10253b",
        },
        "completed": {
            "badge": "OK",
            "bg": _SUCCESS_BG,
            "fg": "#d7f7de",
            "accent": SUCCESS,
            "badge_bg": "#16351f",
        },
        "failed": {
            "badge": "X",
            "bg": _FAILED_BG,
            "fg": "#ffe0e0",
            "accent": DANGER,
            "badge_bg": "#3a1618",
        },
    }

    def __init__(self, step_number: int, description: str, parent=None) -> None:
        super().__init__(parent)
        self.step_number = step_number
        self.description = _normalize_text(description)
        self.status = "pending"
        self._expanded = False
        self._action_count = 0
        self._plan_count = 0
        self._plan_rows: list[_PlanRow] = []
        self._last_duration: float | None = None
        self._last_attempt_count = 1
        self._ok_count = 0
        self._fail_count = 0
        self._current_step = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("ObjectiveCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QWidget()
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(8)

        self._badge = QLabel()
        self._badge.setMinimumWidth(34)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self._badge)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self._title = QLabel(f"Objective {self.step_number}")
        self._title.setStyleSheet(
            f"color:{MUTED}; font-size:10px; font-weight:700; letter-spacing:0.4px; background:transparent;"
        )
        text_col.addWidget(self._title)

        self._text = QLabel(self.description)
        self._text.setWordWrap(True)
        text_col.addWidget(self._text)
        header_layout.addLayout(text_col, stretch=1)

        self._meta = QLabel("")
        self._meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._meta.setStyleSheet(f"color:{MUTED}; font-size:11px; background:transparent;")
        header_layout.addWidget(self._meta)

        self._toggle = QPushButton(">")
        self._toggle.setFixedSize(22, 22)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setStyleSheet(
            f"QPushButton {{ color:{MUTED}; background:transparent; border:none; font-size:11px; font-weight:700; }}"
            f"QPushButton:hover {{ color:{TEXT}; }}"
        )
        self._toggle.clicked.connect(self._on_toggle)
        self._toggle.hide()
        header_layout.addWidget(self._toggle)

        outer.addWidget(self._header)

        self._details = QWidget()
        details_layout = QVBoxLayout(self._details)
        details_layout.setContentsMargins(10, 0, 10, 10)
        details_layout.setSpacing(6)
        self._details.hide()
        outer.addWidget(self._details)

        self._plan_header = QLabel("Live backend steps")
        self._plan_header.setStyleSheet(
            f"color:{MUTED}; font-size:10px; font-weight:700; letter-spacing:0.4px; background:transparent;"
        )
        self._plan_header.hide()
        details_layout.addWidget(self._plan_header)

        self._plan_container = QWidget()
        self._plan_layout = QVBoxLayout(self._plan_container)
        self._plan_layout.setContentsMargins(0, 0, 0, 0)
        self._plan_layout.setSpacing(6)
        self._plan_container.hide()
        details_layout.addWidget(self._plan_container)

        self._action_header = QLabel("Execution trace")
        self._action_header.setStyleSheet(
            f"color:{MUTED}; font-size:10px; font-weight:700; letter-spacing:0.4px; background:transparent;"
        )
        self._action_header.hide()
        details_layout.addWidget(self._action_header)

        self._action_container = QWidget()
        self._action_layout = QVBoxLayout(self._action_container)
        self._action_layout.setContentsMargins(0, 0, 0, 0)
        self._action_layout.setSpacing(6)
        self._action_container.hide()
        details_layout.addWidget(self._action_container)

        self._update_appearance()
        self._refresh_meta()

    def set_status(self, status: str) -> None:
        self.status = status
        self._update_appearance()
        self._refresh_meta()

    def add_action(self, step_num: int, action_type: str, result: str) -> None:
        row = _ActionRow(step_num, action_type, result, self._action_container)
        self._action_layout.addWidget(row)
        self._action_count += 1
        self._current_step = step_num
        _fail_kw = ("error", "failed", "exception", "unexpected", "traceback", "timeout", "stuck")
        if any(kw in result.lower() for kw in _fail_kw):
            self._fail_count += 1
        else:
            self._ok_count += 1
        self._action_header.show()
        self._action_container.show()
        self._sync_detail_visibility(auto_expand=not self._plan_count)
        self._refresh_meta()

    def set_plan_state(self, plan_state: dict[str, Any]) -> None:
        for row in self._plan_rows:
            self._plan_layout.removeWidget(row)
            row.deleteLater()
        self._plan_rows.clear()
        self._plan_count = 0

        steps = plan_state.get("steps", []) if isinstance(plan_state, dict) else []
        if not isinstance(steps, list) or not steps:
            self._plan_header.hide()
            self._plan_container.hide()
            self._sync_detail_visibility()
            self._refresh_meta()
            return

        self._plan_header.show()
        self._plan_container.show()
        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                continue
            row = _PlanRow(
                index=index,
                label=_step_label(raw_step, index),
                status=_normalize_step_status(raw_step.get("status")),
                note=_step_note(raw_step),
                parent=self._plan_container,
            )
            self._plan_rows.append(row)
            self._plan_layout.addWidget(row)

        self._plan_count = len(self._plan_rows)
        if self._plan_count and self.status == "pending":
            self.set_status("running")
        self._sync_detail_visibility(auto_expand=True)
        self._refresh_meta()

    def set_timing(self, duration_s: float, attempt_count: int) -> None:
        self._last_duration = float(duration_s)
        self._last_attempt_count = int(attempt_count)
        self._refresh_meta()

    def _sync_detail_visibility(self, *, auto_expand: bool = False) -> None:
        has_details = bool(self._plan_count or self._action_count)
        self._toggle.setVisible(has_details)
        if auto_expand and has_details:
            self._expanded = True
        self._details.setVisible(has_details and self._expanded)
        self._toggle.setText("v" if self._expanded else ">")

    def _on_toggle(self) -> None:
        self._expanded = not self._expanded
        self._sync_detail_visibility()

    def _refresh_meta(self) -> None:
        parts: list[str] = []
        if self.status == "running" and self._current_step > 0:
            parts.append(f"Step {self._current_step} / 12")
        if self._ok_count or self._fail_count:
            tally = f"{self._ok_count}OK" if self._ok_count else ""
            if self._fail_count:
                tally += ("  " if tally else "") + f"{self._fail_count}X"
            parts.append(tally)
        if self._plan_count:
            noun = "live step" if self._plan_count == 1 else "live steps"
            parts.append(f"{self._plan_count} {noun}")
        if self._last_duration is not None:
            parts.append(f"{self._last_duration:.1f}s")
        if self._last_attempt_count > 1:
            noun = "attempt" if self._last_attempt_count == 1 else "attempts"
            parts.append(f"{self._last_attempt_count} {noun}")
        self._meta.setText("  |  ".join(parts))

    def _update_appearance(self) -> None:
        style = self.STATUS_STYLES.get(self.status, self.STATUS_STYLES["failed"])
        self.setStyleSheet(
            f"QFrame#ObjectiveCard {{ background:{style['bg']}; color:{style['fg']}; "
            f"border:1px solid {style['accent']}; border-left:4px solid {style['accent']}; border-radius:10px; }}"
        )
        self._badge.setText(style["badge"])
        self._badge.setStyleSheet(
            f"background:{style['badge_bg']}; color:{style['fg']}; border:1px solid {style['accent']}; "
            "border-radius:10px; font-size:10px; font-weight:700; padding:2px 6px;"
        )
        self._text.setStyleSheet(f"color:{style['fg']}; font-size:13px; background:transparent;")


class ExecutionPlanPanel(QWidget):
    """Display generated objectives and their execution progress."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.step_widgets: List[StepWidget] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"background-color:{APP_BG};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel("Execution Objectives")
        title.setStyleSheet(f"font-size:16px; font-weight:700; color:{TEXT};")
        header.addWidget(title)

        header.addStretch(1)

        self.summary_label = QLabel("Waiting for a plan")
        self.summary_label.setStyleSheet(f"color:{MUTED}; font-size:11px; background:transparent;")
        header.addWidget(self.summary_label)
        layout.addLayout(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ background-color:{APP_BG}; border:none; }}"
            f"QScrollBar:vertical {{ background:{SURFACE}; width:8px; }}"
            f"QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:4px; min-height:24px; }}"
        )

        self.steps_container = QWidget()
        self.steps_container.setStyleSheet(f"background-color:{APP_BG};")
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setSpacing(8)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.addStretch()
        self.scroll_area.setWidget(self.steps_container)
        layout.addWidget(self.scroll_area)

        self.empty_label = QLabel("No objectives yet. Submit a task to generate objectives.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color:{TEXT_WEAK}; font-style:italic; padding:24px 12px; "
            f"background-color:{SURFACE_ALT}; border:1px dashed {BORDER}; border-radius:10px;"
        )
        self.steps_layout.insertWidget(0, self.empty_label)

    @pyqtSlot(list)
    def display_plan(self, steps: List[str]) -> None:
        self.clear_plan()
        if not steps:
            self._refresh_summary()
            return

        self.empty_label.hide()
        for index, step in enumerate(steps, start=1):
            widget = StepWidget(index, step)
            self.step_widgets.append(widget)
            self.steps_layout.insertWidget(index - 1, widget)
        self._refresh_summary()

    @pyqtSlot(int, str)
    def update_step_status(self, step_number: int, status: str) -> None:
        if 0 < step_number <= len(self.step_widgets):
            self.step_widgets[step_number - 1].set_status(status)
            self._refresh_summary()

    @pyqtSlot(int, int, str, str)
    def add_step_detail(self, obj_idx: int, step_num: int, action_type: str, result: str) -> None:
        if 0 < obj_idx <= len(self.step_widgets):
            self.step_widgets[obj_idx - 1].add_action(step_num, action_type, result)

    @pyqtSlot(int, dict)
    def on_plan_state_updated(self, step_number: int, plan_state: dict) -> None:
        if 0 < step_number <= len(self.step_widgets):
            self.step_widgets[step_number - 1].set_plan_state(plan_state or {})
            self._refresh_summary()

    @pyqtSlot(int, dict)
    def on_step_completed(self, step_number: int, payload: dict) -> None:
        if 0 < step_number <= len(self.step_widgets):
            widget = self.step_widgets[step_number - 1]
            widget.set_status("completed")
            duration = payload.get("duration_s")
            attempts = payload.get("attempt_count", 1)
            if duration is not None:
                widget.set_timing(float(duration), int(attempts))
            self._refresh_summary()

    @pyqtSlot(int, object)
    def on_step_failed(self, step_number: int, payload: object) -> None:
        if 0 < step_number <= len(self.step_widgets):
            widget = self.step_widgets[step_number - 1]
            widget.set_status("failed")
            if isinstance(payload, dict):
                duration = payload.get("duration_s")
                attempts = payload.get("attempt_count", 1)
                if duration is not None:
                    widget.set_timing(float(duration), int(attempts))
            self._refresh_summary()

    def clear_plan(self) -> None:
        for widget in self.step_widgets:
            self.steps_layout.removeWidget(widget)
            widget.deleteLater()
        self.step_widgets.clear()
        self.empty_label.show()
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        if not self.step_widgets:
            self.summary_label.setText("Waiting for a plan")
            return

        total = len(self.step_widgets)
        running = sum(1 for widget in self.step_widgets if widget.status == "running")
        completed = sum(1 for widget in self.step_widgets if widget.status == "completed")
        failed = sum(1 for widget in self.step_widgets if widget.status == "failed")
        pending = total - running - completed - failed

        parts = [f"{total} objectives"]
        if running:
            parts.append(f"{running} running")
        if completed:
            parts.append(f"{completed} done")
        if failed:
            parts.append(f"{failed} failed")
        if pending:
            parts.append(f"{pending} pending")
        self.summary_label.setText("  |  ".join(parts))
