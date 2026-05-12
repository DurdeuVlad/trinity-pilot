from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    gemini_api_key: str
    gemini_planner_model: str = "gemini-2.0-flash"
    gemini_worker_model: str = "gemini-2.0-flash"
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    db_path: str = "trinity_pilot.db"
    debug_mode: bool = False

    def validate(self) -> None:
        if not self.gemini_api_key:
            raise ConfigError("GEMINI_API_KEY is required but not set.")
        if not self.temporal_host:
            raise ConfigError("TEMPORAL_HOST must not be empty.")
        if not self.temporal_namespace:
            raise ConfigError("TEMPORAL_NAMESPACE must not be empty.")

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> "Settings":
        if dotenv_path is not None:
            load_dotenv(dotenv_path=dotenv_path, override=True)
        settings = cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_planner_model=os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.0-flash"),
            gemini_worker_model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.0-flash"),
            temporal_host=os.getenv("TEMPORAL_HOST", "localhost:7233"),
            temporal_namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
            db_path=os.getenv("DB_PATH", "trinity_pilot.db"),
            debug_mode=os.getenv("TRINITY_DEBUG_MODE", "false").strip().lower() in ("true", "1", "yes"),
        )
        settings.validate()
        return settings
