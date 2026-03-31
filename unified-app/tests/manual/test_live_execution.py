"""Live test of orchestrator execution."""
import asyncio
import os
import sys
from pathlib import Path

module_root = Path(__file__).resolve().parents[2]
if str(module_root) not in sys.path:
    sys.path.insert(0, str(module_root))

if os.getenv("GEMINI_MOCK"):
    from testing.gemini_mock.activator import activate

    activate()

from orchestrator.macro_planner import MacroPlanner
from orchestrator.trinity_bridge import TrinityBridge

PASS = "[PASS]"
FAIL = "[FAIL]"


async def test_simple_cli_task():
    """Test a simple CLI task end-to-end."""
    print("=" * 60)
    print("Testing: Simple CLI Task")
    print("=" * 60)

    print("\n1. Testing MacroPlanner...")
    planner = MacroPlanner()
    task_description = "List files in the current directory"
    domain = "cli"

    try:
        plan = await planner.generate_plan(task_description, domain)
        print(f"{PASS} Plan generated with {len(plan.steps)} steps")
        print(f"  Confidence: {plan.confidence:.0%}")
        print("  Steps:")
        for index, step in enumerate(plan.steps, start=1):
            print(f"    {index}. {step}")
    except Exception as exc:
        print(f"{FAIL} Planner failed: {exc}")
        import traceback

        traceback.print_exc()
        return False

    print("\n2. Testing TrinityBridge...")
    bridge = TrinityBridge()

    try:
        await bridge.initialize()
        print(f"{PASS} Trinity bridge initialized")
    except Exception as exc:
        print(f"{FAIL} Bridge initialization failed: {exc}")
        import traceback

        traceback.print_exc()
        return False

    print(f"\n3. Executing step: {plan.steps[0]}")
    try:
        result = await bridge.execute_task(
            task_id="test_001",
            description=plan.steps[0],
            domain=domain,
        )
        print(f"{PASS} Task executed")
        print(f"  Status: {result.status}")
        if hasattr(result, "error") and result.error:
            print(f"  Error: {result.error}")
        if result.status != "success":
            return False
    except Exception as exc:
        print(f"{FAIL} Execution failed: {exc}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        await bridge.shutdown()
        print(f"\n{PASS} Bridge shutdown complete")

    print("\n" + "=" * 60)
    print("TEST COMPLETE - ALL PASSED!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_simple_cli_task())
    sys.exit(0 if success else 1)
