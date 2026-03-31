from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_UNIFIED = REPO_ROOT / "unified-app"
for _p in (str(REPO_ROOT), str(_UNIFIED)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from orchestrator.objectives_decomposer import (  # noqa: E402
    ObjectivesDecomposer,
    _PROJECT_PYTHON_FILES_OBJECTIVE,
    _PRODUCTIVITY_GUIDANCE_OBJECTIVE,
)


class _UnexpectedProviderCall:
    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        raise AssertionError("The deterministic ambiguity guard should bypass the provider")


class _StaticProvider:
    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        return json.dumps(
            {
                "objectives": [
                    "List the Python files in the project",
                    "Identify one useful Python file to inspect next",
                ]
            }
        )


@pytest.mark.asyncio
async def test_decompose_uses_safe_guidance_objective_for_vague_productivity_request() -> None:
    decomposer = ObjectivesDecomposer(_UnexpectedProviderCall())

    objectives = await decomposer.decompose("Help me work faster on my computer")

    assert objectives == [_PRODUCTIVITY_GUIDANCE_OBJECTIVE]


@pytest.mark.asyncio
async def test_decompose_uses_deterministic_python_file_listing_for_ambiguous_project_request() -> None:
    decomposer = ObjectivesDecomposer(_UnexpectedProviderCall())

    objectives = await decomposer.decompose("Do something useful with the Python files in this project")

    assert objectives == [_PROJECT_PYTHON_FILES_OBJECTIVE]


@pytest.mark.asyncio
async def test_decompose_keeps_more_specific_python_file_requests_on_normal_planning_path() -> None:
    decomposer = ObjectivesDecomposer(_StaticProvider())

    objectives = await decomposer.decompose("Review the Python files in this project and identify one useful file to inspect next")

    assert objectives == [
        "List the Python files in the project",
        "Identify one useful Python file to inspect next",
    ]


@pytest.mark.asyncio
async def test_decompose_keeps_simple_builtin_app_launch_as_single_direct_objective() -> None:
    decomposer = ObjectivesDecomposer(_UnexpectedProviderCall())

    objectives = await decomposer.decompose("Open the Windows Calculator application")

    assert objectives == ["Open the Windows Calculator application"]


@pytest.mark.asyncio
async def test_decompose_keeps_app_version_query_as_single_direct_objective() -> None:
    decomposer = ObjectivesDecomposer(_UnexpectedProviderCall())

    objectives = await decomposer.decompose(
        "Open an application called 'NonExistentApp_XYZ123456' and tell me its version number"
    )

    assert objectives == [
        "Open an application called 'NonExistentApp_XYZ123456' and tell me its version number"
    ]


@pytest.mark.asyncio
async def test_decompose_splits_python_version_then_app_open_mixed_prompt() -> None:
    decomposer = ObjectivesDecomposer(_UnexpectedProviderCall())

    objectives = await decomposer.decompose(
        "First run 'python --version' in the CLI to get the Python version, then open an application called 'InvalidSoftware_ABCDEF' that does not exist"
    )

    assert objectives == [
        "python --version",
        "Open an application called 'InvalidSoftware_ABCDEF'",
    ]
