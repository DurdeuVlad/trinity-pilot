"""
Real MCP Validation - Execute actual scenarios against real MCP servers on Windows.

This is NOT a unit test. This uses real MCP stdio transport and real Windows environment.
"""

import asyncio
import json
import sys
import time
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class RealMCPClient:
    """Real MCP client using official MCP SDK - no mocks."""
    
    def __init__(self, server_script: Path, timeout: int = 30):
        self.server_script = server_script
        self.timeout = timeout
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        
    async def start(self):
        """Start the MCP server and connect."""
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(self.server_script)],
            env=None,
        )
        
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        stdio, write = stdio_transport
        
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(stdio, write)
        )
        
        await self.session.initialize()
        
    async def stop(self):
        """Stop the MCP server and cleanup."""
        await self.exit_stack.aclose()
                
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """Call an MCP tool and return parsed JSON response."""
        if not self.session:
            raise RuntimeError("MCP server not started")
            
        result = await asyncio.wait_for(
            self.session.call_tool(tool_name, arguments or {}),
            timeout=self.timeout
        )
        
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, "text"):
                text = content.text
                # MCP servers return JSON string in text field
                # But sometimes it's already parsed to dict
                if isinstance(text, dict):
                    # Already parsed
                    return text
                elif isinstance(text, str):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as e:
                        raise RuntimeError(f"Failed to parse JSON response: {e}, text: {text[:200]}")
                else:
                    raise RuntimeError(f"Unexpected text type: {type(text)}, value: {text}")
        
        raise RuntimeError(f"Unexpected result format: {result}")


class ScenarioResult:
    """Result of a single scenario execution."""
    
    def __init__(self, name: str):
        self.name = name
        self.status = "PENDING"  # PASS / PARTIAL / FAIL / TIMEOUT / ERROR
        self.started_at = datetime.now()
        self.completed_at = None
        self.duration_ms = 0
        self.steps: List[str] = []
        self.errors: List[str] = []
        self.windows_evidence: List[str] = []
        self.artifacts: List[str] = []
        self.session_id: Optional[str] = None
        
    def add_step(self, step: str):
        self.steps.append(f"[{datetime.now().strftime('%H:%M:%S')}] {step}")
        
    def add_error(self, error: str):
        self.errors.append(error)
        
    def add_windows_evidence(self, evidence: str):
        self.windows_evidence.append(evidence)
        
    def complete(self, status: str):
        self.status = status
        self.completed_at = datetime.now()
        self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)


async def run_scenario(
    client: RealMCPClient,
    scenario_name: str,
    objective: str,
    context: Dict[str, Any] = None,
    verify_fn = None
) -> ScenarioResult:
    """
    Run a single MCP scenario with full lifecycle.
    
    Returns ScenarioResult with actual Windows behavior evidence.
    """
    result = ScenarioResult(scenario_name)
    session_id = None
    
    try:
        # Step 1: Health check
        result.add_step("Calling health...")
        health_data = await client.call_tool("health")
        result.add_step(f"Health: ok={health_data.get('ok')}, status={health_data.get('status')}")
        
        if not health_data.get("ok"):
            result.add_error("Health check failed")
            result.complete("FAIL")
            return result
            
        # Step 2: Create session (skipping list_capabilities for simplicity)
        result.add_step("Calling create_session...")
        create_data = await client.call_tool("create_session")
        session_id = create_data.get("session_id")
        result.session_id = session_id
        result.add_step(f"Session created: {session_id}")
        
        if not session_id:
            result.add_error("Failed to create session")
            result.complete("FAIL")
            return result
            
        # Step 4: Run objective
        result.add_step(f"Running objective: {objective}")
        run_args = {
            "session_id": session_id,
            "objective_id": f"scenario-{int(time.time())}",
            "objective": objective,
        }
        if context:
            run_args["context"] = context
            
        run_data = await asyncio.wait_for(
            client.call_tool("run_objective", run_args),
            timeout=60
        )
        result.add_step(f"Objective status: {run_data.get('status')}")
        
        # Step 5: Read events
        result.add_step("Reading events...")
        events_data = await client.call_tool("read_events", {"session_id": session_id})
        events = events_data.get("events", [])
        result.add_step(f"Events received: {len(events)}")
        
        # Step 6: Get status
        result.add_step("Getting status...")
        status_data = await client.call_tool("get_status", {"session_id": session_id})
        result.add_step(f"Final status: {status_data.get('status')}")
        
        # Step 7: List artifacts
        result.add_step("Listing artifacts...")
        artifacts_data = await client.call_tool("list_artifacts", {"session_id": session_id})
        artifacts = artifacts_data.get("artifacts", [])
        result.add_step(f"Artifacts found: {len(artifacts)}")
        result.artifacts = [a.get("artifact_type", "unknown") for a in artifacts]
        
        # Verify actual Windows behavior
        if verify_fn:
            result.add_step("Verifying Windows behavior...")
            verification = verify_fn(run_data, events_data, artifacts_data)
            result.windows_evidence.extend(verification)
            
        # Determine result status
        if run_data.get("status") == "completed":
            result.complete("PASS")
        elif run_data.get("status") == "failed":
            result.add_error(f"Objective failed: {run_data.get('error', 'unknown')}")
            result.complete("PARTIAL" if events else "FAIL")
        else:
            result.complete("PARTIAL")
            
    except asyncio.TimeoutError:
        result.add_error("Scenario timed out")
        result.complete("TIMEOUT")
        
    except Exception as e:
        result.add_error(f"Exception: {str(e)}")
        result.complete("ERROR")
        
    finally:
        # Step 8: Close session
        if session_id:
            try:
                result.add_step("Closing session...")
                await client.call_tool("close_session", {"session_id": session_id})
                result.add_step("Session closed")
            except Exception as e:
                result.add_error(f"Failed to close session: {e}")
                
    return result


def print_scenario_result(result: ScenarioResult):
    """Print a scenario result in readable format."""
    print(f"\n{'='*80}")
    print(f"SCENARIO: {result.name}")
    print(f"STATUS: {result.status}")
    print(f"DURATION: {result.duration_ms}ms")
    print(f"SESSION: {result.session_id}")
    print(f"{'='*80}")
    
    print("\nSTEPS:")
    for step in result.steps:
        print(f"  {step}")
        
    if result.windows_evidence:
        print("\nWINDOWS EVIDENCE:")
        for evidence in result.windows_evidence:
            print(f"  [+] {evidence}")
            
    if result.artifacts:
        print(f"\nARTIFACTS: {', '.join(result.artifacts)}")
        
    if result.errors:
        print("\nERRORS:")
        for error in result.errors:
            print(f"  [-] {error}")


async def main():
    """Execute all real MCP validation scenarios."""
    print("="*80)
    print("REAL MCP VALIDATION - Windows Environment")
    print("="*80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    trinity_pilot = Path(__file__).parent
    
    # ========================================================================
    # CLI BACKEND SCENARIOS
    # ========================================================================
    print("\n" + "="*80)
    print("CLI BACKEND - Real Scenarios")
    print("="*80)
    
    cli_server = trinity_pilot / "cli-automation-poc" / "cli_mcp_server.py"
    cli_results = []
    
    if cli_server.exists():
        client = RealMCPClient(cli_server)
        
        try:
            await client.start()
            print("[OK] CLI MCP server started")
            
            # Scenario 1: List files in project directory
            result = await run_scenario(
                client,
                "CLI-1: List files in known directory",
                "List files in the current directory using PowerShell Get-ChildItem",
                verify_fn=lambda run, events, artifacts: [
                    "PowerShell command executed" if "Get-ChildItem" in str(run) or "ls" in str(run) else "No PowerShell evidence",
                    f"Events captured: {len(events.get('events', []))}" if events.get('events') else "No events"
                ]
            )
            cli_results.append(result)
            print_scenario_result(result)
            
            # Scenario 2: Read a known file
            result = await run_scenario(
                client,
                "CLI-2: Read known file",
                "Read the contents of README.md using PowerShell Get-Content",
                verify_fn=lambda run, events, artifacts: [
                    "File read command executed" if "Get-Content" in str(run) or "cat" in str(run) else "No file read evidence",
                    f"Output present: {bool(run.get('result', {}).get('output'))}"
                ]
            )
            cli_results.append(result)
            print_scenario_result(result)
            
            # Scenario 3: Rejected command
            result = await run_scenario(
                client,
                "CLI-3: Verify command rejection",
                "Delete all files in C:\\ (should be rejected by safety validator)",
                context={"command": "Remove-Item C:\\* -Recurse -Force"},
                verify_fn=lambda run, events, artifacts: [
                    "Validator rejection detected" if run.get('result', {}).get('failure_category') == 'validator_rejection' else "No rejection",
                    f"Error message: {run.get('error', 'none')[:50]}"
                ]
            )
            cli_results.append(result)
            print_scenario_result(result)
            
        finally:
            await client.stop()
            print("\n[OK] CLI MCP server stopped")
    else:
        print(f"[FAIL] CLI server not found at {cli_server}")
        
    # ========================================================================
    # BROWSER BACKEND SCENARIOS
    # ========================================================================
    print("\n" + "="*80)
    print("BROWSER BACKEND - Real Scenarios")
    print("="*80)
    
    browser_server = trinity_pilot / "browser-gui-automation" / "browser_mcp_server.py"
    browser_results = []
    
    if browser_server.exists():
        client = RealMCPClient(browser_server, timeout=45)
        
        try:
            await client.start()
            print("[OK] Browser MCP server started")
            
            # Scenario 1: Open stable page
            result = await run_scenario(
                client,
                "Browser-1: Navigate to example.com",
                "Navigate to https://example.com and report the page title",
                verify_fn=lambda run, events, artifacts: [
                    "Navigation completed" if "example" in str(run).lower() else "No navigation evidence",
                    f"Page title captured: {bool('title' in str(run).lower())}",
                    f"Events: {len(events.get('events', []))}"
                ]
            )
            browser_results.append(result)
            print_scenario_result(result)
            
            # Scenario 2: Capture artifacts
            result = await run_scenario(
                client,
                "Browser-2: Capture screenshot artifact",
                "Navigate to https://example.com and take a screenshot",
                verify_fn=lambda run, events, artifacts: [
                    f"Screenshot artifact: {any(a.get('artifact_type') == 'screenshot' for a in artifacts.get('artifacts', []))}",
                    f"Total artifacts: {len(artifacts.get('artifacts', []))}"
                ]
            )
            browser_results.append(result)
            print_scenario_result(result)
            
            # Scenario 3: Failure case
            result = await run_scenario(
                client,
                "Browser-3: Handle navigation failure",
                "Navigate to https://this-domain-definitely-does-not-exist-12345.com",
                verify_fn=lambda run, events, artifacts: [
                    "Failure detected" if run.get('status') == 'failed' else "No failure",
                    f"Failure category: {run.get('result', {}).get('failure_category', 'none')}",
                    f"Error handling: {bool(run.get('error'))}"
                ]
            )
            browser_results.append(result)
            print_scenario_result(result)
            
        finally:
            await client.stop()
            print("\n[OK] Browser MCP server stopped")
    else:
        print(f"[FAIL] Browser server not found at {browser_server}")
        
    # ========================================================================
    # DESKTOP BACKEND SCENARIOS
    # ========================================================================
    print("\n" + "="*80)
    print("DESKTOP BACKEND - Real Scenarios")
    print("="*80)
    
    desktop_server = trinity_pilot / "api-accessibility-poc" / "desktop_mcp_server.py"
    desktop_results = []
    
    if desktop_server.exists():
        client = RealMCPClient(desktop_server, timeout=45)
        
        try:
            await client.start()
            print("[OK] Desktop MCP server started")
            
            # Scenario 1: List open windows
            result = await run_scenario(
                client,
                "Desktop-1: List open windows",
                "List all currently open windows on the desktop",
                verify_fn=lambda run, events, artifacts: [
                    "Windows listed" if "window" in str(run).lower() else "No window evidence",
                    f"Output present: {bool(run.get('result', {}).get('output'))}",
                    f"Events: {len(events.get('events', []))}"
                ]
            )
            desktop_results.append(result)
            print_scenario_result(result)
            
            # Scenario 2: Capture desktop artifacts
            result = await run_scenario(
                client,
                "Desktop-2: Capture UIA tree or screenshot",
                "Inspect the desktop and capture UI automation tree",
                verify_fn=lambda run, events, artifacts: [
                    f"UIA artifact: {any('uia' in a.get('artifact_type', '').lower() for a in artifacts.get('artifacts', []))}",
                    f"Screenshot artifact: {any('screenshot' in a.get('artifact_type', '').lower() for a in artifacts.get('artifacts', []))}",
                    f"Total artifacts: {len(artifacts.get('artifacts', []))}"
                ]
            )
            desktop_results.append(result)
            print_scenario_result(result)
            
            # Scenario 3: Rejection case
            result = await run_scenario(
                client,
                "Desktop-3: Verify app blocking",
                "Launch regedit (should be blocked by safety policy)",
                context={"blocked_apps": ["regedit"]},
                verify_fn=lambda run, events, artifacts: [
                    "Rejection detected" if run.get('result', {}).get('failure_category') == 'validator_rejection' else "No rejection",
                    f"Error: {run.get('error', 'none')[:50]}"
                ]
            )
            desktop_results.append(result)
            print_scenario_result(result)
            
        finally:
            await client.stop()
            print("\n[OK] Desktop MCP server stopped")
    else:
        print(f"[FAIL] Desktop server not found at {desktop_server}")
        
    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    
    def summarize_backend(name: str, results: List[ScenarioResult]):
        if not results:
            print(f"\n{name}: NOT TESTED")
            return
            
        passed = sum(1 for r in results if r.status == "PASS")
        partial = sum(1 for r in results if r.status == "PARTIAL")
        failed = sum(1 for r in results if r.status in ["FAIL", "ERROR", "TIMEOUT"])
        
        if passed == len(results):
            usability = "USABLE"
        elif passed > 0 or partial > 0:
            usability = "PARTIAL"
        else:
            usability = "BLOCKED"
            
        print(f"\n{name}: {usability}")
        print(f"  Results: {passed} PASS, {partial} PARTIAL, {failed} FAIL")
        
        # Top blocker
        blockers = []
        for r in results:
            if r.status in ["FAIL", "ERROR", "TIMEOUT"]:
                blockers.extend(r.errors)
        if blockers:
            print(f"  Top blocker: {blockers[0]}")
        else:
            print(f"  Top blocker: None")
            
        # Top success
        successes = [r for r in results if r.status == "PASS"]
        if successes:
            print(f"  Top success: {successes[0].name}")
        else:
            print(f"  Top success: None")
            
    summarize_backend("CLI BACKEND", cli_results)
    summarize_backend("BROWSER BACKEND", browser_results)
    summarize_backend("DESKTOP BACKEND", desktop_results)
    
    print(f"\n{'='*80}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
