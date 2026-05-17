"""E2E report runner.

Collects all e2e test results from pytest's JSON report and writes a summary.

Usage (standalone):
    python -m tests.e2e._runner

Requires pytest-json-report:
    pip install pytest-json-report

Or invoke via pytest plugin and read the generated .e2e-reports/ directory.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REPORT_DIR = _PROJECT_ROOT / ".e2e-reports"
_E2E_DIR = Path(__file__).resolve().parent


def run_e2e_suite(
    markers: str = "e2e and not desktop",
    timeout: int = 120,
    output_dir: Path | None = None,
) -> Path:
    """Run the e2e suite via pytest subprocess and write a JSONL report.

    Args:
        markers: pytest -m expression (default skips desktop tests)
        timeout: per-test timeout in seconds
        output_dir: directory for report files (default: .e2e-reports/)

    Returns:
        Path to the written JSONL report file.
    """
    report_dir = output_dir or _REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    json_output = report_dir / f"{timestamp}_pytest_raw.json"
    jsonl_output = report_dir / f"{timestamp}_e2e_report.jsonl"

    cmd = [
        sys.executable, "-m", "pytest",
        str(_E2E_DIR),
        "-v",
        f"--timeout={timeout}",
        "-m", markers,
        "--tb=short",
        "--no-header",
        "-q",
        "--json-report",
        f"--json-report-file={json_output}",
    ]

    print(f"Running: {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=False, text=True, cwd=str(_PROJECT_ROOT))
    duration = time.time() - t0

    # Parse raw pytest JSON if available
    records: list[dict] = []
    if json_output.exists():
        try:
            raw = json.loads(json_output.read_text(encoding="utf-8"))
            for test in raw.get("tests", []):
                records.append({
                    "scenario_name": test.get("nodeid", ""),
                    "domain": _infer_domain(test.get("nodeid", "")),
                    "status": test.get("outcome", "unknown"),
                    "duration_s": test.get("duration", 0.0),
                    "error": _extract_error(test),
                })
        except Exception as exc:
            records.append({"error": f"Failed to parse pytest JSON: {exc}"})
    else:
        records.append({
            "scenario_name": "suite",
            "status": "completed" if proc.returncode == 0 else "failed",
            "duration_s": duration,
            "note": "pytest-json-report not installed; raw JSON unavailable",
        })

    # Write JSONL
    with open(jsonl_output, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    # Write summary report.json
    summary = _build_summary(records, timestamp, duration, proc.returncode)
    summary_path = report_dir / f"{timestamp}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Print summary table
    _print_summary_table(records, summary)

    return jsonl_output


def _infer_domain(nodeid: str) -> str:
    if "terminal" in nodeid:
        return "terminal"
    if "browser" in nodeid:
        return "browser"
    if "desktop" in nodeid:
        return "desktop"
    if "behavioral" in nodeid:
        return "behavioral"
    return "unknown"


def _extract_error(test: dict) -> str:
    call = test.get("call", {})
    longrepr = call.get("longrepr", "")
    if isinstance(longrepr, str):
        return longrepr[:500] if longrepr else ""
    return ""


def _build_summary(
    records: list[dict],
    timestamp: str,
    total_duration: float,
    return_code: int,
) -> dict:
    domain_counts: dict[str, dict] = {}
    for rec in records:
        domain = rec.get("domain", "unknown")
        status = rec.get("status", "unknown")
        if domain not in domain_counts:
            domain_counts[domain] = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
        domain_counts[domain]["total"] += 1
        if status == "passed":
            domain_counts[domain]["passed"] += 1
        elif status in ("failed", "error"):
            domain_counts[domain]["failed"] += 1
        elif status == "skipped":
            domain_counts[domain]["skipped"] += 1

    total = len(records)
    passed = sum(1 for r in records if r.get("status") == "passed")
    failed = sum(1 for r in records if r.get("status") in ("failed", "error"))
    skipped = sum(1 for r in records if r.get("status") == "skipped")

    return {
        "timestamp": timestamp,
        "total_duration_s": round(total_duration, 2),
        "return_code": return_code,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "by_domain": domain_counts,
    }


def _print_summary_table(records: list[dict], summary: dict) -> None:
    print("\n" + "=" * 60)
    print("E2E TEST SUMMARY")
    print("=" * 60)
    print(f"{'Test':<50} {'Status':<10} {'Duration':>8}")
    print("-" * 60)
    for rec in records:
        name = rec.get("scenario_name", "?")[-48:]
        status = rec.get("status", "?")
        dur = f"{rec.get('duration_s', 0):.1f}s"
        print(f"{name:<50} {status:<10} {dur:>8}")
    print("-" * 60)
    print(
        f"Total: {summary['total']}  "
        f"Passed: {summary['passed']}  "
        f"Failed: {summary['failed']}  "
        f"Skipped: {summary['skipped']}"
    )
    print("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run e2e test suite and generate report")
    parser.add_argument("-m", "--markers", default="e2e and not desktop", help="pytest -m expression")
    parser.add_argument("--timeout", type=int, default=120, help="Per-test timeout in seconds")
    parser.add_argument("--output-dir", type=Path, default=None, help="Report output directory")
    args = parser.parse_args()

    report_path = run_e2e_suite(
        markers=args.markers,
        timeout=args.timeout,
        output_dir=args.output_dir,
    )
    print(f"\nReport written to: {report_path}")
