from __future__ import annotations

import tomllib
from pathlib import Path


def test_windows_desktop_dependencies_are_runtime_dependencies() -> None:
    project_file = Path(__file__).parents[2] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))

    dependencies = project["project"]["dependencies"]
    assert any(
        dependency.startswith("pywinauto") and "sys_platform == 'win32'" in dependency
        for dependency in dependencies
    )
    assert any(
        dependency.startswith("pywin32") and "sys_platform == 'win32'" in dependency
        for dependency in dependencies
    )
    assert "windows" not in project["project"].get("optional-dependencies", {})
