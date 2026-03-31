"""Regression checks for requirements-package file references and test commands."""

from __future__ import annotations

import re
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parent

REQUIREMENTS_DOCS = [
    MODULE_ROOT / "docs" / "requirements" / "README.md",
    MODULE_ROOT / "docs" / "requirements" / "traceability-matrix.md",
    MODULE_ROOT / "docs" / "requirements" / "07-quality" / "test-strategy.md",
    MODULE_ROOT / "docs" / "requirements" / "07-quality" / "automated-testing-guide.md",
    MODULE_ROOT / "docs" / "requirements" / "07-quality" / "quality-metrics.md",
]

PATH_TOKEN_RE = re.compile(r"`([^`\n]+)`")
PYTEST_CMD_RE = re.compile(r"pytest\s+([^\n]+)")


def _path_candidates(base_dir: Path, token: str) -> list[Path]:
    cleaned = token.strip().split("::", 1)[0].split("(", 1)[0].strip()
    if not cleaned:
        return []
    if cleaned.startswith(("http://", "https://", "-")):
        return []
    if " " in cleaned and "/" not in cleaned:
        return []
    if not any(marker in cleaned for marker in ("/", ".py", ".md", ".nsi", ".spec", ".ps1")):
        return []
    return [base_dir / cleaned, MODULE_ROOT / cleaned, REPO_ROOT / cleaned]


def test_requirements_docs_reference_real_paths() -> None:
    """Backticked path references in the requirements package should resolve."""
    missing: list[str] = []

    for doc in REQUIREMENTS_DOCS:
        text = doc.read_text(encoding="utf-8")
        for token in PATH_TOKEN_RE.findall(text):
            if any(prefix in token for prefix in ("pytest ", "set ", "python ")):
                continue
            candidates = _path_candidates(doc.parent, token)
            if not candidates:
                continue
            if not any(candidate.exists() for candidate in candidates):
                missing.append(f"{doc.relative_to(MODULE_ROOT)} -> {token}")

    assert not missing, "Stale requirements doc paths:\n" + "\n".join(sorted(missing))


def test_requirements_docs_only_reference_existing_pytest_targets() -> None:
    """Every pytest target documented in the requirements package should exist."""
    missing: list[str] = []

    for doc in REQUIREMENTS_DOCS:
        text = doc.read_text(encoding="utf-8")
        for command_args in PYTEST_CMD_RE.findall(text):
            for token in command_args.split():
                if token.startswith("-") or not token.startswith("unified-app/tests/"):
                    continue
                target = REPO_ROOT / token
                if not target.exists():
                    missing.append(f"{doc.relative_to(MODULE_ROOT)} -> {token}")

    assert not missing, "Stale pytest targets in requirements docs:\n" + "\n".join(sorted(missing))


def test_requirements_readme_reports_actual_markdown_count() -> None:
    """The requirements index should report the actual number of markdown files."""
    readme = MODULE_ROOT / "docs" / "requirements" / "README.md"
    markdown_files = sorted((MODULE_ROOT / "docs" / "requirements").rglob("*.md"))
    expected_line = f"**Total Documents:** {len(markdown_files)}"
    assert expected_line in readme.read_text(encoding="utf-8")
