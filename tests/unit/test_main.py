"""__main__.py CLI tests — subprocess invocation, no PySide6 needed."""
from __future__ import annotations

import subprocess
import sys


class TestMainCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "trinity_pilot", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "trinity-pilot" in result.stdout.lower() or "trinity_pilot" in result.stdout.lower()

    def test_version_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "trinity_pilot", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_version_output_contains_version_string(self):
        result = subprocess.run(
            [sys.executable, "-m", "trinity_pilot", "--version"],
            capture_output=True,
            text=True,
        )
        # argparse prints --version to stdout or stderr depending on Python version
        output = result.stdout + result.stderr
        assert "0.1.0" in output

    def test_help_mentions_worker_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "trinity_pilot", "--help"],
            capture_output=True,
            text=True,
        )
        assert "--worker" in result.stdout
