"""
Live runner for the 9 domain scenarios.

Executes each scenario directly through TrinityBridge (no Qt, no mocks).
Prints a per-scenario result line and a final summary table.

Usage:
    python tests/run_live_domain_scenarios.py

Requires GEMINI_API_KEY in .env or the environment.
Timeout: 120 s per scenario.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen
from typing import Any, Optional

# Path setup — mirrors conftest.py logic
# __file__ = trinity-pilot/unified-app/tests/run_live_domain_scenarios.py
# parents[2] = trinity-pilot/   (contains trinity_core, cli-automation-poc siblings, etc.)
_REPO_ROOT = Path(__file__).resolve().parents[2]   # trinity-pilot/
_UNIFIED_APP = Path(__file__).resolve().parents[1]  # unified-app/

for _p in [
    str(_REPO_ROOT),
    str(_REPO_ROOT.parent / "cli-automation-poc"),
    str(_REPO_ROOT.parent / "api-accessibility-poc"),
    str(_REPO_ROOT.parent / "browser-gui-automation"),
    str(_REPO_ROOT.parent / "audit-debugger" / "src"),
    str(_UNIFIED_APP),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv(_UNIFIED_APP / ".env", override=False)
load_dotenv(_REPO_ROOT / ".env", override=False)

from orchestrator.trinity_bridge import TrinityBridge  # noqa: E402

TIMEOUT_S = 120
RUN_ID = time.strftime("%Y%m%d-%H%M%S")
RESULTS_DIR = _UNIFIED_APP / "_runtime" / "live_domain_scenarios" / RUN_ID

# ---------------------------------------------------------------------------
# Scenario registry (mirrors test_domain_scenarios.py, no ABC dependency)
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    name: str
    description: str
    domain: str
    target_server: Optional[str]
    approved_plan: list[str]
    difficulty: str   # easy | moderate | complex
    category: str     # cli | web | desktop | cross
    verification_checks: list[dict[str, Any]] = field(default_factory=list)


SCENARIOS: list[Scenario] = [
    # --- CLI -----------------------------------------------------------------
    Scenario(
        name="TestCliEasyRunHealthCheck",
        difficulty="easy",
        category="cli",
        description="Check whether the Python interpreter is available and report its version",
        domain="cli",
        target_server="cli_mcp",
        approved_plan=[
            "Run 'python --version' and capture the output",
        ],
    ),
    Scenario(
        name="TestCliModerateOrganizeDownloads",
        difficulty="moderate",
        category="cli",
        description=(
            "Organize the sandboxed downloads folder at "
            "_runtime/domain_scenarios/cli_moderate_downloads/inbox by file type, "
            "then write a manifest of the files that were moved"
        ),
        domain="cli",
        target_server="cli_mcp",
        approved_plan=[
            "Inspect _runtime/domain_scenarios/cli_moderate_downloads/inbox and list every file with its extension",
            "Create documents, images, installers, and archives folders under _runtime/domain_scenarios/cli_moderate_downloads/organized",
            "Move only .pdf, .docx, and .txt files to documents; .png and .jpg files to images; .exe and .msi files to installers; .zip files to archives; leave .tmp and extensionless files in inbox",
            "Write _runtime/domain_scenarios/cli_moderate_downloads/organized/manifest.txt with the moved file names grouped by destination, skipped file names, and Total moved: 8",
        ],
    ),
    # --- Web -----------------------------------------------------------------
    Scenario(
        name="TestWebEasyNavigateToDocumentation",
        difficulty="easy",
        category="web",
        description="Open the Python documentation homepage",
        domain="web",
        target_server="browser_mcp",
        approved_plan=[
            "Navigate to docs.python.org and confirm the page loaded",
        ],
    ),
    Scenario(
        name="TestWebModerateSearchAndExtract",
        difficulty="moderate",
        category="web",
        description=(
            "Search GitHub for the top Python async libraries, "
            "filter by star count, and extract the top 3 names and descriptions"
        ),
        domain="web",
        target_server="browser_mcp",
        approved_plan=[
            "Navigate to github.com/search?q=python+async&type=repositories",
            "Sort results by star count descending",
            "Extract the repository name, description, and star count for the first 3 results",
            "Verify each result is a Python repository before reporting",
        ],
    ),
    # --- Desktop -------------------------------------------------------------
    Scenario(
        name="TestDesktopEasyOpenApplication",
        difficulty="easy",
        category="desktop",
        description="Open Notepad",
        domain="desktop",
        target_server="desktop_mcp",
        approved_plan=[
            "Click the Start menu and launch Notepad",
        ],
    ),
    Scenario(
        name="TestDesktopModerateCreateFormattedNote",
        difficulty="moderate",
        category="desktop",
        description=(
            "Create a meeting notes template in Notepad with sections for "
            "attendees, agenda, and action items, then save it to the Desktop"
        ),
        domain="desktop",
        target_server="desktop_mcp",
        approved_plan=[
            "Open Notepad",
            "Type the document header: 'Meeting Notes - [Date]'",
            "Add three sections: Attendees, Agenda, Action Items with placeholder lines",
            "Save the file as meeting_notes_template.txt on the Desktop",
        ],
    ),
    # --- Cross-domain --------------------------------------------------------
    Scenario(
        name="TestCrossDomainEasyWebResearchAndSave",
        difficulty="easy",
        category="cross",
        description=(
            "Look up the latest Python version on python.org "
            "and save the version number to a local text file"
        ),
        domain="mixed",
        target_server=None,
        approved_plan=[
            "Navigate to python.org/downloads and find the latest stable release version number",
            "Create a file latest_python_version.txt in the current working directory",
            "Write the version number into the file",
            "Confirm the file exists and print its contents",
        ],
    ),
    Scenario(
        name="TestCrossDomainModerateResearchAndDraft",
        difficulty="moderate",
        category="cross",
        description=(
            "Look up the top 3 Python web frameworks on a reputable site, "
            "then collect the local Python version via terminal, "
            "and save a compatibility summary as a text file"
        ),
        domain="mixed",
        target_server=None,
        approved_plan=[
            "Navigate to python.org or a well-known Python resource and identify the top 3 web frameworks",
            "Extract the name and one-line description for each framework",
            "Run 'python --version' in the terminal to capture the local Python version",
            "Create a file framework_summary.txt with the local Python version at the top, "
            "followed by the 3 framework names and descriptions",
            "Confirm the file exists and print its contents",
        ],
    ),
    Scenario(
        name="TestCrossDomainComplexRepoSummary",
        difficulty="complex",
        category="cross",
        description=(
            "Find the GitHub repository for the 'requests' Python library, "
            "collect its star count and latest release tag, "
            "check if 'requests' is installed locally via pip, "
            "and save a full summary note to a file"
        ),
        domain="mixed",
        target_server=None,
        approved_plan=[
            "Navigate to github.com/psf/requests and extract the star count and latest release tag",
            "Run 'pip show requests' in the terminal to get the locally installed version",
            "Run 'python -c \"import requests; print(requests.__version__)\"' to confirm the import works",
            "Create a file requests_summary.txt with: GitHub stars, latest release tag, "
            "locally installed version, and whether the import succeeded",
            "Confirm the file exists and print its full contents",
        ],
    ),
]

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class Result:
    scenario: Scenario
    status: str            # success | failure | error | timeout
    elapsed_s: float
    output: str = ""
    error: str = ""
    steps_completed: int = 0
    verification_status: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def prepare_scenario(scenario: Scenario) -> None:
    if scenario.name != "TestCliModerateOrganizeDownloads":
        return

    base = _UNIFIED_APP / "_runtime" / "domain_scenarios" / "cli_moderate_downloads"
    inbox = base / "inbox"
    organized = base / "organized"
    if base.exists():
        shutil.rmtree(base)
    inbox.mkdir(parents=True, exist_ok=True)
    organized.mkdir(parents=True, exist_ok=True)

    fixtures = {
        "invoice_april.pdf": "PDF invoice placeholder\n",
        "project_brief.docx": "DOCX placeholder\n",
        "todo.txt": "review downloads cleanup\n",
        "screenshot_home.png": "PNG placeholder\n",
        "profile_photo.jpg": "JPG placeholder\n",
        "setup_tool.exe": "EXE placeholder\n",
        "driver_update.msi": "MSI placeholder\n",
        "archive_export.zip": "ZIP placeholder\n",
        "partial_download.tmp": "leave this in inbox\n",
        "README": "leave this in inbox because it has no extension\n",
    }
    for name, content in fixtures.items():
        (inbox / name).write_text(content, encoding="utf-8")


def validate_scenario_result(scenario: Scenario) -> str:
    if scenario.name != "TestCliModerateOrganizeDownloads":
        return ""

    base = _UNIFIED_APP / "_runtime" / "domain_scenarios" / "cli_moderate_downloads"
    expected_locations = {
        "organized/documents/invoice_april.pdf",
        "organized/documents/project_brief.docx",
        "organized/documents/todo.txt",
        "organized/images/screenshot_home.png",
        "organized/images/profile_photo.jpg",
        "organized/installers/setup_tool.exe",
        "organized/installers/driver_update.msi",
        "organized/archives/archive_export.zip",
        "inbox/partial_download.tmp",
        "inbox/README",
    }
    missing = [path for path in sorted(expected_locations) if not (base / path).exists()]
    if missing:
        return "Missing expected organized files: " + ", ".join(missing)

    misplaced = [
        "organized/documents/README",
        "organized/documents/partial_download.tmp",
        "organized/images/README",
        "organized/installers/README",
        "organized/archives/README",
    ]
    found_misplaced = [path for path in misplaced if (base / path).exists()]
    if found_misplaced:
        return "Found files that should have stayed in inbox: " + ", ".join(found_misplaced)

    manifest = base / "organized" / "manifest.txt"
    if not manifest.exists():
        return "Expected manifest.txt to exist."
    manifest_text = manifest.read_text(encoding="utf-8", errors="replace")
    required_manifest_text = ["Total moved: 8", "README", "partial_download.tmp"]
    missing_text = [text for text in required_manifest_text if text not in manifest_text]
    if missing_text:
        return "Manifest missing required text: " + ", ".join(missing_text)
    return ""


def persist_result(index: int, result: Result) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{index:02d}_{result.scenario.name}.json"
    payload = {
        "scenario": {
            "name": result.scenario.name,
            "description": result.scenario.description,
            "domain": result.scenario.domain,
            "target_server": result.scenario.target_server,
            "difficulty": result.scenario.difficulty,
            "category": result.scenario.category,
        },
        "status": result.status,
        "elapsed_s": result.elapsed_s,
        "output": result.output,
        "error": result.error,
        "steps_completed": result.steps_completed,
        "verification_status": result.verification_status,
        "raw": result.raw,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _localhost_urls_in_plan(plan: list[str]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for step in plan:
        for url in re.findall(r"https?://localhost:\d+(?:/[^\s,)]*)?", step, flags=re.IGNORECASE):
            cleaned = url.rstrip(".,;")
            if cleaned not in seen:
                seen.add(cleaned)
                urls.append(cleaned)
    return urls


def _url_reachable(url: str) -> bool:
    try:
        with urlopen(Request(url, method="GET"), timeout=3) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


async def run_one(bridge: TrinityBridge, scenario: Scenario) -> Result:
    for url in _localhost_urls_in_plan(scenario.approved_plan):
        if not await asyncio.to_thread(_url_reachable, url):
            return Result(
                scenario=scenario,
                status="skipped",
                elapsed_s=0.0,
                error=f"Required service not reachable: {url}",
            )
    prepare_scenario(scenario)
    task_id = f"live-{uuid.uuid4().hex[:8]}"
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            bridge.execute_task(
                task_id=task_id,
                description=scenario.description,
                domain=scenario.domain,
                target_server=scenario.target_server,
                sub_objectives=scenario.approved_plan,
                verification_checks=scenario.verification_checks,
                timeout=TIMEOUT_S,
                max_retries=1,
            ),
            timeout=TIMEOUT_S + 10,
        )
        elapsed = time.perf_counter() - t0

        payload: dict[str, Any] = (
            result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
        )
        status = payload.get("status", "unknown")
        meta = payload.get("metadata") or {}
        output = str(meta.get("output") or payload.get("error") or "")[:400]

        exec_log = payload.get("execution_log") or []
        steps_completed = sum(
            1 for s in exec_log
            if isinstance(s, dict) and s.get("result") == "success"
        )

        verification = payload.get("verification") or {}
        if hasattr(verification, "status"):
            v_status = verification.status
        elif isinstance(verification, dict):
            v_status = verification.get("status", "")
        else:
            v_status = ""

        validation_error = validate_scenario_result(scenario) if status == "success" else ""
        if validation_error:
            status = "failure"

        return Result(
            scenario=scenario,
            status=status,
            elapsed_s=elapsed,
            output=output,
            error=validation_error,
            steps_completed=steps_completed,
            verification_status=v_status,
            raw=payload,
        )

    except asyncio.TimeoutError:
        return Result(
            scenario=scenario,
            status="timeout",
            elapsed_s=time.perf_counter() - t0,
            error=f"Exceeded {TIMEOUT_S}s timeout",
        )
    except Exception as exc:
        return Result(
            scenario=scenario,
            status="error",
            elapsed_s=time.perf_counter() - t0,
            error=str(exc)[:400],
        )


def _status_icon(status: str) -> str:
    return {"success": "PASS", "failure": "FAIL", "error": "ERR!", "timeout": "TIME", "skipped": "SKIP"}.get(
        status, "????"
    )


async def main() -> None:
    print("=" * 72)
    print("TrinityPilot Live Domain Scenario Runner")
    print(f"Timeout per scenario: {TIMEOUT_S}s")
    print("=" * 72)

    bridge = TrinityBridge()
    print("\nInitializing bridge...")
    try:
        await bridge.initialize()
        servers = [s["strategy_id"] for s in bridge.known_servers()]
        print(f"Servers online: {servers}\n")
    except Exception as exc:
        print(f"Bridge init failed: {exc}")
        return

    results: list[Result] = []

    for i, scenario in enumerate(SCENARIOS, start=1):
        label = f"[{i:02d}/09] {scenario.category.upper():8s} {scenario.difficulty:8s}  {scenario.name}"
        print(f"\n{label}")
        print("-" * len(label))
        print(f"  Task:    {scenario.description[:80]}")
        print(f"  Steps:   {len(scenario.approved_plan)}")
        print(f"  Running...", end="", flush=True)

        result = await run_one(bridge, scenario)
        results.append(result)
        persist_result(i, result)

        icon = _status_icon(result.status)
        print(f"\r  [{icon}] {result.elapsed_s:.1f}s   status={result.status}")
        if result.output:
            snippet = result.output.replace("\n", " ")[:120]
            print(f"  Output:  {snippet}")
        if result.error:
            print(f"  Error:   {result.error[:120]}")
        if result.verification_status:
            print(f"  Verify:  {result.verification_status}")

    await bridge.shutdown()

    # --- summary table -------------------------------------------------------
    print("\n\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"{'Scenario':<48} {'Cat':>5} {'Diff':>8} {'Status':>8} {'Time':>7}  {'Steps'}")
    print("-" * 72)
    for r in results:
        sc = r.scenario
        icon = _status_icon(r.status)
        print(
            f"{sc.name:<48} {sc.category:>5} {sc.difficulty:>8} "
            f"[{icon}] {r.elapsed_s:6.1f}s  {r.steps_completed}"
        )

    passed = sum(1 for r in results if r.status == "success")
    failed = sum(1 for r in results if r.status == "failure")
    errors = sum(1 for r in results if r.status == "error")
    timeouts = sum(1 for r in results if r.status == "timeout")
    skipped = sum(1 for r in results if r.status == "skipped")

    print("-" * 72)
    print(f"Total: {len(results)}  PASS={passed}  FAIL={failed}  ERR={errors}  TIMEOUT={timeouts}  SKIP={skipped}")
    print(f"Result JSON: {RESULTS_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
