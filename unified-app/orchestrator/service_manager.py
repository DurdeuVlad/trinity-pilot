import asyncio
import logging
from typing import Optional

from .trinity_bridge import TrinityBridge

logger = logging.getLogger(__name__)


class ServiceManager:
    """Compatibility shim that reflects Core-visible MCP health.

    The desktop no longer launches legacy module-service subprocesses. The
    current product path executes through Trinity Core, so this manager now
    verifies Core availability and reports health for the selected MCP targets.
    """

    def __init__(self):
        self._bridge: Optional[TrinityBridge] = None

    async def _ensure_bridge(self) -> TrinityBridge:
        if self._bridge is None:
            self._bridge = TrinityBridge()
            await self._bridge.initialize()
        return self._bridge

    async def _get_health_map(self) -> dict:
        try:
            bridge = await self._ensure_bridge()
            capabilities = await bridge.get_capabilities()
            return {
                "desktop": {"status": "ok" if "desktop" in capabilities else "unavailable", "data": capabilities.get("desktop")},
                "cli": {"status": "ok" if "cli" in capabilities else "unavailable", "data": capabilities.get("cli")},
                "browser": {"status": "ok" if "web" in capabilities else "unavailable", "data": capabilities.get("web")},
            }
        except Exception as exc:
            message = str(exc)
            logger.error("Trinity Core health check failed: %s", message, exc_info=True)
            return {
                "desktop": {"status": "unavailable", "error": message},
                "cli": {"status": "unavailable", "error": message},
                "browser": {"status": "unavailable", "error": message},
            }

    def _run_async(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "ServiceManager sync methods cannot be called from a running event loop. "
            "Use the async helpers instead."
        ) from None

    def start_all(self, max_wait_per_service: float = 10.0) -> bool:
        """Verify Trinity Core and the MCP targets are reachable.

        The legacy module-service subprocesses were removed from the supported
        runtime, so this is now a readiness check rather than a process launcher.
        """
        del max_wait_per_service
        health = self._run_async(self._get_health_map())
        return all(entry.get("status") == "ok" for entry in health.values())

    def stop_all(self):
        """Release Core-side resources. No subprocesses are launched anymore."""
        if self._bridge is None:
            return
        self._run_async(self._bridge.shutdown())
        self._bridge = None

    def health_check_all(self) -> dict:
        """Return health for the Core-visible MCP targets."""
        return self._run_async(self._get_health_map())
