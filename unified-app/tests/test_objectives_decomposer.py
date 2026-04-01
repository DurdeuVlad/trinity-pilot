from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.objectives_decomposer import _deterministic_objectives


def test_python_file_listing_prompt_stays_single_and_deterministic():
    objectives = _deterministic_objectives("List all Python files in the current working directory")

    assert objectives == ["List all Python files in the current working directory"]
