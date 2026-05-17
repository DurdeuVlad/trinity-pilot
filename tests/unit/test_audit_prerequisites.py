from trinity_pilot.audit import prerequisites
from trinity_pilot.audit.prerequisites import check_live_prerequisites


def test_prerequisite_multi_missing_result(tmp_path, monkeypatch):
    monkeypatch.setattr(prerequisites.sys, "platform", "linux")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(prerequisites, "_import_error", lambda module: "missing")

    result = check_live_prerequisites(tmp_path)

    assert result.passed is False
    codes = {issue.code for issue in result.missing}
    assert {"not_windows", "missing_gemini_api_key", "missing_pywinauto", "missing_pywin32", "missing_desktop_input_backend"} <= codes
    assert result.to_dict()["missing"]


def test_prerequisite_all_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(prerequisites.sys, "platform", "win32")
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("SESSIONNAME", "Console")
    monkeypatch.setattr(prerequisites, "_import_error", lambda module: None)

    result = check_live_prerequisites(tmp_path)

    assert result.passed is True
    assert result.missing == []


def test_prerequisite_allows_pywinauto_without_pyautogui(tmp_path, monkeypatch):
    monkeypatch.setattr(prerequisites.sys, "platform", "win32")
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("SESSIONNAME", "Console")
    monkeypatch.setattr(
        prerequisites,
        "_import_error",
        lambda module: "opencv abi mismatch" if module == "pyautogui" else None,
    )

    result = check_live_prerequisites(tmp_path)

    assert result.passed is True
    assert result.missing == []
    assert result.checks["desktop_input_backend"] is True
    assert result.checks["pyautogui"] is False
    assert [warning.code for warning in result.warnings] == ["pyautogui_unavailable"]
