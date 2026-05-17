from __future__ import annotations

import importlib
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class PrerequisiteIssue:
    code: str
    message: str
    detail: str = ""


@dataclass
class PrerequisiteResult:
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    missing: list[PrerequisiteIssue] = field(default_factory=list)
    warnings: list[PrerequisiteIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _import_error(module: str) -> str | None:
    if module in {"pyautogui", "pywinauto", "win32gui"}:
        completed = subprocess.run(
            [sys.executable, "-c", f"import {module}; print('ok')"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0:
            return (completed.stderr or completed.stdout or f"import {module} failed").strip()[:2000]
        if completed.stderr.strip():
            return completed.stderr.strip()[:2000]
        return None
    try:
        importlib.import_module(module)
        return None
    except BaseException as exc:  # noqa: BLE001 - prerequisite probes must catch ABI/import crashes.
        return str(exc)


def _interactive_desktop() -> bool:
    if sys.platform != "win32":
        return False
    return bool(os.environ.get("SESSIONNAME") or os.environ.get("USERNAME"))


def check_live_prerequisites(output_root: str | Path = ".audit-runs") -> PrerequisiteResult:
    checks: dict[str, bool] = {}
    missing: list[PrerequisiteIssue] = []
    warnings: list[PrerequisiteIssue] = []

    checks["windows"] = sys.platform == "win32"
    if not checks["windows"]:
        missing.append(PrerequisiteIssue("not_windows", "Live desktop audit requires Windows", sys.platform))

    checks["interactive_desktop"] = _interactive_desktop()
    if not checks["interactive_desktop"]:
        missing.append(PrerequisiteIssue("no_interactive_desktop", "No interactive Windows desktop session detected"))

    checks["gemini_api_key"] = bool(os.getenv("GEMINI_API_KEY"))
    if not checks["gemini_api_key"]:
        missing.append(PrerequisiteIssue("missing_gemini_api_key", "GEMINI_API_KEY is not set"))

    import_errors: dict[str, str | None] = {}
    for name, module in {
        "pywinauto": "pywinauto",
        "pyautogui": "pyautogui",
        "pywin32": "win32gui",
    }.items():
        error = _import_error(module)
        import_errors[name] = error
        checks[name] = error is None
        if name in {"pywinauto", "pywin32"} and not checks[name]:
            missing.append(PrerequisiteIssue(f"missing_{name}", f"Python module is not importable: {module}", error or "unknown import error"))

    checks["desktop_input_backend"] = checks["pywinauto"] or checks["pyautogui"]
    if not checks["desktop_input_backend"]:
        missing.append(
            PrerequisiteIssue(
                "missing_desktop_input_backend",
                "No desktop input backend is importable: pywinauto and pyautogui both failed",
                f"pywinauto={import_errors.get('pywinauto') or 'ok'}; pyautogui={import_errors.get('pyautogui') or 'ok'}",
            )
        )
    elif not checks["pyautogui"]:
        missing_detail = import_errors.get("pyautogui") or "unknown import error"
        result_warning = PrerequisiteIssue(
            "pyautogui_unavailable",
            "PyAutoGUI is unavailable; live audit will use pywinauto keyboard/UIA path",
            missing_detail,
        )
        checks["pyautogui_fallback_available"] = False
        warnings.append(result_warning)

    try:
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks["writable_output_root"] = True
    except OSError as exc:
        checks["writable_output_root"] = False
        missing.append(PrerequisiteIssue("output_root_not_writable", "Audit output root is not writable", str(exc)))

    return PrerequisiteResult(passed=not missing, checks=checks, missing=missing, warnings=warnings)
