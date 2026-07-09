"""Hard happy-path tests — multi-objective scenarios with 5-10 steps each.

Each scenario asserts a concrete Desktop artifact with required tokens to prove
end-to-end completion.

Run:
    pytest tests/e2e/test_gui_happy_path_hard.py -v --timeout=360
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.e2e._gui_driver import (
    AFTER_CONFIRM,
    AFTER_SUBMIT,
    DESKTOP,
    STATUS_CLARIF,
    STATUS_CONFIRM,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.desktop,
    pytest.mark.slow,
]


@dataclass(frozen=True)
class HardCase:
    case_id: str
    prompt: str
    artifact: Path
    must_have: tuple[str, ...]
    must_match: str | None = None


CASES: list[HardCase] = [
    HardCase(
        case_id="HH01",
        prompt=(
            "Complete this 6-objective workflow using terminal tools only: "
            f"1) Create folder {DESKTOP / 'hh01'}. "
            "2) Inside it create alpha.txt with text alpha-01 and beta.txt with text beta-01. "
            "3) List files in that folder. "
            "4) Compute total file count and total bytes. "
            f"5) Write {DESKTOP / 'hh01_summary.txt'} containing token HH01_OK and the labels 'file_count' and 'byte_count' with their values. "
            "6) Print the summary content."
        ),
        artifact=DESKTOP / "hh01_summary.txt",
        must_have=("HH01_OK", "file_count", "byte_count"),
    ),
    HardCase(
        case_id="HH02",
        prompt=(
            "Complete this 6-step workflow: "
            "1) Open a browser to https://example.com. "
            "2) Capture the page title. "
            f"3) Create {DESKTOP / 'hh02_webnote.txt'}. "
            "4) Write token HH02_OK plus the page title. "
            "5) Append the current date in YYYY-MM-DD. "
            "6) Print the file content in terminal."
        ),
        artifact=DESKTOP / "hh02_webnote.txt",
        must_have=("HH02_OK", "example"),
    ),
    HardCase(
        case_id="HH03",
        prompt=(
            "Complete this 7-objective workflow: "
            # httpbin.org/uuid is flaky (observed repeated 503s 2026-06-29) — httpbingo.org
            # is a more reliable Go rewrite of httpbin with the same {"uuid": "..."} response shape.
            "1) Open browser at https://httpbingo.org/uuid. "
            "2) Extract the UUID value. "
            f"3) Create {DESKTOP / 'hh03_uuid.txt'} with token HH03_OK and that UUID. "
            f"4) Create backup file {DESKTOP / 'hh03_uuid_backup.txt'}. "
            "5) Verify both files exist. "
            "6) Print both file paths. "
            "7) Print the UUID again."
        ),
        artifact=DESKTOP / "hh03_uuid.txt",
        must_have=("HH03_OK",),
        must_match=r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    ),
    HardCase(
        case_id="HH04",
        prompt=(
            "Complete this 6-objective terminal workflow: "
            f"1) Create {DESKTOP / 'hh04_numbers.csv'} with header n and values 3,7,11,19. "
            "2) Compute sum and average. "
            "3) Compute max and min. "
            f"4) Create {DESKTOP / 'hh04_metrics.txt'}. "
            "5) Write token HH04_OK plus sum, average, min, max. "
            "6) Print metrics file content."
        ),
        artifact=DESKTOP / "hh04_metrics.txt",
        must_have=("HH04_OK", "sum", "average", "min", "max"),
    ),
    HardCase(
        case_id="HH05",
        prompt=(
            "Complete this 5-objective workflow: "
            "1) List running python/python.exe processes. "
            "2) Count them. "
            f"3) Create {DESKTOP / 'hh05_process_report.txt'}. "
            "4) Write token HH05_OK, then a line 'process_count: <N>' (using that exact "
            "field name) where <N> is the count, then the first three process names. "
            "5) Print the report."
        ),
        artifact=DESKTOP / "hh05_process_report.txt",
        must_have=("HH05_OK", "process_count"),
    ),
    HardCase(
        case_id="HH06",
        prompt=(
            "Complete this 7-objective filesystem workflow: "
            f"1) Create folder {DESKTOP / 'hh06'} with subfolders one/two/three. "
            "2) Create one.txt two.txt three.txt in matching subfolders. "
            "3) Build a recursive tree listing. "
            "4) Count total files and folders under hh06. "
            f"5) Write {DESKTOP / 'hh06_tree_report.txt'} with token HH06_OK. "
            "6) Include file_count and folder_count. "
            "7) Print the report."
        ),
        artifact=DESKTOP / "hh06_tree_report.txt",
        must_have=("HH06_OK", "file_count", "folder_count"),
    ),
    HardCase(
        case_id="HH07",
        prompt=(
            "Complete this 6-objective system-info workflow: "
            "1) Capture hostname. "
            "2) Capture current user. "
            "3) Capture python version. "
            "4) Capture current time and unix epoch. "
            f"5) Write {DESKTOP / 'hh07_time_report.txt'} with token HH07_OK and all values. "
            "6) Print report content."
        ),
        artifact=DESKTOP / "hh07_time_report.txt",
        must_have=("HH07_OK", "hostname", "python"),
    ),
    HardCase(
        case_id="HH08",
        prompt=(
            "Complete this 7-step workflow: "
            "1) Open browser at https://docs.python.org/3/. "
            "2) Capture page title. "
            f"3) Create {DESKTOP / 'hh08_python_title.txt'}. "
            "4) Write token HH08_OK plus captured title. "
            "5) Append current date and time. "
            f"6) Duplicate to {DESKTOP / 'hh08_python_title_copy.txt'}. "
            "7) Print final file content."
        ),
        artifact=DESKTOP / "hh08_python_title.txt",
        # The real docs.python.org/3/ page title is "3.x.x Documentation" — it
        # doesn't literally contain "python", so check for what's actually there.
        must_have=("HH08_OK", "documentation"),
    ),
    HardCase(
        case_id="HH09",
        prompt=(
            "Complete this 8-objective data workflow: "
            f"1) Create {DESKTOP / 'hh09_input.json'} with keys app, version, env and items list [2,4,6,8]. "
            "2) Parse JSON. "
            "3) Compute list sum and average. "
            "4) Create normalized output text. "
            f"5) Write {DESKTOP / 'hh09_json_report.txt'} with token HH09_OK. "
            "6) Include sum and average fields. "
            "7) Include original version field. "
            "8) Print report content."
        ),
        artifact=DESKTOP / "hh09_json_report.txt",
        must_have=("HH09_OK", "sum", "average", "version"),
    ),
    HardCase(
        case_id="HH10",
        prompt=(
            "Complete this 10-objective end-to-end workflow: "
            f"1) Create folder {DESKTOP / 'hh10'}. "
            "2) Create a.txt with text alpha10. "
            "3) Create b.txt with text beta10. "
            "4) Create c.txt with text gamma10. "
            "5) Concatenate all three into merged.txt in same folder. "
            "6) Count merged line count and character count. "
            f"7) Create {DESKTOP / 'hh10_final_report.txt'}. "
            "8) Write token HH10_OK, then a line 'line_count: <N>' and a line "
            "'char_count: <N>' (using those exact field names). "
            "9) Include absolute path to merged.txt. "
            "10) Print final report content."
        ),
        artifact=DESKTOP / "hh10_final_report.txt",
        must_have=("HH10_OK", "line_count", "char_count", "merged.txt"),
    ),
]

_CLEAN_FILES = [
    DESKTOP / "hh01_summary.txt",
    DESKTOP / "hh02_webnote.txt",
    DESKTOP / "hh03_uuid.txt",
    DESKTOP / "hh03_uuid_backup.txt",
    DESKTOP / "hh04_numbers.csv",
    DESKTOP / "hh04_metrics.txt",
    DESKTOP / "hh05_process_report.txt",
    DESKTOP / "hh06_tree_report.txt",
    DESKTOP / "hh07_time_report.txt",
    DESKTOP / "hh08_python_title.txt",
    DESKTOP / "hh08_python_title_copy.txt",
    DESKTOP / "hh09_input.json",
    DESKTOP / "hh09_json_report.txt",
    DESKTOP / "hh10_final_report.txt",
]

_CLEAN_DIRS = [
    DESKTOP / "hh01",
    DESKTOP / "hh06",
    DESKTOP / "hh10",
]


@pytest.fixture(autouse=True)
def _cleanup_hard_happy_artifacts():
    for p in _CLEAN_FILES:
        p.unlink(missing_ok=True)
    for d in _CLEAN_DIRS:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    yield
    for p in _CLEAN_FILES:
        p.unlink(missing_ok=True)
    for d in _CLEAN_DIRS:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\x00", "").strip()


def _submit_and_confirm(app, prompt: str, plan_timeout: float = 100.0, run_timeout: float = 220.0) -> str:
    from tests.e2e._gui_driver import STATUS_READY

    app.submit(prompt)
    plan = app.wait_for(AFTER_SUBMIT, timeout=plan_timeout)
    if plan == STATUS_READY:
        # Status never left "Ready" — the prompt likely never actually reached
        # the input box (a flaky pywinauto/pyautogui submit race). Retry once
        # before treating this as a real failure.
        app.submit(prompt)
        plan = app.wait_for(AFTER_SUBMIT, timeout=plan_timeout)
    if plan == STATUS_CLARIF:
        pytest.skip("Agent requested clarification for this happy-path prompt")
    assert plan == STATUS_CONFIRM, f"Expected confirmation checkpoint, got {plan!r}"
    app.submit("yes")
    done = app.wait_for(AFTER_CONFIRM, timeout=run_timeout)
    assert done, "No terminal status observed after confirmation"
    return done


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_hard_happy_paths(case: HardCase, app):
    done = _submit_and_confirm(app, case.prompt)
    app.snap(f"{case.case_id}_done")
    app.dump_text(f"{case.case_id}_done")

    # "Failed" = pipeline ran, task beyond model capability — fair failure
    # "Error"  = framework/infrastructure exception — should not happen
    assert done.lower() != "error", f"{case.case_id} framework error (not task failure): {done!r}"
    assert done.lower() not in ("failed", "planning failed"), \
        f"{case.case_id} task not completed: {done!r}"

    assert case.artifact.exists(), f"{case.case_id} artifact missing: {case.artifact}"
    content = _read_text(case.artifact)
    assert content, f"{case.case_id} artifact is empty: {case.artifact}"

    lowered = content.lower()
    for token in case.must_have:
        # Tolerate natural-language label variants — space instead of underscore
        # (e.g. "File count:" for must_have token "file_count"), or no separator
        # at all (e.g. "FileCount=2", observed from a model that wrote a
        # CamelCase-style summary line). The assertion should check the data
        # was reported, not police exact field-name spelling.
        token_lower = token.lower()
        token_variants = (
            token_lower,
            token_lower.replace("_", " "),
            token_lower.replace("_", ""),
        )
        assert any(v in lowered for v in token_variants), (
            f"{case.case_id} missing token {token!r} in artifact: {content[:400]!r}"
        )

    if case.must_match:
        assert re.search(case.must_match, content), (
            f"{case.case_id} content did not match pattern {case.must_match!r}: "
            f"{content[:400]!r}"
        )
