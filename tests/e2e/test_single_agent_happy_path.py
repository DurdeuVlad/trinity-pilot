"""Single-agent ablation happy-path tests — SA_T1 through SA_T20.

Same 20 scenarios as test_gui_happy_path.py but routed through SingleAgentEngine
directly — no Qt GUI, no AppDriver, no pywinauto. One ReAct loop, all domain tools.

Run:
    pytest tests/e2e/test_single_agent_happy_path.py -v --timeout=300
    pytest tests/e2e/test_single_agent_happy_path.py::test_SA_T14_terminal_sysinfo -v
"""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.e2e._gui_driver import DESKTOP
from trinity_pilot.config import Settings
from trinity_pilot.orchestrator.single_agent_engine import SingleAgentEngine

_SETTINGS: Settings | None = None


def _get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings.from_env()
    return _SETTINGS

pytestmark = [pytest.mark.e2e, pytest.mark.desktop, pytest.mark.slow]

# ---------------------------------------------------------------------------
# Artifact cleanup
# ---------------------------------------------------------------------------

_ARTIFACT_FILES = [
    DESKTOP / "tp_e2e.txt",
    DESKTOP / "cross_e2e.txt",
    DESKTOP / "disk_report.txt",
    DESKTOP / "date_note.txt",
    DESKTOP / "py_procs.txt",
    DESKTOP / "tp_source.txt",
    DESKTOP / "tp_source_copy.txt",
    DESKTOP / "sysinfo.txt",
    DESKTOP / "uuid_result.txt",
    DESKTOP / "python_version.txt",
    DESKTOP / "tp_script.py",
]

_ARTIFACT_DIRS = [
    DESKTOP / "tp_test_dir",
]


@pytest.fixture(autouse=True)
def _cleanup_artifacts():
    for p in _ARTIFACT_FILES:
        p.unlink(missing_ok=True)
    for d in _ARTIFACT_DIRS:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    yield
    for p in _ARTIFACT_FILES:
        p.unlink(missing_ok=True)
    for d in _ARTIFACT_DIRS:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def _read_artifact(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16').replace('\x00', '').strip()
    if len(raw) >= 4 and raw[1] == 0 and raw[3] == 0:
        return raw.decode('utf-16-le').replace('\x00', '').strip()
    return raw.decode('utf-8', errors='replace').replace('\x00', '').strip()


def _run_sa(prompt: str, *, timeout: float = 280.0) -> dict[str, Any]:
    """Run prompt through SingleAgentEngine. Returns result dict."""
    engine = SingleAgentEngine(_get_settings())
    return asyncio.run(
        asyncio.wait_for(engine.run(prompt), timeout=timeout)
    )


def _agent_summary(result: dict) -> str:
    """LLM's own summary text only — no evidence serialization."""
    return result.get("single_agent_summary") or ""


def _action_log(result: dict) -> list[str]:
    return result.get("evidence", {}).get("action_log", [])


def _used_tool(result: dict, prefix: str) -> bool:
    """True if any action_log entry starts with or contains prefix."""
    return any(prefix.lower() in entry.lower() for entry in _action_log(result))


def _passed(result: dict) -> bool:
    return result.get("status") == "completed"


# ---------------------------------------------------------------------------
# SA_T1 — Terminal: create a file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T1_terminal_create_file():
    result = _run_sa(
        "Create a file called tp_e2e.txt on the Desktop "
        "containing exactly the text 'hello-e2e'",
    )
    assert _passed(result), f"SA_T1 failed: {result.get('single_agent_summary')!r}"
    artifact = DESKTOP / "tp_e2e.txt"
    assert artifact.exists(), "tp_e2e.txt was not created on the Desktop"
    assert "hello-e2e" in _read_artifact(artifact)


# ---------------------------------------------------------------------------
# SA_T2 — Cross-domain: Notepad write then terminal read-back
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T2_cross_notepad_terminal():
    result = _run_sa(
        "Open Notepad, type the text 'e2e-cross-test', save the file as "
        "cross_e2e.txt on the Desktop, then use the terminal to read the file "
        "back and print its contents.",
    )
    assert _passed(result), f"SA_T2 failed: {result.get('single_agent_summary')!r}"
    artifact = DESKTOP / "cross_e2e.txt"
    assert artifact.exists(), "cross_e2e.txt was not created"
    assert "e2e-cross-test" in _read_artifact(artifact)


# ---------------------------------------------------------------------------
# SA_T3 — Browser: fetch page title
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T3_browser_fetch_title():
    result = _run_sa(
        "Open a browser, go to https://example.com, and tell me the page title.",
    )
    assert _passed(result), f"SA_T3 failed: {result.get('single_agent_summary')!r}"
    assert _used_tool(result, "navigate:"), "SA_T3: navigate tool not called"
    assert "example" in _agent_summary(result).lower(), (
        f"SA_T3: page title not in agent summary: {_agent_summary(result)[:400]}"
    )


# ---------------------------------------------------------------------------
# SA_T4 — Desktop: Windows Calculator 12x12
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T4_desktop_calculator():
    result = _run_sa(
        "Open the Windows Calculator, compute 12 multiplied by 12, "
        "and tell me the result.",
    )
    assert _passed(result), f"SA_T4 failed: {result.get('single_agent_summary')!r}"
    assert any("calc" in e.lower() for e in _action_log(result)), (
        f"SA_T4: Calculator not launched — action_log: {_action_log(result)}"
    )
    assert "144" in _agent_summary(result), (
        f"SA_T4: result '144' not in agent summary: {_agent_summary(result)[:400]}"
    )


# ---------------------------------------------------------------------------
# SA_T5 — Cross-domain: Notepad writes date, terminal reads back
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T5_cross_notepad_date_terminal_readback():
    import datetime
    today = datetime.date.today().strftime("%Y-%m-%d")
    result = _run_sa(
        f"Open Notepad and type the text '{today}'. "
        "Save the file as date_note.txt on the Desktop. "
        "Then use the terminal to read that file and print its contents in chat.",
    )
    assert _passed(result), f"SA_T5 failed: {result.get('single_agent_summary')!r}"
    artifact = DESKTOP / "date_note.txt"
    assert artifact.exists(), "date_note.txt was not created"
    assert today in _read_artifact(artifact)


# ---------------------------------------------------------------------------
# SA_T6 — Terminal: create folder with three files
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T6_terminal_create_folder_with_files():
    result = _run_sa(
        "Create a folder called tp_test_dir on the Desktop. "
        "Inside that folder create three empty files: a.txt, b.txt, and c.txt. "
        "Then list the contents of that folder in the terminal and print the result.",
    )
    assert _passed(result), f"SA_T6 failed: {result.get('single_agent_summary')!r}"
    folder = DESKTOP / "tp_test_dir"
    assert folder.is_dir(), "tp_test_dir was not created on the Desktop"
    created = {f.name for f in folder.iterdir()}
    for name in ("a.txt", "b.txt", "c.txt"):
        assert name in created, f"Expected {name} inside tp_test_dir; found: {created}"


# ---------------------------------------------------------------------------
# SA_T7 — Terminal: disk usage report
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T7_terminal_disk_report():
    result = _run_sa(
        "Check the disk usage of the C: drive using the terminal. "
        "Write a one-line summary of the total and free space to a file called "
        "disk_report.txt on the Desktop.",
    )
    assert _passed(result), f"SA_T7 failed: {result.get('single_agent_summary')!r}"
    artifact = DESKTOP / "disk_report.txt"
    assert artifact.exists(), "disk_report.txt was not created"
    content = _read_artifact(artifact)
    assert content, "disk_report.txt is empty"
    assert re.search(r"\d", content), f"disk_report.txt contains no numeric data: {content!r}"


# ---------------------------------------------------------------------------
# SA_T8 — Browser: httpbin origin
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T8_browser_httpbin_origin():
    result = _run_sa(
        "Open a browser and navigate to https://httpbin.org/get. "
        "Find the value of the 'origin' field in the JSON response and say it in chat.",
    )
    assert _passed(result), f"SA_T8 failed: {result.get('single_agent_summary')!r}"
    assert _used_tool(result, "navigate:"), "SA_T8: navigate tool not called"
    text = _agent_summary(result)
    assert re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", text), (
        f"SA_T8: Expected IP address in agent summary; got: {text[:400]}"
    )


# ---------------------------------------------------------------------------
# SA_T9 — Terminal: count running Python processes
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T9_terminal_count_python_procs():
    result = _run_sa(
        "Use the terminal to list all running processes named 'python' or 'python.exe'. "
        "Count them and write the count as a single number to a file called "
        "py_procs.txt on the Desktop.",
    )
    assert _passed(result), f"SA_T9 failed: {result.get('single_agent_summary')!r}"
    artifact = DESKTOP / "py_procs.txt"
    assert artifact.exists(), "py_procs.txt was not created"
    assert re.search(r"\d+", _read_artifact(artifact))


# ---------------------------------------------------------------------------
# SA_T10 — Desktop: Calculator addition 1024+768
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T10_desktop_calculator_addition():
    result = _run_sa(
        "Open the Windows Calculator, compute 1024 plus 768, and tell me the result.",
    )
    assert _passed(result), f"SA_T10 failed: {result.get('single_agent_summary')!r}"
    assert any("calc" in e.lower() for e in _action_log(result)), (
        f"SA_T10: Calculator not launched — action_log: {_action_log(result)}"
    )
    assert "1792" in _agent_summary(result), (
        f"SA_T10: result '1792' not in agent summary: {_agent_summary(result)[:400]}"
    )


# ---------------------------------------------------------------------------
# SA_T11 — Terminal: copy a file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T11_terminal_copy_file():
    result = _run_sa(
        "Using the terminal: create a file called tp_source.txt on the Desktop "
        "containing the text 'copy-source'. Then copy that file to a new file "
        "called tp_source_copy.txt on the Desktop.",
    )
    assert _passed(result), f"SA_T11 failed: {result.get('single_agent_summary')!r}"
    src = DESKTOP / "tp_source.txt"
    dst = DESKTOP / "tp_source_copy.txt"
    assert src.exists(), "tp_source.txt not created"
    assert dst.exists(), "tp_source_copy.txt not created"
    assert "copy-source" in _read_artifact(dst)


# ---------------------------------------------------------------------------
# SA_T12 — Terminal: write and execute a Python script
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T12_terminal_write_and_run_script():
    result = _run_sa(
        "Using the terminal: create a Python script called tp_script.py on the Desktop. "
        "The script should print exactly the text 'tp-hello'. "
        "Run the script and tell me what it printed.",
    )
    assert _passed(result), f"SA_T12 failed: {result.get('single_agent_summary')!r}"
    stdout = result.get("evidence", {}).get("stdout", "")
    assert "tp-hello" in _agent_summary(result) or "tp-hello" in stdout, (
        f"SA_T12: 'tp-hello' not in agent summary or stdout\n"
        f"  summary: {_agent_summary(result)[:300]}\n"
        f"  stdout:  {stdout[:300]}"
    )


# ---------------------------------------------------------------------------
# SA_T13 — Browser: extract first quote from quotes.toscrape.com
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T13_browser_scrape_quote():
    result = _run_sa(
        "Open a browser and go to https://quotes.toscrape.com. "
        "Read the first quote displayed on the page and say it in chat.",
    )
    assert _passed(result), f"SA_T13 failed: {result.get('single_agent_summary')!r}"
    assert _used_tool(result, "navigate:"), "SA_T13: navigate tool not called"
    text = _agent_summary(result)
    words = [w for w in text.split() if len(w) > 3]
    assert len(words) >= 10, (
        f"SA_T13: agent summary too short to contain a real quote: {text[:400]}"
    )


# ---------------------------------------------------------------------------
# SA_T14 — Terminal: system info to file  [smoke test — fastest scenario]
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T14_terminal_sysinfo():
    result = _run_sa(
        "Using the terminal, get the computer's hostname and the Windows OS version. "
        "Write a single-line summary containing both values to a file called "
        "sysinfo.txt on the Desktop.",
    )
    assert _passed(result), f"SA_T14 failed: {result.get('single_agent_summary')!r}"
    artifact = DESKTOP / "sysinfo.txt"
    assert artifact.exists(), "sysinfo.txt was not created"
    content = _read_artifact(artifact)
    assert content, "sysinfo.txt is empty"
    assert re.search(r"[A-Za-z0-9]", content), f"sysinfo.txt contains no usable data: {content!r}"


# ---------------------------------------------------------------------------
# SA_T15 — Browser: Wikipedia page title
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T15_browser_wikipedia_title():
    result = _run_sa(
        "Open a browser and go to "
        "https://en.wikipedia.org/wiki/Python_(programming_language). "
        "Tell me the exact title of the page.",
    )
    assert _passed(result), f"SA_T15 failed: {result.get('single_agent_summary')!r}"
    assert _used_tool(result, "navigate:"), "SA_T15: navigate tool not called"
    summary = _agent_summary(result).lower()
    assert "python" in summary and ("programming" in summary or "wikipedia" in summary), (
        f"SA_T15: page title not reported in agent summary: {_agent_summary(result)[:400]}"
    )


# ---------------------------------------------------------------------------
# SA_T16 — Terminal: count .txt files on Desktop
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T16_terminal_count_txt_files():
    result = _run_sa(
        "Use the terminal to count how many .txt files are currently on the Desktop. "
        "Report the exact number in chat.",
    )
    assert _passed(result), f"SA_T16 failed: {result.get('single_agent_summary')!r}"
    assert _used_tool(result, "run_command:"), "SA_T16: run_command tool not called"
    text = _agent_summary(result)
    assert re.search(r"\b\d+\b", text), f"SA_T16: No number in agent summary: {text[:400]}"


# ---------------------------------------------------------------------------
# SA_T17 — Desktop: open Paint and close it
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T17_desktop_open_paint():
    result = _run_sa(
        "Open the Windows Paint application. "
        "Once it is open, close it without saving anything. "
        "Confirm in chat that Paint was opened and closed.",
    )
    assert _passed(result), f"SA_T17 failed: {result.get('single_agent_summary')!r}"
    assert any("paint" in e.lower() for e in _action_log(result)), (
        f"SA_T17: Paint not launched — action_log: {_action_log(result)}"
    )
    text = _agent_summary(result).lower()
    assert "paint" in text, f"SA_T17: 'paint' not mentioned in agent summary: {text[:300]}"


# ---------------------------------------------------------------------------
# SA_T18 — Cross: browser fetches UUID, terminal writes to file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T18_cross_browser_uuid_to_file():
    result = _run_sa(
        "Open a browser and go to https://httpbin.org/uuid. "
        "Read the 'uuid' value from the JSON response. "
        "Then use the terminal to write that UUID value to a file called "
        "uuid_result.txt on the Desktop.",
        timeout=280.0,
    )
    assert _passed(result), f"SA_T18 failed: {result.get('single_agent_summary')!r}"
    artifact = DESKTOP / "uuid_result.txt"
    assert artifact.exists(), "uuid_result.txt was not created"
    content = _read_artifact(artifact)
    assert re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        content, re.IGNORECASE,
    ), f"uuid_result.txt does not contain a valid UUID: {content!r}"


# ---------------------------------------------------------------------------
# SA_T19 — Terminal: Python version to file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T19_terminal_python_version():
    result = _run_sa(
        "Use the terminal to check the Python version installed on this machine. "
        "Write the full version string to a file called python_version.txt on the Desktop.",
    )
    assert _passed(result), f"SA_T19 failed: {result.get('single_agent_summary')!r}"
    artifact = DESKTOP / "python_version.txt"
    assert artifact.exists(), "python_version.txt was not created"
    assert re.search(r"\d+\.\d+", _read_artifact(artifact))


# ---------------------------------------------------------------------------
# SA_T20 — Terminal: disk free space in chat
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SA_T20_terminal_disk_info_in_chat():
    """Report C: disk free space directly in chat (no file write)."""
    result = _run_sa(
        "Use the terminal to check how much free disk space is available on C: "
        "and report the number in chat.",
    )
    assert _passed(result), f"SA_T20 failed: {result.get('single_agent_summary')!r}"
    assert _used_tool(result, "run_command:"), "SA_T20: run_command tool not called"
    text = _agent_summary(result)
    assert re.search(r"\d+", text), f"SA_T20: No number in agent summary: {text[:400]}"
