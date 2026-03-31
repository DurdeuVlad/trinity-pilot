from __future__ import annotations

from types import ModuleType, SimpleNamespace

from tests import conftest as root_conftest


def test_purge_google_generativeai_modules_removes_only_targeted_entries(monkeypatch):
    monkeypatch.setitem(root_conftest.sys.modules, "google", ModuleType("google"))
    monkeypatch.setitem(root_conftest.sys.modules, "google.generativeai", ModuleType("google.generativeai"))
    monkeypatch.setitem(
        root_conftest.sys.modules,
        "google.generativeai.client",
        ModuleType("google.generativeai.client"),
    )
    monkeypatch.setitem(root_conftest.sys.modules, "google.api_core", ModuleType("google.api_core"))
    monkeypatch.setitem(
        root_conftest.sys.modules,
        "google.api_core.exceptions",
        ModuleType("google.api_core.exceptions"),
    )
    monkeypatch.setitem(root_conftest.sys.modules, "unrelated.module", ModuleType("unrelated.module"))

    root_conftest._purge_google_generativeai_modules()

    assert "google" not in root_conftest.sys.modules
    assert "google.generativeai" not in root_conftest.sys.modules
    assert "google.generativeai.client" not in root_conftest.sys.modules
    assert "google.api_core" not in root_conftest.sys.modules
    assert "google.api_core.exceptions" not in root_conftest.sys.modules
    assert "unrelated.module" in root_conftest.sys.modules


def test_reload_loaded_modules_only_reloads_present_entries(monkeypatch):
    reloaded: list[str] = []
    monkeypatch.setattr(
        root_conftest,
        "_RELOAD_MODULES",
        ("orchestrator.macro_planner", "cli_planner", "missing.module"),
    )
    loaded = {
        "orchestrator.macro_planner": ModuleType("orchestrator.macro_planner"),
        "cli_planner": ModuleType("cli_planner"),
    }

    for module_name, module in loaded.items():
        monkeypatch.setitem(root_conftest.sys.modules, module_name, module)

    monkeypatch.setattr(
        root_conftest.importlib,
        "reload",
        lambda module: reloaded.append(module.__name__) or module,
    )

    root_conftest._reload_loaded_modules()

    assert reloaded == ["orchestrator.macro_planner", "cli_planner"]


def test_configure_live_gemini_module_state_is_noop_for_non_live_modules():
    request = SimpleNamespace(module=SimpleNamespace(__file__="tests/test_regular_module.py"))

    fixture = root_conftest.configure_live_gemini_module_state.__wrapped__
    generator = fixture(request)

    assert next(generator) is None

    try:
        next(generator)
    except StopIteration:
        pass
    else:
        raise AssertionError("Fixture generator should stop cleanly for non-live modules")


def test_configure_live_gemini_module_state_switches_for_live_smoke_module(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv("LIVE_GEMINI_SMOKE", "1")
    request = SimpleNamespace(
        module=SimpleNamespace(__file__=str(root_conftest.REPO_ROOT / "unified-app" / "tests" / "integration" / "test_live_cli_smoke.py"))
    )

    monkeypatch.setattr(root_conftest, "deactivate", lambda: calls.append("deactivate"))
    monkeypatch.setattr(root_conftest, "_purge_google_generativeai_modules", lambda: calls.append("purge"))
    monkeypatch.setattr(root_conftest, "_reload_loaded_modules", lambda: calls.append("reload"))
    monkeypatch.setattr(root_conftest, "activate", lambda backend: calls.append(type(backend).__name__))

    fixture = root_conftest.configure_live_gemini_module_state.__wrapped__
    generator = fixture(request)

    assert next(generator) is None
    assert calls == ["deactivate", "purge", "reload"]

    try:
        next(generator)
    except StopIteration:
        pass
    else:
        raise AssertionError("Fixture generator should stop after teardown")

    assert calls == ["deactivate", "purge", "reload", "QueueBackend", "reload"]
