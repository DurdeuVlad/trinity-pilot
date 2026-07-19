from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    gemini_api_key: str
    gemini_planner_model: str = "gemini-2.5-flash"
    gemini_worker_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 30.0
    stuck_threshold_steps: int = 5
    db_path: str = "trinity_pilot.db"
    debug_mode: bool = False

    def validate(self) -> None:
        if not self.gemini_api_key:
            raise ConfigError("GEMINI_API_KEY is required but not set.")

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

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> "Settings":
        if dotenv_path is not None:
            load_dotenv(dotenv_path=dotenv_path, override=True)
        settings = cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_planner_model=os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash"),
            gemini_worker_model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.5-flash"),
            gemini_timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30.0")),
            stuck_threshold_steps=int(os.getenv("STUCK_THRESHOLD_STEPS", "5")),
            db_path=os.getenv("DB_PATH", "trinity_pilot.db"),
            debug_mode=os.getenv("TRINITY_DEBUG_MODE", "false").strip().lower() in ("true", "1", "yes"),
        )
        settings.validate()
        return settings
