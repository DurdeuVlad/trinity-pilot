from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    gemini_api_key: str
    gemini_planner_model: str = "gemini-1.5-pro"
    gemini_worker_model: str = "gemini-1.5-flash"
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    db_path: str = "trinity_pilot.db"

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY not set. Add it to .env or environment."
            )
        return cls(
            gemini_api_key=api_key,
            gemini_planner_model=os.getenv("GEMINI_PLANNER_MODEL", "gemini-1.5-pro"),
            gemini_worker_model=os.getenv("GEMINI_WORKER_MODEL", "gemini-1.5-flash"),
            temporal_host=os.getenv("TEMPORAL_HOST", "localhost:7233"),
            temporal_namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
            db_path=os.getenv("DB_PATH", "trinity_pilot.db"),
        )
