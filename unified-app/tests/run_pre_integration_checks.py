"""Pre-integration verification script - Run before AI integration testing.

Tests all programmed orchestrator logic without requiring live AI calls.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded environment from {env_path}")
except ImportError:
    print("⚠️  python-dotenv not installed, skipping .env file loading")
    print("   Install with: pip install python-dotenv")

def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def test_environment():
    """Check environment variables."""
    print_section("1. ENVIRONMENT VARIABLES")
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    print(f"GEMINI_API_KEY: {'✅ SET' if gemini_key else '❌ NOT SET'}")
    print(f"OPENAI_API_KEY: {'✅ SET (optional)' if openai_key else '⚠️  NOT SET (optional)'}")
    
    if not gemini_key:
        print("\n⚠️  WARNING: GEMINI_API_KEY not set - integration tests will fail!")
        return False
    
    return True


def test_dependencies():
    """Check required packages."""
    print_section("2. DEPENDENCIES")
    
    required = {
        "google.genai": "google-genai",
        "openai": "openai",
        "PyQt6": "PyQt6",
        "httpx": "httpx",
        "playwright": "playwright",
    }
    
    all_ok = True
    for module, package in required.items():
        try:
            __import__(module.split('.')[0])
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - NOT INSTALLED")
            all_ok = False
    
    return all_ok


async def test_service_manager():
    """Test ServiceManager lifecycle."""
    print_section("3. SERVICE MANAGER")
    
    try:
        from orchestrator.service_manager import ServiceManager
        
        sm = ServiceManager()
        print("✅ ServiceManager imported")
        
        # Don't actually start services - just verify the class works
        print("✅ ServiceManager instantiated")
        print("⚠️  Skipping actual service start (manual test)")
        
        return True
    except Exception as e:
        print(f"❌ ServiceManager failed: {e}")
        return False


async def test_checkpoint_manager():
    """Test checkpoint save/load."""
    print_section("4. CHECKPOINT MANAGER")
    
    try:
        from orchestrator.checkpoint_manager import CheckpointManager
        from orchestrator.execution_context import ExecutionContext
        
        cm = CheckpointManager()
        print("✅ CheckpointManager imported")
        
        # Create test context
        ctx = ExecutionContext(objective="test checkpoint")
        # ExecutionContext doesn't have add_step - just test save/load
        
        # Save checkpoint
        task_id = "test-task-001"
        cp_id = cm.save_checkpoint(task_id, ctx, 0)
        print(f"✅ Checkpoint saved: {cp_id}")
        
        # Load checkpoint
        loaded_ctx, idx = cm.load_checkpoint(cp_id)
        print(f"✅ Checkpoint loaded: objective='{loaded_ctx.objective}', index={idx}")
        
        # Verify
        assert loaded_ctx.objective == "test checkpoint", "Objective mismatch"
        assert idx == 0, "Index mismatch"
        print("✅ Checkpoint data verified")
        
        # Cleanup
        latest = cm.get_latest_checkpoint(task_id)
        if latest:
            cm.delete_checkpoint(latest)
            print("✅ Checkpoint cleaned up")
        
        return True
    except Exception as e:
        print(f"❌ CheckpointManager failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_event_bus():
    """Test event bus emission."""
    print_section("5. EVENT BUS")
    
    try:
        from orchestrator.event_bus import get_event_bus
        
        bus = get_event_bus()
        print("✅ EventBus imported")
        
        # Test emission (won't actually do anything without listeners)
        # Use correct signal name: status_update (not status_updated)
        bus.status_update.emit("test message", "info")
        print("✅ Event emission works")
        
        return True
    except Exception as e:
        print(f"❌ EventBus failed: {e}")
        return False


async def test_trinity_bridge():
    """Test TrinityBridge initialization."""
    print_section("6. TRINITY BRIDGE")
    
    try:
        from orchestrator.trinity_bridge import TrinityBridge
        
        bridge = TrinityBridge()
        print("✅ TrinityBridge imported")
        print("✅ TrinityBridge instantiated")
        print("⚠️  Skipping initialization (requires module services)")
        
        return True
    except Exception as e:
        print(f"❌ TrinityBridge failed: {e}")
        return False


async def test_providers():
    """Test provider imports and basic setup."""
    print_section("7. LLM PROVIDERS")
    
    try:
        from orchestrator.providers.factory import make_provider
        from orchestrator.providers.gemini_provider import GeminiProvider
        from orchestrator.providers.openai_provider import OpenAIProvider
        
        print("✅ Provider factory imported")
        print("✅ GeminiProvider imported")
        print("✅ OpenAIProvider imported")
        
        # Don't actually probe - just verify we can create them
        gemini_key = os.getenv("GEMINI_API_KEY", "dummy")
        provider = make_provider("gemini", gemini_key)
        print("✅ Gemini provider created")
        
        return True
    except Exception as e:
        print(f"❌ Providers failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_module_service_provider():
    """Test module service provider."""
    print_section("8. MODULE SERVICE PROVIDER")
    
    try:
        from orchestrator.providers.gemini_module_provider import make_gemini_module_provider
        
        print("✅ Gemini module provider imported")
        
        gemini_key = os.getenv("GEMINI_API_KEY", "dummy")
        provider = make_gemini_module_provider(gemini_key)
        print("✅ Gemini module provider created")
        print(f"✅ Model: {provider.model}")
        
        return True
    except Exception as e:
        print(f"❌ Module service provider failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all pre-integration checks."""
    print("\n" + "="*70)
    print("  TRINITY-PILOT PRE-INTEGRATION VERIFICATION")
    print("  Testing orchestrator programmed logic (no AI required)")
    print("="*70)
    
    results = {}
    
    # Synchronous tests
    results["Environment"] = test_environment()
    results["Dependencies"] = test_dependencies()
    
    # Async tests
    results["ServiceManager"] = await test_service_manager()
    results["CheckpointManager"] = await test_checkpoint_manager()
    results["EventBus"] = await test_event_bus()
    results["TrinityBridge"] = await test_trinity_bridge()
    results["Providers"] = await test_providers()
    results["ModuleServiceProvider"] = await test_module_service_provider()
    
    # Summary
    print_section("SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:12} {name}")
    
    print(f"\n{'='*70}")
    print(f"  TOTAL: {passed}/{total} checks passed")
    print(f"{'='*70}\n")
    
    if passed == total:
        print("✅ ALL CHECKS PASSED - Ready for integration testing!")
        print("\nNext steps:")
        print("1. Run unit tests: pytest tests/test_*.py -v")
        print("2. Start module services manually")
        print("3. Test direct module call (see checklist)")
        print("4. Run integration tests with unified app")
        return 0
    else:
        print("❌ SOME CHECKS FAILED - Fix issues before integration testing")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
