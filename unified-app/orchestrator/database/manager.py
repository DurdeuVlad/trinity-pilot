"""History CRUD operations backed by SQLite."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, desc, or_
from sqlalchemy.orm import Session, joinedload, sessionmaker

from .models import Base, ExecutionStep, TaskHistory, TaskStatus


_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "_runtime" / "orchestrator_history.db"
_ARCHIVE_VERSION = 1
_SOURCE_APP = "unified-app"


def _safe_json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _serialize_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _normalize_status(value: str | TaskStatus | None, fallback: TaskStatus = TaskStatus.PENDING) -> TaskStatus:
    if isinstance(value, TaskStatus):
        return value
    if isinstance(value, str):
        try:
            return TaskStatus(value.lower())
        except ValueError:
            return fallback
    return fallback


def canonical_task_status(task_payload: dict[str, Any] | None) -> str:
    """Return the workflow-facing status, preferring persisted result_data when present."""
    if not isinstance(task_payload, dict):
        return "unknown"
    result_data = task_payload.get("result_data")
    if isinstance(result_data, str):
        result_data = _safe_json_loads(result_data, {})
    if isinstance(result_data, dict):
        normalized = str(result_data.get("status", "") or "").strip().lower()
        if normalized:
            return normalized
    normalized = str(task_payload.get("status", "") or "").strip().lower()
    return normalized or "unknown"


class HistoryManager:
    """Store and retrieve task execution records."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._closed = False

    def close(self) -> None:
        """Dispose pooled DB resources."""
        if not self._closed:
            self.engine.dispose()
            self._closed = True

    def __enter__(self) -> "HistoryManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        try:
            self.close()
        except Exception:
            pass

    def get_session(self) -> Session:
        """Open a DB session."""
        return self.SessionLocal()

    def create_task(
        self,
        task_id: str,
        description: str,
        domain: str,
        plan_steps: Optional[list[str]] = None,
        estimated_duration: int | None = None,
        confidence: float | None = None,
    ) -> TaskHistory:
        with self.get_session() as session:
            task = TaskHistory(
                task_id=task_id,
                description=description,
                domain=domain,
                plan_steps=json.dumps(plan_steps or []),
                estimated_duration=estimated_duration,
                confidence=confidence,
                status=TaskStatus.PENDING,
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def start_task(self, task_id: str) -> None:
        with self.get_session() as session:
            task = session.query(TaskHistory).filter_by(task_id=task_id).first()
            if task:
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now(timezone.utc)
                session.commit()

    def update_task_plan(
        self,
        task_id: str,
        *,
        plan_steps: list[str],
        estimated_duration: int | None = None,
        confidence: float | None = None,
    ) -> None:
        """Update plan metadata after a task record already exists."""
        with self.get_session() as session:
            task = session.query(TaskHistory).filter_by(task_id=task_id).first()
            if task is None:
                return
            task.plan_steps = json.dumps(plan_steps or [])
            task.estimated_duration = estimated_duration
            task.confidence = confidence
            session.commit()

    def complete_task(
        self,
        task_id: str,
        result_data: dict | None = None,
        error_message: str | None = None,
        status: TaskStatus | None = None,
    ) -> None:
        with self.get_session() as session:
            task = session.query(TaskHistory).filter_by(task_id=task_id).first()
            if task:
                if status is not None:
                    task.status = status
                else:
                    task.status = TaskStatus.COMPLETED if not error_message else TaskStatus.FAILED
                task.completed_at = datetime.now(timezone.utc)
                task.result_data = json.dumps(result_data or {})
                task.error_message = error_message
                session.commit()

    def add_step(self, task_id: str, step_number: int, description: str) -> ExecutionStep:
        with self.get_session() as session:
            step = ExecutionStep(
                task_id=task_id,
                step_number=step_number,
                description=description,
                status=TaskStatus.PENDING,
            )
            session.add(step)
            session.commit()
            session.refresh(step)
            return step

    def update_step_status(
        self,
        task_id: str,
        step_number: int,
        status: TaskStatus,
        result_data: dict | None = None,
        error_message: str | None = None,
        flight_report_path: str | None = None,
    ) -> None:
        with self.get_session() as session:
            step = session.query(ExecutionStep).filter_by(task_id=task_id, step_number=step_number).first()
            if step is None:
                return
            step.status = status
            if status == TaskStatus.RUNNING:
                    step.started_at = datetime.now(timezone.utc)
            elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    step.completed_at = datetime.now(timezone.utc)
            step.result_data = json.dumps(result_data or {})
            step.error_message = error_message
            step.flight_report_path = flight_report_path
            session.commit()

    def get_task(self, task_id: str) -> TaskHistory | None:
        with self.get_session() as session:
            return session.query(TaskHistory).filter_by(task_id=task_id).first()

    def get_recent_tasks(self, limit: int = 50) -> list[TaskHistory]:
        with self.get_session() as session:
            return session.query(TaskHistory).order_by(desc(TaskHistory.created_at)).limit(limit).all()

    def get_tasks_by_status(self, status: TaskStatus, limit: int = 50) -> list[TaskHistory]:
        """Return tasks matching the given status, newest first."""
        with self.get_session() as session:
            return (
                session.query(TaskHistory)
                .filter(TaskHistory.status == status)
                .order_by(desc(TaskHistory.created_at))
                .limit(limit)
                .all()
            )

    def search_tasks(self, query: str, limit: int = 50) -> list[TaskHistory]:
        normalized_query = query.strip()
        if not normalized_query:
            return self.get_recent_tasks(limit)
        pattern = f"%{normalized_query}%"
        with self.get_session() as session:
            return (
                session.query(TaskHistory)
                .filter(or_(TaskHistory.description.ilike(pattern), TaskHistory.task_id.ilike(pattern)))
                .order_by(desc(TaskHistory.created_at))
                .limit(limit)
                .all()
            )

    def list_tasks(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        """List tasks with optional status filter, returning dict representations."""
        with self.get_session() as session:
            query = session.query(TaskHistory)
            if status:
                query = query.filter(TaskHistory.status == _normalize_status(status))
            tasks = query.order_by(desc(TaskHistory.created_at)).limit(limit).all()
            return [self._task_to_summary(task) for task in tasks]

    def get_task_steps(self, task_id: str) -> list[dict[str, Any]]:
        """Get all steps for a task, returning dict representations."""
        with self.get_session() as session:
            steps = session.query(ExecutionStep).filter_by(task_id=task_id).order_by(ExecutionStep.step_number).all()
            return [self._step_to_dict(step) for step in steps]

    def get_task_with_steps(self, task_id: str) -> dict[str, Any] | None:
        """Return one task with its ordered execution steps."""
        with self.get_session() as session:
            task = (
                session.query(TaskHistory)
                .options(joinedload(TaskHistory.steps))
                .filter(TaskHistory.task_id == task_id)
                .first()
            )
            if task is None:
                return None
            return self._task_to_detail(task)

    def export_archive(
        self,
        task_ids: list[str] | None = None,
        status: str | TaskStatus | None = None,
        query: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return a versioned JSON-serializable archive of one or more tasks."""
        with self.get_session() as session:
            task_query = session.query(TaskHistory).options(joinedload(TaskHistory.steps))
            if task_ids:
                tasks = task_query.filter(TaskHistory.task_id.in_(task_ids)).all()
                order = {task_id: index for index, task_id in enumerate(task_ids)}
                tasks.sort(key=lambda item: order.get(item.task_id, len(order)))
            else:
                if status is not None:
                    task_query = task_query.filter(TaskHistory.status == _normalize_status(status))
                normalized_query = (query or "").strip()
                if normalized_query:
                    pattern = f"%{normalized_query}%"
                    task_query = task_query.filter(
                        or_(TaskHistory.description.ilike(pattern), TaskHistory.task_id.ilike(pattern))
                    )
                tasks = task_query.order_by(desc(TaskHistory.created_at)).limit(limit).all()

        return {
            "version": _ARCHIVE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_app": _SOURCE_APP,
            "tasks": [self._task_to_detail(task) for task in tasks],
        }

    def import_archive(self, payload: dict[str, Any] | str) -> dict[str, Any]:
        """Import a versioned JSON archive into the local history store."""
        if isinstance(payload, str):
            payload = json.loads(payload)
        if payload.get("version") != _ARCHIVE_VERSION:
            raise ValueError(f"Unsupported archive version: {payload.get('version')!r}")
        tasks = payload.get("tasks")
        if not isinstance(tasks, list):
            raise ValueError("Archive payload must contain a tasks list.")

        imported_task_ids: list[str] = []
        collisions: list[dict[str, str]] = []

        with self.get_session() as session:
            for task_payload in tasks:
                if not isinstance(task_payload, dict):
                    raise ValueError("Each archive task entry must be an object.")
                original_task_id = str(task_payload.get("task_id") or "").strip()
                if not original_task_id:
                    raise ValueError("Archive task is missing task_id.")
                task_id = self._ensure_unique_task_id(session, original_task_id)
                if task_id != original_task_id:
                    collisions.append({"original_task_id": original_task_id, "imported_task_id": task_id})

                task = TaskHistory(
                    task_id=task_id,
                    description=str(task_payload.get("description") or "").strip() or "Imported task",
                    domain=str(task_payload.get("domain") or "cli").strip() or "cli",
                    status=_normalize_status(task_payload.get("status")),
                created_at=_parse_timestamp(task_payload.get("created_at")) or datetime.now(timezone.utc),
                    started_at=_parse_timestamp(task_payload.get("started_at")),
                    completed_at=_parse_timestamp(task_payload.get("completed_at")),
                    plan_steps=json.dumps(task_payload.get("plan_steps") or []),
                    estimated_duration=task_payload.get("estimated_duration"),
                    confidence=task_payload.get("confidence"),
                    result_data=json.dumps(task_payload.get("result_data") or {}),
                    error_message=task_payload.get("error_message"),
                )
                session.add(task)

                raw_steps = task_payload.get("steps") or []
                if not isinstance(raw_steps, list):
                    raise ValueError(f"Archive task {original_task_id} has invalid steps payload.")
                for step_index, step_payload in enumerate(raw_steps, start=1):
                    if not isinstance(step_payload, dict):
                        raise ValueError(f"Archive step {step_index} for {original_task_id} is invalid.")
                    step = ExecutionStep(
                        task_id=task_id,
                        step_number=int(step_payload.get("step_number") or step_index),
                        description=str(step_payload.get("description") or f"Step {step_index}"),
                        status=_normalize_status(step_payload.get("status")),
                        started_at=_parse_timestamp(step_payload.get("started_at")),
                        completed_at=_parse_timestamp(step_payload.get("completed_at")),
                        result_data=json.dumps(step_payload.get("result_data") or {}),
                        error_message=step_payload.get("error_message"),
                        flight_report_path=step_payload.get("flight_report_path"),
                    )
                    session.add(step)

                imported_task_ids.append(task_id)

            session.commit()

        return {
            "version": _ARCHIVE_VERSION,
            "source_app": payload.get("source_app") or _SOURCE_APP,
            "imported_count": len(imported_task_ids),
            "task_ids": imported_task_ids,
            "collisions": collisions,
        }

    def delete_task(self, task_id: str) -> None:
        with self.get_session() as session:
            task = session.query(TaskHistory).filter_by(task_id=task_id).first()
            if task:
                session.delete(task)
                session.commit()

    def _ensure_unique_task_id(self, session: Session, task_id: str) -> str:
        candidate = task_id
        suffix = 1
        while session.query(TaskHistory).filter(TaskHistory.task_id == candidate).first() is not None:
            candidate = f"{task_id}-imported-{suffix}"
            suffix += 1
        return candidate

    def _task_to_summary(self, task: TaskHistory) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "description": task.description,
            "domain": task.domain,
            "status": task.status.value if task.status else "unknown",
            "created_at": _serialize_timestamp(task.created_at),
            "started_at": _serialize_timestamp(task.started_at),
            "completed_at": _serialize_timestamp(task.completed_at),
            "confidence": task.confidence,
            "estimated_duration": task.estimated_duration,
        }

    def _task_to_detail(self, task: TaskHistory) -> dict[str, Any]:
        ordered_steps = sorted(task.steps, key=lambda item: item.step_number)
        return {
            **self._task_to_summary(task),
            "plan_steps": _safe_json_loads(task.plan_steps, []),
            "result_data": _safe_json_loads(task.result_data, {}),
            "error_message": task.error_message,
            "steps": [self._step_to_dict(step) for step in ordered_steps],
        }

    def _step_to_dict(self, step: ExecutionStep) -> dict[str, Any]:
        return {
            "step_number": step.step_number,
            "description": step.description,
            "status": step.status.value if step.status else "unknown",
            "started_at": _serialize_timestamp(step.started_at),
            "completed_at": _serialize_timestamp(step.completed_at),
            "result_data": _safe_json_loads(step.result_data, {}),
            "error_message": step.error_message,
            "flight_report_path": step.flight_report_path,
        }
