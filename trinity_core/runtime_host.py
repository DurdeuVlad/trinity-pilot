"""Reusable backend runtime host and session manager."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional

from .models import (
    BackendProfile,
    CapabilityDescriptor,
    RuntimeArtifact,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeFailureCategory,
    RuntimeResult,
    RuntimeSession,
    RuntimeStatus,
)


class RuntimeHost:
    """
    Reusable runtime host for backend execution.
    
    This class manages backend sessions, executes objectives, emits events,
    and provides lifecycle management. It is designed to be wrapped by
    backend MCP servers.
    """

    def __init__(
        self,
        backend_id: Literal["cli", "browser", "desktop"],
        profile: BackendProfile,
        executor_fn: Callable,
        readiness_check_fn: Optional[Callable] = None,
        safety_hook_fn: Optional[Callable] = None,
        artifact_hook_fn: Optional[Callable] = None,
    ):
        """
        Initialize runtime host.
        
        Args:
            backend_id: Backend identifier (cli, browser, desktop)
            profile: Backend profile configuration
            executor_fn: Async function to execute objectives
            readiness_check_fn: Optional async function to check backend readiness
            safety_hook_fn: Optional async function for safety policy checks
            artifact_hook_fn: Optional async function to collect artifacts
        """
        self.backend_id = backend_id
        self.profile = profile
        self.executor_fn = executor_fn
        self.readiness_check_fn = readiness_check_fn
        self.safety_hook_fn = safety_hook_fn
        self.artifact_hook_fn = artifact_hook_fn
        
        self.sessions: Dict[str, RuntimeSession] = {}
        self._event_sequence: Dict[str, int] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    async def health_check(self) -> bool:
        """Check if backend is healthy and ready."""
        if self.readiness_check_fn is None:
            return True
        try:
            return await self.readiness_check_fn()
        except Exception:
            return False

    def list_capabilities(self) -> List[CapabilityDescriptor]:
        """List available backend capabilities."""
        return self.profile.capabilities

    def create_session(self, session_id: Optional[str] = None) -> RuntimeSession:
        """
        Create a new runtime session.
        
        Args:
            session_id: Optional session ID, generated if not provided
            
        Returns:
            RuntimeSession instance
        """
        if session_id is None:
            session_id = uuid.uuid4().hex
        
        if session_id in self.sessions:
            raise ValueError(f"Session {session_id} already exists")
        
        now = datetime.now(timezone.utc).isoformat()
        session = RuntimeSession(
            session_id=session_id,
            backend_id=self.backend_id,
            status=RuntimeStatus.CREATED,
            created_at=now,
        )
        
        self.sessions[session_id] = session
        self._event_sequence[session_id] = 0
        self._locks[session_id] = asyncio.Lock()
        
        self._emit_event(
            session_id=session_id,
            event_type=RuntimeEventType.SESSION_CREATED,
            data={"backend_id": self.backend_id},
        )
        
        return session

    async def run_objective(
        self,
        session_id: str,
        objective_id: str,
        objective: str,
        context: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> RuntimeResult:
        """
        Execute an objective within a session.
        
        Args:
            session_id: Session identifier
            objective_id: Objective identifier
            objective: Objective description
            context: Optional context dictionary
            max_retries: Optional max retries override
            timeout: Optional timeout override
            
        Returns:
            RuntimeResult
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        lock = self._locks[session_id]
        
        async with lock:
            if max_retries is None:
                max_retries = self.profile.max_retries
            if timeout is None:
                timeout = self.profile.timeout
            
            now = datetime.now(timezone.utc).isoformat()
            session.status = RuntimeStatus.RUNNING
            session.started_at = now
            
            self._emit_event(
                session_id=session_id,
                event_type=RuntimeEventType.OBJECTIVE_STARTED,
                objective_id=objective_id,
                data={"objective": objective, "max_retries": max_retries, "timeout": timeout},
            )
            
            try:
                if self.safety_hook_fn is not None:
                    safety_result = await self.safety_hook_fn(objective, context or {})
                    if not safety_result.get("allowed", True):
                        return self._create_failure_result(
                            session_id=session_id,
                            objective_id=objective_id,
                            started_at=now,
                            error=safety_result.get("reason", "Safety policy rejected objective"),
                            failure_category=RuntimeFailureCategory.VALIDATOR_REJECTION,
                        )
                
                result = await asyncio.wait_for(
                    self.executor_fn(
                        session_id=session_id,
                        objective_id=objective_id,
                        objective=objective,
                        context=context or {},
                        max_retries=max_retries,
                    ),
                    timeout=timeout,
                )
                
                if self.artifact_hook_fn is not None:
                    artifacts = await self.artifact_hook_fn(session_id, objective_id)
                    if artifacts:
                        session.artifacts.extend(artifacts)
                        result.artifacts.extend(artifacts)
                
                session.status = RuntimeStatus.COMPLETED if result.status == RuntimeStatus.COMPLETED else RuntimeStatus.FAILED
                session.completed_at = datetime.now(timezone.utc).isoformat()
                
                if result.status == RuntimeStatus.COMPLETED:
                    self._emit_event(
                        session_id=session_id,
                        event_type=RuntimeEventType.OBJECTIVE_COMPLETED,
                        objective_id=objective_id,
                        data={"output": result.output},
                    )
                else:
                    self._emit_event(
                        session_id=session_id,
                        event_type=RuntimeEventType.OBJECTIVE_FAILED,
                        objective_id=objective_id,
                        data={"error": result.error, "failure_category": result.failure_category.value if result.failure_category else None},
                    )
                
                return result
                
            except asyncio.TimeoutError:
                return self._create_failure_result(
                    session_id=session_id,
                    objective_id=objective_id,
                    started_at=now,
                    error=f"Objective timed out after {timeout}s",
                    failure_category=RuntimeFailureCategory.TIMEOUT,
                )
            except Exception as e:
                return self._create_failure_result(
                    session_id=session_id,
                    objective_id=objective_id,
                    started_at=now,
                    error=str(e),
                    failure_category=RuntimeFailureCategory.EXECUTION_FAILURE,
                )

    def read_events(
        self,
        session_id: str,
        after_sequence: Optional[int] = None,
    ) -> List[RuntimeEvent]:
        """
        Read events from a session.
        
        Args:
            session_id: Session identifier
            after_sequence: Optional sequence number to read after
            
        Returns:
            List of RuntimeEvent
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        
        if after_sequence is None:
            return session.events
        
        return [event for event in session.events if event.sequence > after_sequence]

    def get_status(self, session_id: str) -> RuntimeSession:
        """
        Get session status.
        
        Args:
            session_id: Session identifier
            
        Returns:
            RuntimeSession
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        return self.sessions[session_id]

    async def interrupt(self, session_id: str) -> None:
        """
        Interrupt a running session.
        
        Args:
            session_id: Session identifier
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        
        if session.status == RuntimeStatus.RUNNING:
            session.status = RuntimeStatus.INTERRUPTED
            session.completed_at = datetime.now(timezone.utc).isoformat()
            
            self._emit_event(
                session_id=session_id,
                event_type=RuntimeEventType.SESSION_INTERRUPTED,
                data={},
            )

    async def terminate(self, session_id: str) -> None:
        """
        Terminate a session.
        
        Args:
            session_id: Session identifier
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        session.status = RuntimeStatus.TERMINATED
        session.completed_at = datetime.now(timezone.utc).isoformat()
        
        self._emit_event(
            session_id=session_id,
            event_type=RuntimeEventType.SESSION_TERMINATED,
            data={},
        )

    def close_session(self, session_id: str) -> None:
        """
        Close and cleanup a session.
        
        Args:
            session_id: Session identifier
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self._event_sequence:
            del self._event_sequence[session_id]
        if session_id in self._locks:
            del self._locks[session_id]

    def list_artifacts(self, session_id: str) -> List[RuntimeArtifact]:
        """
        List artifacts from a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of RuntimeArtifact
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        return self.sessions[session_id].artifacts

    def _emit_event(
        self,
        session_id: str,
        event_type: RuntimeEventType,
        objective_id: Optional[str] = None,
        action_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a runtime event."""
        if session_id not in self.sessions:
            return
        
        session = self.sessions[session_id]
        sequence = self._event_sequence[session_id]
        self._event_sequence[session_id] += 1
        
        event = RuntimeEvent(
            sequence=sequence,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            objective_id=objective_id,
            action_id=action_id,
            data=data or {},
            metadata=metadata or {},
        )
        
        session.events.append(event)

    def _create_failure_result(
        self,
        session_id: str,
        objective_id: str,
        started_at: str,
        error: str,
        failure_category: RuntimeFailureCategory,
    ) -> RuntimeResult:
        """Create a failure result."""
        session = self.sessions[session_id]
        session.status = RuntimeStatus.FAILED
        session.completed_at = datetime.now(timezone.utc).isoformat()
        
        self._emit_event(
            session_id=session_id,
            event_type=RuntimeEventType.OBJECTIVE_FAILED,
            objective_id=objective_id,
            data={"error": error, "failure_category": failure_category.value},
        )
        
        return RuntimeResult(
            session_id=session_id,
            objective_id=objective_id,
            status=RuntimeStatus.FAILED,
            error=error,
            failure_category=failure_category,
            output=None,
            artifacts=[],
            metadata={},
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
