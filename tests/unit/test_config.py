"""Config unit tests — Settings validation."""
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
        assert s.temporal_host == "localhost:7233"
        assert s.db_path == "trinity_pilot.db"

    def test_from_env_respects_overrides(self):
        env = {
            "GEMINI_API_KEY": "my-key",
            "GEMINI_PLANNER_MODEL": "gemini-2.0-pro",
            "TEMPORAL_HOST": "myhost:7233",
            "DB_PATH": "/tmp/test.db",
        }
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_env()
        assert s.gemini_planner_model == "gemini-2.0-pro"
        assert s.temporal_host == "myhost:7233"
        assert s.db_path == "/tmp/test.db"

    def test_config_error_is_exception(self):
        assert issubclass(ConfigError, Exception)

    def test_validate_raises_on_empty_temporal_namespace(self):
        s = Settings(gemini_api_key="key", temporal_namespace="")
        with pytest.raises(ConfigError, match="TEMPORAL_NAMESPACE"):
            s.validate()

    def test_validate_raises_on_empty_temporal_host(self):
        s = Settings(gemini_api_key="key", temporal_host="")
        with pytest.raises(ConfigError, match="TEMPORAL_HOST"):
            s.validate()

    def test_from_env_loads_dotenv_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("GEMINI_API_KEY=dotenv-loaded-key\n")
            # Clear env so only .env supplies the key
            with patch.dict(os.environ, {}, clear=True):
                s = Settings.from_env(dotenv_path=str(env_file))
            assert s.gemini_api_key == "dotenv-loaded-key"
