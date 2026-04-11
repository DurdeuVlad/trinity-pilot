"""Live run event capture and artifact bundle helpers."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.database import HistoryManager, canonical_task_status


class RunEventRecorder:
    """Capture live event-bus activity and expose cursor-based reads."""

    def __init__(self, history_manager: HistoryManager, runtime_dir: Path) -> None:
        self.history_manager = history_manager
        self.runtime_dir = runtime_dir
        self._lock = threading.Lock()
        self._events_by_task: dict[str, list[dict[str, Any]]] = {}
        self._next_seq_by_task: dict[str, int] = {}
        self._current_task_id: str | None = None
        self._drift_state_by_task: dict[str, str] = {}
        self._drift_failure_count_by_task: dict[str, int] = {}

    def attach(self, event_bus: Any) -> None:
        """Bind to the shared event bus."""
        event_bus.run_started.connect(self._bind_task)
        event_bus.run_ended.connect(self._unbind_task)
        event_bus.status_update.connect(
            lambda message, level: self.record_event("status_update", {"message": message, "level": level})
        )
        event_bus.plan_generated.connect(lambda steps: self.record_event("plan_generated", {"steps": list(steps)}))
        event_bus.step_started.connect(
            lambda idx, description: self.record_event(
                "step_started",
                {"step_index": idx, "description": description},
            )
        )
        event_bus.step_completed.connect(
            lambda idx, payload: self.record_event("step_completed", {"step_index": idx, "payload": payload})
        )
        event_bus.step_failed.connect(
            lambda idx, payload: self._record_step_failure(idx, payload)
        )
        event_bus.blocker_detected.connect(
            lambda message: self._record_blocker(message)
        )
        event_bus.cli_step_progress.connect(
            lambda obj_idx, step: self.record_event(
                "cli_step_progress",
                {"objective_index": obj_idx, "step": step},
            )
        )
        event_bus.execution_complete.connect(
            lambda payload: self._record_execution_complete(payload)
        )

    def record_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        task_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        """Append a live event to the active task."""
        resolved_task_id = task_id or self._current_task_id or self._guess_running_task_id()
        if not resolved_task_id:
            return None
        with self._lock:
            seq = self._next_seq_by_task.get(resolved_task_id, 1)
            event = {
                "sequence": seq,
                "task_id": resolved_task_id,
                "event_type": event_type,
                "status": status,
                "timestamp": time.time(),
                "payload": payload,
            }
            self._events_by_task.setdefault(resolved_task_id, []).append(event)
            self._next_seq_by_task[resolved_task_id] = seq + 1
        if event_type == "policy_stop":
            self._set_drift_state(resolved_task_id, "policy_stop", reason=payload.get("reason", "policy_stop"))
        elif event_type == "intervention_approved":
            self._set_drift_state(resolved_task_id, "bounded_drift", reason="intervention_approved")
        return event

    def get_events(self, task_id: str, after_sequence: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        """Return cursor-based live events for one task."""
        with self._lock:
            events = self._events_by_task.get(task_id, [])
            return [event for event in events if event["sequence"] > after_sequence][:limit]

    def latest_task_id(self) -> str | None:
        """Return the latest known task id."""
        if self._current_task_id:
            return self._current_task_id
        recent = self.history_manager.list_tasks(limit=1)
        if recent:
            return recent[0].get("task_id")
        return None

    def register_terminal_session_reference(self, task_id: str, session_reference: dict[str, Any]) -> None:
        """Attach a terminal session reference to a task via the live event stream."""
        self.record_event("terminal_session_reference", session_reference, task_id=task_id, status="running")

    def build_artifact_bundle(self, task_id: str) -> dict[str, Any]:
        """Return a normalized artifact bundle for one run."""
        details = self.history_manager.get_task_with_steps(task_id)
        if details is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        steps = list(details.get("steps", []))
        task = dict(details.get("task", {})) if "task" in details else {
            key: value for key, value in details.items() if key != "steps"
        }
        task.setdefault("task_id", task_id)

        flight_reports: list[str] = []
        prompt_paths: list[str] = []
        response_paths: list[str] = []
        screenshot_paths: list[str] = []

        for step in steps:
            report_path = step.get("flight_report_path")
            if report_path:
                flight_reports.append(report_path)
                artifact_info = self._extract_report_artifacts(report_path)
                prompt_paths.extend(artifact_info["prompt_paths"])
                response_paths.extend(artifact_info["response_paths"])
                screenshot_paths.extend(artifact_info["screenshot_paths"])

        result_data = task.get("result_data") or {}
        if isinstance(result_data, str):
            try:
                result_data = json.loads(result_data)
            except Exception:
                result_data = {}

        live_events = self.get_events(task_id, after_sequence=0, limit=10000)
        drift_history = [event for event in live_events if event["event_type"] == "drift_state_changed"]

        return {
            "task": task,
            "steps": steps,
            "execution_log": steps,
            "live_events": live_events,
            "checkpoints": self._list_checkpoints(task_id),
            "flight_report_paths": self._dedupe(flight_reports),
            "prompt_paths": self._dedupe(prompt_paths),
            "response_paths": self._dedupe(response_paths),
            "screenshot_paths": self._dedupe(screenshot_paths),
            "terminal_session_references": self._terminal_session_references(task_id, task),
            "intervention_history": [
                event
                for event in live_events
                if event["event_type"] in {"blocker", "policy_stop", "intervention_approved", "drift_state_changed"}
            ],
            "drift_history": drift_history,
            "final_disposition": {
                "task_status": canonical_task_status(task),
                "persisted_task_status": task.get("status") or "unknown",
                "final_status": result_data.get("status") or result_data.get("category") or canonical_task_status(task),
                "error_message": task.get("error_message"),
                "drift_state": self._drift_state_by_task.get(task_id, "healthy"),
            },
        }

    def _bind_task(self, task_id: str) -> None:
        if not task_id:
            return
        self._current_task_id = task_id
        self._drift_failure_count_by_task[task_id] = 0
        self.record_event("run_started", {"message": "Run started"}, task_id=task_id, status="running")
        self._set_drift_state(task_id, "healthy", reason="run_started")

    def _unbind_task(self, task_id: str) -> None:
        task_id = task_id or self._current_task_id or self._guess_running_task_id()
        if task_id:
            self.record_event("run_ended", {"message": "Run ended"}, task_id=task_id)
        self._current_task_id = None

    def _record_step_failure(self, step_index: int, payload: Any) -> None:
        event = self.record_event("step_failed", {"step_index": step_index, "payload": str(payload)})
        if not event:
            return
        task_id = event["task_id"]
        failure_count = self._drift_failure_count_by_task.get(task_id, 0) + 1
        self._drift_failure_count_by_task[task_id] = failure_count
        if failure_count == 1:
            self._set_drift_state(task_id, "suspected_drift", reason="step_failed")
        else:
            self._set_drift_state(task_id, "bounded_drift", reason="repeated_step_failure")

    def _record_blocker(self, message: str) -> None:
        event = self.record_event("blocker", {"message": message}, status="approval_required")
        if not event:
            return
        self._set_drift_state(event["task_id"], "approval_required", reason="blocker_detected")

    def _record_execution_complete(self, payload: dict[str, Any]) -> None:
        normalized = payload if isinstance(payload, dict) else {}
        status = str(normalized.get("status") or "completed")
        event = self.record_event("execution_complete", {"payload": normalized}, status=status)
        if not event:
            return
        task_id = event["task_id"]
        lowered = status.lower()
        if lowered in {"failed", "failure", "cancelled"}:
            self._set_drift_state(task_id, "terminal_failure", reason=status)
        elif lowered == "policy_terminated":
            self._set_drift_state(task_id, "policy_stop", reason=status)
        else:
            self._set_drift_state(task_id, "healthy", reason=status)

    def _set_drift_state(self, task_id: str, state: str, *, reason: str) -> None:
        previous = self._drift_state_by_task.get(task_id)
        if previous == state:
            return
        self._drift_state_by_task[task_id] = state
        self.record_event(
            "drift_state_changed",
            {"previous_state": previous, "state": state, "reason": reason},
            task_id=task_id,
            status=state,
        )

    def _guess_running_task_id(self) -> str | None:
        running = self.history_manager.list_tasks(limit=1, status="running")
        if running:
            return running[0].get("task_id")
        recent = self.history_manager.list_tasks(limit=1)
        if recent:
            return recent[0].get("task_id")
        return None

    def _terminal_session_references(self, task_id: str, task: dict[str, Any]) -> list[dict[str, Any]]:
        references = [
            event["payload"]
            for event in self.get_events(task_id, after_sequence=0, limit=10000)
            if event["event_type"] == "terminal_session_reference"
        ]
        if references:
            return references

        session_dir = self.runtime_dir / "terminal_sessions"
        if not session_dir.exists():
            return []

        started_at = self._as_timestamp(task.get("started_at") or task.get("created_at"))
        completed_at = self._as_timestamp(task.get("completed_at")) or time.time()
        inferred: list[dict[str, Any]] = []
        for path in sorted(session_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            session_created = self._as_timestamp(payload.get("created_at"))
            session_updated = self._as_timestamp(payload.get("updated_at")) or session_created
            purpose = str(payload.get("purpose") or "")
            if task_id in purpose or self._timestamps_overlap(started_at, completed_at, session_created, session_updated):
                inferred.append(
                    {
                        "session_id": payload.get("id"),
                        "purpose": payload.get("purpose"),
                        "cwd": payload.get("cwd"),
                        "status": payload.get("status"),
                        "metadata_path": str(path),
                    }
                )
        return inferred

    def _list_checkpoints(self, task_id: str) -> list[str]:
        checkpoint_dir = self.runtime_dir / "checkpoints"
        if not checkpoint_dir.exists():
            return []
        return sorted(str(path) for path in checkpoint_dir.glob(f"{task_id}_*.json"))

    def _extract_report_artifacts(self, flight_report_path: str) -> dict[str, Any]:
        report = Path(flight_report_path)
        json_path = report if report.suffix == ".json" else report.with_suffix(".json")
        prompts: list[str] = []
        responses: list[str] = []
        screenshots: list[str] = []
        if json_path.exists():
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            for artifact in payload.get("artifacts", []):
                artifact_path = str(artifact.get("path", ""))
                artifact_type = str(artifact.get("type", ""))
                resolved = str((json_path.parent / artifact_path).resolve()) if artifact_path else ""
                if artifact_type == "ai_reasoning_prompt" and resolved:
                    prompts.append(resolved)
                elif artifact_type == "ai_reasoning_response" and resolved:
                    responses.append(resolved)
                elif artifact_type == "screenshot" and resolved:
                    screenshots.append(resolved)
        return {
            "prompt_paths": prompts,
            "response_paths": responses,
            "screenshot_paths": screenshots,
        }

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            if item and item not in seen:
                deduped.append(item)
                seen.add(item)
        return deduped

    @staticmethod
    def _as_timestamp(value: Any) -> float | None:
        if value in {None, ""}:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            pass
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return None

    @staticmethod
    def _timestamps_overlap(
        task_started_at: float | None,
        task_completed_at: float | None,
        session_created_at: float | None,
        session_updated_at: float | None,
    ) -> bool:
        if task_started_at is None or session_created_at is None:
            return False
        task_end = task_completed_at or time.time()
        session_end = session_updated_at or session_created_at
        return session_created_at <= task_end and session_end >= task_started_at
