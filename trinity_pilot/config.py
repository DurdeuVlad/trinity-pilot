from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_APP_DATA_DIR = Path.home() / ".trinity-pilot"


def _default_db_path() -> str:
    """Anchor the default DB to a fixed app-data directory, not the launch CWD."""
    _APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(_APP_DATA_DIR / "trinity_pilot.db")


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    gemini_api_key: str
    gemini_planner_model: str = "gemini-2.5-flash"
    gemini_worker_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 120.0
    stuck_threshold_steps: int = 3
    db_path: str = field(default_factory=_default_db_path)
    debug_mode: bool = False

    def validate(self) -> None:
        if not self.gemini_api_key:
            raise ConfigError("GEMINI_API_KEY is required but not set.")
        if self.gemini_timeout_seconds <= 0:
            raise ConfigError(
                f"GEMINI_TIMEOUT_SECONDS must be positive, got {self.gemini_timeout_seconds!r} "
                "— a zero or negative value would make every LLM call time out instantly."
            )
        if self.stuck_threshold_steps <= 0:
            raise ConfigError(
                f"STUCK_THRESHOLD_STEPS must be a positive integer, got {self.stuck_threshold_steps!r}."
            )

    @staticmethod
    def playwright_preflight() -> tuple[bool, str]:
        """Check that this Python environment has the Chromium revision Playwright expects."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False, "Playwright is not installed in this Python environment."

        try:
            with sync_playwright() as playwright:
                executable = Path(playwright.chromium.executable_path)
        except Exception as exc:
            return False, f"Playwright driver preflight failed: {exc}"

        if executable.is_file():
            return True, f"Playwright Chromium ready: {executable}"
        return False, (
            f"Playwright Chromium is missing: {executable}. "
            "Run 'playwright install chromium' using this project's Python environment."
        )

    @staticmethod
    async def playwright_preflight_async() -> tuple[bool, str]:
        """Async equivalent for live workers and async test harnesses."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return False, "Playwright is not installed in this Python environment."

        try:
            async with async_playwright() as playwright:
                executable = Path(playwright.chromium.executable_path)
        except Exception as exc:
            return False, f"Playwright driver preflight failed: {exc}"

        if executable.is_file():
            return True, f"Playwright Chromium ready: {executable}"
        return False, (
            f"Playwright Chromium is missing: {executable}. "
            "Run 'playwright install chromium' using this project's Python environment."
        )

    @staticmethod
    def desktop_automation_preflight() -> tuple[bool, str]:
        """Check that pywinauto/pywin32 are importable before the first desktop task.

        Without this, a missing/broken native dependency surfaces as a raw
        ImportError deep inside DesktopWorker.execute() — this runs at startup
        instead so the failure is a clear, early warning.
        """
        if sys.platform != "win32":
            return False, "Desktop automation is Windows-only; this platform is unsupported."
        try:
            import pywinauto  # noqa: F401
        except ImportError as exc:
            return False, f"pywinauto is not installed or failed to import: {exc}"
        try:
            import win32gui  # noqa: F401
        except ImportError as exc:
            return False, f"pywin32 is not installed or failed to import: {exc}"
        return True, "Desktop automation ready (pywinauto/pywin32 importable)."

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> "Settings":
        if dotenv_path is not None:
            load_dotenv(dotenv_path=dotenv_path, override=True)

        timeout_raw = os.getenv("GEMINI_TIMEOUT_SECONDS", "120.0")
        try:
            gemini_timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise ConfigError(
                f"GEMINI_TIMEOUT_SECONDS must be a number, got {timeout_raw!r}."
            ) from exc

        threshold_raw = os.getenv("STUCK_THRESHOLD_STEPS", "3")
        try:
            stuck_threshold_steps = int(threshold_raw)
        except ValueError as exc:
            raise ConfigError(
                f"STUCK_THRESHOLD_STEPS must be an integer, got {threshold_raw!r}."
            ) from exc

        settings = cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_planner_model=os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash"),
            gemini_worker_model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.5-flash"),
            gemini_timeout_seconds=gemini_timeout_seconds,
            stuck_threshold_steps=stuck_threshold_steps,
            db_path=os.getenv("DB_PATH", _default_db_path()),
            debug_mode=os.getenv("TRINITY_DEBUG_MODE", "false").strip().lower() in ("true", "1", "yes"),
        )
        settings.validate()
        return settings
