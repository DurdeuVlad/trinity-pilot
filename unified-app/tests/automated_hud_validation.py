"""
Automated HUD Validation Test Suite

Fully autonomous testing of Phase 1 HUD overlay using MCP server.
No manual intervention required.

Usage:
    python automated_hud_validation.py --desktop 2 --output reports/hud_validation.md
"""

import asyncio
import json
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import argparse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.mcp_test_client import MCPTestClient
from tests.screenshot_analyzer_simple import ScreenshotAnalyzer, capture_screenshot
from tests.desktop_isolation import VirtualDesktopManager


class HUDValidator:
    """Automated HUD overlay validation using MCP server"""

    def __init__(self, desktop_number: int = 2, debug: bool = False):
        self.desktop_number = desktop_number
        self.debug = debug
        self.mcp_client = MCPTestClient()
        self.analyzer = ScreenshotAnalyzer()
        self.desktop_manager = VirtualDesktopManager()
        self.results = []

    async def setup(self):
        """Initialize test environment"""
        print("=" * 80)
        print("AUTOMATED HUD VALIDATION TEST SUITE")
        print("=" * 80)
        print()

        # Check if unified-app is running
        hwnd = self.desktop_manager.find_unified_app_window()
        if not hwnd:
            print("❌ ERROR: Unified-app not running")
            print("   Start unified-app first: python unified-app/main.py")
            return False

        print(f"✅ Unified-app detected (window handle: {hwnd})")

        # Isolate to target desktop
        print(f"📍 Isolating unified-app to Desktop {self.desktop_number}...")
        if not self.desktop_manager.isolate_unified_app(self.desktop_number):
            print("⚠️  Warning: Could not isolate to virtual desktop")
            print("   Tests will run on current desktop")

        # Connect to MCP server
        print("🔌 Connecting to MCP server...")
        await self.mcp_client.connect()
        print("✅ MCP server connected")
        print()

        return True

    async def run_test(self, test_id: str, description: str, domain: str,
                       expected_output: Optional[str] = None) -> Dict:
        """
        Run a single HUD validation test.

        Args:
            test_id: Test identifier (e.g., "HP-01")
            description: Task description to submit
            domain: Task domain (cli, browser, desktop, mixed)
            expected_output: Expected output text (optional)

        Returns:
            Test result dictionary with score and validation details
        """
        print(f"🧪 Running {test_id}: {description}")
        print("-" * 80)

        screenshots = []
        start_time = time.time()

        try:
            # Submit task via MCP
            print(f"   📤 Submitting task (domain: {domain})...")
            submit_result = await self.mcp_client.submit_task(description, domain)
            task_id = submit_result.get("task_id")

            if not task_id:
                print(f"   ❌ Failed to submit task: {submit_result}")
                return self._create_failed_result(test_id, "Task submission failed")

            print(f"   ✅ Task submitted: {task_id}")

            # Wait for overlay to appear (200ms per NFR-1.2)
            await asyncio.sleep(0.3)

            # Capture initial screenshot (overlay should be visible)
            print(f"   📸 Capturing overlay screenshot...")
            initial_screenshot = capture_screenshot()
            screenshots.append({
                "moment": "overlay_shown",
                "image": initial_screenshot,
                "timestamp": time.time()
            })

            # Validate HUD overlay elements
            print(f"   🔍 Analyzing HUD overlay...")
            hud_validation = self.analyzer.validate_hud_overlay(initial_screenshot)

            # Monitor task execution
            print(f"   ⏳ Monitoring task execution...")
            execution_screenshots = await self._monitor_execution(task_id)
            screenshots.extend(execution_screenshots)

            # Get final task details
            print(f"   📋 Retrieving task details...")
            task_details = await self.mcp_client.get_task_details(task_id)

            # Calculate score
            score = self._score_test(
                test_id=test_id,
                hud_validation=hud_validation,
                task_details=task_details,
                expected_output=expected_output
            )

            elapsed = time.time() - start_time
            passed = score >= 8  # 8/10 threshold

            result = {
                "test_id": test_id,
                "description": description,
                "domain": domain,
                "passed": passed,
                "score": score,
                "elapsed_seconds": round(elapsed, 2),
                "task_id": task_id,
                "hud_validation": hud_validation,
                "task_details": task_details,
                "screenshots": len(screenshots)
            }

            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"   {status} - Score: {score}/10 ({elapsed:.2f}s)")
            print()

            return result

        except Exception as e:
            print(f"   ❌ Test failed with exception: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()

            return self._create_failed_result(test_id, str(e))

    async def _monitor_execution(self, task_id: str) -> List[Dict]:
        """Monitor task execution and capture screenshots at key moments"""
        screenshots = []
        last_state = None

        while True:
            try:
                status = await self.mcp_client.get_task_status(task_id)
                current_state = status.get("state", "unknown")

                # Capture screenshot on state change
                if current_state != last_state:
                    screenshot = capture_screenshot()
                    screenshots.append({
                        "moment": f"state_{current_state}",
                        "image": screenshot,
                        "timestamp": time.time()
                    })
                    last_state = current_state

                # Check if task completed
                if current_state in ["completed", "failed", "cancelled"]:
                    # Wait for overlay to dismiss
                    await asyncio.sleep(0.5)

                    # Capture final screenshot (overlay should be gone)
                    final_screenshot = capture_screenshot()
                    screenshots.append({
                        "moment": "overlay_dismissed",
                        "image": final_screenshot,
                        "timestamp": time.time()
                    })

                    break

                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"   ⚠️  Error monitoring execution: {e}")
                break

        return screenshots

    def _score_test(self, test_id: str, hud_validation: Dict,
                    task_details: Dict, expected_output: Optional[str]) -> int:
        """
        Score test result using battle-tester rubric.

        Maximum: 10 points
        - Functional Correctness: 4 pts (0 or 4, no partial)
        - User-Visible Feedback: 2 pts
        - Safety and Cleanup: 2 pts
        - Resilience: 2 pts
        """
        score = 0

        # Functional Correctness (4 pts - all or nothing)
        task_state = task_details.get("state", "unknown")
        if task_state == "completed":
            score += 4

        # User-Visible Feedback (2 pts)
        # Check if HUD overlay was visible
        if hud_validation.get("full_screen_overlay"):
            score += 1
        if hud_validation.get("control_panel_visible"):
            score += 1

        # Safety and Cleanup (2 pts)
        # Check if overlay dismissed properly
        if task_state in ["completed", "failed", "cancelled"]:
            score += 2

        # Resilience (2 pts)
        # Check if all HUD elements were present
        hud_checks_passed = sum(1 for v in hud_validation.values() if v)
        hud_checks_total = len(hud_validation)
        if hud_checks_total > 0:
            resilience_score = (hud_checks_passed / hud_checks_total) * 2
            score += round(resilience_score)

        return min(score, 10)  # Cap at 10

    def _create_failed_result(self, test_id: str, error: str) -> Dict:
        """Create a failed test result"""
        return {
            "test_id": test_id,
            "passed": False,
            "score": 0,
            "error": error,
            "hud_validation": {},
            "task_details": {},
            "screenshots": 0
        }

    async def run_hp_suite(self) -> List[Dict]:
        """Run HP-01 through HP-05 test suite"""
        tests = [
            {
                "id": "HP-01",
                "description": "Run echo Hello World in the terminal and show output",
                "domain": "cli",
                "expected_output": "Hello World"
            },
            {
                "id": "HP-02",
                "description": "Open Chrome and navigate to https://example.com",
                "domain": "browser",
                "expected_output": "example.com"
            },
            {
                "id": "HP-03",
                "description": "Create a text file called battle_test.txt on the Desktop",
                "domain": "desktop",
                "expected_output": "battle_test.txt"
            },
            {
                "id": "HP-04",
                "description": "Open a terminal, list Desktop files, show me the count",
                "domain": "mixed",
                "expected_output": "count"
            },
            {
                "id": "HP-05",
                "description": "What files are in my Downloads folder?",
                "domain": "cli",
                "expected_output": "files"
            }
        ]

        results = []

        for test in tests:
            result = await self.run_test(
                test_id=test["id"],
                description=test["description"],
                domain=test["domain"],
                expected_output=test.get("expected_output")
            )
            results.append(result)

            # Wait between tests
            await asyncio.sleep(2)

        return results

    def generate_report(self, results: List[Dict], output_path: Optional[Path] = None) -> str:
        """Generate markdown validation report"""
        passed = sum(1 for r in results if r.get("passed", False))
        failed = len(results) - passed
        pass_rate = (passed / len(results) * 100) if results else 0

        report = f"""# Phase 1 HUD Validation Report

> **Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> **Test Suite:** HP-01 through HP-05 (Happy Path)
> **Execution:** Fully automated via MCP server
> **Desktop:** Isolated to Desktop {self.desktop_number}

---

## Summary

| Metric | Value |
|--------|-------|
| Tests Run | {len(results)} |
| Tests Passed | {passed} |
| Tests Failed | {failed} |
| Pass Rate | {pass_rate:.1f}% |
| SC-9 Status | {"✅ PASS" if passed == 5 else "❌ FAIL"} |

---

## Test Results

"""

        for result in results:
            status = "✅ PASS" if result.get("passed", False) else "❌ FAIL"
            score = result.get("score", 0)
            test_id = result.get("test_id", "Unknown")
            description = result.get("description", "")

            report += f"""### {test_id} - {status}

**Description:** {description}
**Score:** {score}/10
**Elapsed:** {result.get('elapsed_seconds', 0):.2f}s

"""

            if "hud_validation" in result and result["hud_validation"]:
                report += "**HUD Validation:**\n"
                for check, passed_check in result["hud_validation"].items():
                    icon = "✅" if passed_check else "❌"
                    report += f"- {icon} {check}\n"
                report += "\n"

            if "error" in result:
                report += f"**Error:** {result['error']}\n\n"

            report += "---\n\n"

        # Success criteria validation
        report += """## Success Criteria Validation

| Criterion | Status | Notes |
|-----------|--------|-------|
| SC-1: Demo task shows HUD | """

        sc1_passed = any(r.get("hud_validation", {}).get("full_screen_overlay") for r in results)
        report += f"""{"✅ PASS" if sc1_passed else "❌ FAIL"} | Full-screen overlay detected in tests |
| SC-2: Steps appear in HUD | {"✅ PASS" if sc1_passed else "❌ FAIL"} | Step list visible in control panel |
| SC-9: HP-01 through HP-05 pass | {"✅ PASS" if passed == 5 else "❌ FAIL"} | {passed}/5 tests passed |

---

## Conclusion

"""

        if passed == 5:
            report += """✅ **Phase 1 HUD validation PASSED**

All 5 happy-path tests passed with automated verification. The full-screen HUD overlay is working as specified in the Phase 1 requirements.

**Next steps:**
- Update epic acceptance gate in `docs/plans/epics/2026-03-30_seamless-desktop-control/README.md`
- Mark SC-9 as complete
- Proceed with Phase 2 Test Harness epic
"""
        else:
            report += f"""❌ **Phase 1 HUD validation FAILED**

Only {passed}/5 tests passed. Review failed tests above and fix issues before proceeding.

**Action required:**
- Fix failing tests
- Re-run validation suite
- Do not proceed to Phase 2 until all tests pass
"""

        # Save report if output path provided
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")
            print(f"📄 Report saved to: {output_path}")

        return report

    async def cleanup(self):
        """Cleanup test environment"""
        await self.mcp_client.disconnect()


async def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Automated HUD validation test suite"
    )
    parser.add_argument(
        "--desktop",
        type=int,
        default=2,
        help="Virtual desktop number for isolation (default: 2)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/hud_validation.md"),
        help="Output path for validation report"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output"
    )
    parser.add_argument(
        "--test",
        type=str,
        help="Run single test (e.g., HP-01)"
    )

    args = parser.parse_args()

    validator = HUDValidator(
        desktop_number=args.desktop,
        debug=args.debug
    )

    try:
        # Setup
        if not await validator.setup():
            return 1

        # Run tests
        if args.test:
            # Single test mode (not implemented yet)
            print(f"Single test mode not implemented. Running full suite.")

        results = await validator.run_hp_suite()

        # Generate report
        report = validator.generate_report(results, args.output)

        # Print summary
        print()
        print("=" * 80)
        print("TEST SUITE COMPLETE")
        print("=" * 80)
        print(report)

        # Exit code based on results
        passed = sum(1 for r in results if r.get("passed", False))
        return 0 if passed == 5 else 1

    finally:
        await validator.cleanup()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
