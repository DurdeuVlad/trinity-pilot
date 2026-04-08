import os
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DESKTOP_PORT = int(os.getenv("DESKTOP_SERVICE_PORT", "8101"))
CLI_PORT = int(os.getenv("CLI_SERVICE_PORT", "8102"))
BROWSER_PORT = int(os.getenv("BROWSER_SERVICE_PORT", "8103"))

DESKTOP_URL = f"http://127.0.0.1:{DESKTOP_PORT}"
CLI_URL = f"http://127.0.0.1:{CLI_PORT}"
BROWSER_URL = f"http://127.0.0.1:{BROWSER_PORT}"


async def desktop_task(description: str, context: Optional[str] = None) -> dict:
    """
    Execute a desktop automation task via the Desktop Module Service.
    
    Args:
        description: Natural language task description
        context: Optional additional context
        
    Returns:
        dict with keys: result, steps_taken, error
    """
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{DESKTOP_URL}/task",
                json={"description": description, "context": context}
            )
            response.raise_for_status()
            return response.json()
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error(f"Desktop service connection error: {e}")
        return {
            "result": "",
            "steps_taken": 0,
            "error": f"service_error: Desktop service unavailable - {str(e)}"
        }
    except Exception as e:
        logger.error(f"Desktop service error: {e}", exc_info=True)
        return {
            "result": "",
            "steps_taken": 0,
            "error": f"service_error: {str(e)}"
        }


async def cli_task(description: str, context: Optional[str] = None) -> dict:
    """
    Execute a CLI/PowerShell task via the CLI Module Service.
    
    Args:
        description: Natural language task description
        context: Optional additional context
        
    Returns:
        dict with keys: result, steps_taken, error
    """
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{CLI_URL}/task",
                json={"description": description, "context": context}
            )
            response.raise_for_status()
            return response.json()
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error(f"CLI service connection error: {e}")
        return {
            "result": "",
            "steps_taken": 0,
            "error": f"service_error: CLI service unavailable - {str(e)}"
        }
    except Exception as e:
        logger.error(f"CLI service error: {e}", exc_info=True)
        return {
            "result": "",
            "steps_taken": 0,
            "error": f"service_error: {str(e)}"
        }


async def browser_task(description: str, context: Optional[str] = None) -> dict:
    """
    Execute a browser automation task via the Browser Module Service.
    
    Args:
        description: Natural language task description
        context: Optional additional context
        
    Returns:
        dict with keys: result, steps_taken, error
    """
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{BROWSER_URL}/task",
                json={"description": description, "context": context}
            )
            response.raise_for_status()
            return response.json()
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error(f"Browser service connection error: {e}")
        return {
            "result": "",
            "steps_taken": 0,
            "error": f"service_error: Browser service unavailable - {str(e)}"
        }
    except Exception as e:
        logger.error(f"Browser service error: {e}", exc_info=True)
        return {
            "result": "",
            "steps_taken": 0,
            "error": f"service_error: {str(e)}"
        }
