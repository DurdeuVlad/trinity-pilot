from __future__ import annotations

from enum import Enum, auto
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from trinity_pilot.ui import bubble_renderer as br
from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget
from trinity_pilot.ui.thinking_indicator import ThinkingIndicator


class ChatState(Enum):
    IDLE = auto()
    PLANNING = auto()
    AWAITING_CONFIRM = auto()
    EXECUTING = auto()
    DONE = auto()
    ERROR = auto()


class _MessageThoughtWidget(QWidget):
    """A collapsible 'Thoughts' panel attached to a single AI message."""

    def __init__(self, debug_mode: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._debug_mode = debug_mode
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 4)
        layout.setSpacing(2)

        self._toggle = QToolButton()
        self._toggle.setText("\U0001f9e0 Thoughts \u25b8")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(debug_mode)
        self._toggle.setStyleSheet(
            "QToolButton{border:none;color:#FF6347;font-size:11px;font-style:italic;}"
            "QToolButton:hover{color:#E5533D;}"
        )
        self._toggle.toggled.connect(self._on_toggle)
        layout.addWidget(self._toggle)

        self._thought_view = QTextEdit()
        self._thought_view.setReadOnly(True)
        self._thought_view.setFixedHeight(80)
        self._thought_view.setStyleSheet(
            "QTextEdit{background:#FAFAFA;border:1px solid #E0E0E0;"
            "border-radius:4px;font-size:11px;color:#555;padding:4px;}"
        )
        self._thought_view.setVisible(debug_mode)
        layout.addWidget(self._thought_view)

        self._debug_view: QTextEdit | None = None
        if debug_mode:
            self._debug_view = QTextEdit()
            self._debug_view.setReadOnly(True)
            self._debug_view.setFixedHeight(70)
            self._debug_view.setStyleSheet(
                "QTextEdit{background:#212121;color:#80CBC4;"
                "font-family:monospace;font-size:10px;padding:4px;"
                "border-radius:4px;}"
            )
            layout.addWidget(self._debug_view)

    def append_thought_chunk(self, chunk: str) -> None:
        cursor = self._thought_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self._thought_view.setTextCursor(cursor)
        self._thought_view.ensureCursorVisible()

    def set_thought_text(self, text: str) -> None:
        self._thought_view.setPlainText(text)

    def set_debug_json(self, text: str) -> None:
        if self._debug_view:
            self._debug_view.setPlainText(text)

    def _on_toggle(self, checked: bool) -> None:
        arrow = "\u25be" if checked else "\u25b8"
        self._toggle.setText(f"\U0001f9e0 Thoughts {arrow}")
        self._thought_view.setVisible(checked)
        if self._debug_view:
            self._debug_view.setVisible(checked)


class ChatWidget(QWidget):
    """Polished chat interface replacing the raw QTextEdit log view."""

    def __init__(
        self,
        debug_mode: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._debug_mode = debug_mode
        self._state = ChatState.IDLE
        self._pending_specs: list[dict] = []
        self._task_id: str | None = None
        self._start_time: float = 0.0
        self._bridge: Any = None
        self._stream_worker: Any = None
        self._current_thought_widget: _MessageThoughtWidget | None = None

        self._build_ui()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._on_poll)

    def set_bridge(self, bridge: Any) -> None:
        self._bridge = bridge

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Scrollable message area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea{border:none;background:#FAFAFA;}"
        )

        self._msg_container = QWidget()
        self._msg_container.setStyleSheet("background:#FAFAFA;")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(4, 8, 4, 8)
        self._msg_layout.setSpacing(2)
        self._msg_layout.addStretch()

        self._scroll.setWidget(self._msg_container)
        root_layout.addWidget(self._scroll, stretch=1)

        # Thinking indicator (sits outside scroll, always visible when active)
        self._thinking = ThinkingIndicator(self)
        root_layout.addWidget(self._thinking)

        # Objective chips (sits outside scroll)
        self._chips = ObjectiveChipsWidget(self)
        root_layout.addWidget(self._chips)

    # ------------------------------------------------------------------
    # Public message API
    # ------------------------------------------------------------------

    def add_user_message(self, text: str) -> None:
        self._append_html(br.user_bubble(text))

    def add_ai_message(
        self,
        text: str,
        thought_prompt: str = "",
        debug_json: str = "",
    ) -> None:
        self._append_html(br.ai_bubble(text))
        thought_widget = _MessageThoughtWidget(
            debug_mode=self._debug_mode, parent=self._msg_container
        )
        if thought_prompt:
            thought_widget.set_thought_text(thought_prompt)
        if debug_json and self._debug_mode:
            thought_widget.set_debug_json(debug_json)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, thought_widget)
        self._current_thought_widget = thought_widget
        self._scroll_to_bottom()

    def add_system_note(self, text: str) -> None:
        self._append_html(br.system_note(text))

    def show_objectives_card(self, specs: list[dict]) -> None:
        self._append_html(br.objectives_card(specs))
        self._append_html(br.confirmation_prompt())
        self._scroll_to_bottom()

    def show_progress_chips(self, specs: list[dict]) -> None:
        self._chips.set_objectives(specs)

    def show_completion(
        self, status: str, results: dict
    ) -> None:
        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
        self._append_html(br.summary_bubble(elapsed, status, results))
        self._chips.reset()
        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # Streaming thought support
    # ------------------------------------------------------------------

    def on_stream_chunk(self, chunk: str) -> None:
        if self._current_thought_widget:
            self._current_thought_widget.append_thought_chunk(chunk)

    def on_stream_done(self, full_text: str) -> None:
        pass  # already accumulated via chunks

    def on_stream_error(self, error: str) -> None:
        if self._current_thought_widget and self._debug_mode:
            self._current_thought_widget.set_thought_text(
                f"[stream error: {error}]"
            )

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def get_state(self) -> ChatState:
        return self._state

    def set_state(self, state: ChatState) -> None:
        self._state = state
        if state == ChatState.EXECUTING:
            self._poll_timer.start()
        else:
            self._poll_timer.stop()

    def start_task(
        self,
        task_id: str,
        specs: list[dict],
        start_time: float,
    ) -> None:
        self._task_id = task_id
        self._start_time = start_time
        self._pending_specs = specs
        self._chips.set_objectives(specs)
        self.set_state(ChatState.EXECUTING)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _on_poll(self) -> None:
        if not self._bridge:
            return
        progress = self._bridge.query_progress()
        if not progress:
            return
        current = progress.get("current_objective", "")
        completed = set(progress.get("completed_objectives", []))
        for spec in self._pending_specs:
            obj_id = spec.get("objective_id", "")
            if obj_id in completed:
                self._chips.mark_passed(obj_id)
            elif obj_id == current:
                self._chips.mark_running(obj_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _append_html(self, html: str) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        lbl = QLabel()
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(html)
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, lbl)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        def _do_scroll() -> None:
            try:
                import shiboken6
                if not shiboken6.isValid(self._scroll):
                    return
            except ImportError:
                pass
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        QTimer.singleShot(50, _do_scroll)

    @property
    def thinking(self) -> ThinkingIndicator:
        return self._thinking

    @property
    def chips(self) -> ObjectiveChipsWidget:
        return self._chips
