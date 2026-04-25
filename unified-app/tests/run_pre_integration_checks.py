"""Pre-integration verification script - Simplified for MCP-First Architecture.

Tests environment and LLM provider setup without legacy infrastructure.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"âœ… Loaded environment from {env_path}")
except ImportError:
    print("âš ï¸  python-dotenv not installed, skipping .env file loading")

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

    print(f"GEMINI_API_KEY: {'âœ… SET' if gemini_key else 'âŒ NOT SET'}")
    print(f"OPENAI_API_KEY: {'âœ… SET (optional)' if openai_key else 'âš ï¸  NOT SET (optional)'}")

    if not gemini_key:
        print("\nâš ï¸  WARNING: GEMINI_API_KEY not set - integration tests will fail!")
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
        "fastmcp": "fastmcp",
    }

    all_ok = True
    for module, package in required.items():
        try:
            __import__(module.split('.')[0])
            print(f"âœ… {package}")
        except ImportError:
            print(f"âŒ {package} - NOT INSTALLED")
            all_ok = False

    return all_ok


async def test_providers():
    """Test provider factory and basic setup."""
    print_section("3. LLM PROVIDERS")

    try:
        from orchestrator.providers.factory import make_provider
        
        # Verify we can create a provider without legacy cache/module complexity
        gemini_key = os.getenv("GEMINI_API_KEY", "dummy")
        provider = make_provider("gemini", gemini_key)
        print(f"âœ… Gemini provider created (Type: {type(provider).__name__})")

        return True
    except Exception as e:
        print(f"âŒ Providers check failed: {e}")
        return False


async def main():
    """Run core verification checks."""
    print("\n" + "="*70)
    print("  TRINITY-PILOT MCP-FIRST VERIFICATION")
    print("  Testing core dependencies and provider logic")
    print("="*70)

    results = {}

    # Synchronous tests
    results["Environment"] = test_environment()
    results["Dependencies"] = test_dependencies()

    # Async tests
    results["Providers"] = await test_providers()

    # Summary
    print_section("SUMMARY")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "âœ… PASS" if result else "âŒ FAIL"
        print(f"{status:12} {name}")

    print(f"\n{'='*70}")
    print(f"  TOTAL: {passed}/{total} checks passed")
    print(f"{'='*70}\n")

    if passed == total:
        print("âœ… CORE CHECKS PASSED - System aligned with MCP-First Architecture")
        return 0
    else:
        print("âŒ SOME CHECKS FAILED - Fix issues before proceeding")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
