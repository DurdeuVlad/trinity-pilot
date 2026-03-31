"""Battle Runner - Automated test suite for unified-app orchestrator.

Submits tasks via IPC to the running orchestrator app, monitors execution,
and scores results against expected outcomes.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import psutil

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.task_submission_pipe import submit_task_via_pipe, PipeSubmissionUnavailable

_RUNTIME_DIR = Path(__file__).parent.parent / "_runtime"
_BATTLE_OUTPUT_DIR = _RUNTIME_DIR / "output" / "battle"
_BATTLE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TIMEOUT = 120  # seconds per scenario


def load_persona(persona_path: Path) -> dict[str, Any]:
    """Load persona JSON file."""
    with open(persona_path, encoding="utf-8") as f:
        return json.load(f)


def submit_scenario(scenario: dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Submit a scenario task via IPC and monitor execution."""
    scenario_id = scenario["id"]
    description = scenario["input"]
    domain = scenario.get("domain", "mixed")
    
    result = {
        "id": scenario_id,
        "description": description,
        "domain": domain,
        "expected_status": scenario.get("expected_status", "completed"),
        "submission_time": None,
        "completion_time": None,
        "elapsed_ms": None,
        "status": None,
        "step_count": None,
        "orphan_processes": False,
        "score": 0,
        "notes": []
    }
    
    # Submit task
    try:
        start_time = time.time()
        response = submit_task_via_pipe(
            description=description,
            domain=domain,
            timeout_seconds=timeout,
            request_id=f"battle_{scenario_id}"
        )
        result["submission_time"] = start_time
        
        if response.get("status") == "error":
            result["status"] = "error"
            result["notes"].append(f"Submission error: {response.get('message', 'Unknown')}")
            return result
        
        task_id = response.get("task_id")
        if not task_id:
            result["status"] = "error"
            result["notes"].append("No task_id returned from submission")
            return result
        
        # Monitor execution
        max_wait = timeout
        poll_interval = 2
        elapsed = 0
        
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            
            # Check if task completed (would need to query history DB or status endpoint)
            # For now, simplified: wait for timeout or success signal
            # In real implementation, query task status via MCP or history DB
            
        # After timeout
        result["status"] = "timeout"
        result["elapsed_ms"] = int((time.time() - start_time) * 1000)
        result["notes"].append(f"Timeout after {timeout}s")
        
    except PipeSubmissionUnavailable as e:
        result["status"] = "error"
        result["notes"].append(f"IPC unavailable: {e}")
    except Exception as e:
        result["status"] = "error"
        result["notes"].append(f"Exception: {e}")
    
    # Check for orphan processes
    result["orphan_processes"] = check_orphan_processes()
    
    # Score result
    result["score"] = score_scenario(result, scenario)
    
    return result


def check_orphan_processes() -> bool:
    """Check if any orphan processes exist after scenario."""
    # Check for common test-spawned processes
    orphan_names = ["chrome.exe", "firefox.exe", "notepad.exe"]
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] in orphan_names:
                # Check if it's a test-spawned process (simplified check)
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def score_scenario(result: dict[str, Any], scenario: dict[str, Any]) -> int:
    """Score scenario result on 10-point scale."""
    if result["status"] == "error":
        return 0
    if result["status"] == "timeout":
        return 0
    
    expected_status = scenario.get("expected_status", "completed")
    if result["status"] == expected_status:
        score = 10
    else:
        score = 5  # Partial credit for completion
    
    # Deduct for orphan processes
    if result.get("orphan_processes"):
        score -= 2
    
    # Deduct for excessive time (>60s)
    if result.get("elapsed_ms", 0) > 60000:
        score -= 1
    
    return max(0, score)


def run_persona(persona_path: Path, chaos_level: str = "none") -> list[dict[str, Any]]:
    """Run all scenarios for a persona."""
    persona = load_persona(persona_path)
    results = []
    
    print(f"\n{'='*60}")
    print(f"Running persona: {persona['name']}")
    print(f"{'='*60}")
    
    for scenario in persona["scenarios"]:
        scenario_id = scenario["id"]
        print(f"\n→ Testing {scenario_id}: {scenario['input'][:50]}...")
        
        result = submit_scenario(scenario)
        results.append(result)
        
        status_symbol = "✓" if result["score"] >= 8 else "✗"
        print(f"{status_symbol} {scenario_id}: {result['status']} (score: {result['score']}/10)")
    
    return results


def generate_summary(all_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate summary statistics."""
    total = len(all_results)
    passed = sum(1 for r in all_results if r["score"] >= 8)
    failed = sum(1 for r in all_results if r["score"] < 8 and r["status"] != "error")
    errors = sum(1 for r in all_results if r["status"] == "error")
    skipped = 0  # Not implemented yet
    
    avg_score = sum(r["score"] for r in all_results) / total if total > 0 else 0
    score_pct = int((avg_score / 10) * 100)
    
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "score_pct": score_pct,
        "avg_score": avg_score
    }


def main():
    parser = argparse.ArgumentParser(description="Battle Runner for unified-app")
    parser.add_argument("--persona", default="all", help="Persona to run (all or persona name)")
    parser.add_argument("--scenarios", default="all", help="Scenario IDs to run (all or comma-separated)")
    parser.add_argument("--chaos", default="none", choices=["none", "light", "moderate", "heavy"])
    parser.add_argument("--output", default=str(_BATTLE_OUTPUT_DIR / "results.json"))
    parser.add_argument("--report", default=str(_BATTLE_OUTPUT_DIR / "report.html"))
    parser.add_argument("--app-port", type=int, default=None, help="Override IPC pipe port")
    
    args = parser.parse_args()
    
    # Find persona files
    persona_dir = Path(__file__).parent / "personas"
    if not persona_dir.exists():
        print(f"✗ Error: Persona directory not found: {persona_dir}")
        return 1
    
    persona_files = list(persona_dir.glob("persona_*.json"))
    if not persona_files:
        print(f"✗ Error: No persona files found in {persona_dir}")
        return 1
    
    # Run personas
    all_results = []
    for persona_path in sorted(persona_files):
        if args.persona != "all" and args.persona not in persona_path.name:
            continue
        
        results = run_persona(persona_path, args.chaos)
        all_results.extend(results)
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    
    # Print summary
    summary = generate_summary(all_results)
    print(f"\n{'='*60}")
    print("BATTLE RUNNER RESULTS")
    print(f"{'='*60}")
    print(f"Results: {summary['passed']}/{summary['total']} passed | "
          f"{summary['failed']} failed | {summary['skipped']} skipped | "
          f"{summary['errors']} errors | Score: {summary['score_pct']}%")
    print(f"\nResults saved to: {output_path}")
    
    return 0 if summary['score_pct'] >= 90 else 1


if __name__ == "__main__":
    sys.exit(main())
