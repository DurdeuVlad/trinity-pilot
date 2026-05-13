"""Config unit tests -- Settings validation."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from trinity_pilot.config import ConfigError, Settings


class TestSettings:
    def test_from_env_raises_config_error_if_no_api_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            # Ensure key is absent/empty
            env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
            env["GEMINI_API_KEY"] = ""
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
                    Settings.from_env()

    def test_validate_raises_config_error_on_empty_key(self):
        s = Settings(gemini_api_key="")
        with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
            s.validate()

    def test_validate_passes_with_valid_key(self):
        s = Settings(gemini_api_key="fake-key-for-test")
        s.validate()  # should not raise

    def test_from_env_uses_defaults(self):
        env = {"GEMINI_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_env()
        assert s.gemini_planner_model == "gemini-2.0-flash"
        assert s.gemini_worker_model == "gemini-2.0-flash"
        assert s.db_path == "trinity_pilot.db"

    def test_from_env_respects_overrides(self):
        env = {
            "GEMINI_API_KEY": "my-key",
            "GEMINI_PLANNER_MODEL": "gemini-2.0-pro",
            "DB_PATH": "/tmp/test.db",
        }
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_env()
        assert s.gemini_planner_model == "gemini-2.0-pro"
        assert s.db_path == "/tmp/test.db"

    def test_from_env_loads_worker_model_override(self):
        env = {
            "GEMINI_API_KEY": "my-key",
            "GEMINI_WORKER_MODEL": "gemini-worker-test",
        }
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_env()

        assert s.gemini_worker_model == "gemini-worker-test"

    def test_config_error_is_exception(self):
        assert issubclass(ConfigError, Exception)

    def test_from_env_loads_dotenv_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("GEMINI_API_KEY=dotenv-loaded-key\n")
            # Clear env so only .env supplies the key
            with patch.dict(os.environ, {}, clear=True):
                s = Settings.from_env(dotenv_path=str(env_file))
            assert s.gemini_api_key == "dotenv-loaded-key"

    def test_from_env_succeeds_with_only_api_key(self):
        """No temporal env vars needed -- server starts cleanly with just GEMINI_API_KEY."""
        env = {"GEMINI_API_KEY": "only-key"}
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_env()
        assert s.gemini_api_key == "only-key"

    def test_gemini_timeout_seconds_defaults_to_30(self):
        env = {"GEMINI_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_env()
        assert s.gemini_timeout_seconds == 30.0

    def test_stuck_threshold_steps_defaults_to_5(self):
        env = {"GEMINI_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_env()
        assert s.stuck_threshold_steps == 5

    def test_gemini_timeout_seconds_env_override(self):
        env = {"GEMINI_API_KEY": "test-key", "GEMINI_TIMEOUT_SECONDS": "60"}
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_env()
        assert s.gemini_timeout_seconds == 60.0

    def test_stuck_threshold_steps_env_override(self):
        env = {"GEMINI_API_KEY": "test-key", "STUCK_THRESHOLD_STEPS": "10"}
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_env()
        assert s.stuck_threshold_steps == 10
