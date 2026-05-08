"""CLI entry point tests — __main__.py usable without PySide6."""
import subprocess
import sys


class TestCliEntry:
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
        assert "0.1.0" in result.stdout or "0.1.0" in result.stderr

    def test_import_main_module_no_crash(self):
        """__main__.py must import without pulling in PySide6 at module level."""
        result = subprocess.run(
            [sys.executable, "-c", "import trinity_pilot.__main__"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
