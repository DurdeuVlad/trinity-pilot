"""
Backend MCP Validation Helper

Simple script to validate a backend MCP server's basic functionality.
This is a lightweight alternative to running the full conformance suite.

Usage:
    python scripts/validate_backend_mcp.py cli
    python scripts/validate_backend_mcp.py browser
    python scripts/validate_backend_mcp.py desktop
"""
import asyncio
import json
import sys
from pathlib import Path
from contextlib import AsyncExitStack

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class BackendValidator:
    """Lightweight backend MCP validator."""
    
    def __init__(self, backend_id: str):
        self.backend_id = backend_id
        self.server_script = self._get_server_script()
        self.session = None
        self.exit_stack = AsyncExitStack()
        self.stdio = None
        self.write = None
        self.test_session_id = None
        
    def _get_server_script(self) -> Path:
        """Get server script path for backend."""
        scripts = {
            "cli": Path(__file__).parent.parent / "cli-automation-poc" / "cli_mcp_server.py",
            "browser": Path(__file__).parent.parent / "browser-gui-automation" / "browser_mcp_server.py",
            "desktop": Path(__file__).parent.parent / "api-accessibility-poc" / "desktop_mcp_server.py",
        }
        
        if self.backend_id not in scripts:
            raise ValueError(f"Unknown backend: {self.backend_id}. Must be cli, browser, or desktop.")
        
        script = scripts[self.backend_id]
        
        if not script.exists():
            raise FileNotFoundError(f"Backend server not found: {script}")
        
        return script
    
    async def connect(self):
        """Connect to backend MCP server."""
        print(f"[*] Connecting to {self.backend_id} backend MCP server...")
        
        server_params = StdioServerParameters(
            command="python",
            args=[str(self.server_script)],
            env=None,
        )
        
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )
        
        await self.session.initialize()
        print(f"[✓] Connected to {self.backend_id} backend")
    
    async def disconnect(self):
        """Disconnect from backend MCP server."""
        await self.exit_stack.aclose()
    
    async def call_tool(self, name: str, arguments: dict | None = None):
        """Call an MCP tool and return parsed JSON response."""
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self.session.call_tool(name, arguments or {})
        
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, "text"):
                return json.loads(content.text)
        
        raise RuntimeError(f"Unexpected result format: {result}")
    
    async def validate_health(self):
        """Validate health check."""
        print("\n[*] Validating health check...")
        result = await self.call_tool("health")
        
        assert result["ok"] is True, "Health check failed"
        assert result["metadata"]["backend_id"] == self.backend_id, "Backend ID mismatch"
        
        print(f"[✓] Health check passed (status: {result['status']})")
    
    async def validate_capabilities(self):
        """Validate capability listing."""
        print("\n[*] Validating capabilities...")
        result = await self.call_tool("list_capabilities")
        
        assert result["ok"] is True, "List capabilities failed"
        assert len(result.get("capabilities", [])) > 0, "No capabilities returned"
        
        cap_ids = [cap["capability_id"] for cap in result["capabilities"]]
        print(f"[✓] Capabilities: {', '.join(cap_ids)}")
    
    async def validate_tools(self):
        """Validate required tools exist."""
        print("\n[*] Validating required tools...")
        tools = await self.session.list_tools()
        tool_names = [t.name for t in tools.tools]
        
        required_tools = [
            "health", "list_capabilities", "create_session", "run_objective",
            "read_events", "get_status", "interrupt", "terminate",
            "close_session", "list_artifacts"
        ]
        
        missing = [t for t in required_tools if t not in tool_names]
        assert len(missing) == 0, f"Missing required tools: {missing}"
        
        print(f"[✓] All 10 required tools present")
    
    async def validate_session_lifecycle(self):
        """Validate session creation and lifecycle."""
        print("\n[*] Validating session lifecycle...")
        
        # Create session
        create_result = await self.call_tool("create_session")
        assert create_result["ok"] is True, "Create session failed"
        assert create_result["status"] == "created", "Session status not 'created'"
        assert create_result["session_id"] is not None, "No session_id returned"
        
        self.test_session_id = create_result["session_id"]
        print(f"[✓] Session created: {self.test_session_id}")
        
        # Get status
        status_result = await self.call_tool("get_status", {"session_id": self.test_session_id})
        assert status_result["ok"] is True, "Get status failed"
        assert status_result["session_id"] == self.test_session_id, "Session ID mismatch"
        print(f"[✓] Session status: {status_result['status']}")
        
        # Read events
        events_result = await self.call_tool("read_events", {"session_id": self.test_session_id})
        assert events_result["ok"] is True, "Read events failed"
        assert len(events_result["events"]) > 0, "No events emitted"
        
        event_types = [e["event_type"] for e in events_result["events"]]
        assert "session_created" in event_types, "session_created event not found"
        print(f"[✓] Events: {', '.join(event_types)}")
    
    async def validate_envelope_keys(self):
        """Validate response envelope keys."""
        print("\n[*] Validating response envelope...")
        
        result = await self.call_tool("health")
        
        required_keys = ["ok", "status", "session_id", "result", "error", "events", "artifacts", "metadata"]
        missing = [k for k in required_keys if k not in result]
        
        assert len(missing) == 0, f"Missing envelope keys: {missing}"
        print(f"[✓] All 8 envelope keys present")
    
    async def validate_incremental_events(self):
        """Validate incremental event reads."""
        print("\n[*] Validating incremental event reads...")
        
        if not self.test_session_id:
            print("[!] Skipping (no test session)")
            return
        
        # Read all events
        all_events_result = await self.call_tool("read_events", {"session_id": self.test_session_id})
        all_events = all_events_result["events"]
        
        if len(all_events) == 0:
            print("[!] No events to test incremental reads")
            return
        
        last_sequence = all_events[-1]["sequence"]
        
        # Read events after last sequence (should be empty)
        incremental_result = await self.call_tool("read_events", {
            "session_id": self.test_session_id,
            "after_sequence": last_sequence
        })
        
        assert len(incremental_result["events"]) == 0, "Incremental read should return empty list"
        print(f"[✓] Incremental event reads work correctly")
    
    async def validate_cleanup(self):
        """Validate session cleanup."""
        print("\n[*] Validating session cleanup...")
        
        if not self.test_session_id:
            print("[!] Skipping (no test session)")
            return
        
        close_result = await self.call_tool("close_session", {"session_id": self.test_session_id})
        assert close_result["ok"] is True, "Close session failed"
        
        print(f"[✓] Session closed successfully")
        self.test_session_id = None
    
    async def run_validation(self):
        """Run all validation checks."""
        try:
            await self.connect()
            
            await self.validate_health()
            await self.validate_capabilities()
            await self.validate_tools()
            await self.validate_envelope_keys()
            await self.validate_session_lifecycle()
            await self.validate_incremental_events()
            await self.validate_cleanup()
            
            print(f"\n{'='*60}")
            print(f"[✓] All validation checks passed for {self.backend_id} backend")
            print(f"{'='*60}\n")
            
        except AssertionError as e:
            print(f"\n{'='*60}")
            print(f"[✗] Validation failed: {e}")
            print(f"{'='*60}\n")
            sys.exit(1)
        
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"[✗] Unexpected error: {e}")
            print(f"{'='*60}\n")
            sys.exit(1)
        
        finally:
            # Cleanup test session if still exists
            if self.test_session_id:
                try:
                    await self.call_tool("close_session", {"session_id": self.test_session_id})
                except Exception:
                    pass
            
            await self.disconnect()


async def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python scripts/validate_backend_mcp.py <backend>")
        print("  backend: cli, browser, or desktop")
        sys.exit(1)
    
    backend_id = sys.argv[1].lower()
    
    validator = BackendValidator(backend_id)
    await validator.run_validation()


if __name__ == "__main__":
    asyncio.run(main())
