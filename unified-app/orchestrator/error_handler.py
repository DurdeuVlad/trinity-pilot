"""Application-level error handling utilities."""
from __future__ import annotations

from datetime import datetime, timezone
import traceback
import sys
from typing import Any, Dict, Optional

_BACKEND_UNAVAILABLE_MARKERS = (
    "is not available",
    "not initialized",
    "not available in this environment",
    "trinity core is not available",
    "not enabled in config",
    "adapter is not available",
)

_DOMAIN_NEXT_ACTION_HINTS: dict[str, str] = {
    "cli": "Ensure the CLI backend is installed and enabled in Settings -> General.",
    "web": "Ensure the Browser backend is running (requires Playwright) and enabled in Settings.",
    "desktop": "Ensure the Desktop backend is enabled and running on Windows with UIA support.",
}


class ErrorHandler:
    """Normalize exceptions into UI/log-friendly payloads."""

    def classify_error(self, message: str) -> str:
        """Classify an error string as 'transient' or 'permanent'."""
        lowered = (message or "").lower()
        transient_tokens = (
            "timed out", "timeout", "network", "unreachable", "dns",
            "connection", "ssl", "service unavailable", "app not ready",
            "element not found", "not visible", "not interactable",
            "429", "rate limit", "too many requests", "resourceexhausted",
            "temporarily unavailable", "retry", "try again",
        )
        permanent_tokens = (
            "permission denied", "access denied", "unauthorized",
            "file not found", "no such file", "not installed",
            "invalid command", "command not found", "not recognized",
            "app not found", "cannot find", "does not exist",
            "api_key_invalid", "invalid api key", "unauthenticated",
        )
        if any(token in lowered for token in transient_tokens):
            return "transient"
        if any(token in lowered for token in permanent_tokens):
            return "permanent"
        return "transient"

    def classify_live_failure(self, message: str) -> str:
        """Return a contract category inferred from legacy live Gemini failures."""
        lowered = (message or "").lower()
        if any(token in lowered for token in ("api_key_invalid", "invalid api key", "api key not valid", "unauthenticated", "invalidargument")):
            return "auth_failure"
        if any(token in lowered for token in ("timed out", "timeout")):
            return "timeout"
        if any(token in lowered for token in ("429", "quota exceeded", "resourceexhausted", "rate limit", "too many requests", "connectionerror", "network", "unreachable", "dns", "ssl", "service unavailable")):
            return "backend_error"
        if any(token in lowered for token in ("jsondecodeerror", "expecting value", "invalid plan json", "missing 'plan' key", "missing required keys", "empty response", "empty plan", "blank steps", "unusable")):
            return "user_error"
        return "backend_error"

    def build_user_message(self, message: str, category: str | None = None) -> str:
        """Return an operator-safe message for contract failure categories."""
        if (message or "").lstrip().startswith("Gemini "):
            return self.normalize_user_message(message)

        resolved_category = category or self.classify_live_failure(message)
        if resolved_category == "auth_failure":
            return "Authentication failed - check your API key in settings."
        if resolved_category == "timeout":
            return "The request timed out - try again or reduce the task complexity."
        if resolved_category == "backend_error":
            lowered = (message or "").lower()
            if any(token in lowered for token in ("no module named", "cannot import", "not available in this environment")):
                return self.normalize_user_message(message)
            return "The backend encountered an error - check the run log for details."
        if resolved_category == "health_check_failed":
            return "The backend failed its health check - check the run log for details."
        if resolved_category == "user_error":
            return "The request could not be understood - try rephrasing the objective."
        if resolved_category == "cancelled":
            return "The task was cancelled."
        return self.normalize_user_message(message)

    def map_backend_unavailable_reason(self, domain: str, error_text: str) -> str | None:
        """Return a domain-specific message when the backend is unavailable."""
        lowered = (error_text or "").lower()
        if not any(marker in lowered for marker in _BACKEND_UNAVAILABLE_MARKERS):
            return None
        hint = _DOMAIN_NEXT_ACTION_HINTS.get(
            domain,
            "Check that the backend is enabled in Settings -> General.",
        )
        return f"The {domain} backend is not available. {hint}"

    def normalize_user_message(self, message: str) -> str:
        """Return a user-safe error line without traceback noise."""
        cleaned = (message or "").replace("\r", "\n").strip()
        if not cleaned:
            return "Task failed due to an internal error."

        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        filtered = [
            line
            for line in lines
            if "traceback" not in line.lower() and not line.lower().startswith("file ")
        ]
        primary = filtered[0] if filtered else "Task failed due to an internal error."
        if len(primary) > 180:
            primary = f"{primary[:177]}..."
        return primary

    def extract_error_details(self, exc: Exception) -> Dict[str, Any]:
        """Extract all available error details from exception.
        
        This preserves StructuredError details if present, otherwise
        captures standard exception info with full traceback.
        
        Args:
            exc: Exception to extract details from
            
        Returns:
            Dict with error_type, message, traceback, and any structured_error
        """
        details: Dict[str, Any] = {
            "error_type": exc.__class__.__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        
        # Check if exception carries StructuredError
        # (Trinity Core may wrap errors in custom exceptions with .structured_error attribute)
        if hasattr(exc, 'structured_error'):
            structured = getattr(exc, 'structured_error')
            if hasattr(structured, 'model_dump'):
                details["structured_error"] = structured.model_dump()
            elif isinstance(structured, dict):
                details["structured_error"] = structured
        
        # Check if exception args contain StructuredError dict
        if hasattr(exc, 'args') and exc.args:
            if isinstance(exc.args[0], dict) and 'layer' in exc.args[0]:
                details["structured_error"] = exc.args[0]
        
        # Check for TaskResult with error metadata
        if hasattr(exc, 'metadata') and isinstance(exc.metadata, dict):
            details["task_metadata"] = exc.metadata
        
        return details

    def handle(self, error: Exception, context: str = "", category: str | None = None) -> dict:
        """Convert exception to structured error payload.
        
        Now preserves full error details including StructuredError if present.
        """
        message = str(error) or error.__class__.__name__
        resolved_category = category or self.classify_live_failure(message)
        safe_message = self.build_user_message(message, category=resolved_category)
        
        # Extract full error details
        error_details = self.extract_error_details(error)
        
        payload = {
            "type": error.__class__.__name__,
            "category": resolved_category,
            "message": message,
            "context": context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_message": f"{context}: {safe_message}" if context else safe_message,
            "error_details": error_details,  # ← NEW: Full error details
        }
        return payload
