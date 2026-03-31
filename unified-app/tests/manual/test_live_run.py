"""Live test helper for unified-app using a real Gemini API call."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure we can import from the unified-app module root.
module_root = Path(__file__).resolve().parents[2]
if str(module_root) not in sys.path:
    sys.path.insert(0, str(module_root))

from dotenv import load_dotenv
load_dotenv(module_root / ".env")

from orchestrator.macro_planner import MacroPlanner
from orchestrator.providers.factory import make_provider
from orchestrator.trinity_bridge import TrinityBridge


async def test_real_task() -> bool:
    """Submit a real task and verify the live Gemini path is reachable."""
    print("=" * 60)
    print("LIVE TEST - Real Gemini API Call")
    print("=" * 60)

    if os.getenv("GEMINI_MOCK"):
        print("ERROR: GEMINI_MOCK is set - this should be a LIVE test")
        return False

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: No GEMINI_API_KEY found")
        return False

    print(f"OK: API Key configured: {api_key[:20]}...")
    print()

    print("Test 1: Generate plan with real Gemini API")
    print("-" * 60)

    provider = make_provider("gemini", api_key)
    planner = MacroPlanner(provider)
    task_description = "Open Notepad and type 'Hello World'"
    domain = "desktop"

    print(f"Task: {task_description}")
    print(f"Domain: {domain}")
    print()
    print("Calling Gemini API...")

    try:
        plan = await planner.generate_plan(task_description, domain)
        print("OK: Plan generated successfully!")
        print(f"   Steps: {len(plan.steps)}")
        print(f"   Confidence: {plan.confidence:.0%}")
        print(f"   Estimated duration: {plan.estimated_duration}s")
        print()
        print("Generated steps:")
        for i, step in enumerate(plan.steps, 1):
            print(f"   {i}. {step}")
        print()
    except Exception as exc:
        print(f"ERROR: Plan generation failed: {exc}")
        return False

    print("Test 2: Verify Trinity Bridge")
    print("-" * 60)

    bridge = TrinityBridge()
    try:
        await bridge.initialize()
        print("OK: Trinity Bridge initialized successfully")
        await bridge.shutdown()
        print("OK: Trinity Bridge shutdown cleanly")
        print()
    except Exception as exc:
        print(f"ERROR: Trinity Bridge error: {exc}")
        return False

    print("=" * 60)
    print("OK: ALL TESTS PASSED - App is working with real Gemini API")
    print("=" * 60)
    return True


if __name__ == "__main__":
    if "GEMINI_MOCK" in os.environ:
        del os.environ["GEMINI_MOCK"]

    success = asyncio.run(test_real_task())
    raise SystemExit(0 if success else 1)
