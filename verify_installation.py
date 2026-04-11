#!/usr/bin/env python3
"""
Installation verification script for TrinityPilot.
Run this after installation to verify all components are working.
"""
import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def check_python_version():
    """Verify Python version is 3.10+."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        return False, f"Python {version.major}.{version.minor} (need 3.10+)"
    return True, f"Python {version.major}.{version.minor}.{version.micro}"


def check_import(module_name, package_name=None):
    """Try to import a module and return success status."""
    try:
        __import__(module_name)
        return True, f"{package_name or module_name} installed"
    except ImportError as e:
        return False, f"{package_name or module_name} missing: {e}"


def check_file_exists(filepath):
    """Check if a file exists."""
    path = Path(filepath)
    if path.exists():
        return True, f"Found: {filepath}"
    return False, f"Missing: {filepath}"


def check_env_file():
    """Check if .env file exists and has API key."""
    env_path = REPO_ROOT / "unified-app" / ".env"
    if not env_path.exists():
        return False, "unified-app/.env not found (copy from .env.example)"

    content = env_path.read_text()
    if "GEMINI_API_KEY=" not in content:
        return False, "unified-app/.env exists but no GEMINI_API_KEY found"

    if "your_gemini_api_key_here" in content or "your_key" in content:
        return False, "unified-app/.env has placeholder API key (needs real key)"

    return True, "unified-app/.env configured with API key"


def check_trinity_bootstrap_import():
    """Verify the app bootstrap paths are sufficient for Trinity imports."""
    bootstrap_paths = (
        REPO_ROOT,
        REPO_ROOT / "api-accessibility-poc",
        REPO_ROOT / "browser-gui-automation",
        REPO_ROOT / "cli-automation-poc",
        REPO_ROOT / "audit-debugger" / "src",
    )
    for path in reversed(tuple(str(item.resolve()) for item in bootstrap_paths)):
        if path not in sys.path:
            sys.path.insert(0, path)

    try:
        importlib.import_module("trinity_core.trinity")
        return True, "trinity_core bootstrap import succeeded"
    except Exception as e:
        return False, f"trinity_core bootstrap import failed: {e}"


def main():
    print("=" * 60)
    print("TrinityPilot Installation Verification")
    print("=" * 60)
    print()

    checks = [
        ("Python Version", check_python_version),
        ("PyQt6", lambda: check_import("PyQt6")),
        ("Google GenAI", lambda: check_import("google.genai", "google-genai")),
        ("Playwright", lambda: check_import("playwright")),
        ("SQLAlchemy", lambda: check_import("sqlalchemy")),
        ("python-dotenv", lambda: check_import("dotenv", "python-dotenv")),
        (".env Configuration", check_env_file),
        ("unified-app/main.py", lambda: check_file_exists("unified-app/main.py")),
        ("trinity_core", lambda: check_file_exists("trinity_core/trinity.py")),
        ("Trinity bootstrap imports", check_trinity_bootstrap_import),
    ]

    results = []
    for name, check_func in checks:
        try:
            success, message = check_func()
            results.append((name, success, message))
        except Exception as e:
            results.append((name, False, f"Error: {e}"))

    max_name_len = max(len(name) for name, _, _ in results)

    for name, success, message in results:
        status = "[OK]" if success else "[X]"
        color = "\033[92m" if success else "\033[91m"
        reset = "\033[0m"
        print(f"{color}{status}{reset} {name:<{max_name_len}} : {message}")

    print()
    print("=" * 60)

    passed = sum(1 for _, success, _ in results if success)
    total = len(results)

    if passed == total:
        print(f"[OK] All checks passed ({passed}/{total})")
        print()
        print("Installation verified! Run the app with:")
        print("  cd unified-app")
        print("  python main.py")
        return 0

    print(f"[X] {total - passed} check(s) failed ({passed}/{total} passed)")
    print()
    print("Fix the issues above, then run this script again.")
    print("See QUICKSTART.md for installation instructions.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
