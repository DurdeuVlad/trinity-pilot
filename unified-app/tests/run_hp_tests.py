"""Execute HP-01 through HP-05 tests and generate validation report."""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.mcp_test_client import MCPTestClient


# HP test definitions from synthetic-user-battle-tester.md
HP_TESTS = {
    "HP-01": {
        "description": "List all Python files in the current directory",
        "domain": "cli",
        "expected_duration": 5
    },
    "HP-02": {
        "description": "Open Google in browser and search for 'Python tutorial'",
        "domain": "browser",
        "expected_duration": 10
    },
    "HP-03": {
        "description": "Open Notepad and type 'Hello World'",
        "domain": "desktop",
        "expected_duration": 8
    },
    "HP-04": {
        "description": "List Python files using CLI, then open the first file in browser",
        "domain": "mixed",
        "expected_duration": 12
    },
    "HP-05": {
        "description": "Search 'Python tutorial' on Google in browser, then copy the first result title to Notepad",
        "domain": "mixed",
        "expected_duration": 15
    }
}


async def run_test(client: MCPTestClient, test_id: str, test_spec: dict) -> dict:
    """Run a single HP test and return results."""
    print(f"\n{'='*80}")
    print(f"Running {test_id}: {test_spec['description']}")
    print(f"Domain: {test_spec['domain']}")
    print(f"{'='*80}\n")

    start_time = datetime.now()

    try:
        # Submit task via MCP
        result = await client.submit_task(test_spec['description'], test_spec['domain'])
        task_id = result.get('task_id')

        if not task_id:
            return {
                "test_id": test_id,
                "status": "failed",
                "error": "Task submission failed - no task_id returned",
                "result": result
            }

        print(f"✅ Task submitted: {task_id}")
        print(f"   Status: {result.get('status')}")

        # Wait for task to complete
        max_wait = test_spec['expected_duration'] + 10  # Add buffer
        wait_interval = 1
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(wait_interval)
            elapsed += wait_interval

            status = await client.get_task_status(task_id)
            current_status = status.get('status') or status.get('state', 'unknown')

            print(f"   [{elapsed}s] Status: {current_status}")

            if current_status in ['completed', 'failed', 'error']:
                break

        # Get final task details
        details = await client.get_task_details(task_id)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        final_status = details.get('task', {}).get('status') if 'task' in details else details.get('status', 'unknown')

        return {
            "test_id": test_id,
            "task_id": task_id,
            "status": "passed" if final_status == "completed" else "failed",
            "final_status": final_status,
            "duration": duration,
            "description": test_spec['description'],
            "domain": test_spec['domain'],
            "details": details
        }

    except Exception as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        return {
            "test_id": test_id,
            "status": "error",
            "error": str(e),
            "duration": duration,
            "description": test_spec['description'],
            "domain": test_spec['domain']
        }


async def main():
    """Run all HP tests and generate report."""
    client = MCPTestClient()
    results = []

    try:
        print("Connecting to MCP server...")
        await client.connect()
        print("✅ Connected\n")

        # Run each HP test
        for test_id, test_spec in HP_TESTS.items():
            result = await run_test(client, test_id, test_spec)
            results.append(result)

            # Brief pause between tests
            if test_id != "HP-05":
                print(f"\nWaiting 3 seconds before next test...")
                await asyncio.sleep(3)

        # Generate summary
        print(f"\n{'='*80}")
        print("TEST SUITE SUMMARY")
        print(f"{'='*80}\n")

        passed = sum(1 for r in results if r['status'] == 'passed')
        failed = sum(1 for r in results if r['status'] == 'failed')
        errors = sum(1 for r in results if r['status'] == 'error')

        print(f"Total tests: {len(results)}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Errors: {errors}")
        print()

        for result in results:
            status_icon = "✅" if result['status'] == 'passed' else "❌"
            print(f"{status_icon} {result['test_id']}: {result['status'].upper()}")
            if 'description' in result:
                print(f"   Description: {result['description']}")
            print(f"   Duration: {result.get('duration', 0):.1f}s")
            if result.get('error'):
                print(f"   Error: {result['error']}")
            print()

        # Save results to JSON
        results_file = Path(__file__).parent.parent.parent / "reports" / "hp_test_results.json"
        results_file.parent.mkdir(exist_ok=True)

        with open(results_file, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total": len(results),
                    "passed": passed,
                    "failed": failed,
                    "errors": errors
                },
                "results": results
            }, f, indent=2, default=str)

        print(f"Results saved to: {results_file}")

        return 0 if passed == len(results) else 1

    except Exception as e:
        print(f"\n❌ Test suite error: {e}")
        import traceback
        traceback.print_exc()
        return 2
    finally:
        await client.disconnect()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
