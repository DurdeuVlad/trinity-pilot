import logging
from typing import Optional

from .backend_router import BackendRouter

logger = logging.getLogger(__name__)

_router: Optional[BackendRouter] = None


def _get_router() -> BackendRouter:
    """Get or create singleton BackendRouter instance."""
    global _router
    if _router is None:
        _router = BackendRouter()
    return _router


async def desktop_task(description: str, context: Optional[str] = None) -> dict:
    """
    Execute a desktop automation task via MCP or HTTP based on feature flag.
    
    Args:
        description: Natural language task description
        context: Optional additional context
        
    Returns:
        dict with keys: result, steps_taken, error
    """
    router = _get_router()
    return await router.desktop_task(description, context)


async def cli_task(description: str, context: Optional[str] = None) -> dict:
    """
    Execute a CLI/PowerShell task via MCP or HTTP based on feature flag.
    
    Args:
        description: Natural language task description
        context: Optional additional context
        
    Returns:
        dict with keys: result, steps_taken, error
    """
    router = _get_router()
    return await router.cli_task(description, context)


async def browser_task(description: str, context: Optional[str] = None) -> dict:
    """
    Execute a browser automation task via MCP or HTTP based on feature flag.
    
    Args:
        description: Natural language task description
        context: Optional additional context
        
    Returns:
        dict with keys: result, steps_taken, error
    """
    router = _get_router()
    return await router.browser_task(description, context)
