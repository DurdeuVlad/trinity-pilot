"""Regression tests for adapter import boundaries."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_import_probe(module_name: str) -> dict:
    """Import a module in a child process and report whether sys.path changed."""
    script = f"""
import json
import sys

before = list(sys.path)
__import__("{module_name}")
after = list(sys.path)

print(json.dumps({{
    "module": "{module_name}",
    "sys_path_changed": before != after,
    "before_len": len(before),
    "after_len": len(after),
}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip())


def test_adapter_imports_do_not_mutate_sys_path() -> None:
    """Production adapter imports must not rewrite sys.path."""
    results = [
        _run_import_probe("trinity_core.adapters.browser"),
        _run_import_probe("trinity_core.adapters.cli"),
        _run_import_probe("trinity_core.adapters.desktop"),
    ]

    assert all(not result["sys_path_changed"] for result in results), results
