"""Shared deterministic postcondition verification utilities."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any, Iterable

from .models import ExecutionLog, TaskInput, VerificationCheck, VerificationEnvelope

_SUCCESS_STATUSES = {"success", "done", "completed"}
_TRANSIENT_MARKERS = (
    "selector not found",
    "element not visible",
    "element detached",
    "window_not_found",
    "window not found",
    "attach_timeout",
    "launch_timeout",
    "health check timed out",
    "page interaction timed out",
    "execution context was destroyed",
    "still loading",
    "not yet visible",
    "not yet ready",
    "loading",
    "starting up",
)


def build_failure_verification(*, module: str, error: str, evidence: dict[str, Any] | None = None) -> VerificationEnvelope:
    summary = (error or f"{module} execution failed").strip()
    if _looks_transient(summary):
        return VerificationEnvelope(
            status="unknown",
            checks=[],
            summary=summary,
            evidence={"module": module, **(evidence or {})},
            review_required=True,
            source="none",
        )
    return VerificationEnvelope(
        status="failure",
        checks=[],
        summary=summary,
        evidence={"module": module, **(evidence or {})},
        review_required=False,
        source="none",
    )


def build_verification(
    *,
    task: TaskInput,
    module: str,
    backend_result: dict[str, Any],
    task_status: str,
    execution_log: Iterable[ExecutionLog | dict[str, Any]],
    output_text: str | None = None,
) -> VerificationEnvelope:
    evidence = _collect_evidence(
        module=module,
        backend_result=backend_result,
        execution_log=execution_log,
        output_text=output_text,
        task=task,
    )
    explicit_checks = _load_explicit_checks(task)
    evaluated_explicit = _evaluate_checks(explicit_checks, evidence)
    fallback_checks = _build_fallback_checks(
        module=module,
        task=task,
        backend_result=backend_result,
        evidence=evidence,
        execution_log=execution_log,
    )
    evaluated_fallback = _evaluate_checks(fallback_checks, evidence)

    checks = evaluated_explicit + evaluated_fallback
    explicit_present = bool(explicit_checks)
    fallback_present = bool(fallback_checks)
    source = (
        "mixed" if explicit_present and fallback_present else
        "executor" if explicit_present else
        "fallback" if fallback_present else
        "none"
    )

    status = _decide_status(
        module=module,
        task_status=task_status,
        backend_result=backend_result,
        evidence=evidence,
        checks=checks,
        explicit_present=explicit_present,
    )
    summary = _build_summary(status=status, module=module, checks=checks, evidence=evidence, task_status=task_status)
    return VerificationEnvelope(
        status=status,
        checks=checks,
        summary=summary,
        evidence=evidence,
        review_required=status == "unknown",
        source=source,
    )


def coerce_verification(value: Any) -> VerificationEnvelope | None:
    if isinstance(value, VerificationEnvelope):
        return value
    if isinstance(value, dict) and value:
        try:
            return VerificationEnvelope.model_validate(value)
        except Exception:
            return None
    return None


def _load_explicit_checks(task: TaskInput) -> list[VerificationCheck]:
    checks = list(getattr(task, "verification_checks", []) or [])
    if checks:
        return [item if isinstance(item, VerificationCheck) else VerificationCheck.model_validate(item) for item in checks]
    raw_context_checks = (task.context or {}).get("verification_checks", [])
    loaded: list[VerificationCheck] = []
    if isinstance(raw_context_checks, list):
        for item in raw_context_checks:
            try:
                loaded.append(item if isinstance(item, VerificationCheck) else VerificationCheck.model_validate(item))
            except Exception:
                continue
    return loaded


def _collect_evidence(
    *,
    module: str,
    backend_result: dict[str, Any],
    execution_log: Iterable[ExecutionLog | dict[str, Any]],
    output_text: str | None,
    task: TaskInput,
) -> dict[str, Any]:
    entries = [_as_log_dict(entry) for entry in execution_log]
    stdout_snippets = [
        str(entry.get("details") or "")
        for entry in entries
        if str(entry.get("result") or "").strip().lower() == "success" and str(entry.get("details") or "").strip()
    ]
    combined_text = "\n".join(
        part.strip()
        for part in (
            str(backend_result.get("extracted_text") or ""),
            "\n".join(stdout_snippets),
        )
        if str(part).strip()
    )
    plan_state = backend_result.get("plan_state", {})
    metadata = backend_result.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    execution_cwd = _first_non_empty(
        metadata.get("cwd"),
        metadata.get("working_directory"),
        metadata.get("execution_cwd"),
        backend_result.get("cwd"),
        backend_result.get("working_directory"),
        (task.context or {}).get("cwd"),
        (task.context or {}).get("working_directory"),
    )
    extracted_text = str(backend_result.get("extracted_text") or "")
    successful_actions = sum(1 for entry in entries if str(entry.get("result") or "").strip().lower() == "success")
    total_actions = len(entries)
    evidence: dict[str, Any] = {
        "module": module,
        "task_description": task.description,
        "expected_outcome": task.expected_outcome,
        "combined_text": combined_text,
        "model_text": str(output_text or ""),
        "extracted_text": extracted_text,
        "plan_state": plan_state if isinstance(plan_state, dict) else {},
        "current_url": str(backend_result.get("current_url") or ""),
        "page_title": str(backend_result.get("page_title") or ""),
        "verification_status": str(backend_result.get("verification_status") or ""),
        "successful_actions": int(backend_result.get("successful_actions") or successful_actions) if str(backend_result.get("successful_actions", "")).strip() else successful_actions,
        "total_actions": int(backend_result.get("total_actions") or total_actions) if str(backend_result.get("total_actions", "")).strip() else total_actions,
        "app_context": str(
            metadata.get("app_context")
            or metadata.get("app")
            or metadata.get("app_name")
            or backend_result.get("app_context")
            or (task.context or {}).get("app_name")
            or ""
        ),
        "active_window": str(
            metadata.get("active_window")
            or backend_result.get("active_window")
            or metadata.get("window_title")
            or metadata.get("title")
            or backend_result.get("window_title")
            or ""
        ),
        "observed_text": str(metadata.get("text") or ""),
        "exit_codes": [entry.get("exit_code") for entry in entries if entry.get("exit_code") is not None],
        "execution_log_results": [str(entry.get("result") or "") for entry in entries],
        "elements": backend_result.get("elements") if isinstance(backend_result.get("elements"), dict) else {},
        "artifact_count": len(backend_result.get("artifacts") or []),
        "execution_cwd": execution_cwd,
    }
    return evidence


def _build_fallback_checks(
    *,
    module: str,
    task: TaskInput,
    backend_result: dict[str, Any],
    evidence: dict[str, Any],
    execution_log: Iterable[ExecutionLog | dict[str, Any]],
) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    if module == "browser":
        extracted = str(backend_result.get("extracted_text") or "")
        if extracted and task.expected_outcome:
            checks.append(
                VerificationCheck(
                    kind="text_contains",
                    target="combined_text",
                    expected=_pick_text_probe(task.expected_outcome),
                )
            )
    elif module == "cli":
        entries = [_as_log_dict(entry) for entry in execution_log]
        exit_codes = [entry.get("exit_code") for entry in entries if entry.get("exit_code") is not None]
        if exit_codes:
            checks.append(
                VerificationCheck(
                    kind="command_exit_code",
                    target="latest_command",
                    expected=0,
                )
            )
        file_target = _extract_file_target(task.expected_outcome or task.description)
        if file_target:
            checks.append(
                VerificationCheck(
                    kind="file_exists",
                    target=file_target,
                    expected=True,
                )
            )
    return checks


def _evaluate_checks(checks: list[VerificationCheck], evidence: dict[str, Any]) -> list[VerificationCheck]:
    evaluated: list[VerificationCheck] = []
    for check in checks:
        evaluated.append(_evaluate_check(check, evidence))
    return evaluated


def _evaluate_check(check: VerificationCheck, evidence: dict[str, Any]) -> VerificationCheck:
    kind = str(check.kind or "").strip().lower()
    target = str(check.target or "").strip()
    expected = check.expected
    actual: Any = None
    status = "unknown"
    message = check.message or ""

    if kind == "url_equals":
        actual = evidence.get("current_url") or ""
        status = "success" if actual == expected else "failure" if actual else "unknown"
    elif kind == "url_matches":
        actual = evidence.get("current_url") or ""
        if actual:
            status = "success" if _urls_match(actual, expected) else "failure"
    elif kind == "url_contains":
        actual = evidence.get("current_url") or ""
        expected_text = str(expected or "")
        if actual:
            status = "success" if expected_text.lower() in str(actual).lower() else "failure"
    elif kind == "text_contains":
        actual = evidence.get("combined_text") or ""
        expected_text = str(expected or "")
        if actual:
            status = "success" if expected_text.lower() in str(actual).lower() else "failure"
    elif kind == "text_absent":
        actual = evidence.get("combined_text") or ""
        expected_text = str(expected or "")
        if actual:
            status = "success" if expected_text.lower() not in str(actual).lower() else "failure"
    elif kind in {"element_exists", "element_visible"}:
        actual = (evidence.get("elements") or {}).get(target)
        if isinstance(actual, dict):
            actual = bool(actual.get("visible") if kind == "element_visible" else actual.get("exists", True))
        if isinstance(actual, bool):
            status = "success" if actual is bool(expected) else "failure"
    elif kind == "window_exists":
        actual_window = str(evidence.get("active_window") or "")
        actual = actual_window
        if actual_window:
            expected_text = target or str(expected or "")
            status = "success" if expected_text.lower() in actual_window.lower() else "failure"
    elif kind == "process_running":
        actual = _is_process_running(target)
        status = "success" if actual is bool(expected) else "failure"
    elif kind == "file_exists":
        actual = os.path.exists(_resolve_file_target(target, evidence))
        status = "success" if actual is bool(expected) else "failure"
    elif kind == "command_exit_code":
        exit_codes = evidence.get("exit_codes") or []
        actual = exit_codes[-1] if exit_codes else None
        if actual is not None:
            status = "success" if actual == expected else "failure"
    elif kind == "visible_tool_execution":
        actual = int(evidence.get("successful_actions") or 0)
        status = "success" if actual > 0 else "failure"
    if not message:
        message = _default_check_message(kind=kind, status=status, target=target, expected=expected, actual=actual)
    return check.model_copy(update={"actual": actual, "status": status, "message": message})


def _decide_status(
    *,
    module: str,
    task_status: str,
    backend_result: dict[str, Any],
    evidence: dict[str, Any],
    checks: list[VerificationCheck],
    explicit_present: bool,
) -> str:
    task_status = str(task_status or "").strip().lower()
    verification_status = str(evidence.get("verification_status") or "").strip().lower()
    plan_complete = None
    failed_checks = [check for check in checks if check.status == "failure"]
    unknown_checks = [check for check in checks if check.status == "unknown"]
    success_checks = [check for check in checks if check.status == "success"]
    substantive_success_checks = [check for check in success_checks if check.kind != "visible_tool_execution"]

    if task_status == "failure":
        failure_blob = " ".join(
            part for part in (
                str(backend_result.get("error") or ""),
                str(backend_result.get("reason") or ""),
                str(evidence.get("combined_text") or ""),
            )
            if part
        )
        return "unknown" if _looks_transient(failure_blob) else "failure"

    if verification_status == "failure":
        return "failure"
    if verification_status == "unknown":
        return "unknown"
    if verification_status == "success":
        if explicit_present and failed_checks:
            return "failure"
        if plan_complete is False and not explicit_present:
            return "unknown"
        return "success"

    if explicit_present:
        if failed_checks:
            return "failure"
        if unknown_checks:
            return "unknown"
        if substantive_success_checks:
            return "success"

    if module == "cli":
        if failed_checks:
            return "failure"
        if evidence.get("exit_codes"):
            if all(code == 0 for code in evidence["exit_codes"]):
                return "success" if (plan_complete is not False) else "unknown"
            return "failure"
        if plan_complete:
            return "success"
        if substantive_success_checks:
            return "success"
        return "unknown"

    if module == "desktop":
        if failed_checks:
            return "failure"
        if _has_desktop_evidence(evidence):
            return "success" if (plan_complete is not False) else "unknown"
        if substantive_success_checks:
            return "success"
        return "unknown"

    if module == "browser":
        if failed_checks:
            return "failure"
        if plan_complete and _has_browser_evidence(evidence):
            return "success"
        if _has_browser_evidence(evidence):
            return "success"
        return "unknown"

    if failed_checks:
        return "failure"
    if unknown_checks:
        return "unknown"
    if substantive_success_checks:
        return "success"
    
    # Generic success fallback for unknown domains if tool execution passed
    if success_checks and any(c.kind == "visible_tool_execution" for c in success_checks):
        return "success"
        
    return "not_requested"


def _build_summary(
    *,
    status: str,
    module: str,
    checks: list[VerificationCheck],
    evidence: dict[str, Any],
    task_status: str,
) -> str:
    if status == "success":
        if checks:
            passed = [check.kind for check in checks if check.status == "success"]
            return f"{module} verification passed via {', '.join(passed[:3])}."
        return f"{module} execution succeeded with stable backend evidence."
    if status == "failure":
        failures = [check.message for check in checks if check.status == "failure" and check.message]
        if failures:
            return failures[0]
        return f"{module} execution is inconsistent with the expected postcondition."
    if status == "unknown":
        if str(task_status or "").strip().lower() == "failure" and _looks_transient(str(evidence.get('combined_text') or "")):
            return f"{module} execution may still be settling; deterministic verification is inconclusive."
        return f"{module} execution needs reviewer confirmation because deterministic evidence is incomplete."
    return f"{module} verification was not requested."


def _as_log_dict(entry: ExecutionLog | dict[str, Any]) -> dict[str, Any]:
    if isinstance(entry, dict):
        return dict(entry)
    return entry.model_dump() if hasattr(entry, "model_dump") else {
        "turn": getattr(entry, "turn", None),
        "action": getattr(entry, "action", None),
        "result": getattr(entry, "result", None),
        "details": getattr(entry, "details", None),
        "timestamp": getattr(entry, "timestamp", None),
        "exit_code": getattr(entry, "exit_code", None),
    }


def _default_check_message(*, kind: str, status: str, target: str, expected: Any, actual: Any) -> str:
    if status == "success":
        return f"{kind} passed for {target or 'target'}."
    if status == "failure":
        return f"{kind} expected {expected!r} but observed {actual!r}."
    return f"{kind} could not be verified from available evidence."


def _looks_transient(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return any(marker in normalized for marker in _TRANSIENT_MARKERS)


def _urls_match(actual: Any, expected: Any) -> bool:
    actual_normalized = _normalize_url(actual)
    expected_normalized = _normalize_url(expected)
    if not actual_normalized or not expected_normalized:
        return False
    return (
        actual_normalized == expected_normalized
        or actual_normalized.startswith(expected_normalized.rstrip("/"))
        or expected_normalized.startswith(actual_normalized.rstrip("/"))
    )

def _has_browser_evidence(evidence: dict[str, Any]) -> bool:
    return any(
        [
            str(evidence.get("current_url") or "").strip(),
            str(evidence.get("page_title") or "").strip(),
            str(evidence.get("extracted_text") or "").strip(),
            bool(evidence.get("elements") or {}),
            int(evidence.get("artifact_count") or 0) > 0,
        ]
    )


def _has_desktop_evidence(evidence: dict[str, Any]) -> bool:
    return any(
        [
            str(evidence.get("active_window") or "").strip(),
            str(evidence.get("app_context") or "").strip(),
            str(evidence.get("observed_text") or "").strip(),
            bool(evidence.get("elements") or {}),
        ]
    )


def _normalize_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    host = (parts.netloc or "").lower()
    path = re.sub(r"/+", "/", parts.path or "/").rstrip("/")
    if not path:
        path = "/"
    query = parts.query
    normalized = f"{host}{path}"
    if query:
        normalized = f"{normalized}?{query}"
    return normalized


def _pick_text_probe(text: str) -> str:
    match = re.search(r"'([^']+)'|\"([^\"]+)\"", text or "")
    if match:
        return next(group for group in match.groups() if group)
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if len(normalized) <= 80:
        return normalized
    return normalized[:80]


def _extract_file_target(text: str) -> str | None:
    match = re.search(r"([A-Za-z]:\\\\[^\s]+|\.{0,2}[\\/][^\s]+|[A-Za-z0-9_.-]+[\\/][^\s]+)", text or "")
    if not match:
        return None
    return match.group(1).strip("`'\".,;:")


def _resolve_file_target(target: str, evidence: dict[str, Any]) -> str:
    raw = str(target or "").strip().strip("`'\"")
    if not raw or os.path.isabs(raw):
        return raw
    cwd = str(evidence.get("execution_cwd") or "").strip()
    if not cwd:
        return raw
    return str(Path(cwd) / raw)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _is_process_running(process_name: str) -> bool | None:
    process_name = str(process_name or "").strip()
    if not process_name:
        return None
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    output = (completed.stdout or "").lower()
    return process_name.lower() in output
