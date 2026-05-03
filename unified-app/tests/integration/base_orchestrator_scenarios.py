"""
Shared recording helpers and base class for UnifiedAppObjectiveRunner handoff scenarios.

Naming convention: BaseHandoffScenario (no "Test" prefix) → pytest skips
collection and does not try to instantiate it as a test class.
"""
from __future__ import annotations

import time
from typing import Any

import orchestrator.orchestrator_core as core_module
import pytest
from orchestrator.database import TaskStatus
from orchestrator.event_bus import EventBus
from orchestrator.orchestrator_core import UnifiedAppObjectiveRunner


# ---------------------------------------------------------------------------
# Contract mixin — graduated severity helper
# ---------------------------------------------------------------------------

class ContractMixin:
    """
    Graduated-severity contract helper. Inherited by both base scenario classes.

    Severity zones:
      value <= soft              → pass
      soft < value <= hard       → pytest.xfail (non-blocking, CI-visible)
      value > hard               → pytest.fail  (blocking)

    hard=None means hard = soft * 2 (standard two-zone model).
    """

    @staticmethod
    def _assert_contract(
        value: float | int,
        soft: float | int,
        hard: float | int | None,
        label: str,
    ) -> None:
        effective_hard = hard if hard is not None else soft * 2

        if value <= soft:
            return

        msg = f"{label}={value} exceeds soft limit {soft}"
        if value <= effective_hard:
            pytest.xfail(f"NON-BLOCKING — {msg} (hard limit {effective_hard} not yet breached)")
        else:
            pytest.fail(f"BLOCKING — {label}={value} exceeds hard limit {effective_hard}")


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------

class RecordingHistoryManager:
    """Drop-in replacement for HistoryManager that records all calls."""

    def __init__(self) -> None:
        self.completed_calls: list[dict[str, Any]] = []
        self.step_updates: list[dict[str, Any]] = []
        self.call_log: list[str] = []           # ordered method names
        self.created_task_id: str | None = None # task_id from create_task()

    def create_task(self, task_id: Any, *args: Any, **kwargs: Any) -> None:
        self.call_log.append("create_task")
        self.created_task_id = task_id

    def start_task(self, *args: Any, **kwargs: Any) -> None:
        self.call_log.append("start_task")

    def add_sub_objective(self, *args: Any, **kwargs: Any) -> None:
        self.call_log.append("add_sub_objective")

    def update_step_status(
        self,
        task_id: Any,
        step_number: Any,
        status: Any,
        result_data: Any = None,
        error_message: Any = None,
        flight_report_path: Any = None,
    ) -> None:
        self.call_log.append("update_step_status")
        self.step_updates.append(
            {
                "task_id": task_id,
                "step_number": step_number,
                "status": status,
                "result_data": result_data,
                "error_message": error_message,
                "flight_report_path": flight_report_path,
            }
        )

    def complete_task(
        self,
        task_id: Any,
        result_data: Any = None,
        error_message: Any = None,
        status: Any = None,
    ) -> None:
        self.call_log.append("complete_task")
        self.completed_calls.append(
            {
                "task_id": task_id,
                "result_data": result_data,
                "error_message": error_message,
                "status": status,
            }
        )


class _Result:
    """Minimal result object satisfying the model_dump() contract."""

    def __init__(
        self,
        *,
        status: str = "success",
        category: str = "success",
        output: str = "done",
    ) -> None:
        self.status = status
        self.category = category
        self.metadata = {"output": output}
        self.error = None if status == "success" else output

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "category": self.category,
            "metadata": dict(self.metadata),
            "error": self.error,
        }


def _make_result(status: str) -> _Result:
    return _Result(status=status, output=f"result-{status}")


def RecordingBridgeFactory(result_status: str) -> type:
    """
    Return a FRESH class (not an instance) configured to return a _Result
    with the given status. Each call produces a new class with its own
    `instances = []` — no shared state between scenarios.

    Must be a callable-that-returns-instances because UnifiedAppObjectiveRunner
    calls `TrinityBridge()` (i.e. instantiates it).
    """

    class RecordingBridge:
        instances: list["RecordingBridge"] = []

        def __init__(self) -> None:
            self.execute_calls: list[dict[str, Any]] = []
            RecordingBridge.instances.append(self)

        async def initialize(self) -> None:
            return None

        async def execute_task(self, **kwargs: Any) -> _Result:
            self.execute_calls.append(kwargs)
            return _make_result(result_status)

        async def shutdown(self) -> None:
            return None

    return RecordingBridge


# ---------------------------------------------------------------------------
# Base scenario — no "Test" prefix so pytest does not collect it directly
# ---------------------------------------------------------------------------

class BaseHandoffScenario(ContractMixin):
    """
    Contract: every concrete subclass declares its scenario inputs and
    expected outputs as class variables. The 15 test methods below run
    automatically against every subclass, giving 15 granular assertions
    per scenario.

    To add a new scenario: subclass this and override the class variables.
    Do not override any test methods unless you need scenario-specific logic.
    """

    # --- scenario declaration (subclasses override) -----------------------
    task_description: str = "base task"
    domain: str = "cli"
    approved_plan: list[str] = []
    expected_domain: str = "cli"
    expected_target_server: str = "cli_mcp"
    expected_final_status: str = "success"
    bridge_result_status: str = "success"

    # --- contract bounds (subclasses may override) ------------------------
    exec_time_soft_ms: float = 500.0
    exec_time_hard_ms: float = 2000.0
    step_count_soft: int = 10
    step_count_hard: int | None = 50
    required_signal_keys: tuple[str, ...] = ("status", "target_server", "domain", "task_id")

    # --- runtime state (populated by fixture) -----------------------------
    handoff: dict[str, Any]
    history: RecordingHistoryManager
    completions: list[dict[str, Any]]
    bridge: Any
    elapsed_ms: float
    worker_task_id: str

    # --- fixture -----------------------------------------------------------

    @pytest.fixture(autouse=True)
    async def _run_scenario(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Run the scenario once and store results on self so every test
        method can make its assertion independently.
        """
        history = RecordingHistoryManager()
        bus = EventBus()
        completions: list[dict[str, Any]] = []
        bus.execution_complete.connect(lambda payload: completions.append(payload))

        BridgeCls = RecordingBridgeFactory(self.bridge_result_status)

        monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
        monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
        monkeypatch.setattr(core_module, "TrinityBridge", BridgeCls)

        worker = UnifiedAppObjectiveRunner(
            self.task_description,
            self.domain,
            approved_plan=list(self.approved_plan),
        )

        _t0 = time.perf_counter()
        await worker._execute()
        self.elapsed_ms = (time.perf_counter() - _t0) * 1000.0

        self.bridge = BridgeCls.instances[-1]
        self.handoff = self.bridge.execute_calls[-1]
        self.history = history
        self.completions = completions
        self.worker_task_id = worker.task_id

    # --- exact-value assertions (inherited by every concrete subclass) ----

    def test_correct_domain_in_handoff(self) -> None:
        assert self.handoff["domain"] == self.expected_domain

    def test_correct_server_in_handoff(self) -> None:
        assert self.handoff["target_server"] == self.expected_target_server

    def test_sub_objectives_forwarded(self) -> None:
        assert self.handoff["sub_objectives"] == self.approved_plan

    def test_no_expected_outcome_leaked(self) -> None:
        assert "expected_outcome" not in self.handoff

    def test_bridge_called_exactly_once(self) -> None:
        assert len(self.bridge.execute_calls) == 1

    def test_history_task_marked_completed(self) -> None:
        # UnifiedAppObjectiveRunner records COMPLETED whenever the bridge returns
        # without raising — even when result status is "failure".
        # Only an exception triggers TaskStatus.FAILED.
        assert self.history.completed_calls[-1]["status"] == TaskStatus.COMPLETED

    def test_execution_complete_signal_fired(self) -> None:
        assert len(self.completions) >= 1

    def test_signal_carries_correct_target_server(self) -> None:
        assert self.completions[-1]["target_server"] == self.expected_target_server

    def test_signal_carries_correct_status(self) -> None:
        assert self.completions[-1]["status"] == self.expected_final_status

    # --- contract assertions (graduated severity) -------------------------

    def test_execution_time_contract(self) -> None:
        """Wall-clock duration of _execute() must stay within bounds.
        Catches accidental network calls or deadlocks in recording tests."""
        self._assert_contract(
            self.elapsed_ms,
            self.exec_time_soft_ms,
            self.exec_time_hard_ms,
            label="elapsed_ms",
        )

    def test_signal_payload_completeness(self) -> None:
        """All required keys must be present in the execution_complete payload."""
        payload = self.completions[-1]
        missing = [k for k in self.required_signal_keys if k not in payload]
        if missing:
            pytest.fail(
                f"execution_complete payload missing keys: {missing}. "
                f"Got: {list(payload.keys())}"
            )

    def test_task_id_traceability(self) -> None:
        """The same task_id must appear in history, bridge handoff, and signal."""
        wid = self.worker_task_id
        errors = []
        if self.history.created_task_id != wid:
            errors.append(
                f"history.created_task_id={self.history.created_task_id!r} != {wid!r}"
            )
        if self.handoff.get("task_id") != wid:
            errors.append(
                f"handoff['task_id']={self.handoff.get('task_id')!r} != {wid!r}"
            )
        if self.completions[-1].get("task_id") != wid:
            errors.append(
                f"signal task_id={self.completions[-1].get('task_id')!r} != {wid!r}"
            )
        if errors:
            pytest.fail("task_id traceability broken:\n" + "\n".join(errors))

    def test_history_call_ordering(self) -> None:
        """History methods must be called: create_task → start_task → … → complete_task."""
        log = self.history.call_log
        if len(log) < 3:
            pytest.fail(
                f"call_log has only {len(log)} entries, expected ≥3. Got: {log}"
            )
        if log[0] != "create_task":
            pytest.fail(
                f"First history call must be 'create_task', got {log[0]!r}. Log: {log}"
            )
        if log[1] != "start_task":
            pytest.fail(
                f"Second history call must be 'start_task', got {log[1]!r}. Log: {log}"
            )
        if log[-1] != "complete_task":
            pytest.fail(
                f"Last history call must be 'complete_task', got {log[-1]!r}. Log: {log}"
            )

    def test_step_count_contract(self) -> None:
        """Number of update_step_status calls must stay within bounds."""
        self._assert_contract(
            len(self.history.step_updates),
            self.step_count_soft,
            self.step_count_hard,
            label="step_update_count",
        )

    def test_failure_payload_shape(self) -> None:
        """On the non-exception failure path, payload has 'output' not 'error'."""
        if self.bridge_result_status != "failure":
            pytest.skip("Not a failure scenario — shape contract only applies to failure results")
        payload = self.completions[-1]
        if "output" not in payload:
            pytest.fail(
                f"Non-exception failure payload must have 'output'. "
                f"Got keys: {list(payload.keys())}"
            )
        if "error" in payload:
            pytest.fail(
                "Non-exception failure payload must NOT have 'error' (that is the exception path). "
                f"Got keys: {list(payload.keys())}"
            )
