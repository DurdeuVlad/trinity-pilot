import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class CheckResult:
    def __init__(self, success: bool, message: str, details: dict[str, Any] | None = None) -> None:
        self.success = success
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "details": self.details,
        }

class CheckDeliverable(ABC):
    @abstractmethod
    def check(self) -> CheckResult:
        """Run the assertion verification and return the result."""
        pass

class FileExistsCheck(CheckDeliverable):
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def check(self) -> CheckResult:
        exists = self.path.exists()
        if exists:
            return CheckResult(True, f"File exists: {self.path}", {"path": str(self.path)})
        return CheckResult(False, f"File not found: {self.path}", {"path": str(self.path)})

class FileContentContainsCheck(CheckDeliverable):
    def __init__(self, path: Path | str, substring: str, case_sensitive: bool = True) -> None:
        self.path = Path(path)
        self.substring = substring
        self.case_sensitive = case_sensitive

    def check(self) -> CheckResult:
        if not self.path.exists():
            return CheckResult(False, f"File not found for content check: {self.path}", {"path": str(self.path)})
        try:
            content = self.path.read_text(encoding="utf-8", errors="replace")
            matched = False
            if self.case_sensitive:
                matched = self.substring in content
            else:
                matched = self.substring.lower() in content.lower()
            if matched:
                return CheckResult(True, f"Found expected content in file: {self.substring}", {"path": str(self.path)})
            return CheckResult(False, f"Expected content '{self.substring}' not found in file", {"path": str(self.path), "content_preview": content[:200]})
        except Exception as e:
            return CheckResult(False, f"Failed to read file: {e}", {"path": str(self.path), "error": str(e)})

class JsonFormatCheck(CheckDeliverable):
    def __init__(self, path: Path | str, required_keys: list[str] | None = None) -> None:
        self.path = Path(path)
        self.required_keys = required_keys or []

    def check(self) -> CheckResult:
        if not self.path.exists():
            return CheckResult(False, f"JSON file not found: {self.path}", {"path": str(self.path)})
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            missing = [k for k in self.required_keys if k not in data]
            if missing:
                return CheckResult(False, f"JSON missing required keys: {missing}", {"path": str(self.path), "missing_keys": missing})
            return CheckResult(True, "JSON format and required keys validated", {"path": str(self.path)})
        except Exception as e:
            return CheckResult(False, f"Failed to parse JSON: {e}", {"path": str(self.path), "error": str(e)})

class UiTextContainsCheck(CheckDeliverable):
    def __init__(self, driver: Any, substring: str, case_sensitive: bool = False) -> None:
        self.driver = driver
        self.substring = substring
        self.case_sensitive = case_sensitive

    def check(self) -> CheckResult:
        try:
            ui = self.driver.ui_text()
            matched = False
            if self.case_sensitive:
                matched = self.substring in ui
            else:
                matched = self.substring.lower() in ui.lower()
            if matched:
                return CheckResult(True, f"Found expected substring '{self.substring}' in UI text", {})
            return CheckResult(False, f"Expected substring '{self.substring}' not found in UI text", {"ui_text_preview": ui[:300]})
        except Exception as e:
            return CheckResult(False, f"Failed to read UI text: {e}", {"error": str(e)})

