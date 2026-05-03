"""Simple orchestrator: plan generation + task execution."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import uuid
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from event_bus import get_event_bus
from settings import get_settings

logger = logging.getLogger(__name__)

_PLAN_PROMPT = """\
You are a desktop automation planner.
Break this task into 2-5 sub-objectives — concrete goals the executor must achieve.
Sub-objectives are targets, not a fixed sequence. The executor will orient itself
and pursue them adaptively based on what it finds in the environment.
Return ONLY a JSON array of strings — no extra text, no markdown.
Example: ["Open Notepad", "Type Hello World", "Save the file as test.txt"]

Task: {task}"""


def _resolve_api_key(provider_name: str) -> str:
    settings = get_settings()
    if provider_name == "openai":
        return os.getenv("OPENAI_API_KEY") or str(settings.get("openai_api_key", ""))
    return os.getenv("GEMINI_API_KEY") or str(settings.get("gemini_api_key", ""))


def _parse_objectives(text: str, fallback: str) -> list[str]:
    try:
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if isinstance(data, list):
                result = [str(s).strip() for s in data if str(s).strip()]
                if result:
                    return result[:5]
    except Exception:
        pass
    return [fallback]



class _PlanWorker(QObject):
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, task: str) -> None:
        super().__init__()
        self.task = task

    def run(self) -> None:
        try:
            objectives = asyncio.run(self._generate())
            self.finished.emit(objectives)
        except Exception as exc:
            logger.warning("Plan generation failed: %s", exc)
            try:
                from crash_reporter import write_crash_dump
                write_crash_dump(exc, run_id="plan", phase="plan_worker", task=self.task)
            except Exception:
                pass
            self.failed.emit(str(exc))

    async def _generate(self) -> list[str]:
        from orchestrator.providers.factory import make_provider

        settings = get_settings()
        provider_name = str(settings.get("ai_provider", "gemini")).lower()
        api_key = _resolve_api_key(provider_name)
        provider = make_provider(provider_name, api_key)
        try:
            prompt = _PLAN_PROMPT.format(task=self.task)
            text = await asyncio.wait_for(
                provider.call([{"role": "user", "content": prompt}], json_mode=True),
                timeout=30.0,
            )
            return _parse_objectives(text, self.task)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                await close()


class _ExecWorker(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, task: str, objectives: list[str], domain: str) -> None:
        super().__init__()
        self.task = task
        self.objectives = objectives
        self.domain = domain
        self._cancel_event = threading.Event()
        self.run_id = f"run_{uuid.uuid4().hex[:12]}"

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            asyncio.run(self._execute())
        except Exception as exc:
            logger.exception("Execution worker error: %s", exc)
            try:
                from crash_reporter import write_crash_dump
                write_crash_dump(exc, run_id=self.run_id, phase="exec_worker", task=self.task)
            except Exception:
                pass
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    async def _execute(self) -> None:
        from orchestrator.trinity_bridge import TrinityBridge

        bus = get_event_bus()
        bus.status_message.emit("Initializing backend…", "info")

        bridge = TrinityBridge(use_subprocess=False)
        try:
            await bridge.initialize()
            target_server = bridge.suggest_server_for_objective(self.task)

            bus.execution_started.emit()
            for i, obj in enumerate(self.objectives, start=1):
                bus.step_started.emit(i, obj)
                bus.status_message.emit(f"Sub-objective {i}/{len(self.objectives)}: {obj}", "step")

            if self._cancel_event.is_set():
                bus.task_cancelled.emit()
                return

            bus.status_message.emit("Running… (this may take up to 2 minutes)", "info")
            result = await bridge.execute_task(
                task_id=self.run_id,
                description=self.task,
                domain=self.domain,
                target_server=target_server,
                sub_objectives=self.objectives,
                cancel_event=self._cancel_event,
            )

            payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
            success = payload.get("status") == "success"
            meta = payload.get("metadata") or {}
            if not isinstance(meta, dict):
                meta = {}
            output = str(
                meta.get("output") or payload.get("error") or payload.get("status") or ""
            )

            for i in range(1, len(self.objectives) + 1):
                bus.step_done.emit(i, success, output)

            level = "success" if success else "error"
            bus.status_message.emit(output or ("Done." if success else "Execution failed."), level)
            bus.execution_done.emit(success, output)

            if self._cancel_event.is_set():
                bus.task_cancelled.emit()

        except Exception as exc:
            msg = str(exc)
            bus.status_message.emit(f"Execution error: {msg}", "error")
            bus.execution_done.emit(False, msg)
            raise
        finally:
            await bridge.shutdown()


class OrchestratorCore(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._busy = False
        self._plan_thread: Optional[QThread] = None
        self._plan_worker: Optional[_PlanWorker] = None
        self._exec_thread: Optional[QThread] = None
        self._exec_worker: Optional[_ExecWorker] = None
        self._current_task: str = ""

    def is_busy(self) -> bool:
        return self._busy

    def start_planning(self, task: str) -> None:
        if self._busy:
            get_event_bus().status_message.emit("Already running — cancel first.", "warning")
            return
        task = task.strip()
        if not task:
            return
        self._current_task = task
        bus = get_event_bus()
        bus.busy_changed.emit(True)
        bus.chat_reply.emit("Generating execution plan…")

        worker = _PlanWorker(task)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_plan_ready)
        worker.failed.connect(self._on_plan_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._plan_thread = thread
        self._plan_worker = worker
        thread.start()

    def start_execution(self, task: str, objectives: list[str]) -> None:
        if self._busy:
            return
        self._busy = True
        self._current_task = task

        from orchestrator.trinity_bridge import TrinityBridge
        domain = TrinityBridge().suggest_domain(task)

        bus = get_event_bus()
        bus.busy_changed.emit(True)

        worker = _ExecWorker(task, objectives, domain)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_exec_finished)
        worker.error.connect(self._on_exec_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._exec_thread = thread
        self._exec_worker = worker
        thread.start()

    def cancel(self) -> None:
        if self._exec_worker is not None:
            self._exec_worker.cancel()
            get_event_bus().status_message.emit("Cancelling…", "warning")

    def shutdown(self) -> bool:
        self.cancel()
        if self._exec_thread and self._exec_thread.isRunning():
            self._exec_thread.quit()
            if not self._exec_thread.wait(3000):
                return False
        return True

    def _on_plan_ready(self, objectives: list[str]) -> None:
        get_event_bus().plan_ready.emit(objectives)
        get_event_bus().busy_changed.emit(False)

    def _on_plan_failed(self, error: str) -> None:
        get_event_bus().plan_failed.emit(error)
        get_event_bus().chat_reply.emit(
            f"Could not generate a plan: {error}. Try rephrasing your task."
        )
        get_event_bus().busy_changed.emit(False)

    def _on_exec_finished(self) -> None:
        self._busy = False
        self._exec_thread = None
        self._exec_worker = None
        get_event_bus().busy_changed.emit(False)

    def _on_exec_error(self, error: str) -> None:
        get_event_bus().status_message.emit(f"Worker error: {error}", "error")
