"""
Trinity Core - Real World Test Demo

This script demonstrates Trinity Core in action with real tasks across all three domains.
Includes health checks, individual task execution, and cross-domain workflows.
"""
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.append(str(repo_root))

from trinity_core.trinity import TrinityExecutor
from trinity_core.models import TaskInput
from trinity_core.config import TrinityConfig


def print_header(text: str):
    """Print formatted section header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_result(result):
    """Print task result details."""
    print(f"Task ID: {result.task_id}")
    print(f"Status: {result.status.upper()}")
    print(f"Duration: {result.duration:.2f}s")
    
    if result.status == "success":
        print("✓ Task completed successfully!")
    else:
        print(f"✗ Task failed: {result.error}")
    
    if result.execution_log:
        print(f"\nExecution steps ({len(result.execution_log)}):")
        for log in result.execution_log[:5]:  # Show first 5 steps
            print(f"  Step {log.step}: {log.action}")
        if len(result.execution_log) > 5:
            print(f"  ... and {len(result.execution_log) - 5} more steps")
    
    print()


async def test_health_check(executor: TrinityExecutor):
    """Test: Health check all modules."""
    print_header("HEALTH CHECK")
    
    health = await executor.health_check_all()
    capabilities = await executor.get_capabilities_all()
    
    print("Module Status:")
    for domain, status in health.items():
        icon = "✓" if status else "✗"
        caps = capabilities.get(domain, {})
        print(f"  {icon} {domain:10s} - {caps.get('description', 'No description')}")
    
    return all(health.values())


async def test_browser_task(executor: TrinityExecutor):
    """Test: Browser automation task."""
    print_header("BROWSER TASK - Web Navigation")
    
    task = TaskInput(
        task_id=f"web_{datetime.now().strftime('%H%M%S')}",
        description="Navigate to example.com and verify the page loaded successfully",
        domain="web",
        expected_outcome="Page title contains 'Example Domain' and page is fully loaded"
    )
    
    print(f"Executing: {task.description}\n")
    result = await executor.execute(task)
    print_result(result)
    return result.status == "success"


async def test_desktop_task(executor: TrinityExecutor):
    """Test: Desktop automation task."""
    print_header("DESKTOP TASK - Windows UI Automation")
    
    print("⚠️  MANUAL STEP REQUIRED: Please open Notepad before continuing")
    print("    (Start > Notepad)")
    input("Press Enter when Notepad is open...")
    
    task = TaskInput(
        task_id=f"desktop_{datetime.now().strftime('%H%M%S')}",
        description="Type 'Trinity Core Test - Success!' into Notepad",
        domain="desktop",
        context={"app_name": "Notepad"},
        expected_outcome="Text appears in the Notepad window",
        timeout=120
    )
    
    print(f"\nExecuting: {task.description}")
    print("👀 Watch for the red box highlighting UI elements!\n")
    result = await executor.execute(task)
    print_result(result)
    return result.status == "success"


async def test_cli_task(executor: TrinityExecutor):
    """Test: CLI automation task."""
    print_header("CLI TASK - PowerShell Automation")
    
    task = TaskInput(
        task_id=f"cli_{datetime.now().strftime('%H%M%S')}",
        description="List all .md files in the current directory",
        domain="cli",
        expected_outcome="Markdown files are listed in the output"
    )
    
    print(f"Executing: {task.description}\n")
    result = await executor.execute(task)
    print_result(result)
    return result.status == "success"


async def test_cross_domain_workflow(executor: TrinityExecutor):
    """Test: Cross-domain workflow with data chaining."""
    print_header("CROSS-DOMAIN WORKFLOW")
    
    print("This workflow chains tasks across all three domains:\n")
    print("1. CLI: Get system information")
    print("2. Desktop: Save info to Notepad")
    print("3. Browser: Search for related info")
    
    # Step 1: Get system info via CLI
    print("\n--- Step 1: CLI Task ---")
    cli_task = TaskInput(
        task_id=f"workflow_cli_{datetime.now().strftime('%H%M%S')}",
        description="Get the PowerShell version using $PSVersionTable.PSVersion",
        domain="cli",
        expected_outcome="PowerShell version information is displayed"
    )
    
    cli_result = await executor.execute(cli_task)
    print(f"CLI Result: {cli_result.status}")
    
    if cli_result.status != "success":
        print("❌ Workflow stopped: CLI task failed")
        return False
    
    # Step 2: Save to Notepad
    print("\n--- Step 2: Desktop Task ---")
    print("⚠️  Ensure Notepad is still open")
    input("Press Enter to continue...")
    
    desktop_task = TaskInput(
        task_id=f"workflow_desktop_{datetime.now().strftime('%H%M%S')}",
        description="Clear Notepad and type 'Workflow complete - Trinity Core works!'",
        domain="desktop",
        context={"app_name": "Notepad"},
        expected_outcome="Text appears in Notepad"
    )
    
    desktop_result = await executor.execute(desktop_task)
    print(f"Desktop Result: {desktop_result.status}")
    
    if desktop_result.status != "success":
        print("⚠️  Desktop task had issues, continuing anyway...")
    
    # Step 3: Browser search
    print("\n--- Step 3: Browser Task ---")
    browser_task = TaskInput(
        task_id=f"workflow_web_{datetime.now().strftime('%H%M%S')}",
        description="Navigate to wikipedia.org and search for 'automation'",
        domain="web",
        expected_outcome="Search results for automation are displayed"
    )
    
    browser_result = await executor.execute(browser_task)
    print(f"Browser Result: {browser_result.status}")
    
    # Summary
    print("\n--- Workflow Summary ---")
    all_success = all([
        cli_result.status == "success",
        desktop_result.status == "success", 
        browser_result.status == "success"
    ])
    
    if all_success:
        print("✓ All workflow steps completed successfully!")
    else:
        print("⚠️  Some steps had issues (see above)")
    
    return all_success


async def main():
    """Main test runner."""
    print("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║           TRINITY CORE - REAL WORLD TEST DEMO             ║
║                                                           ║
║  Testing unified automation across:                       ║
║    • Browser (Web)                                        ║
║    • Desktop (Windows UI)                                 ║
║    • CLI (PowerShell)                                     ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Check API key
    if not os.getenv("GEMINI_API_KEY"):
        print("❌ ERROR: GEMINI_API_KEY environment variable not set!")
        print("\nSet it with:")
        print('  $env:GEMINI_API_KEY = "your_key_here"')
        return
    
    print("✓ GEMINI_API_KEY is set\n")
    
    # Configuration
    config = TrinityConfig.from_env()
    config.debug_mode = True  # Enable verbose logging
    config.browser.headless = False  # Show browser for demo
    
    results = {}
    
    try:
        async with TrinityExecutor(config=config) as executor:
            # 1. Health Check
            results['health'] = await test_health_check(executor)
            
            if not results['health']:
                print("❌ Some modules are not healthy. Check setup!")
                return
            
            # Ask user which tests to run
            print("\nSelect tests to run:")
            print("  1 = Browser task only")
            print("  2 = Desktop task only")
            print("  3 = CLI task only")
            print("  4 = All individual tasks")
            print("  5 = Cross-domain workflow (recommended)")
            print("  6 = All tests")
            
            choice = input("\nEnter choice (default: 5): ").strip() or "5"
            
            # Execute tests based on choice
            if choice in ["1", "4", "6"]:
                results['browser'] = await test_browser_task(executor)
            
            if choice in ["2", "4", "6"]:
                results['desktop'] = await test_desktop_task(executor)
            
            if choice in ["3", "4", "6"]:
                results['cli'] = await test_cli_task(executor)
            
            if choice in ["5", "6"]:
                results['workflow'] = await test_cross_domain_workflow(executor)
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    
    # Final summary
    print_header("TEST SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"Results: {passed}/{total} tests passed")
    for test_name, passed in results.items():
        icon = "✓" if passed else "✗"
        print(f"  {icon} {test_name}")
    
    print("\n📁 FlightReports saved to: _runtime/flight_reports/")
    print("   Review these for detailed execution logs\n")
    
    if passed == total:
        print("🎉 All tests passed! Trinity Core is working correctly!")
    else:
        print("⚠️  Some tests failed. Check logs for details.")


if __name__ == "__main__":
    asyncio.run(main())
