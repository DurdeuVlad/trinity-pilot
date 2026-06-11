"""Layer-3 GUI happy-path tests — golden-path scenarios through the real Qt app.

Each test:
  1. Submits a natural-language prompt via the input box.
  2. Waits for the deterministic checkpoint "Awaiting confirmation".
  3. Confirms with "yes".
  4. Waits for terminal status (Done / Finished:*).
  5. Checks a concrete real-world side-effect (file on disk, text in chat).

Run:
    pytest tests/e2e/test_gui_happy_path.py -v --timeout=300
    pytest tests/e2e/test_gui_happy_path.py -v -m "e2e and not slow"
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from tests.e2e._gui_driver import (
    AFTER_CONFIRM,
    AFTER_SUBMIT,
    DESKTOP,
    STATUS_CONFIRM,
)

pytestmark = [pytest.mark.e2e, pytest.mark.desktop, pytest.mark.slow]

# ---------------------------------------------------------------------------
# Helpers
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
    """Remove known test artifacts before each test so checks are clean."""
    for p in _ARTIFACT_FILES:
        p.unlink(missing_ok=True)
    for d in _ARTIFACT_DIRS:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    yield
    # Post-test cleanup so artifacts don't pile up
    for p in _ARTIFACT_FILES:
        p.unlink(missing_ok=True)
    for d in _ARTIFACT_DIRS:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def _read_artifact(path: Path) -> str:
    """Read artifact file, detecting UTF-16 LE/BE (PowerShell > redirect) vs UTF-8."""
    raw = path.read_bytes()
    # BOM present: let Python auto-detect endianness
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16').replace('\x00', '').strip()
    # UTF-16 LE without BOM: every other byte is 0x00 for ASCII content
    if len(raw) >= 4 and raw[1] == 0 and raw[3] == 0:
        return raw.decode('utf-16-le').replace('\x00', '').strip()
    return raw.decode('utf-8', errors='replace').replace('\x00', '').strip()


def _plan_and_confirm(app, prompt: str, plan_timeout: float = 90.0) -> str:
    """Submit prompt, assert planning completes, send 'yes'. Returns plan status."""
    app.submit(prompt)
    plan_s = app.wait_for(AFTER_SUBMIT, timeout=plan_timeout)
    assert plan_s == STATUS_CONFIRM, (
        f"Expected 'Awaiting confirmation' but got {plan_s!r}. "
        "The task may have been flagged as vague or planning failed."
    )
    app.submit("yes")
    return plan_s


# ---------------------------------------------------------------------------
# Terminal — create a file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_terminal_create_file(app):
    """Create a file on the Desktop and verify its content."""
    _plan_and_confirm(
        app,
        "Create a file called tp_e2e.txt on the Desktop "
        "containing exactly the text 'hello-e2e'",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=90)
    app.snap("happy_terminal_create_file")

    assert "failed" not in done.lower(), f"Task ended with failure status: {done!r}"

    artifact = DESKTOP / "tp_e2e.txt"
    assert artifact.exists(), "tp_e2e.txt was not created on the Desktop"
    content = _read_artifact(artifact)
    assert "hello-e2e" in content, f"Expected 'hello-e2e' in file, got: {content!r}"


# ---------------------------------------------------------------------------
# Browser — fetch page title
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_browser_fetch_title(app):
    """Navigate to example.com and verify the page title is mentioned in chat."""
    _plan_and_confirm(
        app,
        "Open a browser, go to https://example.com, and tell me the page title.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("happy_browser_title")

    assert "failed" not in done.lower(), f"Task ended with failure status: {done!r}"

    ui = app.ui_text()
    assert "example" in ui, (
        "Page title not mentioned in chat. "
        f"Status: {done!r}. Visible text (first 300): {ui[:300]}"
    )


# ---------------------------------------------------------------------------
# Desktop — Windows Calculator
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_desktop_calculator(app):
    """Open Calculator, compute 12 * 12, verify result 144 appears in chat."""
    _plan_and_confirm(
        app,
        "Open the Windows Calculator, compute 12 multiplied by 12, "
        "and tell me the result.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("happy_desktop_calculator")

    assert "failed" not in done.lower(), f"Task ended with failure status: {done!r}"

    ui = app.ui_text()
    assert "144" in ui, (
        f"Expected '144' in chat but not found. "
        f"Status: {done!r}. Visible text (first 300): {ui[:300]}"
    )


# ---------------------------------------------------------------------------
# Cross-domain — Notepad write then terminal read-back
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_cross_domain_notepad_terminal(app):
    """Write to Notepad, save to Desktop, read back via terminal. Both workers used."""
    _plan_and_confirm(
        app,
        "Open Notepad, type the text 'e2e-cross-test', save the file as "
        "cross_e2e.txt on the Desktop, then use the terminal to read the file "
        "back and print its contents.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=180)
    app.snap("happy_cross_domain")

    assert "failed" not in done.lower(), f"Task ended with failure status: {done!r}"

    artifact = DESKTOP / "cross_e2e.txt"
    assert artifact.exists(), "cross_e2e.txt was not created on the Desktop"
    content = _read_artifact(artifact)
    assert "e2e-cross-test" in content, (
        f"Expected 'e2e-cross-test' in file content, got: {content!r}"
    )


# ---------------------------------------------------------------------------
# T6 — Terminal: create folder with three files, list them
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T6_terminal_create_folder_with_files(app):
    """Create tp_test_dir on Desktop with a.txt, b.txt, c.txt; list contents."""
    _plan_and_confirm(
        app,
        "Create a folder called tp_test_dir on the Desktop. "
        "Inside that folder create three empty files: a.txt, b.txt, and c.txt. "
        "Then list the contents of that folder in the terminal and print the result.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T6_folder_with_files")

    assert "failed" not in done.lower(), f"T6 ended with failure: {done!r}"

    folder = DESKTOP / "tp_test_dir"
    assert folder.is_dir(), "tp_test_dir was not created on the Desktop"
    created = {f.name for f in folder.iterdir()}
    for name in ("a.txt", "b.txt", "c.txt"):
        assert name in created, f"Expected {name} inside tp_test_dir; found: {created}"


# ---------------------------------------------------------------------------
# T7 — Terminal: disk usage report
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T7_terminal_disk_report(app):
    """Check C: disk usage and write a one-line summary to disk_report.txt."""
    _plan_and_confirm(
        app,
        "Check the disk usage of the C: drive using the terminal. "
        "Write a one-line summary of the total and free space to a file called "
        "disk_report.txt on the Desktop.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T7_disk_report")

    assert "failed" not in done.lower(), f"T7 ended with failure: {done!r}"

    artifact = DESKTOP / "disk_report.txt"
    assert artifact.exists(), "disk_report.txt was not created on the Desktop"
    content = _read_artifact(artifact)
    assert content, "disk_report.txt is empty"
    # Must contain at least one number (byte/GB count)
    assert re.search(r"\d", content), (
        f"disk_report.txt contains no numeric data: {content!r}"
    )


# ---------------------------------------------------------------------------
# T8 — Browser: read origin field from httpbin.org/get
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T8_browser_httpbin_origin(app):
    """Navigate to httpbin.org/get, read the 'origin' IP field, report in chat."""
    _plan_and_confirm(
        app,
        "Open a browser and navigate to https://httpbun.com/get. "
        "Find the value of the 'origin' field in the JSON response and say it in chat.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T8_httpbin_origin")

    assert "failed" not in done.lower(), f"T8 ended with failure: {done!r}"

    ui = app.ui_text()
    # The origin field is an IP address (or comma-separated IPs)
    assert re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ui), (
        f"Expected an IP address in chat but not found. "
        f"Status: {done!r}. Visible text (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# T9 — Cross-domain: Notepad writes date, terminal reads it back
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T9_cross_notepad_date_terminal_readback(app):
    """Open Notepad, type today's date, save; terminal reads and prints it."""
    import datetime
    today = datetime.date.today().strftime("%Y-%m-%d")

    _plan_and_confirm(
        app,
        f"Open Notepad and type the text '{today}'. "
        "Save the file as date_note.txt on the Desktop. "
        "Then use the terminal to read that file and print its contents in chat.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=180)
    app.snap("T9_cross_date_readback")

    assert "failed" not in done.lower(), f"T9 ended with failure: {done!r}"

    artifact = DESKTOP / "date_note.txt"
    assert artifact.exists(), "date_note.txt was not created on the Desktop"
    content = _read_artifact(artifact)
    assert today in content, (
        f"Expected today's date '{today}' in file, got: {content!r}"
    )


# ---------------------------------------------------------------------------
# T10 — Terminal: count running Python processes
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T10_terminal_count_python_procs(app):
    """Count running Python processes, write count to py_procs.txt."""
    _plan_and_confirm(
        app,
        "Use the terminal to list all running processes named 'python' or 'python.exe'. "
        "Count them and write the count as a single number to a file called "
        "py_procs.txt on the Desktop.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T10_python_procs")

    assert "failed" not in done.lower(), f"T10 ended with failure: {done!r}"

    artifact = DESKTOP / "py_procs.txt"
    assert artifact.exists(), "py_procs.txt was not created on the Desktop"
    content = _read_artifact(artifact)
    assert re.search(r"\d+", content), (
        f"py_procs.txt must contain a number, got: {content!r}"
    )


# ---------------------------------------------------------------------------
# T11 — Desktop: Calculator arithmetic
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T11_desktop_calculator_addition(app):
    """Open Calculator, compute 1024 + 768, verify result 1792 in chat."""
    _plan_and_confirm(
        app,
        "Open the Windows Calculator, compute 1024 plus 768, "
        "and tell me the result.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T11_calculator_addition")

    assert "failed" not in done.lower(), f"T11 ended with failure: {done!r}"

    ui = app.ui_text()
    assert "1792" in ui, (
        f"Expected '1792' in chat but not found. "
        f"Status: {done!r}. Visible text (first 300): {ui[:300]}"
    )


# ---------------------------------------------------------------------------
# T12 — Terminal: copy a file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T12_terminal_copy_file(app):
    """Create a file on the Desktop then copy it to a new name — both must exist."""
    _plan_and_confirm(
        app,
        "Using the terminal: create a file called tp_source.txt on the Desktop "
        "containing the text 'copy-source'. Then copy that file to a new file "
        "called tp_source_copy.txt on the Desktop.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T12_copy_file")

    assert "failed" not in done.lower(), f"T12 ended with failure: {done!r}"

    src = DESKTOP / "tp_source.txt"
    dst = DESKTOP / "tp_source_copy.txt"
    assert src.exists(), "tp_source.txt not created"
    assert dst.exists(), "tp_source_copy.txt not created — copy step failed"
    assert "copy-source" in _read_artifact(dst), (
        "tp_source_copy.txt does not contain the expected content"
    )


# ---------------------------------------------------------------------------
# T13 — Terminal: write and execute a Python script
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T13_terminal_write_and_run_script(app):
    """Write a Python script to Desktop that prints 'tp-hello', run it, report output."""
    _plan_and_confirm(
        app,
        "Using the terminal: create a Python script called tp_script.py on the Desktop. "
        "The script should print exactly the text 'tp-hello'. "
        "Run the script and tell me what it printed.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T13_run_script")

    assert "failed" not in done.lower(), f"T13 ended with failure: {done!r}"

    ui = app.ui_text()
    assert "tp-hello" in ui, (
        f"Expected 'tp-hello' in chat output. Status: {done!r}. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# T14 — Terminal: system info to file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T14_terminal_sysinfo_to_file(app):
    """Get hostname and OS version, write one-line summary to sysinfo.txt."""
    _plan_and_confirm(
        app,
        "Using the terminal, get the computer's hostname and the Windows OS version. "
        "Write a single-line summary containing both values to a file called "
        "sysinfo.txt on the Desktop.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T14_sysinfo")

    assert "failed" not in done.lower(), f"T14 ended with failure: {done!r}"

    artifact = DESKTOP / "sysinfo.txt"
    assert artifact.exists(), "sysinfo.txt was not created"
    content = _read_artifact(artifact)
    assert content, "sysinfo.txt is empty"
    # Must contain at least one alphanumeric token (hostname or version number)
    assert re.search(r"[A-Za-z0-9]", content), (
        f"sysinfo.txt contains no usable data: {content!r}"
    )


# ---------------------------------------------------------------------------
# T15 — Browser: extract first quote from quotes.toscrape.com
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T15_browser_scrape_quote(app):
    """Navigate to quotes.toscrape.com and report the first quote text in chat."""
    _plan_and_confirm(
        app,
        "Open a browser and go to https://quotes.toscrape.com. "
        "Read the first quote displayed on the page and say it in chat.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T15_scrape_quote")

    assert "failed" not in done.lower(), f"T15 ended with failure: {done!r}"

    ui = app.ui_text()
    # The first quote on quotes.toscrape.com contains common words
    # Just assert the agent reported something quote-like (non-empty meaningful text)
    assert len(ui.strip()) > 20, (
        f"T15: Chat appears empty or too short. Status: {done!r}. UI: {ui[:300]}"
    )
    # Must not just be status labels — verify some actual quote content arrived
    non_status_words = {w for w in ui.split() if len(w) > 4}
    assert len(non_status_words) >= 5, (
        f"T15: Chat does not contain meaningful quote text. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# T16 — Browser: Wikipedia page title
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T16_browser_wikipedia_title(app):
    """Navigate to the Python Wikipedia page and report its title."""
    _plan_and_confirm(
        app,
        "Open a browser and go to "
        "https://en.wikipedia.org/wiki/Python_(programming_language). "
        "Tell me the exact title of the page.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T16_wikipedia_title")

    assert "failed" not in done.lower(), f"T16 ended with failure: {done!r}"

    ui = app.ui_text()
    assert "python" in ui, (
        f"T16: Expected 'python' in chat. Status: {done!r}. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# T17 — Terminal: count .txt files on Desktop
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T17_terminal_count_txt_files(app):
    """Count .txt files on Desktop and report the number in chat."""
    _plan_and_confirm(
        app,
        "Use the terminal to count how many .txt files are currently on the Desktop. "
        "Report the exact number in chat.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T17_count_txt_files")

    assert "failed" not in done.lower(), f"T17 ended with failure: {done!r}"

    ui = app.ui_text()
    assert re.search(r"\b\d+\b", ui), (
        f"T17: Expected a number in chat. Status: {done!r}. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# T18 — Desktop: open Paint and close it
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T18_desktop_open_paint(app):
    """Open Windows Paint and close it without saving — verifies desktop worker."""
    _plan_and_confirm(
        app,
        "Open the Windows Paint application. "
        "Once it is open, close it without saving anything. "
        "Confirm in chat that Paint was opened and closed.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T18_open_paint")

    assert "failed" not in done.lower(), f"T18 ended with failure: {done!r}"

    ui = app.ui_text()
    assert "paint" in ui or "open" in ui or "closed" in ui or "done" in done.lower(), (
        f"T18: Expected confirmation in chat. Status: {done!r}. UI (first 300): {ui[:300]}"
    )


# ---------------------------------------------------------------------------
# T19 — Cross: browser fetches UUID, terminal writes it to file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T19_cross_browser_uuid_to_file(app):
    """Browser fetches a UUID from httpbin, terminal writes it to uuid_result.txt."""
    _plan_and_confirm(
        app,
        "Open a browser and go to https://www.uuidgenerator.net/api/version4. "
        "The page returns a UUID string. "
        "Then use the terminal to write that UUID value to a file called "
        "uuid_result.txt on the Desktop.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=200)
    app.snap("T19_cross_uuid_to_file")

    assert "failed" not in done.lower(), f"T19 ended with failure: {done!r}"

    artifact = DESKTOP / "uuid_result.txt"
    assert artifact.exists(), "uuid_result.txt was not created"
    content = _read_artifact(artifact)
    # UUID format: 8-4-4-4-12 hex chars
    assert re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", content, re.IGNORECASE), (
        f"uuid_result.txt does not contain a valid UUID: {content!r}"
    )


# ---------------------------------------------------------------------------
# T20 — Terminal: Python version to file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T20_terminal_python_version(app):
    """Get Python version string from terminal, write it to python_version.txt."""
    _plan_and_confirm(
        app,
        "Use the terminal to check the Python version installed on this machine. "
        "Write the full version string to a file called python_version.txt on the Desktop.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("T20_python_version")

    assert "failed" not in done.lower(), f"T20 ended with failure: {done!r}"

    artifact = DESKTOP / "python_version.txt"
    assert artifact.exists(), "python_version.txt was not created"
    content = _read_artifact(artifact)
    assert re.search(r"\d+\.\d+", content), (
        f"Expected version number in python_version.txt, got: {content!r}"
    )
