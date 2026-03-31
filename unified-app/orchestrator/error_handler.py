"""Application-level error handling utilities."""
from __future__ import annotations

from datetime import UTC, datetime


class ErrorHandler:
    """Normalize exceptions into UI/log-friendly payloads."""

    def classify_error(self, message: str) -> str:
        """Classify an error string as 'transient' or 'permanent'.

        Transient errors may succeed on retry with the same approach.
        Permanent errors require a different approach or are unrecoverable.
        """
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
        if any(t in lowered for t in transient_tokens):
            return "transient"
        if any(t in lowered for t in permanent_tokens):
            return "permanent"
        return "transient"  # default: assume retryable unless proven otherwise

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

        # Gemini-client messages are already user-friendly; preserve them rather
        # than replacing with a generic category template.
        if (message or "").lstrip().startswith("Gemini "):
            return self.normalize_user_message(message)

        resolved_category = category or self.classify_live_failure(message)
        if resolved_category == "auth_failure":
            return "Authentication failed — check your API key in settings."
        if resolved_category == "timeout":
            return "The request timed out — try again or reduce the task complexity."
        if resolved_category == "backend_error":
            return "The backend encountered an error — check the run log for details."
        if resolved_category == "user_error":
            return "The request could not be understood — try rephrasing the objective."
        if resolved_category == "cancelled":
            return "The task was cancelled."
        return self.normalize_user_message(message)

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

    def handle(self, error: Exception, context: str = "", category: str | None = None) -> dict:
        """Convert exception to structured error payload."""
        message = str(error) or error.__class__.__name__
        resolved_category = category or self.classify_live_failure(message)
        safe_message = self.build_user_message(message, category=resolved_category)
        payload = {
            "type": error.__class__.__name__,
            "category": resolved_category,
            "message": message,
            "context": context,
            "timestamp": datetime.now(UTC).isoformat(),
            "user_message": f"{context}: {safe_message}" if context else safe_message,
        }
        return payload
