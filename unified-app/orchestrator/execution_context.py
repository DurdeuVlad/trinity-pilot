"""Execution context for cross-module state sharing in the orchestrator."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

# App names that produce a "blank document" on launch — used by WorldState
_BLANK_DOCUMENT_APPS_WS: frozenset[str] = frozenset({"notepad", "wordpad"})
# Result prefixes that indicate a status string, NOT meaningful text content
_STATUS_PREFIXES: tuple[str, ...] = (
    "OK (",
    "Navigated",
    "Searched",
    "Focused",
    "Opened",
    "Closed",
    "Pasted",
    "Clicked",
    "Typed",
)


@dataclass
class WorldState:
    """First-class world state shared across objectives, backends, and subprocesses.

    Tracks explicit facts about what is currently open, what was last read,
    and what mode an app is in — replacing fragile heuristic string scanning.

    Fields
    ------
    active_app       : Which application is currently active ("Notepad", "browser", …)
    active_window    : Window title or regex hint (optional, for disambiguation)
    active_document  : File path or logical document name ("new document", …)
    last_text_artifact : Most recent meaningful extracted text (not status strings)
    last_opened_url  : Last URL navigated to in the browser
    app_launch_mode  : "launched" (we started it) | "attached" (was already running)
    document_state   : "fresh" (blank) | "existing" (has content)
    """

    active_app: Optional[str] = None
    active_window: Optional[str] = None
    active_document: Optional[str] = None
    last_text_artifact: Optional[str] = None
    last_opened_url: Optional[str] = None
    app_launch_mode: Optional[str] = None   # "launched" | "attached"
    document_state: Optional[str] = None    # "fresh" | "existing"

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def is_app_open(self, app_name: str) -> bool:
        """Return True if *app_name* matches the current active app."""
        if not self.active_app or not app_name:
            return False
        return self.active_app.lower() == app_name.lower().removesuffix(".exe")

    def has_state(self) -> bool:
        """Return True if any meaningful state has been recorded."""
        return any([
            self.active_app,
            self.last_text_artifact,
            self.last_opened_url,
            self.app_launch_mode,
            self.document_state,
        ])

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_context_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for passing to backend subprocesses."""
        return {
            "active_app": self.active_app,
            "active_window": self.active_window,
            "active_document": self.active_document,
            "last_text_artifact": self.last_text_artifact,
            "last_opened_url": self.last_opened_url,
            "app_launch_mode": self.app_launch_mode,
            "document_state": self.document_state,
        }

    def to_summary_lines(self) -> list[str]:
        """Return human-readable lines for LLM context injection."""
        lines: list[str] = []
        if self.active_app:
            line = f"  Active app: {self.active_app}"
            if self.app_launch_mode:
                line += f" ({self.app_launch_mode})"
            lines.append(line)
        if self.active_document:
            line = f"  Active document: {self.active_document}"
            if self.document_state:
                line += f" ({self.document_state})"
            lines.append(line)
        elif self.document_state:
            lines.append(f"  Document state: {self.document_state}")
        if self.last_opened_url:
            lines.append(f"  Last URL: {self.last_opened_url}")
        if self.last_text_artifact:
            preview = self.last_text_artifact[:100].replace("\n", " ")
            suffix = "…" if len(self.last_text_artifact) > 100 else ""
            lines.append(f'  Last text: "{preview}{suffix}"')
        return lines

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def update_from_action(
        self,
        action_type: str,
        params: dict[str, Any],
        result: str,
        result_payload: dict[str, Any] | None = None,
    ) -> None:
        """Update state based on a completed action and its result.

        Rules
        -----
        * Error results never update state.
        * Status strings (e.g. "OK (status=success)") do NOT contaminate
          ``last_text_artifact`` — only substantive content qualifies.
        * Browser actions always mark ``active_app = "browser"``.
        * Desktop open → ``active_app``, ``app_launch_mode = "launched"``;
          blank-doc apps also get ``document_state = "fresh"``.
        * Desktop focus → ``app_launch_mode = "attached"`` (was pre-existing).
        * Desktop paste/type → ``document_state = "existing"``.
        """
        if result.startswith("ERROR:"):
            return

        if action_type == "desktop":
            app: str = params.get("app", "")
            verb: str = params.get("action", "")
            if not app:
                return
            if verb == "open":
                self.active_app = app
                self.app_launch_mode = "launched"
                if app.lower() in _BLANK_DOCUMENT_APPS_WS:
                    self.document_state = "fresh"
                    self.active_document = "new document"
            elif verb == "focus":
                self.active_app = app
                if not self.app_launch_mode:
                    self.app_launch_mode = "attached"
            elif verb in ("paste", "type"):
                if not self.active_app:
                    self.active_app = app
                self.document_state = "existing"

        elif action_type == "browse":
            self.active_app = "browser"
            browse_action = str(params.get("action", "")).lower()
            url = str(params.get("url", "")).strip()
            if browse_action == "navigate" and url:
                self.last_opened_url = url
            elif browse_action in ("click", "type", "search"):
                current_url = _extract_current_url(result_payload)
                if current_url:
                    self.last_opened_url = current_url
            elif browse_action in ("read", "copy"):
                stripped = result.strip()
                if (
                    len(stripped) >= 20
                    and not any(stripped.startswith(p) for p in _STATUS_PREFIXES)
                ):
                    self.last_text_artifact = stripped


@dataclass
class ModuleResult:
    """Result from a module execution."""
    
    module: str
    status: str  # success, failure, partial
    output: Any
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    def is_success(self) -> bool:
        """Check if the module execution was successful."""
        return self.status == "success"
    
    def is_failure(self) -> bool:
        """Check if the module execution failed."""
        return self.status == "failure"


@dataclass
class ErrorRecord:
    """Record of an error that occurred during execution."""
    
    error_type: str
    error_message: str
    attempted_action: dict
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    
    def increment_retry(self) -> None:
        """Increment the retry count for this error."""
        self.retry_count += 1


@dataclass
class ExecutionContext:
    """Shared execution context that flows through the orchestrator.
    
    This context accumulates state, results, errors, and learned constraints
    as the orchestrator executes objectives. It enables cross-module information
    passing and adaptive behavior based on execution history.
    """
    
    objective: str
    module_results: dict[str, ModuleResult] = field(default_factory=dict)
    learned_constraints: list[str] = field(default_factory=list)
    accumulated_state: dict[str, Any] = field(default_factory=dict)
    backend_plan_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    error_history: list[ErrorRecord] = field(default_factory=list)
    retry_count: int = 0
    fallback_level: int = 0
    checkpoint_id: Optional[str] = None
    world_state: WorldState = field(default_factory=WorldState)
    
    def add_result(self, module: str, result: ModuleResult) -> None:
        """Add a module execution result to the context.
        
        Args:
            module: Name of the module that executed
            result: Result of the module execution
        """
        self.module_results[module] = result
    
    def add_error(self, error: ErrorRecord) -> None:
        """Add an error record to the context and increment retry count.
        
        Args:
            error: Error record to add
        """
        self.error_history.append(error)
        self.retry_count += 1
    
    def add_constraint(self, constraint: str) -> None:
        """Add a learned constraint to the context (deduplicates).
        
        Args:
            constraint: Constraint learned during execution
        """
        if constraint not in self.learned_constraints:
            self.learned_constraints.append(constraint)
    
    def update_state(self, key: str, value: Any) -> None:
        """Update accumulated state.
        
        Args:
            key: State key
            value: State value
        """
        self.accumulated_state[key] = value
    
    def get_last_error(self) -> Optional[ErrorRecord]:
        """Get the most recent error from history.
        
        Returns:
            Most recent error record, or None if no errors
        """
        return self.error_history[-1] if self.error_history else None
    
    def get_result(self, module: str) -> Optional[ModuleResult]:
        """Get result from a specific module.
        
        Args:
            module: Name of the module
            
        Returns:
            Module result, or None if module hasn't executed
        """
        return self.module_results.get(module)
    
    def get_successful_results(self) -> list[ModuleResult]:
        """Get all successful module results.
        
        Returns:
            List of successful module results
        """
        return [r for r in self.module_results.values() if r.is_success()]
    
    def get_failed_results(self) -> list[ModuleResult]:
        """Get all failed module results.
        
        Returns:
            List of failed module results
        """
        return [r for r in self.module_results.values() if r.is_failure()]
    
    def get_latest_text_result(self) -> str | None:
        """Return the most recent non-empty meaningful text result.

        Priority order:
          1. ``world_state.last_text_artifact`` — explicit, semantically
             filtered (status strings never land here).
          2. ``accumulated_state["latest_text_result"]`` — legacy per-action
             override written by the older browser read/copy path.
          3. Walk ``objective_N_result`` keys — final fallback from the
             objective-level result strings stored by the older execution flow.

        Returns None when no text has been captured yet.
        """
        if self.world_state.last_text_artifact:
            return self.world_state.last_text_artifact

        latest_text = self.accumulated_state.get("latest_text_result")
        if isinstance(latest_text, str) and latest_text.strip():
            return latest_text.strip()

        i = 1
        last_text: str | None = None
        while f"objective_{i}_result" in self.accumulated_state:
            value = self.accumulated_state[f"objective_{i}_result"]
            if isinstance(value, str) and value.strip():
                last_text = value.strip()
            i += 1
        return last_text

    def get_plan_state(self, objective_id: str | int, backend: str) -> dict[str, Any] | None:
        """Return persisted low-level plan state for one objective/backend pair."""
        objective_key = str(objective_id)
        backend_state = self.backend_plan_state.get(objective_key, {})
        plan_state = backend_state.get(backend)
        return dict(plan_state) if isinstance(plan_state, dict) else None

    def update_plan_state(self, objective_id: str | int, backend: str, plan_state: dict[str, Any]) -> None:
        """Persist low-level plan state for one objective/backend pair."""
        objective_key = str(objective_id)
        backend_bucket = self.backend_plan_state.setdefault(objective_key, {})
        backend_bucket[backend] = dict(plan_state)

    def get_plan_state_snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a copy of all persisted low-level plan states."""
        return {
            objective_id: {
                backend: dict(plan_state)
                for backend, plan_state in backend_state.items()
                if isinstance(plan_state, dict)
            }
            for objective_id, backend_state in self.backend_plan_state.items()
            if isinstance(backend_state, dict)
        }

    def update_world_state_from_action(
        self,
        action: dict,
        result: str,
        result_payload: dict[str, Any] | None = None,
    ) -> None:
        """Update the WorldState based on a completed action and its result.

        Delegates to ``world_state.update_from_action`` — exists as a
        convenience method so callers don't need to import WorldState directly.
        """
        self.world_state.update_from_action(
            action_type=action.get("action_type", ""),
            params=action.get("parameters", {}),
            result=result,
            result_payload=result_payload,
        )

    def has_errors(self) -> bool:
        """Check if any errors have occurred.

        Returns:
            True if error history is not empty
        """
        return len(self.error_history) > 0
    
    def reset_retry_count(self) -> None:
        """Reset the retry count (e.g., after successful execution)."""
        self.retry_count = 0
    
    def increment_fallback_level(self) -> None:
        """Increment the fallback level (for hierarchical fallback)."""
        self.fallback_level += 1
    
    def to_summary(self) -> dict[str, Any]:
        """Generate a summary of the context for logging/debugging.
        
        Returns:
            Dictionary with context summary
        """
        return {
            "objective": self.objective,
            "module_count": len(self.module_results),
            "successful_modules": len(self.get_successful_results()),
            "failed_modules": len(self.get_failed_results()),
            "error_count": len(self.error_history),
            "retry_count": self.retry_count,
            "fallback_level": self.fallback_level,
            "constraints_learned": len(self.learned_constraints),
            "state_keys": list(self.accumulated_state.keys()),
            "world_state": self.world_state.to_context_dict(),
            "plan_state_objectives": list(self.backend_plan_state.keys()),
        }


def _extract_current_url(result_payload: dict[str, Any] | None) -> str | None:
    if not isinstance(result_payload, dict):
        return None

    metadata = result_payload.get("metadata", {})
    if isinstance(metadata, dict):
        for candidate in (
            metadata.get("current_url"),
            metadata.get("url"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        raw_result = metadata.get("raw_result", {})
        if isinstance(raw_result, dict):
            for candidate in (
                raw_result.get("current_url"),
                raw_result.get("url"),
            ):
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()

    return None
