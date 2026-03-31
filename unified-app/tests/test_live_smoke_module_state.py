"""Regression tests for live smoke fixture module reloading."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_root_conftest_module():
    conftest_path = Path(__file__).resolve().parent / "conftest.py"
    spec = importlib.util.spec_from_file_location("unified_app_tests_conftest", conftest_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_purge_google_modules_removes_all_google_sdk_variants():
    """Live smoke unmocking must clear google.auth/google.api_core state too."""
    module = _load_root_conftest_module()
    injected = {
        "google": types.ModuleType("google"),
        "google.generativeai": types.ModuleType("google.generativeai"),
        "google.generativeai.client": types.ModuleType("google.generativeai.client"),
        "google.api_core": types.ModuleType("google.api_core"),
        "google.api_core.retry": types.ModuleType("google.api_core.retry"),
        "google.auth": types.ModuleType("google.auth"),
        "google.auth.transport": types.ModuleType("google.auth.transport"),
        "google.ai.generativelanguage_v1beta": types.ModuleType("google.ai.generativelanguage_v1beta"),
    }
    original = {}
    try:
        for name, fake_module in injected.items():
            original[name] = sys.modules.get(name)
            sys.modules[name] = fake_module

        module._purge_google_generativeai_modules()

        for name in injected:
            assert name not in sys.modules
    finally:
        for name in injected:
            sys.modules.pop(name, None)
            if original[name] is not None:
                sys.modules[name] = original[name]
