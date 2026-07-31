"""Ensure the old workflow engine imports do not survive in the codebase."""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent / "trinity_pilot"
TESTS_ROOT = Path(__file__).parent.parent


def _grep_py(pattern: str, root: Path) -> list[str]:
    matches = []
    for f in root.rglob("*.py"):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            if re.search(pattern, content):
                matches.append(str(f))
        except Exception:
            pass
    return matches


def test_no_temporalio_in_source():
    """AC-1.3: grep finds zero old workflow-engine imports in trinity_pilot/"""
    matches = _grep_py(r"^\s*(?:import\s+temporalio|from\s+temporalio\b)", PROJECT_ROOT)
    assert matches == [], f"temporalio found in source files: {matches}"


def test_no_temporalio_in_tests():
    """AC-6.3: grep finds zero old workflow-engine imports in tests/"""
    matches = _grep_py(r"^\s*(?:import\s+temporalio|from\s+temporalio\b)", TESTS_ROOT)
    assert matches == [], f"temporalio found in test files: {matches}"


def test_import_orchestrator_without_temporalio():
    """AC-6.2: import succeeds without temporalio installed"""
    import trinity_pilot.config  # noqa: F401
    assert "temporalio" not in sys.modules, "temporalio must not be in sys.modules"
